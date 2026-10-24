"""M07 smoke-level checks for reviewed knowledge and citations."""
from pathlib import Path
import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import AISettings
from app.db import Database, DEFAULT_DB_PATH
from app.main import create_app
from app.services.medical_knowledge import MEDICAL_ENTRIES, MEDICAL_SOURCES
from app.services.rag import respond, smalltalk


@pytest.fixture
def rig(tmp_path, monkeypatch):
    connect = sqlite3.connect

    def isolated(path, *args, **kwargs):
        assert Path(path).resolve() != DEFAULT_DB_PATH.resolve()
        return connect(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", isolated)
    db = Database(tmp_path / "knowledge.sqlite3")
    with TestClient(create_app(db, ai_settings=AISettings())) as client:
        login = client.post("/api/v1/auth/demo-login", json={"demo_alias": "demo-patient-001"})
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        yield client, db, headers


def search(client, headers, domain, q):
    response = client.get("/api/v1/knowledge/search", headers=headers, params={"domain": domain, "q": q})
    assert response.status_code == 200, response.text
    return response.json()


def conversation(client, headers, domain="medical"):
    client.post("/api/v1/consents", headers=headers, json={"scope": "ai_" + domain})
    response = client.post("/api/v1/conversations", headers=headers, json={"domain": domain})
    assert response.status_code == 201
    return response.json()["id"]


def test_seeded_knowledge_is_published_domain_filtered_and_versioned(rig):
    client, _, headers = rig
    medical = search(client, headers, "medical", "用药")
    assert medical["retrieval"] == "sqlite_keyword_v1"
    assert medical["items"] and all(item["domain"] == "medical" for item in medical["items"])
    assert medical["items"][0]["id"].startswith("med-")
    assert medical["items"][0]["version"] == "2026.1"
    assert medical["items"][0]["status"] == "published"
    assert medical["items"][0]["reviewed_by"] == "demo-reviewer-001"
    legal = search(client, headers, "legal", "知情同意")
    assert legal["items"] and all(item["domain"] == "legal" for item in legal["items"])
    assert all(item["id"].startswith("law-") for item in legal["items"])
    assert all(item["version"] for item in legal["items"])
    unknown = search(client, headers, "legal", "明天会不会下雨")
    assert unknown["items"] == []
    assert client.get("/api/v1/knowledge/search", headers=headers,
                      params={"domain": "other", "q": "用药"}).status_code == 422


def test_retired_or_out_of_window_sources_never_appear(rig):
    client, db, headers = rig
    assert any(item["source_id"] == "src-med-1" for item in search(client, headers, "medical", "用药")["items"])
    with db.transaction(write=True) as connection:
        connection.execute("UPDATE knowledge_sources SET status='retired' WHERE id='src-med-1'")
    assert all(item["source_id"] != "src-med-1" for item in search(client, headers, "medical", "用药")["items"])
    with db.transaction(write=True) as connection:
        connection.execute("UPDATE knowledge_sources SET status='published',effective_from='2099-01-01' WHERE id='src-med-1'")
    assert all(item["source_id"] != "src-med-1" for item in search(client, headers, "medical", "用药")["items"])
    with db.transaction(write=True) as connection:
        connection.execute("UPDATE knowledge_sources SET effective_from='2026-10-01',effective_until='2020-01-01' WHERE id='src-med-1'")
    assert all(item["source_id"] != "src-med-1" for item in search(client, headers, "medical", "用药")["items"])


def test_message_payload_has_no_sources_and_stores_no_citations(rig):
    client, db, headers = rig
    cid = conversation(client, headers)
    response = client.post(f"/api/v1/conversations/{cid}/messages", headers=headers, json={"text": "用药"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert "sources" not in body
    assert "suggestions" not in body
    history = client.get(f"/api/v1/conversations/{cid}", headers=headers).json()["messages"]
    assert "sources" not in history[-1]
    with db.transaction() as connection:
        assert connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='message_sources'"
        ).fetchone()[0] == 0


def test_old_metadata_cannot_reintroduce_removed_fields(rig):
    client, db, headers = rig
    cid = conversation(client, headers)
    assert client.post(f"/api/v1/conversations/{cid}/messages", headers=headers, json={"text": "用药"}).status_code == 200
    with db.transaction(write=True) as connection:
        message_id = connection.execute(
            "SELECT id FROM messages WHERE conversation_id=? AND role='assistant' ORDER BY id DESC LIMIT 1", (cid,)
        ).fetchone()["id"]
        connection.execute("UPDATE message_metadata SET data=? WHERE message_id=?", (json.dumps({
            "topic": "旧主题", "suggestions": ["保留的建议"],
            "followups": ["旧追问"], "doctor_questions": ["旧问医生"], "sources": [{"id": "old"}],
        }), message_id))
    message = client.get(f"/api/v1/conversations/{cid}", headers=headers).json()["messages"][-1]
    assert message["topic"] == "旧主题"
    assert "suggestions" not in message
    assert "followups" not in message and "doctor_questions" not in message and "sources" not in message


def test_mcp_empty_result_does_not_blame_local_material():
    result = respond("legal", "明天会不会下雨", context=[], retrieval="legal_mcp_v1")
    assert result["provider"] == "local_safety"
    assert "法宝" in result["answer"]
    assert "本地资料" not in result["answer"]


def test_unknown_query_abstains_without_calling_provider(rig):
    client, _, headers = rig
    cid = conversation(client, headers, "legal")
    result = client.post(f"/api/v1/conversations/{cid}/messages", headers=headers,
                         json={"text": "明天会不会下雨"}).json()
    assert "sources" not in result
    assert result["provider"] == "local_safety"
    assert "没有可靠的本地资料" in result["answer"]


@pytest.mark.parametrize("text", ["你好", "您好呀", "在吗？", "谢谢医生", "再见", "你是谁", "hello"])
def test_pure_small_talk_is_recognised(text):
    assert smalltalk("medical", text)["provider"] == "local_chitchat"


@pytest.mark.parametrize("text", ["", "你好，我最近睡不好", "我胸痛", "这个药怎么吃", "你好我是患者"])
def test_small_talk_does_not_swallow_a_real_question(text):
    assert smalltalk("medical", text) is None


def test_greeting_gets_a_local_human_reply(rig):
    client, _, headers = rig
    for domain in ("medical", "legal"):
        cid = conversation(client, headers, domain)
        result = client.post(f"/api/v1/conversations/{cid}/messages", headers=headers,
                             json={"text": "你好"}).json()
        assert result["provider"] == "local_chitchat"
        assert result["category"] == "chitchat"
        assert "sources" not in result
        assert "suggestions" not in result
        assert result["answer"].startswith("你好")


def test_greeting_never_overrides_the_safety_branch(rig):
    client, _, headers = rig
    cid = conversation(client, headers, "medical")
    result = client.post(f"/api/v1/conversations/{cid}/messages", headers=headers,
                         json={"text": "你好，我突然胸痛"}).json()
    # Any red flag wins over small talk; which local branch answers it is an
    # implementation detail, that it is answered as urgent is not.
    assert result["category"] == "urgent"
    assert result["provider"] != "local_chitchat"
    assert "立即" in result["answer"]


def test_expanded_medical_catalog_is_complete_and_unique():
    assert len(MEDICAL_SOURCES) == 9
    assert len(MEDICAL_ENTRIES) == 105
    source_ids = {source["id"] for source in MEDICAL_SOURCES}
    assert len(source_ids) == 9
    assert all(entry["source"] in source_ids for entry in MEDICAL_ENTRIES)
    ids = [entry["id"] for entry in MEDICAL_ENTRIES]
    assert len(ids) == len(set(ids))
    assert all(entry["title"].strip() and entry["text"].strip() and entry["keywords"] for entry in MEDICAL_ENTRIES)
    assert all("演示" in source["title"] for source in MEDICAL_SOURCES)


def test_search_requires_authentication(rig):
    client, _, _ = rig
    assert client.get("/api/v1/knowledge/search", params={"domain": "medical", "q": "用药"}).status_code == 401
