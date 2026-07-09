from app.pipeline.independence import mark_independence
from app.schemas import EvidenceSource, SourceType
from tests.conftest import FakeLLM


def make_source(url: str, domain: str, snippet: str, published_at: str | None = None) -> EvidenceSource:
    return EvidenceSource(url=url, domain=domain, title="", snippet=snippet, published_at=published_at)


async def test_near_duplicates_share_cluster():
    llm = FakeLLM(vectors={"ALPHA": [1.0, 0.0, 0.0], "BETA": [0.0, 1.0, 0.0]})
    sources = [
        make_source("https://a.example/news/1", "a.example", "ALPHA press release", "2026-07-01"),
        make_source("https://b.example/news/2", "b.example", "ALPHA press release copy", "2026-07-02"),
        make_source("https://c.example/news/3", "c.example", "BETA independent report", "2026-07-01"),
    ]
    marked = await mark_independence(llm, sources, threshold=0.9)
    assert marked[0].cluster_id == marked[1].cluster_id
    assert marked[2].cluster_id != marked[0].cluster_id
    assert marked[0].source_type == SourceType.possible_primary
    assert marked[1].source_type == SourceType.reprint
    assert marked[2].source_type == SourceType.unknown


async def test_same_domain_always_clusters():
    llm = FakeLLM(vectors={"ALPHA": [1.0, 0.0, 0.0], "BETA": [0.0, 1.0, 0.0]})
    sources = [
        make_source("https://a.example/news/1", "a.example", "ALPHA text"),
        make_source("https://a.example/news/2", "a.example", "BETA text"),
    ]
    marked = await mark_independence(llm, sources, threshold=0.9)
    assert marked[0].cluster_id == marked[1].cluster_id


async def test_opinion_url_marked():
    llm = FakeLLM(vectors={"ALPHA": [1.0, 0.0, 0.0]})
    sources = [
        make_source("https://a.example/opinion/take", "a.example", "ALPHA take"),
    ]
    marked = await mark_independence(llm, sources, threshold=0.9)
    assert marked[0].source_type == SourceType.opinion


async def test_empty_sources():
    llm = FakeLLM()
    assert await mark_independence(llm, [], threshold=0.9) == []
