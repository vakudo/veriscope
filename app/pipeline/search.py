import asyncio
import re
from dataclasses import dataclass
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import urlparse

from ddgs import DDGS

from app.pipeline.json_utils import extract_json_value
from app.pipeline.similarity import cosine
from app.schemas import EvidenceSource

CYRILLIC_PATTERN = re.compile(r"[а-яё]", re.IGNORECASE)

TRANSLATE_SYSTEM = (
    "Translate the user text to English. "
    "Output only the translation, one line, nothing else."
)

QUERY_PLAN_SYSTEM = (
    "You plan web research for a fact-check. Return JSON only with this shape: "
    '{"questions": ["2-3 concrete verification questions"], '
    '"queries": ["2-3 concise web search queries"]}. '
    "Preserve names, dates, quantities and locations. Include one query aimed at a primary or "
    "official source and one query capable of finding counter-evidence. Do not assume the claim "
    "is true or false. Queries must be search strings, not full explanations."
)


@dataclass
class SearchResult:
    url: str
    title: str
    snippet: str
    published_at: str | None = None


@dataclass(frozen=True)
class QueryPlan:
    queries: list[str]
    verification_questions: list[str]
    translated_claim: str | None = None


class SearchProvider(Protocol):
    async def search(self, query: str, max_results: int) -> list[SearchResult]: ...


def parse_publication_date(value: str | None) -> date | None:
    if not value:
        return None
    candidate = value.strip()
    try:
        return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date()
    except ValueError:
        pass
    for pattern in ("%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(candidate, pattern).date()
        except ValueError:
            pass
    try:
        return parsedate_to_datetime(candidate).date()
    except (TypeError, ValueError):
        return None


def published_after(value: str | None, cutoff: date | None) -> bool:
    parsed = parse_publication_date(value)
    return cutoff is not None and parsed is not None and parsed > cutoff


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
        parsed_date = parse_publication_date(published_at)
        results.append(
            SearchResult(
                url=url,
                title=title or "",
                snippet=snippet or "",
                published_at=parsed_date.isoformat() if parsed_date else published_at,
            )
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


def _clean_plan_items(value, limit: int, max_length: int = 200) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned = []
    seen = set()
    for item in value:
        text = " ".join(str(item).split()).strip()
        key = text.casefold()
        if len(text.split()) < 2 or len(text) > max_length or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


async def build_query_plan(
    llm,
    claim_text: str,
    cross_lingual: bool = True,
    context: str | None = None,
    max_queries: int = 5,
    enabled: bool = True,
) -> QueryPlan:
    fallback_queries, translated = await build_queries(llm, claim_text, cross_lingual)
    if not enabled:
        return QueryPlan(queries=fallback_queries, verification_questions=[], translated_claim=translated)
    user = f"CLAIM:\n{claim_text}"
    if context:
        user += f"\n\nCONTEXT:\n{context[:1000]}"
    planned_queries: list[str] = []
    questions: list[str] = []
    try:
        raw = await llm.chat(QUERY_PLAN_SYSTEM, user, max_tokens=384)
        parsed = extract_json_value(raw)
        if isinstance(parsed, dict):
            planned_queries = _clean_plan_items(parsed.get("queries"), limit=2)
            questions = _clean_plan_items(parsed.get("questions"), limit=3, max_length=300)
    except Exception:
        pass

    queries = []
    seen = set()
    for query in [fallback_queries[0], *planned_queries, *fallback_queries[1:]]:
        key = query.casefold()
        if key in seen:
            continue
        seen.add(key)
        queries.append(query)
        if len(queries) >= max(1, max_queries):
            break
    return QueryPlan(
        queries=queries,
        verification_questions=questions,
        translated_claim=translated,
    )


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
    published_before: date | None = None,
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
    if published_before:
        found = [result for result in found if not published_after(result.published_at, published_before)]
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
