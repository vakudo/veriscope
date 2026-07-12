import hashlib
import json
import time
from typing import Protocol

import asyncpg

from app.pipeline.similarity import cosine
from app.schemas import AnalysisResult, EvidenceItem


def claim_key(claim_text: str) -> str:
    return hashlib.sha256(claim_text.strip().lower().encode("utf-8")).hexdigest()


def result_key(url: str | None, text: str | None) -> str:
    basis = (url or "").strip() or (text or "").strip()
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


class MemoryResultCache:
    def __init__(self, ttl_seconds: float = 21600.0):
        self.ttl_seconds = ttl_seconds
        self._items: dict[str, tuple[float, AnalysisResult]] = {}

    async def get(self, key: str) -> AnalysisResult | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        stored_at, result = entry
        if time.time() - stored_at > self.ttl_seconds:
            del self._items[key]
            return None
        return result.model_copy(deep=True)

    async def put(self, key: str, result: AnalysisResult) -> None:
        self._items[key] = (time.time(), result.model_copy(deep=True))


class PgResultCache:
    def __init__(self, pool: asyncpg.Pool, ttl_seconds: float = 21600.0):
        self._pool = pool
        self.ttl_seconds = ttl_seconds

    async def init(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS result_cache (
                    result_key TEXT PRIMARY KEY,
                    payload JSONB NOT NULL,
                    expires_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS result_cache_expires_at_idx ON result_cache (expires_at)"
            )

    async def get(self, key: str) -> AnalysisResult | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT payload
                FROM result_cache
                WHERE result_key = $1 AND expires_at > now()
                """,
                key,
            )
        if row is None:
            return None
        return AnalysisResult.model_validate(json.loads(row["payload"]))

    async def put(self, key: str, result: AnalysisResult) -> None:
        payload = json.dumps(result.model_dump(mode="json"))
        async with self._pool.acquire() as conn:
            await conn.execute("DELETE FROM result_cache WHERE expires_at <= now()")
            await conn.execute(
                """
                INSERT INTO result_cache (result_key, payload, expires_at)
                VALUES ($1, $2, now() + $3::double precision * interval '1 second')
                ON CONFLICT (result_key)
                DO UPDATE SET payload = excluded.payload, expires_at = excluded.expires_at
                """,
                key,
                payload,
                self.ttl_seconds,
            )


class EvidenceCache(Protocol):
    async def get(
        self, claim_text: str, embedding: list[float] | None
    ) -> list[EvidenceItem] | None: ...

    async def put(
        self, claim_text: str, embedding: list[float] | None, evidence: list[EvidenceItem]
    ) -> None: ...


class MemoryEvidenceCache:
    def __init__(self, similarity_threshold: float = 0.95):
        self.similarity_threshold = similarity_threshold
        self._by_key: dict[str, list[EvidenceItem]] = {}
        self._embeddings: dict[str, list[float]] = {}

    async def get(
        self, claim_text: str, embedding: list[float] | None = None
    ) -> list[EvidenceItem] | None:
        key = claim_key(claim_text)
        if key in self._by_key:
            return [item.model_copy(deep=True) for item in self._by_key[key]]
        if embedding:
            for other_key, other_vector in self._embeddings.items():
                if cosine(embedding, other_vector) >= self.similarity_threshold:
                    return [item.model_copy(deep=True) for item in self._by_key[other_key]]
        return None

    async def put(
        self, claim_text: str, embedding: list[float] | None, evidence: list[EvidenceItem]
    ) -> None:
        key = claim_key(claim_text)
        self._by_key[key] = [item.model_copy(deep=True) for item in evidence]
        if embedding:
            self._embeddings[key] = embedding


class PgEvidenceCache:
    def __init__(self, database_url: str, embed_dim: int, similarity_threshold: float = 0.95):
        self.database_url = database_url
        self.embed_dim = embed_dim
        self.similarity_threshold = similarity_threshold
        self._pool: asyncpg.Pool | None = None

    async def init(self) -> None:
        self._pool = await asyncpg.create_pool(self.database_url)
        async with self._pool.acquire() as conn:
            await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS evidence_cache (
                    claim_key TEXT PRIMARY KEY,
                    claim_text TEXT NOT NULL,
                    embedding vector({self.embed_dim}),
                    payload JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("PostgreSQL cache is not initialized")
        return self._pool

    async def get(
        self, claim_text: str, embedding: list[float] | None = None
    ) -> list[EvidenceItem] | None:
        if self._pool is None:
            return None
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT payload FROM evidence_cache WHERE claim_key = $1",
                claim_key(claim_text),
            )
            if row is None and embedding:
                row = await conn.fetchrow(
                    """
                    SELECT payload, 1 - (embedding <=> $1::vector) AS similarity
                    FROM evidence_cache
                    WHERE embedding IS NOT NULL
                    ORDER BY embedding <=> $1::vector
                    LIMIT 1
                    """,
                    _vector_literal(embedding),
                )
                if row is not None and row["similarity"] < self.similarity_threshold:
                    row = None
        if row is None:
            return None
        return [EvidenceItem.model_validate(item) for item in json.loads(row["payload"])]

    async def put(
        self, claim_text: str, embedding: list[float] | None, evidence: list[EvidenceItem]
    ) -> None:
        if self._pool is None:
            return
        payload = json.dumps([item.model_dump(mode="json") for item in evidence])
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO evidence_cache (claim_key, claim_text, embedding, payload)
                VALUES ($1, $2, $3::vector, $4)
                ON CONFLICT (claim_key)
                DO UPDATE SET claim_text = $2, embedding = $3::vector, payload = $4
                """,
                claim_key(claim_text),
                claim_text,
                _vector_literal(embedding) if embedding else None,
                payload,
            )


def _vector_literal(embedding: list[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in embedding) + "]"
