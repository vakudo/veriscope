import asyncio

from app.config import Settings
from app.pipeline.claims import extract_claims
from app.pipeline.extract import extract_article
from app.pipeline.independence import mark_independence
from app.pipeline.manipulation import detect_manipulation
from app.pipeline.search import SearchProvider, gather_evidence
from app.pipeline.stance import detect_stance
from app.pipeline.verdict import aggregate_verdict, build_summary
from app.schemas import AnalysisResult, Claim, ClaimVerdict


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
        flags = detect_manipulation(title, text)
        claims = await extract_claims(self.llm, text, self.settings.max_claims)
        verdicts = list(await asyncio.gather(*(self._check_claim(claim) for claim in claims)))
        return AnalysisResult(
            input_title=title,
            claims=verdicts,
            flags=flags,
            summary=build_summary(verdicts, flags),
        )

    async def _check_claim(self, claim: Claim) -> ClaimVerdict:
        embedding = None
        if self.cache is not None:
            embedding = (await self.llm.embed([claim.text]))[0]
            cached = await self.cache.get(claim.text, embedding)
            if cached is not None:
                return aggregate_verdict(claim, cached)
        sources = await gather_evidence(
            self.llm,
            self.search,
            claim.text,
            self.settings.search_max_results,
            self.settings.evidence_top_k,
        )
        sources = await mark_independence(self.llm, sources, self.settings.duplicate_threshold)
        evidence = list(
            await asyncio.gather(
                *(detect_stance(self.llm, claim.text, source) for source in sources)
            )
        )
        if self.cache is not None and evidence:
            await self.cache.put(claim.text, embedding, evidence)
        return aggregate_verdict(claim, evidence)
