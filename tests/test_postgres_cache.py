import os
import uuid

import asyncpg
import pytest

from app.cache.store import PgResultCache
from app.schemas import AnalysisResult

DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.mark.skipif(not DATABASE_URL, reason="TEST_DATABASE_URL is not configured")
async def test_postgres_result_cache_roundtrip_and_expiry():
    pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=2)
    key = f"integration-{uuid.uuid4().hex}"
    try:
        cache = PgResultCache(pool, ttl_seconds=60)
        await cache.init()
        expected = AnalysisResult(claims=[], flags=[], summary="persistent result")
        await cache.put(key, expected)
        assert await cache.get(key) == expected

        expired = PgResultCache(pool, ttl_seconds=-1)
        await expired.put(key, expected)
        assert await expired.get(key) is None
    finally:
        async with pool.acquire() as connection:
            await connection.execute("DELETE FROM result_cache WHERE result_key = $1", key)
        await pool.close()
