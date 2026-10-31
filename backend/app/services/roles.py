"""Capability resolution.

A user is not one role: the same person can be a patient, a navigation
volunteer and a legal volunteer. ``users.role`` stays the original
patient/volunteer column (it is a CHECK constraint), and every extra capability
lives in ``user_roles`` / ``volunteer_profiles`` / ``navigation_memberships``.

Everything here is server-side. Hiding a button in the client is never the
authorization.
"""
from app.config import admin_phones
from app.db import utcnow

REVIEWER = "reviewer"
VOLUNTEER = "volunteer"
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testserver", "testclient"})


def is_loopback(host: str | None) -> bool:
    """Only the developer machine may use the seeded reviewer demo account."""
    return (host or "").strip().lower() in LOOPBACK_HOSTS


def roles_of(connection, user_id: str) -> set[str]:
    return {row["role"] for row in
            connection.execute("SELECT role FROM user_roles WHERE user_id=?", (user_id,))}


def grant(connection, user_id: str, role: str, granted_by: str | None = None) -> None:
    connection.execute(
        "INSERT OR IGNORE INTO user_roles(user_id,role,granted_by,granted_at) VALUES(?,?,?,?)",
        (user_id, role, granted_by, utcnow().isoformat()))


def revoke(connection, user_id: str, role: str) -> None:
    connection.execute("DELETE FROM user_roles WHERE user_id=? AND role=?", (user_id, role))


def volunteer_profile(connection, user_id: str):
    return connection.execute(
        "SELECT * FROM volunteer_profiles WHERE user_id=?", (user_id,)).fetchone()


def capabilities(connection, user) -> dict:
    """What this account may do, computed from the database, not from the token."""
    roles = roles_of(connection, user["id"])
    member = connection.execute(
        "SELECT * FROM navigation_memberships WHERE user_id=?", (user["id"],)).fetchone()
    profile = volunteer_profile(connection, user["id"])
    status = profile["status"] if profile else "none"
    kinds = [kind for kind in ((profile["kinds"] if profile else "") or "").split(",") if kind]
    # 法律帮扶要求：志愿者档案已通过 + 声明 legal + 至少一张执业证已核验。
    credential = connection.execute(
        "SELECT 1 FROM volunteer_credentials WHERE user_id=? AND status='approved' LIMIT 1",
        (user["id"],)).fetchone()
    return {
        "roles": sorted(roles | ({user["role"]} if user.get("role") else set())),
        "is_reviewer": REVIEWER in roles or bool(member and member["can_review"]),
        "is_volunteer": VOLUNTEER in roles or user.get("role") == VOLUNTEER or status != "none",
        "volunteer_status": status,
        "volunteer_kinds": kinds,
        "can_collect": bool(member and member["can_collect"]),
        "can_help_legal": "legal" in kinds and status == "approved" and credential is not None,
    }


def grant_admin(connection, user, phone: str | None = None) -> bool:
    """Configured admin numbers become reviewers at login time.

    Deliberately not self-service: nothing in the client can make an account an
    admin, and an unknown phone simply gets no role.
    """
    phone = (phone or "").strip()
    if not phone or phone not in admin_phones():
        return False
    grant(connection, user["id"], REVIEWER)
    # 旧数据里可能已有 can_review=0 的成员行，必须覆盖而不是忽略，
    # 否则管理台能进、导航工作台却仍被当成"体验员"。
    connection.execute(
        "INSERT INTO navigation_memberships(user_id,can_collect,can_review) VALUES(?,0,1) "
        "ON CONFLICT(user_id) DO UPDATE SET can_review=1", (user["id"],))
    return True
