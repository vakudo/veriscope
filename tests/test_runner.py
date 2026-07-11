from app.cache.store import MemoryResultCache
from app.pipeline.runner import FactCheckPipeline
from app.pipeline.search import SearchResult
from app.pipeline.stance import INHERITED_RATIONALE
from app.schemas import Stance, VerdictLabel
from tests.conftest import FakeLLM, FakeSearch

TEXT = "5 марта 2026 года компания Альфа объявила о покупке компании Бета, сообщил Иван Петров."


def make_setup():
    llm = FakeLLM(
        claims=["Компания Альфа купила компанию Бета"],
        vectors={"ALPHA": [1.0, 0.0, 0.0]},
    )
    search = FakeSearch(
        default=[
            SearchResult(
                url="https://one.example/news/1",
                title="",
                snippet="ALPHA STANCE_SUPPORTS",
                published_at="2026-03-05",
            )
        ]
    )
    return llm, search


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


async def test_analyzed_article_domain_excluded_from_evidence(settings):
    llm = FakeLLM(
        claims=["Компания Альфа купила компанию Бета"],
        vectors={"ALPHA": [1.0, 0.0, 0.0]},
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
                url="https://www.self.example/original-article",
                title="",
                snippet="ALPHA STANCE_SUPPORTS",
                published_at="2026-03-04",
            ),
        ]
    )
    pipeline = FactCheckPipeline(llm=llm, search=search, cache=None, settings=settings)
    result = await pipeline.analyze(
        text="5 марта 2026 года компания Альфа объявила о покупке компании Бета, сообщил Иван Петров.",
        url="https://self.example/original-article",
    )
    domains = {item.source.domain for item in result.claims[0].evidence}
    assert domains == {"one.example"}


async def test_result_cache_returns_same_analysis_without_recompute(settings):
    llm, search = make_setup()
    pipeline = FactCheckPipeline(
        llm=llm, search=search, cache=None, settings=settings, result_cache=MemoryResultCache()
    )
    first = await pipeline.analyze(text=TEXT)
    calls_after_first = len(llm.chat_calls)
    second = await pipeline.analyze(text=TEXT)
    assert len(llm.chat_calls) == calls_after_first
    assert second.claims[0].label == first.claims[0].label


async def test_force_bypasses_result_cache(settings):
    llm, search = make_setup()
    pipeline = FactCheckPipeline(
        llm=llm, search=search, cache=None, settings=settings, result_cache=MemoryResultCache()
    )
    await pipeline.analyze(text=TEXT)
    calls_after_first = len(llm.chat_calls)
    await pipeline.analyze(text=TEXT, force=True)
    assert len(llm.chat_calls) > calls_after_first


async def test_progress_events_emitted(settings):
    llm, search = make_setup()
    pipeline = FactCheckPipeline(
        llm=llm, search=search, cache=None, settings=settings, result_cache=MemoryResultCache()
    )
    events = []

    async def progress(event):
        events.append(event)

    await pipeline.analyze(text=TEXT, progress=progress)
    stages = [event["stage"] for event in events]
    assert stages == ["claims", "claims_done", "claim_done"]
    assert events[1]["total"] == 1
    assert events[2]["done"] == 1
    events.clear()
    await pipeline.analyze(text=TEXT, progress=progress)
    assert [event["stage"] for event in events] == ["cached"]


async def test_calibration_attached_to_verdicts(settings):
    llm, search = make_setup()
    pipeline = FactCheckPipeline(
        llm=llm,
        search=search,
        cache=None,
        settings=settings,
        calibration={"supported": 0.8},
    )
    result = await pipeline.analyze(text=TEXT)
    assert result.claims[0].label == VerdictLabel.supported
    assert result.claims[0].historical_accuracy == 0.8


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
