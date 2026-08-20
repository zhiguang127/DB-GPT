"""Agreement check between the two independent table readings.

The text-layout reader assigns columns positionally, so a shifted or merged
column moves a figure into the wrong period without raising anything. The
geometry reader derives cells from drawn rulings instead, and fails differently.

Comparing them turns a silent misread into a reported warning. Disagreement is
never resolved automatically: the disclosed text reading is kept as the primary
value and the conflict is surfaced, because picking a winner without a rule
would just relocate the silent failure.
"""

import re
from typing import Dict, Iterable, List, Optional, Tuple

from .models import (
    Evidence,
    FinancialMetric,
    IssueSeverity,
    ParsedDocument,
    ValidationIssue,
)

# Values are compared as parsed numbers, not strings, so "1,234.00" and
# "1234.0" agree. A relative tolerance absorbs the last-digit differences that
# come from OCR-adjacent glyph rendering without hiding real column shifts.
_RELATIVE_TOLERANCE = 1e-6
_ABSOLUTE_TOLERANCE = 0.01


def _normalize_label(value: str) -> str:
    value = re.sub(r"\s+", "", value or "")
    value = re.sub(r"^[一二三四五六七八九十]+[、.]", "", value)
    value = value.replace("其中：", "").replace("其中:", "")
    return re.sub(r"[（）()：:，,。]", "", value)


def _parse_number(token: str) -> Optional[float]:
    if not token:
        return None
    cleaned = (
        token.replace(",", "")
        .replace("−", "-")
        .replace("－", "-")
        .replace("%", "")
        .strip()
    )
    # Accounting negatives are parenthesised.
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = f"-{cleaned[1:-1]}"
    try:
        return float(cleaned)
    except ValueError:
        return None


def _values_agree(left: float, right: float) -> bool:
    difference = abs(left - right)
    if difference <= _ABSOLUTE_TOLERANCE:
        return True
    scale = max(abs(left), abs(right))
    return difference <= scale * _RELATIVE_TOLERANCE


def _geometry_index(
    document: ParsedDocument,
) -> Dict[Tuple[int, str, str], str]:
    """Map (page, normalized label, column label) to the geometry raw value."""

    index: Dict[Tuple[int, str, str], str] = {}
    for table in document.geometric_tables:
        for row in table.rows:
            label = _normalize_label(row.label)
            if not label:
                continue
            for value in row.values:
                key = (value.page_number, label, value.column_label)
                # First reading wins: a repeated label on one page cannot be
                # disambiguated without the row heading, so no claim is made.
                index.setdefault(key, value.raw_value)
    return index


def cross_check_extraction(
    documents: Iterable[ParsedDocument],
    metrics: Iterable[FinancialMetric],
    evidence: Iterable[Evidence],
) -> List[ValidationIssue]:
    """Report reported facts whose two readings disagree.

    Only facts that both readers located are compared. A fact the geometry
    reader never saw produces nothing: absence of a second reading is not
    evidence against the first.
    """
    documents_by_id = {document.id: document for document in documents}
    indexes = {
        document_id: _geometry_index(document)
        for document_id, document in documents_by_id.items()
        if document.geometric_tables
    }
    if not indexes:
        return []

    evidence_by_id = {item.id: item for item in evidence}
    issues: List[ValidationIssue] = []
    compared = 0
    for metric in metrics:
        if not metric.is_reported:
            continue
        index = indexes.get(metric.document_id)
        if not index:
            continue
        for evidence_id in metric.evidence_ids:
            item = evidence_by_id.get(evidence_id)
            if item is None or item.row_label is None or item.column_label is None:
                continue
            key = (
                item.page_number,
                _normalize_label(item.row_label),
                item.column_label,
            )
            geometry_raw = index.get(key)
            if geometry_raw is None:
                continue
            primary = _parse_number(item.cell_value or "")
            secondary = _parse_number(geometry_raw)
            if primary is None or secondary is None:
                continue
            compared += 1
            if _values_agree(primary, secondary):
                continue
            issues.append(
                ValidationIssue(
                    severity=IssueSeverity.WARNING,
                    code="extraction_strategy_disagreement",
                    message=(
                        f"{metric.display_name} {metric.period} 的两种表格识别结果"
                        f"不一致：文本版式识别为 {item.cell_value}，"
                        f"表格线识别为 {geometry_raw}（PDF 第 "
                        f"{item.page_number} 页）。已保留文本识别值，请人工复核。"
                    ),
                    metric_ids=[metric.id],
                )
            )
    if compared == 0:
        issues.append(
            ValidationIssue(
                severity=IssueSeverity.INFO,
                code="cross_check_not_applicable",
                message=(
                    "表格线识别未覆盖任何已采用事实，本次未能进行双策略交叉核对。"
                ),
            )
        )
    return issues
