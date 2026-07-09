from enum import StrEnum

from pydantic import BaseModel


class Stance(StrEnum):
    supports = "supports"
    refutes = "refutes"
    not_enough_info = "not_enough_info"


class SourceType(StrEnum):
    possible_primary = "possible_primary"
    reprint = "reprint"
    opinion = "opinion"
    unknown = "unknown"


class VerdictLabel(StrEnum):
    supported = "supported"
    refuted = "refuted"
    conflicting = "conflicting"
    unverifiable = "unverifiable"


class Confidence(StrEnum):
    high = "high"
    low = "low"


class AnalyzeRequest(BaseModel):
    text: str | None = None
    url: str | None = None
    title: str | None = None


class Claim(BaseModel):
    id: int
    text: str


class EvidenceSource(BaseModel):
    url: str
    domain: str
    title: str = ""
    snippet: str = ""
    published_at: str | None = None
    source_type: SourceType = SourceType.unknown
    cluster_id: int = -1


class EvidenceItem(BaseModel):
    source: EvidenceSource
    stance: Stance
    rationale: str = ""


class ClaimVerdict(BaseModel):
    claim: Claim
    label: VerdictLabel
    confidence: Confidence
    independent_supporting: int
    independent_refuting: int
    evidence: list[EvidenceItem]
    explanation: str


class ManipulationFlag(BaseModel):
    kind: str
    detail: str


class AnalysisResult(BaseModel):
    input_title: str | None = None
    claims: list[ClaimVerdict]
    flags: list[ManipulationFlag]
    summary: str
