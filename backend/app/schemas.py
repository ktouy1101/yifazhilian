from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Scope = Literal["ai_medical", "ai_legal", "vitals", "records_read"]
Domain = Literal["medical", "legal"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DemoLogin(StrictModel):
    role: Literal["patient", "volunteer"] = "patient"
    demo_alias: str | None = None


class ConsentInput(StrictModel):
    scope: Scope
    granted: Literal[True] = True


class ConversationInput(StrictModel):
    domain: Domain


class MessageInput(StrictModel):
    text: str = Field(min_length=1, max_length=1000)


class VitalInput(StrictModel):
    sample_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    source: Literal["demo_device"]
    kind: Literal["heart_rate", "spo2", "systolic_bp", "diastolic_bp"]
    value: float = Field(allow_inf_nan=False)
    unit: Literal["bpm", "%", "mmHg"]
    measured_at: datetime
    quality: Literal["good", "poor"] = "good"


class EmergencyInput(StrictModel):
    idempotency_key: str = Field(pattern=r"^[A-Za-z0-9_-]{8,64}$")
