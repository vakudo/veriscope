import asyncio
import json
from dataclasses import dataclass

import trafilatura


@dataclass
class Article:
    text: str
    title: str | None = None
    published_at: str | None = None
    url: str | None = None


async def extract_article(url: str) -> Article | None:
    html = await asyncio.to_thread(trafilatura.fetch_url, url)
    if not html:
        return None
    raw = await asyncio.to_thread(
        trafilatura.extract,
        html,
        output_format="json",
        with_metadata=True,
        url=url,
    )
    if not raw:
        return None
    data = json.loads(raw)
    text = (data.get("text") or "").strip()
    if not text:
        return None
    return Article(
        text=text,
        title=data.get("title"),
        published_at=data.get("date"),
        url=url,
    )
