from datetime import timedelta
from secrets import token_urlsafe
from fastapi import APIRouter, Depends, HTTPException
from app.api.dependencies import current_user, get_database, owned_row, patient, require_consent
from app.config import CONSENT_TTL_SECONDS, DISCLAIMER, TOKEN_TTL_SECONDS
from app.db import (Database, audit, consent_dict, conversation_dict, emergency_dict,
                    new_id, token_hash, user_dict, utcnow, vital_dict)
from app.schemas import (ConsentInput, ConversationInput, DemoLogin,
                         EmergencyInput, MessageInput, Scope, VitalInput)
from app.services.rag import respond
from app.services.vitals import alert_for, validate_vital

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok", "mode": "demo", "synthetic_only": True,
            "external_network": False, "storage": "sqlite_local"}


@router.post("/auth/demo-login")
def demo_login(payload: DemoLogin, database: Database = Depends(get_database)):
    alias = payload.demo_alias or ("demo-patient-001" if payload.role == "patient" else "demo-volunteer-001")
    with database.transaction(write=True) as connection:
        row = connection.execute("SELECT * FROM users WHERE id=? AND role=?", (alias, payload.role)).fetchone()
        if row is None:
            raise HTTPException(422, "仅支持固定的合成演示账号，不接收openid或真实患者标识")
        user = user_dict(row)
        token = token_urlsafe(32)
        connection.execute("INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)",
                           (token_hash(token), user["id"], utcnow().isoformat(),
                            (utcnow() + timedelta(seconds=TOKEN_TTL_SECONDS)).isoformat()))
        audit(connection, user["id"], "demo_login", user["id"])
    return {"access_token": token, "token_type": "bearer", "expires_in": TOKEN_TTL_SECONDS,
            "user": user, "notice": "公开演示身份选择器，不能用于真实身份认证"}


@router.get("/users/me")
def me(user=Depends(current_user)):
    return user


@router.get("/consents")
def list_consents(user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        return {"items": [consent_dict(connection, row) for row in connection.execute(
            "SELECT * FROM consents WHERE user_id=? ORDER BY scope", (user["id"],))]}


@router.post("/consents", status_code=201)
def grant_consent(payload: ConsentInput, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction(write=True) as connection:
        now = utcnow()
        connection.execute(
            """INSERT INTO consents(id,user_id,scope,granted,policy_version,recipient,purpose,created_at,expires_at,revoked_at)
               VALUES(?,?,?,1,'demo-1','local_demo_process',?,?,?,NULL)
               ON CONFLICT(user_id,scope) DO UPDATE SET granted=1,policy_version=excluded.policy_version,
               recipient=excluded.recipient,purpose=excluded.purpose,created_at=excluded.created_at,
               expires_at=excluded.expires_at,revoked_at=NULL""",
            (new_id("consent"), user["id"], payload.scope, payload.scope, now.isoformat(),
             (now + timedelta(seconds=CONSENT_TTL_SECONDS)).isoformat()))
        row = connection.execute("SELECT * FROM consents WHERE user_id=? AND scope=?", (user["id"], payload.scope)).fetchone()
        fields = {"ai_medical": ["synthetic_question"], "ai_legal": ["synthetic_question"],
                  "vitals": ["synthetic_vital_value", "sample_time"], "records_read": ["synthetic_record"]}[payload.scope]
        connection.execute("DELETE FROM consent_fields WHERE consent_id=?", (row["id"],))
        connection.executemany("INSERT INTO consent_fields(consent_id,field_name) VALUES(?,?)",
                               [(row["id"], field) for field in fields])
        audit(connection, user["id"], "consent_granted", row["id"])
        return consent_dict(connection, row)


@router.delete("/consents/{scope}")
def revoke_consent(scope: Scope, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction(write=True) as connection:
        connection.execute("UPDATE consents SET granted=0,revoked_at=? WHERE user_id=? AND scope=?",
                           (utcnow().isoformat(), user["id"], scope))
        audit(connection, user["id"], "consent_revoked", scope)
    return {"scope": scope, "granted": False, "effective": "immediate_next_request",
            "notice": "撤回阻断后续处理；已存记录按留存政策处理。此本地演示保留历史，重启不会清空。"}


@router.post("/conversations", status_code=201)
def create_conversation(payload: ConversationInput, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction(write=True) as connection:
        require_consent(connection, user["id"], f"ai_{payload.domain}")
        cid = new_id("chat")
        connection.execute("INSERT INTO conversations(id,user_id,domain,created_at) VALUES(?,?,?,?)",
                           (cid, user["id"], payload.domain, utcnow().isoformat()))
        audit(connection, user["id"], "conversation_created", cid)
        return conversation_dict(connection, connection.execute("SELECT * FROM conversations WHERE id=? AND user_id=?", (cid, user["id"])).fetchone())


@router.get("/conversations/{conversation_id}")
def get_conversation(conversation_id: str, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        row = owned_row(connection.execute("SELECT * FROM conversations WHERE id=? AND user_id=?", (conversation_id, user["id"])).fetchone())
        require_consent(connection, user["id"], f"ai_{row['domain']}")
        return conversation_dict(connection, row)


@router.post("/conversations/{conversation_id}/messages")
def send_message(conversation_id: str, payload: MessageInput, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction(write=True) as connection:
        row = owned_row(connection.execute("SELECT * FROM conversations WHERE id=? AND user_id=?", (conversation_id, user["id"])).fetchone())
        require_consent(connection, user["id"], f"ai_{row['domain']}")
        # Only the immediate local mock runs here. Future slow/network providers
        # need an outbox with a second authorization check before delivery.
        result = respond(row["domain"], payload.text)
        result.update({"role": "assistant", "disclaimer": DISCLAIMER})
        now = utcnow().isoformat()
        connection.execute("INSERT INTO messages(conversation_id,role,text,created_at) VALUES(?,'user',?,?)",
                           (conversation_id, payload.text, now))
        mid = connection.execute(
            "INSERT INTO messages(conversation_id,role,text,provider,retrieval,disclaimer,created_at) VALUES(?,'assistant',?,?,?,?,?)",
            (conversation_id, result["answer"], result["provider"], result["retrieval"], result["disclaimer"], now)).lastrowid
        connection.executemany(
            "INSERT INTO message_sources(message_id,position,source_id,domain,title,text,url) VALUES(?,?,?,?,?,?,?)",
            [(mid, index, source["id"], source["domain"], source["title"], source["text"], source["url"])
             for index, source in enumerate(result["sources"])])
        audit(connection, user["id"], "conversation_answered", conversation_id)
        return result


@router.get("/records")
def list_records(user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        require_consent(connection, user["id"], "records_read")
        return {"items": [{"id": "synthetic-record-001", "patient_display": "合成患者",
                           "summary": "仅占位演示病历，无真实诊断", "synthetic": True}], "ocr": "not_implemented"}


@router.get("/medications")
def medications(user=Depends(patient)):
    return {"items": [{"id": "synthetic-med-001", "name": "演示药品A（虚构）", "scheduled_time": "08:00",
                       "dose": "请以主管医护医嘱为准", "synthetic": True}], "notice": "此列表为界面占位，无真实处方功能"}


@router.get("/vitals")
def list_vitals(user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        require_consent(connection, user["id"], "vitals")
        return {"items": [vital_dict(row) for row in connection.execute("SELECT * FROM vitals WHERE user_id=? ORDER BY created_at", (user["id"],))]}


@router.post("/vitals", status_code=201)
def upload_vital(payload: VitalInput, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction(write=True) as connection:
        require_consent(connection, user["id"], "vitals")
        previous = connection.execute("SELECT * FROM vitals WHERE user_id=? AND source=? AND sample_id=?",
                                      (user["id"], payload.source, payload.sample_id)).fetchone()
        if previous:
            result = vital_dict(previous)
            if result["sample"] != payload.model_dump(mode="json"):
                raise HTTPException(409, "同一sample_id不能覆盖不同采样内容")
            return result
        validate_vital(payload)
        alert = alert_for(payload)
        vid = new_id("vital")
        connection.execute(
            """INSERT INTO vitals(id,user_id,sample_id,source,kind,value,unit,measured_at,quality,alert_status,alert_message,created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (vid, user["id"], payload.sample_id, payload.source, payload.kind, payload.value, payload.unit,
             payload.model_dump(mode="json")["measured_at"], payload.quality, alert["status"], alert["message"], utcnow().isoformat()))
        audit(connection, user["id"], "vital_received", vid)
        return vital_dict(connection.execute("SELECT * FROM vitals WHERE id=? AND user_id=?", (vid, user["id"])).fetchone())


@router.post("/emergencies", status_code=201)
def create_emergency(payload: EmergencyInput, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction(write=True) as connection:
        previous = connection.execute("SELECT * FROM emergency_events WHERE user_id=? AND idempotency_key=?",
                                      (user["id"], payload.idempotency_key)).fetchone()
        if previous:
            return emergency_dict(previous)
        eid = new_id("sos")
        connection.execute(
            """INSERT INTO emergency_events(id,user_id,idempotency_key,status,delivery,created_at,acknowledged_at,message)
               VALUES(?,?,?,'received','mock',?,NULL,?)""",
            (eid, user["id"], payload.idempotency_key, utcnow().isoformat(),
             "只记录演示事件，未拨号、未通知、无人确认。请直接联系病区医护或使用实体呼叫铃。"))
        audit(connection, user["id"], "emergency_demo_received", eid)
        return emergency_dict(connection.execute("SELECT * FROM emergency_events WHERE id=? AND user_id=?", (eid, user["id"])).fetchone())


@router.get("/emergencies/{event_id}")
def get_emergency(event_id: str, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        return emergency_dict(owned_row(connection.execute("SELECT * FROM emergency_events WHERE id=? AND user_id=?", (event_id, user["id"])).fetchone()))


@router.get("/audit-events")
def audit_events(user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        return {"items": [dict(row) for row in connection.execute(
            "SELECT id,user_id,action,object_id,created_at FROM audit_events WHERE user_id=? ORDER BY created_at", (user["id"],))],
                "durable": True, "tamper_evident": False}
