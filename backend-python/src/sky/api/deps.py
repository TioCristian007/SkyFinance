"""
sky.api.deps — Dependencias inyectables de FastAPI.

Uso:
    @router.get("/something")
    async def endpoint(user_id: str = Depends(require_user_id)):
        ...
"""

from fastapi import Depends, Request

from sky.api.middleware.jwt_auth import extract_and_verify_user_id


async def require_user_id(request: Request) -> str:
    """Dependency que garantiza un usuario autenticado."""
    return await extract_and_verify_user_id(request)
