import json
import logging
import re

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
        claims=[
            "Компания Альфа купила компанию Бета",
            "Акции компании Альфа выросли на десять процентов",
        ],
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


async def test_ready_without_external_checker(settings):
    async with client_for(build_app(settings)) as client:
        response = await client.get("/api/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


async def test_ready_reports_dependency_failure(settings):
    app = build_app(settings)

    async def unavailable():
        raise RuntimeError("LLM unavailable")

    app.state.readiness = unavailable
    async with client_for(app) as client:
        response = await client.get("/api/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}


async def test_request_id_and_metrics_do_not_log_payload(settings, caplog):
    secret_text = "private article text"
    with caplog.at_level(logging.INFO, logger="uvicorn.veriscope_access"):
        async with client_for(build_app(settings)) as client:
            response = await client.post("/api/analyze", json={"text": secret_text})
            metrics = await client.get("/api/metrics")
    assert response.status_code == 200
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["x-request-id"])
    assert 'path="/api/analyze",status="200"' in metrics.text
    access_records = [
        record.message for record in caplog.records if record.name == "uvicorn.veriscope_access"
    ]
    assert any('"path":"/api/analyze"' in message for message in access_records)
    assert all(secret_text not in message for message in access_records)


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


async def test_analyze_stream_emits_progress_and_result(settings):
    async with client_for(build_app(settings)) as client:
        async with client.stream(
            "POST", "/api/analyze/stream", json={"text": TEXT, "title": "Альфа покупает Бету"}
        ) as response:
            assert response.status_code == 200
            body = ""
            async for chunk in response.aiter_text():
                body += chunk
    events = [json.loads(line[6:]) for line in body.split("\n") if line.startswith("data: ")]
    stages = [event["stage"] for event in events]
    assert "claims_done" in stages
    assert stages[-1] == "done"
    assert len(events[-1]["result"]["claims"]) == 2


async def test_analyze_requires_text_or_url(settings):
    async with client_for(build_app(settings)) as client:
        response = await client.post("/api/analyze", json={})
    assert response.status_code == 422


async def test_analyze_rejects_blank_text(settings):
    async with client_for(build_app(settings)) as client:
        response = await client.post("/api/analyze", json={"text": "   "})
    assert response.status_code == 422


async def test_analyze_rejects_oversized_input(settings):
    async with client_for(build_app(settings)) as client:
        response = await client.post("/api/analyze", json={"text": "x" * 100_001})
    assert response.status_code == 422


async def test_analyze_rate_limit(settings):
    limited = settings.model_copy(
        update={"rate_limit_requests": 1, "rate_limit_window_seconds": 60.0}
    )
    async with client_for(build_app(limited)) as client:
        first = await client.post("/api/analyze", json={"text": TEXT})
        second = await client.post("/api/analyze", json={"text": TEXT})
        metrics = await client.get("/api/metrics")
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["retry-after"] == "60"
    assert 'path="/api/analyze",status="429"' in metrics.text


async def test_cors_origins_are_configurable(settings):
    restricted = settings.model_copy(update={"cors_origins": "https://app.example"})
    async with client_for(build_app(restricted)) as client:
        allowed = await client.options(
            "/api/analyze",
            headers={
                "Origin": "https://app.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        denied = await client.options(
            "/api/analyze",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
            },
        )
    assert allowed.headers["access-control-allow-origin"] == "https://app.example"
    assert "access-control-allow-origin" not in denied.headers
