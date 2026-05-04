"""
sky.api.middleware.jwt_auth — Verificación JWT de Supabase.

RESUELVE P0-1: el backend Node confiaba en header x-user-id sin verificar.
Aquí el JWT se verifica criptográficamente contra la clave de Supabase.

Uso en routers:
    from sky.api.deps import require_user_id

    @router.get("/")
    async def my_endpoint(user_id: str = Depends(require_user_id)):
        ...
"""
from __future__ import annotations

import jwt
from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from sky.core.config import settings
from sky.core.errors import AuthenticationError
from sky.core.logging import get_logger

logger = get_logger("jwt_auth")

_security = HTTPBearer(auto_error=False)


async def extract_and_verify_user_id(request: Request) -> str:
    """
    Extrae y verifica el JWT del header Authorization.

    Returns:
        user_id (UUID string) del usuario autenticado.

    Raises:
        AuthenticationError: si el JWT es inválido, expirado o ausente.
    """
    credentials: HTTPAuthorizationCredentials | None = await _security(request)

    if credentials is None:
        raise AuthenticationError("Token de autenticación requerido")

    token = credentials.credentials

    try:
        jwt_secret = settings.supabase_anon_key
        payload = jwt.decode(
            token,
            jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )

        user_id = payload.get("sub")
        if not user_id:
            raise AuthenticationError("Token no contiene user ID")

        return str(user_id)

    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token expirado") from exc
    except jwt.InvalidTokenError as exc:
        logger.warning("jwt_invalid", error=str(exc))
        raise AuthenticationError("Token inválido") from exc
