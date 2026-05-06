"""Tests de sky.domain.simulations — compute_projection (pure)."""
from sky.domain.simulations import compute_projection


class TestComputeProjection:
    def test_already_reached_returns_month_zero(self) -> None:
        r = compute_projection(
            target_amount=500_000,
            monthly_savings=10_000,
            current_savings=600_000,
        )
        assert r.feasible is True
        assert r.months_to_goal == 0
        assert r.final_amount == 600_000
        assert len(r.points) == 1
        assert r.points[0].month == 0

    def test_feasible_with_enough_savings(self) -> None:
        r = compute_projection(
            target_amount=1_000_000,
            monthly_savings=200_000,
        )
        assert r.feasible is True
        assert r.months_to_goal == 5
        assert r.months_to_goal is not None
        assert r.points[r.months_to_goal - 1].accumulated >= 1_000_000

    def test_not_feasible_insufficient_savings(self) -> None:
        r = compute_projection(
            target_amount=100_000_000,
            monthly_savings=10_000,
        )
        assert r.feasible is False
        assert r.months_to_goal is None
        assert len(r.points) == 60

    def test_zero_monthly_savings_not_feasible(self) -> None:
        r = compute_projection(
            target_amount=500_000,
            monthly_savings=0,
        )
        assert r.feasible is False
        assert r.months_to_goal is None
        assert "cero" in r.rationale

    def test_max_60_points(self) -> None:
        r = compute_projection(
            target_amount=999_000_000,
            monthly_savings=1_000,
        )
        assert len(r.points) == 60

    def test_current_savings_speeds_up_goal(self) -> None:
        r_no_head = compute_projection(
            target_amount=1_000_000, monthly_savings=100_000,
        )
        r_head_start = compute_projection(
            target_amount=1_000_000, monthly_savings=100_000, current_savings=500_000,
        )
        assert r_head_start.months_to_goal is not None
        assert r_no_head.months_to_goal is not None
        assert r_head_start.months_to_goal < r_no_head.months_to_goal

    def test_compound_interest_increases_accumulation(self) -> None:
        r_no_interest = compute_projection(
            target_amount=1_000_000, monthly_savings=50_000,
        )
        r_with_interest = compute_projection(
            target_amount=1_000_000, monthly_savings=50_000, annual_return_pct=5.0,
        )
        assert r_with_interest.months_to_goal is not None
        assert r_no_interest.months_to_goal is not None
        assert r_with_interest.months_to_goal <= r_no_interest.months_to_goal

    def test_points_are_monotonically_increasing(self) -> None:
        r = compute_projection(
            target_amount=5_000_000, monthly_savings=100_000,
        )
        accumulated = [p.accumulated for p in r.points]
        assert accumulated == sorted(accumulated)

    def test_rationale_mentions_months_when_feasible(self) -> None:
        r = compute_projection(
            target_amount=300_000, monthly_savings=100_000,
        )
        assert r.feasible is True
        assert "mes" in r.rationale

    def test_rationale_mentions_shortfall_when_not_feasible(self) -> None:
        r = compute_projection(
            target_amount=100_000_000, monthly_savings=10_000,
        )
        assert "bajo la meta" in r.rationale

    def test_final_amount_equals_last_point(self) -> None:
        r = compute_projection(
            target_amount=99_000_000, monthly_savings=50_000,
        )
        assert r.final_amount == r.points[-1].accumulated
