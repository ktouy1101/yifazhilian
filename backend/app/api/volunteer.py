"""P2: 志愿者申请与审核。

志愿者提交申请（医院、实名、培训确认）→ 审核员通过后自动获得导航采集权限。
权限仍以 navigation_memberships 为准，申请状态只是入口条件。
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import current_user, get_database, require_reviewer
from app.db import Database, audit, utcnow
from app.schemas import VolunteerApplyInput, VolunteerReviewInput
from app.services import roles

router = APIRouter(prefix="/volunteer", tags=["volunteer"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])

MAX_ACTIVE = ("pending", "approved")


def _serialize(row):
    return {
        "user_id": row["user_id"], "hospital_id": row["hospital_id"], "kinds": row["kinds"],
        "real_name": row["real_name"], "status": row["status"], "note": row["note"],
        "reviewed_by": row["reviewed_by"], "reviewed_at": row["reviewed_at"],
        "updated_at": row["updated_at"],
    }


@router.get("/me")
def my_application(user=Depends(current_user), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        row = roles.volunteer_profile(connection, user["id"])
        capabilities = roles.capabilities(connection, user)
    return {"profile": _serialize(row) if row else None, "capabilities": capabilities}


@router.post("/apply", status_code=201)
def apply(payload: VolunteerApplyInput, user=Depends(current_user),
          database: Database = Depends(get_database)):
    if not payload.training_confirmed:
        raise HTTPException(422, "需要先完成培训确认才能提交申请")
    with database.transaction(write=True) as connection:
        existing = roles.volunteer_profile(connection, user["id"])
        if existing is not None and existing["status"] in MAX_ACTIVE:
            raise HTTPException(409, "已提交申请或已通过审核，无需重复提交")
        now = utcnow().isoformat()
        if existing is None:
            connection.execute(
                "INSERT INTO volunteer_profiles(user_id,hospital_id,kinds,real_name,status,updated_at) "
                "VALUES(?,?,?,?,'pending',?)",
                (user["id"], payload.hospital_id, "guide", payload.real_name, now))
        else:
            # 被拒绝后允许重新申请：清掉上一次的审核结论。
            connection.execute(
                "UPDATE volunteer_profiles SET hospital_id=?, kinds=?, real_name=?, status='pending', "
                "note=NULL, reviewed_by=NULL, reviewed_at=NULL, updated_at=? WHERE user_id=?",
                (payload.hospital_id, "guide", payload.real_name, now, user["id"]))
        audit(connection, user["id"], "volunteer_apply", user["id"])
    return {"status": "pending"}


@admin_router.get("/volunteers")
def list_applications(status: str = Query(default="pending", pattern=r"^(pending|approved|rejected)$"),
                      user=Depends(require_reviewer), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT p.*, u.display_name FROM volunteer_profiles p JOIN users u ON u.id=p.user_id "
            "WHERE p.status=? ORDER BY p.updated_at DESC", (status,)).fetchall()
    items = []
    for row in rows:
        item = _serialize(row)
        item["display_name"] = row["display_name"]
        items.append(item)
    return {"items": items}


@admin_router.post("/volunteers/{user_id}/review")
def review_application(user_id: str, payload: VolunteerReviewInput,
                       user=Depends(require_reviewer), database: Database = Depends(get_database)):
    if user_id == user["id"]:
        raise HTTPException(400, "不能审核自己的申请")
    with database.transaction(write=True) as connection:
        row = roles.volunteer_profile(connection, user_id)
        if row is None:
            raise HTTPException(404, "申请不存在")
        if row["status"] != "pending":
            raise HTTPException(409, "该申请已处理")
        now = utcnow().isoformat()
        approved = payload.decision == "approve"
        connection.execute(
            "UPDATE volunteer_profiles SET status=?, note=?, reviewed_by=?, reviewed_at=?, updated_at=? "
            "WHERE user_id=?",
            ("approved" if approved else "rejected", payload.note, user["id"], now, now, user_id))
        if approved:
            roles.grant(connection, user_id, roles.VOLUNTEER)
            # 只有审核通过才写采集权限；采集提交后仍需另一位审核员发布。
            connection.execute(
                "INSERT INTO navigation_memberships(user_id,hospital_id,can_collect,can_review) "
                "VALUES(?,?,1,0) ON CONFLICT(user_id) DO UPDATE SET can_collect=1",
                (user_id, row["hospital_id"]))
        else:
            connection.execute(
                "UPDATE navigation_memberships SET can_collect=0 WHERE user_id=?", (user_id,))
        audit(connection, user["id"], "volunteer_review", user_id)
    return {"user_id": user_id, "status": "approved" if approved else "rejected"}
