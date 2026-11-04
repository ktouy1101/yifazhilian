"""Local relational SQLite storage. UNENCRYPTED: synthetic teaching data only."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import re
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
from threading import Lock
from uuid import uuid4

DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "yifazhilian.db"
PUBLIC_METADATA_KEYS = frozenset({
    "category", "topic", "topic_key", "materials", "next_steps", "external_ai",
})


def database_path() -> Path:
    return Path(os.getenv("YIFAZHILIAN_DB_PATH", str(DEFAULT_DB_PATH))).expanduser().resolve()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def column_exists(connection, table: str, column: str) -> bool:
    return any(row[1] == column for row in connection.execute(f"PRAGMA table_info({table})"))


def token_hash(token: str) -> str:
    # Random 256-bit opaque tokens, not low-entropy passwords.
    return sha256(token.encode("utf-8")).hexdigest()


class Database:
    """Lazy connection factory; each transaction closes its thread-local connection."""

    def __init__(self, path: str | Path | None = None):
        self.mysql_url = os.getenv("YIFAZHILIAN_DB_URL", "").strip()
        if self.mysql_url and not self.mysql_url.startswith("mysql://"):
            raise RuntimeError("YIFAZHILIAN_DB_URL 只支持 mysql:// 连接串")
        self.path = Path(path).resolve() if path is not None else database_path()
        self._initialized = False
        self._initialization_lock = Lock()

    def _connect(self):
        if self.mysql_url:
            from app import mysql_adapter
            return mysql_adapter.connect(self.mysql_url)
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def initialize(self):
        if self._initialized:
            return
        if self.mysql_url:
            with self._initialization_lock:
                if self._initialized:
                    return
                self._initialize_mysql()
            return
        self._initialize_sqlite()

    def _initialize_mysql(self):
        from app import mysql_adapter
        mysql_adapter.ensure_database(self.mysql_url)
        connection = mysql_adapter.connect(self.mysql_url)
        try:
            schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
            connection.executescript(schema)
            connection.executemany(
                "INSERT OR IGNORE INTO schema_meta(k,v) VALUES(?,?)", [("user_version", "12")])
            connection.commit()
            self._seed_mysql(connection)
            connection.commit()
            self._initialized = True
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _seed_mysql(self, connection):
        """演示种子数据；两个数据库共用同一份声明。"""
        from app.services.knowledge import seed_knowledge
        now = utcnow().isoformat()
        connection.executemany(
            "INSERT OR IGNORE INTO users(id,role,display_name,synthetic) VALUES(?,?,?,1)",
            [("demo-patient-001", "patient", "合成患者 001"),
             ("demo-patient-002", "patient", "合成患者 002"),
             ("demo-volunteer-001", "volunteer", "演示志愿者"),
             ("demo-reviewer-001", "volunteer", "演示审核员")])
        connection.executemany(
            "INSERT OR IGNORE INTO navigation_memberships(user_id,can_collect,can_review) VALUES(?,?,?)",
            [("demo-patient-001", 0, 0), ("demo-patient-002", 0, 0),
             ("demo-volunteer-001", 1, 0), ("demo-reviewer-001", 0, 1)])
        connection.executemany(
            "INSERT OR IGNORE INTO user_roles(user_id,role,granted_at) VALUES(?,?,?)",
            [("demo-volunteer-001", "volunteer", now), ("demo-reviewer-001", "reviewer", now)])
        connection.executemany(
            """INSERT OR IGNORE INTO navigation_tasks(id,title,description,floor,status,created_at)
               VALUES(?,?,?,?, 'open', ?)""",
            [("task-lab-a", "门诊楼一层：大厅→检验科",
              "从门诊大厅导诊台出发，沿指示牌到检验科入口，记录转弯、地标与电梯/楼梯。",
              "门诊1层", now),
             ("task-pharmacy-b", "住院楼一层：心内科病房→西药房",
              "从心内科护士站出发到住院楼一层西药房，注意无障碍通道与单向门。",
              "住院1层", now)])
        seed_knowledge(connection)

    def _initialize_sqlite(self):
        if self._initialized:
            return
        with self._initialization_lock:
            if self._initialized:
                return
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = self._connect()
            try:
                connection.execute("PRAGMA journal_mode = WAL")
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version not in (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12):
                    raise RuntimeError(f"Unsupported database schema version: {version}")
                connection.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
                # Migration v1 -> v2: existing databases add the openid column.
                # SQLite cannot ADD COLUMN with a UNIQUE constraint; use a partial unique index.
                if not column_exists(connection, "users", "openid"):
                    connection.execute("ALTER TABLE users ADD COLUMN openid TEXT")
                    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_openid ON users(openid) WHERE openid IS NOT NULL")
                if not column_exists(connection, "users", "phone"):
                    connection.execute("ALTER TABLE users ADD COLUMN phone TEXT")
                    connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_phone ON users(phone) WHERE phone IS NOT NULL")
                if not column_exists(connection, "user_profiles", "doctor_phone"):
                    connection.execute("ALTER TABLE user_profiles ADD COLUMN doctor_phone TEXT")
                # Migration v9 -> v10: soft delete. Accounts are never hard-deleted, so
                # audit rows keep pointing at a real user and orphan rows cannot appear.
                if not column_exists(connection, "users", "deleted_at"):
                    connection.execute("ALTER TABLE users ADD COLUMN deleted_at TEXT")
                # Migration v11 -> v12: password login. Existing accounts keep NULL
                # until a password is set through the API or an admin.
                if not column_exists(connection, "users", "password_hash"):
                    connection.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")
                # Source cards were removed from the chat UI and API; drop the
                # legacy citation table so old databases do not keep a dead copy.
                connection.execute("DROP TABLE IF EXISTS message_sources")
                connection.execute("BEGIN IMMEDIATE")
                if version < 7:
                    # Preserve legacy self-entered medicines as paused plans for review.
                    # Do not convert synthetic device readings into real manual entries.
                    migrated_at = utcnow().isoformat()
                    for legacy in connection.execute("SELECT * FROM medications").fetchall():
                        clock = (legacy["scheduled_time"] or "").strip()
                        if re.fullmatch(r"\d:[0-5]\d", clock):
                            clock = "0" + clock
                        times = [clock] if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", clock) else []
                        data = {"name": legacy["name"], "strength": "", "dose": legacy["dose"] or "",
                                "times": times, "start_date": utcnow().astimezone(timezone(timedelta(hours=8))).date().isoformat(),
                                "end_date": None, "note": legacy["note"] or "", "status": "paused"}
                        encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                        connection.execute("INSERT OR IGNORE INTO health_medication_plans(id,user_id,request_id,payload,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                                           (legacy["id"], legacy["user_id"], "legacy_" + legacy["id"], encoded, legacy["created_at"], migrated_at))
                        connection.execute("INSERT OR IGNORE INTO health_plan_versions(plan_id,revision,payload,effective_from) VALUES(?,1,?,?)",
                                           (legacy["id"], encoded, migrated_at))
                connection.executemany(
                    "INSERT OR IGNORE INTO users(id,role,display_name,synthetic) VALUES(?,?,?,1)",
                    [("demo-patient-001", "patient", "合成患者 001"),
                     ("demo-patient-002", "patient", "合成患者 002"),
                     ("demo-volunteer-001", "volunteer", "演示志愿者"),
                     ("demo-reviewer-001", "volunteer", "演示审核员")])
                # 导航角色：采集者与审核员分离；普通患者默认可浏览/反馈。
                connection.executemany(
                    "INSERT OR IGNORE INTO navigation_memberships(user_id,can_collect,can_review) VALUES(?,?,?)",
                    [("demo-patient-001", 0, 0),
                     ("demo-patient-002", 0, 0),
                     ("demo-volunteer-001", 1, 0),
                     ("demo-reviewer-001", 0, 1)])
                # 两条示例采集任务，覆盖一条短路线。
                now = utcnow().isoformat()
                # v9：能力位与 users.role 分离。演示审核员的 reviewer 能力来自这里，
                # 与 navigation_memberships.can_review 并存，历史数据不受影响。
                connection.executemany(
                    "INSERT OR IGNORE INTO user_roles(user_id,role,granted_at) VALUES(?,?,?)",
                    [("demo-volunteer-001", "volunteer", now),
                     ("demo-reviewer-001", "reviewer", now)])
                connection.executemany(
                    """INSERT OR IGNORE INTO navigation_tasks(id,title,description,floor,status,created_at)
                       VALUES(?,?,?,?, 'open', ?)""",
                    [("task-lab-a", "门诊楼一层：大厅→检验科",
                      "从门诊大厅导诊台出发，沿指示牌到检验科入口，记录转弯、地标与电梯/楼梯。",
                      "门诊1层", now),
                     ("task-pharmacy-b", "住院楼一层：心内科病房→西药房",
                      "从心内科护士站出发到住院楼一层西药房，注意无障碍通道与单向门。",
                      "住院1层", now)])
                from app.services.knowledge import seed_knowledge
                seed_knowledge(connection)
                connection.execute("PRAGMA user_version = 12")
                connection.commit()
                self._initialized = True
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

    @contextmanager
    def transaction(self, *, write: bool = False):
        self.initialize()
        connection = self._connect()
        try:
            # Consent read and mutation have one serial commit order.
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def audit(connection, user_id: str, action: str, object_id: str):
    connection.execute(
        "INSERT INTO audit_events(id,user_id,action,object_id,created_at) VALUES(?,?,?,?,?)",
        (new_id("audit"), user_id, action, object_id, utcnow().isoformat()))


def user_dict(row):
    return {"id": row["id"], "role": row["role"], "display_name": row["display_name"],
            "synthetic": bool(row["synthetic"])}


def consent_dict(connection, row):
    result = {key: row[key] for key in ("id", "user_id", "scope", "policy_version", "recipient", "purpose", "created_at", "expires_at", "revoked_at")}
    result.update(granted=bool(row["granted"]), synthetic_only=not (
        (row["scope"] == "records_read" and row["policy_version"] == "records-local-3") or
        (row["scope"] == "vitals" and row["policy_version"] == "health-records-1")))
    result["fields"] = [value[0] for value in connection.execute(
        "SELECT field_name FROM consent_fields WHERE consent_id=? ORDER BY field_name", (row["id"],))]
    return result


def conversation_dict(connection, row):
    messages = []
    for message in connection.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (row["id"],)):
        if message["role"] == "user":
            messages.append({"role": "user", "text": message["text"]})
        else:
            entry = {"role": "assistant", "answer": message["text"], "provider": message["provider"],
                     "retrieval": message["retrieval"], "disclaimer": message["disclaimer"]}
            metadata = connection.execute(
                "SELECT data FROM message_metadata WHERE message_id=?", (message["id"],)).fetchone()
            if metadata is not None:
                try:
                    stored = json.loads(metadata["data"])
                    entry.update({key: value for key, value in stored.items() if key in PUBLIC_METADATA_KEYS})
                except (TypeError, ValueError):
                    pass
            messages.append(entry)
    return {"id": row["id"], "user_id": row["user_id"], "domain": row["domain"],
            "created_at": row["created_at"], "messages": messages, "synthetic_only": True}


def vital_dict(row):
    return {"id": row["id"], "user_id": row["user_id"], "created_at": row["created_at"], "synthetic": True,
            "sample": {key: row[key] for key in ("sample_id", "source", "kind", "value", "unit", "measured_at", "quality")},
            "alert": {"status": row["alert_status"], "clinical": False, "message": row["alert_message"]}}


def emergency_dict(row):
    return {key: row[key] for key in ("id", "user_id", "status", "delivery", "created_at", "acknowledged_at", "message")} | {"contact_attempts": []}
