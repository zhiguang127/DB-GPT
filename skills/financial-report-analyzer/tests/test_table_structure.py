"""Column/period regressions independent of any company or report filename."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from financial_document import build_result, source_period  # noqa: E402
from table_structure import structure_table  # noqa: E402


def table(
    rows, boxes, *, number=1, statement="summary", heading=1, scope="summary", bbox=None
):
    bbox = bbox or [0, 0, 300, 20 * len(rows)]
    return {
        "id": f"p{number}-t1",
        "rows": rows,
        "cellBoxes": boxes,
        "bbox": bbox,
        "scope": scope,
        "statement": statement,
        "section": scope + statement,
        "headingPage": heading,
        "unit": "元",
        "unitPage": heading,
        "unitText": "单位：元",
        "structure": structure_table(rows, boxes, bbox),
    }


def regular(rows, **kwargs):
    boxes = [
        [[100 * c, 20 * r, 100 * (c + 1), 20 * (r + 1)] for c in range(len(row))]
        for r, row in enumerate(rows)
    ]
    return table(rows, boxes, **kwargs)


def page(number, *tables):
    return {
        "page": number,
        "text": "测试股份有限公司 2024 年年度报告",
        "tables": list(tables),
    }


def fact(result, code="total_assets", year="2024"):
    return next(
        f
        for f in result["facts"]
        if f["metricCode"] == code and f["fiscalPeriod"] == year
    )


def adjusted(after="190"):
    rows = [
        ["项目", "2024年末", "2023年末", None],
        [None, None, "调整前", "调整后"],
        ["总资产（元）", "200", "180", after],
    ]
    boxes = [
        [[0, 0, 60, 20], [60, 0, 140, 20], [140, 0, 300, 20], None],
        [None, None, [140, 20, 220, 40], [220, 20, 300, 40]],
        [[0, 40, 60, 60], [60, 40, 140, 60], [140, 40, 220, 60], [220, 40, 300, 60]],
    ]
    return table(rows, boxes)


def test_padding_columns_map_by_bounds_and_keep_missing_amount():
    rows = [
        ["项目", "", "2024年度", "", "2023年度"],
        ["营业收入", "200", None, "190", None],
        ["营业成本", None, None, "80", None],
    ]
    boxes = [
        [
            [0, 0, 100, 20],
            [100, 0, 105, 20],
            [105, 0, 195, 20],
            [200, 0, 205, 20],
            [205, 0, 295, 20],
        ],
        [[0, 20, 100, 40], [100, 20, 200, 40], None, [200, 20, 300, 40], None],
        [[0, 40, 100, 60], [100, 40, 200, 60], None, [200, 40, 300, 60], None],
    ]
    source = table(rows, boxes, scope="合并", statement="利润表")
    result = build_result([page(1, source)], "doc", "fixture.pdf")
    assert fact(result, "revenue")["normalizedValue"] == "200"
    assert fact(result, "revenue", "2023")["normalizedValue"] == "190"
    assert fact(result, "cost_of_sales")["normalizedValue"] is None
    assert fact(result, "cost_of_sales", "2023")["normalizedValue"] == "80"
    assert source["rows"] == rows
    assert (
        next(e for e in result["evidence"] if e["normalizedValue"] == "200")[
            "sourceCells"
        ][0]["column"]
        == 1
    )


def test_explicit_adjustments_choose_after_and_preserve_before():
    result = build_result([page(1, adjusted())], "doc", "fixture.pdf")
    assert fact(result, year="2023")["normalizedValue"] == "190"
    assert fact(result, year="2023")["sourcePeriods"][0]["adjustment"] == "after"
    assert any(
        c["normalizedValue"] == "180" and c["sourcePeriod"]["adjustment"] == "before"
        for c in result["sourceObservations"]
    )
    assert not any(e["normalizedValue"] == "180" for e in result["evidence"])


@pytest.mark.parametrize("missing", ["—", ""])
def test_missing_adjusted_value_never_falls_back_to_before(missing):
    # A dash retains column bounds without inventing a numeric value.
    source = adjusted(missing)
    # This table's explicit subheader establishes the blank adjusted column.
    result = build_result([page(1, source)], "doc", "fixture.pdf")
    assert fact(result)["normalizedValue"] == "200"
    assert fact(result, year="2023")["normalizedValue"] is None


@pytest.mark.parametrize("marker", ["未知口径", "重述调整数"])
def test_unknown_adjustment_headers_cannot_use_prior_year_map(marker):
    source = adjusted()
    source["rows"][1][3] = marker
    source["structure"] = structure_table(
        source["rows"], source["cellBoxes"], source["bbox"]
    )
    result = build_result([page(1, source)], "doc", "fixture.pdf")
    assert fact(result, year="2023")["normalizedValue"] is None


def test_opening_is_retained_separately_not_relabelled_prior_closing():
    source = regular(
        [["项目", "2024年12月31日", "2024年1月1日"], ["资产总计", "200", "180"]],
        scope="合并",
        statement="资产负债表",
    )
    result = build_result([page(1, source)], "doc", "fixture.pdf")
    assert fact(result)["normalizedValue"] == "200"
    assert fact(result, year="2023")["normalizedValue"] is None
    opening = next(
        c
        for c in result["sourceObservations"]
        if c["sourcePeriod"]["role"] == "opening"
    )
    assert opening["fiscalPeriod"] == "2024" and opening["normalizedValue"] == "180"
    assert opening["sourcePeriod"]["date"] == "2024-01-01"


@pytest.mark.parametrize("date", ["2024年6月30日", "2024年1月2日", "2024/2023"])
def test_unsupported_period_is_not_an_annual_header(date):
    assert source_period(date) is None


def test_continuation_needs_matching_geometry_and_scope():
    first = regular(
        [["项目", "2024年末", "2023年末"], ["资产总计", "200", "180"]],
        scope="合并",
        statement="资产负债表",
    )
    next_table = regular(
        [["负债合计", "80", "70"]], number=2, scope="合并", statement="资产负债表"
    )
    parent = regular(
        [["项目", "2024年末", "2023年末"], ["负债合计", "999", "999"]],
        number=3,
        heading=3,
        scope="母公司",
        statement="资产负债表",
    )
    result = build_result(
        [page(1, first), page(2, next_table), page(3, parent)], "doc", "fixture.pdf"
    )
    assert fact(result, "total_liabilities")["normalizedValue"] == "80"
    # Same column count, different positions: must not inherit the header.
    next_table["structure"]["columns"] = [(0, 80), (80, 160), (160, 300)]
    result = build_result([page(1, first), page(2, next_table)], "doc", "fixture.pdf")
    assert fact(result, "total_liabilities")["normalizedValue"] is None


def test_cross_page_metric_label_keeps_its_amount_page():
    first = regular(
        [["项目", "2024年末", "2023年末"], ["归属于上市公司股东的净资", "200", "180"]]
    )
    suffix = regular([["产（元）", None, None]], number=2)
    result = build_result([page(1, first), page(2, suffix)], "doc", "fixture.pdf")
    assert fact(result, "equity")["normalizedValue"] == "200"
    source = result["evidence"][0]
    assert source["page"] == 1 and source["labelContinuation"]["page"] == 2
    assert result["_meta"]["tableIssues"] == []


def test_conflicting_adjusted_and_unqualified_sources_stay_conflicts():
    other = regular(
        [["项目", "2024年末", "2023年末"], ["资产总计", "200", "185"]],
        number=2,
        heading=2,
        scope="合并",
        statement="资产负债表",
    )
    result = build_result([page(1, adjusted()), page(2, other)], "doc", "fixture.pdf")
    assert fact(result, year="2023")["extractionStatus"] == "conflict"


def test_overlapping_amount_columns_are_rejected():
    rows = [["资产总计", "200", "180"], ["负债合计", "80", "70"]]
    boxes = [
        [[0, 0, 100, 20], [100, 0, 230, 20], [200, 0, 300, 20]],
        [[0, 20, 100, 40], [100, 20, 230, 40], [200, 20, 300, 40]],
    ]
    assert structure_table(rows, boxes, [0, 0, 300, 40])["status"] == "ambiguous"
