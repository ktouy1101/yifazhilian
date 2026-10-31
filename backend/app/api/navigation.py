"""M11: claimed collection, versioned review, independent publication."""
from hashlib import sha256
from io import BytesIO
import json
import warnings

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from PIL import Image, ImageOps, UnidentifiedImageError
from app.api.dependencies import current_user, get_database
from app.db import Database, audit, new_id, utcnow
from app.schemas import (DisableInput, FeedbackInput, ReviewDecisionInput,
                         SubmissionCreate, SubmissionSubmit, SubmissionUpdate, SubmissionRevise)

router = APIRouter(prefix="/navigation", tags=["navigation"])
MAX_MEDIA_BYTES = 5 * 1024 * 1024
EDITABLE = {"draft", "changes_requested"}


def _perms(c, uid):
    """导航能力位。审核权取"成员位或 reviewer 角色"的并集：

    管理员是通过 user_roles 授权的，旧库里可能还留着 can_review=0 的成员行，
    只看成员位会把人误判成"体验员"。
    """
    row = c.execute("SELECT * FROM navigation_memberships WHERE user_id=?", (uid,)).fetchone()
    roles = {item["role"] for item in
             c.execute("SELECT role FROM user_roles WHERE user_id=?", (uid,))}
    return {"hospital_id": row["hospital_id"] if row else "demo-hospital",
            "collect": bool(row and row["can_collect"]),
            "review": bool((row and row["can_review"]) or "reviewer" in roles),
            "browse": True, "feedback": True}


def _load(c, sid):
    row = c.execute("SELECT s.*,t.hospital_id FROM navigation_submissions s "
                    "JOIN navigation_tasks t ON t.id=s.task_id WHERE s.id=?", (sid,)).fetchone()
    if row is None:
        raise HTTPException(404, "提交不存在")
    return row


def _access(c, row, uid, *, edit=False, review=False):
    p, owner = _perms(c, uid), row["collector_id"] == uid
    if row["hospital_id"] != p["hospital_id"]:
        raise HTTPException(403, "只能操作所属医院的采集资料")
    if review:
        if not p["review"]:
            raise HTTPException(403, "当前身份没有审核权限")
        if owner:
            raise HTTPException(403, "采集者不能审核或发布自己提交的路线")
    elif edit:
        if not (owner and p["collect"]):
            raise HTTPException(403, "只能修改本人且有采集权限的草稿")
    elif not (owner or (p["review"] and row["status"] != "draft")):
        raise HTTPException(403, "无权查看该提交")


def _serialize(c, row, *, history=True):
    result = {key: row[key] for key in (
        "id", "task_id", "collector_id", "revision", "title", "status", "created_at",
        "updated_at", "reviewer_id", "reviewed_at", "review_note", "disabled_reason")}
    result.update({key: bool(row[key]) for key in ("privacy_confirmed", "walkthrough_confirmed", "ar_ready")})
    result["nodes"] = [dict(n) for n in c.execute(
        "SELECT node_key,position,kind,floor,direction,description FROM navigation_nodes "
        "WHERE submission_id=? ORDER BY position", (row["id"],))]
    result["media"] = [dict(m) for m in c.execute(
        "SELECT id,node_key,revision,mime,size FROM navigation_media WHERE submission_id=?", (row["id"],))]
    if history:
        result["history"] = [{"id": e["id"], "actor_id": e["actor_id"], "action": e["action"],
                              "revision": e["revision"], "created_at": e["created_at"],
                              "details": json.loads(e["payload"])} for e in c.execute(
            "SELECT * FROM navigation_events WHERE submission_id=? ORDER BY id", (row["id"],))]
        result["versions"] = [dict(v) for v in c.execute(
            "SELECT revision,created_at FROM navigation_versions WHERE submission_id=? ORDER BY revision DESC", (row["id"],))]
        result["feedback"] = [dict(f) for f in c.execute(
            "SELECT id,category,note,created_at FROM navigation_feedback WHERE route_id=? ORDER BY created_at DESC", (row["id"],))]
    return result


def _event(c, row, uid, action, payload):
    c.execute("INSERT INTO navigation_events(submission_id,actor_id,action,from_revision,revision,payload,created_at) "
              "VALUES(?,?,?,?,?,?,?)", (row["id"], uid, action, row["revision"], row["revision"] + 1,
                                        json.dumps(payload, ensure_ascii=False, sort_keys=True), utcnow().isoformat()))
    audit(c, uid, "navigation_" + action, row["id"])


def _retry(c, row, uid, action, payload, status):
    event = c.execute("SELECT * FROM navigation_events WHERE submission_id=? AND from_revision=? AND action=?",
                      (row["id"], payload["revision"], action)).fetchone()
    if event and event["actor_id"] == uid and json.loads(event["payload"]) == payload:
        if row["revision"] == event["revision"] and row["status"] == status:
            return _serialize(c, row)
    return None


def _check(row, revision, statuses):
    if row["revision"] != revision or row["status"] not in statuses:
        raise HTTPException(409, "内容或状态已变化，请刷新后重试；旧审核意见不能用于新提交")


def _photo(data, mime):
    return Response(bytes(data), media_type=mime, headers={"Cache-Control": "no-store"})


def _require_wayfinding_details(nodes):
    for index, node in enumerate(nodes, 1):
        if not (node.get("floor") or "").strip() or not (node.get("description") or "").strip():
            raise HTTPException(422, f"请补全第 {index} 个节点的楼栋 / 楼层和位置说明，患者需要据此核对现场")


@router.get("/me")
def me(user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction() as c:
        return {"user": user, "permissions": _perms(c, user["id"]),
                "notice": "合成演示身份；权限由后端分配。采集者不能审核自己的路线。"}


@router.get("/tasks")
def tasks(user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction() as c:
        p, items = _perms(c, user["id"]), []
        for row in c.execute("SELECT * FROM navigation_tasks WHERE hospital_id=? ORDER BY created_at", (p["hospital_id"],)):
            sub = c.execute("SELECT id FROM navigation_submissions WHERE task_id=? AND collector_id=? "
                            "ORDER BY created_at DESC LIMIT 1", (row["id"], user["id"])).fetchone()
            items.append(dict(row) | {"mine_claimed": row["claimed_by"] == user["id"],
                         "collectable": p["collect"] and row["status"] == "open",
                         "submission_id": sub["id"] if sub else None})
        return {"items": items}


@router.post("/tasks/{task_id}/claim")
def claim(task_id: str, user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction(write=True) as c:
        p = _perms(c, user["id"])
        if not p["collect"]:
            raise HTTPException(403, "当前身份没有采集权限")
        task = c.execute("SELECT * FROM navigation_tasks WHERE id=? AND hospital_id=?", (task_id, p["hospital_id"])).fetchone()
        if not task:
            raise HTTPException(404, "任务不存在")
        if task["claimed_by"] == user["id"]:
            return {"task": dict(task), "idempotent": True}
        if task["status"] != "open":
            raise HTTPException(409, "任务已被他人领取或已完成")
        c.execute("UPDATE navigation_tasks SET status='claimed',claimed_by=?,claimed_at=? WHERE id=?",
                  (user["id"], utcnow().isoformat(), task_id))
        audit(c, user["id"], "navigation_task_claimed", task_id)
        return {"task": dict(c.execute("SELECT * FROM navigation_tasks WHERE id=?", (task_id,)).fetchone()), "idempotent": False}


@router.post("/submissions", status_code=201)
def create(payload: SubmissionCreate, user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction(write=True) as c:
        p = _perms(c, user["id"])
        if not p["collect"]:
            raise HTTPException(403, "当前身份没有采集权限")
        task = c.execute("SELECT * FROM navigation_tasks WHERE id=? AND hospital_id=?", (payload.task_id, p["hospital_id"])).fetchone()
        if not task:
            raise HTTPException(404, "任务不存在")
        if task["claimed_by"] != user["id"]:
            raise HTTPException(403, "请先领取该任务；不能替他人创建草稿")
        # One working submission per task even when a client retries with a different key.
        old = c.execute("SELECT * FROM navigation_submissions WHERE task_id=? ORDER BY created_at DESC LIMIT 1", (payload.task_id,)).fetchone()
        if old:
            if old["collector_id"] != user["id"]:
                raise HTTPException(409, "任务已有其他采集者的提交")
            return _serialize(c, old)
        if task["status"] != "claimed":
            raise HTTPException(409, "任务已完成")
        sid, now = new_id("navsub"), utcnow().isoformat()
        c.execute("INSERT INTO navigation_submissions(id,task_id,collector_id,title,status,client_request_id,created_at,updated_at) "
                  "VALUES(?,?,?,?,'draft',?,?,?)", (sid, payload.task_id, user["id"], payload.title, payload.request_id, now, now))
        audit(c, user["id"], "navigation_submission_draft", sid)
        return _serialize(c, _load(c, sid))


@router.get("/submissions")
def submissions(scope: str = "mine", user=Depends(current_user), database: Database = Depends(get_database)):
    if scope not in ("mine", "review"):
        raise HTTPException(422, "scope 必须为 mine 或 review")
    with database.transaction() as c:
        p = _perms(c, user["id"])
        if scope == "review" and not p["review"]:
            raise HTTPException(403, "当前身份没有审核权限")
        clause = "s.collector_id=?" if scope == "mine" else "s.collector_id!=? AND s.status!='draft'"
        rows = c.execute("SELECT s.* FROM navigation_submissions s JOIN navigation_tasks t ON t.id=s.task_id "
                         f"WHERE t.hospital_id=? AND {clause} ORDER BY s.updated_at DESC", (p["hospital_id"], user["id"])).fetchall()
        return {"items": [_serialize(c, r) for r in rows], "scope": scope}


@router.get("/submissions/{sid}")
def detail(sid: str, user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction() as c:
        row = _load(c, sid)
        _access(c, row, user["id"])
        return _serialize(c, row)


@router.put("/submissions/{sid}")
def update(sid: str, payload: SubmissionUpdate, user=Depends(current_user), database: Database = Depends(get_database)):
    nodes = sorted(payload.nodes, key=lambda n: n.position)
    if len({n.node_key for n in nodes}) != len(nodes) or [n.position for n in nodes] != list(range(len(nodes))):
        raise HTTPException(422, "节点标识必须唯一，顺序必须从 0 开始连续")
    if nodes[0].kind != "start" or nodes[-1].kind != "end" or any(n.kind in ("start", "end") for n in nodes[1:-1]):
        raise HTTPException(422, "第一个节点须为起点，最后一个须为终点，中间不能重复起终点")
    with database.transaction(write=True) as c:
        row = _load(c, sid)
        _access(c, row, user["id"], edit=True)
        _check(row, payload.revision, EDITABLE)
        old_nodes = {n["node_key"]: dict(n) for n in c.execute("SELECT node_key,position,kind,floor,direction,description FROM navigation_nodes WHERE submission_id=? ORDER BY position", (sid,))}
        values = [n.model_dump() for n in nodes]
        if row["title"] == payload.title and list(old_nodes.values()) == values:
            return _serialize(c, row)
        for key, old in old_nodes.items():
            new = next((n for n in values if n["node_key"] == key), None)
            if new is None or any(old[k] != new[k] for k in ("kind", "floor")):
                c.execute("DELETE FROM navigation_media WHERE submission_id=? AND node_key=?", (sid, key))
        c.execute("DELETE FROM navigation_nodes WHERE submission_id=?", (sid,))
        c.executemany("INSERT INTO navigation_nodes(submission_id,node_key,position,kind,floor,direction,description) VALUES(?,?,?,?,?,?,?)",
                      [(sid, n.node_key, n.position, n.kind, n.floor, n.direction, n.description) for n in nodes])
        c.execute("UPDATE navigation_submissions SET title=?,revision=revision+1,privacy_confirmed=0,updated_at=? WHERE id=?",
                  (payload.title, utcnow().isoformat(), sid))
        _event(c, row, user["id"], "edit", {"node_count": len(nodes)})
        return _serialize(c, _load(c, sid))


@router.post("/submissions/{sid}/media", status_code=201)
async def upload(sid: str, node_key: str = Form(..., max_length=64), revision: int = Form(..., ge=1),
                 client_upload_id: str = Form(default="", max_length=64), file: UploadFile = File(...),
                 user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction() as c:
        _access(c, _load(c, sid), user["id"], edit=True)
    data = await file.read(MAX_MEDIA_BYTES + 1)
    if len(data) > MAX_MEDIA_BYTES:
        raise HTTPException(413, "图片不能超过 5MB")
    if file.content_type not in ("image/jpeg", "image/png"):
        raise HTTPException(415, "仅支持 JPEG / PNG")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                fmt = image.format
                if fmt not in ("JPEG", "PNG") or image.width * image.height > 24_000_000:
                    raise ValueError("图片格式或尺寸不支持")
                image.load()
                clean = ImageOps.exif_transpose(image).convert("RGB")
                output = BytesIO()
                clean.save(output, format=fmt)
                data = output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise HTTPException(422, "图片损坏或尺寸过大，请重新选择 JPEG / PNG")
    if len(data) > MAX_MEDIA_BYTES:
        raise HTTPException(413, "处理后的图片超过 5MB，请压缩后重试")
    mime, digest = ("image/jpeg" if fmt == "JPEG" else "image/png"), sha256(data).hexdigest()
    with database.transaction(write=True) as c:
        row = _load(c, sid)
        _access(c, row, user["id"], edit=True)
        old = c.execute("SELECT * FROM navigation_media WHERE submission_id=? AND node_key=?", (sid, node_key)).fetchone()
        if client_upload_id and old and old["client_upload_id"] == client_upload_id:
            if old["sha256"] != digest:
                raise HTTPException(409, "同一上传编号不能用于不同照片")
            return {"id": old["id"], "node_key": node_key, "revision": old["revision"], "submission_revision": row["revision"]}
        _check(row, revision, EDITABLE)
        if not c.execute("SELECT 1 FROM navigation_nodes WHERE submission_id=? AND node_key=?", (sid, node_key)).fetchone():
            raise HTTPException(422, "请先保存这个节点再上传照片")
        mid = new_id("navmedia")
        c.execute("DELETE FROM navigation_media WHERE submission_id=? AND node_key=?", (sid, node_key))
        c.execute("INSERT INTO navigation_media(id,submission_id,node_key,revision,client_upload_id,mime,size,data,sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (mid, sid, node_key, revision + 1, client_upload_id, mime, len(data), data, digest, utcnow().isoformat()))
        c.execute("UPDATE navigation_submissions SET revision=revision+1,privacy_confirmed=0,updated_at=? WHERE id=?", (utcnow().isoformat(), sid))
        _event(c, row, user["id"], "photo", {"node_key": node_key})
        return {"id": mid, "node_key": node_key, "revision": revision + 1, "submission_revision": revision + 1, "mime": mime, "size": len(data)}


@router.get("/media/{mid}")
def media(mid: str, user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction(write=True) as c:
        item = c.execute("SELECT * FROM navigation_media WHERE id=?", (mid,)).fetchone()
        if not item:
            raise HTTPException(404, "照片已替换或不存在")
        row, p = _load(c, item["submission_id"]), _perms(c, user["id"])
        if row["status"] != "published" or row["hospital_id"] != p["hospital_id"]:
            _access(c, row, user["id"])
        audit(c, user["id"], "navigation_media_read", mid)
        return _photo(item["data"], item["mime"])


@router.post("/submissions/{sid}/submit")
def submit(sid: str, payload: SubmissionSubmit, user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction(write=True) as c:
        row = _load(c, sid)
        _access(c, row, user["id"], edit=True)
        retry = _retry(c, row, user["id"], "submit", payload.model_dump(), "submitted")
        if retry:
            return retry
        _check(row, payload.revision, EDITABLE)
        content = _serialize(c, row, history=False)
        if len(content["nodes"]) < 2 or {n["node_key"] for n in content["nodes"]} != {m["node_key"] for m in content["media"]}:
            raise HTTPException(422, "每个路线节点都必须有一张已上传的照片")
        _require_wayfinding_details(content["nodes"])
        now = utcnow().isoformat()
        c.execute("UPDATE navigation_submissions SET status='submitted',revision=revision+1,privacy_confirmed=1,walkthrough_confirmed=0,ar_ready=0,updated_at=? WHERE id=?", (now, sid))
        snapshot = _serialize(c, _load(c, sid), history=False)
        c.execute("INSERT INTO navigation_versions VALUES(?,?,?,?)", (sid, snapshot["revision"], json.dumps(snapshot, ensure_ascii=False), now))
        c.execute("INSERT INTO navigation_version_media SELECT submission_id,?,node_key,mime,data FROM navigation_media WHERE submission_id=?", (snapshot["revision"], sid))
        _event(c, row, user["id"], "submit", payload.model_dump())
        return _serialize(c, _load(c, sid))


@router.post("/submissions/{sid}/review")
def review(sid: str, payload: ReviewDecisionInput, user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction(write=True) as c:
        row = _load(c, sid)
        _access(c, row, user["id"], review=True)
        if payload.decision == "approve" and (not payload.walkthrough_confirmed or not payload.note):
            raise HTTPException(422, "发布前须确认独立实走，并填写现场核验及障碍、通行条件")
        if payload.decision == "request_changes" and not payload.note:
            raise HTTPException(422, "退回时请填写具体补拍或修改原因")
        status = "published" if payload.decision == "approve" else "changes_requested"
        retry = _retry(c, row, user["id"], payload.decision, payload.model_dump(), status)
        if retry:
            return retry
        _check(row, payload.revision, {"submitted"})
        if payload.decision == "approve":
            _require_wayfinding_details(_serialize(c, row, history=False)["nodes"])
        now = utcnow().isoformat()
        c.execute("UPDATE navigation_submissions SET status=?,revision=revision+1,reviewer_id=?,reviewed_at=?,review_note=?,walkthrough_confirmed=?,ar_ready=0,updated_at=? WHERE id=?",
                  (status, user["id"], now, payload.note, int(status == "published"), now, sid))
        c.execute("UPDATE navigation_tasks SET status=? WHERE id=?", ("done" if status == "published" else "claimed", row["task_id"]))
        _event(c, row, user["id"], payload.decision, payload.model_dump())
        return _serialize(c, _load(c, sid))


@router.post("/submissions/{sid}/disable")
def disable(sid: str, payload: DisableInput, user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction(write=True) as c:
        row = _load(c, sid)
        _access(c, row, user["id"], review=True)
        retry = _retry(c, row, user["id"], "disable", payload.model_dump(), "disabled")
        if retry:
            return retry
        _check(row, payload.revision, {"published"})
        c.execute("UPDATE navigation_submissions SET status='disabled',revision=revision+1,disabled_reason=?,updated_at=? WHERE id=?",
                  (payload.reason, utcnow().isoformat(), sid))
        _event(c, row, user["id"], "disable", payload.model_dump())
        return _serialize(c, _load(c, sid))


@router.get("/submissions/{sid}/versions/{revision}")
def version(sid: str, revision: int, user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction() as c:
        _access(c, _load(c, sid), user["id"])
        row = c.execute("SELECT snapshot FROM navigation_versions WHERE submission_id=? AND revision=?", (sid, revision)).fetchone()
        if not row:
            raise HTTPException(404, "历史版本不存在")
        return json.loads(row["snapshot"])


@router.post("/submissions/{sid}/revise")
def revise(sid: str, payload: SubmissionRevise, user=Depends(current_user), database: Database = Depends(get_database)):
    """Restore a historical collection as a new draft, withdrawing the current route.

    Restoring is never publication: the collector must submit and another reviewer
    must perform a new walkthrough. Immutable earlier versions remain available.
    """
    with database.transaction(write=True) as c:
        row = _load(c, sid)
        _access(c, row, user["id"], edit=True)
        retry = _retry(c, row, user["id"], "revise", payload.model_dump(), "draft")
        if retry:
            return retry
        _check(row, payload.revision, {"published", "disabled"})
        source = c.execute("SELECT snapshot FROM navigation_versions WHERE submission_id=? AND revision=?",
                           (sid, payload.source_revision)).fetchone()
        if not source:
            raise HTTPException(404, "历史版本不存在，不能恢复")
        snapshot = json.loads(source["snapshot"])
        c.execute("DELETE FROM navigation_nodes WHERE submission_id=?", (sid,))
        c.execute("DELETE FROM navigation_media WHERE submission_id=?", (sid,))
        c.executemany("INSERT INTO navigation_nodes(submission_id,node_key,position,kind,floor,direction,description) VALUES(?,?,?,?,?,?,?)",
                      [(sid, n["node_key"], n["position"], n["kind"], n["floor"], n["direction"], n["description"]) for n in snapshot["nodes"]])
        now = utcnow().isoformat()
        for photo in c.execute("SELECT * FROM navigation_version_media WHERE submission_id=? AND revision=?",
                               (sid, payload.source_revision)).fetchall():
            c.execute("INSERT INTO navigation_media(id,submission_id,node_key,revision,mime,size,data,sha256,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                      (new_id("navmedia"), sid, photo["node_key"], row["revision"] + 1, photo["mime"],
                       len(photo["data"]), photo["data"], sha256(photo["data"]).hexdigest(), now))
        c.execute("UPDATE navigation_submissions SET title=?,status='draft',revision=revision+1,privacy_confirmed=0,walkthrough_confirmed=0,"
                  "reviewer_id=NULL,reviewed_at=NULL,review_note=NULL,disabled_reason=NULL,ar_ready=0,updated_at=? WHERE id=?",
                  (snapshot["title"], now, sid))
        c.execute("UPDATE navigation_tasks SET status='claimed' WHERE id=?", (row["task_id"],))
        _event(c, row, user["id"], "revise", payload.model_dump())
        return _serialize(c, _load(c, sid))


@router.get("/submissions/{sid}/versions/{revision}/media/{node_key}")
def version_media(sid: str, revision: int, node_key: str, user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction() as c:
        _access(c, _load(c, sid), user["id"])
        row = c.execute("SELECT * FROM navigation_version_media WHERE submission_id=? AND revision=? AND node_key=?", (sid, revision, node_key)).fetchone()
        if not row:
            raise HTTPException(404, "历史照片不存在")
        return _photo(row["data"], row["mime"])


def _public(c, row, *, nodes=False):
    result = {k: row[k] for k in ("id", "title", "revision", "status", "updated_at")}
    result.update(verified_at=row["reviewed_at"], ar_ready=False, walkthrough_confirmed=bool(row["walkthrough_confirmed"]))
    points = [dict(n) for n in c.execute(
        "SELECT n.node_key,n.position,n.kind,n.floor,n.direction,n.description,m.id AS media_id "
        "FROM navigation_nodes n LEFT JOIN navigation_media m ON m.submission_id=n.submission_id AND m.node_key=n.node_key "
        "WHERE n.submission_id=? ORDER BY n.position", (row["id"],))]
    endpoint = lambda kind: next(({k: n[k] for k in ("description", "floor")} for n in points if n["kind"] == kind), None)
    result.update(start=endpoint("start"), end=endpoint("end"), node_count=len(points),
                  floors=list(dict.fromkeys(n["floor"] for n in points if n["floor"])),
                  has_stairs=any(n["kind"] == "stairs" for n in points))
    if nodes:
        result["nodes"] = points
    return result


def _published(c, rid, uid):
    row = _load(c, rid)
    if row["status"] != "published" or row["hospital_id"] != _perms(c, uid)["hospital_id"]:
        raise HTTPException(404, "路线不存在或已停用，请返回选择其他路线")
    return row


@router.get("/routes")
def routes(user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction() as c:
        rows = c.execute("SELECT s.* FROM navigation_submissions s JOIN navigation_tasks t ON t.id=s.task_id "
                         "WHERE t.hospital_id=? AND s.status='published' ORDER BY s.updated_at DESC", (_perms(c, user["id"])["hospital_id"],))
        return {"items": [_public(c, r) for r in rows], "ar_preview_only": True}


@router.get("/routes/{rid}")
def route(rid: str, user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction() as c:
        return _public(c, _published(c, rid, user["id"]), nodes=True)


@router.post("/routes/{rid}/feedback", status_code=201)
def feedback(rid: str, payload: FeedbackInput, user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction(write=True) as c:
        previous = c.execute("SELECT f.* FROM navigation_feedback_requests r JOIN navigation_feedback f ON f.id=r.feedback_id "
                             "WHERE r.user_id=? AND r.request_id=?", (user["id"], payload.request_id)).fetchone()
        if previous:
            if (previous["route_id"], previous["category"], previous["note"]) != (rid, payload.category, payload.note):
                raise HTTPException(409, "反馈编号已用于其他内容")
            return {"id": previous["id"], "accepted": True}
        _published(c, rid, user["id"])
        fid = new_id("navfb")
        c.execute("INSERT INTO navigation_feedback VALUES(?,?,?,?,?,?)", (fid, rid, user["id"], payload.category, payload.note, utcnow().isoformat()))
        c.execute("INSERT INTO navigation_feedback_requests VALUES(?,?,?)", (user["id"], payload.request_id, fid))
        audit(c, user["id"], "navigation_feedback", rid)
        return {"id": fid, "accepted": True}

