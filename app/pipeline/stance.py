import re

from app.pipeline.json_utils import extract_json_value
from app.schemas import EvidenceItem, EvidenceSource, Stance

STANCE_SYSTEM = (
    "You are a fact-checking assistant. Given a claim and an excerpt from a source, "
    "decide the stance of the source towards the claim. "
    'Respond with a JSON object: {"stance": "supports" | "refutes" | "not_enough_info", '
    '"rationale": "<one short sentence in the language of the claim>", '
    '"evidence_quote": "<short exact quote copied from SOURCE EXCERPT>"}. '
    "Use refutes only when the excerpt explicitly says the claim is false or states a mutually "
    "incompatible fact. A missing mention, unrelated information, or lack of confirmation is "
    "not a refutation. Choose not_enough_info when the excerpt neither clearly confirms nor "
    "contradicts the claim, and leave evidence_quote empty."
)

STANCE_VALUES = {stance.value for stance in Stance}

ABSENCE_MARKERS = (
    "does not mention",
    "doesn't mention",
    "does not provide",
    "doesn't provide",
    "no information",
    "not enough information",
    "not mentioned",
    "не упомина",
    "не содержит",
    "нет информации",
    "недостаточно информации",
)


def quote_is_in_excerpt(quote: str, excerpt: str) -> bool:
    normalized_quote = re.sub(r"\s+", " ", quote).strip().casefold()
    normalized_excerpt = re.sub(r"\s+", " ", excerpt).strip().casefold()
    return len(normalized_quote) >= 4 and normalized_quote in normalized_excerpt


def refutation_is_grounded(rationale: str, quote: str, excerpt: str) -> bool:
    lowered = rationale.casefold()
    return not any(marker in lowered for marker in ABSENCE_MARKERS) and quote_is_in_excerpt(
        quote, excerpt
    )


async def detect_stance(llm, claim_text: str, source: EvidenceSource) -> EvidenceItem:
    user = (
        f"CLAIM:\n{claim_text}\n\n"
        f"SOURCE TITLE:\n{source.title}\n\n"
        f"SOURCE EXCERPT:\n{source.snippet[:1200]}"
    )
    stance = Stance.not_enough_info
    rationale = ""
    evidence_quote = ""
    try:
        raw = await llm.chat(STANCE_SYSTEM, user, max_tokens=256)
        parsed = extract_json_value(raw)
        if isinstance(parsed, dict):
            value = str(parsed.get("stance", "")).strip().lower()
            if value in STANCE_VALUES:
                stance = Stance(value)
            rationale = str(parsed.get("rationale", "")).strip()
            evidence_quote = str(parsed.get("evidence_quote", "")).strip()
    except Exception:
        pass
    if stance == Stance.refutes and not refutation_is_grounded(
        rationale, evidence_quote, source.snippet
    ):
        stance = Stance.not_enough_info
        evidence_quote = ""
    elif evidence_quote and not quote_is_in_excerpt(evidence_quote, source.snippet):
        evidence_quote = ""
    return EvidenceItem(
        source=source,
        stance=stance,
        rationale=rationale,
        evidence_quote=evidence_quote,
    )
