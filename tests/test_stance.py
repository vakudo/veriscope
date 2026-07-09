import pytest

from app.pipeline.stance import detect_stance
from app.schemas import EvidenceSource, Stance
from tests.conftest import RawLLM

SOURCE = EvidenceSource(url="https://a.example/1", domain="a.example", snippet="отрывок")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"stance": "supports", "rationale": "да"}', Stance.supports),
        ('{"stance": "refutes", "rationale": "нет"}', Stance.refutes),
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


async def test_detect_stance_survives_llm_error():
    class BrokenLLM:
        async def chat(self, system, user, **kwargs):
            raise RuntimeError("llm down")

    item = await detect_stance(BrokenLLM(), "утверждение", SOURCE)
    assert item.stance == Stance.not_enough_info
