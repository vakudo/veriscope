from app.pipeline.json_utils import extract_json_value
from app.schemas import Claim

CLAIMS_SYSTEM = (
    "You decompose news text into atomic, independently checkable factual claims. "
    "Each claim must be a single self-contained statement with concrete actors, actions, "
    "numbers and dates resolved from the text. Skip opinions, predictions and value judgements. "
    "Keep the language of the original text. "
    "Respond with a JSON array of strings and nothing else."
)


async def extract_claims(llm, text: str, max_claims: int = 6) -> list[Claim]:
    user = f"Extract at most {max_claims} claims.\n\nTEXT:\n{text[:6000]}"
    raw = await llm.chat(CLAIMS_SYSTEM, user)
    parsed = extract_json_value(raw)
    claims: list[Claim] = []
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                item = item.get("claim") or item.get("text") or ""
            candidate = str(item).strip()
            if candidate:
                claims.append(Claim(id=len(claims), text=candidate))
            if len(claims) >= max_claims:
                break
    return claims
