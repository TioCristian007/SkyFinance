"""sky.api.routers.profile — PATCH /api/profile para ajustes de usuario."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text

from sky.api.deps import require_user_id
from sky.core.db import get_engine
from sky.core.logging import get_logger

logger = get_logger("profile_router")
router = APIRouter(prefix="/api/profile", tags=["profile"])


class ProfilePatch(BaseModel):
    count_transfers_as_income:  bool | None = None
    count_transfers_as_expense: bool | None = None
    aria_consent:               bool | None = None


@router.patch("")
async def patch_profile(
    body: ProfilePatch,
    user_id: str = Depends(require_user_id),
) -> dict[str, object]:
    """Actualiza ajustes de perfil del usuario autenticado."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("""
                UPDATE public.profiles
                   SET count_transfers_as_income  = COALESCE(:income,   count_transfers_as_income),
                       count_transfers_as_expense = COALESCE(:expense,  count_transfers_as_expense),
                       aria_consent               = COALESCE(:consent,  aria_consent)
                 WHERE id = :uid
            """),
            {
                "income":  body.count_transfers_as_income,
                "expense": body.count_transfers_as_expense,
                "consent": body.aria_consent,
                "uid":     user_id,
            },
        )
    logger.info(
        "profile_updated",
        user_id=user_id,
        count_transfers_as_income=body.count_transfers_as_income,
        count_transfers_as_expense=body.count_transfers_as_expense,
    )
    if body.aria_consent is not None:
        logger.info("profile_aria_consent_changed", user_id=user_id, value=body.aria_consent)

    result: dict[str, object] = {}
    if body.count_transfers_as_income is not None:
        result["count_transfers_as_income"] = body.count_transfers_as_income
    if body.count_transfers_as_expense is not None:
        result["count_transfers_as_expense"] = body.count_transfers_as_expense
    if body.aria_consent is not None:
        result["aria_consent"] = body.aria_consent
    return result
