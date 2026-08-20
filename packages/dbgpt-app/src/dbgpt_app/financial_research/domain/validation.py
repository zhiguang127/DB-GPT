"""Deterministic domain validation gates for financial data."""

import hashlib
from collections import defaultdict
from typing import Iterable, List, Set

from .models import (
    MONETARY_UNITS,
    MONEY_UNITS,
    SUPPORTED_CURRENCIES,
    AnalysisSection,
    Computation,
    Evidence,
    FinancialMetric,
    IssueSeverity,
    MetricUnit,
    ParsedDocument,
    ValidationIssue,
)
from .periods import (
    is_valid_period,
    period_display_name,
    period_sort_key,
    previous_comparable_period,
)

REQUIRED_METRICS = ("revenue", "net_profit", "operating_cash_flow")
# These issues remain ERRORs in the audit trail, but cannot safely identify one
# concrete fact as the culprit:
#
# * normalization resolves ``cross_document_conflict`` with an explicit,
#   deterministic primary-selection rule;
# * an accounting identity mismatch proves that at least one operand is wrong,
#   but does not prove which one. Quarantining every operand would discard whole
#   statement groups (and their derived descendants) on ordinary disclosure
#   rounding or one bad extraction.
#
# They therefore remain visible research limitations instead of automatic
# metric-level quarantine signals. A later validator may emit a separate,
# attributable ERROR when it can identify the unsafe fact.
NON_BLOCKING_ERROR_CODES = frozenset(
    {
        "cross_document_conflict",
        "balance_sheet_assets_mismatch",
        "balance_sheet_liabilities_mismatch",
        "balance_sheet_equation_mismatch",
        "operating_cash_flow_mismatch",
        "cash_reconciliation_mismatch",
        "net_profit_attribution_mismatch",
    }
)


def _growth(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * 100


def blocked_metric_ids(
    metrics: Iterable[FinancialMetric],
    issues: Iterable[ValidationIssue],
    computations: Iterable[Computation] = (),
) -> Set[str]:
    """Return metric IDs that must not enter research analysis.

    Only an ``ERROR`` attached to a concrete metric is a blocking signal.
    Document-level completeness issues intentionally have no metric IDs and
    remain report limitations rather than invalidating every usable fact in
    the document.  Blocking is propagated through computation lineage so a
    derived metric cannot survive after one of its inputs has been rejected.
    """

    known_metric_ids = {metric.id for metric in metrics}
    blocked = {
        metric_id
        for issue in issues
        if issue.severity == IssueSeverity.ERROR
        and issue.code not in NON_BLOCKING_ERROR_CODES
        for metric_id in issue.metric_ids
        if metric_id in known_metric_ids
    }
    computation_list = list(computations)
    changed = True
    while changed:
        changed = False
        for computation in computation_list:
            if computation.metric_id not in known_metric_ids:
                continue
            if computation.metric_id in blocked or not blocked.intersection(
                computation.input_metric_ids
            ):
                continue
            blocked.add(computation.metric_id)
            changed = True
    return blocked


def validate_metrics(
    metrics: Iterable[FinancialMetric],
    evidence: Iterable[Evidence],
    documents: Iterable[ParsedDocument] = (),
    raw_metrics: Iterable[FinancialMetric] = (),
    computations: Iterable[Computation] = (),
) -> List[ValidationIssue]:
    metric_list = list(metrics)
    evidence_list = list(evidence)
    evidence_ids = {item.id for item in evidence_list}
    issues: List[ValidationIssue] = []
    document_table_ids = {
        table.id for document in documents for table in document.tables
    }
    evidence_by_id = {item.id: item for item in evidence_list}

    for metric in metric_list:
        missing = [item for item in metric.evidence_ids if item not in evidence_ids]
        if not metric.evidence_ids or missing:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    code="missing_evidence",
                    message=(
                        f"{metric.display_name} {metric.period} 缺少可解析的来源证据。"
                    ),
                    metric_ids=[metric.id],
                )
            )
        if metric.is_reported and metric.raw_value is None:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    code="missing_raw_value",
                    message=f"{metric.display_name} {metric.period} 缺少原始披露值。",
                    metric_ids=[metric.id],
                )
            )
        if (
            metric.unit in MONETARY_UNITS
            and metric.currency not in SUPPORTED_CURRENCIES
        ):
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    code="currency_missing",
                    message=(
                        f"{metric.display_name} {metric.period} 的币种口径 "
                        f"{metric.currency or '未标明'} 不在支持范围内。"
                    ),
                    metric_ids=[metric.id],
                )
            )
        if not is_valid_period(metric.period):
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    code="invalid_period",
                    message=(
                        f"{metric.display_name} 的期间 {metric.period} 无法标准化。"
                    ),
                    metric_ids=[metric.id],
                )
            )
        if metric.is_reported:
            for evidence_id in metric.evidence_ids:
                item = evidence_by_id.get(evidence_id)
                if item and (
                    item.table_id not in document_table_ids
                    or item.row_index is None
                    or item.column_index is None
                ):
                    issues.append(
                        ValidationIssue(
                            severity=IssueSeverity.ERROR,
                            code="incomplete_cell_lineage",
                            message=(
                                f"{metric.display_name} {metric.period} 的证据未定位到"
                                "已索引表格的行列。"
                            ),
                            metric_ids=[metric.id],
                        )
                    )

    computations_list = list(computations)
    metric_by_id = {item.id: item for item in metric_list}
    computation_by_metric = {item.metric_id: item for item in computations_list}
    for metric in metric_list:
        if not metric.is_reported and metric.id not in computation_by_metric:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    code="missing_computation_lineage",
                    message=f"派生指标 {metric.display_name} 缺少可复现计算记录。",
                    metric_ids=[metric.id],
                )
            )
    for computation in computations_list:
        output = metric_by_id.get(computation.metric_id)
        missing_inputs = [
            item for item in computation.input_metric_ids if item not in metric_by_id
        ]
        expected_hash = hashlib.sha256(
            (
                f"{computation.formula_id}|{computation.formula_version}|"
                f"{computation.expression}"
            ).encode("utf-8")
        ).hexdigest()
        if (
            output is None
            or missing_inputs
            or computation.program_hash != expected_hash
        ):
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    code="invalid_computation_lineage",
                    message=(
                        f"计算 {computation.formula_id} 的输出、输入或程序哈希不完整。"
                    ),
                    metric_ids=[
                        item
                        for item in [computation.metric_id, *missing_inputs]
                        if item
                    ],
                )
            )
        elif abs(output.value - computation.result) > 1e-9:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    code="computation_result_mismatch",
                    message=f"计算 {computation.formula_id} 的结果与派生事实不一致。",
                    metric_ids=[output.id],
                )
            )

    metrics_by_document = defaultdict(list)
    metrics_by_company = defaultdict(list)
    document_metric_list = list(raw_metrics) or metric_list
    for metric in document_metric_list:
        metrics_by_document[metric.document_id].append(metric)
    for metric in metric_list:
        metrics_by_company[metric.company_name].append(metric)

    for document in documents:
        if document.id not in metrics_by_document:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    code="document_without_metrics",
                    message=f"{document.file_name} 未抽取到任何结构化财务指标。",
                )
            )

    for company, company_metrics in metrics_by_company.items():
        available_names = {metric.name for metric in company_metrics}
        for required in REQUIRED_METRICS:
            if required not in available_names:
                issues.append(
                    ValidationIssue(
                        severity=IssueSeverity.ERROR,
                        code="required_metric_missing",
                        message=(
                            f"{company}的核心指标 {required} 未抽取到，"
                            "报告必须明确标为缺失。"
                        ),
                    )
                )

    grouped = defaultdict(list)
    for metric in metric_list:
        grouped[
            (
                metric.company_name,
                metric.name,
                metric.scope,
                tuple(sorted(metric.dimensions.items())),
            )
        ].append(metric)

    for (_company, _name, _scope, _dimensions), items in grouped.items():
        by_period = defaultdict(list)
        for item in items:
            by_period[item.period].append(item)
        for period, duplicates in by_period.items():
            distinct_values = {round(item.value, 8) for item in duplicates}
            if len(distinct_values) > 1:
                issues.append(
                    ValidationIssue(
                        severity=IssueSeverity.ERROR,
                        code="conflicting_values",
                        message=f"{duplicates[0].display_name} {period} 存在冲突值。",
                        metric_ids=[item.id for item in duplicates],
                    )
                )

        ordered = sorted(
            items, key=lambda item: period_sort_key(item.period), reverse=True
        )
        if len(ordered) < 2:
            continue
        current = ordered[0]
        comparable = previous_comparable_period(current.period)
        previous = next(
            (item for item in ordered[1:] if item.period == comparable), None
        )
        # Without a prior-year equivalent there is nothing to recompute against;
        # comparing an interim period to a full year would fabricate growth.
        if previous is None:
            continue
        recalculated = _growth(current.value, previous.value)
        reported = current.reported_growth_pct
        # Percentage facts report a percentage-point change; currency and
        # per-share facts report relative year-over-year growth.
        if (
            current.unit != MetricUnit.PERCENT
            and recalculated is not None
            and reported is not None
        ):
            delta = abs(recalculated - reported)
            if delta > 0.06:
                issues.append(
                    ValidationIssue(
                        severity=IssueSeverity.WARNING,
                        code="growth_mismatch",
                        message=(
                            f"{current.display_name}同比复算为 {recalculated:.2f}%，"
                            f"原表披露为 {reported:.2f}%，差异 {delta:.2f} 个百分点。"
                        ),
                        metric_ids=[current.id, previous.id],
                    )
                )

    # One company-period must be denominated in exactly one currency. Mixing
    # them would let a later formula divide HKD by CNY without an exchange rate.
    currencies_by_period = defaultdict(set)
    money_metrics_by_period = defaultdict(list)
    for metric in metric_list:
        if metric.unit not in MONEY_UNITS or not metric.currency:
            continue
        key = (metric.company_name, metric.period)
        currencies_by_period[key].add(metric.currency)
        money_metrics_by_period[key].append(metric)
    for (company, period), currencies in currencies_by_period.items():
        if len(currencies) > 1:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    code="currency_conflict",
                    message=(
                        f"{company} {period} 的货币金额同时出现 "
                        f"{'、'.join(sorted(currencies))} 多种币种，已阻止跨币种计算。"
                    ),
                    metric_ids=[
                        item.id for item in money_metrics_by_period[(company, period)]
                    ],
                )
            )

    facts_by_period: dict[tuple[str, str, object], dict[str, FinancialMetric]] = (
        defaultdict(dict)
    )
    for metric in metric_list:
        if metric.dimensions:
            continue
        facts_by_period[(metric.company_name, metric.period, metric.scope)][
            metric.name
        ] = metric

    def check_identity(
        values: dict,
        code: str,
        result_name: str,
        input_names: tuple[str, ...],
        signs: tuple[int, ...],
    ) -> None:
        result = values.get(result_name)
        inputs = [values.get(name) for name in input_names]
        if result is None or any(item is None for item in inputs):
            return
        expected = sum(
            sign * item.value for sign, item in zip(signs, inputs) if item is not None
        )
        tolerance = max(1.0, abs(result.value) * 1e-8)
        if abs(result.value - expected) > tolerance:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    code=code,
                    message=(
                        f"{result.company_name} {period_display_name(result.period)}的"
                        f"{result.display_name}勾稽不平，披露值 {result.value:,.2f}，"
                        f"按明细复算 {expected:,.2f}。"
                    ),
                    metric_ids=[result.id, *(item.id for item in inputs if item)],
                )
            )

    for period_facts in facts_by_period.values():
        check_identity(
            period_facts,
            "balance_sheet_assets_mismatch",
            "total_assets",
            ("current_assets", "non_current_assets"),
            (1, 1),
        )
        check_identity(
            period_facts,
            "balance_sheet_liabilities_mismatch",
            "total_liabilities",
            ("current_liabilities", "non_current_liabilities"),
            (1, 1),
        )
        check_identity(
            period_facts,
            "balance_sheet_equation_mismatch",
            "total_assets",
            ("total_liabilities", "total_equity"),
            (1, 1),
        )
        check_identity(
            period_facts,
            "operating_cash_flow_mismatch",
            "operating_cash_flow",
            ("operating_cash_inflow", "operating_cash_outflow"),
            (1, -1),
        )
        check_identity(
            period_facts,
            "cash_reconciliation_mismatch",
            "cash_at_end",
            ("cash_at_beginning", "net_increase_in_cash"),
            (1, 1),
        )
        check_identity(
            period_facts,
            "net_profit_attribution_mismatch",
            "net_profit_total",
            ("net_profit", "minority_profit"),
            (1, 1),
        )
        disclosed_non_recurring = period_facts.get("non_recurring_net_effect_reported")
        inferred_non_recurring = period_facts.get("non_recurring_net_effect")
        if disclosed_non_recurring and inferred_non_recurring:
            tolerance = max(1.0, abs(disclosed_non_recurring.value) * 1e-6)
            if (
                abs(disclosed_non_recurring.value - inferred_non_recurring.value)
                > tolerance
            ):
                issues.append(
                    ValidationIssue(
                        severity=IssueSeverity.WARNING,
                        code="non_recurring_effect_mismatch",
                        message=(
                            f"{disclosed_non_recurring.company_name} "
                            f"{period_display_name(disclosed_non_recurring.period)}"
                            "非经常性损益合计"
                            f"披露为 {disclosed_non_recurring.value:,.2f}，"
                            f"按归母净利润减扣非净利润推算为 "
                            f"{inferred_non_recurring.value:,.2f}。"
                        ),
                        metric_ids=[
                            disclosed_non_recurring.id,
                            inferred_non_recurring.id,
                        ],
                    )
                )

    referenced_evidence = {
        evidence_id for metric in metric_list for evidence_id in metric.evidence_ids
    }
    for item in evidence_list:
        if item.table_id and item.id not in referenced_evidence:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.INFO,
                    code="unused_evidence",
                    message=f"PDF 第 {item.page_number} 页的证据尚未绑定到指标。",
                )
            )
    return issues


def validate_findings(
    sections: Iterable[AnalysisSection],
    metrics: Iterable[FinancialMetric],
    evidence: Iterable[Evidence],
) -> List[ValidationIssue]:
    """Reject financial findings that lost their fact or source lineage."""

    metric_by_id = {item.id: item for item in metrics}
    evidence_ids = {item.id for item in evidence}
    issues: List[ValidationIssue] = []
    for section in sections:
        for finding in section.findings:
            missing_metrics = [
                item for item in finding.metric_ids if item not in metric_by_id
            ]
            missing_evidence = [
                item for item in finding.evidence_ids if item not in evidence_ids
            ]
            if missing_metrics or missing_evidence:
                issues.append(
                    ValidationIssue(
                        severity=IssueSeverity.ERROR,
                        code="invalid_finding_lineage",
                        message=f"结论“{finding.title}”引用了不存在的事实或证据。",
                        metric_ids=finding.metric_ids,
                    )
                )
                continue
            is_system_quality_finding = finding.title == "数据质量风险"
            if (
                not is_system_quality_finding
                and not finding.metric_ids
                and not finding.evidence_ids
            ):
                issues.append(
                    ValidationIssue(
                        severity=IssueSeverity.ERROR,
                        code="unsupported_finding",
                        message=f"结论“{finding.title}”没有事实、计算或原文证据。",
                    )
                )
            if finding.metric_ids and not finding.evidence_ids:
                issues.append(
                    ValidationIssue(
                        severity=IssueSeverity.ERROR,
                        code="finding_without_citation",
                        message=f"结论“{finding.title}”引用了事实但没有来源证据。",
                        metric_ids=finding.metric_ids,
                    )
                )
    return issues
