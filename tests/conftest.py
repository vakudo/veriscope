import json

import pytest

from app.config import Settings
from app.pipeline.search import SearchResult


class FakeLLM:
    def __init__(self, claims: list[str] | None = None, vectors: dict[str, list[float]] | None = None):
        self.claims = claims or []
        self.vectors = vectors or {}
        self.chat_calls: list[tuple[str, str]] = []

    async def chat(self, system: str, user: str, **kwargs) -> str:
        self.chat_calls.append((system, user))
        if "atomic" in system:
            return json.dumps(self.claims)
        if "stance" in system:
            if "STANCE_SUPPORTS" in user:
                return json.dumps({"stance": "supports", "rationale": "подтверждает"})
            if "STANCE_REFUTES" in user:
                return json.dumps({"stance": "refutes", "rationale": "опровергает"})
            return json.dumps({"stance": "not_enough_info", "rationale": ""})
        return "{}"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        for marker, vector in self.vectors.items():
            if marker in text:
                return vector
        seed = sum(ord(char) for char in text) % 97
        return [1.0, float(seed), float(seed * seed % 31)]


class RawLLM:
    def __init__(self, raw: str):
        self.raw = raw

    async def chat(self, system: str, user: str, **kwargs) -> str:
        return self.raw

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, 0.0, 0.0] for _ in texts]


class FakeSearch:
    def __init__(
        self,
        results: dict[str, list[SearchResult]] | None = None,
        default: list[SearchResult] | None = None,
    ):
        self.results = results or {}
        self.default = default or []
        self.queries: list[str] = []

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        self.queries.append(query)
        for key, value in self.results.items():
            if key in query:
                return value[:max_results]
        return self.default[:max_results]


@pytest.fixture
def settings() -> Settings:
    return Settings(
        database_url=None,
        search_max_results=8,
        evidence_top_k=4,
        duplicate_threshold=0.9,
        min_relevance=0.0,
        max_claims=6,
    )
