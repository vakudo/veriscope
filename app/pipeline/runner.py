import asyncio
import time
from collections.abc import Awaitable, Callable

from app.cache.store import result_key
from app.config import Settings
from app.i18n import detect_language, strings_for
from app.pipeline.claims import extract_claims
from app.pipeline.extract import extract_article
from app.pipeline.independence import mark_independence
from app.pipeline.manipulation import detect_manipulation
from app.pipeline.search import SearchProvider, build_queries, domain_of, gather_evidence
from app.pipeline.similarity import cosine
from app.pipeline.stance import detect_stance
from app.pipeline.verdict import aggregate_verdict, build_summary
from app.schemas import (
    AnalysisResult,
    Claim,
    ClaimVerdict,
    EvidenceItem,
    EvidenceSource,
    SourceType,
    Stance,
)

ProgressCallback = Callable[[dict], Awaitable[None]]


class FactCheckPipeline:
    def __init__(
        self,
        llm,
        search: SearchProvider,
        cache,
        settings: Settings,
        result_cache=None,
        calibration: dict[str, float] | None = None,
    ):
        self.llm = llm
        self.search = search
        self.cache = cache
        self.settings = settings
        self.result_cache = result_cache
        self.calibration = calibration or {}
        self._semaphore = asyncio.Semaphore(max(1, settings.max_concurrent_analyses))

    async def verify_claim(
        self,
        claim_text: str,
        claim_id: int = 0,
        exclude_domain: str | None = None,
        lang: str | None = None,
    ) -> ClaimVerdict:
        """Verify one already-normalized claim without extracting claims from an article."""
        resolved_text = claim_text.strip()
        if not resolved_text:
            raise ValueError("claim text is required")
        return await self._check_claim(
            Claim(id=claim_id, text=resolved_text),
            exclude_domain=exclude_domain,
            lang=lang or detect_language(resolved_text),
        )

    async def analyze(
        self,
        text: str | None = None,
        url: str | None = None,
        title: str | None = None,
        force: bool = False,
        progress: ProgressCallback | None = None,
    ) -> AnalysisResult:
        async def notify(event: dict) -> None:
            if progress is not None:
                await progress(event)

        cache_key = result_key(url, text)
        if self.result_cache is not None and not force:
            cached = await self.result_cache.get(cache_key)
            if cached is not None:
                await notify({"stage": "cached"})
                return cached
        async with self._semaphore:
            started = time.perf_counter()
            if url and not text:
                await notify({"stage": "extract"})
                article = await extract_article(url)
                if article is None:
                    raise ValueError("failed to extract article text from url")
                text = article.text
                title = title or article.title
            if not text or not text.strip():
                raise ValueError("no text to analyze")
            extract_done = time.perf_counter()
            exclude_domain = domain_of(url) if url else None
            lang = detect_language(text)
            flags = detect_manipulation(title, text, lang)
            await notify({"stage": "claims"})
            claims = await extract_claims(self.llm, text, self.settings.max_claims)
            total = len(claims)
            await notify({"stage": "claims_done", "total": total})
            claims_done = time.perf_counter()
            done_count = 0
            counter_lock = asyncio.Lock()

            async def check_and_report(claim: Claim) -> ClaimVerdict:
                nonlocal done_count
                verdict = await self._check_claim(claim, exclude_domain, lang)
                async with counter_lock:
                    done_count += 1
                    current = done_count
                await notify(
                    {
                        "stage": "claim_done",
                        "done": current,
                        "total": total,
                        "label": verdict.label.value,
                    }
                )
                return verdict

            verdicts = list(await asyncio.gather(*(check_and_report(claim) for claim in claims)))
            for verdict in verdicts:
                verdict.historical_accuracy = self.calibration.get(verdict.label.value)
            finished = time.perf_counter()
            result = AnalysisResult(
                input_title=title,
                language=lang,
                claims=verdicts,
                flags=flags,
                summary=build_summary(verdicts, flags, lang),
                timings={
                    "extract_s": round(extract_done - started, 1),
                    "claims_s": round(claims_done - extract_done, 1),
                    "verify_s": round(finished - claims_done, 1),
                    "total_s": round(finished - started, 1),
                },
            )
        if self.result_cache is not None:
            await self.result_cache.put(cache_key, result)
        return result

    async def _enrich_source(self, claim_text: str, source: EvidenceSource) -> None:
        try:
            article = await asyncio.wait_for(
                extract_article(source.url), timeout=self.settings.article_fetch_timeout
            )
        except Exception:
            return
        if article is None:
            return
        paragraphs = [
            line.strip() for line in article.text.splitlines() if len(line.strip()) >= 80
        ][:40]
        if not paragraphs:
            return
        try:
            vectors = await self.llm.embed([claim_text] + paragraphs)
        except Exception:
            return
        ranked = sorted(
            zip(paragraphs, vectors[1:], strict=False),
            key=lambda pair: cosine(vectors[0], pair[1]),
            reverse=True,
        )
        source.snippet = " … ".join(paragraph for paragraph, _ in ranked[:2])[:1600]
        if article.published_at and not source.published_at:
            source.published_at = article.published_at

    async def _check_claim(
        self, claim: Claim, exclude_domain: str | None = None, lang: str = "ru"
    ) -> ClaimVerdict:
        strings = strings_for(lang)
        embedding = None
        if self.cache is not None:
            embedding = (await self.llm.embed([claim.text]))[0]
            cached = await self.cache.get(claim.text, embedding)
            if cached is not None:
                if exclude_domain:
                    cached = [item for item in cached if item.source.domain != exclude_domain]
                return aggregate_verdict(claim, cached, lang)
        queries, translated = await build_queries(
            self.llm, claim.text, self.settings.cross_lingual_search
        )
        sources = await gather_evidence(
            self.llm,
            self.search,
            claim.text,
            self.settings.search_max_results,
            self.settings.evidence_top_k,
            self.settings.min_relevance,
            exclude_domain,
            queries,
            translated,
        )
        sources = await mark_independence(self.llm, sources, self.settings.duplicate_threshold)
        representatives: dict[int, EvidenceSource] = {}
        for source in sources:
            current = representatives.get(source.cluster_id)
            if current is None or (
                source.source_type == SourceType.possible_primary
                and current.source_type != SourceType.possible_primary
            ):
                representatives[source.cluster_id] = source
        if self.settings.deep_evidence:
            await asyncio.gather(
                *(
                    self._enrich_source(claim.text, representative)
                    for representative in representatives.values()
                )
            )
        judged = list(
            await asyncio.gather(
                *(
                    detect_stance(self.llm, claim.text, representative)
                    for representative in representatives.values()
                )
            )
        )
        if self.settings.verify_conflicts:
            supporting = [item for item in judged if item.stance == Stance.supports]
            refuting = [item for item in judged if item.stance == Stance.refutes]
            if supporting and refuting:
                if len(supporting) < len(refuting):
                    contested = supporting
                elif len(refuting) < len(supporting):
                    contested = refuting
                else:
                    contested = supporting + refuting
                rechecks = await asyncio.gather(
                    *(detect_stance(self.llm, claim.text, item.source) for item in contested)
                )
                for item, recheck in zip(contested, rechecks, strict=False):
                    if recheck.stance != item.stance:
                        item.stance = Stance.not_enough_info
                        item.rationale = strings["unstable"]
        by_cluster = {item.source.cluster_id: item for item in judged}
        evidence = []
        for source in sources:
            cluster_item = by_cluster[source.cluster_id]
            if source is cluster_item.source:
                evidence.append(cluster_item)
            else:
                evidence.append(
                    EvidenceItem(
                        source=source,
                        stance=cluster_item.stance,
                        rationale=strings["inherited"],
                    )
                )
        if self.cache is not None and evidence:
            await self.cache.put(claim.text, embedding, evidence)
        return aggregate_verdict(claim, evidence, lang)
