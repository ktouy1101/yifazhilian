from app.services.answer_style import compose_answer, normalize_model_answer


def test_compose_answer_uses_lead_bullets_and_optional_alert():
    answer = compose_answer(
        "结论：阿莫西林是抗生素。",
        ["对病毒无效", "属于处方药"],
        alert="出现皮疹时联系医护")

    assert answer == (
        "阿莫西林是抗生素。\n"
        "- 对病毒无效\n"
        "- 属于处方药\n"
        "注意：出现皮疹时联系医护"
    )


def test_compose_answer_drops_empty_points_and_collapses_whitespace():
    answer = compose_answer("  结论：  先观察。 ", ["", "  多喝水  "])

    assert answer == "先观察。\n- 多喝水"


def test_normalize_model_answer_removes_duplicate_doctor_question_list():
    text = (
        "结论：先观察。\n"
        "- 多喝水\n"
        "你可以这样问医生：\n"
        "1. 什么时候需要复查？\n"
        "2. 出现什么要叫医护？\n"
        "就医提示：胸痛时立即联系医护"
    )

    normalized = normalize_model_answer(text)

    assert "可以这样问医生" not in normalized
    assert "什么时候需要复查" not in normalized
    assert "结论：先观察。" in normalized
    assert "就医提示：胸痛时立即联系医护" in normalized


def test_normalize_model_answer_keeps_normal_advice_sentences():
    text = "出现胸痛要马上问医生。\n- 不要自行停药。"

    normalized = normalize_model_answer(text)

    assert normalized == text


def test_normalize_model_answer_strips_markdown_noise():
    text = "### 结论：先观察\n**多喝水**，不要自行停药。"

    normalized = normalize_model_answer(text)

    assert normalized == "结论：先观察\n多喝水，不要自行停药。"


def test_citation_numbers_are_removed():
    """前端不显示来源列表，正文里的 [1] 只会像排版错误。"""
    text = "住院押金一般能退[1]。参照[2][3]的规定，出院时结算。"

    assert normalize_model_answer(text) == "住院押金一般能退。参照的规定，出院时结算。"
