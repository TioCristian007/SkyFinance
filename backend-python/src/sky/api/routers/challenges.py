"""sky.api.routers.challenges — Desafíos financieros."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from sky.api.deps import require_user_id
from sky.api.schemas.challenges import (
    ChallengeAcceptResponse,
    ChallengeDeclineResponse,
    ChallengeOut,
)
from sky.core.logging import get_logger
from sky.domain import challenges as domain_challenges

logger = get_logger("api.challenges")
router = APIRouter(prefix="/api/challenges", tags=["challenges"])


@router.get("", response_model=list[ChallengeOut])
async def list_challenges(
    user_id: str = Depends(require_user_id),
) -> list[ChallengeOut]:
    rows = await domain_challenges.get_challenges(user_id)
    return [
        ChallengeOut(
            id=str(r["id"]),
            title=str(r["title"]),
            description=str(r["description"] or ""),
            target_amount=int(r["target_amount"] or 0),
            current_amount=int(r["current_amount"] or 0),
            start_date=r["start_date"],
            end_date=r["end_date"],
            status=str(r["status"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.post("/{challenge_id}/accept", response_model=ChallengeAcceptResponse)
async def accept_challenge(
    challenge_id: str,
    user_id: str = Depends(require_user_id),
) -> ChallengeAcceptResponse:
    result = await domain_challenges.accept_challenge(
        user_id=user_id, challenge_id=challenge_id,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Desafío no encontrado o ya no está en estado propuesto",
        )
    logger.info("challenge_accepted", challenge_id=challenge_id)
    return ChallengeAcceptResponse(id=str(result["id"]), status="active")


@router.post("/{challenge_id}/decline", response_model=ChallengeDeclineResponse)
async def decline_challenge(
    challenge_id: str,
    user_id: str = Depends(require_user_id),
) -> ChallengeDeclineResponse:
    result = await domain_challenges.decline_challenge(
        user_id=user_id, challenge_id=challenge_id,
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="Desafío no encontrado o ya no está en estado propuesto",
        )
    logger.info("challenge_declined", challenge_id=challenge_id)
    return ChallengeDeclineResponse(id=str(result["id"]), status="declined")
