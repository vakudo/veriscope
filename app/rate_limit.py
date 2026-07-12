import asyncio
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests: int, window_seconds: float):
        super().__init__(app)
        self.requests = requests
        self.window_seconds = window_seconds
        self._requests_by_client: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method != "POST" or request.url.path not in {
            "/api/analyze",
            "/api/analyze/stream",
        }:
            return await call_next(request)
        if self.requests <= 0:
            return await call_next(request)

        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        async with self._lock:
            timestamps = self._requests_by_client[client]
            cutoff = now - self.window_seconds
            while timestamps and timestamps[0] <= cutoff:
                timestamps.popleft()
            if len(timestamps) >= self.requests:
                retry_after = max(1, int(self.window_seconds - (now - timestamps[0]) + 0.999))
                return JSONResponse(
                    status_code=429,
                    content={"detail": "rate limit exceeded"},
                    headers={"Retry-After": str(retry_after)},
                )
            timestamps.append(now)
        return await call_next(request)
