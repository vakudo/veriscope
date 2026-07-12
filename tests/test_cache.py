import json

from app.cache.store import MemoryEvidenceCache, PgResultCache
from app.pipeline.runner import FactCheckPipeline
from app.pipeline.search import SearchResult
from app.schemas import AnalysisResult, EvidenceItem, EvidenceSource, Stance
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
    queries_after_first = len(search.queries)
    second = await pipeline.analyze(text=text)
    assert queries_after_first > 0
    assert len(search.queries) == queries_after_first
    assert first.claims[0].label == second.claims[0].label


class FakeConnection:
    def __init__(self, row=None):
        self.row = row
        self.executions = []
        self.fetches = []

    async def execute(self, query, *args):
        self.executions.append((query, args))

    async def fetchrow(self, query, *args):
        self.fetches.append((query, args))
        return self.row


class FakeAcquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, *args):
        return None


class FakePool:
    def __init__(self, connection):
        self.connection = connection

    def acquire(self):
        return FakeAcquire(self.connection)


def cached_result() -> AnalysisResult:
    return AnalysisResult(claims=[], flags=[], summary="cached")


async def test_postgres_result_cache_initializes_and_enforces_ttl():
    connection = FakeConnection()
    cache = PgResultCache(FakePool(connection), ttl_seconds=90)
    await cache.init()
    await cache.put("result-key", cached_result())
    statements = "\n".join(query for query, _ in connection.executions)
    assert "CREATE TABLE IF NOT EXISTS result_cache" in statements
    assert "DELETE FROM result_cache WHERE expires_at <= now()" in statements
    insert, args = connection.executions[-1]
    assert "ON CONFLICT (result_key)" in insert
    assert args[0] == "result-key"
    assert json.loads(args[1])["summary"] == "cached"
    assert args[2] == 90


async def test_postgres_result_cache_restores_typed_result():
    payload = json.dumps(cached_result().model_dump(mode="json"))
    connection = FakeConnection(row={"payload": payload})
    cache = PgResultCache(FakePool(connection))
    result = await cache.get("result-key")
    assert result == cached_result()
    query, args = connection.fetches[0]
    assert "expires_at > now()" in query
    assert args == ("result-key",)
