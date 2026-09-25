"""Run with unittest discovery; no network or model required."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from financial_document import (  # noqa: E402
    amount,
    build_result,
    extract_document,
    logical_rows,
    period_header,
    row_metric,
)


def table(rows, *, page=1, scope="合并", statement="资产负债表", unit="元", heading=1):
    return {
        "id": f"p{page}-t1",
        "rows": rows,
        "scope": scope,
        "statement": statement,
        "section": scope + statement,
        "headingPage": heading,
        "unit": unit,
        "unitPage": heading,
        "unitText": "单位：" + unit if unit else None,
    }


def page(number, *tables):
    return {
        "page": number,
        "text": "测试股份有限公司 2024年度报告",
        "tables": list(tables),
    }


def fact(result, code, year="2024"):
    return next(
        f
        for f in result["facts"]
        if f["metricCode"] == code and f["fiscalPeriod"] == year
    )


class FinancialDocumentTest(unittest.TestCase):
    def test_exact_decimal_units_and_negative_values(self):
        for raw, unit, expected in [
            ("（1,234.56）", "万元", "-12345600.00"),
            ("−21,008,592.71", "元", "-21008592.71"),
            ("0", "亿元", "0"),
            ("1.23", "百万元", "1230000.00"),
            ("9.01", "千元", "9010.00"),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(amount(raw, unit), (expected, None))
        for raw in ["", "--", "—", "不适用"]:
            self.assertEqual(amount(raw, "元"), (None, "missing_value"))
        for raw in ["5%", "1,23", "(5", "12万元", "NaN"]:
            self.assertEqual(amount(raw, "元"), (None, "invalid_amount"))
        self.assertEqual(amount("123", None), (None, "unknown_unit"))

    def test_exact_metric_names_do_not_match_subtotals(self):
        for text in [
            "流动负债合计",
            "非流动负债合计",
            "负债和所有者权益总计",
            "货币资金",
            "营业总成本",
            "净利润",
            "减：营业收入",
        ]:
            self.assertIsNone(row_metric(text), text)
        self.assertEqual(row_metric("其中：营业收入"), "revenue")
        self.assertEqual(row_metric("1.归属于母公司所有者的净利润"), "net_profit")

    def test_periods_require_complete_annual_dates(self):
        for header in [
            "2024年",
            "2024年度",
            "2024 年末",
            "2024年12月31日",
            "2024-12-31",
        ]:
            self.assertEqual(period_header(header), "2024")
        for header in ["2024年01月01日", "2024年6月30日", "本年同比", "2024/2023"]:
            self.assertIsNone(period_header(header))

    def test_split_rows_keep_periods_and_growth_column(self):
        rows = [
            ["", "", "2023年", "2024年", "同比", "2022年", ""],
            ["", "归属于上市公司股东的扣除非", None, None, None, None, ""],
            [None, None, "5.00", "（3.00）", "-160%", "—", None],
            [None, "经常性损益的净利润（万元）", None, None, None, None, None],
        ]
        self.assertEqual(len(list(logical_rows(rows))), 2)
        result = build_result(
            [page(1, table(rows, scope="summary", statement="summary", unit=None))],
            "doc",
            "fixture.pdf",
        )
        self.assertEqual(
            fact(result, "non_recurring_net_profit")["normalizedValue"], "-30000.00"
        )
        self.assertEqual(
            fact(result, "non_recurring_net_profit", "2023")["normalizedValue"],
            "50000.00",
        )
        self.assertEqual(
            fact(result, "non_recurring_net_profit", "2022")["missingReason"],
            "missing_value",
        )

    def test_continued_table_inherits_header_but_parent_never_overwrites(self):
        pages = [
            page(
                2,
                table(
                    [
                        ["项目", "2023年12月31日", "2024年12月31日"],
                        ["货币资金", "9", "10"],
                    ],
                    page=2,
                ),
            ),
            page(
                3,
                table([["流动负债合计", "50", "60"], ["负债合计", "70", "80"]], page=3),
                table(
                    [
                        ["项目", "2023年12月31日", "2024年12月31日"],
                        ["负债合计", "700", "800"],
                    ],
                    page=3,
                    scope="母公司",
                    heading=3,
                ),
            ),
        ]
        result = build_result(pages, "doc", "fixture.pdf")
        current = fact(result, "total_liabilities")
        self.assertEqual(current["normalizedValue"], "80")
        evidence = next(
            e for e in result["evidence"] if e["id"] in current["evidenceExcerptIds"]
        )
        self.assertEqual(
            (evidence["page"], evidence["headerPage"], evidence["unitPage"]), (3, 2, 1)
        )
        self.assertEqual(fact(result, "total_assets")["missingReason"], "row_not_found")

    def test_conflicts_are_null_and_keep_both_sources(self):
        first = table(
            [["项目", "2024年度", "2023年度"], ["营业收入", "10", "9"]],
            statement="利润表",
        )
        second = table(
            [["项目", "2024年", "2023年"], ["营业收入（元）", "20", "9"]],
            page=2,
            scope="summary",
            statement="summary",
            heading=2,
        )
        result = build_result([page(1, first), page(2, second)], "doc", "fixture.pdf")
        current = fact(result, "revenue")
        self.assertIsNone(current["normalizedValue"])
        self.assertIsNone(result["revenue"])
        self.assertEqual(current["extractionStatus"], "conflict")
        self.assertEqual(len(current["evidenceExcerptIds"]), 2)
        self.assertEqual(fact(result, "revenue", "2023")["extractionStatus"], "parsed")

    def test_restatement_and_new_section_cannot_reuse_header(self):
        rows = [
            ["项目", "2024年12月31日", "2023年12月31日"],
            ["货币资金", "1", "2"],
            ["项目", "2023年12月31日", "2024年01月01日"],
            ["资产总计", "3", "4"],
        ]
        result = build_result(
            [
                page(1, table(rows)),
                page(2, table([["资产总计", "5", "6"]], page=2, heading=2)),
            ],
            "doc",
            "fixture.pdf",
        )
        self.assertIsNone(result["total_assets"])
        self.assertEqual(result["_meta"]["status"], "unsupported")

    def test_unknown_units_cannot_be_assumed(self):
        rows = [["项目", "2024年", "2023年"], ["营业收入", "10", "20"]]
        result = build_result(
            [page(1, table(rows, scope="summary", statement="summary", unit=None))],
            "doc",
            "fixture.pdf",
        )
        self.assertIsNone(result["revenue"])
        self.assertEqual(fact(result, "revenue")["missingReason"], "unknown_unit")

    def test_document_without_text_is_explicitly_unsupported(self):
        from pypdf import PdfWriter

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "blank.pdf"
            writer = PdfWriter()
            writer.add_blank_page(width=595, height=842)
            with path.open("wb") as stream:
                writer.write(stream)
            result = extract_document(path)
        self.assertEqual(result["document"]["pageCount"], 1)
        self.assertEqual(result["_meta"]["status"], "unsupported")
        self.assertIsNone(result["revenue"])
        self.assertFalse(result["_meta"]["humanVerified"])

    def test_foreign_currency_is_not_relabelled_as_yuan(self):
        from financial_document import currency_in, unit_in

        self.assertEqual(unit_in("单位：万元 币种：人民币"), "万元")
        self.assertEqual(currency_in("币种：美元"), "USD")
        source = table(
            [["项目", "2024年", "2023年"], ["营业收入", "10", "20"]],
            scope="summary",
            statement="summary",
        )
        source["currency"] = "USD"
        result = build_result([page(1, source)], "doc", "fixture.pdf")
        self.assertIsNone(result["revenue"])
        self.assertEqual(
            fact(result, "revenue")["missingReason"], "unsupported_currency"
        )

    def test_damaged_pdf_returns_structured_tool_error(self):
        from extract_financials import extract_financials

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.pdf"
            path.write_bytes(b"%PDF-1.4\ninvalid")
            result = extract_financials(path)
        self.assertTrue(result["error"])
        self.assertTrue(result["message"])


if __name__ == "__main__":
    unittest.main()
