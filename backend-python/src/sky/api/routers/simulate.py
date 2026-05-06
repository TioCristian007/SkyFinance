"""sky.api.routers.simulate — Proyecciones financieras (compound interest)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from sky.api.deps import require_user_id
from sky.api.schemas.simulate import ProjectionRequest, ProjectionResponse
from sky.domain.simulations import compute_projection

router = APIRouter(prefix="/api/simulate", tags=["simulate"])


@router.post("/projection", response_model=ProjectionResponse)
async def get_projection(
    body: ProjectionRequest,
    user_id: str = Depends(require_user_id),
) -> ProjectionResponse:
    return compute_projection(**body.model_dump())
