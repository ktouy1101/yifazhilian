"""Document-completeness checklist for patient-uploaded medical records.

This checks whether common document types were uploaded and reviewed. It is not
a clinical-quality or hospital-compliance judgment.
"""
import json

RECORD_TYPES = (
    "检验单", "检查报告", "影像报告", "门诊病历", "入院记录", "出院记录",
    "病案首页", "手术记录", "麻醉记录", "病理报告", "医嘱单", "处方",
    "诊断证明", "费用清单", "其他",
)

SCENARIOS = {
    "outpatient": {
        "label": "门诊病历",
        "hint": "门诊就诊后，建议保留门诊病历、检查结果和处方/医嘱。",
        "items": [
            {"key": "outpatient", "label": "门诊病历", "types": ("门诊病历",), "required": True},
            {"key": "tests", "label": "检验/检查报告", "types": ("检验单", "检查报告", "影像报告"), "required": True},
            {"key": "orders", "label": "处方/医嘱", "types": ("处方", "医嘱单"), "required": False},
            {"key": "diagnosis", "label": "诊断证明", "types": ("诊断证明",), "required": False},
        ],
    },
    "inpatient": {
        "label": "住院病历",
        "hint": "住院病案通常包含首页、入院记录、出院记录、检查检验和医嘱。",
        "items": [
            {"key": "front", "label": "病案首页", "types": ("病案首页",), "required": True},
            {"key": "admission", "label": "入院记录", "types": ("入院记录",), "required": True},
            {"key": "discharge", "label": "出院记录/小结", "types": ("出院记录",), "required": True},
            {"key": "tests", "label": "检验/检查报告", "types": ("检验单", "检查报告", "影像报告"), "required": True},
            {"key": "orders", "label": "医嘱单", "types": ("医嘱单",), "required": True},
            {"key": "surgery", "label": "手术记录", "types": ("手术记录", "麻醉记录"), "required": False},
            {"key": "pathology", "label": "病理报告", "types": ("病理报告",), "required": False},
        ],
    },
    "followup": {
        "label": "复诊资料",
        "hint": "复诊时优先带出院记录、最近复查结果和当前用药。",
        "items": [
            {"key": "discharge", "label": "出院记录/门诊病历", "types": ("出院记录", "门诊病历"), "required": True},
            {"key": "review", "label": "最近复查报告", "types": ("检验单", "检查报告", "影像报告"), "required": True},
            {"key": "orders", "label": "处方/用药清单", "types": ("处方", "医嘱单"), "required": False},
        ],
    },
}

STATUS_LABEL = {"complete": "已归档", "pending": "待核对", "missing": "未上传"}


def build_checklist(rows, scenario="outpatient"):
    scenario = scenario if scenario in SCENARIOS else "outpatient"
    definition = SCENARIOS[scenario]
    documents = []
    for row in rows:
        try:
            draft = json.loads(row["draft"])
        except (TypeError, ValueError, KeyError):
            continue
        documents.append({"type": draft.get("record_type", "其他"), "status": row["status"]})

    items = []
    for spec in definition["items"]:
        matched = [doc for doc in documents if doc["type"] in spec["types"]]
        archived = [doc for doc in matched if doc["status"] == "archived"]
        status = "complete" if archived else ("pending" if matched else "missing")
        items.append({**spec, "types": list(spec["types"]), "status": status,
                      "statusLabel": STATUS_LABEL[status], "count": len(archived),
                      "matched": len(matched)})

    required = [item for item in items if item["required"]]
    return {
        "scenario": scenario,
        "scenario_label": definition["label"],
        "hint": definition["hint"],
        "items": items,
        "total_required": len(required),
        "complete_count": sum(1 for item in required if item["status"] == "complete"),
        "pending_count": sum(1 for item in required if item["status"] == "pending"),
        "missing_count": sum(1 for item in required if item["status"] == "missing"),
        "complete": all(item["status"] == "complete" for item in required),
        "missing": [item["label"] for item in required if item["status"] == "missing"],
        "pending": [item["label"] for item in required if item["status"] == "pending"],
        "disclaimer": "这是资料类型完整度，不是病历质量、诊疗完整性或医院责任判断。",
    }
