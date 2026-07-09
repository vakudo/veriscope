import asyncio
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from ddgs import DDGS

from app.pipeline.similarity import cosine
from app.schemas import EvidenceSource


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str
    published_at: str | None = None


class SearchProvider(Protocol):
    async def search(self, query: str, max_results: int) -> list[SearchResult]: ...


class DdgsSearch:
    def __init__(self, region: str = "wt-wt"):
        self.region = region

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        return await asyncio.to_thread(self._search_sync, query, max_results)

    def _search_sync(self, query: str, max_results: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        seen: set[str] = set()
        with DDGS() as ddgs:
            try:
                for row in ddgs.news(query, region=self.region, max_results=max_results):
                    self._append(
                        results, seen, row.get("url"), row.get("title"), row.get("body"), row.get("date")
                    )
            except Exception:
                pass
            if len(results) < max_results:
                try:
                    for row in ddgs.text(query, region=self.region, max_results=max_results):
                        self._append(
                            results, seen, row.get("href"), row.get("title"), row.get("body"), None
                        )
                except Exception:
                    pass
        return results[:max_results]

    @staticmethod
    def _append(
        results: list[SearchResult],
        seen: set[str],
        url: str | None,
        title: str | None,
        snippet: str | None,
        published_at: str | None,
    ) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        results.append(
            SearchResult(url=url, title=title or "", snippet=snippet or "", published_at=published_at)
        )


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


async def gather_evidence(
    llm,
    search: SearchProvider,
    claim_text: str,
    max_results: int,
    top_k: int,
    min_relevance: float = 0.0,
    exclude_domain: str | None = None,
) -> list[EvidenceSource]:
    query = " ".join(claim_text.split()[:16])
    found = await search.search(query, max_results)
    if exclude_domain:
        found = [result for result in found if domain_of(result.url) != exclude_domain]
    if not found:
        return []
    vectors = await llm.embed([claim_text] + [f"{r.title}\n{r.snippet}" for r in found])
    claim_vector, result_vectors = vectors[0], vectors[1:]
    scored = [
        (result, cosine(claim_vector, vector))
        for result, vector in zip(found, result_vectors, strict=False)
    ]
    relevant = sorted(
        (pair for pair in scored if pair[1] >= min_relevance),
        key=lambda pair: pair[1],
        reverse=True,
    )
    return [
        EvidenceSource(
            url=result.url,
            domain=domain_of(result.url),
            title=result.title,
            snippet=result.snippet,
            published_at=result.published_at,
        )
        for result, _ in relevant[:top_k]
    ]
