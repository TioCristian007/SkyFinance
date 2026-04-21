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
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

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
        # Supabase firma JWTs con el JWT secret (que es la misma SUPABASE_ANON_KEY
        # usada como HMAC secret, o la SUPABASE_JWT_SECRET si está configurada).
        # En producción se recomienda usar SUPABASE_JWT_SECRET directamente.
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

        return user_id

    except jwt.ExpiredSignatureError:
        raise AuthenticationError("Token expirado")
    except jwt.InvalidTokenError as e:
        logger.warning("jwt_invalid", error=str(e))
        raise AuthenticationError("Token inválido")
