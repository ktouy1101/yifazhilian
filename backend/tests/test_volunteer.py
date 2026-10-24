"""P2: volunteer application, approval, and the collection permission it unlocks."""
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import AISettings
from app.db import Database, DEFAULT_DB_PATH
from app.main import create_app

ADMIN_PHONE = "13900000001"
VOLUNTEER_PHONE = "13900000002"


@pytest.fixture
def rig(tmp_path, monkeypatch):
    connect = sqlite3.connect

    def isolated(path, *args, **kwargs):
        assert Path(path).resolve() != DEFAULT_DB_PATH.resolve()
        return connect(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", isolated)
    monkeypatch.setenv("YIFAZHILIAN_ADMIN_PHONE", ADMIN_PHONE)
    db = Database(tmp_path / "volunteer.sqlite3")
    with TestClient(create_app(db, ai_settings=AISettings())) as client:
        yield client, db


def login(client, phone):
    code = client.post("/api/v1/auth/send-code", json={"phone": phone}).json()["dev_code"]
    token = client.post("/api/v1/auth/phone-login",
                        json={"phone": phone, "code": code}).json()["access_token"]
    return {"Authorization": "Bearer " + token}


def capabilities(client, headers):
    return client.get("/api/v1/users/me", headers=headers).json()["capabilities"]


def apply(client, headers, **overrides):
    payload = {"hospital_id": "demo-hospital", "real_name": "张小明", "training_confirmed": True}
    payload.update(overrides)
    return client.post("/api/v1/volunteer/apply", headers=headers, json=payload)


def test_application_starts_pending_without_collection_rights(rig):
    client, _ = rig
    headers = login(client, VOLUNTEER_PHONE)
    assert apply(client, headers).status_code == 201

    profile = client.get("/api/v1/volunteer/me", headers=headers).json()
    assert profile["profile"]["status"] == "pending"
    assert profile["capabilities"]["can_collect"] is False

    # 未通过审核时，采集接口按现有规则拒绝
    denied = client.post("/api/v1/navigation/submissions", headers=headers,
                         json={"task_id": "task-lab-a", "title": "草稿", "request_id": "r1"})
    assert denied.status_code == 403


def test_admin_approval_grants_collection_permission(rig):
    client, _ = rig
    volunteer = login(client, VOLUNTEER_PHONE)
    apply(client, volunteer)
    admin = login(client, ADMIN_PHONE)

    queue = client.get("/api/v1/admin/volunteers", headers=admin).json()["items"]
    assert [item["status"] for item in queue] == ["pending"]

    user_id = capabilities(client, volunteer)  # 确认能力前后变化
    reviewed = client.post(f"/api/v1/admin/volunteers/{queue[0]['user_id']}/review",
                           headers=admin, json={"decision": "approve", "note": "材料齐全"})
    assert reviewed.status_code == 200
    assert user_id["can_collect"] is False
    assert capabilities(client, volunteer)["can_collect"] is True

    claimed = client.post("/api/v1/navigation/tasks/task-lab-a/claim", headers=volunteer)
    assert claimed.status_code == 200, claimed.text
    created = client.post("/api/v1/navigation/submissions", headers=volunteer,
                          json={"task_id": "task-lab-a", "title": "一层大厅到检验科", "request_id": "r1"})
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "draft"


def test_rejection_keeps_permission_off_and_allows_reapplying(rig):
    client, _ = rig
    volunteer = login(client, VOLUNTEER_PHONE)
    apply(client, volunteer)
    admin = login(client, ADMIN_PHONE)
    user_id = client.get("/api/v1/volunteer/me", headers=volunteer).json()["profile"]["user_id"]

    rejected = client.post(f"/api/v1/admin/volunteers/{user_id}/review", headers=admin,
                           json={"decision": "reject", "note": "培训未完成"})
    assert rejected.status_code == 200
    assert capabilities(client, volunteer)["can_collect"] is False
    assert apply(client, volunteer).status_code == 201
    assert client.get("/api/v1/volunteer/me", headers=volunteer).json()["profile"]["status"] == "pending"


def test_application_rules(rig):
    client, _ = rig
    headers = login(client, VOLUNTEER_PHONE)
    assert apply(client, headers, training_confirmed=False).status_code == 422
    assert apply(client, headers, real_name="张").status_code == 422
    assert apply(client, headers).status_code == 201
    assert apply(client, headers).status_code == 409  # 重复提交


def test_only_reviewers_may_approve_and_nobody_approves_themselves(rig):
    client, _ = rig
    volunteer = login(client, VOLUNTEER_PHONE)
    apply(client, volunteer)
    admin = login(client, ADMIN_PHONE)
    user_id = client.get("/api/v1/volunteer/me", headers=volunteer).json()["profile"]["user_id"]

    assert client.get("/api/v1/admin/volunteers", headers=volunteer).status_code == 403
    assert client.post(f"/api/v1/admin/volunteers/{user_id}/review", headers=volunteer,
                       json={"decision": "approve"}).status_code == 403

    # 管理员自己申请也不能自己批
    apply(client, admin, real_name="李管理")
    admin_id = client.get("/api/v1/volunteer/me", headers=admin).json()["profile"]["user_id"]
    assert client.post(f"/api/v1/admin/volunteers/{admin_id}/review", headers=admin,
                       json={"decision": "approve"}).status_code == 400
