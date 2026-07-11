import asyncio
import re
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

from ddgs import DDGS

from app.pipeline.similarity import cosine
from app.schemas import EvidenceSource

CYRILLIC_PATTERN = re.compile(r"[а-яё]", re.IGNORECASE)

TRANSLATE_SYSTEM = (
    "Translate the user text to English. "
    "Output only the translation, one line, nothing else."
)


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


def base_query(claim_text: str) -> str:
    return " ".join(claim_text.split()[:16])


async def translate_to_english(llm, text: str) -> str | None:
    try:
        raw = await llm.chat(TRANSLATE_SYSTEM, text[:300], max_tokens=128)
    except Exception:
        return None
    lines = [line.strip() for line in raw.strip().splitlines() if line.strip()]
    if not lines:
        return None
    translated = lines[0]
    if CYRILLIC_PATTERN.search(translated):
        return None
    return translated


async def build_queries(llm, claim_text: str, cross_lingual: bool = True) -> tuple[list[str], str | None]:
    base = base_query(claim_text)
    queries = [base]
    translated = None
    if CYRILLIC_PATTERN.search(claim_text):
        queries.append(f"{base} опровержение фейк")
        if cross_lingual:
            translated = await translate_to_english(llm, claim_text)
            if translated:
                queries.append(base_query(translated))
    else:
        queries.append(f"{base} fact check false")
    return queries, translated


async def gather_evidence(
    llm,
    search: SearchProvider,
    claim_text: str,
    max_results: int,
    top_k: int,
    min_relevance: float = 0.0,
    exclude_domain: str | None = None,
    queries: list[str] | None = None,
    alt_claim_text: str | None = None,
) -> list[EvidenceSource]:
    if not queries:
        queries = [base_query(claim_text)]
    batches = await asyncio.gather(*(search.search(query, max_results) for query in queries))
    found: list[SearchResult] = []
    seen: set[str] = set()
    for batch in batches:
        for result in batch:
            if result.url in seen:
                continue
            seen.add(result.url)
            found.append(result)
    if exclude_domain:
        found = [result for result in found if domain_of(result.url) != exclude_domain]
    if not found:
        return []
    claim_texts = [claim_text] + ([alt_claim_text] if alt_claim_text else [])
    vectors = await llm.embed(claim_texts + [f"{r.title}\n{r.snippet}" for r in found])
    claim_vectors, result_vectors = vectors[: len(claim_texts)], vectors[len(claim_texts) :]
    scored = [
        (result, max(cosine(claim_vector, vector) for claim_vector in claim_vectors))
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
