"""
sky.api.middleware.jwt_auth — Verificación JWT de Supabase.

RESUELVE P0-1: el backend Node confiaba en header x-user-id sin verificar.
Aquí el JWT se verifica criptográficamente contra la clave pública JWKS de Supabase.

Supabase firma JWTs con ES256 (ECDSA), no HS256.
La clave pública se obtiene del endpoint JWKS y se cachea en memoria.

Uso en routers:
    from sky.api.deps import require_user_id

    @router.get("/")
    async def my_endpoint(user_id: str = Depends(require_user_id)):
        ...
"""
from __future__ import annotations

import httpx
import jwt
from fastapi import Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from sky.core.config import settings
from sky.core.errors import AuthenticationError
from sky.core.logging import get_logger

logger = get_logger("jwt_auth")

_security = HTTPBearer(auto_error=False)

# Cache en memoria de las claves públicas JWKS de Supabase.
# Se cargan una vez al primer request y se reutilizan.
_jwks_client: jwt.PyJWKClient | None = None


def _get_jwks_client() -> jwt.PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        jwks_url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
        _jwks_client = jwt.PyJWKClient(jwks_url, cache_keys=True)
    return _jwks_client


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
        client = _get_jwks_client()
        signing_key = client.get_signing_key_from_jwt(token)

        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["ES256"],
            audience="authenticated",
        )

        user_id = payload.get("sub")
        if not user_id:
            raise AuthenticationError("Token no contiene user ID")

        logger.info("jwt_verified", user_id=user_id[:8] + "...")
        return str(user_id)

    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token expirado") from exc
    except jwt.InvalidTokenError as exc:
        logger.warning("jwt_invalid", error=str(exc))
        raise AuthenticationError("Token inválido") from exc