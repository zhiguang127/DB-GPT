"""Anomaly-led investigation stages that produce evidence-linked conclusions."""

from typing import Callable, Iterable

from ...domain.models import (
    AnalysisSection,
    FinancialAnomaly,
    FinancialMetric,
    ResearchHypothesis,
    ResearchStage,
    ResearchState,
)
from ...domain.research_analysis import (
    analyze_peers,
    detect_financial_anomalies,
    formulate_hypotheses,
    investigate_capital_returns,
    investigate_cash_conversion,
    investigate_earnings,
    investigate_notes,
    review_disclosures,
    synthesize_research,
)
from ...ports.workflow import WorkflowDependencies


class DetectAnomaliesStage:
    stage = ResearchStage.DETECT_ANOMALIES
    title = "发现需要解释的异常"
    description = "从三年趋势及跨指标背离中生成研究问题，而不是逐指标写结论"
    category = "研究调查"
    deliverable = "异常清单与待验证假设"
    start_message = "正在发现跨期异常并形成调查假设"

    async def execute(
        self, state: ResearchState, dependencies: WorkflowDependencies
    ) -> str:
        del dependencies
        state.anomalies = detect_financial_anomalies(state.metrics)
        state.hypotheses = formulate_hypotheses(state.anomalies)
        return (
            f"识别 {len(state.anomalies)} 个异常，形成 "
            f"{len(state.hypotheses)} 个待验证假设"
        )


class _InvestigationStage:
    analyzer: Callable[
        [
            Iterable[FinancialMetric],
            Iterable[FinancialAnomaly],
            Iterable[ResearchHypothesis],
        ],
        AnalysisSection,
    ]

    async def execute(
        self, state: ResearchState, dependencies: WorkflowDependencies
    ) -> str:
        del dependencies
        section: AnalysisSection = self.analyzer(
            state.metrics, state.anomalies, state.hypotheses
        )
        state.analysis_sections.append(section)
        return (
            f"{section.title}：{len(section.findings)} 条独立结论，"
            f"状态 {section.status.value}"
        )


class InvestigateEarningsStage(_InvestigationStage):
    stage = ResearchStage.INVESTIGATE_EARNINGS
    title = "调查利润变化与核心盈利"
    description = "串联三年趋势、扣非差异、非经常性明细和利润变动桥"
    category = "研究调查"
    deliverable = "利润驱动、非经常性支撑与未解释差额"
    start_message = "正在拆解利润变化和非经常性损益"
    analyzer = staticmethod(investigate_earnings)


class InvestigateCashStage(_InvestigationStage):
    stage = ResearchStage.INVESTIGATE_CASH
    title = "调查经营现金流变化"
    description = "使用经营收付桥验证现金流变化，并检查营运资本线索"
    category = "研究调查"
    deliverable = "现金流收付驱动、营运资本线索和未决问题"
    start_message = "正在拆解经营现金流和营运资本变化"
    analyzer = staticmethod(investigate_cash_conversion)


class InvestigateCapitalStage(_InvestigationStage):
    stage = ResearchStage.INVESTIGATE_CAPITAL
    title = "调查资本回报与资产占用"
    description = "联合 ROE、净利率、平均资产周转和资产科目变化"
    category = "研究调查"
    deliverable = "资本回报驱动与资产占用线索"
    start_message = "正在调查资本回报和资产占用"
    analyzer = staticmethod(investigate_capital_returns)


class InvestigateNotesStage(_InvestigationStage):
    stage = ResearchStage.INVESTIGATE_NOTES
    title = "调查附注披露明细"
    description = "读取应收账龄、商誉和关联方交易附注，衡量集中度与相对规模"
    category = "研究调查"
    deliverable = "附注集中度结论与缺失的附注清单"
    start_message = "正在读取附注明细并衡量集中度"
    analyzer = staticmethod(investigate_notes)


class AnalyzePeersStage:
    stage = ResearchStage.ANALYZE_PEERS
    title = "执行同口径公司比较"
    description = "只对共同期间、共同概念进行横向比较，不生成综合评分"
    category = "研究调查"
    deliverable = "同口径差异与比较局限"
    start_message = "正在执行同期间、同口径公司比较"

    async def execute(
        self, state: ResearchState, dependencies: WorkflowDependencies
    ) -> str:
        del dependencies
        section = analyze_peers(state.metrics)
        state.analysis_sections.append(section)
        return f"{section.title}：{len(section.findings)} 条结论"


class ReviewDisclosuresStage:
    stage = ResearchStage.REVIEW_DISCLOSURES
    title = "审阅审计与披露约束"
    description = "将审计意见、关键审计事项和数据质量作为结论约束"
    category = "证据审阅"
    deliverable = "审计约束与数据质量问题"
    start_message = "正在审阅审计意见和数据质量约束"

    async def execute(
        self, state: ResearchState, dependencies: WorkflowDependencies
    ) -> str:
        del dependencies
        section = review_disclosures(
            state.metrics,
            state.validation_issues,
            state.evidence,
            state.documents,
        )
        state.analysis_sections.append(section)
        return f"披露审阅完成：{len(section.findings)} 条约束"


class SynthesizeResearchStage:
    stage = ResearchStage.ANALYZE
    title = "形成研究结论"
    description = "按研究问题合并重复事实，保留证据、反证和未决问题"
    category = "研究综合"
    deliverable = "按重要性排序的独立核心结论"
    start_message = "正在合并重复发现并形成研究结论"

    async def execute(
        self, state: ResearchState, dependencies: WorkflowDependencies
    ) -> str:
        del dependencies
        state.analysis = synthesize_research(
            state.metrics,
            state.analysis_sections,
            state.validation_issues,
            state.computations,
            state.anomalies,
            state.hypotheses,
        )
        return f"形成 {len(state.analysis['top_findings'])} 条独立核心结论"
