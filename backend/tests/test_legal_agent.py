"""M06 legal guide: local explanations, boundaries and no invented conclusions."""
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import AISettings
from app.db import Database, DEFAULT_DB_PATH
from app.main import create_app
from app.services import legal_agent

LEGALESE = ("应当", "依照", "本法", "之规定", "予以", "有权", "上述", "鉴于")


def test_local_legal_answers_are_plain_language(monkeypatch):
    """The patient-facing branches must not read like a statute."""
    monkeypatch.setattr(legal_agent, "retrieve", lambda *args, **kwargs: [])
    for question in ("手术前签同意书要注意什么", "病历可以复印吗", "我的隐私会被泄露吗",
                     "出了医疗纠纷找谁", "是不是误诊", "能赔多少钱", "怀疑过度检查怎么办",
                     "工伤怎么赔"):
        result = legal_agent.answer(None, question)
        assert result is not None, question
        answer = result["answer"]
        assert len(answer) <= 260, question
        for word in LEGALESE:
            assert word not in answer, (question, word)


@pytest.fixture
def rig(tmp_path, monkeypatch):
    connect = sqlite3.connect

    def isolated(path, *args, **kwargs):
        assert Path(path).resolve() != DEFAULT_DB_PATH.resolve()
        return connect(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", isolated)
    db = Database(tmp_path / "legal-agent.sqlite3")
    with TestClient(create_app(db, ai_settings=AISettings())) as client:
        login = client.post("/api/v1/auth/demo-login", json={"demo_alias": "demo-patient-001"})
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        client.post("/api/v1/consents", headers=headers, json={"scope": "ai_legal"})
        conversation = client.post("/api/v1/conversations", headers=headers,
                                   json={"domain": "legal"}).json()["id"]
        yield client, db, headers, conversation


def ask(client, headers, conversation, text):
    response = client.post(f"/api/v1/conversations/{conversation}/messages", headers=headers,
                           json={"text": text})
    assert response.status_code == 200, response.text
    return response.json()


def test_informed_consent_is_local_and_cited(rig):
    client, _, headers, conversation = rig
    result = ask(client, headers, conversation, "手术前签字，医生要告诉我什么？")
    assert result["provider"] == "local_legal_guide"
    assert result["category"] == "consent"
    assert result["external_ai"] is False
    assert "别的办法" in result["answer"] and "书面同意" in result["answer"]
    assert "sources" not in result
    assert result["materials"] and result["next_steps"]


def test_records_copy_and_seal_are_explained(rig):
    client, _, headers, conversation = rig
    result = ask(client, headers, conversation, "医院不给复印病历怎么办？")
    assert result["provider"] == "local_legal_guide"
    assert result["category"] == "records"
    assert "复印" in result["answer"] and "封存" in result["answer"]
    assert "sources" not in result


def test_privacy_question_mentions_sensitive_data_and_withdrawal(rig):
    client, _, headers, conversation = rig
    result = ask(client, headers, conversation, "我不想让医院继续用我的健康信息，怎么撤回？")
    assert result["category"] == "privacy"
    assert "敏感信息" in result["answer"]
    assert "撤回" in result["answer"]
    assert "sources" not in result


def test_dispute_routes_are_listed_without_promising_outcome(rig):
    client, _, headers, conversation = rig
    result = ask(client, headers, conversation, "发生医疗纠纷可以怎么解决？")
    assert result["category"] == "dispute"
    for word in ("协商", "人民调解", "诉讼"):
        assert word in result["answer"]
    assert "光靠聊天判断不了" in result["answer"]
    assert "sources" not in result


def test_liability_question_refuses_to_judge_fault(rig):
    client, _, headers, conversation = rig
    result = ask(client, headers, conversation, "医院是不是误诊，要不要负责？")
    assert result["provider"] == "local_legal_boundary"
    assert result["category"] == "liability"
    assert "不能替你判断" in result["answer"]
    assert "鉴定" in result["answer"]
    assert "suggestions" not in result


def test_compensation_amount_is_not_estimated(rig):
    client, _, headers, conversation = rig
    result = ask(client, headers, conversation, "能赔多少钱？")
    assert result["provider"] == "local_legal_boundary"
    assert "没法" in result["answer"] and "赔多少" in result["answer"]
    assert result["category"] == "compensation"


def test_out_of_scope_question_redirects_to_12348(rig):
    client, _, headers, conversation = rig
    result = ask(client, headers, conversation, "劳动工伤怎么赔？")
    assert result["provider"] == "local_legal_guide"
    assert result["category"] == "out_of_scope"
    assert "12348" in result["answer"]


def test_crisis_points_to_110_and_120_and_never_claims_notification(rig):
    client, _, headers, conversation = rig
    result = ask(client, headers, conversation, "我被医生打了，现在很危险")
    assert result["provider"] == "local_legal_boundary"
    assert result["category"] == "crisis"
    assert "110" in result["answer"] and "120" in result["answer"]
    assert "不会通知任何人" in result["answer"]


def test_overcheck_uses_the_unnecessary_exam_article(rig):
    client, _, headers, conversation = rig
    result = ask(client, headers, conversation, "医院是不是过度检查？")
    assert result["category"] == "overcheck"
    assert "sources" not in result
    assert "检查" in result["answer"]


def test_legal_metadata_is_restored_in_history(rig):
    client, _, headers, conversation = rig
    body = ask(client, headers, conversation, "病历可以复印哪些？")
    assert body["materials"] and body["next_steps"]
    history = client.get(f"/api/v1/conversations/{conversation}", headers=headers).json()["messages"]
    last = history[-1]
    assert last["category"] == body["category"]
    assert last["materials"] == body["materials"]
    assert last["next_steps"] == body["next_steps"]
    assert "suggestions" not in last
