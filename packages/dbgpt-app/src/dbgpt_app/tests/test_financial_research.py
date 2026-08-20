"""Tests for the deterministic financial research agent."""

import json
import os
import re
import sqlite3
from pathlib import Path

import pytest

from dbgpt_app.financial_research import FinancialResearchAgent, ResearchRequest
from dbgpt_app.financial_research.domain.metric_catalog import SUPPORTED_FACT_COUNT
from dbgpt_app.financial_research.domain.models import (
    ConsolidationScope,
    Evidence,
    FinancialMetric,
    MetricUnit,
    ParsedDocument,
    ParsedPage,
    ResearchSource,
    ResearchStage,
    SourceKind,
    StatementType,
)
from dbgpt_app.financial_research.domain.normalization import normalize_metrics
from dbgpt_app.financial_research.domain.validation import validate_metrics
from dbgpt_app.financial_research.infrastructure.extraction import (
    extract_financial_facts,
)
from dbgpt_app.financial_research.infrastructure.parsers import (
    ParserRegistry,
    build_document_index,
)
from dbgpt_app.openapi.api_view_model import ConversationVo

ANNUAL_REPORT_TEXT = """示例股份有限公司2019年年度报告全文
五、主要会计数据和财务指标
2019年 2018年 本年比上年增减 2017年
营业收入（元） 318,024,319.30 320,070,653.13 -0.64% 359,659,866.37
归属于上市公司股东的净利润
63,616,426.50 75,275,286.09 -15.49% 79,802,362.53
（元）
归属于上市公司股东的扣除非
47,853,754.35 65,201,451.76 -26.61% 65,734,253.73
经常性损益的净利润（元）
经营活动产生的现金流量净额
36,228,660.52 58,318,179.79 -37.88% -21,008,592.71
（元）
基本每股收益（元/股） 0.65 0.75 -13.33% 0.81
加权平均净资产收益率 7.77% 9.06% -1.29% 10.66%
2019年末 2018年末 本年末比上年末增减 2017年末
资产总额（元） 1,050,566,795.15 1,060,545,382.44 -0.94% 1,018,578,365.92
归属于上市公司股东的净资产
825,989,994.28 854,728,505.93 -3.36% 812,788,219.84
（元）
"""


@pytest.mark.asyncio
async def test_agent_generates_traceable_self_contained_report(tmp_path: Path):
    source = (
        tmp_path / "2020-01-01__示例股份有限公司__000001__示例__2019年__年度报告.txt"
    )
    source.write_text(ANNUAL_REPORT_TEXT, encoding="utf-8")
    output_dir = tmp_path / "output"
    events = []

    async def collect(event, _state):
        events.append(event)

    state = await FinancialResearchAgent().run(
        ResearchRequest(file_paths=[str(source)], output_dir=str(output_dir)),
        collect,
    )

    current = {
        metric.name: metric for metric in state.metrics if metric.period == "2019"
    }
    assert current["net_profit"].value == 63_616_426.50
    assert current["non_recurring_net_profit"].value == 47_853_754.35
    assert current["operating_cash_flow"].reported_growth_pct == -37.88
    assert current["net_margin"].value == pytest.approx(
        63_616_426.50 / 318_024_319.30 * 100
    )
    assert current["net_margin"].is_reported is False
    assert len(current["net_margin"].evidence_ids) == 2
    historical = {
        (metric.name, metric.period): metric.value for metric in state.metrics
    }
    assert historical[("revenue", "2017")] == 359_659_866.37
    assert historical[("weighted_roe", "2017")] == 10.66
    assert state.validation_issues == []
    assert {section.key for section in state.analysis_sections} == {
        "earnings_investigation",
        "cash_investigation",
        "capital_investigation",
        "notes_investigation",
        "disclosure_review",
    }
    assert ResearchStage.ANALYZE_PEERS not in {item.stage for item in state.plan}
    assert len(state.plan) == 17
    assert {item.topic_key for item in state.anomalies} == {
        "earnings_quality",
        "core_earnings",
        "cash_conversion",
        "capital_returns",
    }
    assert len(state.hypotheses) == 6
    assert state.analysis["top_findings"]
    assert len(
        {
            (finding["company_name"], finding["topic_key"])
            for finding in state.analysis["top_findings"]
        }
    ) == len(state.analysis["top_findings"])
    assert state.analysis["quality"]["evidence_coverage_pct"] == 100
    assert state.analysis["quality"]["computation_coverage_pct"] == 100
    assert len(state.computations) == sum(
        not metric.is_reported for metric in state.metrics
    )
    assert all(metric.evidence_ids for metric in state.metrics)
    assert {evidence.page_number for evidence in state.evidence} == {1}

    report_path = Path(state.report.path)
    report_html = report_path.read_text(encoding="utf-8")
    assert "PDF 1页" in report_html
    assert "占归母净利润 24.78%" in report_html
    assert "不套用固定风险线" in report_html
    assert "研究任务与执行记录" not in report_html
    assert "<svg" in report_html
    assert "data:image" not in report_html
    visible_html = re.sub(
        r"<style\b.*?</style>", "", report_html, flags=re.IGNORECASE | re.DOTALL
    )
    visible_text = re.sub(r"<[^>]+>", " ", visible_html)
    leaked_enum_tokens = re.findall(
        r"\b(?:consolidated|parent_company|unspecified|balance_sheet|"
        r"income_statement|cash_flow_statement|segment_disclosure|"
        r"non_recurring_disclosure|computed|supported|partial|unresolved|"
        r"rejected|insufficient_data)\b",
        visible_text,
    )
    assert leaked_enum_tokens == []
    assert "百万元" not in visible_text
    assert "亿元" in visible_text
    assert "包括 、" not in visible_text
    for chart in state.charts:
        svg = Path(chart.path).read_text(encoding="utf-8")
        text_nodes = re.findall(r"<text\b[^>]*>", svg)
        assert text_nodes
        assert all("font-family=" in node for node in text_nodes)
    assert (output_dir / "research_state.json").is_file()
    assert (output_dir / "financial_research.sqlite3").is_file()
    with sqlite3.connect(output_dir / "financial_research.sqlite3") as database:
        assert database.execute("SELECT count(*) FROM evidence").fetchone()[0] == len(
            state.evidence
        )
        assert database.execute("SELECT count(*) FROM computations").fetchone()[
            0
        ] == len(state.computations)
    assert events[-1].message == "可追溯财务研究完成"


@pytest.mark.asyncio
async def test_selected_skill_routes_around_react(monkeypatch):
    from dbgpt_app.openapi.api_v1 import agentic_data_api

    calls = []

    async def financial_stream(_dialogue):
        calls.append("financial")
        yield "financial-event"

    async def react_stream(_dialogue, tool_mode):
        calls.append(f"react:{tool_mode}")
        yield "react-event"

    monkeypatch.setattr(
        agentic_data_api, "_financial_research_agent_stream", financial_stream
    )
    monkeypatch.setattr(agentic_data_api, "_react_agent_stream", react_stream)
    dialogue = ConversationVo(
        user_input="分析财报",
        ext_info={"skill_name": "financial-report-analyzer", "file_path": "/tmp/a.pdf"},
    )

    events = [
        event async for event in agentic_data_api._selected_agent_stream(dialogue)
    ]

    assert events == ["financial-event"]
    assert calls == ["financial"]


@pytest.mark.parametrize(
    ("user_input", "file_path", "expected"),
    [
        ("帮我分析这份财报", "/tmp/upload.pdf", True),
        ("分析这个文件", "/tmp/某公司__2019年__年度报告.pdf", True),
        ("总结这篇论文", "/tmp/paper.pdf", False),
    ],
)
def test_unambiguous_report_upload_is_automatically_routed(
    user_input, file_path, expected
):
    from dbgpt_app.openapi.api_v1.agentic_data_api import (
        _is_financial_research_request,
    )

    dialogue = ConversationVo(
        user_input=user_input,
        ext_info={"file_path": file_path},
    )

    assert _is_financial_research_request(dialogue) is expected


@pytest.mark.asyncio
async def test_agent_compares_multiple_companies_without_mixing_metrics(
    tmp_path: Path,
):
    first = (
        tmp_path / "2020-01-01__示例A股份有限公司__000001__示例A__2019年__年度报告.txt"
    )
    second = (
        tmp_path / "2020-01-01__示例B股份有限公司__000002__示例B__2019年__年度报告.txt"
    )
    first.write_text(ANNUAL_REPORT_TEXT, encoding="utf-8")
    second.write_text(
        ANNUAL_REPORT_TEXT.replace(
            "318,024,319.30 320,070,653.13",
            "636,048,638.60 640,141,306.26",
        ),
        encoding="utf-8",
    )

    state = await FinancialResearchAgent().run(
        ResearchRequest(
            file_paths=[str(first), str(second)],
            output_dir=str(tmp_path / "output"),
        )
    )

    assert state.mode.value == "multi_company"
    assert len(state.raw_metrics) == 48
    assert len(state.metrics) == len(state.raw_metrics) + len(state.computations)
    assert {section.key for section in state.analysis_sections} == {
        "earnings_investigation",
        "cash_investigation",
        "capital_investigation",
        "notes_investigation",
        "peer_comparison",
        "disclosure_review",
    }
    assert len(state.plan) == 18
    peer_task = next(
        item for item in state.plan if item.stage == ResearchStage.ANALYZE_PEERS
    )
    assert peer_task.depends_on == [ResearchStage.DETECT_ANOMALIES]
    assert all(
        finding.evidence_ids
        for section in state.analysis_sections
        for finding in section.findings
        if finding.metric_ids
    )
    assert all(item.status.value == "completed" for item in state.plan)
    assert any(event.stage.value == "normalize" for event in state.events)
    comparison = state.analysis["peer_comparison"]
    assert comparison["period"] == "2019"
    assert comparison["metrics"]["revenue"][0]["company"] == "示例B股份有限公司"

    report_html = Path(state.report.path).read_text(encoding="utf-8")
    assert "2 家公司可追溯财务对比报告" in report_html
    assert "示例A股份有限公司" in report_html
    assert "示例B股份有限公司" in report_html
    assert "同业比较" in report_html
    assert "核心结论" in report_html
    assert "异常与调查问题" in report_html
    assert "版本化计算血缘" in report_html
    assert "未决问题与资料边界" in report_html
    assert (tmp_path / "output" / "peer_key_metrics.svg").is_file()
    assert (tmp_path / "output" / "peer_cash_quality.svg").is_file()


@pytest.mark.asyncio
async def test_workflow_replans_multiple_reports_from_same_company_as_single_company(
    tmp_path: Path,
):
    first = tmp_path / "a__示例股份有限公司__2019年__年度报告.txt"
    second = tmp_path / "b__示例股份有限公司__2018年__年度报告.txt"
    first.write_text(ANNUAL_REPORT_TEXT, encoding="utf-8")
    second.write_text(ANNUAL_REPORT_TEXT, encoding="utf-8")

    state = await FinancialResearchAgent().run(
        ResearchRequest(
            file_paths=[str(first), str(second)],
            output_dir=str(tmp_path / "output"),
        )
    )

    assert state.mode.value == "single_company"
    assert ResearchStage.ANALYZE_PEERS not in {item.stage for item in state.plan}


def test_document_index_and_extractor_preserve_table_cell_and_segment_dimensions():
    pages = [
        ParsedPage(
            page_number=1,
            text="""第一节 公司简介和主要财务指标
1、合并资产负债表
项目 2019年12月31日 2018年12月31日
货币资金 100.00 80.00
应收账款 50.00 40.00
存货 30.00 20.00
流动资产合计 180.00 140.00
非流动资产合计 120.00 110.00
资产总计 300.00 250.00
流动负债合计 90.00 70.00
非流动负债合计 10.00 10.00
负债合计 100.00 80.00
所有者权益合计 200.00 170.00
负债和所有者权益总计 300.00 250.00
""",
        ),
        ParsedPage(
            page_number=2,
            text="""3、合并利润表
项目 2019年度 2018年度
营业收入 200.00 180.00
营业成本 120.00 100.00
销售费用 10.00 9.00
管理费用 15.00 14.00
研发费用 8.00 7.00
财务费用 2.00 2.00
利息费用 3.00 3.00
营业利润 45.00 43.00
利润总额 44.00 42.00
所得税费用 4.00 4.00
净利润 40.00 38.00
归属于母公司所有者的净利润 39.00 37.00
少数股东损益 1.00 1.00
""",
        ),
        ParsedPage(
            page_number=3,
            text="""5、合并现金流量表
项目 2019年度 2018年度
经营活动现金流入小计 240.00 210.00
经营活动现金流出小计 190.00 180.00
经营活动产生的现金流量净额 50.00 30.00
购建固定资产、无形资产和其他长期资产支付的现金 20.00 18.00
投资活动产生的现金流量净额 -20.00 -18.00
筹资活动产生的现金流量净额 -10.00 -5.00
现金及现金等价物净增加额 20.00 7.00
期初现金及现金等价物余额 75.00 68.00
期末现金及现金等价物余额 95.00 75.00
""",
        ),
        ParsedPage(
            page_number=4,
            text="""第三节 经营情况讨论与分析
（1）营业收入构成
2019年 2018年
金额 占营业收入比重 金额 占营业收入比重 同比增减
分行业
软件 120.00 60.00% 90.00 50.00% 10.00%
服务 80.00 40.00% 90.00 50.00% -10.00%
分产品
产品A 150.00 75.00% 135.00 75.00% 0.00%
产品B 50.00 25.00% 45.00 25.00% 0.00%
""",
        ),
    ]
    sections, tables = build_document_index(pages, 2019)
    document = ParsedDocument(
        source_id="source-golden",
        file_name="golden.pdf",
        media_type="application/pdf",
        company_name="示例公司",
        report_year=2019,
        pages=pages,
        sections=sections,
        tables=tables,
    )

    evidence, metrics = extract_financial_facts(document)

    assert SUPPORTED_FACT_COUNT >= 30
    assert {table.name for table in tables} >= {
        "合并资产负债表",
        "合并利润表",
        "合并现金流量表",
        "营业收入构成（分行业/产品/地区）",
    }
    assert all(
        item.table_id and item.row_index is not None and item.column_index is not None
        for item in evidence
    )
    segment_facts = [item for item in metrics if item.name == "segment_revenue"]
    assert {tuple(item.dimensions.items()) for item in segment_facts} >= {
        (("industry", "软件"),),
        (("product", "产品A"),),
    }


def test_non_recurring_disclosure_is_extracted_as_composition_not_only_gap():
    pages = [
        ParsedPage(
            page_number=9,
            text="""八、非经常性损益项目及金额
单位：元
项目 2019年金额 2018年金额 2017年金额 说明
计入当期损益的政府补助 3,641,079.64 3,338,400.81 11,169,002.46
委托他人投资或管理资产的损益 20,577,067.50 8,885,167.92 5,180,731.79
减：所得税影响额 2,794,385.75 1,779,954.64 2,478,240.65
合计 15,762,672.15 10,073,834.33 14,068,108.80
""",
        )
    ]
    sections, tables = build_document_index(pages, 2019)
    document = ParsedDocument(
        source_id="source-non-recurring",
        file_name="non-recurring.pdf",
        media_type="application/pdf",
        company_name="示例公司",
        report_year=2019,
        pages=pages,
        sections=sections,
        tables=tables,
    )

    evidence, metrics = extract_financial_facts(document)

    assert any(
        table.statement_type == StatementType.NON_RECURRING_DISCLOSURE
        for table in tables
    )
    components = [
        item
        for item in metrics
        if item.name == "non_recurring_item" and item.period == "2019"
    ]
    assert {item.dimensions["item"] for item in components} == {
        "计入当期损益的政府补助",
        "委托他人投资或管理资产的损益",
        "减：所得税影响额",
    }
    disclosed_total = next(
        item
        for item in metrics
        if item.name == "non_recurring_net_effect_reported" and item.period == "2019"
    )
    assert disclosed_total.value == 15_762_672.15
    assert all(item.evidence_ids for item in components)
    assert len(evidence) == len(metrics)


def test_conflicting_facts_are_retained_and_resolved_by_disclosed_precedence():
    summary = FinancialMetric(
        document_id="summary-document",
        company_name="示例公司",
        period="2019",
        name="total_assets",
        display_name="资产总计",
        value=299.0,
        raw_value="299.00",
        unit=MetricUnit.CNY,
        currency="CNY",
        scope=ConsolidationScope.CONSOLIDATED,
        statement_type=StatementType.SUMMARY,
        confidence=0.99,
        evidence_ids=["summary-evidence"],
    )
    statement = summary.model_copy(
        update={
            "id": "statement-fact",
            "document_id": "statement-document",
            "value": 300.0,
            "raw_value": "300.00",
            "statement_type": StatementType.BALANCE_SHEET,
            "confidence": 0.95,
            "evidence_ids": ["statement-evidence"],
        }
    )

    normalized, issues = normalize_metrics([summary, statement])

    assert len(normalized) == 1
    assert normalized[0].value == 300.0
    assert [summary.value, statement.value] == [299.0, 300.0]
    assert set(normalized[0].evidence_ids) == {
        "summary-evidence",
        "statement-evidence",
    }
    assert [item.code for item in issues] == ["cross_document_conflict"]


def test_accounting_equation_mismatch_is_a_hard_validation_error():
    evidence = Evidence(
        id="balance-evidence",
        document_id="document",
        source_id="source",
        page_number=1,
        table_name="合并资产负债表",
        quote="资产、负债和权益",
        extraction_method="test",
    )

    def fact(name: str, display_name: str, value: float) -> FinancialMetric:
        return FinancialMetric(
            document_id="document",
            company_name="示例公司",
            period="2019",
            name=name,
            display_name=display_name,
            value=value,
            raw_value=str(value),
            unit=MetricUnit.CNY,
            currency="CNY",
            scope=ConsolidationScope.CONSOLIDATED,
            statement_type=StatementType.BALANCE_SHEET,
            evidence_ids=[evidence.id],
        )

    issues = validate_metrics(
        [
            fact("total_assets", "资产总计", 300.0),
            fact("total_liabilities", "负债合计", 100.0),
            fact("total_equity", "所有者权益合计", 150.0),
        ],
        [evidence],
    )

    equation_issue = next(
        item for item in issues if item.code == "balance_sheet_equation_mismatch"
    )
    assert equation_issue.severity.value == "error"


def test_interim_periods_and_hkd_units_are_preserved_end_to_end():
    from dbgpt_app.financial_research.domain.periods import (
        PeriodKind,
        period_display_name,
    )

    pages = [
        ParsedPage(
            page_number=1,
            text="""示例公司2024年半年度报告
主要会计数据和财务指标
单位：千港元
2024年 2023年
营业收入 100.00 90.00
归属于上市公司股东的净利润 20.00 18.00
经营活动产生的现金流量净额 16.00 14.00
基本每股收益 0.50 0.40
""",
        ),
        ParsedPage(
            page_number=2,
            text="""1、合并资产负债表
单位：千港元
项目 2024年6月30日 2023年12月31日
资产总计 300.00 280.00
负债合计 100.00 90.00
所有者权益合计 200.00 190.00
""",
        ),
    ]
    sections, tables = build_document_index(
        pages, 2024, PeriodKind.HALF_YEAR, default_currency="HKD"
    )
    summary = next(table for table in tables if table.name == "主要会计数据和财务指标")
    balance_sheet = next(table for table in tables if table.name == "合并资产负债表")

    assert summary.columns[:2] == ["2024H1", "2023H1"]
    assert balance_sheet.columns == ["2024H1", "2023"]
    assert summary.currency == "HKD"
    assert summary.scale == 1_000
    assert period_display_name("2024H1") == "2024年上半年"

    document = ParsedDocument(
        source_id="source-interim",
        file_name="interim.pdf",
        media_type="application/pdf",
        company_name="示例公司",
        report_year=2024,
        pages=pages,
        sections=sections,
        tables=tables,
        report_kind="half_year",
        currency="HKD",
    )
    evidence, metrics = extract_financial_facts(document)
    current = {metric.name: metric for metric in metrics if metric.period == "2024H1"}
    assert current["revenue"].value == 100_000
    assert current["revenue"].currency == "HKD"
    assert current["basic_eps"].value == 0.5
    assert current["basic_eps"].currency == "HKD"
    issues = validate_metrics(metrics, evidence, [document])
    assert not {
        "invalid_period",
        "currency_missing",
        "currency_conflict",
    } & {issue.code for issue in issues}


def test_restatement_summary_spans_pages_and_uses_adjusted_comparatives():
    pages = [
        ParsedPage(
            page_number=1,
            text="""示例公司2019年年度报告
六、主要会计数据和财务指标
""",
        ),
        ParsedPage(
            page_number=2,
            text="""2018年 2017年
2019年 增减
调整前 调整后 调整后 调整前 调整后
营业收入（元） 100.00 80.00 90.00 11.11% 70.00 75.00
归属于上市公司股东的净利润（元） 20.00 15.00 18.00 11.11% 10.00 12.00
经营活动产生的现金流量净额（元） 16.00 12.00 14.00 14.29% 8.00 9.00
境内外会计准则下会计数据差异
""",
        ),
        ParsedPage(
            page_number=3,
            text="""3、合并利润表
项目 2019年度 2018年度
1.归属于母公司所有者的净利润 20.00 18.00
2.少数股东损益 2.00 1.00
""",
        ),
    ]
    sections, tables = build_document_index(pages, 2019)
    document = ParsedDocument(
        source_id="source-restated",
        file_name="restated.pdf",
        media_type="application/pdf",
        company_name="示例公司",
        report_year=2019,
        pages=pages,
        sections=sections,
        tables=tables,
    )

    evidence, raw_metrics = extract_financial_facts(document)
    metrics, issues = normalize_metrics(raw_metrics)
    revenue = {
        metric.period: metric
        for metric in metrics
        if metric.name == "revenue" and not metric.dimensions
    }
    net_profit = {
        metric.period: metric
        for metric in metrics
        if metric.name == "net_profit" and not metric.dimensions
    }

    assert revenue["2019"].value == 100.0
    assert revenue["2018"].value == 90.0
    assert revenue["2017"].value == 75.0
    assert revenue["2019"].reported_growth_pct == 11.11
    assert net_profit["2019"].value == 20.0
    assert net_profit["2018"].value == 18.0
    assert issues == []
    assert all(item.evidence_ids for item in metrics)
    assert evidence


def test_note_tables_exclude_headers_overlaps_and_non_transaction_sections():
    from dbgpt_app.financial_research.domain.research_analysis import investigate_notes

    pages = [
        ParsedPage(
            page_number=1,
            text="""按账龄披露
单位：元
账龄 账面余额
1年以内（含1年） 100.00
1至2年 20.00
3年以上 10.00
3至4年 6.00
4至5年 4.00
合计 130.00
（2）本期计提、收回或转回的坏账准备情况
""",
        ),
        ParsedPage(
            page_number=2,
            text="""（1）商誉账面原值
单位：元
被投资单位名称或形成商誉的事项 期初余额 本期增加 本期减少 期末余额
示例标的有限公司 80.00 20.00 100.00
合计 80.00 20.00 100.00
（2）商誉减值准备
""",
        ),
        ParsedPage(
            page_number=3,
            text="""（1）购销商品、提供和接受劳务的关联交易
采购商品/接受劳务情况表
单位：元
关联方 关联交易内容 本期发生额 上期发生额
示例关联方有限公司 采购 12.00 8.00
（2）关联受托管理/承包及委托管理/出包情况
担保方 担保金额 担保起始日 担保到期日
某股东 200,000,000.00 2019年01月01日 2020年01月01日
""",
        ),
    ]
    sections, tables = build_document_index(pages, 2019)
    document = ParsedDocument(
        source_id="source-notes",
        file_name="notes.pdf",
        media_type="application/pdf",
        company_name="示例公司",
        report_year=2019,
        pages=pages,
        sections=sections,
        tables=tables,
    )
    _evidence, metrics = extract_financial_facts(document)

    aging = [
        metric
        for metric in metrics
        if metric.name == "receivable_aging_balance" and metric.row_label != "合计"
    ]
    related = [
        metric for metric in metrics if metric.name == "related_party_transaction"
    ]
    goodwill = [
        metric
        for metric in metrics
        if metric.name == "goodwill_detail" and metric.period == "2019"
    ]
    assert {item.row_label for item in aging} >= {
        "1年以内",
        "1至2年",
        "3年以上",
        "3至4年",
        "4至5年",
    }
    assert [
        (item.row_label, item.value) for item in related if item.period == "2019"
    ] == [("示例关联方有限公司", 12.0)]
    assert all("某股东" not in item.row_label for item in related)
    assert [
        (item.row_label, item.value) for item in goodwill if item.row_label != "合计"
    ] == [("示例标的有限公司", 100.0)]

    section = investigate_notes(metrics)
    findings = {finding.topic_key: finding for finding in section.findings}
    aging_finding = findings["note_receivables_aging"]
    assert "3年以上" not in aging_finding.summary
    assert "明细合计 130.00 元" in aging_finding.summary
    assert "占该披露 76.92%" in aging_finding.summary
    assert "不计算集中度" in findings["note_goodwill"].summary
    assert "占该披露 100.00%" not in findings["note_related_party"].summary


def test_cross_check_surfaces_disagreement_instead_of_selecting_a_winner():
    from dbgpt_app.financial_research.domain.cross_check import (
        cross_check_extraction,
    )
    from dbgpt_app.financial_research.domain.models import (
        ParsedTable,
        ParsedTableRow,
        ParsedTableValue,
    )

    geometry = ParsedTable(
        name="几何识别表格",
        statement_type=StatementType.COMPUTED,
        start_page=1,
        end_page=1,
        columns=["2019"],
        strategy="geometry",
        rows=[
            ParsedTableRow(
                row_index=0,
                label="营业收入",
                page_number=1,
                raw_text="营业收入 120.00",
                values=[
                    ParsedTableValue(
                        column_index=0,
                        column_label="2019",
                        raw_value="120.00",
                        page_number=1,
                    )
                ],
            )
        ],
    )
    document = ParsedDocument(
        id="document",
        source_id="source",
        file_name="report.pdf",
        media_type="application/pdf",
        geometric_tables=[geometry],
    )
    evidence = Evidence(
        id="evidence",
        document_id=document.id,
        source_id="source",
        page_number=1,
        table_id="primary-table",
        row_index=0,
        column_index=0,
        row_label="营业收入",
        column_label="2019",
        cell_value="100.00",
        quote="营业收入 100.00",
        extraction_method="test",
    )
    metric = FinancialMetric(
        id="metric",
        document_id=document.id,
        company_name="示例公司",
        period="2019",
        name="revenue",
        display_name="营业收入",
        value=100.0,
        raw_value="100.00",
        unit=MetricUnit.MONEY,
        currency="CNY",
        evidence_ids=[evidence.id],
    )

    issues = cross_check_extraction([document], [metric], [evidence])

    assert [issue.code for issue in issues] == ["extraction_strategy_disagreement"]
    assert metric.value == 100.0


def test_narration_rejects_numbers_not_selected_by_deterministic_analysis():
    from dbgpt_app.financial_research.domain.models import ResearchFinding
    from dbgpt_app.financial_research.domain.narration import accept_narrative

    evidence = Evidence(
        id="evidence",
        document_id="document",
        source_id="source",
        page_number=1,
        quote="营业收入 999.00 元",
        extraction_method="test",
    )
    finding = ResearchFinding(
        title="利润下降",
        summary="利润同比下降 10.00%。",
        evidence_ids=[evidence.id],
    )
    evidence_by_id = {evidence.id: evidence}

    assert (
        accept_narrative(
            finding, "利润同比下降 10.00%，需结合原因分析。", evidence_by_id
        )
        is not None
    )
    assert accept_narrative(finding, "营业收入为 999.00 元。", evidence_by_id) is None


def test_ocr_is_explicit_and_marks_recognized_pages(monkeypatch, tmp_path: Path):
    from dbgpt_app.financial_research.infrastructure import parsers

    parser = parsers.PdfPlumberParser()
    pages = [ParsedPage(page_number=1, text="", width=100, height=200)]
    path = tmp_path / "scan.pdf"
    monkeypatch.setattr(parsers, "ocr_pdf_pages", lambda _path: [(1, "营业收入 100")])

    with pytest.raises(ValueError, match="开启 OCR"):
        parser._ensure_text_layer(path, pages, False)
    recognized, count = parser._ensure_text_layer(path, pages, True)

    assert count == 1
    assert recognized[0].text_source == "ocr"
    assert recognized[0].text == "营业收入 100"


def test_every_planned_stage_has_a_simplified_chinese_stream_title():
    from dbgpt_app.financial_research.application.planning import ResearchTaskPlanner
    from dbgpt_app.financial_research.presentation.streaming import STAGE_TITLES

    request = ResearchRequest(enable_narration=True)
    stages = ResearchTaskPlanner().plan(request)

    assert all(stage.stage.value in STAGE_TITLES for stage in stages)
    assert STAGE_TITLES[ResearchStage.INVESTIGATE_NOTES.value] == "调查附注披露明细"


def test_empty_key_audit_matter_label_is_not_rendered_as_punctuation():
    from dbgpt_app.financial_research.domain.research_analysis import (
        review_disclosures,
    )

    document = ParsedDocument(
        id="document",
        source_id="source",
        file_name="report.pdf",
        media_type="application/pdf",
        company_name="示例公司",
    )
    matter = Evidence(
        document_id=document.id,
        source_id="source",
        page_number=1,
        quote="三、关键审计事项\n（一）    \n（二）收入确认",
        extraction_method="key_audit_matters_v1",
    )

    section = review_disclosures([], [], [matter], [document])

    assert len(section.findings) == 1
    assert "包括 、" not in section.findings[0].summary
    assert "收入确认" in section.findings[0].summary


@pytest.mark.skipif(
    os.environ.get("DBGPT_RUN_FINANCIAL_PDF_EVALS") != "1",
    reason="Set DBGPT_RUN_FINANCIAL_PDF_EVALS=1 to run local PDF golden evaluations.",
)
def test_real_pdf_golden_facts_and_provenance():
    manifest_path = (
        Path(__file__).with_name("fixtures") / "financial_research_golden.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    repository_root = next(
        parent for parent in Path(__file__).parents if (parent / ".git").exists()
    )
    dataset_dir = repository_root / "python_uploads" / "001"
    assert manifest["local_case_count"] == len(manifest["cases"])

    for case in manifest["cases"]:
        path = (
            repository_root / case["path"]
            if case.get("path")
            else dataset_dir / case["file_name"]
        )
        if not path.is_file():
            pytest.fail(f"Golden PDF is missing: {path}")
        source = ResearchSource(
            kind=SourceKind.LOCAL_FILE,
            location=str(path),
            display_name=path.name,
        )
        document = ParserRegistry(
            enable_geometry=bool(case.get("check_geometry", False))
        ).parse(source)
        evidence, raw_metrics = extract_financial_facts(document)
        metrics, issues = normalize_metrics(raw_metrics)

        assert document.company_name == case["company"]
        assert document.report_year == case["report_year"]
        assert len({item.name for item in metrics}) >= case["minimum_concepts"]
        assert issues == []
        assert {
            "合并资产负债表",
            "合并利润表",
            "合并现金流量表",
            "营业收入构成（分行业/产品/地区）",
        } <= {table.name for table in document.tables}
        current = {
            item.name: item
            for item in metrics
            if item.period == str(case["report_year"]) and not item.dimensions
        }
        for concept, expected in case["facts"].items():
            assert current[concept].value == pytest.approx(expected)
            assert current[concept].raw_value is not None
            assert current[concept].evidence_ids
        current_note_facts = {
            f"{item.name}|{item.row_label}": item
            for item in metrics
            if item.period == str(case["report_year"])
            and item.statement_type == StatementType.NOTE
            and item.row_label != "合计"
        }
        for identity, expected in case.get("note_facts", {}).items():
            assert current_note_facts[identity].value == pytest.approx(expected)
            assert current_note_facts[identity].evidence_ids
        assert all(
            item.row_index is not None and item.column_index is not None
            for item in evidence
            if item.table_id
        )
        assert any(item.extraction_method == "audit_opinion_v1" for item in evidence)
        if case.get("check_geometry"):
            assert document.geometric_tables
