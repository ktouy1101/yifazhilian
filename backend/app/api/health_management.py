"""M04: user-entered records and daily medication plans; no device/clinical alerts."""
from datetime import date as Date, datetime, time, timedelta, timezone
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field, field_validator, model_validator

from app.api.dependencies import consent_policy, get_database, owned_row, patient, require_consent
from app.db import Database, audit, new_id, utcnow
from app.schemas import StrictModel

router = APIRouter(prefix="/health-management")
LOCAL = timezone(timedelta(hours=8))


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def stamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("时间必须包含时区")
    return value.astimezone(timezone.utc).isoformat()


def past_time(value: datetime):
    stamp(value)
    if value > utcnow() + timedelta(minutes=5) or value.year < 1900:
        raise ValueError("请填写已经发生的真实时间")
    return value.astimezone(timezone.utc)


class EntryFields(StrictModel):
    kind: Literal["heart_rate", "spo2", "blood_pressure", "symptom"]
    source: Literal["manual", "report"] = "manual"
    measured_at: datetime
    value: float | None = Field(default=None, allow_inf_nan=False)
    secondary_value: float | None = Field(default=None, allow_inf_nan=False)
    title: str = Field(default="", max_length=80)
    note: str = Field(default="", max_length=1000)

    _time = field_validator("measured_at")(past_time)

    @model_validator(mode="after")
    def check_values(self):
        if self.kind == "symptom":
            if not self.title or not self.note or self.value is not None or self.secondary_value is not None or self.source != "manual":
                raise ValueError("身体感受请填写主题和描述，不填写测量值")
            return self
        upper = {"heart_rate": 350, "spo2": 100, "blood_pressure": 400}[self.kind]
        if self.value is None or not 0 < self.value <= upper:
            raise ValueError("请核对数值、单位和小数点；此检查不判断健康状态")
        if self.kind == "blood_pressure":
            if self.secondary_value is None or not 0 < self.secondary_value < self.value:
                raise ValueError("请同时填写收缩压和舒张压，收缩压应大于舒张压")
        elif self.secondary_value is not None:
            raise ValueError("此指标只填写一个测量值")
        return self


class EntryCreate(EntryFields):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")


class EntryUpdate(EntryFields):
    revision: int = Field(ge=1)


class PlanFields(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    strength: str = Field(default="", max_length=100)
    dose: str = Field(min_length=1, max_length=100)
    times: list[str] = Field(min_length=1, max_length=8)
    start_date: Date
    end_date: Date | None = None
    note: str = Field(default="", max_length=500)
    status: Literal["active", "paused", "ended"] = "active"

    @field_validator("times")
    @classmethod
    def valid_times(cls, values):
        import re
        if any(not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", item) for item in values):
            raise ValueError("每日时间请使用 HH:mm 格式")
        if len(set(values)) != len(values):
            raise ValueError("每日时间不能重复")
        return sorted(values)

    @model_validator(mode="after")
    def valid_dates(self):
        if self.start_date.year < 1900 or (self.end_date and self.end_date < self.start_date):
            raise ValueError("请核对计划起止日期")
        return self


class PlanCreate(PlanFields):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")


class PlanUpdate(PlanFields):
    revision: int = Field(ge=1)


class DoseInput(StrictModel):
    plan_id: str = Field(min_length=1, max_length=80)
    plan_revision: int = Field(ge=1)
    scheduled_at: datetime
    revision: int = Field(default=0, ge=0)
    status: Literal["taken", "skipped", "postponed", "pending"]
    actual_at: datetime | None = None
    postponed_until: datetime | None = None
    note: str = Field(default="", max_length=500)

    @field_validator("scheduled_at", "postponed_until")
    @classmethod
    def timezone_required(cls, value):
        if value is not None:
            stamp(value)
        return value

    @model_validator(mode="after")
    def valid_record(self):
        if self.status == "taken":
            if self.actual_at is None:
                raise ValueError("请填写实际服药时间")
            past_time(self.actual_at)
        elif self.actual_at is not None:
            raise ValueError("只有已服用记录可以填写实际服药时间")
        if self.status == "postponed":
            if self.postponed_until is None or self.postponed_until <= utcnow() or self.postponed_until > utcnow() + timedelta(days=1):
                raise ValueError("稍后处理时间应在未来24小时内")
        elif self.postponed_until is not None:
            raise ValueError("仅稍后处理可设置推迟时间")
        return self


class FollowupCreate(StrictModel):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    title: str = Field(min_length=1, max_length=100)
    due_at: datetime
    note: str = Field(default="", max_length=500)

    @field_validator("due_at")
    @classmethod
    def timezone_required(cls, value):
        stamp(value)
        if value.year < 1900:
            raise ValueError("请核对日期")
        return value


class FollowupUpdate(StrictModel):
    done: bool


def authorize(c, user):
    require_consent(c, user["id"], "vitals", consent_policy("vitals", None))


def entry_dict(row):
    return {**json.loads(row["payload"]), "id": row["id"], "revision": row["revision"],
            "created_at": row["created_at"], "updated_at": row["updated_at"],
            "unit": {"heart_rate": "bpm", "spo2": "%", "blood_pressure": "mmHg", "symptom": ""}[json.loads(row["payload"])["kind"]]}


def plan_dict(row):
    return {**json.loads(row["payload"]), "id": row["id"], "revision": row["revision"],
            "created_at": row["created_at"], "updated_at": row["updated_at"]}


def occurrence(plan_id, version, scheduled):
    p = json.loads(version["payload"])
    return {"key": plan_id + "|" + scheduled, "plan_id": plan_id, "plan_revision": version["revision"],
            "scheduled_at": scheduled, "name": p["name"], "strength": p.get("strength", ""),
            "dose": p["dose"], "plan_note": p.get("note", ""), "status": "pending",
            "actual_at": None, "postponed_until": None, "note": "", "revision": 0}


def dose_dict(row):
    return {**json.loads(row["snapshot"]), **{key: row[key] for key in
            ("status", "actual_at", "postponed_until", "note", "revision", "updated_at")}}


def day_doses(c, uid, day):
    """Compute schedule from time-bounded versions; saved reports retain their snapshot."""
    result = {}
    versions = c.execute("""SELECT v.* FROM health_plan_versions v JOIN health_medication_plans p
                            ON p.id=v.plan_id WHERE p.user_id=? ORDER BY v.effective_from""", (uid,))
    for version in versions:
        p = json.loads(version["payload"])
        if p["status"] != "active" or day.isoformat() < p["start_date"] or (p.get("end_date") and day.isoformat() > p["end_date"]):
            continue
        for clock in p["times"]:
            scheduled = stamp(datetime.combine(day, time.fromisoformat(clock), LOCAL))
            if scheduled < version["effective_from"] or (version["effective_until"] and scheduled >= version["effective_until"]):
                continue
            item = occurrence(version["plan_id"], version, scheduled)
            result[item["key"]] = item
    begin = stamp(datetime.combine(day, time.min, LOCAL))
    end = stamp(datetime.combine(day + timedelta(days=1), time.min, LOCAL))
    for row in c.execute("SELECT * FROM health_dose_logs WHERE user_id=? AND scheduled_at>=? AND scheduled_at<?", (uid, begin, end)):
        item = dose_dict(row)
        # Preserve reported history; don't revive cancelled future pending slots.
        if item["status"] in ("taken", "skipped") or row["scheduled_at"] <= utcnow().isoformat() or item["key"] in result:
            result[item["key"]] = item
    return sorted(result.values(), key=lambda item: (item["scheduled_at"], item["plan_id"]))


KIND_ORDER = ("heart_rate", "spo2", "blood_pressure", "symptom")
MEASUREMENT_KINDS = KIND_ORDER[:3]


def summary_payload(c, uid, days):
    """Period recap for a visit. Counts self-reports; never grades adherence."""
    today = utcnow().astimezone(LOCAL).date()
    start_day = today - timedelta(days=days - 1)
    start_at = stamp(datetime.combine(start_day, time.min, LOCAL))
    end_at = stamp(datetime.combine(today + timedelta(days=1), time.min, LOCAL))
    total = c.execute("SELECT count(*) FROM health_entries WHERE user_id=? AND measured_at>=? AND measured_at<?",
                      (uid, start_at, end_at)).fetchone()[0]
    rows = c.execute("SELECT * FROM health_entries WHERE user_id=? AND measured_at>=? AND measured_at<? "
                     "ORDER BY measured_at DESC,created_at DESC LIMIT 1000",
                     (uid, start_at, end_at)).fetchall()
    entries = [entry_dict(row) for row in rows]
    by_kind = {kind: 0 for kind in KIND_ORDER}
    latest_by_kind, symptom_items = {}, []
    for item in entries:
        kind = item["kind"]
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if kind == "symptom":
            symptom_items.append(item)
        elif kind not in latest_by_kind:
            latest_by_kind[kind] = item
    latest = [{key: latest_by_kind[kind].get(key) for key in
               ("id", "kind", "value", "secondary_value", "unit", "measured_at", "source")}
              for kind in MEASUREMENT_KINDS if kind in latest_by_kind]
    plans = c.execute("SELECT * FROM health_medication_plans WHERE user_id=? ORDER BY created_at", (uid,)).fetchall()
    doses, day = [], start_day
    while day <= today:
        doses.extend(day_doses(c, uid, day))
        day += timedelta(days=1)
    now = utcnow().isoformat()
    medication = {"plan_count": len(plans), "plans_in_period": 0, "total": 0, "due": 0,
                  "taken": 0, "skipped": 0, "postponed": 0, "unrecorded": 0, "upcoming": 0,
                  "by_plan": []}
    groups = {}
    for dose in doses:
        due = dose["scheduled_at"] <= now
        medication["total"] += 1
        if due:
            medication["due"] += 1
        status = dose["status"]
        if status in ("taken", "skipped", "postponed"):
            medication[status] += 1
        elif due:
            medication["unrecorded"] += 1
        else:
            medication["upcoming"] += 1
        # Keep the dose snapshot separate: a plan edited mid-period must not
        # aggregate the old and new dose into one line.
        group = groups.setdefault((dose["plan_id"], dose["dose"]), {
            "plan_id": dose["plan_id"], "name": dose["name"], "strength": dose.get("strength", ""),
            "dose": dose["dose"], "total": 0, "due": 0, "taken": 0, "skipped": 0,
            "postponed": 0, "unrecorded": 0, "upcoming": 0})
        group["total"] += 1
        if due:
            group["due"] += 1
        if status in ("taken", "skipped", "postponed"):
            group[status] += 1
        elif due:
            group["unrecorded"] += 1
        else:
            group["upcoming"] += 1
    medication["plans_in_period"] = len({group["plan_id"] for group in groups.values()})
    medication["by_plan"] = sorted(groups.values(), key=lambda item: (item["name"], item["dose"]))
    pending = c.execute("SELECT * FROM health_followups WHERE user_id=? AND done=0 ORDER BY due_at LIMIT 20",
                        (uid,)).fetchall()
    pending_count = c.execute("SELECT count(*) FROM health_followups WHERE user_id=? AND done=0",
                              (uid,)).fetchone()[0]
    return {
        "start": start_day.isoformat(), "end": today.isoformat(), "days": days,
        "timezone": "Asia/Shanghai", "generated_at": now,
        "entries": {"total": total, "truncated": total > len(entries), "by_kind": by_kind,
                    "latest": latest},
        "symptoms": {"count": len(symptom_items), "items": [
            {key: item.get(key) for key in ("id", "title", "measured_at")} for item in symptom_items[:20]]},
        "medication": medication,
        "followups": {"pending_count": pending_count, "items": [
            {key: row[key] for key in ("id", "title", "due_at")} for row in pending]},
    }


@router.get("/summary")
def visit_summary(days: int = Query(default=7, ge=1, le=90), user=Depends(patient),
                  database: Database = Depends(get_database)):
    with database.transaction() as c:
        authorize(c, user)
        return summary_payload(c, user["id"], days)


def latest_record(c, uid):
    """Latest archived M03 document, only when records_read is currently granted."""
    policy = consent_policy("records_read", None)
    active = c.execute(
        "SELECT 1 FROM consents WHERE user_id=? AND scope='records_read' AND granted=1 "
        "AND revoked_at IS NULL AND expires_at>? AND policy_version=? AND recipient=?",
        (uid, utcnow().isoformat(), policy["policy_version"], policy["recipient"])).fetchone()
    if not active:
        return None, 0
    rows = c.execute(
        "SELECT id,draft,updated_at FROM record_documents WHERE user_id=? AND status='archived'",
        (uid,)).fetchall()
    candidates = []
    for row in rows:
        try:
            draft = json.loads(row["draft"])
        except (TypeError, ValueError):
            continue
        candidates.append((draft.get("record_date") or "", row["updated_at"], row["id"], draft))
    if not candidates:
        return None, 0
    candidates.sort(reverse=True)
    _, updated_at, document_id, draft = candidates[0]
    fields = [{"name": field.get("name", ""), "result": field.get("result", ""),
               "unit": field.get("unit", ""), "reference": field.get("reference", ""),
               "confirmed": bool(field.get("confirmed"))}
              for field in (draft.get("fields") or []) if field.get("name") or field.get("result")]
    return {"id": document_id, "title": draft.get("title", ""), "record_type": draft.get("record_type", ""),
            "record_date": draft.get("record_date", ""), "institution": draft.get("institution", ""),
            "visit": draft.get("visit", ""), "updated_at": updated_at,
            "fields": fields[:12], "source": "record_document"}, len(candidates)


@router.get("/overview")
def overview(day: Date | None = Query(default=None), user=Depends(patient), database: Database = Depends(get_database)):
    day = day or utcnow().astimezone(LOCAL).date()
    if day > utcnow().astimezone(LOCAL).date() or day.year < 1900:
        raise HTTPException(422, "请选择今天或过去的记录日期")
    with database.transaction() as c:
        authorize(c, user)
        uid = user["id"]
        entries = c.execute("SELECT * FROM health_entries WHERE user_id=? ORDER BY measured_at DESC,created_at DESC LIMIT 300", (uid,)).fetchall()
        plans = c.execute("SELECT * FROM health_medication_plans WHERE user_id=? ORDER BY created_at DESC", (uid,)).fetchall()
        followups = c.execute("SELECT * FROM health_followups WHERE user_id=? ORDER BY done,due_at", (uid,)).fetchall()
        record, record_count = latest_record(c, uid)
        return {"day": day.isoformat(), "timezone": "Asia/Shanghai", "server_time": utcnow().isoformat(),
                "entries": [entry_dict(r) for r in entries],
                "entry_count": c.execute("SELECT count(*) FROM health_entries WHERE user_id=?", (uid,)).fetchone()[0],
                "plans": [plan_dict(r) for r in plans], "doses": day_doses(c, uid, day),
                "latest_record": record, "record_count": record_count,
                "followups": [{k: row[k] for k in ("id", "title", "due_at", "note", "done")} for row in followups]}


@router.post("/entries", status_code=201)
def create_entry(payload: EntryCreate, user=Depends(patient), database: Database = Depends(get_database)):
    data = payload.model_dump(mode="json", exclude={"request_id"})
    data["measured_at"] = stamp(payload.measured_at)
    with database.transaction(write=True) as c:
        authorize(c, user)
        row = c.execute("SELECT * FROM health_entries WHERE user_id=? AND request_id=?", (user["id"], payload.request_id)).fetchone()
        if row:
            if row["payload"] != encode(data):
                raise HTTPException(409, "该保存请求已用于不同记录，请重新载入")
            return entry_dict(row)
        rid, now = new_id("entry"), utcnow().isoformat()
        c.execute("INSERT INTO health_entries(id,user_id,request_id,payload,measured_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                  (rid, user["id"], payload.request_id, encode(data), data["measured_at"], now, now))
        audit(c, user["id"], "health_entry_created", rid)
        return entry_dict(c.execute("SELECT * FROM health_entries WHERE id=?", (rid,)).fetchone())


@router.put("/entries/{entry_id}")
def update_entry(entry_id: str, payload: EntryUpdate, user=Depends(patient), database: Database = Depends(get_database)):
    data = payload.model_dump(mode="json", exclude={"revision"})
    data["measured_at"] = stamp(payload.measured_at)
    with database.transaction(write=True) as c:
        authorize(c, user)
        row = owned_row(c.execute("SELECT * FROM health_entries WHERE id=? AND user_id=?", (entry_id, user["id"])).fetchone())
        if row["revision"] != payload.revision:
            if row["payload"] == encode(data):
                return entry_dict(row)
            raise HTTPException(409, "记录已变化，请重新载入后核对")
        c.execute("UPDATE health_entries SET payload=?,measured_at=?,revision=revision+1,updated_at=? WHERE id=?",
                  (encode(data), data["measured_at"], utcnow().isoformat(), entry_id))
        audit(c, user["id"], "health_entry_corrected", entry_id)
        return entry_dict(c.execute("SELECT * FROM health_entries WHERE id=?", (entry_id,)).fetchone())


@router.delete("/entries/{entry_id}")
def delete_entry(entry_id: str, revision: int = Query(ge=1), user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction(write=True) as c:
        authorize(c, user)
        row = owned_row(c.execute("SELECT * FROM health_entries WHERE id=? AND user_id=?", (entry_id, user["id"])).fetchone())
        if row["revision"] != revision:
            raise HTTPException(409, "记录已变化，请刷新后重试")
        c.execute("DELETE FROM health_entries WHERE id=?", (entry_id,))
        audit(c, user["id"], "health_entry_deleted", entry_id)
    return {"deleted": True}


@router.post("/plans", status_code=201)
def create_plan(payload: PlanCreate, user=Depends(patient), database: Database = Depends(get_database)):
    data = payload.model_dump(mode="json", exclude={"request_id"})
    with database.transaction(write=True) as c:
        authorize(c, user)
        row = c.execute("SELECT * FROM health_medication_plans WHERE user_id=? AND request_id=?", (user["id"], payload.request_id)).fetchone()
        if row:
            if row["payload"] != encode(data):
                raise HTTPException(409, "该保存请求已用于不同计划，请重新载入")
            return plan_dict(row)
        pid, now = new_id("plan"), utcnow().isoformat()
        c.execute("INSERT INTO health_medication_plans(id,user_id,request_id,payload,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                  (pid, user["id"], payload.request_id, encode(data), now, now))
        effective = stamp(datetime.combine(payload.start_date, time.min, LOCAL))
        c.execute("INSERT INTO health_plan_versions(plan_id,revision,payload,effective_from) VALUES(?,1,?,?)", (pid, encode(data), effective))
        audit(c, user["id"], "medication_plan_created", pid)
        return plan_dict(c.execute("SELECT * FROM health_medication_plans WHERE id=?", (pid,)).fetchone())


@router.put("/plans/{plan_id}")
def update_plan(plan_id: str, payload: PlanUpdate, user=Depends(patient), database: Database = Depends(get_database)):
    data = payload.model_dump(mode="json", exclude={"revision"})
    with database.transaction(write=True) as c:
        authorize(c, user)
        row = owned_row(c.execute("SELECT * FROM health_medication_plans WHERE id=? AND user_id=?", (plan_id, user["id"])).fetchone())
        if row["revision"] != payload.revision:
            if row["payload"] == encode(data):
                return plan_dict(row)
            raise HTTPException(409, "计划已变化，请重新载入后核对")
        now, revision = utcnow().isoformat(), row["revision"] + 1
        # Pending future tasks are derived from the new plan, not historical reports.
        c.execute("DELETE FROM health_dose_logs WHERE plan_id=? AND scheduled_at>=? AND status IN ('pending','postponed')", (plan_id, now))
        c.execute("UPDATE health_plan_versions SET effective_until=? WHERE plan_id=? AND effective_until IS NULL", (now, plan_id))
        c.execute("INSERT INTO health_plan_versions(plan_id,revision,payload,effective_from) VALUES(?,?,?,?)", (plan_id, revision, encode(data), now))
        c.execute("UPDATE health_medication_plans SET payload=?,revision=?,updated_at=? WHERE id=?", (encode(data), revision, now, plan_id))
        audit(c, user["id"], "medication_plan_updated", plan_id)
        return plan_dict(c.execute("SELECT * FROM health_medication_plans WHERE id=?", (plan_id,)).fetchone())


@router.delete("/plans/{plan_id}")
def delete_plan(plan_id: str, revision: int = Query(ge=1), user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction(write=True) as c:
        authorize(c, user)
        row = owned_row(c.execute("SELECT * FROM health_medication_plans WHERE id=? AND user_id=?", (plan_id, user["id"])).fetchone())
        if row["revision"] != revision:
            raise HTTPException(409, "计划已变化，请刷新后重试")
        c.execute("DELETE FROM health_medication_plans WHERE id=?", (plan_id,))
        # Migrated legacy plans must not remain accessible through the old API.
        c.execute("DELETE FROM medications WHERE id=? AND user_id=?", (plan_id, user["id"]))
        audit(c, user["id"], "medication_plan_and_logs_deleted", plan_id)
    return {"deleted": True}


@router.put("/doses")
def record_dose(payload: DoseInput, user=Depends(patient), database: Database = Depends(get_database)):
    scheduled = stamp(payload.scheduled_at)
    day = payload.scheduled_at.astimezone(LOCAL).date()
    if day > utcnow().astimezone(LOCAL).date():
        raise HTTPException(422, "不能提前确认未来日期的服药记录")
    actual = stamp(payload.actual_at) if payload.actual_at else None
    postponed = stamp(payload.postponed_until) if payload.postponed_until else None
    with database.transaction(write=True) as c:
        authorize(c, user)
        owned_row(c.execute("SELECT id FROM health_medication_plans WHERE id=? AND user_id=?", (payload.plan_id, user["id"])).fetchone())
        previous = c.execute("SELECT * FROM health_dose_logs WHERE user_id=? AND plan_id=? AND scheduled_at=?", (user["id"], payload.plan_id, scheduled)).fetchone()
        item = next((d for d in day_doses(c, user["id"], day) if d["plan_id"] == payload.plan_id and d["scheduled_at"] == scheduled), None)
        if item is None or item["plan_revision"] != payload.plan_revision:
            raise HTTPException(409, "此时段的计划已变化，请重新载入核对")
        if previous:
            if previous["revision"] != payload.revision:
                if (previous["status"], previous["actual_at"], previous["postponed_until"], previous["note"]) == (payload.status, actual, postponed, payload.note):
                    return dose_dict(previous)
                raise HTTPException(409, "服药记录已变化，请刷新后再确认")
            c.execute("UPDATE health_dose_logs SET status=?,actual_at=?,postponed_until=?,note=?,revision=revision+1,updated_at=? WHERE id=?",
                      (payload.status, actual, postponed, payload.note, utcnow().isoformat(), previous["id"]))
            rid = previous["id"]
        else:
            if payload.revision != 0:
                raise HTTPException(409, "服药记录已变化，请刷新")
            rid = new_id("dose")
            c.execute("""INSERT INTO health_dose_logs(id,user_id,plan_id,scheduled_at,snapshot,status,actual_at,postponed_until,note,updated_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?)""", (rid, user["id"], payload.plan_id, scheduled, encode(item), payload.status, actual, postponed, payload.note, utcnow().isoformat()))
        audit(c, user["id"], "medication_self_reported", rid)
        return dose_dict(c.execute("SELECT * FROM health_dose_logs WHERE id=?", (rid,)).fetchone())


@router.post("/followups", status_code=201)
def create_followup(payload: FollowupCreate, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction(write=True) as c:
        authorize(c, user)
        previous = c.execute("SELECT * FROM health_followups WHERE user_id=? AND request_id=?", (user["id"], payload.request_id)).fetchone()
        if previous:
            if (previous["title"], previous["due_at"], previous["note"]) != (payload.title, stamp(payload.due_at), payload.note):
                raise HTTPException(409, "该保存请求已用于不同待办")
            return {"id": previous["id"]}
        rid = new_id("followup")
        c.execute("INSERT INTO health_followups(id,user_id,request_id,title,due_at,note,created_at) VALUES(?,?,?,?,?,?,?)",
                  (rid, user["id"], payload.request_id, payload.title, stamp(payload.due_at), payload.note, utcnow().isoformat()))
        audit(c, user["id"], "health_followup_created", rid)
        return {"id": rid}


@router.patch("/followups/{followup_id}")
def update_followup(followup_id: str, payload: FollowupUpdate, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction(write=True) as c:
        authorize(c, user)
        owned_row(c.execute("SELECT id FROM health_followups WHERE id=? AND user_id=?", (followup_id, user["id"])).fetchone())
        c.execute("UPDATE health_followups SET done=? WHERE id=?", (int(payload.done), followup_id))
        audit(c, user["id"], "health_followup_updated", followup_id)
    return {"done": payload.done}


@router.delete("/followups/{followup_id}")
def delete_followup(followup_id: str, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction(write=True) as c:
        authorize(c, user)
        owned_row(c.execute("SELECT id FROM health_followups WHERE id=? AND user_id=?", (followup_id, user["id"])).fetchone())
        c.execute("DELETE FROM health_followups WHERE id=?", (followup_id,))
        audit(c, user["id"], "health_followup_deleted", followup_id)
    return {"deleted": True}
