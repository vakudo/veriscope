import json
import logging
import time
import uuid
from collections import defaultdict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

access_logger = logging.getLogger("uvicorn.veriscope_access")
MIDDLEWARE_ENDPOINTS = {"/api/analyze", "/api/analyze/stream"}


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class MetricsRegistry:
    def __init__(self):
        self.requests: dict[tuple[str, str, int], int] = defaultdict(int)
        self.duration_seconds: dict[tuple[str, str], float] = defaultdict(float)
        self.duration_count: dict[tuple[str, str], int] = defaultdict(int)
        self.in_flight = 0

    def observe(self, method: str, path: str, status: int, duration_seconds: float) -> None:
        self.requests[(method, path, status)] += 1
        self.duration_seconds[(method, path)] += duration_seconds
        self.duration_count[(method, path)] += 1

    def render(self) -> str:
        lines = [
            "# HELP veriscope_http_requests_total HTTP requests handled.",
            "# TYPE veriscope_http_requests_total counter",
        ]
        for (method, path, status), count in sorted(self.requests.items()):
            labels = (
                f'method="{_escape_label(method)}",path="{_escape_label(path)}",status="{status}"'
            )
            lines.append(f"veriscope_http_requests_total{{{labels}}} {count}")
        lines.extend(
            [
                "# HELP veriscope_http_request_duration_seconds HTTP request duration.",
                "# TYPE veriscope_http_request_duration_seconds summary",
            ]
        )
        for method, path in sorted(self.duration_count):
            labels = f'method="{_escape_label(method)}",path="{_escape_label(path)}"'
            duration = self.duration_seconds[(method, path)]
            count = self.duration_count[(method, path)]
            lines.append(
                f"veriscope_http_request_duration_seconds_sum{{{labels}}} {duration:.6f}"
            )
            lines.append(f"veriscope_http_request_duration_seconds_count{{{labels}}} {count}")
        lines.extend(
            [
                "# HELP veriscope_http_requests_in_flight HTTP requests currently running.",
                "# TYPE veriscope_http_requests_in_flight gauge",
                f"veriscope_http_requests_in_flight {self.in_flight}",
            ]
        )
        return "\n".join(lines) + "\n"


class ObservabilityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, registry: MetricsRegistry):
        super().__init__(app)
        self.registry = registry

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = uuid.uuid4().hex
        request.state.request_id = request_id
        started = time.perf_counter()
        self.registry.in_flight += 1
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration = time.perf_counter() - started
            self.registry.in_flight -= 1
            route = request.scope.get("route")
            path = (
                request.url.path
                if route is not None or request.url.path in MIDDLEWARE_ENDPOINTS
                else "<unmatched>"
            )
            self.registry.observe(request.method, path, status, duration)
            access_logger.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": request.method,
                        "path": path,
                        "status": status,
                        "duration_ms": round(duration * 1000, 1),
                    },
                    separators=(",", ":"),
                )
            )
