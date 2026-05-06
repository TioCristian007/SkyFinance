"""Tests de sky.domain.finance — cálculos puros."""

from sky.domain.finance import (
    CATEGORY_LABELS,
    FinancialSummary,
    compute_savings_rate,
    compute_summary,
    top_categories,
)


class TestComputeSavingsRate:
    def test_zero_income_returns_zero(self) -> None:
        assert compute_savings_rate(0, 50000) == 0.0

    def test_negative_income_returns_zero(self) -> None:
        assert compute_savings_rate(-1000, 0) == 0.0

    def test_expenses_greater_than_income_clamped(self) -> None:
        assert compute_savings_rate(100_000, 200_000) == 0.0

    def test_typical_savings(self) -> None:
        rate = compute_savings_rate(1_000_000, 700_000)
        assert abs(rate - 0.3) < 1e-9

    def test_full_savings_no_expenses(self) -> None:
        assert compute_savings_rate(500_000, 0) == 1.0


class TestComputeSummary:
    def test_empty_transactions(self) -> None:
        s = compute_summary([])
        assert s.income == 0
        assert s.expenses == 0
        assert s.balance == 0
        assert s.savings_rate == 0.0
        assert s.by_category == {}
        assert s.net_flow == 0

    def test_income_only(self) -> None:
        txs = [{"amount": 800_000, "category": "income"}]
        s = compute_summary(txs)
        assert s.income == 800_000
        assert s.expenses == 0
        assert s.balance == 800_000

    def test_expenses_only(self) -> None:
        txs = [
            {"amount": -10_000, "category": "food"},
            {"amount": -5_000,  "category": "transport"},
        ]
        s = compute_summary(txs)
        assert s.income == 0
        assert s.expenses == 15_000
        assert s.balance == -15_000
        assert s.by_category == {"food": 10_000, "transport": 5_000}

    def test_income_category_excluded_from_expenses(self) -> None:
        txs = [
            {"amount": -50_000, "category": "income"},  # category="income" → excluded
            {"amount": -10_000, "category": "food"},
        ]
        s = compute_summary(txs)
        # paridad con financeService.js: category="income" nunca suma a expenses
        assert s.expenses == 10_000
        assert "income" not in s.by_category
        assert s.by_category["food"] == 10_000

    def test_savings_rate_computed(self) -> None:
        txs = [
            {"amount": 1_000_000, "category": "income"},
            {"amount": -600_000,  "category": "food"},
        ]
        s = compute_summary(txs)
        assert abs(s.savings_rate - 0.4) < 1e-9

    def test_zero_amount_ignored(self) -> None:
        txs = [{"amount": 0, "category": "food"}]
        s = compute_summary(txs)
        assert s.income == 0
        assert s.expenses == 0

    def test_net_flow_matches_balance(self) -> None:
        txs = [
            {"amount": 500_000, "category": "income"},
            {"amount": -200_000, "category": "shopping"},
        ]
        s = compute_summary(txs)
        assert s.net_flow == s.balance == 300_000

    def test_by_category_accumulates(self) -> None:
        txs = [
            {"amount": -5_000, "category": "food"},
            {"amount": -8_000, "category": "food"},
            {"amount": -3_000, "category": "transport"},
        ]
        s = compute_summary(txs)
        assert s.by_category["food"] == 13_000
        assert s.by_category["transport"] == 3_000

    def test_period_days_ignored_in_pure_calculation(self) -> None:
        txs = [{"amount": -1_000, "category": "food"}]
        s30 = compute_summary(txs, period_days=30)
        s60 = compute_summary(txs, period_days=60)
        assert s30.expenses == s60.expenses

    def test_returns_financial_summary_dataclass(self) -> None:
        s = compute_summary([])
        assert isinstance(s, FinancialSummary)


class TestTopCategories:
    def test_empty_returns_empty(self) -> None:
        assert top_categories({}) == []

    def test_sorted_by_amount_desc(self) -> None:
        by_cat = {"food": 100_000, "transport": 50_000, "shopping": 200_000}
        result = top_categories(by_cat)
        amounts = [r["amount"] for r in result]
        assert amounts == sorted(amounts, reverse=True)

    def test_limit_respected(self) -> None:
        by_cat = {f"cat_{i}": i * 1000 for i in range(10)}
        result = top_categories(by_cat, limit=3)
        assert len(result) == 3

    def test_percentage_sums_to_100(self) -> None:
        by_cat = {"food": 300_000, "transport": 200_000, "other": 500_000}
        result = top_categories(by_cat)
        total_pct = sum(r["percentage"] for r in result)
        assert abs(total_pct - 100.0) < 0.2  # rounding tolerance

    def test_label_lookup(self) -> None:
        by_cat = {"food": 10_000}
        result = top_categories(by_cat)
        assert result[0]["label"] == CATEGORY_LABELS["food"]

    def test_unknown_category_uses_key_as_label(self) -> None:
        by_cat = {"custom_cat": 5_000}
        result = top_categories(by_cat)
        assert result[0]["label"] == "custom_cat"

    def test_result_fields(self) -> None:
        by_cat = {"food": 50_000}
        r = top_categories(by_cat)[0]
        assert set(r.keys()) == {"category", "label", "amount", "percentage"}
