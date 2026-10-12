"""This build deliberately cannot start in production mode."""
import os

APP_MODE = os.getenv("YIFAZHILIAN_MODE", "demo")
if APP_MODE != "demo":
    raise RuntimeError("This build only supports demo mode and synthetic data.")

API_PREFIX = "/api/v1"
TOKEN_TTL_SECONDS = 3600
CONSENT_TTL_SECONDS = 3600
DISCLAIMER = "仅本地合成数据演示；非真实诊疗或法律意见；紧急情况请直接联系病区医护。"
