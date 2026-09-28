from copy import deepcopy
from types import SimpleNamespace

from dbgpt_serve.financial_analysis.report import build_report

from .test_calculations import expanded_facts


def build(data, **extra):
    return build_report(
        {
            "report_year": "2024",
            "company_name": "测试公司",
            "facts": data,
            "document": {"id": "doc", "pageCount": 10},
            "evidence": [{"id": "E1", "sourceDocumentId": "doc", "page": 3}],
            **extra,
        },
        {"id": "run", "completed_at": "2026-09-26T00:00:00Z"},
        SimpleNamespace(display_name="fixture.pdf", file_id="file", size_bytes=100),
    )


def test_opening_and_pre_adjustment_observations_survive_without_becoming_inputs():
    from dbgpt_serve.financial_analysis.analysis import model_context

    values = [
        {
            "normalizedValue": "999999",
            "sourcePeriod": {"role": "opening", "adjustment": "unspecified"},
        },
        {
            "normalizedValue": "888888",
            "sourcePeriod": {"role": "closing", "adjustment": "before"},
        },
        {
            "normalizedValue": "777777",
            "sourcePeriod": {"role": "closing", "adjustment": "after"},
        },
    ]
    facts = expanded_facts()
    report = build(facts, sourceObservations=values)
    assert report["extractionAudit"]["observations"] == values[:2]
    assert report["calculations"] == build(facts)["calculations"]
    report["evidence"][0]["snippet"] = "财务报表原文"
    assert "extractionAudit" not in model_context(report)
    report["extractionAudit"]["observations"][0]["normalizedValue"] = "changed"
    assert values[0]["normalizedValue"] == "999999"


def test_report_rates_link_both_years_and_keep_negative_expenses():
    data = expanded_facts()
    original = deepcopy(data)
    report = build(data)
    assert data == original
    calculations = {c["id"]: c for c in report["calculations"]}
    rows = report["sections"]["profitability"]["rateComparisons"]
    assert len(rows) == 5
    for row in rows:
        current = calculations[row["currentCalculationId"]]
        prior = calculations[row["previousCalculationId"]]
        change = calculations[row["changeCalculationId"]]
        assert current["fiscalPeriod"] == "2024"
        assert prior["fiscalPeriod"] == "2023"
        assert change["unit"] == "百分点"
        assert set(change["inputFactIds"]) == set(
            current["inputFactIds"] + prior["inputFactIds"]
        )
    assert len(report["trends"]["expenses"]) == 8
    negative = [p for p in report["trends"]["expenses"] if p["expense"] == "财务费用率"]
    assert [p["value"] for p in negative] == [-2, -3]
    for point in report["trends"]["expenses"]:
        assert calculations[point["calculationId"]]["fiscalPeriod"] == point["year"]
    assert "inventory2024" in report["sections"]["balance"]["factIds"]
    assert any(
        m["id"] == "current_ratio" and m["displayValue"] == "3.00×"
        for m in report["healthMetrics"]
    )
    assert report["findings"] == []


def test_report_missing_expense_is_not_zero_and_keeps_other_period():
    data = expanded_facts()
    next(f for f in data if f["id"] == "research_expenses2024")["normalizedValue"] = (
        None
    )
    report = build(data)
    points = [p for p in report["trends"]["expenses"] if p["expense"] == "研发费用率"]
    assert len(points) == 1 and points[0]["year"] == "2023" and points[0]["value"] == 0
    calculations = {c["id"]: c for c in report["calculations"]}
    assert calculations["calc-research_expense_ratio-2024"]["reason"] == "missing_input"
    assert calculations["calc-research_expense_ratio_change-2024"]["result"] is None
