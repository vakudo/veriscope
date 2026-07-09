from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.pipeline.runner import FactCheckPipeline
from app.pipeline.search import SearchResult
from tests.conftest import FakeLLM, FakeSearch

TEXT = (
    "5 марта 2026 года компания Альфа объявила о покупке компании Бета. "
    "Сделку подтвердил Иван Петров."
)


def build_app(settings):
    llm = FakeLLM(
        claims=["Компания Альфа купила компанию Бета", "Акции Альфы выросли"],
        vectors={"ALPHA": [1.0, 0.0, 0.0], "BETA": [0.0, 1.0, 0.0]},
    )
    search = FakeSearch(
        results={
            "купила": [
                SearchResult(
                    url="https://one.example/news/1",
                    title="Альфа купила Бету",
                    snippet="ALPHA STANCE_SUPPORTS",
                    published_at="2026-03-05",
                ),
                SearchResult(
                    url="https://two.example/news/2",
                    title="Сделка Альфы",
                    snippet="BETA STANCE_SUPPORTS",
                    published_at="2026-03-06",
                ),
            ]
        }
    )
    pipeline = FactCheckPipeline(llm=llm, search=search, cache=None, settings=settings)
    return create_app(settings=settings, pipeline=pipeline)


def client_for(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_health(settings):
    async with client_for(build_app(settings)) as client:
        response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_analyze_text_end_to_end(settings):
    async with client_for(build_app(settings)) as client:
        response = await client.post(
            "/api/analyze", json={"text": TEXT, "title": "Альфа покупает Бету"}
        )
    assert response.status_code == 200
    body = response.json()
    assert body["input_title"] == "Альфа покупает Бету"
    assert body["flags"] == []
    assert len(body["claims"]) == 2
    first, second = body["claims"]
    assert first["label"] == "supported"
    assert first["confidence"] == "high"
    assert first["independent_supporting"] == 2
    assert {item["source"]["domain"] for item in first["evidence"]} == {
        "one.example",
        "two.example",
    }
    assert second["label"] == "unverifiable"
    assert "Проверено утверждений: 2" in body["summary"]


async def test_analyze_requires_text_or_url(settings):
    async with client_for(build_app(settings)) as client:
        response = await client.post("/api/analyze", json={})
    assert response.status_code == 422


async def test_analyze_rejects_blank_text(settings):
    async with client_for(build_app(settings)) as client:
        response = await client.post("/api/analyze", json={"text": "   "})
    assert response.status_code == 422
