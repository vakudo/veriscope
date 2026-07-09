from app.pipeline.json_utils import extract_json_value
from app.schemas import EvidenceItem, EvidenceSource, Stance

STANCE_SYSTEM = (
    "You are a fact-checking assistant. Given a claim and an excerpt from a source, "
    "decide the stance of the source towards the claim. "
    'Respond with a JSON object: {"stance": "supports" | "refutes" | "not_enough_info", '
    '"rationale": "<one short sentence in the language of the claim>"}. '
    "Choose not_enough_info when the excerpt neither clearly confirms nor contradicts the claim."
)

STANCE_VALUES = {stance.value for stance in Stance}


async def detect_stance(llm, claim_text: str, source: EvidenceSource) -> EvidenceItem:
    user = (
        f"CLAIM:\n{claim_text}\n\n"
        f"SOURCE TITLE:\n{source.title}\n\n"
        f"SOURCE EXCERPT:\n{source.snippet[:2000]}"
    )
    stance = Stance.not_enough_info
    rationale = ""
    try:
        raw = await llm.chat(STANCE_SYSTEM, user)
        parsed = extract_json_value(raw)
        if isinstance(parsed, dict):
            value = str(parsed.get("stance", "")).strip().lower()
            if value in STANCE_VALUES:
                stance = Stance(value)
            rationale = str(parsed.get("rationale", "")).strip()
    except Exception:
        pass
    return EvidenceItem(source=source, stance=stance, rationale=rationale)
