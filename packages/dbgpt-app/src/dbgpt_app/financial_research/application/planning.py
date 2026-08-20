"""Constrained task planning for the PDF financial-research agent."""

from pathlib import Path
from typing import Sequence

from ..domain.models import ResearchMode, ResearchRequest, ResearchStage
from .stages.analysis import (
    AnalyzePeersStage,
    DetectAnomaliesStage,
    InvestigateCapitalStage,
    InvestigateCashStage,
    InvestigateEarningsStage,
    InvestigateNotesStage,
    ReviewDisclosuresStage,
    SynthesizeResearchStage,
)
from .stages.base import WorkflowStage
from .stages.delivery import (
    GenerateChartsStage,
    NarrateFindingsStage,
    RenderReportStage,
)
from .stages.ingestion import (
    ExtractMetricsStage,
    NormalizeMetricsStage,
    ParseDocumentsStage,
)
from .stages.intake import InitializeSourcesStage
from .stages.reasoning import (
    CrossCheckExtractionStage,
    DeriveMetricsStage,
    ValidateMetricsStage,
    VerifyFindingsStage,
)

PEER_TERMS = ("对比", "比较", "同行", "横向")


class ResearchTaskPlanner:
    """Select from audited task types; never invent executable tool calls."""

    @staticmethod
    def mode_for(request: ResearchRequest) -> ResearchMode:
        if request.requested_mode:
            return request.requested_mode
        unique_files = {
            str(Path(item).expanduser().resolve()) for item in request.file_paths
        }
        if len(unique_files) > 1 or any(
            term in request.question for term in PEER_TERMS
        ):
            return ResearchMode.MULTI_COMPANY
        return ResearchMode.SINGLE_COMPANY

    def plan(
        self,
        request: ResearchRequest,
        actual_mode: ResearchMode | None = None,
    ) -> tuple[WorkflowStage, ...]:
        stages: list[WorkflowStage] = [
            InitializeSourcesStage(),
            ParseDocumentsStage(),
            ExtractMetricsStage(),
            NormalizeMetricsStage(),
            DeriveMetricsStage(),
            ValidateMetricsStage(),
            # The second table reading only constrains facts that were already
            # selected, so it runs after validation rather than replacing it.
            CrossCheckExtractionStage(),
            DetectAnomaliesStage(),
            InvestigateEarningsStage(),
            InvestigateCashStage(),
            InvestigateCapitalStage(),
            InvestigateNotesStage(),
        ]
        requested_peer_analysis = any(term in request.question for term in PEER_TERMS)
        planned_mode = request.requested_mode or actual_mode or self.mode_for(request)
        if planned_mode == ResearchMode.MULTI_COMPANY or requested_peer_analysis:
            stages.append(AnalyzePeersStage())
        stages.extend(
            [
                ReviewDisclosuresStage(),
                VerifyFindingsStage(),
                SynthesizeResearchStage(),
            ]
        )
        if request.enable_narration:
            # Narration reads finished findings and writes only display text, so
            # it sits after synthesis and before any artifact is rendered.
            stages.append(NarrateFindingsStage())
        stages.extend([GenerateChartsStage(), RenderReportStage()])
        return tuple(stages)

    @staticmethod
    def dependencies(
        stages: Sequence[WorkflowStage],
    ) -> dict[ResearchStage, list[ResearchStage]]:
        selected = {stage.stage for stage in stages}
        dependencies: dict[ResearchStage, list[ResearchStage]] = {
            ResearchStage.INITIALIZE: [],
            ResearchStage.PARSE: [ResearchStage.INITIALIZE],
            ResearchStage.EXTRACT: [ResearchStage.PARSE],
            ResearchStage.NORMALIZE: [ResearchStage.EXTRACT],
            ResearchStage.DERIVE: [ResearchStage.NORMALIZE],
            ResearchStage.VALIDATE: [ResearchStage.DERIVE],
        }
        if ResearchStage.CROSS_CHECK in selected:
            dependencies[ResearchStage.CROSS_CHECK] = [ResearchStage.VALIDATE]
            investigation_root = ResearchStage.CROSS_CHECK
        else:
            investigation_root = ResearchStage.VALIDATE
        investigation_stages = [
            item
            for item in (
                ResearchStage.INVESTIGATE_EARNINGS,
                ResearchStage.INVESTIGATE_CASH,
                ResearchStage.INVESTIGATE_CAPITAL,
                ResearchStage.INVESTIGATE_NOTES,
                ResearchStage.ANALYZE_PEERS,
            )
            if item in selected
        ]
        dependencies[ResearchStage.DETECT_ANOMALIES] = [investigation_root]
        for item in investigation_stages:
            dependencies[item] = [ResearchStage.DETECT_ANOMALIES]
        dependencies[ResearchStage.REVIEW_DISCLOSURES] = investigation_stages
        dependencies[ResearchStage.VERIFY_FINDINGS] = [ResearchStage.REVIEW_DISCLOSURES]
        dependencies[ResearchStage.ANALYZE] = [ResearchStage.VERIFY_FINDINGS]
        if ResearchStage.NARRATE in selected:
            dependencies[ResearchStage.NARRATE] = [ResearchStage.ANALYZE]
            dependencies[ResearchStage.VISUALIZE] = [ResearchStage.NARRATE]
        else:
            dependencies[ResearchStage.VISUALIZE] = [ResearchStage.ANALYZE]
        dependencies[ResearchStage.RENDER] = [ResearchStage.VISUALIZE]
        return dependencies
