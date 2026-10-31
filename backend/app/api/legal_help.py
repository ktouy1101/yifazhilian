"""P4: 法律帮扶 —— 律师凭证、求助工单与异步回复。

隐私边界：工单只传问题文本，不接收病历、身份标识或手机号；凭证图片存私有
BLOB，只有本人和审核员能通过鉴权接口读取。
"""
from io import BytesIO

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from PIL import Image, UnidentifiedImageError

from app.api.dependencies import current_user, get_database, patient, require_reviewer
from app.db import Database, audit, new_id, utcnow
from app.schemas import CredentialReviewInput, LegalHelpCreate, LegalHelpMessageInput
from app.services import roles

router = APIRouter(tags=["legal-help"])

MAX_IMAGE_BYTES = 4 * 1024 * 1024
CREDENTIAL_KINDS = ("lawyer_license", "legal_aid")


def _can_help_legal(connection, user) -> bool:
    return roles.capabilities(connection, user)["can_help_legal"]


def _ensure_legal_intent(connection, user_id):
    """提交凭证即视为愿意做法律志愿者；没有档案时建一份待审档案。"""
    row = roles.volunteer_profile(connection, user_id)
    now = utcnow().isoformat()
    if row is None:
        connection.execute(
            "INSERT INTO volunteer_profiles(user_id,hospital_id,kinds,real_name,status,updated_at) "
            "VALUES(?,?,?,?,?,?)", (user_id, "demo-hospital", "legal", None, "pending", now))
        return
    kinds = [item for item in (row["kinds"] or "").split(",") if item]
    if "legal" not in kinds:
        kinds.append("legal")
        connection.execute("UPDATE volunteer_profiles SET kinds=?, updated_at=? WHERE user_id=?",
                           (",".join(kinds), now, user_id))


@router.post("/volunteer/credentials", status_code=201)
async def upload_credential(kind: str = Form(...), file: UploadFile = File(...),
                            user=Depends(current_user),
                            database: Database = Depends(get_database)):
    if kind not in CREDENTIAL_KINDS:
        raise HTTPException(422, "凭证类型只能是 lawyer_license 或 legal_aid")
    raw = await file.read()
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "图片为空或超过 4MB")
    try:
        image = Image.open(BytesIO(raw))
        image = image.convert("RGB")
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=85)
    except (UnidentifiedImageError, OSError):
        raise HTTPException(422, "无法识别的图片格式") from None
    data = buffer.getvalue()
    with database.transaction(write=True) as connection:
        cid = new_id("cred")
        connection.execute(
            "INSERT INTO volunteer_credentials(id,user_id,kind,mime,size,data,status,created_at) "
            "VALUES(?,?,?,?,?,?,'pending',?)",
            (cid, user["id"], kind, "image/jpeg", len(data), data, utcnow().isoformat()))
        _ensure_legal_intent(connection, user["id"])
        audit(connection, user["id"], "volunteer_credential_submitted", cid)
    return {"id": cid, "status": "pending"}


@router.get("/volunteer/credentials")
def my_credentials(user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT id,kind,status,note,reviewed_at,created_at FROM volunteer_credentials "
            "WHERE user_id=? ORDER BY created_at DESC", (user["id"],)).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.get("/admin/credentials")
def list_credentials(status: str = Query(default="pending", pattern=r"^(pending|approved|rejected)$"),
                     user=Depends(require_reviewer), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT c.id,c.user_id,c.kind,c.status,c.created_at,u.display_name "
            "FROM volunteer_credentials c JOIN users u ON u.id=c.user_id "
            "WHERE c.status=? ORDER BY c.created_at DESC", (status,)).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.get("/admin/credentials/{cid}/image")
def credential_image(cid: str, user=Depends(require_reviewer),
                     database: Database = Depends(get_database)):
    with database.transaction() as connection:
        row = connection.execute(
            "SELECT mime,data FROM volunteer_credentials WHERE id=?", (cid,)).fetchone()
    if row is None:
        raise HTTPException(404, "凭证不存在")
    return Response(content=row["data"], media_type=row["mime"],
                    headers={"Cache-Control": "no-store"})


@router.post("/admin/credentials/{cid}/review")
def review_credential(cid: str, payload: CredentialReviewInput,
                      user=Depends(require_reviewer), database: Database = Depends(get_database)):
    with database.transaction(write=True) as connection:
        row = connection.execute("SELECT * FROM volunteer_credentials WHERE id=?", (cid,)).fetchone()
        if row is None:
            raise HTTPException(404, "凭证不存在")
        if row["status"] != "pending":
            raise HTTPException(409, "该凭证已处理")
        approved = payload.decision == "approve"
        connection.execute(
            "UPDATE volunteer_credentials SET status=?, note=?, reviewed_by=?, reviewed_at=? WHERE id=?",
            ("approved" if approved else "rejected", payload.note, user["id"],
             utcnow().isoformat(), cid))
        if approved:
            _ensure_legal_intent(connection, row["user_id"])
        audit(connection, user["id"], "volunteer_credential_review", cid)
    return {"id": cid, "status": "approved" if approved else "rejected"}


def _has_approved_volunteer(connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM volunteer_credentials c JOIN volunteer_profiles p ON p.user_id=c.user_id "
        "WHERE c.status='approved' AND p.status='approved' LIMIT 1").fetchone()
    return row is not None


@router.post("/legal-help/requests", status_code=201)
def create_request(payload: LegalHelpCreate, user=Depends(patient),
                   database: Database = Depends(get_database)):
    # 先进队列再等人接：没有在线志愿者时也让患者把问题留下，避免白填一遍。
    with database.transaction(write=True) as connection:
        rid = new_id("help")
        now = utcnow().isoformat()
        connection.execute(
            "INSERT INTO legal_help_requests(id,patient_id,topic,text,status,created_at,updated_at) "
            "VALUES(?,?,?,?,'open',?,?)", (rid, user["id"], payload.topic, payload.text, now, now))
        audit(connection, user["id"], "legal_help_requested", rid)
    return {"id": rid, "status": "open"}


@router.get("/legal-help/requests")
def my_requests(user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT * FROM legal_help_requests WHERE patient_id=? ORDER BY updated_at DESC",
            (user["id"],)).fetchall()
        available = _has_approved_volunteer(connection)
    return {"items": [_request_dict(row) for row in rows], "available": available}


@router.get("/legal-help/queue")
def queue(user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        if not _can_help_legal(connection, user):
            raise HTTPException(403, "需要已核验的法律志愿者身份")
        rows = connection.execute(
            "SELECT * FROM legal_help_requests WHERE status IN ('open','claimed','answered') "
            "ORDER BY updated_at DESC").fetchall()
    return {"items": [_request_dict(row) for row in rows]}


@router.get("/legal-help/requests/{rid}")
def request_detail(rid: str, user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        row = connection.execute("SELECT * FROM legal_help_requests WHERE id=?", (rid,)).fetchone()
        if row is None:
            raise HTTPException(404, "工单不存在")
        is_owner = row["patient_id"] == user["id"]
        is_volunteer = row["volunteer_id"] == user["id"]
        is_reviewer = roles.capabilities(connection, user)["is_reviewer"]
        if not (is_owner or is_volunteer or is_reviewer):
            raise HTTPException(403, "无权查看该工单")
        messages = connection.execute(
            "SELECT id,role,text,created_at FROM legal_help_messages WHERE request_id=? "
            "ORDER BY created_at", (rid,)).fetchall()
    result = _request_dict(row)
    # 审核员只监督、不参与回复；前端据此隐藏输入框。
    result["viewer_role"] = "owner" if is_owner else "volunteer" if is_volunteer else "reviewer"
    result["messages"] = [dict(item) for item in messages]
    return result


@router.post("/legal-help/requests/{rid}/claim")
def claim(rid: str, user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction(write=True) as connection:
        if not _can_help_legal(connection, user):
            raise HTTPException(403, "需要已核验的法律志愿者身份")
        row = connection.execute("SELECT * FROM legal_help_requests WHERE id=?", (rid,)).fetchone()
        if row is None:
            raise HTTPException(404, "工单不存在")
        if row["patient_id"] == user["id"]:
            raise HTTPException(400, "不能接自己的工单")
        if row["status"] != "open":
            raise HTTPException(409, "工单已被接走或已结束")
        connection.execute(
            "UPDATE legal_help_requests SET status='claimed', volunteer_id=?, updated_at=? WHERE id=?",
            (user["id"], utcnow().isoformat(), rid))
        audit(connection, user["id"], "legal_help_claimed", rid)
    return {"id": rid, "status": "claimed"}


@router.post("/legal-help/requests/{rid}/messages", status_code=201)
def reply(rid: str, payload: LegalHelpMessageInput, user=Depends(current_user),
          database: Database = Depends(get_database)):
    with database.transaction(write=True) as connection:
        row = connection.execute("SELECT * FROM legal_help_requests WHERE id=?", (rid,)).fetchone()
        if row is None:
            raise HTTPException(404, "工单不存在")
        is_owner = row["patient_id"] == user["id"]
        is_volunteer = row["volunteer_id"] == user["id"]
        if not (is_owner or is_volunteer) or row["status"] == "closed":
            raise HTTPException(403, "无权回复该工单")
        now = utcnow().isoformat()
        connection.execute(
            "INSERT INTO legal_help_messages(id,request_id,sender_id,role,text,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (new_id("msg"), rid, user["id"], "patient" if is_owner else "volunteer", payload.text, now))
        status = "answered" if is_volunteer else ("claimed" if row["volunteer_id"] else "open")
        connection.execute("UPDATE legal_help_requests SET status=?, updated_at=? WHERE id=?",
                           (status, now, rid))
        audit(connection, user["id"], "legal_help_replied", rid)
    return {"id": rid, "status": status}


@router.get("/admin/legal-help")
def admin_requests(user=Depends(require_reviewer), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT r.*, (SELECT count(*) FROM legal_help_messages m WHERE m.request_id=r.id) AS message_count "
            "FROM legal_help_requests r ORDER BY r.updated_at DESC").fetchall()
    items = []
    for row in rows:
        item = _request_dict(row)
        item["message_count"] = row["message_count"]
        items.append(item)
    return {"items": items}


def _request_dict(row):
    return {"id": row["id"], "topic": row["topic"], "text": row["text"], "status": row["status"],
            "volunteer_id": row["volunteer_id"], "created_at": row["created_at"],
            "updated_at": row["updated_at"]}
