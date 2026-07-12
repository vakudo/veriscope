import secrets

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

PROTECTED_ENDPOINTS = {"/api/analyze", "/api/analyze/stream"}


class ApiKeyMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, api_key: str):
        super().__init__(app)
        self.api_key = api_key

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if (
            not self.api_key
            or request.method != "POST"
            or request.url.path not in PROTECTED_ENDPOINTS
        ):
            return await call_next(request)
        provided = request.headers.get("X-API-Key", "")
        if not provided or not secrets.compare_digest(provided, self.api_key):
            return JSONResponse(
                status_code=401,
                content={"detail": "invalid or missing API key"},
                headers={"WWW-Authenticate": "API-Key"},
            )
        return await call_next(request)
