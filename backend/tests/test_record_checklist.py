"""M03/M05 document-completeness checklist and local agent answer."""
from pathlib import Path
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import AISettings
from app.db import Database, DEFAULT_DB_PATH
from app.main import create_app
from app.services.record_checklist import build_checklist


def rows(*types, status="archived"):
    return [{"draft": json.dumps({"record_type": record_type}, ensure_ascii=False), "status": status}
            for record_type in types]


def test_checklist_separates_archived_pending_and_missing():
    missing = build_checklist([], "inpatient")
    assert missing["complete_count"] == 0
    assert missing["missing_count"] == missing["total_required"]
    assert "病案首页" in missing["missing"]
    pending = build_checklist(rows("病案首页", status="review"), "inpatient")
    assert pending["pending_count"] == 1
    assert pending["complete_count"] == 0
    complete = build_checklist(rows("病案首页", "入院记录", "出院记录", "检验单", "医嘱单"), "inpatient")
    assert complete["complete"] is True
    assert complete["complete_count"] == complete["total_required"] == 5
    assert complete["items"][-1]["status"] == "missing"  # optional surgery/pathology not required


@pytest.fixture
def rig(tmp_path, monkeypatch):
    connect = sqlite3.connect

    def isolated(path, *args, **kwargs):
        assert Path(path).resolve() != DEFAULT_DB_PATH.resolve()
        return connect(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", isolated)
    db = Database(tmp_path / "checklist.sqlite3")
    with TestClient(create_app(db, ai_settings=AISettings())) as client:
        login = client.post("/api/v1/auth/demo-login", json={"demo_alias": "demo-patient-001"})
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        for scope in ("records_read", "ai_medical"):
            policy = client.get("/api/v1/consents", headers=headers).json()["policies"][scope]
            assert client.post("/api/v1/consents", headers=headers, json={
                "scope": scope, "policy_version": policy["policy_version"],
                "recipient": policy["recipient"]}).status_code == 201
        draft = {"title": "合成出院记录", "record_type": "出院记录", "record_date": "2026-10-17",
                 "institution": "合成医院", "visit": "合成住院", "fields": []}
        with db.transaction(write=True) as c:
            c.execute(
                "INSERT INTO record_documents(id,user_id,sha256,image,mime,width,height,status,draft,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                ("doc-discharge", "demo-patient-001", "b" * 64, sqlite3.Binary(b"png"),
                 "image/png", 1, 1, "archived", json.dumps(draft, ensure_ascii=False),
                 "2026-10-17T00:00:00+00:00", "2026-10-17T00:00:00+00:00"))
        yield client, headers, db


def test_checklist_endpoint_and_agent_report_missing_documents(rig):
    client, headers, _ = rig
    response = client.get("/api/v1/record-documents/checklist?scenario=inpatient", headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["complete_count"] == 1
    assert "病案首页" in data["missing"]
    assert data["items"][2]["status"] == "complete"
    conversation = client.post("/api/v1/conversations", headers=headers, json={"domain": "medical"}).json()["id"]
    message = client.post(f"/api/v1/conversations/{conversation}/messages", headers=headers,
                          json={"text": "住院病历还缺什么？"})
    assert message.status_code == 200, message.text
    result = message.json()
    assert result["provider"] == "local_record_checklist"
    assert result["category"] == "record_checklist"
    assert "未看到" in result["answer"]
    assert "不代表医院诊疗不完整" in result["answer"]
