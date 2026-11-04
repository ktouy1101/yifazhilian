"""MySQL 后端集成测试。

默认跳过；设置 YIFAZHILIAN_TEST_MYSQL_URL 后运行，例如：
    YIFAZHILIAN_TEST_MYSQL_URL=mysql://root:root@127.0.0.1:3307 pytest tests/test_mysql_backend.py
每次会用随机库名建一个临时库，跑完删除。
"""
import os
import uuid

import pytest
from fastapi.testclient import TestClient
import pymysql

from app.config import AISettings
from app.db import Database
from app.main import create_app

MYSQL_URL = os.getenv("YIFAZHILIAN_TEST_MYSQL_URL", "").strip()
pytestmark = pytest.mark.skipif(not MYSQL_URL, reason="未设置 YIFAZHILIAN_TEST_MYSQL_URL")

ADMIN_PHONE = "13900000001"


def _url_with_db(name: str) -> str:
    base, _, _ = MYSQL_URL.rpartition("/")
    return f"{base}/{name}"


def _drop(url: str, name: str) -> None:
    parsed = pymysql.connect(
        host="127.0.0.1", port=3307, user="root", password="root", autocommit=True)
    try:
        with parsed.cursor() as cursor:
            cursor.execute(f"DROP DATABASE IF EXISTS `{name}`")
    finally:
        parsed.close()


@pytest.fixture
def mysql_client(monkeypatch):
    name = "yfz_test_" + uuid.uuid4().hex[:12]
    url = _url_with_db(name)
    monkeypatch.setenv("YIFAZHILIAN_DB_URL", url)
    monkeypatch.setenv("YIFAZHILIAN_ADMIN_PHONE", ADMIN_PHONE)
    monkeypatch.setenv("YIFAZHILIAN_DEMO_AUTH", "1")
    db = Database()
    with TestClient(create_app(db, ai_settings=AISettings())) as client:
        yield client
    _drop(url, name)


def login(client, phone):
    code = client.post("/api/v1/auth/send-code", json={"phone": phone}).json()["dev_code"]
    body = client.post("/api/v1/auth/phone-login", json={"phone": phone, "code": code}).json()
    return {"Authorization": "Bearer " + body["access_token"]}


def test_health_reports_mysql(mysql_client):
    payload = mysql_client.get("/api/v1/health").json()
    assert payload == {"status": "ok", "storage": "mysql"}


def test_login_and_capabilities_on_mysql(mysql_client):
    admin = login(mysql_client, ADMIN_PHONE)
    me = mysql_client.get("/api/v1/users/me", headers=admin).json()
    assert me["capabilities"]["is_reviewer"] is True


def test_legal_help_roundtrip_on_mysql(mysql_client):
    admin = login(mysql_client, ADMIN_PHONE)
    patient = login(mysql_client, "13900000077")
    created = mysql_client.post("/api/v1/legal-help/requests", headers=patient,
                                json={"topic": "MySQL", "text": "工单能否落到MySQL里"})
    assert created.status_code == 201
    rid = created.json()["id"]
    items = mysql_client.get("/api/v1/admin/legal-help", headers=admin).json()["items"]
    assert any(item["id"] == rid for item in items)
    detail = mysql_client.get(f"/api/v1/legal-help/requests/{rid}", headers=patient).json()
    assert detail["topic"] == "MySQL"


def test_navigation_base64_media_on_mysql(mysql_client):
    import base64
    import io

    from PIL import Image

    volunteer = mysql_client.post("/api/v1/auth/demo-login",
                                  json={"demo_alias": "demo-volunteer-001", "role": "volunteer"}).json()
    headers = {"Authorization": "Bearer " + volunteer["access_token"]}
    task = mysql_client.get("/api/v1/navigation/tasks", headers=headers).json()["items"][0]
    mysql_client.post(f"/api/v1/navigation/tasks/{task['id']}/claim", headers=headers)
    submission = mysql_client.post("/api/v1/navigation/submissions", headers=headers,
                                   json={"task_id": task["id"], "title": task["title"],
                                         "request_id": "mysql-test-1"}).json()
    nodes = {"revision": submission["revision"], "title": task["title"], "nodes": [
        {"node_key": "start", "position": 0, "kind": "start", "floor": "1F"},
        {"node_key": "end", "position": 1, "kind": "end", "floor": "1F"}]}
    saved = mysql_client.put(f"/api/v1/navigation/submissions/{submission['id']}",
                             headers=headers, json=nodes).json()

    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 220, 230)).save(buffer, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    uploaded = mysql_client.post(
        f"/api/v1/navigation/submissions/{submission['id']}/media-base64", headers=headers,
        json={"node_key": "start", "revision": saved["revision"], "data": data_url})
    assert uploaded.status_code == 201

    media = mysql_client.get(f"/api/v1/navigation/media/{uploaded.json()['id']}/base64",
                             headers=headers)
    assert media.status_code == 200
    assert media.json()["data"].startswith("data:image/png;base64,")


def test_record_document_base64_on_mysql(mysql_client):
    import base64
    import io

    from PIL import Image

    patient = login(mysql_client, "13800138000")
    policy = mysql_client.get("/api/v1/consents", headers=patient).json()["policies"]["records_read"]
    granted = mysql_client.post("/api/v1/consents", headers=patient,
                                json={"scope": "records_read", "granted": True,
                                      "recipient": policy["recipient"],
                                      "policy_version": policy["policy_version"]})
    assert granted.status_code == 201

    buffer = io.BytesIO()
    Image.new("RGB", (320, 200), (245, 245, 240)).save(buffer, format="PNG")
    data_url = "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()
    uploaded = mysql_client.post("/api/v1/record-documents/base64", headers=patient,
                                 json={"data": data_url})
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["id"]

    image = mysql_client.get(f"/api/v1/record-documents/{document_id}/image-base64",
                             headers=patient)
    assert image.status_code == 200
    assert image.json()["data"].startswith("data:image/png;base64,")
