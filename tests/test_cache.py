from app.cache.store import MemoryEvidenceCache
from app.pipeline.runner import FactCheckPipeline
from app.pipeline.search import SearchResult
from app.schemas import EvidenceItem, EvidenceSource, Stance
from tests.conftest import FakeLLM, FakeSearch


def make_evidence() -> list[EvidenceItem]:
    source = EvidenceSource(url="https://a.example/1", domain="a.example", cluster_id=0)
    return [EvidenceItem(source=source, stance=Stance.supports, rationale="ok")]


async def test_exact_hit():
    cache = MemoryEvidenceCache()
    await cache.put("Компания купила завод", None, make_evidence())
    hit = await cache.get("компания купила завод", None)
    assert hit is not None
    assert hit[0].stance == Stance.supports


async def test_similarity_hit():
    cache = MemoryEvidenceCache(similarity_threshold=0.95)
    await cache.put("claim one", [1.0, 0.0, 0.0], make_evidence())
    hit = await cache.get("slightly different claim", [0.999, 0.01, 0.0])
    assert hit is not None


async def test_miss():
    cache = MemoryEvidenceCache(similarity_threshold=0.95)
    await cache.put("claim one", [1.0, 0.0, 0.0], make_evidence())
    assert await cache.get("unrelated claim", [0.0, 1.0, 0.0]) is None


async def test_cached_copies_are_isolated():
    cache = MemoryEvidenceCache()
    await cache.put("claim", None, make_evidence())
    first = await cache.get("claim", None)
    first[0].source.cluster_id = 99
    second = await cache.get("claim", None)
    assert second[0].source.cluster_id == 0


async def test_pipeline_skips_search_on_cache_hit(settings):
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
    pipeline = FactCheckPipeline(llm=llm, search=search, cache=MemoryEvidenceCache(), settings=settings)
    text = "5 марта 2026 года компания Альфа объявила о покупке компании Бета, сообщил Иван Петров."
    first = await pipeline.analyze(text=text)
    second = await pipeline.analyze(text=text)
    assert len(search.queries) == 1
    assert first.claims[0].label == second.claims[0].label
