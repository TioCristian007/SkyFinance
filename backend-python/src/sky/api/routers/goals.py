"""sky.api.routers.goals — CRUD de metas financieras."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from sky.api.deps import require_user_id
from sky.api.schemas.goals import GoalCreateRequest, GoalOut, GoalPatchRequest
from sky.core.logging import get_logger
from sky.domain import goals as domain_goals

logger = get_logger("api.goals")
router = APIRouter(prefix="/api/goals", tags=["goals"])


@router.get("", response_model=list[GoalOut])
async def list_goals(
    user_id: str = Depends(require_user_id),
) -> list[GoalOut]:
    rows = await domain_goals.get_goals(user_id)
    return [
        GoalOut(
            id=str(r["id"]),
            name=str(r["name"]),
            target_amount=int(r["target_amount"]),
            current_amount=int(r["current_amount"] or 0),
            target_date=r.get("target_date"),
            progress_pct=float(r.get("progress_pct", 0.0)),
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.post("", response_model=GoalOut, status_code=201)
async def create_goal(
    body: GoalCreateRequest,
    user_id: str = Depends(require_user_id),
) -> GoalOut:
    row = await domain_goals.create_goal(
        user_id=user_id,
        name=body.name,
        target_amount=body.target_amount,
        target_date=body.target_date,
    )
    return GoalOut(
        id=str(row["id"]),
        name=str(row["name"]),
        target_amount=int(row["target_amount"]),
        current_amount=int(row["current_amount"] or 0),
        target_date=row.get("target_date"),
        progress_pct=float(row.get("progress_pct", 0.0)),
        created_at=row["created_at"],
    )


@router.patch("/{goal_id}", response_model=GoalOut)
async def update_goal(
    goal_id: str,
    body: GoalPatchRequest,
    user_id: str = Depends(require_user_id),
) -> GoalOut:
    updates = body.model_dump(exclude_none=True)
    row = await domain_goals.update_goal(user_id=user_id, goal_id=goal_id, updates=updates)
    if row is None:
        raise HTTPException(status_code=404, detail="Meta no encontrada")
    return GoalOut(
        id=str(row["id"]),
        name=str(row["name"]),
        target_amount=int(row["target_amount"]),
        current_amount=int(row["current_amount"] or 0),
        target_date=row.get("target_date"),
        progress_pct=float(row.get("progress_pct", 0.0)),
        created_at=row["created_at"],
    )


@router.delete("/{goal_id}", status_code=204)
async def delete_goal(
    goal_id: str,
    user_id: str = Depends(require_user_id),
) -> None:
    deleted = await domain_goals.delete_goal(user_id=user_id, goal_id=goal_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Meta no encontrada")
    logger.info("goal_deleted", goal_id=goal_id)
