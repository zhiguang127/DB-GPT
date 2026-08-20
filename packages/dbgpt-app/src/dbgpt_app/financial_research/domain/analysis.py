"""Deterministic domain calculations for financial research."""

from collections import defaultdict
from typing import Any, Dict, Iterable, List

from .models import FinancialMetric, MetricUnit
from .periods import (
    period_display_name,
    period_sort_key,
    previous_comparable_period,
)


def _growth(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * 100


def _analyze_company(
    company: str, metrics: Iterable[FinancialMetric]
) -> Dict[str, Any]:
    metric_list = list(metrics)
    grouped = defaultdict(list)
    for metric in metric_list:
        grouped[metric.name].append(metric)

    growth: Dict[str, float | None] = {}
    comparisons: Dict[str, Dict[str, Any]] = {}
    insights: List[str] = []
    for name, items in grouped.items():
        ordered = sorted(
            items, key=lambda item: period_sort_key(item.period), reverse=True
        )
        if len(ordered) < 2:
            continue
        current = ordered[0]
        comparable = previous_comparable_period(current.period)
        previous = next(
            (item for item in ordered[1:] if item.period == comparable), None
        )
        if previous is None:
            continue
        value: float | None
        if current.unit == MetricUnit.PERCENT:
            value = current.value - previous.value
            comparisons[name] = {"value": value, "unit": "percentage_point"}
        else:
            value = _growth(current.value, previous.value)
            comparisons[name] = {"value": value, "unit": "percent"}
        growth[name] = value
        if value is not None and name in {
            "revenue",
            "net_profit",
            "non_recurring_net_profit",
            "operating_cash_flow",
            "net_margin",
        }:
            direction = "增长" if value >= 0 else "下降"
            change_unit = " 个百分点" if current.unit == MetricUnit.PERCENT else "%"
            insights.append(
                f"{company}的{current.display_name}由 "
                f"{period_display_name(previous.period)}的 "
                f"{previous.value:,.2f} 变为 "
                f"{period_display_name(current.period)}的 "
                f"{current.value:,.2f}，同比{direction} {abs(value):.2f}"
                f"{change_unit}。"
            )

    risks: List[str] = []
    revenue_growth = growth.get("revenue")
    profit_growth = growth.get("net_profit")
    cash_growth = growth.get("operating_cash_flow")
    margin_change = growth.get("net_margin")
    if profit_growth is not None and revenue_growth is not None:
        if profit_growth < revenue_growth - 5:
            risks.append(
                f"{company}的利润增速显著弱于收入增速，需关注成本、费用或资产减值压力。"
            )
    if cash_growth is not None and cash_growth < -20:
        risks.append(
            f"{company}的经营现金流同比降幅超过 20%，"
            "需结合应收账款和营运资本进一步核验。"
        )
    if margin_change is not None and margin_change < -2:
        risks.append(f"{company}的净利率下降超过 2 个百分点，盈利质量出现弱化信号。")
    if not risks:
        risks.append(
            f"{company}当前仅完成核心财务指标核验，业务分部、行业环境和重大事项仍需补充资料。"
        )

    return {
        "growth_pct": growth,
        "comparisons": comparisons,
        "insights": insights,
        "risks": risks,
        "periods": sorted(
            {item.period for item in metric_list}, key=period_sort_key, reverse=True
        ),
    }


def _peer_comparison(metrics: List[FinancialMetric]) -> Dict[str, Any]:
    companies_by_period = defaultdict(set)
    for metric in metrics:
        if metric.dimensions:
            continue
        companies_by_period[metric.period].add(metric.company_name)
    comparable_periods = [
        period
        for period, companies in companies_by_period.items()
        if len(companies) > 1
    ]
    if not comparable_periods:
        return {"period": None, "metrics": {}, "insights": []}

    period = max(comparable_periods, key=period_sort_key)
    compared = defaultdict(list)
    for metric in metrics:
        if metric.dimensions:
            continue
        if metric.period == period:
            compared[metric.name].append(metric)

    metric_results: Dict[str, List[Dict[str, Any]]] = {}
    insights: List[str] = []
    for name, items in compared.items():
        ranked = sorted(items, key=lambda item: item.value, reverse=True)
        metric_results[name] = [
            {
                "company": item.company_name,
                "display_name": item.display_name,
                "value": item.value,
                "unit": item.unit.value,
                "currency": item.currency,
                "rank": rank,
            }
            for rank, item in enumerate(ranked, start=1)
        ]
        if name in {
            "revenue",
            "net_profit",
            "operating_cash_flow",
            "weighted_roe",
            "net_margin",
        }:
            leader = ranked[0]
            insights.append(
                f"{period_display_name(period)}{leader.display_name}最高的是"
                f"{leader.company_name}，"
                f"披露值为 {leader.value:,.2f} {leader.unit.value}。"
            )
    return {"period": period, "metrics": metric_results, "insights": insights}


def analyze_metrics(metrics: Iterable[FinancialMetric]) -> Dict[str, Any]:
    metric_list = list(metrics)
    by_company = defaultdict(list)
    for metric in metric_list:
        by_company[metric.company_name].append(metric)

    company_analysis = {
        company: _analyze_company(company, items)
        for company, items in sorted(by_company.items())
    }
    companies = list(company_analysis)
    peer_comparison = _peer_comparison(metric_list)
    insights = [
        insight
        for result in company_analysis.values()
        for insight in result["insights"]
    ]
    insights.extend(peer_comparison["insights"])
    risks = [risk for result in company_analysis.values() for risk in result["risks"]]

    result: Dict[str, Any] = {
        "mode": "multi_company" if len(companies) > 1 else "single_company",
        "companies": companies,
        "company_analysis": company_analysis,
        "peer_comparison": peer_comparison,
        "insights": insights,
        "risks": risks,
    }
    if len(companies) == 1:
        single = company_analysis[companies[0]]
        result["growth_pct"] = single["growth_pct"]
        result["comparisons"] = single["comparisons"]
    else:
        result["growth_pct"] = {}
        result["comparisons"] = {}
    return result
