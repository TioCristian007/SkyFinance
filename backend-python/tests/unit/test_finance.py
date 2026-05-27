"""Tests de sky.domain.finance — cálculos puros."""

from sky.domain.finance import (
    CATEGORY_LABELS,
    NON_CONSUMPTION,
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


class TestNonConsumptionExclusion:
    """Transfer/savings/debt_payment excluidos de expenses pero cuentan en net_flow."""

    def test_non_consumption_constant_contains_expected_keys(self) -> None:
        assert {"transfer", "savings", "debt_payment"} == NON_CONSUMPTION

    def test_transfer_excluded_from_expenses_and_by_category(self) -> None:
        txs = [{"amount": -30_000, "category": "transfer"}]
        s = compute_summary(txs)
        assert s.expenses == 0
        assert "transfer" not in s.by_category

    def test_savings_excluded_from_expenses_and_by_category(self) -> None:
        txs = [{"amount": -20_000, "category": "savings"}]
        s = compute_summary(txs)
        assert s.expenses == 0
        assert "savings" not in s.by_category

    def test_debt_payment_excluded_from_expenses_and_by_category(self) -> None:
        txs = [{"amount": -15_000, "category": "debt_payment"}]
        s = compute_summary(txs)
        assert s.expenses == 0
        assert "debt_payment" not in s.by_category

    def test_non_consumption_counted_in_net_flow_and_balance(self) -> None:
        txs = [
            {"amount": 1_000_000, "category": "income"},
            {"amount": -200_000,  "category": "food"},
            {"amount": -100_000,  "category": "transfer"},
            {"amount":  -50_000,  "category": "savings"},
            {"amount":  -50_000,  "category": "debt_payment"},
        ]
        s = compute_summary(txs)
        # expenses solo cuenta consumo (food)
        assert s.expenses == 200_000
        assert set(s.by_category.keys()) == {"food"}
        # net_flow y balance cuentan TODOS los egresos
        total_out = 200_000 + 100_000 + 50_000 + 50_000
        assert s.net_flow == 1_000_000 - total_out
        assert s.balance  == 1_000_000 - total_out
        # savings_rate basada en expenses (consumo), complementaria a spending_rate
        assert abs(s.savings_rate - (1_000_000 - 200_000) / 1_000_000) < 1e-9

    def test_consumption_categories_unaffected(self) -> None:
        txs = [
            {"amount": 500_000, "category": "income"},
            {"amount": -80_000, "category": "food"},
            {"amount": -40_000, "category": "transport"},
        ]
        s = compute_summary(txs)
        assert s.expenses == 120_000
        assert s.by_category == {"food": 80_000, "transport": 40_000}
        assert s.net_flow == 380_000
        assert s.balance  == 380_000


class TestIncomeRealLogic:
    """Comportamiento de ingresos según el flag count_transfers_as_income."""

    def test_positive_transfer_not_counted_when_flag_off(self) -> None:
        txs = [{"amount": 500_000, "category": "transfer"}]
        s = compute_summary(txs, count_transfers_as_income=False)
        assert s.income == 0
        assert s.net_flow == 0
        assert s.balance == 0

    def test_positive_transfer_counted_when_flag_on(self) -> None:
        txs = [{"amount": 500_000, "category": "transfer"}]
        s = compute_summary(txs, count_transfers_as_income=True)
        assert s.income == 500_000
        assert s.net_flow == 500_000
        assert s.balance == 500_000

    def test_positive_transfer_counted_by_default(self) -> None:
        txs = [{"amount": 300_000, "category": "transfer"}]
        s = compute_summary(txs)
        assert s.income == 300_000

    def test_transfer_and_income_both_count_when_flag_on(self) -> None:
        txs = [
            {"amount": 300_000, "category": "transfer"},
            {"amount": 1_000_000, "category": "income"},
        ]
        s = compute_summary(txs, count_transfers_as_income=True)
        assert s.income == 1_300_000
        assert s.net_flow == 1_300_000

    def test_transfer_excluded_from_income_flag_off(self) -> None:
        txs = [
            {"amount": 300_000, "category": "transfer"},
            {"amount": 1_000_000, "category": "income"},
        ]
        s = compute_summary(txs, count_transfers_as_income=False)
        assert s.income == 1_000_000
        assert s.net_flow == 1_000_000

    def test_negative_transfer_unaffected_by_flag(self) -> None:
        """Las transferencias salientes siguen excluidas de expenses sin importar el flag."""
        txs = [
            {"amount": -200_000, "category": "transfer"},
        ]
        s_on  = compute_summary(txs, count_transfers_as_income=True)
        s_off = compute_summary(txs, count_transfers_as_income=False)
        assert s_on.expenses  == 0
        assert s_off.expenses == 0
        assert s_on.net_flow  == -200_000
        assert s_off.net_flow == -200_000

    def test_savings_rate_uses_expenses_not_total_outflow(self) -> None:
        """savings_rate es complementaria a spending_rate (misma base: expenses)."""
        txs = [
            {"amount": 1_000_000, "category": "income"},
            {"amount": -300_000,  "category": "food"},
            {"amount": -200_000,  "category": "transfer"},
        ]
        # Con flag ON: income sigue siendo 1M (la transfer saliente no afecta income)
        s = compute_summary(txs, count_transfers_as_income=True)
        assert s.expenses == 300_000
        # savings_rate = (income - expenses) / income = (1M - 300k) / 1M = 0.7
        assert abs(s.savings_rate - 0.7) < 1e-9

    def test_savings_and_spending_rates_are_complementary(self) -> None:
        from sky.domain.finance import compute_savings_rate
        income = 1_000_000
        expenses = 400_000
        sr = compute_savings_rate(income, expenses)
        sp = expenses / income
        assert abs(sr + sp - 1.0) < 1e-9


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
