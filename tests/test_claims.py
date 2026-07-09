import pytest

from app.pipeline.claims import extract_claims
from tests.conftest import RawLLM


@pytest.mark.parametrize(
    "raw",
    [
        '["Первое утверждение", "Второе утверждение"]',
        'Вот утверждения:\n```json\n["Первое утверждение", "Второе утверждение"]\n```',
        '[{"claim": "Первое утверждение"}, {"text": "Второе утверждение"}]',
    ],
)
async def test_extract_claims_parses_variants(raw):
    claims = await extract_claims(RawLLM(raw), "текст новости")
    assert [claim.text for claim in claims] == ["Первое утверждение", "Второе утверждение"]
    assert [claim.id for claim in claims] == [0, 1]


async def test_extract_claims_respects_limit():
    raw = '["a", "b", "c", "d"]'
    claims = await extract_claims(RawLLM(raw), "текст", max_claims=2)
    assert len(claims) == 2


async def test_extract_claims_skips_empty_items():
    raw = '["", "  ", "настоящее утверждение"]'
    claims = await extract_claims(RawLLM(raw), "текст")
    assert [claim.text for claim in claims] == ["настоящее утверждение"]


async def test_extract_claims_handles_garbage():
    claims = await extract_claims(RawLLM("не могу выделить утверждения"), "текст")
    assert claims == []
