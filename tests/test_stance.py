import pytest

from app.pipeline.stance import detect_stance
from app.schemas import EvidenceSource, Stance
from tests.conftest import RawLLM

SOURCE = EvidenceSource(
    url="https://a.example/1",
    domain="a.example",
    snippet="The report explicitly says the claim is false.",
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"stance": "supports", "rationale": "да"}', Stance.supports),
        (
            '{"stance": "refutes", "rationale": "явно опровергает", '
            '"evidence_quote": "claim is false"}',
            Stance.refutes,
        ),
        ('{"stance": "refutes", "rationale": "нет"}', Stance.not_enough_info),
        ('{"stance": "not_enough_info", "rationale": ""}', Stance.not_enough_info),
        ('```json\n{"stance": "SUPPORTS", "rationale": "да"}\n```', Stance.supports),
        ("непонятный ответ без json", Stance.not_enough_info),
        ('{"stance": "maybe"}', Stance.not_enough_info),
    ],
)
async def test_detect_stance_parsing(raw, expected):
    item = await detect_stance(RawLLM(raw), "утверждение", SOURCE)
    assert item.stance == expected
    assert item.source is SOURCE


@pytest.mark.parametrize(
    "raw",
    [
        (
            '{"stance": "refutes", "rationale": "The source does not mention the event", '
            '"evidence_quote": "the claim is false"}'
        ),
        (
            '{"stance": "refutes", "rationale": "The source contradicts it", '
            '"evidence_quote": "invented quote"}'
        ),
    ],
)
async def test_refutation_requires_explicit_quote_and_not_merely_absence(raw):
    item = await detect_stance(RawLLM(raw), "claim", SOURCE)

    assert item.stance == Stance.not_enough_info
    assert item.evidence_quote == ""


async def test_grounded_refutation_preserves_exact_quote():
    raw = (
        '{"stance": "refutes", "rationale": "The report explicitly contradicts the claim", '
        '"evidence_quote": "the claim is false"}'
    )

    item = await detect_stance(RawLLM(raw), "claim", SOURCE)

    assert item.stance == Stance.refutes
    assert item.evidence_quote == "the claim is false"


async def test_detect_stance_survives_llm_error():
    class BrokenLLM:
        async def chat(self, system, user, **kwargs):
            raise RuntimeError("llm down")

    item = await detect_stance(BrokenLLM(), "утверждение", SOURCE)
    assert item.stance == Stance.not_enough_info
