"""Deterministic legal guide for common patient questions.

This module handles the recurring, high-risk topics with reviewed local text
and citations. General legal knowledge questions still go to the knowledge
provider, but never with patient records or conversation history.
"""
from app.services.knowledge import citation, retrieve

CRISIS = ("打我", "被打", "打人", "殴打", "打了", "受伤", "暴力", "威胁", "人身安全", "限制自由", "报警", "不想活", "自杀")
CONSENT = ("知情同意", "签字", "同意书", "手术同意", "特殊检查", "特殊治疗", "替代方案", "风险说明")
RECORDS = ("病历", "病历本", "复印", "复制", "查阅", "封存", "医嘱单", "住院志", "护理记录")
PRIVACY = ("隐私", "个人信息", "泄露", "公开", "保密", "授权", "撤回", "敏感信息")
DISPUTE = ("纠纷", "投诉", "调解", "诉讼", "起诉", "鉴定", "协商", "医务科")
LIABILITY = ("误诊", "过错", "医疗事故", "医院有责任", "承担责任", "能不能赢", "胜算", "责任程度")
COMPENSATION = ("赔多少", "赔偿金额", "能赔", "要多少钱", "赔偿项目")
OVERCHECK = ("过度检查", "不必要检查", "乱检查", "重复检查")
OUT_OF_SCOPE = ("劳动", "工伤", "离婚", "房产", "继承", "合同", "交通事故", "刑事", "欠款", "租房")

TOPICS = {
    "consent": "知情同意与签字",
    "records": "病历查阅、复制与封存",
    "privacy": "隐私与个人信息",
    "dispute": "医疗纠纷处理",
    "liability": "医疗损害责任",
    "compensation": "赔偿与鉴定",
    "overcheck": "检查的必要性",
    "crisis": "人身安全",
    "out_of_scope": "超出本模块范围",
    "general": "医疗法律知识",
}

FOLLOWUPS = {
    "consent": ["签字前我可以问哪些问题？", "紧急情况下没签字怎么办？", "同意书签了还能投诉吗？"],
    "records": ["病历可以复印哪些？", "医院不给复印怎么办？", "病历封存怎么启动？"],
    "privacy": ["授权后还能撤回吗？", "医院能公开我的病历吗？", "信息泄露后可以怎么处理？"],
    "dispute": ["协商、调解、诉讼怎么选？", "需要准备哪些材料？", "医疗损害鉴定看什么？"],
    "overcheck": ["怎么判断检查是否必要？", "怀疑过度检查先找谁？"],
    "general": ["知情同意书里重点看什么？", "病历复印和封存有什么区别？", "发生纠纷先找哪个部门？"],
}

MATERIALS = {
    "consent": ["知情同意书/手术同意书", "医生对风险、替代方案的说明记录", "患者或家属的问题清单"],
    "records": ["身份证/就诊凭证", "病历资料清单", "已复印或拍照的病历", "封存申请/沟通记录"],
    "privacy": ["授权/同意记录", "泄露内容截图或时间线", "与医院沟通记录"],
    "dispute": ["就诊时间线", "病历复印件/封存清单", "费用清单和票据", "沟通记录", "损害后果资料"],
    "overcheck": ["检查申请单", "费用清单", "病历和医嘱", "与医生沟通记录"],
    "general": ["就诊时间线", "相关病历/同意书", "与医护沟通记录"],
}

NEXT_STEPS = {
    "consent": ["要求医生用大白话说明风险、替代方案和“不做”的后果",
                "确认理解后再签；有疑问先问",
                "紧急情况由医院按规定处理，事后可要求说明"],
    "records": ["向病案室书面申请查阅/复制",
                "核对清单和页码，要求加盖证明印记",
                "发生争议时申请医患双方在场封存"],
    "privacy": ["要求医院说明处理目的、范围和保存期限",
                "撤回同意并要求停止后续处理（法定留存除外）",
                "向医务科/投诉部门书面反映，必要时咨询12348"],
    "dispute": ["先固定病历和费用材料",
                "向医院医务科/投诉部门书面反映",
                "协商不成可申请人民调解、行政调解或诉讼",
                "需要责任判断时申请医疗损害鉴定"],
    "overcheck": ["保留检查申请单和费用清单", "向医务科书面询问检查目的和依据", "必要时请专业律师评估"],
    "general": ["先确认事实和时间线", "把问题写成清单", "向医务科、12348或律师核实"],
}

PROFESSIONAL_QUESTIONS = {
    "consent": ["这个操作的必要性、主要风险和替代方案是什么？", "如果不做，可能有什么后果？", "同意书里哪些条款需要我特别注意？"],
    "records": ["复制病历需要哪些材料、多久能拿到？", "能否加盖病案室证明印记？", "如果发生争议，病历封存怎么启动？"],
    "privacy": ["我的哪些信息会被共享，目的是什么？", "撤回授权后，医院还会保留哪些资料？", "如果信息泄露，医院内部怎么处理？"],
    "dispute": ["医院内部投诉/医务科的处理流程是什么？", "病历和现场实物是否已经封存？", "是否建议先调解或做鉴定？"],
    "liability": ["根据现有病历，需要重点核实哪些诊疗环节？", "是否需要做医疗损害鉴定？", "如果要主张权利，诉讼时效和证据保全要注意什么？"],
    "compensation": ["赔偿项目通常包括哪些？", "需要哪些票据和证明材料？", "责任程度和伤残等级如何影响金额？"],
    "overcheck": ["这项检查的诊断目的和依据是什么？", "如果不做这项检查，会影响哪些判断？"],
    "general": ["我这个情况适用哪些规定？", "需要准备哪些材料？", "下一步找医务科、12348还是律师？"],
}

BOUNDARY = {"crisis", "liability", "compensation"}


def _text(text):
    return (text or "").casefold()


def _has(text, words):
    return any(word in text for word in words)


def classify(text):
    folded = _text(text)
    if _has(folded, CRISIS):
        return "crisis"
    if _has(folded, COMPENSATION):
        return "compensation"
    if _has(folded, LIABILITY):
        return "liability"
    if _has(folded, CONSENT):
        return "consent"
    if _has(folded, PRIVACY):
        return "privacy"
    if _has(folded, RECORDS):
        return "records"
    if _has(folded, DISPUTE):
        return "dispute"
    if _has(folded, OVERCHECK):
        return "overcheck"
    if _has(folded, OUT_OF_SCOPE):
        return "out_of_scope"
    return "general"


def plan(question):
    category = classify(question)
    return {
        "category": category,
        "topic": TOPICS[category],
        "topic_key": category,
        "followups": FOLLOWUPS.get(category, []),
        "doctor_questions": PROFESSIONAL_QUESTIONS.get(category, []),
        "materials": MATERIALS.get(category, []),
        "next_steps": NEXT_STEPS.get(category, []),
        "external_ai": False,
    }


def _answer(question, category, answer, connection, provider):
    chunks = retrieve(connection, "legal", question, limit=3)
    result = plan(question)
    result.update({
        "answer": answer,
        "provider": provider,
        "retrieval": provider,
        "sources": [citation(chunk) for chunk in chunks],
    })
    return result


def boundary_answer(connection, question):
    category = classify(question)
    if category == "crisis":
        return _answer(
            question, category,
            "如果正在发生暴力、威胁、限制人身自由，或你感到人身危险：先离开现场，呼叫医院保安，"
            "拨打110；有伤情拨打120。保留伤情照片、时间线和证人信息。不要等待聊天回复；"
            "这个演示不会通知任何人。",
            connection, "local_legal_boundary")
    if category == "liability":
        return _answer(
            question, category,
            "我不能替你判断这是不是误诊，也猜不出能不能赢。要看医院有没有责任，一般看四件事："
            "医生怎么治的、你受了什么损害、医院有没有过错、这个过错和损害有没有关系。"
            "病历、鉴定意见、费用票据是最关键的证据。你可以先把病历和沟通记录留好，"
            "再找律师或鉴定机构看。",
            connection, "local_legal_boundary")
    if category == "compensation":
        return _answer(
            question, category,
            "我没法凭几句话算出能赔多少。赔偿一般看这些：你花了多少医疗费、误工和护理损失、"
            "有没有伤残，再加上医院的责任有多大、鉴定怎么认定。病历、票据、沟通记录都要留好。"
            "你可以先问医务科，再打12348或找律师核实。",
            connection, "local_legal_boundary")
    return None


def guide_answer(connection, question):
    category = classify(question)
    if category == "consent":
        return _answer(
            question, category,
            "签字不是走个过场。做手术、特殊检查或特殊治疗前，医生要用你听得懂的话讲清楚："
            "要做什么、有什么风险、还有没有别的办法，然后拿到你的书面同意。"
            "你自己没法决定、或者不适合直接告诉你时，会讲给近亲属听并签字。"
            "你可以先问四句话：为什么做、不做会怎样、还有没有别的选择、最坏会怎样。"
            "签了字也不等于不能追究过错；当时没讲清楚，你可以要求补讲，把同意书和沟通记录留好。"
            "抢救等紧急情况另有规定。",
            connection, "local_legal_guide")
    if category == "records":
        return _answer(
            question, category,
            "自己的病历，你可以查、也可以复印：门诊病历、住院记录、体温单、医嘱单、检验报告、"
            "片子、同意书、手术和麻醉记录、病理、护理记录、费用清单都算。"
            "医院要给你复印并盖章，复印时你或近亲属在场。真出纠纷，可以要求医患双方一起把病历封存，"
            "列个清单各拿一份。医院要是藏、不给、弄丢或者改病历，对它不利，"
            "但是不是有过错，还得看事实。",
            connection, "local_legal_guide")
    if category == "privacy":
        return _answer(
            question, category,
            "病历和健康信息是敏感信息。医院要用它，得有明确目的和必要理由，通常还要单独征得你同意。"
            "你可以随时撤回同意，撤回后医院要停止后续处理（法律要求留存的除外）。"
            "医生和医院有保密义务；泄露、或者没经你同意就公开病历，可能要担责。",
            connection, "local_legal_guide")
    if category == "dispute":
        return _answer(
            question, category,
            "碰上医疗纠纷，先把病历和费用单据固定好，再书面找医院医务科或投诉部门。"
            "路子一般有四条：双方协商、人民调解、行政调解、打官司（诉讼）。协商不下来，"
            "可以申请医疗纠纷人民调解；要弄清责任，就做医疗损害鉴定。"
            "具体走哪条、能不能赔，得看事实、证据和鉴定，光靠聊天判断不了。",
            connection, "local_legal_guide")
    if category == "overcheck":
        return _answer(
            question, category,
            "怀疑做了没必要的检查，先把检查申请单、费用清单和病历留好，再书面问医务科或投诉部门："
            "这项检查为什么做、依据是什么。是不是“违反诊疗规范的不必要检查”，"
            "要结合你的病情和专业判断，不能只看做了几项检查。",
            connection, "local_legal_guide")
    if category == "out_of_scope":
        return _answer(
            question, category,
            "这里只讲看病过程中那四件事：知情同意、病历资料、隐私保护、医疗纠纷。"
            "劳动、工伤、交通事故、离婚继承、房子这些不归这里管；"
            "你可以打12348公共法律服务热线，或者找律师。",
            connection, "local_legal_guide")
    return None


def answer(connection, question):
    """Return a deterministic answer for recurring topics, or None for general Q&A."""
    return boundary_answer(connection, question) or guide_answer(connection, question)


def enrich(result, question):
    """Add legal structure to a provider answer without changing its text."""
    result.update(plan(question))
    result["external_ai"] = result.get("provider") not in ("local_safety", "mock")
    return result
