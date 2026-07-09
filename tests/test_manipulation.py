from app.pipeline.manipulation import detect_manipulation


def kinds(flags):
    return {flag.kind for flag in flags}


def test_emotional_language_flagged():
    text = "Это настоящий шок и сенсация, кошмар для всей отрасли. 5 марта Иван Петров подтвердил данные."
    assert "emotional_language" in kinds(detect_manipulation(None, text))


def test_anonymous_sources_flagged():
    text = "По словам источников, знакомых с ситуацией, сделка сорвалась. 5 марта Иван Петров ушёл."
    assert "anonymous_sources" in kinds(detect_manipulation(None, text))


def test_clickbait_title_flagged():
    flags = detect_manipulation("Вы не поверите, что произошло!!!", "5 марта Иван Петров провёл встречу.")
    assert "clickbait_title" in kinds(flags)


def test_missing_attribution_flagged():
    text = "где-то что-то произошло и все обсуждают последствия без подробностей"
    assert "missing_attribution" in kinds(detect_manipulation(None, text))


def test_neutral_text_with_names_and_dates_is_clean():
    text = "5 марта 2026 года Иван Петров представил отчёт компании о выручке за квартал."
    assert detect_manipulation("Компания представила отчёт", text) == []
