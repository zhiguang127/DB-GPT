"""Versioned, deterministic financial formulas with complete input lineage."""

import hashlib
from collections import defaultdict
from typing import Iterable, List, Sequence, Tuple

from .models import (
    MONEY_UNITS,
    Computation,
    ConsolidationScope,
    FinancialMetric,
    MetricUnit,
    StatementType,
)
from .periods import previous_comparable_period

FORMULA_VERSION = "1.0"


def _evidence_ids(*metrics: FinancialMetric) -> List[str]:
    return list(
        dict.fromkeys(
            evidence_id for metric in metrics for evidence_id in metric.evidence_ids
        )
    )


def _program_hash(formula_id: str, expression: str) -> str:
    payload = f"{formula_id}|{FORMULA_VERSION}|{expression}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _safe_divide(numerator: float, denominator: float) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _input_currency(inputs: Sequence[FinancialMetric]) -> str | None:
    """The single currency shared by every monetary input, else ``None``."""

    currencies = {
        metric.currency
        for metric in inputs
        if metric.unit in MONEY_UNITS and metric.currency
    }
    if len(currencies) == 1:
        return next(iter(currencies))
    return None


def _currencies_are_comparable(inputs: Sequence[FinancialMetric]) -> bool:
    """Reject formulas that would add or divide across different currencies.

    A ratio between two amounts in different currencies is meaningless without
    an exchange rate, and the pipeline deliberately holds no rate source.
    """
    currencies = {
        metric.currency
        for metric in inputs
        if metric.unit in MONEY_UNITS and metric.currency
    }
    return len(currencies) <= 1


def _metric_and_computation(
    *,
    name: str,
    display_name: str,
    value: float,
    unit: MetricUnit,
    inputs: Sequence[FinancialMetric],
    expression: str,
) -> tuple[FinancialMetric, Computation]:
    anchor = inputs[0]
    metric = FinancialMetric(
        document_id=anchor.document_id,
        company_name=anchor.company_name,
        period=anchor.period,
        name=name,
        display_name=display_name,
        value=value,
        raw_value=None,
        unit=unit,
        currency=_input_currency(inputs) if unit in MONEY_UNITS else None,
        scope=anchor.scope,
        period_type=anchor.period_type,
        statement_type=StatementType.COMPUTED,
        row_label=None,
        confidence=min(item.confidence for item in inputs),
        evidence_ids=_evidence_ids(*inputs),
        is_reported=False,
    )
    computation = Computation(
        metric_id=metric.id,
        formula_id=name,
        formula_version=FORMULA_VERSION,
        expression=expression,
        input_metric_ids=[item.id for item in inputs],
        result=value,
        program_hash=_program_hash(name, expression),
    )
    return metric, computation


def derive_metrics_with_lineage(
    metrics: Iterable[FinancialMetric],
) -> Tuple[List[FinancialMetric], List[Computation]]:
    """Calculate only formulas whose complete input set is present."""

    metric_list = list(metrics)
    grouped: dict[tuple[str, str, ConsolidationScope], dict[str, FinancialMetric]] = (
        defaultdict(dict)
    )
    by_series: dict[tuple[str, ConsolidationScope, str], dict[str, FinancialMetric]] = (
        defaultdict(dict)
    )
    for metric in metric_list:
        if metric.dimensions:
            continue
        grouped[(metric.company_name, metric.period, metric.scope)][metric.name] = (
            metric
        )
        by_series[(metric.company_name, metric.scope, metric.name)][metric.period] = (
            metric
        )

    derived: List[FinancialMetric] = []
    computations: List[Computation] = []
    existing = {
        (metric.company_name, metric.period, metric.scope, metric.name)
        for metric in metric_list
    }

    def add(
        name: str,
        display_name: str,
        value: float | None,
        unit: MetricUnit,
        inputs: Sequence[FinancialMetric],
        expression: str,
    ) -> None:
        if value is None or not inputs:
            return
        if not _currencies_are_comparable(inputs):
            return
        anchor = inputs[0]
        identity = (anchor.company_name, anchor.period, anchor.scope, name)
        if identity in existing:
            return
        metric, computation = _metric_and_computation(
            name=name,
            display_name=display_name,
            value=value,
            unit=unit,
            inputs=inputs,
            expression=expression,
        )
        derived.append(metric)
        computations.append(computation)
        existing.add(identity)

    for (company, period, scope), values in grouped.items():
        del company, scope
        revenue = values.get("revenue")
        operating_cost = values.get("operating_cost")
        net_profit = values.get("net_profit") or values.get("net_profit_total")
        adjusted_net_profit = values.get("non_recurring_net_profit")
        cash_flow = values.get("operating_cash_flow")
        current_assets = values.get("current_assets")
        current_liabilities = values.get("current_liabilities")
        inventory = values.get("inventory")
        cash = values.get("cash")
        total_assets = values.get("total_assets")
        total_liabilities = values.get("total_liabilities")
        total_equity = values.get("total_equity") or values.get("shareholder_equity")
        interest_expense = values.get("interest_expense")
        total_profit = values.get("total_profit")
        capex = values.get("cash_paid_for_long_term_assets")

        if revenue and operating_cost:
            gross_profit = revenue.value - operating_cost.value
            add(
                "gross_profit",
                "毛利润",
                gross_profit,
                MetricUnit.MONEY,
                (revenue, operating_cost),
                "revenue - operating_cost",
            )
            ratio = _safe_divide(gross_profit, revenue.value)
            add(
                "gross_margin",
                "毛利率",
                ratio * 100 if ratio is not None else None,
                MetricUnit.PERCENT,
                (revenue, operating_cost),
                "(revenue - operating_cost) / revenue * 100",
            )
        if revenue and net_profit:
            ratio = _safe_divide(net_profit.value, revenue.value)
            add(
                "net_margin",
                "净利率",
                ratio * 100 if ratio is not None else None,
                MetricUnit.PERCENT,
                (net_profit, revenue),
                "net_profit / revenue * 100",
            )
        if net_profit and adjusted_net_profit:
            non_recurring_effect = net_profit.value - adjusted_net_profit.value
            add(
                "non_recurring_net_effect",
                "非经常性损益净影响（推算）",
                non_recurring_effect,
                MetricUnit.MONEY,
                (net_profit, adjusted_net_profit),
                "net_profit - adjusted_net_profit",
            )
            effect_ratio = _safe_divide(non_recurring_effect, net_profit.value)
            add(
                "non_recurring_profit_share",
                "非经常性损益占归母净利润比例",
                effect_ratio * 100 if effect_ratio is not None else None,
                MetricUnit.PERCENT,
                (net_profit, adjusted_net_profit),
                "(net_profit - adjusted_net_profit) / net_profit * 100",
            )
            adjusted_ratio = _safe_divide(adjusted_net_profit.value, net_profit.value)
            add(
                "adjusted_profit_share",
                "扣非净利润占归母净利润比例",
                adjusted_ratio * 100 if adjusted_ratio is not None else None,
                MetricUnit.PERCENT,
                (adjusted_net_profit, net_profit),
                "adjusted_net_profit / net_profit * 100",
            )
        if cash_flow and net_profit:
            add(
                "cash_profit_ratio",
                "现金利润比",
                _safe_divide(cash_flow.value, net_profit.value),
                MetricUnit.RATIO,
                (cash_flow, net_profit),
                "operating_cash_flow / net_profit",
            )
        if cash_flow and revenue:
            ratio = _safe_divide(cash_flow.value, revenue.value)
            add(
                "operating_cash_flow_margin",
                "经营现金流率",
                ratio * 100 if ratio is not None else None,
                MetricUnit.PERCENT,
                (cash_flow, revenue),
                "operating_cash_flow / revenue * 100",
            )
        if cash_flow and capex:
            add(
                "free_cash_flow",
                "自由现金流（近似）",
                cash_flow.value - capex.value,
                MetricUnit.MONEY,
                (cash_flow, capex),
                "operating_cash_flow - cash_paid_for_long_term_assets",
            )
        if current_assets and current_liabilities:
            add(
                "working_capital",
                "营运资本",
                current_assets.value - current_liabilities.value,
                MetricUnit.MONEY,
                (current_assets, current_liabilities),
                "current_assets - current_liabilities",
            )
            add(
                "current_ratio",
                "流动比率",
                _safe_divide(current_assets.value, current_liabilities.value),
                MetricUnit.RATIO,
                (current_assets, current_liabilities),
                "current_assets / current_liabilities",
            )
            if inventory:
                add(
                    "quick_ratio",
                    "速动比率",
                    _safe_divide(
                        current_assets.value - inventory.value,
                        current_liabilities.value,
                    ),
                    MetricUnit.RATIO,
                    (current_assets, inventory, current_liabilities),
                    "(current_assets - inventory) / current_liabilities",
                )
            if cash:
                add(
                    "cash_ratio",
                    "现金比率",
                    _safe_divide(cash.value, current_liabilities.value),
                    MetricUnit.RATIO,
                    (cash, current_liabilities),
                    "cash / current_liabilities",
                )
        if total_liabilities and total_assets:
            ratio = _safe_divide(total_liabilities.value, total_assets.value)
            add(
                "debt_asset_ratio",
                "资产负债率",
                ratio * 100 if ratio is not None else None,
                MetricUnit.PERCENT,
                (total_liabilities, total_assets),
                "total_liabilities / total_assets * 100",
            )
        if total_assets and total_equity:
            add(
                "equity_multiplier",
                "权益乘数",
                _safe_divide(total_assets.value, total_equity.value),
                MetricUnit.RATIO,
                (total_assets, total_equity),
                "total_assets / total_equity",
            )
        if total_profit and interest_expense:
            add(
                "interest_coverage",
                "利息保障倍数",
                _safe_divide(
                    total_profit.value + interest_expense.value,
                    interest_expense.value,
                ),
                MetricUnit.RATIO,
                (total_profit, interest_expense),
                "(total_profit + interest_expense) / interest_expense",
            )

        for expense_name, result_name, display_name in (
            ("selling_expenses", "selling_expense_ratio", "销售费用率"),
            ("administrative_expenses", "administrative_expense_ratio", "管理费用率"),
            (
                "research_and_development_expenses",
                "research_expense_ratio",
                "研发费用率",
            ),
            ("finance_expenses", "finance_expense_ratio", "财务费用率"),
        ):
            expense = values.get(expense_name)
            if revenue and expense:
                ratio = _safe_divide(expense.value, revenue.value)
                add(
                    result_name,
                    display_name,
                    ratio * 100 if ratio is not None else None,
                    MetricUnit.PERCENT,
                    (expense, revenue),
                    f"{expense_name} / revenue * 100",
                )

        short_debt = values.get("short_term_borrowings")
        long_debt = values.get("long_term_borrowings")
        debt_inputs = [item for item in (short_debt, long_debt) if item]
        if debt_inputs and cash:
            add(
                "net_debt",
                "净债务",
                sum(item.value for item in debt_inputs) - cash.value,
                MetricUnit.MONEY,
                (*debt_inputs, cash),
                "short_term_borrowings + long_term_borrowings - cash",
            )

        # Averages must span the same interval a year earlier, so an interim
        # period resolves to the prior-year interim rather than a full year.
        previous_period = previous_comparable_period(period)
        if previous_period:
            for denominator_name, output_name, display_name, numerator, expression in (
                (
                    "total_assets",
                    "asset_turnover",
                    "总资产周转率",
                    revenue,
                    "revenue / average(total_assets)",
                ),
                (
                    "accounts_receivable",
                    "accounts_receivable_turnover",
                    "应收账款周转率",
                    revenue,
                    "revenue / average(accounts_receivable)",
                ),
                (
                    "inventory",
                    "inventory_turnover",
                    "存货周转率",
                    operating_cost,
                    "operating_cost / average(inventory)",
                ),
            ):
                current_denominator = values.get(denominator_name)
                previous_denominator = (
                    by_series[
                        (
                            current_denominator.company_name,
                            current_denominator.scope,
                            denominator_name,
                        )
                    ].get(previous_period)
                    if current_denominator
                    else None
                )
                if numerator and current_denominator and previous_denominator:
                    average = (
                        current_denominator.value + previous_denominator.value
                    ) / 2
                    add(
                        output_name,
                        display_name,
                        _safe_divide(numerator.value, average),
                        MetricUnit.RATIO,
                        (numerator, current_denominator, previous_denominator),
                        expression,
                    )
            previous_assets = (
                by_series[
                    (total_assets.company_name, total_assets.scope, "total_assets")
                ].get(previous_period)
                if total_assets
                else None
            )
            if net_profit and total_assets and previous_assets:
                average_assets = (total_assets.value + previous_assets.value) / 2
                roa = _safe_divide(net_profit.value, average_assets)
                add(
                    "return_on_assets",
                    "总资产收益率",
                    roa * 100 if roa is not None else None,
                    MetricUnit.PERCENT,
                    (net_profit, total_assets, previous_assets),
                    "net_profit / average(total_assets) * 100",
                )
            if net_profit and cash_flow and total_assets and previous_assets:
                average_assets = (total_assets.value + previous_assets.value) / 2
                accrual = _safe_divide(
                    net_profit.value - cash_flow.value, average_assets
                )
                add(
                    "accrual_ratio",
                    "应计比率",
                    accrual * 100 if accrual is not None else None,
                    MetricUnit.PERCENT,
                    (net_profit, cash_flow, total_assets, previous_assets),
                    "(net_profit - operating_cash_flow) / average(total_assets) * 100",
                )

    return derived, computations


def derive_metrics(metrics: Iterable[FinancialMetric]) -> List[FinancialMetric]:
    """Compatibility facade returning derived facts without computation records."""

    return derive_metrics_with_lineage(metrics)[0]
