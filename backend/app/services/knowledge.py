"""Small reviewed knowledge base. SQLite keyword retrieval, no vector service.

Sources are versioned and date-bounded; only published sources are eligible.
This is a demo corpus, not a clinical guideline or an official legal database.
"""
import json
from datetime import datetime, timezone

from app.ai.providers.base import KnowledgeChunk
from app.services.medical_knowledge import MEDICAL_ENTRIES, MEDICAL_SOURCES

SEED_TIME = "2026-10-20T00:00:00+00:00"

# Plain-language synonyms for local retrieval. This is deliberately small and
# deterministic; it expands a patient's wording, not the model's knowledge.
MEDICAL_SYNONYMS = {
    "验血": "血常规 检验",
    "血象": "血常规 白细胞",
    "肝功": "肝功能 转氨酶",
    "转氨酶": "肝功能",
    "alt": "转氨酶 肝功能",
    "ast": "转氨酶 肝功能",
    "肾功": "肾功能 肌酐",
    "肌酐": "肾功能",
    "血糖高": "血糖 糖尿病",
    "糖化": "血糖",
    "电解质": "钾 钠",
    "凝血": "PT INR 抗凝",
    "尿检": "尿常规",
    "片子": "影像 CT X光 超声",
    "ct": "影像 CT",
    "b超": "超声 影像",
    "副作用": "用药 不良反应",
    "这个药": "用药",
    "消炎药": "抗生素 用药",
    "抗生素": "用药",
    "输液": "输液 留置针",
    "留置针": "输液",
    "止痛": "止痛药 疼痛",
    "抗凝": "凝血 出血",
    "手术": "术前 术后",
    "发烧": "发热 体温",
    "血压高": "血压 高血压",
    "摔": "跌倒",
    "过敏": "药物过敏",
}

# Broader colloquial wording for the expanded patient-education corpus. These
# only expand the query; they never broaden the source domain or bypass review.
MEDICAL_SYNONYMS.update({
    "c反应蛋白": "C反应蛋白 CRP 炎症",
    "crp": "C反应蛋白 炎症",
    "pct": "降钙素原 感染",
    "血气": "血气分析 氧合 酸碱",
    "氧分压": "血气 氧合",
    "肌钙蛋白": "心肌标志物 心肌 心梗",
    "心梗": "心肌梗死 肌钙蛋白 胸痛",
    "甲功": "甲状腺 TSH FT3 FT4",
    "促甲状腺": "甲状腺 TSH",
    "肿瘤标志物": "肿瘤 癌症 复查",
    "癌胚抗原": "肿瘤标志物 CEA",
    "血脂": "胆固醇 低密度脂蛋白 甘油三酯",
    "胆固醇": "血脂 低密度脂蛋白",
    "便检": "便常规 隐血",
    "大便": "便常规 排便 隐血",
    "铁蛋白": "贫血 缺铁",
    "叶酸": "贫血 维生素B12",
    "糖化": "糖化血红蛋白 血糖",
    "尿酸高": "尿酸 痛风",
    "痛风": "尿酸 关节",
    "发烧": "发热 体温",
    "咳痰": "咳嗽 痰",
    "气短": "呼吸困难 喘",
    "喘": "呼吸困难 哮喘",
    "肚子痛": "腹痛",
    "胃痛": "腹痛 胃炎",
    "拉肚子": "腹泻",
    "便秘": "排便 便秘",
    "眩晕": "头晕",
    "偏头痛": "头痛",
    "浮肿": "水肿",
    "腿肿": "水肿 血栓",
    "疹子": "皮疹 过敏",
    "没劲": "乏力",
    "睡不着": "失眠 睡眠",
    "心慌": "心悸 心慌",
    "心跳快": "心悸",
    "手麻": "麻木 神经",
    "脚麻": "麻木 神经",
    "中风": "脑卒中 偏瘫",
    "高血压": "血压 降压药",
    "血压高": "高血压 血压",
    "糖尿病": "血糖 降糖",
    "血糖高": "血糖 糖尿病",
    "冠心病": "心绞痛 支架 冠心病",
    "支架": "冠心病 抗血小板",
    "慢阻肺": "哮喘 吸入剂 肺",
    "肺炎": "肺部感染 咳嗽 发热",
    "尿路感染": "尿频 尿痛 尿培养",
    "胃溃疡": "胃炎 幽门螺杆菌 黑便",
    "肝硬化": "肝炎 肝功能 腹水",
    "肾病": "肾功能 肌酐 尿量",
    "贫血": "血红蛋白 缺铁",
    "甲减": "甲状腺 左甲状腺素",
    "甲亢": "甲状腺 抗甲状腺",
    "癌症": "肿瘤 病理 分期",
    "糊涂": "谵妄 意识",
    "降压药": "高血压 降压",
    "降糖药": "糖尿病 血糖",
    "二甲双胍": "降糖药",
    "胰岛素": "糖尿病 低血糖",
    "他汀": "血脂 胆固醇",
    "激素": "糖皮质激素",
    "胃药": "抑酸药 质子泵抑制剂",
    "利尿": "利尿剂 水肿",
    "吸入剂": "哮喘 慢阻肺",
    "吗啡": "阿片 止痛",
    "泻药": "便秘 乳果糖",
    "补铁": "铁剂 贫血",
    "补钾": "钾 电解质",
    "抽血": "抽血 检验",
    "增强ct": "造影剂 增强CT",
    "核磁": "磁共振 MRI",
    "胃镜": "内镜 胃镜",
    "肠镜": "内镜 肠镜",
    "气管镜": "支气管镜",
    "腰穿": "腰椎穿刺",
    "活检": "病理 穿刺",
    "导尿": "导尿管 尿量",
    "胃管": "鼻饲 管饲",
    "引流": "引流管 引流量",
    "造口": "造口护理 造口袋",
    "跌倒": "摔倒 跌倒",
    "褥疮": "压疮 翻身",
    "血栓": "静脉血栓 踝泵",
    "营养": "饮食 营养",
    "出院": "出院 复诊 随访",
    "复诊": "随访 复诊",
    "孕妇": "怀孕 孕产",
    "哺乳": "母乳 哺乳",
    "焦虑": "情绪 焦虑",
    "抑郁": "情绪 抑郁",
    "临终": "安宁疗护",
    "戒烟": "吸烟 戒烟",
    "喝酒": "饮酒 酒精",
    "疫苗": "接种 疫苗",
    "筛查": "体检 筛查",
})


LEGAL_SYNONYMS = {
    "签字": "知情同意 同意书",
    "手术同意": "知情同意 手术",
    "同意书": "知情同意 书面",
    "风险": "知情同意 说明",
    "替代方案": "知情同意 替代",
    "复印": "病历 复制",
    "复制": "病历 复制",
    "封存": "病历 封存 清单",
    "病历": "病历 复制 封存",
    "病历本": "病历 复制",
    "隐私": "隐私 个人信息",
    "泄露": "隐私 个人信息 保密",
    "授权": "同意 个人信息",
    "撤回": "撤回 同意 个人信息",
    "投诉": "纠纷 投诉 调解",
    "纠纷": "纠纷 协商 调解 诉讼",
    "赔偿": "赔偿 责任 损害",
    "赔多少": "赔偿 金额",
    "误诊": "过错 责任 损害",
    "医疗事故": "过错 责任 鉴定",
    "鉴定": "鉴定 过错 因果关系",
    "调解": "调解 纠纷",
    "起诉": "诉讼 纠纷",
}


def _expand_legal_text(text):
    folded = text.casefold()
    extras = [value for key, value in LEGAL_SYNONYMS.items() if key in folded]
    return text + (" " + " ".join(extras) if extras else "")


def _expand_medical_text(text):
    folded = text.casefold()
    extras = [value for key, value in MEDICAL_SYNONYMS.items() if key in folded]
    return text + (" " + " ".join(extras) if extras else "")

SEED_SOURCES = (
    {
        "id": "src-med-1", "domain": "medical",
        "title": "医法智联演示健康提示（非临床指南）",
        "publisher": "医法智联示例知识库", "url": None,
        "document_version": "2026.1", "effective_from": "2026-10-01",
        "effective_until": None, "reviewed_by": "demo-reviewer-001",
        "reviewed_at": "2026-10-19T08:00:00+00:00", "status": "published",
    },
    {
        "id": "src-med-lab", "domain": "medical",
        "title": "常见检验指标科普（演示）",
        "publisher": "医法智联示例知识库", "url": None,
        "document_version": "2026.1", "effective_from": "2026-10-01",
        "effective_until": None, "reviewed_by": "demo-reviewer-001",
        "reviewed_at": "2026-10-19T08:00:00+00:00", "status": "published",
    },
    {
        "id": "src-med-med", "domain": "medical",
        "title": "住院用药安全科普（演示）",
        "publisher": "医法智联示例知识库", "url": None,
        "document_version": "2026.1", "effective_from": "2026-10-01",
        "effective_until": None, "reviewed_by": "demo-reviewer-001",
        "reviewed_at": "2026-10-19T08:00:00+00:00", "status": "published",
    },
    {
        "id": "src-med-care", "domain": "medical",
        "title": "住院照护与检查科普（演示）",
        "publisher": "医法智联示例知识库", "url": None,
        "document_version": "2026.1", "effective_from": "2026-10-01",
        "effective_until": None, "reviewed_by": "demo-reviewer-001",
        "reviewed_at": "2026-10-19T08:00:00+00:00", "status": "published",
    },
    {
        "id": "src-law-civil", "domain": "legal",
        "title": "《中华人民共和国民法典》相关条文（演示摘录）",
        "publisher": "全国人民代表大会",
        "url": "https://gdca.miit.gov.cn/zwgk/zcwj/flfg/art/2020/art_573d6ef5018b46b6a4e1f31ca085a710.html",
        "document_version": "2020-05-28", "effective_from": "2021-01-01",
        "effective_until": None, "reviewed_by": "demo-reviewer-001",
        "reviewed_at": "2026-10-19T08:00:00+00:00", "status": "published",
    },
    {
        "id": "src-law-dispute", "domain": "legal",
        "title": "《医疗纠纷预防和处理条例》相关条文（演示摘录）",
        "publisher": "国务院",
        "url": "https://www.gov.cn/zhengce/content/2018-08/31/content_5318057.htm",
        "document_version": "2018-08-31", "effective_from": "2018-10-01",
        "effective_until": None, "reviewed_by": "demo-reviewer-001",
        "reviewed_at": "2026-10-19T08:00:00+00:00", "status": "published",
    },
    {
        "id": "src-law-pipl", "domain": "legal",
        "title": "《中华人民共和国个人信息保护法》相关条文（演示摘录）",
        "publisher": "全国人民代表大会常务委员会",
        "url": "https://www.cac.gov.cn/2021-08/20/c_1631050028355286.htm",
        "document_version": "2021-08-20", "effective_from": "2021-11-01",
        "effective_until": None, "reviewed_by": "demo-reviewer-001",
        "reviewed_at": "2026-10-19T08:00:00+00:00", "status": "published",
    },
) + MEDICAL_SOURCES


def _source(source_id):
    return next(item for item in SEED_SOURCES if item["id"] == source_id)


def _chunk(chunk_id, source_id, title, text, keywords, position):
    source = _source(source_id)
    return KnowledgeChunk(
        chunk_id, source["domain"], title, text, source["url"], tuple(keywords),
        source_id=source_id, source_title=source["title"],
        version=source["document_version"], status=source["status"],
        effective_from=source["effective_from"], reviewed_by=source["reviewed_by"])


SEED_CHUNKS = (
    _chunk("med-001", "src-med-1", "住院用药：先核对再记录",
           "住院期间用药应以医嘱和主管医护的说明为准。可以记录药名、剂量、时间和身体反应；"
           "发现不适或漏服先联系医护，不要自行加量、停药或换药。",
           ("用药", "药", "剂量", "服药", "过敏"), 0),
    _chunk("med-002", "src-med-1", "住院监测：读数要带时间和来源",
           "心率和血压等读数要记录测量时间、来源和单位。单次异常或没有记录不等于诊断结论；"
           "持续不适请联系医护现场核对。",
           ("血压", "心率", "血氧", "监测", "测量", "记录"), 1),
    _chunk("med-003", "src-med-1", "急症与求助：先联系现场医护",
           "出现胸痛、胸闷、呼吸困难、意识异常等情况，应立即使用床旁呼叫器或联系病区医护，"
           "不要等待聊天回复。本演示不会派出急救人员。",
           ("胸痛", "胸闷", "呼吸困难", "喘不过气", "昏迷", "急症"), 2),
    _chunk("med-004", "src-med-1", "检验单核对：单位、小数点与参考区间",
           "检验结果要结合参考区间、单位和采样时间核对。拍照识别可能有误，确认前不要据此调整用药；"
           "看不懂的项目请向医护核实。",
           ("检验", "报告", "结果", "单位", "参考", "小数点"), 3),
    _chunk("med-101", "src-med-lab", "血常规：白细胞、红细胞和血小板",
           "血常规主要看白细胞、红细胞和血红蛋白、血小板。白细胞升高可能与感染、炎症、应激等有关，"
           "也可能受药物影响；单次结果不能直接确定病因，要结合症状、采样时间和既往结果。",
           ("血常规", "白细胞", "红细胞", "血红蛋白", "血小板", "贫血", "感染", "炎症"), 4),
    _chunk("med-102", "src-med-lab", "肝功能：转氨酶和胆红素说明什么",
           "肝功能里的转氨酶、胆红素、白蛋白反映不同方面。转氨酶升高可能与肝脏、药物、饮酒、"
           "剧烈运动等有关，也可能只是一过性变化；单看一次结果不能判断肝损伤程度或原因。",
           ("肝功能", "转氨酶", "谷丙", "谷草", "ALT", "AST", "胆红素", "白蛋白", "黄疸"), 5),
    _chunk("med-103", "src-med-lab", "肾功能：肌酐、尿素氮和滤过率",
           "肾功能常看肌酐、尿素氮和估算滤过率。结果会受年龄、肌肉量、饮水和当天状态影响；"
           "一次异常不等于肾衰竭，也不能据此自行停药，尤其降压药、止痛药和抗生素要问开药医生。",
           ("肾功能", "肌酐", "尿素氮", "eGFR", "滤过率", "尿量"), 6),
    _chunk("med-104", "src-med-lab", "血糖：空腹、餐后和糖化血红蛋白",
           "血糖要区分空腹、餐后和随机值，糖化血红蛋白反映近一段时间平均水平。一次偏高不等于糖尿病，"
           "一次偏低也要看是否伴心慌、出汗、手抖；具体判断要结合采血时间和用药。",
           ("血糖", "空腹", "餐后", "糖化", "低血糖", "高血糖", "糖尿病"), 7),
    _chunk("med-105", "src-med-lab", "电解质：钾、钠、氯、钙",
           "电解质里钾、钠、氯、钙的异常可能影响心跳、肌肉和意识。轻度异常不一定有感觉，"
           "明显异常可能需要及时处理；看到“危急值”或伴心慌、乏力、抽搐，应立即叫医护。",
           ("电解质", "钾", "钠", "氯", "钙", "低钾", "高钾", "低钠"), 8),
    _chunk("med-106", "src-med-lab", "凝血功能：PT、INR 和抗凝药",
           "凝血功能常看 PT、INR、APTT 等。服用华法林、利伐沙班等抗凝药时，结果要和用药时间、"
           "剂量一起看；牙龈出血、黑便、血尿、碰撞后大片淤青要告诉医护，不要自行加量或停药。",
           ("凝血", "PT", "INR", "APTT", "抗凝", "华法林", "利伐沙班", "出血", "黑便"), 9),
    _chunk("med-107", "src-med-lab", "尿常规：蛋白、红细胞和白细胞",
           "尿常规里的蛋白、红细胞、白细胞、酮体等会受饮水、月经、取样和运动影响。一次异常可能需要"
           "复查晨尿；尿路感染不能只凭尿常规一项确定，要结合尿频、尿痛、发热等症状。",
           ("尿常规", "尿蛋白", "尿红细胞", "尿白细胞", "酮体", "尿路感染", "尿频", "尿痛"), 10),
    _chunk("med-108", "src-med-lab", "心电图：窦性心律和 ST-T 改变",
           "心电图记录的是检查那一刻的心电活动。窦性心律、早搏、ST-T 改变等描述需要结合症状、年龄、"
           "用药和既往心电图；一份报告不能单独确诊心脏病，胸痛心慌时先叫医护。",
           ("心电图", "窦性", "早搏", "ST", "T波", "心律", "心慌", "心悸"), 11),
    _chunk("med-201", "src-med-care", "CT、X光、超声报告里的“待排”",
           "CT、X光、超声、核磁报告里的“考虑”“待排”“不除外”是影像学判断，不是病理确诊。"
           "结节、阴影、囊肿等词需要结合大小、位置、变化和临床情况；不要只看一句话就下结论。",
           ("CT", "X光", "超声", "B超", "核磁", "MRI", "影像", "结节", "阴影", "囊肿"), 12),
    _chunk("med-202", "src-med-care", "输液和留置针：哪些情况要叫医护",
           "输液速度由医护根据药物和病情设置，不要自行调快。留置针周围出现红肿、疼痛、渗液、"
           "发凉或堵管，立即按呼叫铃；输液时心慌、气短、皮疹也要马上说。",
           ("输液", "留置针", "打点滴", "针眼", "红肿", "渗液", "堵管", "输液反应"), 13),
    _chunk("med-203", "src-med-med", "抗生素：为什么不能自己停",
           "抗生素只对细菌感染等特定情况有效，对普通病毒性感冒无效。不同抗生素疗程不同，"
           "不要感觉好转就自行停，也不要漏服后加倍；出现皮疹、腹泻、呼吸困难要联系医护。",
           ("抗生素", "消炎药", "头孢", "阿莫西林", "左氧氟沙星", "疗程", "皮疹", "腹泻"), 14),
    _chunk("med-204", "src-med-med", "止痛药：按医嘱用，不硬扛也不叠加",
           "止痛药按医嘱使用，不要因为担心“上瘾”硬扛，也不要自行加量或叠加多种含同一种成分的药。"
           "常见便秘、恶心可以和医护说；疼痛突然加重或伴出血要尽快处理。",
           ("止痛药", "镇痛", "布洛芬", "对乙酰氨基酚", "疼痛", "便秘", "恶心"), 15),
    _chunk("med-205", "src-med-med", "抗凝药：漏服、出血和拔牙",
           "抗凝药用于预防或治疗血栓，出血风险需要关注。漏服后不要自行补双倍；拔牙、手术、"
           "穿刺前要告诉医生正在用抗凝药；黑便、血尿、呕血、摔倒撞头要立即就医。",
           ("抗凝", "华法林", "利伐沙班", "达比加群", "血栓", "漏服", "拔牙"), 16),
    _chunk("med-206", "src-med-care", "手术前后：禁食、活动和伤口",
           "术前禁食禁水时间、是否停某些药，要按麻醉和手术团队的书面要求，不要自行决定。"
           "术后尽早按医护指导活动、深呼吸和咳嗽有助恢复；伤口红肿渗液、发热、剧烈疼痛要及时说。",
           ("手术", "术前", "术后", "麻醉", "禁食", "禁水", "下床", "伤口", "换药"), 17),
    _chunk("med-207", "src-med-care", "发热：记录时间和伴随症状",
           "发热要记录测量时间、部位和数值，以及有没有寒战、咳嗽、尿痛、腹泻等伴随症状。"
           "退热药按医嘱使用，不要重复叠加；持续高热、意识改变、呼吸困难或皮疹要立即联系医护。",
           ("发热", "发烧", "体温", "退烧", "寒战", "高热"), 18),
    _chunk("med-208", "src-med-care", "疼痛：用 0 到 10 分说清楚",
           "疼痛可以用 0 到 10 分描述，并说清位置、性质（胀痛、刺痛、烧灼）、什么时候加重和伴随症状。"
           "疼痛评分没有“标准答案”，如实说最有助于医护调整处理；突然剧烈疼痛要立即呼叫。",
           ("疼痛", "疼", "评分", "部位", "刺痛", "胀痛"), 19),
    _chunk("med-209", "src-med-care", "血压和心率：一次高不等于高血压",
           "血压和心率受活动、情绪、疼痛、饮水和测量姿势影响。测量前安静休息，记录时间和数值；"
           "一次偏高不等于高血压，头晕、胸痛、气短或血压持续异常要请医护复测。",
           ("血压", "心率", "高压", "低压", "收缩压", "舒张压", "头晕", "复测"), 20),
    _chunk("med-210", "src-med-care", "跌倒和压疮：先叫人，不要自己撑",
           "住院期间不要独自下床、入厕或洗澡，先按呼叫铃请人协助。跌倒后不要急着拉起或走动，"
           "先叫医护评估；长期卧床要按指导翻身、活动踝泵，皮肤发红或破损要及时说。",
           ("跌倒", "摔倒", "压疮", "褥疮", "皮肤", "翻身", "下床", "呼叫铃"), 21),
    _chunk("med-211", "src-med-care", "药物过敏：记住药名和反应",
           "药物过敏要记清药名、用药时间、出现什么反应和处理经过。皮疹、瘙痒、嘴唇肿、呼吸困难"
           "可能是严重过敏，应立即叫医护；不要再次自行使用同类药，后续就诊主动告知过敏史。",
           ("过敏", "皮疹", "瘙痒", "呼吸困难", "药物过敏", "过敏史"), 22),
    _chunk("law-1219", "src-law-civil", "《民法典》第1219条（简要释义）",
           "医务人员应说明病情和医疗措施；手术、特殊检查、特殊治疗通常需要说明风险、替代方案并取得明确同意。"
           "紧急情形另有规则，具体情况请核实。",
           ("知情", "同意", "手术", "风险", "治疗", "法条"), 0),
    _chunk("law-1222", "src-law-civil", "《民法典》第1222条（简要释义）",
           "在法律规定的情形下，如隐匿、拒绝提供与纠纷有关的病历，或者遗失、伪造、篡改、违法销毁病历，"
           "可能推定医疗机构有过错；不等同于自动认定全部赔偿责任。",
           ("病历", "篡改", "纠纷", "过错", "赔偿"), 1),
    _chunk("law-1218", "src-law-civil", "《民法典》第1218条（简要释义）",
           "患者在诊疗活动中受到损害，医疗机构或者其医务人员有过错的，由医疗机构承担赔偿责任。"
           "具体责任仍要结合事实、证据和适用规则判断。",
           ("损害", "过错", "赔偿", "责任", "诊疗"), 2),
    _chunk("law-pipl-15", "src-law-pipl", "《个人信息保护法》第15条（简要释义）",
           "个人信息处理者应当提供便捷的撤回同意方式。撤回同意不影响撤回前基于同意已进行的处理，"
           "但后续处理应停止；法定留存等例外需另行核对。",
           ("授权", "撤回", "同意", "隐私", "个人信息"), 0),
    _chunk("law-pipl-28", "src-law-pipl", "《个人信息保护法》第28条（简要释义）",
           "医疗健康信息属于敏感个人信息。处理应具有特定目的和充分必要性，并采取严格保护措施；"
           "只有在具有特定目的和充分必要性时方可处理。",
           ("敏感", "医疗", "健康", "个人信息", "隐私"), 1),
    _chunk("law-pipl-29", "src-law-pipl", "《个人信息保护法》第29条（简要释义）",
           "处理敏感个人信息应取得个人的单独同意；法律、行政法规规定应当取得书面同意的，从其规定。"
           "单独同意不能由一揽子授权替代。",
           ("单独同意", "敏感", "书面", "授权", "同意"), 2),
    _chunk("law-1220", "src-law-civil", "《民法典》第1220条（简要释义）",
           "因抢救生命垂危的患者等紧急情况，不能取得患者或者其近亲属意见的，经医疗机构负责人"
           "或者授权的负责人批准，可以立即实施相应的医疗措施。",
           ("紧急", "抢救", "生命垂危", "同意", "批准"), 3),
    _chunk("law-1221", "src-law-civil", "《民法典》第1221条（简要释义）",
           "医务人员在诊疗活动中未尽到与当时的医疗水平相应的诊疗义务，造成患者损害的，"
           "医疗机构应当承担赔偿责任。是否尽到义务要结合具体病情和诊疗过程判断。",
           ("诊疗义务", "医疗水平", "过错", "损害", "责任"), 4),
    _chunk("law-1223", "src-law-civil", "《民法典》第1223条（简要释义）",
           "因药品、消毒产品、医疗器械缺陷或者输入不合格血液造成损害的，患者可以向生产者、"
           "血液提供机构等请求赔偿，也可以向医疗机构请求赔偿；医疗机构赔偿后可依法追偿。",
           ("药品", "器械", "血液", "缺陷", "赔偿"), 5),
    _chunk("law-1224", "src-law-civil", "《民法典》第1224条（简要释义）",
           "患者不配合符合诊疗规范的诊疗、医务人员在紧急抢救中已尽合理诊疗义务，或者限于当时"
           "医疗水平难以诊疗的，医疗机构不承担赔偿责任；前两种情形下医疗机构也有过错的，仍应承担相应责任。",
           ("免责", "不配合", "紧急", "医疗水平", "过错"), 6),
    _chunk("law-1225", "src-law-civil", "《民法典》第1225条（简要释义）",
           "医疗机构及其医务人员应当按规定填写并妥善保管住院志、医嘱单、检验报告、手术及麻醉记录、"
           "病理资料、护理记录等病历资料；患者要求查阅、复制这些病历资料的，医疗机构应当及时提供。",
           ("病历", "查阅", "复制", "住院志", "医嘱", "护理记录"), 7),
    _chunk("law-1226", "src-law-civil", "《民法典》第1226条（简要释义）",
           "医疗机构及其医务人员应当对患者的隐私和个人信息保密。泄露患者隐私和个人信息，"
           "或者未经患者同意公开其病历资料的，应当承担侵权责任。",
           ("隐私", "个人信息", "保密", "公开", "病历"), 8),
    _chunk("law-1227", "src-law-civil", "《民法典》第1227条（简要释义）",
           "医疗机构及其医务人员不得违反诊疗规范实施不必要的检查。",
           ("不必要", "检查", "诊疗规范", "过度检查"), 9),
    _chunk("law-1228", "src-law-civil", "《民法典》第1228条（简要释义）",
           "医疗机构及其医务人员的合法权益受法律保护。干扰医疗秩序、妨害医务人员工作生活的，"
           "应当依法承担法律责任。",
           ("合法权益", "医疗秩序", "医务人员", "法律责任"), 10),
    _chunk("law-dispute-13", "src-law-dispute", "《医疗纠纷预防和处理条例》第13条（简要释义）",
           "需要手术，或者开展临床试验等存在一定危险性、可能产生不良后果的特殊检查、特殊治疗的，"
           "医务人员应及时说明医疗风险、替代医疗方案等，并取得书面同意；患者无法自主决定或不宜告知的，"
           "向其近亲属说明并取得书面同意。紧急情况下不能取得意见的，经负责人批准可立即实施相应医疗措施。",
           ("知情同意", "手术", "特殊检查", "书面同意", "风险", "替代方案", "紧急"), 11),
    _chunk("law-dispute-16", "src-law-dispute", "《医疗纠纷预防和处理条例》第16条（简要释义）",
           "患者有权查阅、复制门诊病历、住院志、体温单、医嘱单、检验报告、医学影像资料、特殊检查同意书、"
           "手术同意书、手术及麻醉记录、病理资料、护理记录、医疗费用等病历资料。医疗机构应提供复制服务，"
           "在复制件上加盖证明印记，复制时应有患者或其近亲属在场。",
           ("病历", "查阅", "复制", "复印", "盖章", "医疗费用"), 12),
    _chunk("law-dispute-22", "src-law-dispute", "《医疗纠纷预防和处理条例》第22条（简要释义）",
           "发生医疗纠纷，医患双方可以通过双方自愿协商、申请人民调解、申请行政调解、向人民法院"
           "提起诉讼，以及法律、法规规定的其他途径解决。",
           ("纠纷", "协商", "人民调解", "行政调解", "诉讼"), 13),
    _chunk("law-dispute-24", "src-law-dispute", "《医疗纠纷预防和处理条例》第24条（简要释义）",
           "封存、启封病历资料应在医患双方在场的情况下进行；封存病历可以是原件或复制件，由医疗机构保管。"
           "医疗机构应开列封存清单，由医患双方签字或盖章，各执一份。病历封存满3年未再提出解决纠纷要求的，"
           "医疗机构可以自行启封。",
           ("封存", "启封", "病历", "清单", "医患双方", "3年"), 14),
    _chunk("law-dispute-25", "src-law-dispute", "《医疗纠纷预防和处理条例》第25条（简要释义）",
           "疑似输液、输血、注射、用药等引起不良后果的，医患双方应共同对现场实物进行封存、启封，"
           "封存实物由医疗机构保管；需要检验的，由双方共同委托有资格的检验机构，无法共同委托的由"
           "当地县级卫生主管部门指定。",
           ("输液", "输血", "注射", "用药", "现场实物", "封存", "检验"), 15),
    _chunk("law-dispute-36", "src-law-dispute", "《医疗纠纷预防和处理条例》第36条（简要释义）",
           "医疗损害鉴定意见应载明并论述是否存在医疗损害及损害程度、是否存在医疗过错、"
           "医疗过错与损害之间是否存在因果关系，以及医疗过错在损害中的责任程度。",
           ("鉴定", "医疗损害", "过错", "因果关系", "责任程度"), 16),
) + tuple(
    _chunk(entry["id"], entry["source"], entry["title"], entry["text"],
           entry["keywords"], 100 + index)
    for index, entry in enumerate(MEDICAL_ENTRIES)
)


def seed_knowledge(connection):
    for source in SEED_SOURCES:
        connection.execute(
            """INSERT OR IGNORE INTO knowledge_sources
               (id,domain,title,publisher,url,document_version,effective_from,effective_until,
                reviewed_by,reviewed_at,status,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (source["id"], source["domain"], source["title"], source["publisher"], source["url"],
             source["document_version"], source["effective_from"], source["effective_until"],
             source["reviewed_by"], source["reviewed_at"], source["status"], SEED_TIME, SEED_TIME))
    for position, chunk in enumerate(SEED_CHUNKS):
        connection.execute(
            """INSERT OR IGNORE INTO knowledge_chunks
               (id,source_id,domain,title,text,keywords,position,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (chunk.id, chunk.source_id, chunk.domain, chunk.title, chunk.text,
             json.dumps(list(chunk.keywords), ensure_ascii=False),
             position, SEED_TIME, SEED_TIME))


def retrieve(connection, domain, text, limit=2, today=None):
    """Return published, currently effective chunks ranked by keyword hits."""
    today = today or datetime.now(timezone.utc).date().isoformat()
    raw_query = text.casefold()
    if domain == "medical":
        text = _expand_medical_text(text)
    elif domain == "legal":
        text = _expand_legal_text(text)
    haystack = text.casefold()
    rows = connection.execute(
        """SELECT c.id,c.source_id,c.domain,c.title,c.text,c.keywords,c.position,
                  s.title AS source_title,s.url,s.document_version,s.status,
                  s.effective_from,s.effective_until,s.reviewed_by
           FROM knowledge_chunks c JOIN knowledge_sources s ON s.id=c.source_id
           WHERE c.domain=? AND s.domain=? AND s.status='published'
             AND (s.effective_from IS NULL OR s.effective_from<=?)
             AND (s.effective_until IS NULL OR s.effective_until>=?)
           ORDER BY c.position,c.id""",
        (domain, domain, today, today)).fetchall()
    ranked = []
    for row in rows:
        try:
            keywords = tuple(json.loads(row["keywords"]))
        except (TypeError, ValueError):
            keywords = ()
        score = sum(
            1 + min(len(word), 8) / 10
            for word in keywords
            if word.casefold() in haystack
        )
        # A short query that is literally in the title is a strong signal,
        # e.g. "健康饮食" or "感染预防". Without this, generic symptom words
        # can outrank the exact topic.
        if len(raw_query) >= 2 and raw_query in row["title"].casefold():
            score += 2
        if score:
            ranked.append((score, row))
    ranked.sort(key=lambda pair: (-pair[0], pair[1]["position"], pair[1]["id"]))
    result = []
    for _, row in ranked[:limit]:
        result.append(KnowledgeChunk(
            row["id"], row["domain"], row["title"], row["text"], row["url"],
            tuple(json.loads(row["keywords"])), source_id=row["source_id"],
            source_title=row["source_title"], version=row["document_version"],
            status=row["status"], effective_from=row["effective_from"],
            effective_until=row["effective_until"], reviewed_by=row["reviewed_by"]))
    return result


def citation(chunk):
    return {
        "id": chunk.id, "domain": chunk.domain, "title": chunk.title, "text": chunk.text,
        "url": chunk.url, "source_id": chunk.source_id, "source_title": chunk.source_title,
        "version": chunk.version, "status": chunk.status,
        "effective_from": chunk.effective_from, "effective_until": chunk.effective_until,
        "reviewed_by": chunk.reviewed_by,
    }
