"""Metric identity normalization and cross-document conflict handling."""

import re
from collections import defaultdict
from typing import Iterable, List, Tuple

from .models import (
    FinancialMetric,
    IssueSeverity,
    ParsedDocument,
    StatementType,
    ValidationIssue,
)
from .periods import period_display_name


def canonical_company_name(value: str) -> str:
    """Remove layout noise without collapsing legally distinct company names."""
    return re.sub(r"\s+", "", value).strip("-_—")


def identified_company_names(
    metrics: Iterable[FinancialMetric] = (),
    documents: Iterable[ParsedDocument] = (),
) -> List[str]:
    """Return company identities found in either documents or usable facts."""

    names = {
        canonical_company_name(value)
        for value in [
            *(metric.company_name for metric in metrics),
            *(document.company_name or "" for document in documents),
        ]
        if canonical_company_name(value)
    }
    return sorted(names)


def normalize_metrics(
    metrics: Iterable[FinancialMetric],
) -> Tuple[List[FinancialMetric], List[ValidationIssue]]:
    """Produce one comparable observation per company, period, scope and metric.

    Identical observations are merged and retain all evidence references. Conflicting
    observations remain in ``raw_metrics`` and are reported as errors. The analytical
    primary is selected by disclosed precedence (restated, full statement, confidence)
    rather than by file order.
    """
    grouped = defaultdict(list)
    for metric in metrics:
        company = canonical_company_name(metric.company_name)
        normalized = metric.model_copy(update={"company_name": company})
        grouped[
            (
                company,
                metric.period,
                metric.name,
                metric.scope,
                metric.period_type,
                tuple(sorted(metric.dimensions.items())),
            )
        ].append(normalized)

    normalized_metrics: List[FinancialMetric] = []
    issues: List[ValidationIssue] = []
    for (
        company,
        period,
        _name,
        _scope,
        _period_type,
        _dimensions,
    ), items in grouped.items():
        primary = max(
            items,
            key=lambda item: (
                item.is_restated,
                item.statement_type != StatementType.SUMMARY,
                item.confidence,
                len(item.evidence_ids),
                item.document_id,
            ),
        )
        currencies = {item.currency for item in items if item.currency}
        if len(currencies) > 1:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    code="currency_conflict",
                    message=(
                        f"{company} {period} {primary.display_name} 在不同来源中的"
                        f"币种不一致（{'、'.join(sorted(currencies))}），"
                        "已阻止自动换算。"
                    ),
                    metric_ids=[item.id for item in items],
                )
            )

        units = {item.unit for item in items}
        if len(units) > 1:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    code="unit_conflict",
                    message=(
                        f"{company} {period_display_name(period)} "
                        f"{primary.display_name} 存在单位冲突，"
                        "已阻止自动换算。"
                    ),
                    metric_ids=[item.id for item in items],
                )
            )

        values = {round(item.value, 8) for item in items}
        if len(values) > 1:
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.ERROR,
                    code="cross_document_conflict",
                    message=(
                        f"{company} {period_display_name(period)} "
                        f"{primary.display_name} 在多份财报中"
                        "存在冲突值；原始值均已保留，分析按重述状态、"
                        "完整报表和置信度顺序选择主值。"
                    ),
                    metric_ids=[item.id for item in items],
                )
            )

        evidence_ids = list(
            dict.fromkeys(
                evidence_id for item in items for evidence_id in item.evidence_ids
            )
        )
        normalized_metrics.append(
            primary.model_copy(update={"evidence_ids": evidence_ids})
        )

    return normalized_metrics, issues
