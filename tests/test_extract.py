import socket

import httpx
import pytest

from app.pipeline.extract import fetch_public_html, validate_public_url


async def test_private_and_non_http_urls_are_rejected():
    with pytest.raises(ValueError, match="public addresses"):
        await validate_public_url("http://127.0.0.1/admin")
    with pytest.raises(ValueError, match="http or https"):
        await validate_public_url("file:///etc/passwd")
    with pytest.raises(ValueError, match="credentials"):
        await validate_public_url("https://user:password@example.com/")


async def test_hostname_must_resolve_only_to_public_addresses(monkeypatch):
    def mixed_addresses(*args, **kwargs):
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", mixed_addresses)
    with pytest.raises(ValueError, match="public addresses"):
        await validate_public_url("https://mixed.example/article")


async def test_redirect_target_is_validated(monkeypatch):
    validated = []

    async def validate(url):
        validated.append(url)
        if "127.0.0.1" in url:
            raise ValueError("url must resolve only to public addresses")

    async def handler(request):
        return httpx.Response(302, headers={"Location": "http://127.0.0.1/private"})

    monkeypatch.setattr("app.pipeline.extract.validate_public_url", validate)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ValueError, match="public addresses"):
            await fetch_public_html(
                "https://public.example/article",
                timeout=1,
                max_bytes=1_000,
                max_redirects=3,
                client=client,
            )
    finally:
        await client.aclose()
    assert validated == [
        "https://public.example/article",
        "http://127.0.0.1/private",
    ]


async def test_streaming_download_enforces_size_limit(monkeypatch):
    async def validate(url):
        return None

    async def handler(request):
        return httpx.Response(200, content=b"x" * 101)

    monkeypatch.setattr("app.pipeline.extract.validate_public_url", validate)
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(ValueError, match="size limit"):
            await fetch_public_html(
                "https://public.example/article",
                timeout=1,
                max_bytes=100,
                max_redirects=0,
                client=client,
            )
    finally:
        await client.aclose()
