import json
from datetime import date

from app.pipeline.search import (
    SearchResult,
    build_queries,
    build_query_plan,
    domain_of,
    gather_evidence,
    parse_publication_date,
    published_after,
)
from tests.conftest import FakeLLM, FakeSearch, RawLLM


async def test_build_queries_cyrillic_adds_refutation_and_translation():
    queries, translated = await build_queries(FakeLLM(), "Компания Альфа купила компанию Бета")
    assert len(queries) == 3
    assert "опровержение" in queries[1]
    assert queries[2] == "Alpha acquired Beta"
    assert translated == "Alpha acquired Beta"


async def test_build_queries_latin_adds_fact_check():
    queries, translated = await build_queries(FakeLLM(), "Alpha corp acquired Beta corp")
    assert len(queries) == 2
    assert "fact check" in queries[1]
    assert translated is None


async def test_build_queries_without_cross_lingual():
    queries, translated = await build_queries(
        FakeLLM(), "Компания Альфа купила компанию Бета", cross_lingual=False
    )
    assert len(queries) == 2
    assert translated is None


async def test_query_plan_combines_fallback_focused_queries_and_context():
    class PlanningLLM(FakeLLM):
        async def chat(self, system: str, user: str, **kwargs) -> str:
            self.chat_calls.append((system, user))
            if "plan web research" in system:
                return json.dumps(
                    {
                        "questions": [
                            "What did the official agency report?",
                            "Was the reported number later corrected?",
                        ],
                        "queries": [
                            "Alpha acquisition official filing 2020",
                            "Alpha acquisition correction denied",
                        ],
                    }
                )
            return await super().chat(system, user, **kwargs)

    llm = PlanningLLM()
    plan = await build_query_plan(
        llm,
        "Alpha acquired Beta in 2020",
        context="Location: GB\nSpeaker: Alpha",
        max_queries=5,
    )

    assert plan.queries[0] == "Alpha acquired Beta in 2020"
    assert "Alpha acquisition official filing 2020" in plan.queries
    assert "Alpha acquisition correction denied" in plan.queries
    assert plan.queries[-1].endswith("fact check false")
    assert len(plan.verification_questions) == 2
    planner_call = next(call for call in llm.chat_calls if "plan web research" in call[0])
    assert "Location: GB" in planner_call[1]


async def test_query_plan_falls_back_when_planner_returns_invalid_json():
    plan = await build_query_plan(RawLLM("not json"), "Alpha acquired Beta", max_queries=5)

    assert plan.queries == ["Alpha acquired Beta", "Alpha acquired Beta fact check false"]
    assert plan.verification_questions == []


async def test_query_plan_can_be_disabled_without_calling_planner():
    llm = FakeLLM()
    plan = await build_query_plan(
        llm,
        "Alpha acquired Beta",
        max_queries=5,
        enabled=False,
    )

    assert plan.queries == ["Alpha acquired Beta", "Alpha acquired Beta fact check false"]
    assert plan.verification_questions == []
    assert not any("plan web research" in system for system, _ in llm.chat_calls)


async def test_gather_evidence_merges_and_dedupes_queries():
    llm = FakeLLM(vectors={"ALPHA": [1.0, 0.0, 0.0]})
    shared = SearchResult(url="https://one.example/1", title="", snippet="ALPHA news")
    search = FakeSearch(
        results={
            "первый": [shared, SearchResult(url="https://two.example/2", title="", snippet="ALPHA copy")],
            "второй": [shared],
        }
    )
    sources = await gather_evidence(
        llm,
        search,
        "ALPHA утверждение",
        max_results=8,
        top_k=4,
        queries=["первый запрос", "второй запрос"],
    )
    assert [source.url for source in sources] == [
        "https://one.example/1",
        "https://two.example/2",
    ]


async def test_alt_claim_text_rescues_cross_lingual_source():
    llm = FakeLLM(vectors={"CLAIMRU": [1.0, 0.0, 0.0], "TRANS": [0.0, 1.0, 0.0], "ENSRC": [0.0, 1.0, 0.0]})
    search = FakeSearch(
        default=[SearchResult(url="https://en.example/1", title="", snippet="ENSRC english article")]
    )
    without_alt = await gather_evidence(
        llm, search, "CLAIMRU утверждение", max_results=8, top_k=4, min_relevance=0.5
    )
    with_alt = await gather_evidence(
        llm,
        search,
        "CLAIMRU утверждение",
        max_results=8,
        top_k=4,
        min_relevance=0.5,
        alt_claim_text="TRANS english claim",
    )
    assert without_alt == []
    assert [source.domain for source in with_alt] == ["en.example"]


async def test_irrelevant_results_filtered_out():
    llm = FakeLLM(vectors={"ALPHA": [1.0, 0.0, 0.0], "BETA": [0.0, 1.0, 0.0]})
    search = FakeSearch(
        default=[
            SearchResult(url="https://one.example/1", title="", snippet="ALPHA по теме"),
            SearchResult(url="https://two.example/2", title="", snippet="BETA совсем не о том"),
        ]
    )
    sources = await gather_evidence(
        llm, search, "ALPHA утверждение", max_results=8, top_k=4, min_relevance=0.5
    )
    assert [source.domain for source in sources] == ["one.example"]


async def test_all_irrelevant_gives_empty_evidence():
    llm = FakeLLM(vectors={"ALPHA": [1.0, 0.0, 0.0], "BETA": [0.0, 1.0, 0.0]})
    search = FakeSearch(
        default=[SearchResult(url="https://two.example/2", title="", snippet="BETA не о том")]
    )
    sources = await gather_evidence(
        llm, search, "ALPHA утверждение", max_results=8, top_k=4, min_relevance=0.5
    )
    assert sources == []


async def test_query_truncated_to_first_words():
    llm = FakeLLM(vectors={"ALPHA": [1.0, 0.0, 0.0]})
    search = FakeSearch(default=[])
    long_claim = "ALPHA " + " ".join(f"слово{i}" for i in range(40))
    await gather_evidence(llm, search, long_claim, max_results=8, top_k=4)
    assert len(search.queries[0].split()) == 16


def test_domain_of_strips_www():
    assert domain_of("https://www.example.com/news/1") == "example.com"
    assert domain_of("https://sub.example.com/x") == "sub.example.com"


def test_publication_date_parses_dataset_iso_and_http_formats():
    assert parse_publication_date("31-10-2020") == date(2020, 10, 31)
    assert parse_publication_date("2020-10-31T12:30:00Z") == date(2020, 10, 31)
    assert parse_publication_date("Sat, 31 Oct 2020 12:30:00 GMT") == date(2020, 10, 31)
    assert parse_publication_date("unknown") is None


def test_publication_on_cutoff_is_allowed_but_future_is_not():
    cutoff = date(2020, 10, 31)
    assert not published_after("2020-10-31", cutoff)
    assert published_after("2020-11-01", cutoff)
    assert not published_after(None, cutoff)


async def test_gather_evidence_excludes_known_future_sources_but_keeps_unknown_dates():
    llm = FakeLLM(vectors={"ALPHA": [1.0, 0.0, 0.0]})
    search = FakeSearch(
        default=[
            SearchResult(
                url="https://past.example/story",
                title="",
                snippet="ALPHA past",
                published_at="2020-10-30",
            ),
            SearchResult(
                url="https://future.example/story",
                title="",
                snippet="ALPHA future",
                published_at="2020-11-01",
            ),
            SearchResult(
                url="https://unknown.example/story",
                title="",
                snippet="ALPHA unknown",
            ),
        ]
    )

    sources = await gather_evidence(
        llm,
        search,
        "ALPHA claim",
        max_results=8,
        top_k=4,
        published_before=date(2020, 10, 31),
    )

    assert {source.domain for source in sources} == {"past.example", "unknown.example"}
