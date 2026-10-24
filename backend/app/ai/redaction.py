"""Best-effort pattern replacement, NOT reliable anonymization of free text."""
import re


def redact_outbound(text: str) -> str:
    text = re.sub(r"(?<![A-Za-z0-9_])(?:sk|pk|api)[-_][A-Za-z0-9_-]{12,}(?![A-Za-z0-9_])", "[API_KEY已隐藏]", text, flags=re.IGNORECASE)
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*", "Bearer [TOKEN已隐藏]", text)
    text = re.sub(r"(?i)(?:api[_ -]?key|密钥)\s*[:=：]\s*[^\s,，;；]+", "API_KEY=[已隐藏]", text)
    text = re.sub(r"(?<!\d)\d{17}[\dXx](?!\d)", "[身份证号已隐藏]", text)
    text = re.sub(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)", "[手机号已隐藏]", text)
    text = re.sub(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+", "[邮箱已隐藏]", text)
    return text
