"""Medical knowledge agent: classify, guard, retrieve and shape one turn.

This module is deliberately deterministic. It does not diagnose, change a
prescription or call an external model. The external model only receives the
current synthetic question plus reviewed, same-domain reference chunks.
"""
from app.services.answer_style import compose_answer
from app.services.knowledge import citation, retrieve

CRISIS = (
    "胸痛", "胸闷", "呼吸困难", "喘不过气", "意识不清", "昏迷", "抽搐",
    "大出血", "剧烈头痛", "自杀", "不想活", "窒息", "心跳骤停", "大咯血",
    "呕血", "晕厥", "意识丧失", "剧烈胸痛", "压榨", "伤害自己",
)
URGENT = (
    "高烧不退", "持续高热", "黑便", "呕血", "血尿", "晕倒", "摔倒",
    "严重过敏", "嘴唇肿", "说不清话", "一侧无力", "持续呕吐", "不能进水",
    "尿量明显减少", "伤口化脓", "红肿热痛", "小腿肿痛", "单侧肿",
    "视力突然", "嘴角歪", "手脚无力", "血便", "柏油便", "皮下出血",
    "大片淤青", "寒战", "高热",
)
DIAGNOSIS = (
    "我是不是", "会不会是", "是不是得", "我得的是", "能治好吗", "还能活多久",
    "是不是误诊", "是不是癌症", "确诊了吗", "我这个严重吗",
)
MEDICATION = (
    "停药", "换药", "加量", "减量", "剂量", "能不能吃", "副作用",
    "漏服", "补服", "一起吃",
)
PROCEDURE_HINTS = (
    "手术", "麻醉", "插管", "胃镜", "肠镜", "穿刺", "导尿", "检查前",
    "术前", "术后", "禁食", "禁水",
)
SYMPTOM_HINTS = (
    "疼", "痛", "头晕", "恶心", "呕吐", "咳嗽", "乏力", "失眠",
    "便秘", "腹泻", "心慌", "肿", "麻",
)
LIFESTYLE_HINTS = (
    "吃什么", "饮食", "忌口", "运动", "洗澡", "下床", "抽烟",
    "喝酒", "熬夜", "营养", "能吃什么",
)
REPORT_HINTS = (
    "报告", "结果", "指标", "偏高", "偏低", "升高", "降低", "阳性",
    "阴性", "是什么意思", "说明", "怎么看", "参考范围", "参考区间",
    "白细胞低", "血小板低", "血红蛋白低", "白蛋白低", "铁蛋白低",
    "血钾低", "血钠低",
)
DISCHARGE_HINTS = (
    "出院", "回家", "复诊", "随访", "复查", "出院带药", "出院小结",
)
MENTAL_HINTS = (
    "焦虑", "抑郁", "情绪", "失眠", "睡不着", "害怕", "恐慌", "压力",
    "心情", "心理",
)
INFECTION_HINTS = (
    "感染", "隔离", "手卫生", "洗手", "消毒", "传染", "探视", "陪护",
)
REHAB_HINTS = (
    "康复", "锻炼", "活动", "下床", "走路", "物理治疗", "踝泵", "恢复",
)
NUTRITION_HINTS = (
    "吃什么", "饮食", "营养", "忌口", "补品", "蛋白质", "低蛋白", "盐", "喝水", "饮水",
)
PREVENTION_HINTS = (
    "疫苗", "预防", "筛查", "体检", "戒烟", "喝酒", "运动", "生活方式",
)

TOPICS = (
    ("inflammation", "炎症指标", ("c反应蛋白", "crp", "降钙素原", "pct", "炎症")),
    ("bloodgas", "血气分析", ("血气", "氧分压", "二氧化碳分压", "碳酸氢", "乳酸")),
    ("cardiac", "心肌标志物", ("肌钙蛋白", "心肌", "心梗", "ck-mb")),
    ("thyroid", "甲状腺", ("甲状腺", "甲功", "tsh", "ft3", "ft4", "甲减", "甲亢")),
    ("tumor", "肿瘤相关", ("肿瘤", "癌症", "病理", "化疗", "放疗", "靶向")),
    ("lipid", "血脂", ("血脂", "胆固醇", "低密度脂蛋白", "甘油三酯")),
    ("stool", "便常规", ("便常规", "大便", "隐血", "黑便", "血便")),
    ("anemia", "贫血", ("贫血", "铁蛋白", "维生素b12", "叶酸")),
    ("blood", "血常规", ("血常规", "白细胞", "红细胞", "血红蛋白", "血小板", "贫血")),
    ("liver", "肝功能", ("肝", "转氨酶", "胆红素", "alt", "ast", "黄疸", "白蛋白")),
    ("kidney", "肾功能", ("肾", "肌酐", "尿素氮", "滤过", "尿量")),
    ("diabetes", "糖尿病", ("糖尿病", "降糖", "胰岛素", "二甲双胍")),
    ("glucose", "血糖", ("血糖", "糖化", "低血糖", "高血糖")),
    ("electrolyte", "电解质", ("电解质", "低钾", "高钾", "低钠", "血钾", "血钠")),
    ("coagulation", "凝血功能", ("凝血", "pt", "inr", "aptt", "华法林", "利伐沙班", "抗凝")),
    ("urine", "尿常规", ("尿常规", "尿蛋白", "尿路感染", "尿频", "尿痛")),
    ("ecg", "心电图", ("心电图", "窦性", "早搏", "st-t", "心律")),
    ("imaging", "影像检查", ("ct", "x光", "超声", "b超", "核磁", "mri", "影像", "结节", "阴影")),
    ("fever", "发热", ("发热", "发烧", "体温", "寒战")),
    ("cough", "咳嗽", ("咳嗽", "咳痰", "咯血")),
    ("dyspnea", "呼吸困难", ("呼吸困难", "喘", "气短", "缺氧")),
    ("chestpain", "胸痛", ("胸痛", "胸闷", "压榨")),
    ("gallstone", "胆囊与胆道", ("胆囊炎", "胆结石", "右上腹", "胆囊")),
    ("pancreas", "胰腺", ("胰腺炎", "淀粉酶", "脂肪酶", "上腹痛")),
    ("appendix", "阑尾", ("阑尾炎", "右下腹", "转移性腹痛")),
    ("abdominal", "腹痛", ("腹痛", "肚子痛", "腹胀", "急腹症")),
    ("nausea", "恶心呕吐", ("恶心", "呕吐", "干呕")),
    ("diarrhea", "腹泻", ("腹泻", "拉肚子", "水样便")),
    ("constipation", "便秘", ("便秘", "排便", "开塞露")),
    ("dizziness", "头晕", ("头晕", "眩晕", "晕倒")),
    ("headache", "头痛", ("头痛", "偏头痛")),
    ("edema", "水肿", ("水肿", "浮肿", "腿肿")),
    ("rash", "皮疹", ("皮疹", "瘙痒", "疹子")),
    ("allergy", "过敏", ("过敏", "荨麻疹", "嘴唇肿")),
    ("fatigue", "乏力", ("乏力", "没劲", "疲劳")),
    ("palpitation", "心悸", ("心悸", "心慌", "心跳快")),
    ("neuro", "麻木无力", ("麻木", "手麻", "脚麻", "说话不清", "偏瘫")),
    ("hypertension", "高血压", ("高血压", "降压药", "血压高")),
    ("coronary", "冠心病", ("冠心病", "心绞痛", "支架")),
    ("arrhythmia", "房颤与心律失常", ("房颤", "心房颤动", "心跳乱", "脉搏不齐")),
    ("heartfailure", "心力衰竭", ("心衰", "心力衰竭", "夜间憋醒", "脚肿")),
    ("stroke", "脑卒中", ("脑卒中", "中风", "偏瘫")),
    ("copd", "慢阻肺与哮喘", ("慢阻肺", "哮喘", "吸入剂")),
    ("pneumonia", "肺炎", ("肺炎", "肺部感染")),
    ("uti", "尿路感染", ("尿路感染", "尿频", "尿痛", "尿培养")),
    ("gi", "胃肠疾病", ("胃炎", "胃溃疡", "幽门螺杆菌", "消化道")),
    ("mental", "情绪与睡眠", ("焦虑", "抑郁", "情绪", "心理", "失眠", "睡不着")),
    ("delirium", "谵妄", ("谵妄", "糊涂", "意识")),
    ("nutrition", "营养饮食", ("饮食", "营养", "吃什么", "忌口")),
    ("rehab", "康复活动", ("康复", "锻炼", "下床", "走路")),
    ("infection", "感染预防", ("感染", "隔离", "手卫生", "洗手")),
    ("discharge", "出院随访", ("出院", "复诊", "随访", "复查")),
    ("older", "老年患者", ("老年", "老人", "跌倒")),
    ("pregnancy", "孕产期", ("怀孕", "孕妇", "哺乳")),
    ("palliative", "安宁疗护", ("安宁疗护", "临终", "舒适")),
    ("prevention", "预防与筛查", ("疫苗", "筛查", "预防", "戒烟", "饮酒")),
    ("hormone", "激素与免疫用药", ("激素", "糖皮质激素", "泼尼松", "地塞米松", "免疫抑制")),
    ("medication", "用药", ("抗生素", "止痛药", "抗凝药", "输液", "用药", "吃药")),
    ("surgery", "手术与麻醉", ("手术", "术前", "术后", "麻醉", "禁食", "禁水")),
    ("care", "住院照护", ("发热", "发烧", "疼痛", "血压", "跌倒", "过敏", "压疮")),
)

TOPIC_LABELS = {key: label for key, label, _ in TOPICS}
CARE_QUESTIONS = (
    "这个结果或症状，最需要先排除什么？",
    "下一步需要复查、做检查还是先观察？",
    "出现哪些变化要提前联系或立即就医？",
    "复诊时需要带哪些资料？",
)


def _has(text, words):
    folded = text.casefold()
    return any(word.casefold() in folded for word in words)


def classify(text):
    if _has(text, CRISIS):
        return "crisis"
    if _has(text, URGENT):
        return "urgent"
    if _has(text, MEDICATION):
        return "medication"
    if _has(text, DIAGNOSIS):
        return "diagnosis"
    if _has(text, DISCHARGE_HINTS):
        return "discharge"
    if _has(text, MENTAL_HINTS):
        return "mental"
    if _has(text, INFECTION_HINTS):
        return "infection"
    if _has(text, PROCEDURE_HINTS):
        return "procedure"
    if _has(text, REHAB_HINTS):
        return "rehab"
    if _has(text, NUTRITION_HINTS):
        return "nutrition"
    if _has(text, PREVENTION_HINTS):
        return "prevention"
    if _has(text, REPORT_HINTS):
        return "report"
    if _has(text, SYMPTOM_HINTS):
        return "symptom"
    if _has(text, LIFESTYLE_HINTS):
        return "lifestyle"
    return "general"


def topic_of(text):
    folded = text.casefold()
    for key, label, words in TOPICS:
        if any(word in folded for word in words):
            return {"key": key, "label": label}
    return {"key": "general", "label": "一般医学知识"}


def plan(question):
    category = classify(question)
    topic = topic_of(question)
    return {"category": category, "topic": topic, "red_flag": category in ("crisis", "urgent")}


def _followups(category, topic_key):
    if category in ("crisis", "urgent", "diagnosis"):
        return []
    if category == "medication" or topic_key == "medication":
        return ["漏服了一次怎么办？", "这个药和别的药能一起吃吗？", "出现皮疹或黑便怎么办？"]
    if category == "discharge":
        return ["出院后多久复诊？", "哪些药需要长期吃？", "出现什么情况要提前回医院？"]
    if category == "mental":
        return ["睡不着可以先做什么？", "什么时候需要找心理科？", "家人怎么帮助我？"]
    if category == "infection":
        return ["陪护需要注意什么？", "什么时候可以解除隔离？", "手卫生怎么做？"]
    if category == "rehab":
        return ["现在适合做哪些活动？", "活动时出现什么要停？", "需要康复科评估吗？"]
    if category == "nutrition":
        return ["我现在适合吃什么？", "需要请营养科吗？", "哪些食物要暂时避免？"]
    if category == "prevention":
        return ["我适合接种哪些疫苗？", "多久做一次筛查？", "生活方式先改哪一项？"]
    if category == "report":
        return ["这个指标需要空腹复查吗？", "复查前要注意什么？", "这个结果和我在吃的药有关吗？"]
    if category == "procedure":
        return ["术前为什么要禁食？", "术后什么时候能下床？", "伤口出现什么情况要叫医护？"]
    if category == "symptom":
        return ["这个症状需要马上处理吗？", "出现哪些变化要叫医护？", "复诊时怎么跟医生说清楚？"]
    if category == "lifestyle":
        return ["住院期间饮食要注意什么？", "现在能下床活动吗？", "洗澡和如厕要注意什么？"]
    return ["我该把这个问题问哪个科？", "看报告前要准备什么？", "复诊要带哪些资料？"]


def _doctor_questions(category, topic_key):
    if category == "diagnosis":
        return ["医生目前考虑哪些可能？依据是什么？", "还需要做哪些检查来确认？", "下一步治疗和复诊怎么安排？"]
    if category == "medication" or topic_key == "medication":
        return ["这个药主要是治什么的？", "漏服或不舒服时应该怎么处理？", "和其他药一起吃要注意什么？", "出现哪些反应要马上说？"]
    if category == "discharge":
        return ["出院后复诊时间和科室是什么？", "哪些药需要长期吃、哪些可以停？", "伤口、饮食和活动分别注意什么？", "出现哪些情况要提前回医院？"]
    if category == "mental":
        return ["我的情绪和睡眠问题需要专科评估吗？", "现在用的药会不会影响情绪或睡眠？", "出现自伤想法时应该找谁？"]
    if category == "infection":
        return ["我现在需要哪种隔离措施？", "陪护和探视要注意什么？", "什么时候可以解除隔离？"]
    if category == "rehab":
        return ["我现在适合多大强度的活动？", "哪些动作可能影响伤口或安全？", "需要康复科制定计划吗？"]
    if category == "nutrition":
        return ["我的病需要限制盐、蛋白或水分吗？", "现在体重变化需要营养科吗？", "哪些补品或食物要避免？"]
    if category == "prevention":
        return ["我目前适合哪些疫苗和筛查？", "生活方式先从哪一项改起？", "需要转社区或专科随访吗？"]
    if category == "procedure":
        return ["术前/术后我自己要注意什么？", "出现哪些情况要叫医护？", "什么时候可以恢复饮食和活动？"]
    if category == "report":
        return ["这个指标和参考区间相比具体偏了多少？", "这次结果和上次比是变好还是变差？", "需要复查或进一步检查吗？", "这个结果会不会受正在用的药影响？"]
    if category == "symptom":
        return ["这个症状最可能和哪些因素有关？", "需要马上处理还是可以观察？", "出现哪些变化要提前叫医护？"]
    if category == "lifestyle":
        return ["我现在适合什么饮食和活动？", "有哪些动作或食物要避免？", "需要请营养科或康复科会诊吗？"]
    return list(CARE_QUESTIONS)


def _result(answer, *, provider, retrieval, category, topic, sources=None,
            followups=None, doctor_questions=None, external_ai=False):
    return {
        "answer": answer,
        "sources": sources or [],
        "provider": provider,
        "retrieval": retrieval,
        "category": category,
        "topic": topic["label"],
        "topic_key": topic["key"],
        "followups": list(followups or []),
        "doctor_questions": list(doctor_questions or []),
        "external_ai": external_ai,
    }


MEDICATION_NOTES = {
    "hormone": "长期用激素可能影响血糖、血压、体重、睡眠和骨骼；不要自行停药或突然减量，"
               "调整由开药医生决定。",
    "antibiotic": "抗生素可能有胃肠道不适、皮疹；是否继续、更换或停药由开药医生决定，"
                  "不要自行加量。",
    "anticoagulant": "抗凝药最主要的风险是出血，例如黑便、血尿、牙龈持续出血或不明原因瘀斑；"
                     "不要自行停药、加量或叠加止痛药。",
}


def _medication_note(question, topic_key):
    note = MEDICATION_NOTES.get(topic_key)
    if note:
        return note
    if any(word in question for word in ("激素", "泼尼松", "地塞米松", "甲泼尼龙")):
        return MEDICATION_NOTES["hormone"]
    if any(word in question for word in ("抗生素", "消炎药", "头孢", "阿莫西林", "左氧氟沙星")):
        return MEDICATION_NOTES["antibiotic"]
    if any(word in question for word in ("抗凝", "华法林", "利伐沙班", "阿哌沙班")):
        return MEDICATION_NOTES["anticoagulant"]
    return ""


def boundary_answer(connection, question, current_plan=None):
    """Return a safe local answer for high-risk intents, else None."""
    current_plan = current_plan or plan(question)
    category = current_plan["category"]
    topic = current_plan["topic"]
    if category not in ("crisis", "urgent", "diagnosis", "medication"):
        return None
    if category == "crisis":
        return _result(
            "【需要立即处理】你描述的情况可能需要现场急救。请立即按床旁呼叫铃、叫身边人或拨打 120，"
            "不要等待聊天回复。本演示不会派出急救人员，也不会通知医护。",
            provider="local_safety", retrieval="local_medical_boundary",
            category="crisis", topic=topic, external_ai=False)
    if category == "urgent":
        return _result(
            "【尽快联系医护】你描述的情况不适合只靠聊天判断。请尽快联系病区医护或使用床旁呼叫铃；"
            "如果正在加重，按急症处理。本演示不会派出急救人员。",
            provider="local_safety", retrieval="local_medical_boundary",
            category="urgent", topic=topic, external_ai=False)
    if category == "diagnosis":
        return _result(
            compose_answer(
                "我不能根据聊天里的一句话判断你得没得某种病，也不能判断严重程度。",
                ["判断通常需要医生问诊、查体，结合检验/影像、既往病史和用药情况",
                 "只看一个指标或一句描述容易误判",
                 "把具体报告、检查时间和症状记下来，复诊时逐条问主管医生"]),
            provider="local_medical_boundary", retrieval="local_medical_boundary",
            category="diagnosis", topic=topic,
            doctor_questions=_doctor_questions(category, topic["key"]), external_ai=False)
    sources = [citation(chunk) for chunk in retrieve(connection, "medical", question, limit=2)]
    note = _medication_note(question, topic["key"])
    points = [note] if note else []
    points.append("把药名、当前用法、漏服或不适的时间、正在用的其他药记下来")
    points.append("联系开药医生或药师核对；不要自行补双倍，也不要叠加含同一种成分的药")
    return _result(
        compose_answer(
            "我不能根据聊天给你停药、换药、加量或减量的建议。",
            points,
            alert="出现呼吸困难、面唇肿胀、黑便、血尿或持续出血，立即联系医护"),
        provider="local_medical_boundary", retrieval="local_medical_boundary",
        category="medication", topic=topic, sources=sources,
        followups=_followups(category, topic["key"]),
        doctor_questions=_doctor_questions(category, topic["key"]), external_ai=False)


def decorate(result, question):
    """Add agent metadata to a local care/checklist result without changing it."""
    current_plan = plan(question)
    category = result.get("category") or current_plan["category"]
    topic = current_plan["topic"]
    result.setdefault("topic", topic["label"])
    result.setdefault("topic_key", topic["key"])
    result.setdefault("followups", _followups(category, topic["key"]))
    result.setdefault("doctor_questions", _doctor_questions(category, topic["key"]))
    result.setdefault("external_ai", False)
    return result


def enrich(result, question):
    """Shape a retrieved/model answer into the same structured contract."""
    current_plan = plan(question)
    topic = current_plan["topic"]
    category = "report" if current_plan["category"] in ("report", "general") and _has(question, REPORT_HINTS) else current_plan["category"]
    return _result(
        result["answer"], provider=result["provider"], retrieval=result["retrieval"],
        category=category, topic=topic, sources=result.get("sources"),
        followups=_followups(category, topic["key"]),
        doctor_questions=_doctor_questions(category, topic["key"]),
        external_ai=result["provider"] not in ("local_safety", "mock"),
    )
