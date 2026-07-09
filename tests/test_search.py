from app.pipeline.search import SearchResult, domain_of, gather_evidence
from tests.conftest import FakeLLM, FakeSearch


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
