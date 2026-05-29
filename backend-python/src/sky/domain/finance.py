"""sky.domain.finance — Cálculos financieros puros."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

NON_CONSUMPTION: frozenset[str] = frozenset({"transfer", "savings", "debt_payment"})

CATEGORY_LABELS: dict[str, str] = {
    "income": "Ingresos",
    "food": "Alimentación",
    "transport": "Transporte",
    "housing": "Vivienda",
    "health": "Salud",
    "entertainment": "Entretención",
    "shopping": "Compras",
    "utilities": "Servicios básicos",
    "subscriptions": "Suscripciones",
    "education": "Educación",
    "travel": "Viajes",
    "banking_fee": "Comisiones bancarias",
    "transfer": "Transferencias",
    "debt_payment": "Pago de deudas",
    "savings": "Ahorro",
    "other": "Otros",
}


@dataclass(frozen=True, slots=True)
class FinancialSummary:
    balance: int
    income: int
    expenses: int
    savings_rate: float
    by_category: dict[str, int]
    net_flow: int


def compute_summary(
    transactions: list[dict[str, Any]],
    *,
    period_days: int = 30,
    count_transfers_as_income: bool = True,
    count_transfers_as_expense: bool = True,
) -> FinancialSummary:
    """
    Calcula summary a partir de lista de transacciones.

    Cada transacción: {"amount": int, "category": str}.
    amount > 0 = ingreso; amount < 0 = gasto.
    Paridad con financeService.js: expenses = sum(abs) donde category != "income".

    count_transfers_as_income=True (default): transferencias entrantes (amount>0,
    category=="transfer") también cuentan como ingreso.

    count_transfers_as_expense=True (default): transferencias salientes (amount<0,
    category=="transfer") cuentan como gasto. savings/debt_payment siguen fuera.
    """
    income = 0
    expenses = 0
    total_outflow = 0
    by_category: dict[str, int] = {}

    for tx in transactions:
        amount = int(tx.get("amount", 0))
        category = str(tx.get("category", "other"))

        is_income_tx = amount > 0 and (
            category != "transfer" or count_transfers_as_income
        )

        if is_income_tx:
            income += amount
        elif amount < 0:
            abs_amount = abs(amount)
            if category != "income":
                total_outflow += abs_amount
                counts_as_expense = (
                    category not in NON_CONSUMPTION
                    or (count_transfers_as_expense and category == "transfer")
                )
                if counts_as_expense:
                    expenses += abs_amount
                    by_category[category] = by_category.get(category, 0) + abs_amount

    return FinancialSummary(
        balance=income - total_outflow,
        income=income,
        expenses=expenses,
        savings_rate=compute_savings_rate(income, expenses),
        by_category=by_category,
        net_flow=income - total_outflow,
    )


def compute_savings_rate(income: int, expenses: int) -> float:
    if income <= 0:
        return 0.0
    return max(0.0, (income - expenses) / income)


def top_categories(
    by_category: dict[str, int],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Devuelve las top-N categorías de gasto ordenadas por monto descendente."""
    total = sum(by_category.values()) or 1
    return [
        {
            "category": cat,
            "label": CATEGORY_LABELS.get(cat, cat),
            "amount": amount,
            "percentage": round(amount / total * 100, 1),
        }
        for cat, amount in sorted(
            by_category.items(), key=lambda x: x[1], reverse=True
        )[:limit]
    ]
