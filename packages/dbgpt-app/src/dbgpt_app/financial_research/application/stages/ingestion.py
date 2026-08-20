"""Document parsing, extraction, and normalization stages."""

import asyncio

from ...domain.models import ResearchMode, ResearchStage, ResearchState
from ...domain.normalization import normalize_metrics
from ...ports.workflow import WorkflowDependencies


class ParseDocumentsStage:
    stage = ResearchStage.PARSE
    title = "解析财报"
    description = "并行解析所有财报并保留物理页码"
    category = "资料准备"
    deliverable = "带物理页码的文档语料"
    start_message = "正在并行解析财报并保留物理页码"

    async def execute(
        self, state: ResearchState, dependencies: WorkflowDependencies
    ) -> str:
        # `True` opts this request into OCR; `None` leaves the decision to the
        # adapter default (environment-configured), so the flag can only widen
        # what is attempted, never silently disable a configured backend.
        ocr_override = True if state.request.enable_ocr else None
        state.documents = await asyncio.gather(
            *(
                asyncio.to_thread(dependencies.parse_document, source, ocr_override)
                for source in state.sources
            )
        )
        scanned = sum(document.ocr_page_count > 0 for document in state.documents)
        if scanned:
            return (
                f"已解析 {len(state.documents)} 份文档，其中 {scanned} 份使用 OCR "
                "识别，相关证据置信度已下调"
            )
        return f"已解析 {len(state.documents)} 份文档"


class ExtractMetricsStage:
    stage = ResearchStage.EXTRACT
    title = "抽取指标与证据"
    description = "从原始披露表抽取指标，并绑定页码级证据"
    category = "数据工程"
    deliverable = "原始指标表与页码证据索引"
    start_message = "正在从原表抽取指标和证据"

    async def execute(
        self, state: ResearchState, dependencies: WorkflowDependencies
    ) -> str:
        results = await asyncio.gather(
            *(
                asyncio.to_thread(dependencies.extract_document, document)
                for document in state.documents
            )
        )
        for evidence, metrics in results:
            state.evidence.extend(evidence)
            state.raw_metrics.extend(metrics)
        return (
            f"已抽取 {len(state.raw_metrics)} 条原始指标、{len(state.evidence)} 条证据"
        )


class NormalizeMetricsStage:
    stage = ResearchStage.NORMALIZE
    title = "统一指标口径"
    description = "按公司、期间和指标归一化，并识别跨文档冲突"
    category = "数据工程"
    deliverable = "跨公司可比指标集与冲突清单"
    start_message = "正在统一公司、期间、指标和单位口径"

    async def execute(
        self, state: ResearchState, dependencies: WorkflowDependencies
    ) -> str:
        del dependencies
        state.metrics, issues = normalize_metrics(state.raw_metrics)
        state.validation_issues.extend(issues)
        companies = {metric.company_name for metric in state.metrics}
        state.mode = (
            ResearchMode.MULTI_COMPANY
            if len(companies) > 1
            else ResearchMode.SINGLE_COMPANY
        )
        return (
            f"已形成 {len(state.metrics)} 条可比指标，识别 "
            f"{len(companies)} 家公司、{len(issues)} 个口径冲突"
        )
