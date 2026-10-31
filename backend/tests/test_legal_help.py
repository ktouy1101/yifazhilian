"""P4: 律师凭证核验与法律帮扶工单。"""
from io import BytesIO
from pathlib import Path
import sqlite3

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from app.config import AISettings
from app.db import Database, DEFAULT_DB_PATH
from app.main import create_app

ADMIN_PHONE = "13900000001"
VOLUNTEER_PHONE = "13900000002"
PATIENT_PHONE = "13900000003"


@pytest.fixture
def rig(tmp_path, monkeypatch):
    connect = sqlite3.connect

    def isolated(path, *args, **kwargs):
        assert Path(path).resolve() != DEFAULT_DB_PATH.resolve()
        return connect(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", isolated)
    monkeypatch.setenv("YIFAZHILIAN_ADMIN_PHONE", ADMIN_PHONE)
    db = Database(tmp_path / "legal-help.sqlite3")
    with TestClient(create_app(db, ai_settings=AISettings())) as client:
        yield client, db


def login(client, phone):
    code = client.post("/api/v1/auth/send-code", json={"phone": phone}).json()["dev_code"]
    token = client.post("/api/v1/auth/phone-login",
                        json={"phone": phone, "code": code}).json()["access_token"]
    return {"Authorization": "Bearer " + token}


def caps(client, headers):
    return client.get("/api/v1/users/me", headers=headers).json()["capabilities"]


def png_bytes():
    buffer = BytesIO()
    Image.new("RGB", (40, 30), (240, 240, 240)).save(buffer, format="PNG")
    return buffer.getvalue()


def become_approved_volunteer(client, admin, volunteer):
    client.post("/api/v1/volunteer/apply", headers=volunteer,
                json={"hospital_id": "demo-hospital", "real_name": "王律师", "training_confirmed": True})
    uid = client.get("/api/v1/volunteer/me", headers=volunteer).json()["profile"]["user_id"]
    client.post(f"/api/v1/admin/volunteers/{uid}/review", headers=admin,
                json={"decision": "approve", "note": "材料齐全"})
    return uid


def upload_credential(client, headers, kind="lawyer_license"):
    return client.post("/api/v1/volunteer/credentials", headers=headers,
                       data={"kind": kind},
                       files={"file": ("license.png", png_bytes(), "image/png")})


def test_credential_flow_gates_legal_help(rig):
    client, _ = rig
    admin = login(client, ADMIN_PHONE)
    volunteer = login(client, VOLUNTEER_PHONE)
    patient = login(client, PATIENT_PHONE)

    become_approved_volunteer(client, admin, volunteer)
    assert caps(client, volunteer)["can_help_legal"] is False
    # 没有已核验志愿者时，患者的问题仍然入队，只是没人能接
    queued = client.post("/api/v1/legal-help/requests", headers=patient,
                         json={"topic": "病历", "text": "医院不给复印病历怎么办"})
    assert queued.status_code == 201
    assert client.get("/api/v1/legal-help/queue", headers=volunteer).status_code == 403

    created = upload_credential(client, volunteer)
    assert created.status_code == 201, created.text
    cid = created.json()["id"]
    assert caps(client, volunteer)["can_help_legal"] is False  # 还没核验

    queue = client.get("/api/v1/admin/credentials", headers=admin).json()["items"]
    assert [item["id"] for item in queue] == [cid]
    # 审核员能看图，普通账号不能
    assert client.get(f"/api/v1/admin/credentials/{cid}/image", headers=admin).status_code == 200
    assert client.get(f"/api/v1/admin/credentials/{cid}/image", headers=volunteer).status_code == 403

    reviewed = client.post(f"/api/v1/admin/credentials/{cid}/review", headers=admin,
                           json={"decision": "approve", "note": "执业证清晰"})
    assert reviewed.status_code == 200
    assert caps(client, volunteer)["can_help_legal"] is True


def test_help_request_claim_reply_and_admin_view(rig):
    client, _ = rig
    admin = login(client, ADMIN_PHONE)
    volunteer = login(client, VOLUNTEER_PHONE)
    patient = login(client, PATIENT_PHONE)
    become_approved_volunteer(client, admin, volunteer)
    cid = upload_credential(client, volunteer).json()["id"]
    client.post(f"/api/v1/admin/credentials/{cid}/review", headers=admin, json={"decision": "approve"})

    created = client.post("/api/v1/legal-help/requests", headers=patient,
                          json={"topic": "病历复印", "text": "医院不给复印病历，我该怎么办"})
    assert created.status_code == 201, created.text
    rid = created.json()["id"]

    queue = client.get("/api/v1/legal-help/queue", headers=volunteer).json()["items"]
    assert [item["id"] for item in queue] == [rid]
    # 患者自己没有接单权限
    assert client.get("/api/v1/legal-help/queue", headers=patient).status_code == 403

    assert client.post(f"/api/v1/legal-help/requests/{rid}/claim", headers=volunteer).status_code == 200
    reply = client.post(f"/api/v1/legal-help/requests/{rid}/messages", headers=volunteer,
                        json={"text": "先书面申请，医院拒绝可向医务科投诉。"})
    assert reply.status_code == 201
    assert reply.json()["status"] == "answered"

    detail = client.get(f"/api/v1/legal-help/requests/{rid}", headers=patient).json()
    assert detail["status"] == "answered"
    assert [item["role"] for item in detail["messages"]] == ["volunteer"]
    assert detail["messages"][0]["text"].startswith("先书面申请")

    admin_view = client.get("/api/v1/admin/legal-help", headers=admin).json()["items"]
    assert admin_view[0]["id"] == rid and admin_view[0]["message_count"] == 1
    # 工单里只有问题文本，不含手机号或病历字段
    assert set(admin_view[0]) == {"id", "topic", "text", "status", "volunteer_id",
                                  "created_at", "updated_at", "message_count"}


def test_unverified_volunteer_cannot_claim_and_outsiders_cannot_read(rig):
    client, _ = rig
    admin = login(client, ADMIN_PHONE)
    volunteer = login(client, VOLUNTEER_PHONE)
    patient = login(client, PATIENT_PHONE)
    other = login(client, "13900000009")

    become_approved_volunteer(client, admin, volunteer)  # 通过志愿者，但没有凭证
    assert client.get("/api/v1/legal-help/queue", headers=volunteer).status_code == 403

    cid = upload_credential(client, volunteer).json()["id"]
    client.post(f"/api/v1/admin/credentials/{cid}/review", headers=admin, json={"decision": "approve"})
    rid = client.post("/api/v1/legal-help/requests", headers=patient,
                      json={"topic": "知情同意", "text": "手术前签字要注意什么"}).json()["id"]
    assert client.get(f"/api/v1/legal-help/requests/{rid}", headers=other).status_code == 403


def test_credential_rejects_non_image_and_second_review(rig):
    client, _ = rig
    admin = login(client, ADMIN_PHONE)
    volunteer = login(client, VOLUNTEER_PHONE)
    become_approved_volunteer(client, admin, volunteer)

    bad = client.post("/api/v1/volunteer/credentials", headers=volunteer, data={"kind": "lawyer_license"},
                      files={"file": ("x.txt", b"not an image", "text/plain")})
    assert bad.status_code == 422
    assert client.post("/api/v1/volunteer/credentials", headers=volunteer, data={"kind": "other"},
                       files={"file": ("x.png", png_bytes(), "image/png")}).status_code == 422

    cid = upload_credential(client, volunteer).json()["id"]
    assert client.post(f"/api/v1/admin/credentials/{cid}/review", headers=admin,
                       json={"decision": "approve"}).status_code == 200
    assert client.post(f"/api/v1/admin/credentials/{cid}/review", headers=admin,
                       json={"decision": "approve"}).status_code == 409
