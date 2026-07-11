import pytest

from app.pipeline.claims import extract_claims, is_checkworthy
from tests.conftest import RawLLM

FIRST = "Компания Альфа купила компанию Бета"
SECOND = "Сделка была закрыта пятого марта"


@pytest.mark.parametrize(
    "raw",
    [
        f'["{FIRST}", "{SECOND}"]',
        f'Вот утверждения:\n```json\n["{FIRST}", "{SECOND}"]\n```',
        f'[{{"claim": "{FIRST}"}}, {{"text": "{SECOND}"}}]',
    ],
)
async def test_extract_claims_parses_variants(raw):
    claims = await extract_claims(RawLLM(raw), "текст новости")
    assert [claim.text for claim in claims] == [FIRST, SECOND]
    assert [claim.id for claim in claims] == [0, 1]


async def test_extract_claims_respects_limit():
    raw = (
        '["Компания Альфа купила компанию Бета", "Сделка была закрыта пятого марта", '
        '"Акции компании выросли на десять процентов", "Регулятор одобрил сделку без условий"]'
    )
    claims = await extract_claims(RawLLM(raw), "текст", max_claims=2)
    assert len(claims) == 2


async def test_extract_claims_skips_empty_items():
    raw = f'["", "  ", "{FIRST}"]'
    claims = await extract_claims(RawLLM(raw), "текст")
    assert [claim.text for claim in claims] == [FIRST]


async def test_extract_claims_handles_garbage():
    claims = await extract_claims(RawLLM("не могу выделить утверждения"), "текст")
    assert claims == []


async def test_extract_claims_drops_non_checkworthy():
    raw = (
        f'["{FIRST}", "Это плохо", "Неужели сделка состоится?", '
        f'"По мнению автора, сделка была ошибкой"]'
    )
    claims = await extract_claims(RawLLM(raw), "текст")
    assert [claim.text for claim in claims] == [FIRST]


def test_is_checkworthy_rules():
    assert is_checkworthy("Компания Альфа купила компанию Бета")
    assert not is_checkworthy("Это плохо")
    assert not is_checkworthy("Неужели сделка всё-таки состоится?")
    assert not is_checkworthy("По мнению автора, сделка была ошибкой")
    assert not is_checkworthy("In my opinion the deal was a mistake")
