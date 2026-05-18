"""sky.api.routers.goals — CRUD de metas financieras."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from sky.api.deps import require_user_id
from sky.api.schemas.goals import GoalCreateRequest, GoalPatchRequest
from sky.core.logging import get_logger
from sky.domain import goals as domain_goals

logger = get_logger("api.goals")
router = APIRouter(prefix="/api/goals", tags=["goals"])


def _goal_to_camel(row: dict[str, Any]) -> dict[str, Any]:
    """Convierte un dict de dominio al shape camelCase que espera el frontend.

    Paridad con Node financeService.getGoals() / editGoal() que devuelven
    { title, targetAmount, savedAmount, deadline, projection: {pct, ...} }.
    """
    current = int(row.get("current_amount") or 0)
    target = int(row.get("target_amount") or 1)
    proj = row.get("projection") or {}
    return {
        "id":           str(row["id"]),
        "title":        str(row.get("name") or row.get("title") or ""),
        "targetAmount": target,
        "savedAmount":  current,
        "deadline":     str(row["target_date"]) if row.get("target_date") else None,
        "projection": {
            "pct":          int(proj.get("pct", row.get("progress_pct", 0))),
            "remaining":    int(proj.get("remaining", max(0, target - current))),
            "monthsToGoal": proj.get("months_to_goal"),
            "projectedDate": proj.get("projected_date"),
        },
        "created_at": str(row["created_at"]) if row.get("created_at") else None,
    }


@router.get("")
async def list_goals(
    user_id: str = Depends(require_user_id),
) -> dict[str, Any]:
    """Lista metas del usuario en shape camelCase compatible con Node."""
    rows = await domain_goals.get_goals(user_id)
    return {"goals": [_goal_to_camel(r) for r in rows]}


@router.post("", status_code=201)
async def create_goal(
    body: GoalCreateRequest,
    user_id: str = Depends(require_user_id),
) -> dict[str, Any]:
    """Crea meta. Acepta title/targetAmount/deadline (frontend) o name/target_amount (interno)."""
    name = getattr(body, "title", None) or body.name
    target = getattr(body, "targetAmount", None) or body.target_amount
    deadline = getattr(body, "deadline", None) or body.target_date
    row = await domain_goals.create_goal(
        user_id=user_id,
        name=name,
        target_amount=target,
        target_date=deadline,
    )
    return {"goal": _goal_to_camel(row)}


@router.patch("/{goal_id}")
async def update_goal(
    goal_id: str,
    body: GoalPatchRequest,
    user_id: str = Depends(require_user_id),
) -> dict[str, Any]:
    updates = body.model_dump(exclude_none=True)
    row = await domain_goals.update_goal(user_id=user_id, goal_id=goal_id, updates=updates)
    if row is None:
        raise HTTPException(status_code=404, detail="Meta no encontrada")
    return {"goal": _goal_to_camel(row)}


@router.delete("/{goal_id}", status_code=204)
async def delete_goal(
    goal_id: str,
    user_id: str = Depends(require_user_id),
) -> None:
    deleted = await domain_goals.delete_goal(user_id=user_id, goal_id=goal_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Meta no encontrada")
    logger.info("goal_deleted", goal_id=goal_id)
