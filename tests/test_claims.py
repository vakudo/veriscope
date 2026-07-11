import json

import pytest

from app.pipeline.claims import extract_claims, is_checkworthy, split_text_chunks
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
    assert not is_checkworthy("The report discusses market background.")
    assert not is_checkworthy("Статья описывает общую историю рынка.")


def test_split_text_chunks_samples_the_end_of_a_long_article():
    text = "START_MARKER. " + ("Middle paragraph contains background information. " * 80) + "END_MARKER."

    chunks = split_text_chunks(text, chunk_chars=300, overlap=30, max_chunks=4)

    assert len(chunks) == 4
    assert "START_MARKER" in chunks[0]
    assert "END_MARKER" in chunks[-1]


async def test_extract_claims_covers_beginning_and_end_round_robin():
    class ChunkAwareLLM:
        def __init__(self):
            self.calls = []

        async def chat(self, system, user, **kwargs):
            self.calls.append(user)
            if "START_MARKER" in user:
                return json.dumps(["Alpha opened its first office in London in 2020."])
            if "END_MARKER" in user:
                return json.dumps(["Beta closed its final factory in Berlin in 2024."])
            return "[]"

    llm = ChunkAwareLLM()
    text = "START_MARKER. " + ("Background details fill the article body. " * 80) + "END_MARKER."

    claims = await extract_claims(
        llm,
        text,
        max_claims=2,
        chunk_chars=300,
        chunk_overlap=30,
        max_chunks=4,
    )

    assert [claim.text for claim in claims] == [
        "Alpha opened its first office in London in 2020.",
        "Beta closed its final factory in Berlin in 2024.",
    ]
    assert len(llm.calls) == 4


async def test_extract_claims_deduplicates_overlap_results():
    repeated = "Alpha acquired Beta for ten million dollars in 2020."

    class RepeatingLLM:
        async def chat(self, system, user, **kwargs):
            return json.dumps([repeated])

    claims = await extract_claims(
        RepeatingLLM(),
        "A long report. " * 200,
        max_claims=6,
        chunk_chars=300,
        chunk_overlap=50,
        max_chunks=4,
    )

    assert [claim.text for claim in claims] == [repeated]


def test_split_text_chunks_rejects_invalid_settings():
    with pytest.raises(ValueError, match="invalid claim chunk settings"):
        split_text_chunks("article text", chunk_chars=200, overlap=200)
