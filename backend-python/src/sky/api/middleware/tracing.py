"""sky.api.middleware.tracing — Middleware de métricas por request."""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from sky.core.metrics import sky_api_request_duration


class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Registra sky_api_request_duration_seconds por endpoint y status."""

    async def dispatch(self, request: Request, call_next: Callable[..., Any]) -> Response:
        start = time.perf_counter()
        response: Response = await call_next(request)
        elapsed = time.perf_counter() - start

        # Usar el path pattern de la ruta (no la URL real) para evitar alta cardinalidad.
        # Ej: "/api/banking/sync/{id}" en vez de "/api/banking/sync/abc-123".
        route = request.scope.get("route")
        endpoint = route.path if route and hasattr(route, "path") else request.url.path

        sky_api_request_duration.labels(
            endpoint=endpoint,
            status=str(response.status_code),
        ).observe(elapsed)

        return response
