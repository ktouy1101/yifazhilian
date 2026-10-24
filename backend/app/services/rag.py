"""Two isolated corpora. SQLite-backed reviewed knowledge, keyword retrieval.

The legacy in-memory corpus remains for provider tests and for callers that do
not pass a database connection; API requests use the reviewed SQLite knowledge
base and return source version/validity metadata with every citation.
"""
import json
import re
from datetime import datetime, timedelta, timezone

from app.ai.providers.base import AIProvider, KnowledgeChunk
from app.ai.providers.mock import MockProvider
from app.services.answer_style import compose_answer, normalize_model_answer
from app.services.knowledge import SEED_CHUNKS, citation, retrieve as retrieve_knowledge
from app.services.record_checklist import build_checklist

CORPORA = {
    domain: tuple(chunk for chunk in SEED_CHUNKS if chunk.domain == domain)
    for domain in ("medical", "legal")
}

CARE_HINTS = ("诊断", "误诊", "复诊", "复查", "医嘱", "看不懂", "检查结果", "报告怎么看", "医生为什么",
              "停药", "换药", "加量", "减量", "剂量")
RED_FLAGS = ("胸痛", "胸闷", "呼吸困难", "喘不过气", "意识不清", "昏迷", "抽搐", "大出血", "剧烈头痛")
JUDGEMENT = ("误诊", "诊断错", "诊断不对", "诊断对吗", "诊断依据", "为什么诊断", "责任", "赔偿")
MEDICATION = ("停药", "换药", "加量", "减量", "剂量", "能不能吃")
FOLLOWUP_WORDS = ("复诊", "复查", "随访", "下次来", "什么时候来")
CARE_QUESTIONS = (
    "医生记录中的诊断依据是什么？",
    "这个诊断或检查结果对我下一步治疗和复诊意味着什么？",
    "下次复诊需要带哪些资料？",
    "出现哪些情况需要提前联系或立即就医？",
)
CHECKLIST_HINTS = ("缺", "还差", "完整", "齐", "资料全")
CHECKLIST_TOPICS = ("病历", "资料", "报告", "检查")

# Small talk is answered locally, without retrieval and without a model. These
# lists only recognise the *whole* message; see smalltalk() for the rule.
IDENTITY_WORDS = ("你是谁", "你叫什么", "你能做什么", "你会做什么", "你会什么", "你是什么",
                  "介绍一下你", "你能帮我做什么", "你是真人吗", "你是机器人吗", "你是ai吗")
GREETING_WORDS = ("你好", "您好", "在吗", "在么", "在不在", "有人吗", "早上好", "早安",
                  "中午好", "下午好", "晚上好", "嗨", "哈喽", "hello", "hi")
THANKS_WORDS = ("谢谢", "感谢", "多谢", "谢了", "谢啦", "thanks")
FAREWELL_WORDS = ("再见", "拜拜", "晚安", "先这样", "回头聊", "下次聊")
ADDRESS_WORDS = ("医生", "大夫", "护士", "律师", "老师", "助手")
SMALLTALK_FILLER = "呀啊呢吧哦喔哈啦嘛呗了么哒噢哇"
SMALLTALK_MAX_LENGTH = 24
_PUNCTUATION = re.compile(r"[\s，。！？、,.!?~～…:：;；\"'“”‘’()（）【】\[\]]+")

CHITCHAT_ANSWERS = {
    ("medical", "greeting"): (
        "你好呀，我在。",
        ["我是这个演示里的助手，不是医生；能帮你把检查报告、用药疑问、复诊准备这些事理清楚",
         "直接说你现在想问的就行，不用先想好措辞"]),
    ("medical", "thanks"): (
        "不客气。",
        ["有想不明白的报告或医嘱，随时问我",
         "要问医生的事，我可以帮你先整理成几句话"]),
    ("medical", "farewell"): (
        "好，那你先忙。",
        ["需要的时候随时回来找我",
         "如果症状突然加重，别等聊天回复，优先联系医护"]),
    ("medical", "identity"): (
        "我是这个演示里的助手，不是医生。",
        ["能解释已审核的科普资料，把要问医生的问题整理成清单，提醒复诊要带的资料",
         "诊断、处方、病情轻重这类判断，我会请你直接问医护"]),
    ("legal", "greeting"): (
        "你好，我在。",
        ["我是这个演示里的助手，不是律师；能帮你把知情同意、病历资料、隐私和纠纷处理这些事理清楚",
         "直接说你现在想问的就行，不用先想好措辞"]),
    ("legal", "thanks"): (
        "不客气。",
        ["就医过程中还有拿不准的，随时问我",
         "涉及具体责任判断的，建议先固定病历和沟通记录"]),
    ("legal", "farewell"): (
        "好，那你先忙。",
        ["需要的时候随时回来找我",
         "如果正在有人身危险，先离开现场、呼叫保安并拨打 110，不要等聊天回复"]),
    ("legal", "identity"): (
        "我是这个演示里的助手，不是律师。",
        ["能解释已审核的就医法律常识，把材料清单和问题整理出来",
         "是否构成过错、能赔多少这类判断，要由律师或鉴定机构结合证据看"]),
}


def _strip_tokens(text, words):
    for word in sorted(words, key=len, reverse=True):
        text = text.replace(word, "")
    return text


def smalltalk(domain, text):
    """Return a local, model-free reply for messages that are only small talk.

    It fires only when the message is nothing but a greeting, thanks, farewell
    or "who are you": after removing those words only filler characters may
    remain. "你好，我最近睡不好" therefore still goes down the knowledge path,
    and a red flag in the same message is caught by the safety branch first.
    """
    compact = _PUNCTUATION.sub("", str(text or "")).casefold()
    if not compact or len(compact) > SMALLTALK_MAX_LENGTH:
        return None
    kind = None
    rest = compact
    for name, words in (("identity", IDENTITY_WORDS), ("greeting", GREETING_WORDS),
                        ("thanks", THANKS_WORDS), ("farewell", FAREWELL_WORDS)):
        if any(word in rest for word in words):
            rest = _strip_tokens(rest, words)
            kind = kind or name
    if kind is None:
        return None
    rest = _strip_tokens(rest, ADDRESS_WORDS).strip(SMALLTALK_FILLER)
    if rest:
        return None
    lead, points = CHITCHAT_ANSWERS[(domain, kind)]
    return {
        "answer": compose_answer(lead, points),
        "sources": [],
        "provider": "local_chitchat",
        "retrieval": "local_chitchat",
        "category": "chitchat",
        "external_ai": False,
    }


def _health_consent(connection, user_id):
    return connection.execute(
        "SELECT 1 FROM consents WHERE user_id=? AND scope='vitals' AND granted=1 "
        "AND revoked_at IS NULL AND expires_at>? AND policy_version='health-records-1'",
        (user_id, datetime.now(timezone.utc).isoformat())).fetchone() is not None


def _recent_red_flag(connection, user_id):
    rows = connection.execute(
        "SELECT payload,measured_at FROM health_entries WHERE user_id=? ORDER BY measured_at DESC LIMIT 30",
        (user_id,)).fetchall()
    for row in rows:
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            continue
        text = " ".join(str(payload.get(key, "")) for key in ("title", "note"))
        if any(word in text for word in RED_FLAGS):
            return row["measured_at"]
    return None


def _followup_message(connection, user_id):
    row = connection.execute(
        "SELECT title,due_at FROM health_followups WHERE user_id=? AND done=0 ORDER BY due_at LIMIT 1",
        (user_id,)).fetchone()
    if row is None:
        return "未记录复诊时间；如医生有安排，请在“复诊待办”中补充。"
    try:
        due = datetime.fromisoformat(row["due_at"])
        if due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
    except ValueError:
        return "复诊日期格式无法核对，请手动确认。"
    now = datetime.now(timezone.utc)
    if due <= now:
        return "你记录的复诊时间已到或已过，建议尽快联系医院确认新的复诊安排。"
    if due <= now + timedelta(days=3):
        return "复诊时间临近，请提前确认挂号、材料和交通安排。"
    return "已记录复诊时间；如症状加重或出现新的不适，请提前联系医护。"


def answer_visit_question(connection, user_id, text):
    """Local M05 branch for diagnosis questions and follow-up guidance.

    Returns None for ordinary medical questions so the normal retrieved answer
    path still runs. It never calls a model and never stores patient text.
    """
    if not any(word in text for word in CARE_HINTS) and not any(word in text for word in RED_FLAGS):
        return None
    can_health = _health_consent(connection, user_id)
    red_flag = _recent_red_flag(connection, user_id) if can_health else None
    if red_flag or any(word in text for word in RED_FLAGS):
        category = "urgent"
    elif any(word in text for word in JUDGEMENT):
        category = "judgement"
    elif any(word in text for word in MEDICATION):
        category = "medication"
    elif any(word in text for word in FOLLOWUP_WORDS):
        category = "followup"
    else:
        category = "explain"

    sources = retrieve_knowledge(connection, "medical", text, limit=2)
    follow_up = _followup_message(connection, user_id) if can_health else "未取得健康记录授权；如医生有安排，请在“健康 → 复诊待办”补充复诊时间。"

    if category == "urgent":
        answer = compose_answer(
            "你描述的情况可能需要立即处理，请立即联系病区医护或使用床旁呼叫铃。",
            ["不要等待聊天回复；如果不在医院，请拨打 120 或让身边的人立即求助",
             "本演示不会派出急救人员，也不会通知医护"])
        sources = []
        follow_up = "先处理当前症状，复诊时间可稍后由医护确认。"
    elif category == "judgement":
        answer = compose_answer(
            "我不能判断诊断是否正确；你消息里的内容只代表你本人的说法，不是医院认证记录。",
            ["我能帮你把诊断或医嘱原文、想问的问题整理成清单",
             "误诊、责任或赔偿，需要医生、医务科或专业机构结合完整病历核实",
             "复诊时把清单逐条问医生，必要时请医务科协助"])
    elif category == "medication":
        answer = compose_answer(
            "不要根据聊天内容自行停药、换药、加量或减量。",
            ["把药名、用法、当前疑问和身体反应记下来",
             "联系开药医生或药师核对，本页不提供剂量调整建议",
             "出现皮疹、黑便、呼吸困难等，及时联系医护"])
    elif category == "followup":
        answer = compose_answer(
            "复诊时间以医生安排和医院通知为准，本页只根据你记录的时间做提醒。",
            ["把要带的资料和想问的问题提前列好",
             "症状加重或出现新的不适，提前联系医护"])
    else:
        points = []
        if sources:
            points.append("关键说法来自下方引用的公开资料，可对照自己的报告看")
        else:
            points.append("现有记录和公开资料没有足够信息解释这个问题，我不会编造原因")
        points.append("把不懂的地方写成清单，复诊时逐条问医生")
        answer = compose_answer("我不能判断诊断是否正确；下面只解释公开资料里的相关说法。", points)
    if category != "urgent":
        answer += "\n\n复诊提示：" + follow_up
    return {
        "answer": answer,
        "sources": [citation(source) for source in sources] if category in ("explain", "judgement", "followup") else [],
        "provider": "local_care_guide",
        "retrieval": "local_care_guide",
        "category": category,
        "questions_for_doctor": list(CARE_QUESTIONS),
        "follow_up": follow_up,
        "external_ai": False,
    }


def answer_record_checklist(connection, user_id, text):
    """Local M05 answer for “which medical-record documents are missing?”"""
    if not (any(word in text for word in CHECKLIST_HINTS) and any(word in text for word in CHECKLIST_TOPICS)):
        return None
    active = connection.execute(
        "SELECT 1 FROM consents WHERE user_id=? AND scope='records_read' AND granted=1 "
        "AND revoked_at IS NULL AND expires_at>? AND policy_version='records-local-3' "
        "AND recipient='local_record_service'",
        (user_id, datetime.now(timezone.utc).isoformat())).fetchone()
    if not active:
        return {"answer": "我还没有本地病历处理授权，不能读取你上传的病历资料。请先到“检验单与病历”阅读告知并授权，再问我缺哪些资料。",
                "sources": [], "provider": "local_record_checklist", "retrieval": "local_record_checklist",
                "category": "record_checklist", "external_ai": False}
    scenario = "inpatient" if "住院" in text else ("followup" if "复诊" in text else "outpatient")
    rows = connection.execute(
        "SELECT draft,status FROM record_documents WHERE user_id=? ORDER BY updated_at DESC",
        (user_id,)).fetchall()
    result = build_checklist([{"draft": row["draft"], "status": row["status"]} for row in rows], scenario)
    lines = [f"按“{result['scenario_label']}”的资料清单看，{result['complete_count']}/{result['total_required']} 项必需资料已归档。"]
    if result["missing"]:
        lines.append("未看到：" + "、".join(result["missing"]) + "。")
    if result["pending"]:
        lines.append("已上传但还需核对：" + "、".join(result["pending"]) + "。")
    if result["complete"]:
        lines.append("按这份清单，必需资料都已归档；是否足够仍要看医院和医生要求。")
    else:
        lines.append("这些只是资料类型完整度，不代表医院诊疗不完整，也不代表医院责任；可以向病案室确认能否提供。")
    lines.append("你可以继续在“检验单与病历”上传缺失资料；我不会仅凭缺少文件判断诊断或责任。")
    return {"answer": "\n\n".join(lines), "sources": [], "provider": "local_record_checklist",
            "retrieval": "local_record_checklist", "category": "record_checklist",
            "checklist": result, "external_ai": False}


def retrieve(domain: str, text: str) -> list[KnowledgeChunk]:
    # Domain is selected on conversation creation and never taken from prompts.
    ranked = [(sum(word in text for word in doc.keywords), doc)
              for doc in CORPORA[domain]]
    return [doc for score, doc in sorted(ranked, key=lambda pair: pair[0], reverse=True)
            if score > 0][:2]


def respond(domain: str, text: str, provider: AIProvider | None = None,
            context: list[KnowledgeChunk] | None = None, connection=None,
            retrieval: str = "local_keyword_demo") -> dict:
    selected = provider if provider is not None else MockProvider()
    if context is None:
        context = (retrieve_knowledge(connection, domain, text)
                   if connection is not None else retrieve(domain, text))
    # These safeguards must survive replacement of the model adapter. They run
    # locally before any egress, never as a fallback after a paid request fails.
    urgent = any(word in text for word in ("胸痛", "胸闷", "呼吸困难", "喘不过气", "昏迷"))
    if urgent:
        answer = "【本地安全提示】请立即联系病区医护或使用实体呼叫铃；不要等待 AI 回复。本程序不会派出急救人员。"
        context = []
        source_provider = "local_safety"
    elif not context:
        # Still an abstention: no citation, no guess. Only the wording is human.
        if retrieval.startswith("legal_mcp"):
            answer = ("法宝库里没有检索到和这句相关的条文，我就不硬猜了。\n"
                      "你可以换个更具体的说法，比如“病历复印”“知情同意”，或者拨打 12348、找律师问问。")
        elif domain == "legal":
            answer = ("这个我手上没有可靠的本地资料，就不硬猜了。\n"
                      "你可以换个更具体的说法，或者拨打 12348、找律师问问，他们会结合你的实际情况判断。")
        else:
            answer = ("这个我手上没有可靠的本地资料，就不硬猜了。\n"
                      "你可以换个更具体的说法，或者把问题记下来直接问医护，他们会结合你的实际情况判断。")
        source_provider = "local_safety"
    else:
        generated = selected.generate(domain=domain, text=text, context=context)
        answer = normalize_model_answer(generated) or generated
        source_provider = selected.name
    return {
        "answer": answer,
        "sources": [citation(doc) for doc in context],
        "provider": source_provider,
        "retrieval": retrieval,
    }
