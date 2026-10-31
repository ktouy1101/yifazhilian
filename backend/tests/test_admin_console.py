"""P3: 审核台数据接口（概览/反馈/审计/角色）。"""
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import AISettings
from app.db import Database, DEFAULT_DB_PATH
from app.main import create_app

ADMIN_PHONE = "13900000001"
USER_PHONE = "13900000002"


@pytest.fixture
def rig(tmp_path, monkeypatch):
    connect = sqlite3.connect

    def isolated(path, *args, **kwargs):
        assert Path(path).resolve() != DEFAULT_DB_PATH.resolve()
        return connect(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", isolated)
    monkeypatch.setenv("YIFAZHILIAN_ADMIN_PHONE", ADMIN_PHONE)
    db = Database(tmp_path / "admin.sqlite3")
    with TestClient(create_app(db, ai_settings=AISettings())) as client:
        yield client, db


def login(client, phone):
    code = client.post("/api/v1/auth/send-code", json={"phone": phone}).json()["dev_code"]
    token = client.post("/api/v1/auth/phone-login",
                        json={"phone": phone, "code": code}).json()["access_token"]
    return {"Authorization": "Bearer " + token}


def me(client, headers):
    return client.get("/api/v1/users/me", headers=headers).json()


def test_console_requires_reviewer(rig):
    client, _ = rig
    plain = login(client, USER_PHONE)
    for path in ("/api/v1/admin/overview", "/api/v1/admin/feedback", "/api/v1/admin/audit"):
        assert client.get(path, headers=plain).status_code == 403
    assert client.get("/api/v1/admin/overview").status_code == 401


def test_overview_counts_and_queues(rig):
    client, _ = rig
    admin = login(client, ADMIN_PHONE)
    data = client.get("/api/v1/admin/overview", headers=admin).json()
    assert set(data) == {"routes_pending", "routes_published", "volunteers_pending",
                         "credentials_pending", "help_open", "feedback_total", "users_total"}
    assert data["users_total"] >= 2
    assert client.get("/api/v1/admin/feedback", headers=admin).json()["items"] == []


def test_audit_records_admin_actions(rig):
    client, _ = rig
    admin = login(client, ADMIN_PHONE)
    user = login(client, USER_PHONE)
    target = me(client, user)["id"]
    granted = client.post(f"/api/v1/admin/users/{target}/roles", headers=admin,
                          json={"role": "volunteer", "action": "grant"})
    assert granted.status_code == 200

    items = client.get("/api/v1/admin/audit?limit=10", headers=admin).json()["items"]
    assert any(item["action"] == "admin_role_grant" and item["object_id"] == target for item in items)


def test_role_grant_and_revoke_change_capabilities(rig):
    client, _ = rig
    admin = login(client, ADMIN_PHONE)
    user = login(client, USER_PHONE)
    target = me(client, user)["id"]

    client.post(f"/api/v1/admin/users/{target}/roles", headers=admin,
                json={"role": "reviewer", "action": "grant"})
    assert me(client, user)["capabilities"]["is_reviewer"] is True
    # 新审核员立刻能进只读接口
    assert client.get("/api/v1/admin/overview", headers=user).status_code == 200

    client.post(f"/api/v1/admin/users/{target}/roles", headers=admin,
                json={"role": "reviewer", "action": "revoke"})
    assert me(client, user)["capabilities"]["is_reviewer"] is False
    assert client.get("/api/v1/admin/overview", headers=user).status_code == 403


def test_admin_cannot_revoke_own_reviewer_role(rig):
    client, _ = rig
    admin = login(client, ADMIN_PHONE)
    own_id = me(client, admin)["id"]
    response = client.post(f"/api/v1/admin/users/{own_id}/roles", headers=admin,
                           json={"role": "reviewer", "action": "revoke"})
    assert response.status_code == 400


def test_role_change_rejects_unknown_user(rig):
    client, _ = rig
    admin = login(client, ADMIN_PHONE)
    response = client.post("/api/v1/admin/users/nobody/roles", headers=admin,
                           json={"role": "volunteer", "action": "grant"})
    assert response.status_code == 404


def test_admin_relogin_repairs_stale_membership(rig):
    """旧库里 can_review=0 的成员行，要在管理员再次登录时被修正。"""
    client, db = rig
    headers = login(client, ADMIN_PHONE)
    uid = me(client, headers)["id"]
    with db.transaction(write=True) as connection:
        connection.execute("UPDATE navigation_memberships SET can_review=0 WHERE user_id=?", (uid,))

    login(client, ADMIN_PHONE)  # 重新登录
    with db.transaction() as connection:
        row = connection.execute(
            "SELECT can_review FROM navigation_memberships WHERE user_id=?", (uid,)).fetchone()
        assert row[0] == 1


def test_reviewer_role_alone_grants_navigation_review(rig):
    """即使成员位仍是 0，reviewer 角色也应被导航判权识别，避免显示成“体验员”。"""
    client, db = rig
    admin = login(client, ADMIN_PHONE)
    uid = me(client, admin)["id"]
    with db.transaction(write=True) as connection:
        connection.execute("UPDATE navigation_memberships SET can_review=0 WHERE user_id=?", (uid,))

    perms = client.get("/api/v1/navigation/me", headers=admin).json()["permissions"]
    assert perms["review"] is True
    assert client.get("/api/v1/navigation/submissions?scope=review", headers=admin).status_code == 200
