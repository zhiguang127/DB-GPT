from copy import deepcopy
from decimal import Decimal

from dbgpt_serve.financial_analysis.calculations import calculate


def facts():
    result = []
    for year in ["2024", "2023"]:
        for metric, value in {
            "revenue": "100.10" if year == "2024" else "80.08",
            "net_profit": "20",
            "non_recurring_net_profit": "15",
            "operating_cash_flow": "10",
            "total_assets": "200",
            "total_liabilities": "50",
        }.items():
            result.append(
                {
                    "id": metric + year,
                    "metricCode": metric,
                    "metricName": metric,
                    "fiscalPeriod": year,
                    "normalizedValue": value,
                    "rawValue": value,
                    "unit": "元",
                    "currency": "CNY",
                    "statementScope": "合并",
                    "extractionStatus": "parsed",
                    "periodType": "instant"
                    if metric in {"total_assets", "total_liabilities"}
                    else "flow",
                    "attribution": "owners_of_parent"
                    if metric in {"net_profit", "non_recurring_net_profit"}
                    else "consolidated",
                    "evidenceExcerptIds": ["E1"],
                    "qualityStatus": "warning",
                }
            )
    return result


def by_code(data):
    return {
        c["code"]: c for c in calculate(data, "2024") if c["fiscalPeriod"] == "2024"
    }


def expanded_facts():
    data = facts()
    values = {
        "cost_of_sales": ("100", "60"),
        "selling_expenses": ("20", "5"),
        "administrative_expenses": ("30", "20"),
        "research_expenses": ("10", "0"),
        "financial_expenses": ("-4", "-3"),
        "current_assets": ("90", "80"),
        "current_liabilities": ("30", "40"),
        "inventory": ("25", "20"),
    }
    for i, year in enumerate(["2024", "2023"]):
        base = next(f for f in data if f["id"] == "revenue" + year)
        base["normalizedValue"] = ("200", "100")[i]
        for code, amounts in values.items():
            data.append(
                dict(
                    base,
                    id=code + year,
                    metricCode=code,
                    metricName=code,
                    normalizedValue=amounts[i],
                    periodType="instant"
                    if code in {"current_assets", "current_liabilities", "inventory"}
                    else "flow",
                )
            )
    return data


def test_rates_compare_unrounded_period_values_in_percentage_points():
    data = expanded_facts()
    result = by_code(data)
    for code, expected in {
        "gross_margin": "50",
        "gross_margin_change": "10",
        "selling_expense_ratio": "10",
        "selling_expense_ratio_change": "5",
        "administrative_expense_ratio_change": "-5",
        "research_expense_ratio_change": "5",
        "financial_expense_ratio": "-2",
        "financial_expense_ratio_change": "1",
        "current_ratio": "3",
    }.items():
        assert Decimal(result[code]["result"]) == Decimal(expected)
        assert result[code]["unit"] == (
            "百分点"
            if code.endswith("_change")
            else "×"
            if code == "current_ratio"
            else "%"
        )
    all_calcs = calculate(data, "2024")
    assert len({c["id"] for c in all_calcs}) == len(all_calcs) == 24
    prior = next(c for c in all_calcs if c["id"] == "calc-gross_margin-2023")
    assert Decimal(prior["result"]) == 40
    assert result["gross_margin_change"]["inputFactIds"] == [
        "cost_of_sales2024",
        "revenue2024",
        "cost_of_sales2023",
        "revenue2023",
    ]


def test_rate_failures_keep_valid_period_and_explain_missing_inputs():
    data = expanded_facts()
    next(f for f in data if f["id"] == "revenue2023")["normalizedValue"] = "0"
    result = by_code(data)
    assert result["gross_margin"]["status"] == "calculated"
    assert result["gross_margin_change"]["reason"] == "zero_denominator"
    current = next(f for f in data if f["id"] == "current_liabilities2024")
    current["periodType"] = "flow"
    assert by_code(data)["current_ratio"]["reason"] == "incompatible_input"
    current["periodType"], current["normalizedValue"] = "instant", "0"
    assert by_code(data)["current_ratio"]["reason"] == "zero_denominator"
    current["normalizedValue"] = None
    assert by_code(data)["current_ratio"]["reason"] == "missing_input"
    next(f for f in data if f["id"] == "financial_expenses2024")["extractionStatus"] = (
        "conflict"
    )
    assert by_code(data)["financial_expense_ratio"]["result"] is None


def test_percentage_point_change_is_not_difference_of_rounded_rates():
    data = expanded_facts()
    for code, amount in {
        "selling_expenses2024": "1",
        "selling_expenses2023": "1",
        "revenue2024": "3",
        "revenue2023": "6",
    }.items():
        next(f for f in data if f["id"] == code)["normalizedValue"] = amount
    result = by_code(data)
    assert result["selling_expense_ratio"]["displayResult"] == "33.33%"
    assert result["selling_expense_ratio_change"]["displayResult"] == "16.67百分点"


def test_exact_formulas_and_trace_references():
    data = facts()
    original = deepcopy(data)
    result = by_code(data)
    expected = {
        "revenue_yoy": "25",
        "nonrecurring_impact": "5",
        "nonrecurring_share": "25",
        "cash_profit_ratio": "0.5",
        "debt_ratio": "25",
    }
    for code, value in expected.items():
        assert Decimal(result[code]["result"]) == Decimal(value)
        assert result[code]["status"] == "calculated"
        assert set(result[code]["inputFactIds"]) <= {f["id"] for f in data}
        assert result[code]["steps"]
    assert data == original


def test_negative_base_missing_and_zero_denominator():
    data = facts()
    next(f for f in data if f["id"] == "revenue2023")["normalizedValue"] = "-80.08"
    assert Decimal(by_code(data)["revenue_yoy"]["result"]) == Decimal("225")
    for f in data:
        if f["id"] == "net_profit2024":
            f["normalizedValue"] = "0"
        if f["id"] == "revenue2024":
            f["normalizedValue"] = None
    result = by_code(data)
    assert result["cash_profit_ratio"]["reason"] == "zero_denominator"
    assert result["cash_profit_ratio"]["result"] is None
    assert result["revenue_yoy"]["reason"] == "missing_input"
    assert result["revenue_yoy"]["result"] is None


def test_incompatible_facts_and_non_finite_values():
    for key, wrong in [
        ("currency", "USD"),
        ("unit", "万元"),
        ("statementScope", "母公司"),
        ("attribution", "consolidated"),
        ("periodType", "instant"),
    ]:
        data = facts()
        next(f for f in data if f["id"] == "net_profit2024")[key] = wrong
        assert by_code(data)["cash_profit_ratio"]["reason"] == "incompatible_input"
    for invalid in ["NaN", "Infinity", "oops"]:
        data = facts()
        data[0]["normalizedValue"] = invalid
        assert by_code(data)["revenue_yoy"]["reason"] == "missing_input"
