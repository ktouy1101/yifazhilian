"""P3: 审核台的数据接口。

路线审核复用 navigation 既有接口（scope=review / {sid}/review），这里只补
概览、反馈、审计和角色管理，避免出现第二套审核逻辑。
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.dependencies import get_database, require_reviewer
from app.db import Database, audit, utcnow
from app.schemas import RoleInput, SetPasswordInput
from app.services import passwords, roles

router = APIRouter(prefix="/admin", tags=["admin"])

ROLE_NAMES = ("volunteer", "reviewer")


@router.get("/overview")
def overview(user=Depends(require_reviewer), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        def count(sql, params=()):
            return connection.execute(sql, params).fetchone()[0]
        return {
            "routes_pending": count("SELECT count(*) FROM navigation_submissions WHERE status='submitted'"),
            "routes_published": count("SELECT count(*) FROM navigation_submissions WHERE status='published'"),
            "volunteers_pending": count("SELECT count(*) FROM volunteer_profiles WHERE status='pending'"),
            "credentials_pending": count("SELECT count(*) FROM volunteer_credentials WHERE status='pending'"),
            "help_open": count("SELECT count(*) FROM legal_help_requests WHERE status IN ('open','claimed')"),
            "feedback_total": count("SELECT count(*) FROM navigation_feedback"),
            "users_total": count("SELECT count(*) FROM users WHERE deleted_at IS NULL"),
        }


@router.get("/feedback")
def list_feedback(limit: int = Query(default=20, ge=1, le=100),
                  user=Depends(require_reviewer), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        rows = connection.execute(
            "SELECT f.id,f.route_id,f.category,f.note,f.created_at,r.title "
            "FROM navigation_feedback f LEFT JOIN navigation_submissions r ON r.id=f.route_id "
            "ORDER BY f.created_at DESC LIMIT ?", (limit,)).fetchall()
    return {"items": [{"id": row["id"], "route_id": row["route_id"], "route_title": row["title"] or "",
                       "category": row["category"], "note": row["note"],
                       "created_at": row["created_at"]} for row in rows]}


@router.get("/audit")
def audit_log(limit: int = Query(default=30, ge=1, le=200), action: str | None = None,
              user=Depends(require_reviewer), database: Database = Depends(get_database)):
    with database.transaction() as connection:
        if action:
            rows = connection.execute(
                "SELECT id,user_id,action,object_id,created_at FROM audit_events "
                "WHERE action=? ORDER BY created_at DESC LIMIT ?", (action, limit)).fetchall()
        else:
            rows = connection.execute(
                "SELECT id,user_id,action,object_id,created_at FROM audit_events "
                "ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.post("/users/{user_id}/roles")
def set_role(user_id: str, payload: RoleInput, user=Depends(require_reviewer),
             database: Database = Depends(get_database)):
    """授予/撤销能力。拒绝把自己降级，避免唯一管理员把自己锁在门外。"""
    if payload.role not in ROLE_NAMES:
        raise HTTPException(422, "只支持 volunteer 或 reviewer")
    if user_id == user["id"] and payload.role == "reviewer" and payload.action == "revoke":
        raise HTTPException(400, "不能撤销自己的审核员权限")
    with database.transaction(write=True) as connection:
        row = connection.execute(
            "SELECT id FROM users WHERE id=? AND deleted_at IS NULL", (user_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "账号不存在或已注销")
        if payload.action == "grant":
            roles.grant(connection, user_id, payload.role, granted_by=user["id"])
            if payload.role == "reviewer":
                connection.execute(
                    "INSERT INTO navigation_memberships(user_id,can_collect,can_review) VALUES(?,0,1) "
                    "ON CONFLICT(user_id) DO UPDATE SET can_review=1", (user_id,))
        else:
            roles.revoke(connection, user_id, payload.role)
            if payload.role == "reviewer":
                # 能力是每次请求现算的，撤销立即生效；不必踢掉会话。
                connection.execute(
                    "UPDATE navigation_memberships SET can_review=0 WHERE user_id=?", (user_id,))
        audit(connection, user["id"], f"admin_role_{payload.action}", user_id)
    return {"user_id": user_id, "role": payload.role, "action": payload.action,
            "at": utcnow().isoformat()}


@router.post("/users/{user_id}/password")
def set_user_password(user_id: str, payload: SetPasswordInput,
                      user=Depends(require_reviewer), database: Database = Depends(get_database)):
    """审核员为账号设置/重置密码。用于给已有账号开通密码登录。"""
    with database.transaction(write=True) as connection:
        row = connection.execute(
            "SELECT id FROM users WHERE id=? AND deleted_at IS NULL", (user_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "账号不存在或已注销")
        connection.execute("UPDATE users SET password_hash=? WHERE id=?",
                           (passwords.hash_password(payload.password), user_id))
        audit(connection, user["id"], "admin_password_set", user_id)
    return {"user_id": user_id, "ok": True}
