"""sky.domain.simulations — Proyecciones financieras con compound interest."""
from __future__ import annotations

from sky.api.schemas.simulate import ProjectionPoint, ProjectionResponse

_MAX_MONTHS = 60


def compute_projection(
    target_amount: int,
    monthly_savings: int,
    current_savings: int = 0,
    annual_return_pct: float = 0.0,
) -> ProjectionResponse:
    """
    Proyecta acumulación mensual con interés compuesto opcional.

    annual_return_pct=0 → sin rendimiento (puro ahorro).
    annual_return_pct=5 → 5% anual nominal mensualizado.
    Max 60 meses de proyección.
    """
    if current_savings >= target_amount:
        return ProjectionResponse(
            months_to_goal=0,
            final_amount=current_savings,
            points=[ProjectionPoint(month=0, accumulated=current_savings)],
            feasible=True,
            rationale="Ya alcanzaste tu meta con tus ahorros actuales.",
        )

    monthly_rate = (annual_return_pct / 100) / 12
    accumulated = float(current_savings)
    points: list[ProjectionPoint] = []
    months_to_goal: int | None = None

    for month in range(1, _MAX_MONTHS + 1):
        if monthly_rate > 0:
            accumulated = accumulated * (1 + monthly_rate) + monthly_savings
        else:
            accumulated += monthly_savings

        acc_int = int(accumulated)
        points.append(ProjectionPoint(month=month, accumulated=acc_int))

        if months_to_goal is None and acc_int >= target_amount:
            months_to_goal = month

    final_amount = int(accumulated)
    feasible = months_to_goal is not None

    if feasible:
        interest_note = (
            f" (con {annual_return_pct:.1f}% anual)"
            if annual_return_pct > 0
            else ""
        )
        rationale = (
            f"Con ahorro de ${monthly_savings:,}/mes{interest_note} "
            f"alcanzarías tu meta en {months_to_goal} meses."
        )
    elif monthly_savings == 0:
        rationale = "Con ahorro mensual cero no es posible alcanzar la meta en 60 meses."
    else:
        shortfall = target_amount - final_amount
        rationale = (
            f"Con ${monthly_savings:,}/mes llegarías a ${final_amount:,} "
            f"en {_MAX_MONTHS} meses, ${shortfall:,} bajo la meta."
        )

    return ProjectionResponse(
        months_to_goal=months_to_goal,
        final_amount=final_amount,
        points=points,
        feasible=feasible,
        rationale=rationale,
    )
