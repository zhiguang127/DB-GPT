"""Narration, chart and traceable-report delivery stages."""

import logging

from ...domain.models import ResearchStage, ResearchState
from ...domain.narration import apply_narratives, finding_prompt_payload
from ...ports.workflow import WorkflowDependencies

logger = logging.getLogger(__name__)


class NarrateFindingsStage:
    stage = ResearchStage.NARRATE
    title = "生成受约束的结论叙述"
    description = "仅基于已验证结论和原文证据撰写文字，不引入任何新数字"
    category = "研究交付"
    deliverable = "通过数字校验的结论叙述"
    start_message = "正在基于已验证事实生成结论叙述"

    async def execute(
        self, state: ResearchState, dependencies: WorkflowDependencies
    ) -> str:
        if dependencies.narrate is None:
            return "未配置叙述适配器，报告仅保留确定性结论文本"
        findings = [
            finding
            for section in state.analysis_sections
            for finding in section.findings
        ]
        if not findings:
            return "没有可供叙述的结论"
        evidence_by_id = {item.id: item for item in state.evidence}
        payloads = [
            finding_prompt_payload(finding, evidence_by_id) for finding in findings
        ]
        try:
            narratives = dependencies.narrate(payloads, state.request.locale)
        except Exception as exc:
            # Narration is additive. A narrator failure must not discard a
            # complete, evidence-backed report.
            logger.warning("Financial research narration failed: %s", exc)
            return f"叙述生成失败，已保留确定性结论文本：{exc}"
        rejected = apply_narratives(findings, narratives or {}, state.evidence)
        accepted = sum(1 for finding in findings if finding.narrative)
        # `synthesize_research` has already serialized the findings, so the
        # headline copies must be refreshed for the narrative to reach the
        # report.
        narrative_by_id = {
            finding.id: finding.narrative for finding in findings if finding.narrative
        }
        for item in state.analysis.get("top_findings", []):
            if item.get("id") in narrative_by_id:
                item["narrative"] = narrative_by_id[item["id"]]
        for section in state.analysis.get("sections", []):
            for item in section.get("findings", []):
                if item.get("id") in narrative_by_id:
                    item["narrative"] = narrative_by_id[item["id"]]
        return (
            f"叙述生成完成：{accepted} 条通过数字校验，"
            f"{len(rejected)} 条因引入未经验证数字被丢弃"
        )


class GenerateChartsStage:
    stage = ResearchStage.VISUALIZE
    title = "生成图表"
    description = "按研究模式生成单公司趋势图或多公司对比图"
    category = "研究交付"
    deliverable = "可复现的 SVG 分析图表"
    start_message = "正在生成确定性 SVG 图表"

    async def execute(
        self, state: ResearchState, dependencies: WorkflowDependencies
    ) -> str:
        state.charts = dependencies.generate_charts(
            state.metrics, state.request.resolved_output_dir()
        )
        return f"已生成 {len(state.charts)} 张图表"


class RenderReportStage:
    stage = ResearchStage.RENDER
    title = "生成引用报告"
    description = "渲染包含研究计划、质量提示、图表和来源索引的 HTML 报告"
    category = "研究交付"
    deliverable = "完整可追溯 HTML 研究报告"
    start_message = "正在生成带页码引用的 HTML 报告"

    async def execute(
        self, state: ResearchState, dependencies: WorkflowDependencies
    ) -> str:
        state.report = dependencies.render_report(
            state, state.request.resolved_output_dir()
        )
        return "HTML 报告生成完成"
