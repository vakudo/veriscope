import json
from datetime import date

import pytest

from app.cache.store import MemoryResultCache
from app.i18n import STRINGS
from app.pipeline.extract import Article
from app.pipeline.runner import FactCheckPipeline
from app.pipeline.search import SearchResult
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
    assert verdict.search_queries
    assert all(item.stance == Stance.supports for item in verdict.evidence)
    inherited = [item for item in verdict.evidence if item.rationale == STRINGS["ru"]["inherited"]]
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


async def test_unstable_refutation_downgraded_on_recheck(settings):
    class FlakyLLM(FakeLLM):
        def __init__(self):
            super().__init__(
                claims=["Компания Альфа купила компанию Бета"],
                vectors={"ALPHA": [1.0, 0.0, 0.0], "BETA": [0.0, 1.0, 0.0]},
            )
            self.flaky_answers = [
                json.dumps(
                    {
                        "stance": "refutes",
                        "rationale": "шум",
                        "evidence_quote": "FLAKY",
                    }
                ),
                json.dumps({"stance": "not_enough_info", "rationale": ""}),
            ]

        async def chat(self, system: str, user: str, **kwargs) -> str:
            if "stance" in system and "FLAKY" in user:
                self.chat_calls.append((system, user))
                return self.flaky_answers.pop(0)
            return await super().chat(system, user, **kwargs)

    llm = FlakyLLM()
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
                snippet="BETA FLAKY",
                published_at="2026-03-06",
            ),
        ]
    )
    pipeline = FactCheckPipeline(llm=llm, search=search, cache=None, settings=settings)
    result = await pipeline.analyze(text=TEXT)
    verdict = result.claims[0]
    assert verdict.label == VerdictLabel.supported
    assert verdict.independent_refuting == 0
    downgraded = [item for item in verdict.evidence if item.rationale == STRINGS["ru"]["unstable"]]
    assert len(downgraded) == 1
    assert downgraded[0].stance == Stance.not_enough_info


async def test_deep_evidence_replaces_snippet_with_best_paragraph(settings, monkeypatch):
    settings.deep_evidence = True
    llm = FakeLLM(
        claims=["Компания ALPHA купила компанию Бета"],
        vectors={"ALPHA": [1.0, 0.0, 0.0], "OFFTOPIC": [0.0, 1.0, 0.0]},
    )
    relevant = "ALPHA " + "подробности сделки компании Альфа и Бета " * 3
    offtopic = "OFFTOPIC " + "реклама подписки на наш замечательный журнал " * 3
    article = Article(text=f"{offtopic}\n{relevant}", published_at="2026-03-01")

    async def fake_extract(url, **kwargs):
        return article

    monkeypatch.setattr("app.pipeline.runner.extract_article", fake_extract)
    search = FakeSearch(
        default=[
            SearchResult(
                url="https://one.example/news/1",
                title="",
                snippet="ALPHA STANCE_SUPPORTS короткий сниппет",
            )
        ]
    )
    pipeline = FactCheckPipeline(llm=llm, search=search, cache=None, settings=settings)
    result = await pipeline.analyze(text=TEXT)
    source = result.claims[0].evidence[0].source
    assert source.snippet.startswith("ALPHA подробности")
    assert "OFFTOPIC" not in source.snippet.split(" … ")[0]
    assert source.published_at == "2026-03-01"


async def test_timings_reported(settings):
    llm, search = make_setup()
    pipeline = FactCheckPipeline(llm=llm, search=search, cache=None, settings=settings)
    result = await pipeline.analyze(text=TEXT)
    assert result.timings is not None
    assert set(result.timings) == {"extract_s", "claims_s", "verify_s", "total_s"}


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
    assert stance_calls(llm) == 4
    assert verdict.label == VerdictLabel.conflicting


async def test_historical_verification_drops_future_date_found_during_deep_fetch(
    settings, monkeypatch
):
    settings.deep_evidence = True
    llm = FakeLLM(vectors={"ALPHA": [1.0, 0.0, 0.0]})
    article = Article(
        text="ALPHA evidence paragraph " + "with enough detail to be extracted safely " * 4,
        published_at="2020-11-01",
    )

    async def fake_extract(url, **kwargs):
        return article

    monkeypatch.setattr("app.pipeline.runner.extract_article", fake_extract)
    search = FakeSearch(
        default=[
            SearchResult(
                url="https://future.example/story",
                title="",
                snippet="ALPHA STANCE_SUPPORTS",
            )
        ]
    )
    pipeline = FactCheckPipeline(llm=llm, search=search, cache=None, settings=settings)

    verdict = await pipeline.verify_claim(
        "ALPHA historical claim", lang="en", published_before=date(2020, 10, 31)
    )

    assert verdict.label == VerdictLabel.unverifiable
    assert verdict.evidence == []
    assert stance_calls(llm) == 0


async def test_historical_verification_does_not_read_or_write_evidence_cache(settings):
    class ForbiddenCache:
        async def get(self, claim_text, embedding=None):
            raise AssertionError("historical verification must not read the cache")

        async def put(self, claim_text, embedding, evidence):
            raise AssertionError("historical verification must not write the cache")

    llm, search = make_setup()
    pipeline = FactCheckPipeline(llm=llm, search=search, cache=ForbiddenCache(), settings=settings)

    verdict = await pipeline.verify_claim(
        "ALPHA historical claim", lang="en", published_before=date(2026, 3, 5)
    )

    assert verdict.label == VerdictLabel.supported


async def test_strict_historical_verification_drops_undated_evidence(settings):
    llm = FakeLLM(vectors={"ALPHA": [1.0, 0.0, 0.0]})
    search = FakeSearch(
        default=[
            SearchResult(
                url="https://unknown.example/story",
                title="",
                snippet="ALPHA STANCE_SUPPORTS",
            )
        ]
    )
    pipeline = FactCheckPipeline(llm=llm, search=search, cache=None, settings=settings)

    verdict = await pipeline.verify_claim(
        "ALPHA historical claim",
        lang="en",
        published_before=date(2020, 10, 31),
        require_known_dates=True,
    )

    assert verdict.label == VerdictLabel.unverifiable
    assert verdict.evidence == []


async def test_strict_dates_require_a_cutoff(settings):
    llm, search = make_setup()
    pipeline = FactCheckPipeline(llm=llm, search=search, cache=None, settings=settings)

    with pytest.raises(ValueError, match="needs a publication cutoff"):
        await pipeline.verify_claim("ALPHA claim", require_known_dates=True)
