import hashlib
import json
from typing import Protocol

import asyncpg

from app.pipeline.similarity import cosine
from app.schemas import EvidenceItem


def claim_key(claim_text: str) -> str:
    return hashlib.sha256(claim_text.strip().lower().encode("utf-8")).hexdigest()


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
