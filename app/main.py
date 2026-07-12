from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import router
from app.auth import ApiKeyMiddleware
from app.cache.store import MemoryEvidenceCache, MemoryResultCache, PgEvidenceCache, PgResultCache
from app.calibration import load_calibration
from app.config import Settings, get_settings
from app.llm import LLMClient
from app.observability import MetricsRegistry, ObservabilityMiddleware
from app.pipeline.runner import FactCheckPipeline
from app.pipeline.search import DdgsSearch
from app.rate_limit import RateLimitMiddleware


def create_app(settings: Settings | None = None, pipeline: FactCheckPipeline | None = None) -> FastAPI:
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if getattr(app.state, "pipeline", None) is not None:
            yield
            return
        llm = LLMClient(
            base_url=resolved.llm_base_url,
            api_key=resolved.llm_api_key,
            model=resolved.llm_model,
            embed_model=resolved.embed_model,
            timeout=resolved.request_timeout,
        )
        if resolved.database_url:
            cache = PgEvidenceCache(
                resolved.database_url, resolved.embed_dim, resolved.cache_similarity_threshold
            )
            await cache.init()
            result_cache = PgResultCache(cache.pool, resolved.result_cache_ttl_seconds)
            await result_cache.init()
        else:
            cache = MemoryEvidenceCache(resolved.cache_similarity_threshold)
            result_cache = MemoryResultCache(resolved.result_cache_ttl_seconds)
        app.state.pipeline = FactCheckPipeline(
            llm=llm,
            search=DdgsSearch(),
            cache=cache,
            settings=resolved,
            result_cache=result_cache,
            calibration=load_calibration(
                resolved.calibration_path, resolved.calibration_min_samples
            ),
        )
        app.state.readiness = llm.health
        yield
        await llm.close()
        if isinstance(cache, PgEvidenceCache):
            await cache.close()

    app = FastAPI(title="Veriscope", version=__version__, lifespan=lifespan)
    metrics = MetricsRegistry()
    app.state.metrics = metrics
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(ApiKeyMiddleware, api_key=resolved.api_access_key)
    app.add_middleware(
        RateLimitMiddleware,
        requests=resolved.rate_limit_requests,
        window_seconds=resolved.rate_limit_window_seconds,
    )
    app.add_middleware(ObservabilityMiddleware, registry=metrics)
    app.include_router(router, prefix="/api")
    if pipeline is not None:
        app.state.pipeline = pipeline
        app.state.readiness = getattr(pipeline.llm, "health", None)
    return app


app = create_app()
