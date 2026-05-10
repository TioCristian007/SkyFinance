"""sky.api.middleware.jwt_context — Setea request.state.user_id para rate limiter."""
from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from sky.api.middleware.jwt_auth import extract_and_verify_user_id
from sky.core.errors import AuthenticationError


class JWTContextMiddleware(BaseHTTPMiddleware):
    """
    Extrae y verifica JWT. Si es válido, setea request.state.user_id (str UUID).
    Si es inválido o ausente, setea request.state.user_id = None.

    NO rechaza requests — eso es responsabilidad de require_user_id (deps.py).
    Propósito: proveer user_id verificado al SlowAPIMiddleware (rate limit key)
    y a cualquier otro middleware que lo necesite.

    Corre ANTES de SlowAPIMiddleware (añadido después en LIFO → más externo en request).
    JWT se verifica una sola vez por request en el middleware layer.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.user_id = None
        with contextlib.suppress(AuthenticationError, Exception):
            request.state.user_id = await extract_and_verify_user_id(request)
        return await call_next(request)
