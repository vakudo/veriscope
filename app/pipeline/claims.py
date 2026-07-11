from app.pipeline.json_utils import extract_json_value
from app.schemas import Claim

CLAIMS_SYSTEM = (
    "You decompose news text into atomic, independently checkable factual claims. "
    "Each claim must be a single self-contained statement with concrete actors, actions, "
    "numbers and dates resolved from the text. Skip opinions, predictions, questions, "
    "value judgements and claims too vague to verify. "
    "Keep the language of the original text. "
    "Respond with a JSON array of strings and nothing else."
)

OPINION_MARKERS = (
    "по мнению",
    "по словам автора",
    "я думаю",
    "я считаю",
    "кажется",
    "in my opinion",
    "i think",
    "arguably",
)


def is_checkworthy(text: str) -> bool:
    if len(text.split()) < 4:
        return False
    if text.rstrip().endswith("?"):
        return False
    lowered = text.lower()
    return not any(lowered.startswith(marker) for marker in OPINION_MARKERS)


async def extract_claims(llm, text: str, max_claims: int = 6) -> list[Claim]:
    user = f"Extract at most {max_claims} claims.\n\nTEXT:\n{text[:3500]}"
    raw = await llm.chat(CLAIMS_SYSTEM, user, max_tokens=512)
    parsed = extract_json_value(raw)
    claims: list[Claim] = []
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                item = item.get("claim") or item.get("text") or ""
            candidate = str(item).strip()
            if candidate and is_checkworthy(candidate):
                claims.append(Claim(id=len(claims), text=candidate))
            if len(claims) >= max_claims:
                break
    return claims
