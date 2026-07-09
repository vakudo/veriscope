import httpx


class LLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        embed_model: str,
        timeout: float = 120.0,
    ):
        self.model = model
        self.embed_model = embed_model
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    async def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        response = await self._client.post(
            "/chat/completions",
            json={
                "model": self.model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = await self._client.post(
            "/embeddings",
            json={"model": self.embed_model, "input": texts},
        )
        response.raise_for_status()
        data = sorted(response.json()["data"], key=lambda item: item["index"])
        return [item["embedding"] for item in data]

    async def close(self) -> None:
        await self._client.aclose()
