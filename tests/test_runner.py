from app.pipeline.runner import FactCheckPipeline
from app.pipeline.search import SearchResult
from app.pipeline.stance import INHERITED_RATIONALE
from app.schemas import Stance, VerdictLabel
from tests.conftest import FakeLLM, FakeSearch


def stance_calls(llm: FakeLLM) -> int:
    return sum(1 for system, _ in llm.chat_calls if "stance" in system)


async def test_reprints_judged_once_and_inherit_stance(settings):
    llm = FakeLLM(
        claims=["Компания Альфа купила компанию Бета"],
        vectors={"ALPHA": [1.0, 0.0, 0.0]},
    )
    search = FakeSearch(
        default=[
            SearchResult(
                url="https://one.example/news/1",
                title="",
                snippet="ALPHA STANCE_SUPPORTS оригинал",
                published_at="2026-03-05",
            ),
            SearchResult(
                url="https://two.example/news/2",
                title="",
                snippet="ALPHA STANCE_SUPPORTS перепечатка",
                published_at="2026-03-06",
            ),
        ]
    )
    pipeline = FactCheckPipeline(llm=llm, search=search, cache=None, settings=settings)
    result = await pipeline.analyze(
        text="5 марта 2026 года компания Альфа объявила о покупке компании Бета, сообщил Иван Петров."
    )
    verdict = result.claims[0]
    assert stance_calls(llm) == 1
    assert verdict.label == VerdictLabel.supported
    assert verdict.independent_supporting == 1
    assert all(item.stance == Stance.supports for item in verdict.evidence)
    inherited = [item for item in verdict.evidence if item.rationale == INHERITED_RATIONALE]
    assert len(inherited) == 1


async def test_independent_clusters_judged_separately(settings):
    llm = FakeLLM(
        claims=["Компания Альфа купила компанию Бета"],
        vectors={"ALPHA": [1.0, 0.0, 0.0], "BETA": [0.0, 1.0, 0.0]},
    )
    search = FakeSearch(
        default=[
            SearchResult(
                url="https://one.example/news/1",
                title="",
                snippet="ALPHA STANCE_SUPPORTS",
                published_at="2026-03-05",
            ),
            SearchResult(
                url="https://two.example/news/2",
                title="",
                snippet="BETA STANCE_REFUTES",
                published_at="2026-03-06",
            ),
        ]
    )
    pipeline = FactCheckPipeline(llm=llm, search=search, cache=None, settings=settings)
    result = await pipeline.analyze(
        text="5 марта 2026 года компания Альфа объявила о покупке компании Бета, сообщил Иван Петров."
    )
    verdict = result.claims[0]
    assert stance_calls(llm) == 2
    assert verdict.label == VerdictLabel.conflicting
