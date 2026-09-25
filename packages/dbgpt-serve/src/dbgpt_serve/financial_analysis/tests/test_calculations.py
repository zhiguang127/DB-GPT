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
    return {c["code"]: c for c in calculate(data, "2024")}


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
