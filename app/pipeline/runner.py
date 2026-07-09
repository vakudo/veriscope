import asyncio

from app.config import Settings
from app.pipeline.claims import extract_claims
from app.pipeline.extract import extract_article
from app.pipeline.independence import mark_independence
from app.pipeline.manipulation import detect_manipulation
from app.pipeline.search import SearchProvider, domain_of, gather_evidence
from app.pipeline.stance import INHERITED_RATIONALE, detect_stance
from app.pipeline.verdict import aggregate_verdict, build_summary
from app.schemas import AnalysisResult, Claim, ClaimVerdict, EvidenceItem, EvidenceSource, SourceType


class FactCheckPipeline:
    def __init__(self, llm, search: SearchProvider, cache, settings: Settings):
        self.llm = llm
        self.search = search
        self.cache = cache
        self.settings = settings

    async def analyze(
        self,
        text: str | None = None,
        url: str | None = None,
        title: str | None = None,
    ) -> AnalysisResult:
        if url and not text:
            article = await extract_article(url)
            if article is None:
                raise ValueError("failed to extract article text from url")
            text = article.text
            title = title or article.title
        if not text or not text.strip():
            raise ValueError("no text to analyze")
        exclude_domain = domain_of(url) if url else None
        flags = detect_manipulation(title, text)
        claims = await extract_claims(self.llm, text, self.settings.max_claims)
        verdicts = list(
            await asyncio.gather(*(self._check_claim(claim, exclude_domain) for claim in claims))
        )
        return AnalysisResult(
            input_title=title,
            claims=verdicts,
            flags=flags,
            summary=build_summary(verdicts, flags),
        )

    async def _check_claim(self, claim: Claim, exclude_domain: str | None = None) -> ClaimVerdict:
        embedding = None
        if self.cache is not None:
            embedding = (await self.llm.embed([claim.text]))[0]
            cached = await self.cache.get(claim.text, embedding)
            if cached is not None:
                if exclude_domain:
                    cached = [item for item in cached if item.source.domain != exclude_domain]
                return aggregate_verdict(claim, cached)
        sources = await gather_evidence(
            self.llm,
            self.search,
            claim.text,
            self.settings.search_max_results,
            self.settings.evidence_top_k,
            self.settings.min_relevance,
            exclude_domain,
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
        judged = await asyncio.gather(
            *(
                detect_stance(self.llm, claim.text, representative)
                for representative in representatives.values()
            )
        )
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
                        rationale=INHERITED_RATIONALE,
                    )
                )
        if self.cache is not None and evidence:
            await self.cache.put(claim.text, embedding, evidence)
        return aggregate_verdict(claim, evidence)
