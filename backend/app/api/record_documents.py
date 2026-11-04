"""M03 private images, local OCR, explicit review and immutable archive versions."""
import base64
import binascii
from datetime import date, datetime, timedelta
from hashlib import sha256
from io import BytesIO
import json
from typing import Literal
import warnings

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import Field, model_validator

from app.api.dependencies import consent_policy, get_database, patient, require_consent
from app.db import Database, audit, new_id, token_hash, utcnow
from app.schemas import RecordBase64Input, StrictModel
from app.services.record_ocr import OCRError, empty_draft, parse_report, upright_png
from app.services.record_checklist import RECORD_TYPES, build_checklist

router = APIRouter(prefix="/record-documents", tags=["record-documents"])
MAX_BYTES = 8 * 1024 * 1024


class RevisionInput(StrictModel):
    revision: int = Field(ge=1)
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,80}$")


class ReviewField(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    name: str = Field(max_length=120)
    result: str = Field(max_length=200)
    unit: str = Field(default="", max_length=100)
    reference: str = Field(default="", max_length=200)
    confirmed: bool = False


class ReviewInput(RevisionInput):
    title: str = Field(min_length=1, max_length=100)
    record_type: Literal[*RECORD_TYPES] = "检验单"
    record_date: str = Field(default="", max_length=10)
    institution: str = Field(default="", max_length=120)
    visit: str = Field(default="", max_length=120)
    metadata_confirmed: bool = False
    fields: list[ReviewField] = Field(max_length=100)
    reason: str = Field(default="", max_length=300)

    @model_validator(mode="after")
    def validate_review(self):
        if self.record_date:
            if len(self.record_date) != 10:
                raise ValueError("日期须为 YYYY-MM-DD")
            date.fromisoformat(self.record_date)
        if len({f.id for f in self.fields}) != len(self.fields):
            raise ValueError("核对项目标识不能重复")
        return self


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def authorize(c, user, request=None):
    if request is not None:
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not c.execute("SELECT 1 FROM sessions WHERE token_hash=? AND user_id=? AND expires_at>?",
                         (token_hash(token), user["id"], utcnow().isoformat())).fetchone():
            raise HTTPException(401, "登录已失效，本次识别结果未保存")
    return require_consent(c, user["id"], "records_read", consent_policy("records_read", None))


def load(c, uid, document_id):
    row = c.execute("SELECT * FROM record_documents WHERE id=? AND user_id=?", (document_id, uid)).fetchone()
    if row is None:
        raise HTTPException(404, "资料不存在")
    return row


def serialize(c, row, *, full=True):
    draft = json.loads(row["draft"])
    result = {key: row[key] for key in ("id", "revision", "status", "archived_version", "created_at", "updated_at", "width", "height")}
    result.update(title=draft["title"], institution=draft["institution"], record_date=draft["record_date"],
                  visit=draft["visit"], source="user_upload", external_ai=False)
    job = c.execute("SELECT * FROM record_ocr_jobs WHERE id=?", (row["latest_job_id"],)).fetchone()
    result["job"] = ({key: job[key] for key in ("id", "status", "error", "started_at", "finished_at")} if job else None)
    if full:
        result["draft"] = draft
        result["ocr"] = json.loads(job["result"]) if job and job["result"] else None
        result["versions"] = [dict(v) for v in c.execute(
            "SELECT version,reason,created_at FROM record_document_versions WHERE document_id=? ORDER BY version DESC", (row["id"],))]
        result["jobs"] = [dict(j) for j in c.execute(
            "SELECT id,status,error,started_at,finished_at FROM record_ocr_jobs WHERE document_id=? ORDER BY started_at DESC", (row["id"],))]
    return result


def check_revision(row, revision):
    if row["revision"] != revision:
        raise HTTPException(409, "资料已变化，请重新载入后核对；未覆盖其他版本")


def check_not_running(c, row):
    if row["status"] != "recognizing":
        return
    job = c.execute("SELECT * FROM record_ocr_jobs WHERE id=?", (row["latest_job_id"],)).fetchone()
    if job and datetime.fromisoformat(job["started_at"]) > utcnow() - timedelta(seconds=100):
        raise HTTPException(409, "OCR仍在运行，请稍后刷新；中断超过100秒可重试或手填")
    c.execute("UPDATE record_ocr_jobs SET status='failed',error=?,finished_at=? WHERE id=? AND status='running'",
              ("识别中断，可重试或手填", utcnow().isoformat(), row["latest_job_id"]))


def _validate_record_image(data: bytes):
    """校验病历照片，返回 (mime, width, height)。"""
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(413, "请选择8MB以内的检验单照片")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format not in ("JPEG", "PNG", "WEBP") or getattr(image, "n_frames", 1) != 1:
                    raise ValueError()
                if image.width * image.height > 20_000_000 or min(image.size) < 40:
                    raise ValueError()
                mime = Image.MIME[image.format]
                image.verify()
            with Image.open(BytesIO(data)) as image:
                upright = ImageOps.exif_transpose(image)
                width, height = upright.size
    except (ValueError, OSError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(422, "照片无效；请用清晰的JPEG、PNG或WebP单张照片（40像素以上，2000万像素以内）")
    return mime, width, height


def _store_document(request: Request, user, database, data: bytes):
    mime, width, height = _validate_record_image(data)
    with database.transaction() as c:
        consent = authorize(c, user)
    digest = sha256(data).hexdigest()
    with database.transaction(write=True) as c:
        if authorize(c, user, request) != consent:
            raise HTTPException(403, "授权已变化，照片未保存，请重新确认授权")
        previous = c.execute("SELECT * FROM record_documents WHERE user_id=? AND sha256=?", (user["id"], digest)).fetchone()
        if previous:
            return serialize(c, previous) | {"duplicate": True}
        did, now = new_id("doc"), utcnow().isoformat()
        c.execute("INSERT INTO record_documents(id,user_id,sha256,image,mime,width,height,status,draft,created_at,updated_at) "
                  "VALUES(?,?,?,?,?,?,?,'uploaded',?,?,?)",
                  (did, user["id"], digest, data, mime, width, height, dump(empty_draft()), now, now))
        audit(c, user["id"], "record_image_uploaded", did)
        return serialize(c, load(c, user["id"], did)) | {"duplicate": False}


@router.post("", status_code=201)
def upload_document(request: Request, file: UploadFile = File(...), user=Depends(patient),
                    database: Database = Depends(get_database)):
    try:
        data = file.file.read(MAX_BYTES + 1)
    finally:
        file.file.close()
    return _store_document(request, user, database, data)


@router.post("/base64", status_code=201)
def upload_document_base64(payload: RecordBase64Input, request: Request, user=Depends(patient),
                           database: Database = Depends(get_database)):
    """云托管没有 multipart，病历照片走 JSON base64。"""
    raw = payload.data.split(",", 1)[-1]
    try:
        data = base64.b64decode(raw, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(422, "图片内容不是合法的 base64") from None
    return _store_document(request, user, database, data)


@router.get("")
def list_documents(user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction() as c:
        authorize(c, user)
        return {"items": [serialize(c, row, full=False) for row in c.execute(
            "SELECT * FROM record_documents WHERE user_id=? ORDER BY updated_at DESC", (user["id"],))]}


@router.get("/checklist")
def checklist(scenario: str = "outpatient", user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction() as c:
        authorize(c, user)
        rows = c.execute("SELECT draft,status FROM record_documents WHERE user_id=? ORDER BY updated_at DESC",
                         (user["id"],)).fetchall()
        return build_checklist([{"draft": row["draft"], "status": row["status"]} for row in rows], scenario)


@router.get("/{document_id}/image-base64")
def get_image_base64(document_id: str, original: bool = False, user=Depends(patient),
                     database: Database = Depends(get_database)):
    with database.transaction() as c:
        authorize(c, user)
        row = load(c, user["id"], document_id)
        data, mime = bytes(row["image"]), row["mime"]
    payload = data if original else upright_png(data)
    media = mime if original else "image/png"
    return {"mime": media, "data": "data:" + media + ";base64," + base64.b64encode(payload).decode()}


@router.get("/{document_id}/jobs/{job_id}/fields/{field_id}/image-base64")
def field_image_base64(document_id: str, job_id: str, field_id: str, user=Depends(patient),
                       database: Database = Depends(get_database)):
    return {"mime": "image/png", "data": "data:image/png;base64,"
            + base64.b64encode(_field_png(document_id, job_id, field_id, user, database)).decode()}


@router.get("/{document_id}")
def get_document(document_id: str, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction() as c:
        authorize(c, user)
        return serialize(c, load(c, user["id"], document_id))


@router.get("/{document_id}/image")
def get_image(document_id: str, original: bool = False, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction() as c:
        authorize(c, user)
        row = load(c, user["id"], document_id)
        data, mime = bytes(row["image"]), row["mime"]
    return Response(data if original else upright_png(data), media_type=mime if original else "image/png")


@router.get("/{document_id}/jobs/{job_id}")
def get_job(document_id: str, job_id: str, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction() as c:
        authorize(c, user)
        load(c, user["id"], document_id)
        job = c.execute("SELECT * FROM record_ocr_jobs WHERE document_id=? AND id=?", (document_id, job_id)).fetchone()
        if not job:
            raise HTTPException(404, "识别任务不存在")
        return {"id": job_id, "status": job["status"], "error": job["error"],
                "result": json.loads(job["result"]) if job["result"] else None}


@router.get("/{document_id}/jobs/{job_id}/fields/{field_id}/image")
def field_image(document_id: str, job_id: str, field_id: str, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction() as c:
        authorize(c, user)
        row = load(c, user["id"], document_id)
        job = c.execute("SELECT result FROM record_ocr_jobs WHERE id=? AND document_id=?", (job_id, document_id)).fetchone()
        result = json.loads(job["result"]) if job and job["result"] else {}
        field = next((f for f in result.get("draft", {}).get("fields", []) if f["id"] == field_id), None)
        if not field:
            raise HTTPException(404, "没有对应的原图位置，请查看整张原图")
        data = bytes(row["image"])
    return Response(_crop_field(data, field), media_type="image/png")


def _crop_field(data: bytes, field: dict) -> bytes:
    with Image.open(BytesIO(upright_png(data))) as image:
        x1, y1, x2, y2 = field["box"]
        crop = image.crop((max(0, int(x1) - 12), max(0, int(y1) - 12), min(image.width, int(x2) + 12), min(image.height, int(y2) + 12)))
        output = BytesIO()
        crop.save(output, format="PNG")
    return output.getvalue()


def _field_png(document_id: str, job_id: str, field_id: str, user, database) -> bytes:
    with database.transaction() as c:
        authorize(c, user)
        row = load(c, user["id"], document_id)
        job = c.execute("SELECT result FROM record_ocr_jobs WHERE id=? AND document_id=?", (job_id, document_id)).fetchone()
        result = json.loads(job["result"]) if job and job["result"] else {}
        field = next((f for f in result.get("draft", {}).get("fields", []) if f["id"] == field_id), None)
        if not field:
            raise HTTPException(404, "没有对应的原图位置，请查看整张原图")
        data = bytes(row["image"])
    return Response(_crop_field(data, field), media_type="image/png")


@router.post("/{document_id}/ocr")
def recognize(document_id: str, payload: RevisionInput, request: Request, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction(write=True) as c:
        consent = authorize(c, user)
        row = load(c, user["id"], document_id)
        previous = c.execute("SELECT * FROM record_ocr_jobs WHERE document_id=? AND request_id=?", (document_id, payload.request_id)).fetchone()
        if previous:
            return serialize(c, row)
        check_revision(row, payload.revision)
        if row["archived_version"]:
            raise HTTPException(409, "已归档资料请用更正功能；重新拍摄需新建资料")
        check_not_running(c, row)
        jid, now = new_id("ocr"), utcnow().isoformat()
        c.execute("INSERT INTO record_ocr_jobs(id,document_id,request_id,status,started_at) VALUES(?,?,?,'running',?)",
                  (jid, document_id, payload.request_id, now))
        c.execute("UPDATE record_documents SET status='recognizing',latest_job_id=?,revision=revision+1,updated_at=? WHERE id=?", (jid, now, document_id))
        image = bytes(row["image"])
    result, error = None, None
    try:
        result = request.app.state.record_ocr.recognize(upright_png(image))
        result["draft"] = parse_report(result)
        result["draft"]["source_job_id"] = jid
    except OCRError as exc:
        error = str(exc)
    except Exception:
        # Do not put image text, filesystem details or provider exceptions into logs/UI.
        error = "识别结果无法解析，可重试或对照原图手填"
    rejected = None
    with database.transaction(write=True) as c:
        row = load(c, user["id"], document_id)
        try:
            if authorize(c, user, request) != consent:
                raise HTTPException(403, "识别期间授权已变化，结果已丢弃；请重新核对授权")
        except HTTPException as exc:
            rejected = exc
        job = c.execute("SELECT status FROM record_ocr_jobs WHERE id=?", (jid,)).fetchone()
        if row["latest_job_id"] != jid or not job or job["status"] != "running":
            raise HTTPException(409, "该识别任务已被新操作取代，未覆盖当前核对内容")
        now = utcnow().isoformat()
        status = "discarded" if rejected else ("failed" if error else "succeeded")
        c.execute("UPDATE record_ocr_jobs SET status=?,result=?,error=?,finished_at=? WHERE id=?",
                  (status, dump(result) if result and not rejected else None,
                   "授权变化，结果已丢弃" if rejected else error, now, jid))
        c.execute("UPDATE record_documents SET status=?,revision=revision+1,draft=?,updated_at=? WHERE id=?",
                  ("review" if status == "succeeded" else "failed", dump(result["draft"]) if status == "succeeded" else row["draft"], now, document_id))
        audit(c, user["id"], "record_ocr_" + status, document_id)
        response = serialize(c, load(c, user["id"], document_id)) if not rejected else None
    if rejected:
        raise rejected
    return response


def merged_draft(c, row, payload):
    draft = payload.model_dump(exclude={"request_id", "revision"})
    # A failed retry must not disconnect the retained fields from their successful
    # source attempt. The client cannot choose or overwrite this provenance.
    draft["source_job_id"] = json.loads(row["draft"]).get("source_job_id")
    job = c.execute("SELECT result FROM record_ocr_jobs WHERE id=?", (draft["source_job_id"],)).fetchone()
    result = json.loads(job["result"]) if job and job["result"] else {}
    originals = {f["id"]: f for f in result.get("draft", {}).get("fields", [])}
    for field in draft["fields"]:
        source = originals.get(field["id"])
        if not source and not field["id"].startswith("manual-"):
            raise HTTPException(422, "新增项目须使用手填标识")
        field.update({key: source[key] if source else default for key, default in
                      (("original", None), ("confidence", None), ("box", None), ("source_ids", []))})
    return draft


def changes_between(old, new):
    changes = []
    for key in ("title", "record_type", "record_date", "institution", "visit"):
        if old.get(key) != new.get(key):
            changes.append({"field": key, "before": old.get(key, ""), "after": new.get(key, "")})
    old_rows = {f["id"]: f for f in old.get("fields", [])}
    new_rows = {f["id"]: f for f in new.get("fields", [])}
    for fid in sorted(old_rows.keys() | new_rows.keys()):
        for key in ("name", "result", "unit", "reference"):
            before, after = old_rows.get(fid, {}).get(key, ""), new_rows.get(fid, {}).get(key, "")
            if before != after:
                changes.append({"field": fid + "." + key, "before": before, "after": after})
    return changes


def save_review(document_id, payload, user, database, confirm):
    with database.transaction(write=True) as c:
        authorize(c, user)
        row = load(c, user["id"], document_id)
        action = "confirm" if confirm else "draft"
        body = payload.model_dump()
        previous = c.execute("SELECT * FROM record_document_events WHERE document_id=? AND request_id=?", (document_id, payload.request_id)).fetchone()
        if previous:
            if previous["action"] != action or json.loads(previous["payload"]) != body:
                raise HTTPException(409, "同一操作编号不能提交不同内容，请刷新确认")
            return serialize(c, row)
        check_revision(row, payload.revision)
        check_not_running(c, row)
        draft = merged_draft(c, row, payload)
        if confirm:
            if not payload.metadata_confirmed or not payload.fields or any(not f.confirmed or not f.name or not f.result for f in payload.fields):
                raise HTTPException(422, "请核对资料信息，并逐项确认项目和结果后再归档")
            if row["archived_version"] and not payload.reason:
                raise HTTPException(422, "更正归档须填写修改原因")
            old_version = c.execute("SELECT snapshot FROM record_document_versions WHERE document_id=? AND version=?", (document_id, row["archived_version"])).fetchone()
            job = c.execute("SELECT result FROM record_ocr_jobs WHERE id=?", (draft["source_job_id"],)).fetchone()
            baseline = json.loads(old_version["snapshot"])["draft"] if old_version else (json.loads(job["result"])["draft"] if job and job["result"] else empty_draft())
            version = row["archived_version"] + 1
            snapshot = {"draft": draft, "job_id": draft["source_job_id"], "image_sha256": row["sha256"], "version": version}
            c.execute("INSERT INTO record_document_versions(document_id,version,snapshot,changes,actor_id,reason,created_at) VALUES(?,?,?,?,?,?,?)",
                      (document_id, version, dump(snapshot), dump(changes_between(baseline, draft)), user["id"], payload.reason or "首次核对归档", utcnow().isoformat()))
        else:
            version = row["archived_version"]
        now = utcnow().isoformat()
        c.execute("UPDATE record_documents SET draft=?,status=?,revision=revision+1,archived_version=?,updated_at=? WHERE id=?",
                  (dump(draft), "archived" if confirm else "review", version, now, document_id))
        c.execute("INSERT INTO record_document_events(document_id,request_id,action,payload,created_at) VALUES(?,?,?,?,?)", (document_id, payload.request_id, action, dump(body), now))
        audit(c, user["id"], "record_" + action, document_id)
        return serialize(c, load(c, user["id"], document_id))


@router.put("/{document_id}/draft")
def save_draft(document_id: str, payload: ReviewInput, user=Depends(patient), database: Database = Depends(get_database)):
    return save_review(document_id, payload, user, database, False)


@router.post("/{document_id}/confirm")
def confirm_document(document_id: str, payload: ReviewInput, user=Depends(patient), database: Database = Depends(get_database)):
    return save_review(document_id, payload, user, database, True)


@router.get("/{document_id}/versions/{version}")
def get_version(document_id: str, version: int, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction() as c:
        authorize(c, user)
        load(c, user["id"], document_id)
        row = c.execute("SELECT * FROM record_document_versions WHERE document_id=? AND version=?", (document_id, version)).fetchone()
        if not row:
            raise HTTPException(404, "版本不存在")
        return {"snapshot": json.loads(row["snapshot"]), "changes": json.loads(row["changes"]),
                "reason": row["reason"], "created_at": row["created_at"], "actor_id": row["actor_id"]}


@router.delete("/{document_id}")
def delete_unarchived(document_id: str, revision: int, user=Depends(patient), database: Database = Depends(get_database)):
    with database.transaction(write=True) as c:
        authorize(c, user)
        row = load(c, user["id"], document_id)
        check_revision(row, revision)
        check_not_running(c, row)
        if row["archived_version"]:
            raise HTTPException(409, "已归档资料不能作为草稿删除，请用更正功能保留历史")
        c.execute("DELETE FROM record_documents WHERE id=?", (document_id,))
        audit(c, user["id"], "record_draft_deleted", document_id)
    return {"deleted": document_id}
