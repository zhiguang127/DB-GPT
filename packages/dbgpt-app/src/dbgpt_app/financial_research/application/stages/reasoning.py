"""Validation and deterministic financial-analysis stages."""

from ...domain.cross_check import cross_check_extraction
from ...domain.derivation import derive_metrics_with_lineage
from ...domain.models import ResearchStage, ResearchState
from ...domain.validation import (
    blocked_metric_ids,
    validate_findings,
    validate_metrics,
)
from ...ports.workflow import WorkflowDependencies


class DeriveMetricsStage:
    stage = ResearchStage.DERIVE
    title = "计算派生指标"
    description = "基于已核验输入计算净利率、现金利润比和资产周转率"
    category = "财务建模"
    deliverable = "带计算口径与底层证据的派生指标"
    start_message = "正在计算可复核的盈利能力和现金质量指标"

    async def execute(
        self, state: ResearchState, dependencies: WorkflowDependencies
    ) -> str:
        del dependencies
        derived, computations = derive_metrics_with_lineage(state.metrics)
        state.metrics.extend(derived)
        state.computations.extend(computations)
        return (
            f"已生成 {len(derived)} 条派生指标和 {len(computations)} 条可复现计算记录"
        )


class ValidateMetricsStage:
    stage = ResearchStage.VALIDATE
    title = "校验和复算"
    description = "逐公司检查核心指标、来源证据、冲突值和同比计算，并隔离错误事实"
    category = "证据审计"
    deliverable = "数据质量、证据完整性、同比复算与错误指标隔离结果"
    start_message = "正在逐公司复算同比并检查证据完整性"

    async def execute(
        self, state: ResearchState, dependencies: WorkflowDependencies
    ) -> str:
        del dependencies
        issues = validate_metrics(
            state.metrics,
            state.evidence,
            state.documents,
            raw_metrics=state.raw_metrics,
            computations=state.computations,
        )
        state.validation_issues.extend(issues)
        blocked = blocked_metric_ids(
            state.metrics,
            state.validation_issues,
            state.computations,
        )
        if blocked:
            state.excluded_metric_ids = list(
                dict.fromkeys(
                    [
                        *state.excluded_metric_ids,
                        *(
                            metric.id
                            for metric in state.metrics
                            if metric.id in blocked
                        ),
                    ]
                )
            )
            state.metrics = [
                metric for metric in state.metrics if metric.id not in blocked
            ]
            state.computations = [
                computation
                for computation in state.computations
                if computation.metric_id not in blocked
                and not blocked.intersection(computation.input_metric_ids)
            ]
        return (
            f"校验完成，新增 {len(issues)} 个提示；"
            f"隔离 {len(blocked)} 条错误指标，文档级缺项保留为研究限制"
        )


class CrossCheckExtractionStage:
    stage = ResearchStage.CROSS_CHECK
    title = "交叉核对表格识别"
    description = "用表格线识别结果复核文本版式识别的每个已采用数值"
    category = "证据审计"
    deliverable = "双策略识别一致性结果与需人工复核清单"
    start_message = "正在用第二种表格识别策略复核已采用数值"

    async def execute(
        self, state: ResearchState, dependencies: WorkflowDependencies
    ) -> str:
        del dependencies
        issues = cross_check_extraction(state.documents, state.metrics, state.evidence)
        state.validation_issues.extend(issues)
        disagreements = sum(
            issue.code == "extraction_strategy_disagreement" for issue in issues
        )
        if not issues:
            return "双策略识别结果一致，未发现数值分歧"
        if disagreements:
            return f"发现 {disagreements} 处两种识别策略结果不一致，已标记人工复核"
        return "未能建立双策略对照，已在报告中标注该限制"


class VerifyFindingsStage:
    stage = ResearchStage.VERIFY_FINDINGS
    title = "验证研究结论"
    description = "检查每条结论引用的事实、计算和原文证据是否完整"
    category = "证据审计"
    deliverable = "结论级引用覆盖与断链检查结果"
    start_message = "正在验证研究结论与底层事实、来源证据的连接"

    async def execute(
        self, state: ResearchState, dependencies: WorkflowDependencies
    ) -> str:
        del dependencies
        issues = validate_findings(
            state.analysis_sections,
            state.metrics,
            state.evidence,
        )
        state.validation_issues.extend(issues)
        if issues:
            raise ValueError("研究结论验证失败：存在未绑定事实或来源证据的结论。")
        return f"结论验证完成：发现 {len(issues)} 个引用问题"
