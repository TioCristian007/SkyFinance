"""sky.api.schemas.profile_aria — Schema interno del perfil cualitativo.

No expuesto en ningún endpoint público. Solo usado internamente por
mr_money.py y financial_profile.py. El usuario no ve este schema.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class FinancialProfile(BaseModel):
    savings_mindset:           Literal["saver", "spender", "avoider", "balanced"] | None = None
    savings_mindset_conf:      float | None = None
    risk_tolerance:            int | None = None
    risk_tolerance_conf:       float | None = None
    financial_volatility:      int | None = None
    financial_volatility_conf: float | None = None
    goal_orientation:          Literal["short_term", "long_term", "mixed"] | None = None
    goal_orientation_conf:     float | None = None
    stress_baseline:           int | None = None
    stress_current:            int | None = None
    emotional_volatility:      int | None = None
    last_emotion:              str | None = None
    last_emotion_at:           datetime | None = None
    motivation_primary: (
        Literal["security", "family", "experience", "freedom", "status"] | None
    ) = None
    motivation_primary_conf:   float | None = None
    recurring_blockers:        list[Any] | None = None
    protective_behaviors:      list[Any] | None = None
    updates_count:             int = 0
