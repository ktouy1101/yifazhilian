"""密码登录：管理员开通、账号自设、错误密码拒绝。"""
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
    db = Database(tmp_path / "password.sqlite3")
    with TestClient(create_app(db, ai_settings=AISettings())) as client:
        yield client, db


def login_by_code(client, phone):
    code = client.post("/api/v1/auth/send-code", json={"phone": phone}).json()["dev_code"]
    body = client.post("/api/v1/auth/phone-login", json={"phone": phone, "code": code}).json()
    return {"Authorization": "Bearer " + body["access_token"]}


def test_admin_sets_password_then_user_logs_in_with_it(rig):
    client, _ = rig
    admin = login_by_code(client, ADMIN_PHONE)
    user = login_by_code(client, USER_PHONE)
    uid = client.get("/api/v1/users/me", headers=user).json()["id"]

    # 还没设密码时，密码登录必须失败
    assert client.post("/api/v1/auth/password-login",
                       json={"phone": USER_PHONE, "password": "abc12345"}).status_code == 401

    set_response = client.post(f"/api/v1/admin/users/{uid}/password", headers=admin,
                               json={"password": "abc12345"})
    assert set_response.status_code == 200

    ok = client.post("/api/v1/auth/password-login",
                     json={"phone": USER_PHONE, "password": "abc12345"})
    assert ok.status_code == 200
    assert ok.json()["access_token"]
    assert client.post("/api/v1/auth/password-login",
                       json={"phone": USER_PHONE, "password": "wrong-pass"}).status_code == 401


def test_password_login_rejects_unknown_phone(rig):
    client, _ = rig
    response = client.post("/api/v1/auth/password-login",
                           json={"phone": "13900000099", "password": "whatever1"})
    assert response.status_code == 401


def test_logged_in_user_can_set_own_password(rig):
    client, _ = rig
    user = login_by_code(client, USER_PHONE)
    assert client.post("/api/v1/auth/password", headers=user,
                       json={"password": "self-set-1"}).status_code == 200
    assert client.post("/api/v1/auth/password-login",
                       json={"phone": USER_PHONE, "password": "self-set-1"}).status_code == 200


def test_non_reviewer_cannot_set_others_password(rig):
    client, _ = rig
    admin = login_by_code(client, ADMIN_PHONE)
    user = login_by_code(client, USER_PHONE)
    uid = client.get("/api/v1/users/me", headers=user).json()["id"]
    response = client.post(f"/api/v1/admin/users/{uid}/password", headers=user,
                           json={"password": "hacked123"})
    assert response.status_code == 403
    assert client.post(f"/api/v1/admin/users/{uid}/password", headers=admin,
                       json={"password": "12345"}).status_code == 422  # 太短
