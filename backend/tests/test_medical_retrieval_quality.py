"""Golden queries for the expanded medical corpus.

This is a coverage check, not a clinical benchmark: each query must put the
expected reviewed topic in the top-3 local keyword results. It catches the
regressions that matter most for a demo corpus: a symptom stealing a lab
question, a generic medication page hiding the specific drug, or a topic
disappearing after a seed edit.
"""
from pathlib import Path
import sqlite3

from app.services.knowledge import retrieve, seed_knowledge

GOLDEN = [
    ("C反应蛋白偏高说明什么", "med-301"),
    ("降钙素原高是不是感染", "med-301"),
    ("肌钙蛋白升高要紧吗", "med-303"),
    ("甲功TSH高说明什么", "med-304"),
    ("肿瘤标志物偏高怎么办", "med-305"),
    ("血脂和胆固醇怎么看", "med-306"),
    ("大便隐血阳性", "med-307"),
    ("维生素B12和叶酸", "med-308"),
    ("糖化血红蛋白高", "med-309"),
    ("尿酸高会痛风吗", "med-310"),
    ("发烧了怎么记录", "med-401"),
    ("咳嗽有痰", "med-402"),
    ("呼吸困难怎么办", "med-403"),
    ("胸痛要做什么", "med-404"),
    ("肚子痛怎么描述", "med-405"),
    ("恶心呕吐", "med-406"),
    ("拉肚子", "med-407"),
    ("便秘", "med-408"),
    ("头晕", "med-409"),
    ("突然头痛", "med-410"),
    ("水肿", "med-411"),
    ("皮疹", "med-412"),
    ("皮肤瘙痒", "med-412"),
    ("失眠", "med-414"),
    ("心悸", "med-415"),
    ("手脚麻木", "med-416"),
    ("高血压住院", "med-501"),
    ("糖尿病住院", "med-502"),
    ("冠心病支架", "med-503"),
    ("房颤", "med-515"),
    ("心衰", "med-516"),
    ("肺炎", "med-506"),
    ("尿路感染", "med-507"),
    ("胃炎", "med-508"),
    ("胆囊炎", "med-517"),
    ("胰腺炎", "med-518"),
    ("贫血", "med-511"),
    ("甲减", "med-512"),
    ("阑尾炎", "med-519"),
    ("脑卒中", "med-504"),
    ("降压药", "med-601"),
    ("低血糖", "med-602"),
    ("他汀", "med-603"),
    ("激素药", "med-604"),
    ("华法林", "med-205"),
    ("抗生素", "med-203"),
    ("雾化", "med-607"),
    ("止痛药", "med-204"),
    ("泻药", "med-609"),
    ("抑酸药", "med-605"),
    ("补钾", "med-611"),
    ("药物相互作用", "med-612"),
    ("抽血空腹", "med-701"),
    ("增强CT", "med-702"),
    ("胃管", "med-704"),
    ("导尿管", "med-703"),
    ("伤口换药", "med-706"),
    ("造口", "med-707"),
    ("胃镜", "med-708"),
    ("支气管镜", "med-709"),
    ("腰穿", "med-710"),
    ("超声", "med-201"),
    ("磁共振", "med-712"),
    ("跌倒", "med-801"),
    ("压疮", "med-802"),
    ("静脉血栓", "med-803"),
    ("住院营养", "med-804"),
    ("输液", "med-202"),
    ("住院睡眠", "med-806"),
    ("感染预防", "med-808"),
    ("约束", "med-811"),
    ("临终护理", "med-1008"),
    ("术后活动", "med-812"),
    ("出院带药", "med-901"),
    ("出院复诊", "med-902"),
    ("出院伤口", "med-903"),
    ("出院活动", "med-904"),
    ("出院饮食", "med-905"),
    ("出院后什么情况要回医院", "med-906"),
    ("家庭氧疗", "med-907"),
    ("照护者交接", "med-908"),
    ("老年跌倒", "med-1001"),
    ("孕产用药", "med-1002"),
    ("哺乳期用药", "med-1003"),
    ("肾功能不全止痛", "med-1004"),
    ("肝功能不全", "med-1005"),
    ("药物过敏", "med-1006"),
    ("焦虑抑郁", "med-1007"),
    ("安宁疗护", "med-1008"),
    ("戒烟", "med-1101"),
    ("饮酒", "med-1102"),
    ("健康饮食", "med-1103"),
    ("运动", "med-1104"),
    ("睡眠压力", "med-1105"),
    ("疫苗", "med-1106"),
    ("筛查", "med-1107"),
    ("家庭安全", "med-1108"),
]


def test_golden_queries_hit_expected_topic_in_top_three(tmp_path):
    schema = (Path(__file__).parents[1] / "app/schema.sql").read_text(encoding="utf-8")
    connection = sqlite3.connect(tmp_path / "retrieval.sqlite3")
    connection.row_factory = sqlite3.Row
    try:
        connection.executescript(schema)
        seed_knowledge(connection)
        failures = []
        for query, expected in GOLDEN:
            chunks = retrieve(connection, "medical", query, limit=3, today="2026-10-21")
            got = [chunk.id for chunk in chunks]
            if expected not in got:
                failures.append(f"{query!r}: expected {expected}, got {got}")
            if any(chunk.domain != "medical" for chunk in chunks):
                failures.append(f"{query!r}: non-medical result {got}")
        assert not failures, "\n".join(failures)
    finally:
        connection.close()
