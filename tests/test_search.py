from app.pipeline.search import SearchResult, build_queries, domain_of, gather_evidence
from tests.conftest import FakeLLM, FakeSearch


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
