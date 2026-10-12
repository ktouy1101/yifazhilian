"""Local relational SQLite storage. UNENCRYPTED: synthetic teaching data only."""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import os
from pathlib import Path
import sqlite3
from threading import Lock
from uuid import uuid4

DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "yifazhilian.db"


def database_path() -> Path:
    return Path(os.getenv("YIFAZHILIAN_DB_PATH", str(DEFAULT_DB_PATH))).expanduser().resolve()


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def token_hash(token: str) -> str:
    # Random 256-bit opaque tokens, not low-entropy passwords.
    return sha256(token.encode("utf-8")).hexdigest()


class Database:
    """Lazy connection factory; each transaction closes its thread-local connection."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path).resolve() if path is not None else database_path()
        self._initialized = False
        self._initialization_lock = Lock()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA synchronous = FULL")
        return connection

    def initialize(self):
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
                if version not in (0, 1):
                    raise RuntimeError(f"Unsupported database schema version: {version}")
                connection.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
                connection.execute("BEGIN IMMEDIATE")
                connection.executemany(
                    "INSERT OR IGNORE INTO users(id,role,display_name,synthetic) VALUES(?,?,?,1)",
                    [("demo-patient-001", "patient", "合成患者 001"),
                     ("demo-patient-002", "patient", "合成患者 002"),
                     ("demo-volunteer-001", "volunteer", "演示志愿者")])
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
    result.update(granted=bool(row["granted"]), synthetic_only=True)
    result["fields"] = [value[0] for value in connection.execute(
        "SELECT field_name FROM consent_fields WHERE consent_id=? ORDER BY field_name", (row["id"],))]
    return result


def conversation_dict(connection, row):
    messages = []
    for message in connection.execute("SELECT * FROM messages WHERE conversation_id=? ORDER BY id", (row["id"],)):
        if message["role"] == "user":
            messages.append({"role": "user", "text": message["text"]})
        else:
            sources = [dict(source) for source in connection.execute(
                "SELECT source_id AS id,domain,title,text,url FROM message_sources WHERE message_id=? ORDER BY position", (message["id"],))]
            messages.append({"role": "assistant", "answer": message["text"], "provider": message["provider"],
                             "retrieval": message["retrieval"], "disclaimer": message["disclaimer"], "sources": sources})
    return {"id": row["id"], "user_id": row["user_id"], "domain": row["domain"],
            "created_at": row["created_at"], "messages": messages, "synthetic_only": True}


def vital_dict(row):
    return {"id": row["id"], "user_id": row["user_id"], "created_at": row["created_at"], "synthetic": True,
            "sample": {key: row[key] for key in ("sample_id", "source", "kind", "value", "unit", "measured_at", "quality")},
            "alert": {"status": row["alert_status"], "clinical": False, "message": row["alert_message"]}}


def emergency_dict(row):
    return {key: row[key] for key in ("id", "user_id", "status", "delivery", "created_at", "acknowledged_at", "message")} | {"contact_attempts": []}
