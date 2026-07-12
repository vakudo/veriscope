import asyncio
import ipaddress
import json
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx
import trafilatura

REDIRECT_STATUSES = {301, 302, 303, 307, 308}


@dataclass
class Article:
    text: str
    title: str | None = None
    published_at: str | None = None
    url: str | None = None


async def validate_public_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("url must use http or https")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("url credentials are not allowed")

    try:
        literal = ipaddress.ip_address(parsed.hostname)
        addresses = {literal}
    except ValueError:
        try:
            resolved = await asyncio.to_thread(
                socket.getaddrinfo,
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except socket.gaierror as error:
            raise ValueError("url hostname could not be resolved") from error
        addresses = {ipaddress.ip_address(item[4][0]) for item in resolved}

    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("url must resolve only to public addresses")


async def fetch_public_html(
    url: str,
    *,
    timeout: float,
    max_bytes: int,
    max_redirects: int,
    client: httpx.AsyncClient | None = None,
) -> tuple[str, str]:
    current_url = url
    owns_client = client is None
    resolved_client = client or httpx.AsyncClient(
        follow_redirects=False,
        timeout=timeout,
        trust_env=False,
        headers={"User-Agent": "Veriscope/0.3 (+https://github.com/vakudo/veriscope)"},
    )
    try:
        for redirect_count in range(max_redirects + 1):
            await validate_public_url(current_url)
            async with resolved_client.stream("GET", current_url) as response:
                if response.status_code in REDIRECT_STATUSES:
                    location = response.headers.get("location")
                    if not location:
                        raise ValueError("article redirect has no location")
                    if redirect_count >= max_redirects:
                        raise ValueError("article has too many redirects")
                    current_url = urljoin(current_url, location)
                    continue
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        declared_size = int(content_length)
                    except ValueError:
                        declared_size = 0
                    if declared_size > max_bytes:
                        raise ValueError("article exceeds download size limit")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        raise ValueError("article exceeds download size limit")
                encoding = response.encoding or "utf-8"
                return body.decode(encoding, errors="replace"), current_url
    finally:
        if owns_client:
            await resolved_client.aclose()
    raise ValueError("article could not be downloaded")


async def extract_article(
    url: str,
    *,
    timeout: float = 12.0,
    max_bytes: int = 5_000_000,
    max_redirects: int = 5,
) -> Article | None:
    html, final_url = await fetch_public_html(
        url,
        timeout=timeout,
        max_bytes=max_bytes,
        max_redirects=max_redirects,
    )
    raw = await asyncio.to_thread(
        trafilatura.extract,
        html,
        output_format="json",
        with_metadata=True,
        url=final_url,
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
        url=final_url,
    )
