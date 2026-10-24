"""M05 local visit-question branch: understanding and follow-up, no diagnosis."""
from datetime import timedelta
from pathlib import Path
import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import AISettings
from app.db import Database, DEFAULT_DB_PATH, utcnow
from app.main import create_app


@pytest.fixture
def rig(tmp_path, monkeypatch):
    connect = sqlite3.connect

    def isolated(path, *args, **kwargs):
        assert Path(path).resolve() != DEFAULT_DB_PATH.resolve()
        return connect(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", isolated)
    db = Database(tmp_path / "medical-agent.sqlite3")
    with TestClient(create_app(db, ai_settings=AISettings())) as client:
        login = client.post("/api/v1/auth/demo-login", json={"demo_alias": "demo-patient-001"})
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        client.post("/api/v1/consents", headers=headers, json={"scope": "ai_medical"})
        conversation = client.post("/api/v1/conversations", headers=headers,
                                   json={"domain": "medical"}).json()["id"]
        yield client, db, headers, conversation


def ask(client, headers, conversation, text):
    response = client.post(f"/api/v1/conversations/{conversation}/messages", headers=headers,
                           json={"text": text})
    assert response.status_code == 200, response.text
    return response.json()


def test_diagnosis_question_is_explained_without_judging(rig):
    client, _, headers, conversation = rig
    result = ask(client, headers, conversation, "看不懂医生的诊断，我应该怎么问？")
    assert result["provider"] == "local_care_guide"
    assert result["retrieval"] == "local_care_guide"
    assert result["external_ai"] is False
    assert "不能判断诊断" in result["answer"]
    assert "问医生" in result["answer"]
    assert result["category"] == "explain"


def test_misdiagnosis_and_medication_questions_fail_closed(rig):
    client, _, headers, conversation = rig
    misdiagnosis = ask(client, headers, conversation, "是不是误诊了，医院要不要赔偿？")
    assert misdiagnosis["category"] == "judgement"
    assert "不能判断" in misdiagnosis["answer"] and "赔偿" in misdiagnosis["answer"]
    medication = ask(client, headers, conversation, "我想停药，可以吗？")
    assert medication["category"] == "medication"
    assert "不要" in medication["answer"] and "医生" in medication["answer"]


def test_red_flag_preempts_follow_up_and_never_claims_dispatch(rig):
    client, db, headers, conversation = rig
    result = ask(client, headers, conversation, "突然胸痛，喘不过气")
    assert result["category"] == "urgent"
    assert "立即联系病区医护" in result["answer"]
    assert "不会派出急救人员" in result["answer"]
    with db.transaction() as connection:
        assert connection.execute("SELECT count(*) FROM emergency_events").fetchone()[0] == 0


def test_follow_up_reminder_uses_recorded_task(rig):
    client, _, headers, conversation = rig
    client.post("/api/v1/consents", headers=headers, json={"scope": "vitals"})
    due = (utcnow() + timedelta(days=1)).isoformat()
    response = client.post("/api/v1/health-management/followups", headers=headers, json={
        "request_id": "agent-followup", "title": "心内科复诊", "due_at": due, "note": "",
    })
    assert response.status_code == 201, response.text
    result = ask(client, headers, conversation, "复诊要带什么？")
    assert result["category"] == "followup"
    assert "复诊提示" in result["answer"]
    assert "心内科复诊" not in result["answer"]  # private title is not echoed
    assert "复诊时间临近" in result["answer"] or "已记录复诊时间" in result["answer"]


def test_general_medication_question_keeps_retrieved_answer_path(rig):
    client, _, headers, conversation = rig
    result = ask(client, headers, conversation, "用药")
    assert result["provider"] == "mock"
    assert "sources" not in result


def test_lab_report_explains_topic_with_citations_and_questions(rig):
    client, _, headers, conversation = rig
    result = ask(client, headers, conversation, "转氨酶偏高是什么意思")
    assert result["category"] == "report"
    assert result["topic"] == "肝功能"
    assert result["provider"] == "mock"
    assert "sources" not in result
    assert "suggestions" not in result
    assert "确诊" not in result["answer"]


def test_personal_diagnosis_request_refuses_to_judge(rig):
    client, _, headers, conversation = rig
    result = ask(client, headers, conversation, "我是不是得了癌症")
    assert result["category"] == "diagnosis"
    assert result["provider"] == "local_medical_boundary"
    assert "sources" not in result
    assert "不能根据聊天" in result["answer"]
    assert "suggestions" not in result


def test_antibiotic_side_effect_question_is_guarded_but_cited(rig):
    client, _, headers, conversation = rig
    result = ask(client, headers, conversation, "抗生素有哪些副作用")
    assert result["category"] == "medication"
    assert result["topic"] == "用药"
    assert result["provider"] == "local_medical_boundary"
    assert "sources" not in result
    assert "不要" in result["answer"] and "医生" in result["answer"]
    assert "抗生素" in result["answer"]
    assert "suggestions" not in result
    hormone = ask(client, headers, conversation, "激素药的副作用")
    assert hormone["category"] == "medication"
    assert "激素" in hormone["answer"] and "自行停药" in hormone["answer"]


def test_urgent_symptom_gets_local_safety_boundary(rig):
    client, _, headers, conversation = rig
    result = ask(client, headers, conversation, "黑便怎么办")
    assert result["category"] == "urgent"
    assert result["provider"] == "local_safety"
    assert "尽快联系医护" in result["answer"]
    assert "不会派出急救人员" in result["answer"]
    assert "suggestions" not in result


def test_agent_metadata_is_restored_in_history(rig):
    client, _, headers, conversation = rig
    result = ask(client, headers, conversation, "白细胞高说明什么")
    assert result["topic"] == "血常规"
    history = client.get(f"/api/v1/conversations/{conversation}", headers=headers).json()["messages"]
    assistant = history[-1]
    assert assistant["category"] == "report"
    assert assistant["topic"] == "血常规"
    assert "suggestions" not in assistant
    assert assistant["external_ai"] is False


def test_expanded_report_catalog_retrieves_new_markers(rig):
    client, _, headers, conversation = rig
    cases = {
        "C反应蛋白偏高说明什么": "med-301",
        "血气分析怎么看": "med-302",
        "肌钙蛋白高要紧吗": "med-303",
        "甲功报告怎么看": "med-304",
        "肿瘤标志物升高怎么办": "med-305",
        "低密度脂蛋白高": "med-306",
        "大便隐血阳性": "med-307",
        "铁蛋白低": "med-308",
        "糖化血红蛋白高": "med-309",
        "尿酸高": "med-310",
    }
    for question, expected in cases.items():
        items = client.get("/api/v1/knowledge/search", headers=headers,
                           params={"domain": "medical", "q": question, "limit": 3}).json()["items"]
        assert items and items[0]["id"] == expected, (question, items)
        result = ask(client, headers, conversation, question)
        assert "sources" not in result
        assert "suggestions" not in result
    crp = ask(client, headers, conversation, "C反应蛋白偏高说明什么")
    assert crp["category"] == "report"
    assert crp["topic"] == "炎症指标"
    assert "suggestions" not in crp
    chemo = ask(client, headers, conversation, "化疗后白细胞低")
    assert chemo["category"] == "report"
    assert "sources" not in chemo

    conditions = {
        "房颤平时要注意什么": ("房颤与心律失常", "med-515"),
        "心衰患者怎么限盐": ("心力衰竭", "med-516"),
        "胆囊炎右上腹痛": ("胆囊与胆道", "med-517"),
        "胰腺炎为什么要禁食": ("胰腺", "med-518"),
        "阑尾炎右下腹痛": ("阑尾", "med-519"),
    }
    for question, (topic, expected) in conditions.items():
        items = client.get("/api/v1/knowledge/search", headers=headers,
                           params={"domain": "medical", "q": question, "limit": 3}).json()["items"]
        assert items and items[0]["id"] == expected, (question, items)
        result = ask(client, headers, conversation, question)
        assert result["topic"] == topic, (question, result["topic"])
        assert "sources" not in result


def test_discharge_mental_infection_and_medication_topics_get_guided(rig):
    client, _, headers, conversation = rig
    discharge = ask(client, headers, conversation, "出院后伤口怎么护理")
    assert discharge["category"] == "discharge"
    assert discharge["topic"] == "出院随访"
    assert "suggestions" not in discharge

    mental = ask(client, headers, conversation, "最近焦虑睡不着")
    assert mental["category"] == "mental"
    assert mental["topic"] == "情绪与睡眠"
    assert "不能根据聊天" not in mental["answer"]

    infection = ask(client, headers, conversation, "陪护需要隔离吗")
    assert infection["category"] == "infection"
    assert infection["topic"] == "感染预防"

    steroid = ask(client, headers, conversation, "激素副作用")
    assert steroid["category"] == "medication"
    assert steroid["topic"] == "激素与免疫用药"
    assert steroid["provider"] == "local_medical_boundary"
    assert "sources" not in steroid
    assert "不要" in steroid["answer"]
