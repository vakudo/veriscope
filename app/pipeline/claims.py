import asyncio
import re

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

VAGUE_SUBJECT_MARKERS = (
    "the report",
    "this report",
    "the article",
    "this article",
    "the text",
    "this text",
    "статья",
    "эта статья",
    "материал",
    "этот материал",
    "текст",
)


def is_checkworthy(text: str) -> bool:
    if len(text.split()) < 4:
        return False
    if text.rstrip().endswith("?"):
        return False
    lowered = text.lower()
    return not any(
        lowered.startswith(marker) for marker in (*OPINION_MARKERS, *VAGUE_SUBJECT_MARKERS)
    )


def split_text_chunks(
    text: str,
    chunk_chars: int = 3500,
    overlap: int = 300,
    max_chunks: int = 8,
) -> list[str]:
    cleaned = text.strip()
    if not cleaned:
        return []
    if chunk_chars < 200 or overlap < 0 or overlap >= chunk_chars or max_chunks < 1:
        raise ValueError("invalid claim chunk settings")
    chunks = []
    start = 0
    while start < len(cleaned):
        target_end = min(start + chunk_chars, len(cleaned))
        end = target_end
        if target_end < len(cleaned):
            search_from = start + chunk_chars // 2
            boundaries = (
                cleaned.rfind("\n\n", search_from, target_end),
                cleaned.rfind(". ", search_from, target_end),
                cleaned.rfind("\n", search_from, target_end),
            )
            boundary = max(boundaries)
            if boundary > start:
                end = boundary + (2 if cleaned[boundary : boundary + 2] in {"\n\n", ". "} else 1)
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)

    if len(chunks) <= max_chunks:
        return chunks
    if max_chunks == 1:
        return [chunks[0]]
    indices = [round(index * (len(chunks) - 1) / (max_chunks - 1)) for index in range(max_chunks)]
    return [chunks[index] for index in dict.fromkeys(indices)]


async def _extract_chunk(llm, chunk: str, max_claims: int, index: int, total: int) -> list[str]:
    user = (
        f"Extract at most {max_claims} claims from article chunk {index + 1} of {total}.\n\n"
        f"TEXT:\n{chunk}"
    )
    raw = await llm.chat(CLAIMS_SYSTEM, user, max_tokens=512)
    parsed = extract_json_value(raw)
    candidates = []
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict):
                item = item.get("claim") or item.get("text") or ""
            candidate = str(item).strip()
            if candidate and is_checkworthy(candidate):
                candidates.append(candidate)
            if len(candidates) >= max_claims:
                break
    return candidates


def _claims_are_similar(first: str, second: str, threshold: float = 0.78) -> bool:
    first_tokens = set(re.findall(r"\w+", first.casefold()))
    second_tokens = set(re.findall(r"\w+", second.casefold()))
    if not first_tokens or not second_tokens:
        return False
    return len(first_tokens & second_tokens) / len(first_tokens | second_tokens) >= threshold


async def extract_claims(
    llm,
    text: str,
    max_claims: int = 6,
    chunk_chars: int = 3500,
    chunk_overlap: int = 300,
    max_chunks: int = 8,
) -> list[Claim]:
    chunks = split_text_chunks(text, chunk_chars, chunk_overlap, max_chunks)
    if not chunks or max_claims < 1:
        return []
    batches = await asyncio.gather(
        *(
            _extract_chunk(llm, chunk, max_claims, index, len(chunks))
            for index, chunk in enumerate(chunks)
        )
    )
    selected: list[str] = []
    for position in range(max((len(batch) for batch in batches), default=0)):
        for batch in batches:
            if position >= len(batch):
                continue
            candidate = batch[position]
            if any(_claims_are_similar(candidate, existing) for existing in selected):
                continue
            selected.append(candidate)
            if len(selected) >= max_claims:
                return [Claim(id=index, text=claim) for index, claim in enumerate(selected)]
    claims = [Claim(id=index, text=claim) for index, claim in enumerate(selected)]
    return claims
