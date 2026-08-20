"""Workflow-order and safety-gate tests for financial research."""

import hashlib

import pytest

from dbgpt_app.financial_research.application.planning import ResearchTaskPlanner
from dbgpt_app.financial_research.application.stages.ingestion import (
    NormalizeMetricsStage,
)
from dbgpt_app.financial_research.application.stages.reasoning import (
    ValidateMetricsStage,
)
from dbgpt_app.financial_research.domain.models import (
    Computation,
    FinancialMetric,
    IssueSeverity,
    MetricUnit,
    ParsedDocument,
    ResearchMode,
    ResearchRequest,
    ResearchStage,
    ResearchState,
    ValidationIssue,
)


def _metric(metric_id: str, name: str, *, is_reported: bool = True) -> FinancialMetric:
    return FinancialMetric(
        id=metric_id,
        document_id="document",
        company_name="示例公司",
        period="2019",
        name=name,
        display_name=name,
        value=100.0,
        raw_value="100.0" if is_reported else None,
        unit=MetricUnit.CNY,
        currency="CNY",
        evidence_ids=["evidence"],
        is_reported=is_reported,
    )


def test_cross_check_precedes_derivation_and_final_validation():
    planner = ResearchTaskPlanner()
    stages = planner.plan(ResearchRequest())
    stage_names = [stage.stage for stage in stages]

    assert stage_names.index(ResearchStage.NORMALIZE) < stage_names.index(
        ResearchStage.CROSS_CHECK
    )
    assert stage_names.index(ResearchStage.CROSS_CHECK) < stage_names.index(
        ResearchStage.DERIVE
    )
    assert stage_names.index(ResearchStage.DERIVE) < stage_names.index(
        ResearchStage.VALIDATE
    )

    dependencies = planner.dependencies(stages)
    assert dependencies[ResearchStage.CROSS_CHECK] == [ResearchStage.NORMALIZE]
    assert dependencies[ResearchStage.DERIVE] == [ResearchStage.CROSS_CHECK]
    assert dependencies[ResearchStage.VALIDATE] == [ResearchStage.DERIVE]
    assert dependencies[ResearchStage.DETECT_ANOMALIES] == [ResearchStage.VALIDATE]


@pytest.mark.asyncio
async def test_validation_gate_excludes_error_metric_and_derived_descendants(
    monkeypatch,
):
    from dbgpt_app.financial_research.application.stages import reasoning

    bad_input = _metric("bad-input", "revenue")
    good_input = _metric("good-input", "net_profit")
    derived = _metric("derived", "net_margin", is_reported=False)
    expression = "net_profit / revenue * 100"
    computation = Computation(
        metric_id=derived.id,
        formula_id=derived.name,
        expression=expression,
        input_metric_ids=[good_input.id, bad_input.id],
        result=derived.value,
        program_hash=hashlib.sha256(
            f"{derived.name}|1.0|{expression}".encode("utf-8")
        ).hexdigest(),
    )
    state = ResearchState(
        request=ResearchRequest(),
        metrics=[bad_input, good_input, derived],
        computations=[computation],
        validation_issues=[
            ValidationIssue(
                severity=IssueSeverity.ERROR,
                code="bad_reported_fact",
                message="错误事实",
                metric_ids=[bad_input.id],
            ),
            ValidationIssue(
                severity=IssueSeverity.ERROR,
                code="document_without_metrics",
                message="另一份文档未抽取到指标",
            ),
            ValidationIssue(
                severity=IssueSeverity.WARNING,
                code="review_good_fact",
                message="提示人工复核",
                metric_ids=[good_input.id],
            ),
        ],
    )
    monkeypatch.setattr(reasoning, "validate_metrics", lambda *args, **kwargs: [])

    message = await ValidateMetricsStage().execute(state, object())

    assert [metric.id for metric in state.metrics] == [good_input.id]
    assert state.computations == []
    assert state.excluded_metric_ids == [bad_input.id, derived.id]
    assert "隔离 2 条错误指标" in message


@pytest.mark.asyncio
async def test_validation_gate_keeps_metrics_for_document_level_errors(
    monkeypatch,
):
    from dbgpt_app.financial_research.application.stages import reasoning

    metric = _metric("usable", "revenue")
    state = ResearchState(
        request=ResearchRequest(),
        metrics=[metric],
        validation_issues=[
            ValidationIssue(
                severity=IssueSeverity.ERROR,
                code="required_metric_missing",
                message="核心指标缺失",
            )
        ],
    )
    monkeypatch.setattr(reasoning, "validate_metrics", lambda *args, **kwargs: [])

    await ValidateMetricsStage().execute(state, object())

    assert state.metrics == [metric]
    assert state.excluded_metric_ids == []


@pytest.mark.asyncio
async def test_validation_gate_keeps_deterministically_selected_conflict_primary(
    monkeypatch,
):
    from dbgpt_app.financial_research.application.stages import reasoning

    selected_primary = _metric("selected-primary", "revenue")
    derived = _metric("derived", "revenue_copy", is_reported=False)
    expression = "revenue"
    computation = Computation(
        metric_id=derived.id,
        formula_id=derived.name,
        expression=expression,
        input_metric_ids=[selected_primary.id],
        result=derived.value,
        program_hash=hashlib.sha256(
            f"{derived.name}|1.0|{expression}".encode("utf-8")
        ).hexdigest(),
    )
    state = ResearchState(
        request=ResearchRequest(),
        metrics=[selected_primary, derived],
        computations=[computation],
        validation_issues=[
            ValidationIssue(
                severity=IssueSeverity.ERROR,
                code="cross_document_conflict",
                message="已按确定性优先级选择主值",
                metric_ids=[selected_primary.id, "unselected-raw-value"],
            )
        ],
    )
    monkeypatch.setattr(reasoning, "validate_metrics", lambda *args, **kwargs: [])

    await ValidateMetricsStage().execute(state, object())

    assert state.metrics == [selected_primary, derived]
    assert state.computations == [computation]
    assert state.excluded_metric_ids == []


@pytest.mark.asyncio
async def test_validation_gate_does_not_quarantine_ambiguous_identity_operands(
    monkeypatch,
):
    from dbgpt_app.financial_research.application.stages import reasoning

    total_assets = _metric("total-assets", "total_assets")
    total_liabilities = _metric("total-liabilities", "total_liabilities")
    total_equity = _metric("total-equity", "total_equity")
    metrics = [total_assets, total_liabilities, total_equity]
    state = ResearchState(
        request=ResearchRequest(),
        metrics=metrics,
        validation_issues=[
            ValidationIssue(
                severity=IssueSeverity.ERROR,
                code="balance_sheet_equation_mismatch",
                message="资产不等于负债加权益，但无法定位错误项",
                metric_ids=[metric.id for metric in metrics],
            )
        ],
    )
    monkeypatch.setattr(reasoning, "validate_metrics", lambda *args, **kwargs: [])

    await ValidateMetricsStage().execute(state, object())

    assert state.metrics == metrics
    assert state.excluded_metric_ids == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("second_company", "expected_mode"),
    [
        ("示例B公司", ResearchMode.MULTI_COMPANY),
        (None, ResearchMode.MULTI_COMPANY),
        ("示例A公司", ResearchMode.SINGLE_COMPANY),
    ],
)
async def test_normalization_infers_mode_without_collapsing_unknown_documents(
    second_company,
    expected_mode,
):
    first = ParsedDocument(
        id="document-a",
        source_id="source-a",
        file_name="a.pdf",
        media_type="application/pdf",
        company_name="示例A公司",
    )
    second = ParsedDocument(
        id="document-b",
        source_id="source-b",
        file_name="b.pdf",
        media_type="application/pdf",
        company_name=second_company,
    )
    only_metric = _metric("metric-a", "revenue").model_copy(
        update={"document_id": first.id, "company_name": "示例A公司"}
    )
    state = ResearchState(
        request=ResearchRequest(file_paths=["a.pdf", "b.pdf"]),
        mode=ResearchMode.MULTI_COMPANY,
        documents=[first, second],
        raw_metrics=[only_metric],
    )

    await NormalizeMetricsStage().execute(state, object())

    assert state.mode == expected_mode
