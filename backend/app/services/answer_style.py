"""Shared shape for short, natural answers.

Every answer the chat page renders follows one small contract:

    一句话回答是什么、为什么或怎么办
    - 一条要点
    - 另一条要点
    注意：只有存在需要及时处理的情况时才出现

The first sentence is rendered as the lead by the client. ``compose_answer``
builds that shape for the deterministic local branches.
``normalize_model_answer`` cleans model output so it does not repeat the
doctor-question list the client already renders as its own block.
"""

import re

_LEADING_CONCLUSION = re.compile(r"^结论[:：]\s*")
_MARKDOWN = re.compile(r"\*\*(.+?)\*\*|__(.+?)__|`([^`]+)`")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_ASK_DOCTOR_HEADER = re.compile(
    r"^你?可以(?:这样)?问(?:医生|药师|医护|主管医生|专业人员)"
    r"(?:的?问题)?\s*[:：]?\s*$"
)
_ASK_DOCTOR_INLINE = re.compile(
    r"^你?可以(?:这样)?问(?:医生|药师|医护|主管医生|专业人员)"
    r"(?:的?问题)?\s*[:：].*\d+\s*[.、]"
)
_NUMBERED_OR_BULLET = re.compile(r"^\s*(?:\d+\s*[.、]|[-*•·])\s*")
# Citation markers such as [1] / ［2］ are stripped: the client shows no source
# list, so a dangling number reads like a typo to the patient.
_CITATION = re.compile(r"[\[［【]\s*\d+\s*[\]］】]")


def _one_line(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()


def compose_answer(conclusion, points=(), alert=""):
    """Return a short, conversational answer with an optional warning line."""
    conclusion = _one_line(_LEADING_CONCLUSION.sub("", _one_line(conclusion)))
    lines = [conclusion] if conclusion else []
    for point in points:
        point = _one_line(point)
        if point:
            lines.append("- " + point)
    alert = _one_line(alert)
    if alert:
        lines.append("注意：" + alert)
    return "\n".join(lines)


def normalize_model_answer(text):
    """Remove markdown noise and a trailing "可以问医生" list from model output.

    The chat page renders one de-duplicated suggestion list, so a second list
    inside the answer is redundant. Legitimate sentences such as
    "出现胸痛要马上问医生。" are left untouched because the pattern is anchored
    to a line that is only an invitation to ask.
    """
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _MARKDOWN.sub(lambda match: next(group for group in match.groups() if group is not None), text)
    text = _HEADING.sub("", text)
    text = _CITATION.sub("", text)

    kept = []
    skipping_list = False
    for raw_line in text.split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()
        if _ASK_DOCTOR_INLINE.match(stripped):
            skipping_list = True
            continue
        if _ASK_DOCTOR_HEADER.match(stripped):
            skipping_list = True
            continue
        if skipping_list:
            if not stripped or _NUMBERED_OR_BULLET.match(stripped):
                continue
            skipping_list = False
        kept.append(line)

    text = "\n".join(kept)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
