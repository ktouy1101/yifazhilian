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


class WechatLoginInput(StrictModel):
    code: str = Field(min_length=1, max_length=128)


class SendCodeInput(StrictModel):
    phone: str = Field(pattern=r"^1[3-9]\d{9}$")


class PhoneLoginInput(StrictModel):
    phone: str = Field(pattern=r"^1[3-9]\d{9}$")
    code: str = Field(pattern=r"^\d{6}$")


class PasswordLoginInput(StrictModel):
    phone: str = Field(pattern=r"^1[3-9]\d{9}$")
    password: str = Field(min_length=6, max_length=64)


class SetPasswordInput(StrictModel):
    password: str = Field(min_length=6, max_length=64)


class ConsentInput(StrictModel):
    scope: Scope
    granted: Literal[True] = True
    recipient: str | None = Field(default=None, max_length=300)
    policy_version: str | None = Field(default=None, max_length=100)


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


class ProfileUpdate(StrictModel):
    nickname: str | None = Field(default=None, max_length=50)
    age: int | None = Field(default=None, ge=0, le=150)
    gender: Literal["男", "女", "未填"] | None = None
    bed_location: str | None = Field(default=None, max_length=100)
    allergies: str | None = Field(default=None, max_length=200)
    emergency_name: str | None = Field(default=None, max_length=50)
    emergency_phone: str | None = Field(default=None, max_length=20)
    doctor_phone: str | None = Field(default=None, max_length=20)


class MedicationCreate(StrictModel):
    name: str = Field(min_length=1, max_length=100)
    dose: str | None = Field(default=None, max_length=100)
    scheduled_time: str | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=300)


class RecordCreate(StrictModel):
    title: str = Field(min_length=1, max_length=100)
    summary: str | None = Field(default=None, max_length=2000)
    record_date: str | None = Field(default=None, max_length=20)


# ===== M11 导航采集与审核 =====

NodeKind = Literal["start", "turn", "landmark", "elevator", "stairs", "end"]
ReviewDecision = Literal["approve", "request_changes"]
FeedbackCategory = Literal["closed", "misdirected", "privacy", "other"]


class NavigationNodeInput(StrictModel):
    node_key: str = Field(min_length=1, max_length=64)
    position: int = Field(ge=0, le=99)
    kind: NodeKind
    floor: str | None = Field(default=None, max_length=50)
    direction: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=300)


class SubmissionCreate(StrictModel):
    task_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=100)
    request_id: str = Field(min_length=1, max_length=64)


class SubmissionUpdate(StrictModel):
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=100)
    nodes: list[NavigationNodeInput] = Field(min_length=2, max_length=30)


class SubmissionSubmit(StrictModel):
    revision: int = Field(ge=1)
    privacy_confirmed: Literal[True]


class ReviewDecisionInput(StrictModel):
    revision: int = Field(ge=1)
    decision: ReviewDecision
    note: str | None = Field(default=None, max_length=500)
    walkthrough_confirmed: bool = False


class DisableInput(StrictModel):
    revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=300)


class VolunteerApplyInput(StrictModel):
    hospital_id: str = Field(default="demo-hospital", min_length=1, max_length=64)
    real_name: str = Field(min_length=2, max_length=32)
    training_confirmed: bool


class VolunteerReviewInput(StrictModel):
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=200)


class RoleInput(StrictModel):
    role: Literal["volunteer", "reviewer"]
    action: Literal["grant", "revoke"]


class CredentialReviewInput(StrictModel):
    decision: Literal["approve", "reject"]
    note: str = Field(default="", max_length=200)


class LegalHelpCreate(StrictModel):
    topic: str = Field(min_length=2, max_length=40)
    text: str = Field(min_length=5, max_length=1000)


class LegalHelpMessageInput(StrictModel):
    text: str = Field(min_length=1, max_length=1000)


class SubmissionRevise(StrictModel):
    revision: int = Field(ge=1)
    source_revision: int = Field(ge=1)


class FeedbackInput(StrictModel):
    request_id: str = Field(min_length=1, max_length=64)
    category: FeedbackCategory
    note: str | None = Field(default=None, max_length=500)
