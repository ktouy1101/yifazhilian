from datetime import timedelta

from fastapi import HTTPException

from app.db import utcnow
from app.schemas import VitalInput

UNITS = {"heart_rate": "bpm", "spo2": "%", "systolic_bp": "mmHg", "diastolic_bp": "mmHg"}
INPUT_RANGES = {"heart_rate": (1, 300), "spo2": (1, 100), "systolic_bp": (1, 350), "diastolic_bp": (1, 250)}


def validate_vital(payload: VitalInput):
    if payload.unit != UNITS[payload.kind]:
        raise HTTPException(422, "指标与单位不匹配")
    low, high = INPUT_RANGES[payload.kind]
    if not low <= payload.value <= high:
        raise HTTPException(422, "超出演示数据格式允许范围")
    if payload.measured_at.tzinfo is None or payload.measured_at.utcoffset() is None:
        raise HTTPException(422, "采样时间必须包含时区")
    now = utcnow()
    if payload.measured_at > now + timedelta(minutes=5) or payload.measured_at < now - timedelta(hours=24):
        raise HTTPException(422, "演示仅接收最近24小时、未来偏差不超过5分钟的数据")
    if payload.quality != "good":
        raise HTTPException(422, "低质量数据不参与演示告警，请重测")


def alert_for(payload: VitalInput) -> dict:
    # Deliberately labelled UI-demo thresholds: NOT a validated triage algorithm.
    unusual = ((payload.kind == "heart_rate" and (payload.value < 50 or payload.value > 120))
               or (payload.kind == "spo2" and payload.value < 94)
               or (payload.kind == "systolic_bp" and (payload.value < 90 or payload.value > 180))
               or (payload.kind == "diastolic_bp" and payload.value > 110))
    return {"status": "demo_review" if unusual else "demo_no_flag",
            "clinical": False,
            "message": "仅用于演示页面变化；不能判断健康正常与否，不能替代医护判断。"}
