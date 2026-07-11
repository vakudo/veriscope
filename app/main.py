from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.cache.store import MemoryEvidenceCache, MemoryResultCache, PgEvidenceCache
from app.calibration import load_calibration
from app.config import Settings, get_settings
from app.llm import LLMClient
from app.pipeline.runner import FactCheckPipeline
from app.pipeline.search import DdgsSearch


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
        else:
            cache = MemoryEvidenceCache(resolved.cache_similarity_threshold)
        app.state.pipeline = FactCheckPipeline(
            llm=llm,
            search=DdgsSearch(),
            cache=cache,
            settings=resolved,
            result_cache=MemoryResultCache(resolved.result_cache_ttl_seconds),
            calibration=load_calibration(resolved.calibration_path),
        )
        yield
        await llm.close()
        if isinstance(cache, PgEvidenceCache):
            await cache.close()

    app = FastAPI(title="Veriscope", version="0.3.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api")
    if pipeline is not None:
        app.state.pipeline = pipeline
    return app


app = create_app()
