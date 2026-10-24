"""P1 identity base: roles, capabilities and the admin-only surface."""
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import AISettings
from app.db import Database, DEFAULT_DB_PATH
from app.main import create_app

ADMIN_PHONE = "13900000001"


@pytest.fixture
def rig(tmp_path, monkeypatch):
    connect = sqlite3.connect

    def isolated(path, *args, **kwargs):
        assert Path(path).resolve() != DEFAULT_DB_PATH.resolve()
        return connect(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", isolated)
    db = Database(tmp_path / "roles.sqlite3")
    with TestClient(create_app(db, ai_settings=AISettings())) as client:
        yield client, db


def login_by_phone(client, phone):
    code = client.post("/api/v1/auth/send-code", json={"phone": phone}).json()["dev_code"]
    response = client.post("/api/v1/auth/phone-login", json={"phone": phone, "code": code})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def test_admin_phone_gets_reviewer_and_admin_surface(rig, monkeypatch):
    client, _ = rig
    monkeypatch.setenv("YIFAZHILIAN_ADMIN_PHONE", ADMIN_PHONE)
    headers = login_by_phone(client, ADMIN_PHONE)
    me = client.get("/api/v1/users/me", headers=headers).json()
    assert me["capabilities"]["is_reviewer"] is True
    assert "reviewer" in me["capabilities"]["roles"]
    assert client.get("/api/v1/admin/ping", headers=headers).status_code == 200


def test_ordinary_user_is_not_an_admin(rig, monkeypatch):
    client, _ = rig
    monkeypatch.setenv("YIFAZHILIAN_ADMIN_PHONE", ADMIN_PHONE)
    headers = login_by_phone(client, "13900000002")
    me = client.get("/api/v1/users/me", headers=headers).json()
    assert me["capabilities"]["is_reviewer"] is False
    assert client.get("/api/v1/admin/ping", headers=headers).status_code == 403


def test_admin_list_is_configuration_not_self_service(rig, monkeypatch):
    client, _ = rig
    monkeypatch.setenv("YIFAZHILIAN_ADMIN_PHONE", "")
    headers = login_by_phone(client, ADMIN_PHONE)
    assert client.get("/api/v1/admin/ping", headers=headers).status_code == 403


def test_demo_reviewer_is_local_only(rig, tmp_path):
    """演示审核员账号可以从开发机本机登录，但局域网客户端一律拒绝。"""
    client, db = rig
    local = client.post("/api/v1/auth/demo-login",
                        json={"demo_alias": "demo-reviewer-001", "role": "volunteer"})
    assert local.status_code == 200, local.text

    with TestClient(create_app(db, ai_settings=AISettings()),
                    client=("192.168.1.50", 50000)) as remote:
        response = remote.post("/api/v1/auth/demo-login",
                               json={"demo_alias": "demo-reviewer-001", "role": "volunteer"})
        assert response.status_code == 403
        assert "本机" in response.json()["detail"]


def test_demo_login_closes_with_demo_auth(rig, monkeypatch):
    client, _ = rig
    monkeypatch.setenv("YIFAZHILIAN_DEMO_AUTH", "0")
    response = client.post("/api/v1/auth/demo-login", json={"demo_alias": "demo-patient-001"})
    assert response.status_code == 403


def test_volunteer_capabilities_expose_collection(rig):
    client, _ = rig
    response = client.post("/api/v1/auth/demo-login",
                           json={"demo_alias": "demo-volunteer-001", "role": "volunteer"})
    assert response.status_code == 200, response.text
    headers = {"Authorization": "Bearer " + response.json()["access_token"]}
    capabilities = client.get("/api/v1/users/me", headers=headers).json()["capabilities"]
    assert capabilities["is_volunteer"] is True
    assert capabilities["can_collect"] is True
    assert capabilities["is_reviewer"] is False
    assert client.get("/api/v1/admin/ping", headers=headers).status_code == 403


def test_capabilities_require_login(rig):
    client, _ = rig
    assert client.get("/api/v1/users/me").status_code == 401
    assert client.get("/api/v1/admin/ping").status_code == 401


def test_admin_delete_is_soft_and_audit_survives(rig, monkeypatch):
    client, db = rig
    monkeypatch.setenv("YIFAZHILIAN_ADMIN_PHONE", ADMIN_PHONE)
    admin = login_by_phone(client, ADMIN_PHONE)
    victim = login_by_phone(client, "13900000008")
    victim_id = client.get("/api/v1/users/me", headers=victim).json()["id"]

    response = client.delete(f"/api/v1/admin/users/{victim_id}", headers=admin)
    assert response.status_code == 200, response.text
    # 令牌立即失效
    assert client.get("/api/v1/users/me", headers=victim).status_code == 401
    # 手机号被释放，重新登录得到新账号
    again = login_by_phone(client, "13900000008")
    assert client.get("/api/v1/users/me", headers=again).json()["id"] != victim_id
    # 软删除：行还在、审计还在、没有悬空外键
    with db.transaction() as connection:
        row = connection.execute("SELECT id,deleted_at,phone FROM users WHERE id=?", (victim_id,)).fetchone()
        assert row["deleted_at"] and row["phone"] is None
        assert connection.execute(
            "SELECT count(*) FROM audit_events WHERE object_id=? AND action='admin_delete_user'",
            (victim_id,)).fetchone()[0] == 1
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_admin_cannot_delete_self(rig, monkeypatch):
    client, _ = rig
    monkeypatch.setenv("YIFAZHILIAN_ADMIN_PHONE", ADMIN_PHONE)
    admin = login_by_phone(client, ADMIN_PHONE)
    me = client.get("/api/v1/users/me", headers=admin).json()
    assert client.delete(f"/api/v1/admin/users/{me['id']}", headers=admin).status_code == 400


def test_ordinary_user_cannot_delete_accounts(rig, monkeypatch):
    client, _ = rig
    monkeypatch.setenv("YIFAZHILIAN_ADMIN_PHONE", ADMIN_PHONE)
    normal = login_by_phone(client, "13900000006")
    assert client.delete("/api/v1/admin/users/demo-patient-001", headers=normal).status_code == 403
