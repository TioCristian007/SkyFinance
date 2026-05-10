"""
sky.api.deps — Dependencias inyectables de FastAPI.

Uso:
    @router.get("/something")
    async def endpoint(user_id: str = Depends(require_user_id)):
        ...
"""
from __future__ import annotations

from fastapi import Request

from sky.core.errors import AuthenticationError


async def require_user_id(request: Request) -> str:
    """
    Dependency que garantiza un usuario autenticado.

    Lee request.state.user_id seteado por JWTContextMiddleware (middleware layer).
    JWT se verifica UNA sola vez por request en el middleware; aquí solo se
    garantiza que era válido (defense-in-depth: si el middleware falla
    silenciosamente, este dependency rechaza con 401).
    """
    user_id: str | None = getattr(request.state, "user_id", None)
    if not user_id:
        raise AuthenticationError("Token de autenticación requerido")
    return user_id
