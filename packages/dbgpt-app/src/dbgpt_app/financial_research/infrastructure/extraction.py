"""Evidence-first extraction from indexed annual-report tables."""

import re
from typing import Iterable, List, Optional, Sequence, Tuple

from ..domain.metric_catalog import METRIC_SPECS, SUMMARY_METRIC_SPECS, MetricSpec
from ..domain.models import (
    MONETARY_UNITS,
    UNSCALED_UNITS,
    ConsolidationScope,
    DocumentSection,
    Evidence,
    FinancialMetric,
    MetricUnit,
    ParsedDocument,
    ParsedTable,
    ParsedTableRow,
    StatementType,
)

NUMBER_RE = re.compile(r"(?<![\d])[-−－]?\d[\d,]*(?:\.\d+)?%?")

# Text recognized by OCR is not disclosed text: a misread digit group changes a
# figure with no other signal. Evidence from such pages is capped well below the
# digital-text confidence so downstream ranking can prefer disclosed values.
OCR_CONFIDENCE = 0.75


def _parse_number(token: str, scale: float = 1.0) -> float:
    cleaned = (
        token.replace(",", "").replace("−", "-").replace("－", "-").removesuffix("%")
    )
    return float(cleaned) * scale


def _normalized_label(value: str) -> str:
    value = re.sub(r"\s+", "", value)
    value = re.sub(r"^(?:[一二三四五六七八九十]+|\d+)[、.]", "", value)
    value = value.replace("其中：", "").replace("其中:", "")
    return re.sub(r"[（）()：:，,。]", "", value)


def _match_spec(row_label: str, specs: Sequence[MetricSpec]) -> Optional[MetricSpec]:
    label = _normalized_label(row_label)
    candidates: list[tuple[int, MetricSpec]] = []
    for spec in specs:
        if any(_normalized_label(item) in label for item in spec.exclude):
            continue
        for alias in spec.aliases:
            normalized_alias = _normalized_label(alias)
            # Minor prefix truncation is common when PDF text interleaves a wrapped
            # row label and its numeric cells. Keep the tolerance deterministic.
            exact = normalized_alias in label
            truncated = (
                len(label) >= 4
                and normalized_alias.startswith(label)
                and len(normalized_alias) - len(label) <= 2
            )
            if exact or truncated:
                candidates.append((len(normalized_alias), spec))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _section_for_page(
    sections: Iterable[DocumentSection], page_number: int
) -> Optional[DocumentSection]:
    return next(
        (
            section
            for section in sections
            if section.start_page <= page_number <= section.end_page
        ),
        None,
    )


def _growth_from_summary_row(row: ParsedTableRow) -> Optional[float]:
    tokens = NUMBER_RE.findall(row.raw_text)
    if len(tokens) < 3:
        return None
    candidates = (3, 2) if len(tokens) >= 6 else (2,)
    growth = next(
        (tokens[index] for index in candidates if tokens[index].endswith("%")), None
    )
    return _parse_number(growth) if growth else None


def _page_confidence(document: ParsedDocument, page_number: int, base: float) -> float:
    """Cap confidence for pages whose text came from OCR rather than the file."""

    page = next(
        (item for item in document.pages if item.page_number == page_number), None
    )
    if page is not None and page.text_source == "ocr":
        return min(base, OCR_CONFIDENCE)
    return base


def _fact_from_cell(
    document: ParsedDocument,
    table: ParsedTable,
    row: ParsedTableRow,
    spec: MetricSpec,
    value_index: int,
) -> tuple[Evidence, FinancialMetric]:
    value = row.values[value_index]
    section = _section_for_page(document.sections, value.page_number)
    numeric_scale = 1.0 if spec.unit in UNSCALED_UNITS else table.scale
    evidence = Evidence(
        document_id=document.id,
        source_id=document.source_id,
        page_number=value.page_number,
        section_id=section.id if section else None,
        section_title=section.title if section else None,
        table_id=table.id,
        table_name=table.name,
        statement_type=table.statement_type,
        row_index=row.row_index,
        column_index=value.column_index,
        row_label=row.label,
        column_label=value.column_label,
        cell_value=value.raw_value,
        bbox=value.bbox,
        quote=row.raw_text,
        extraction_method="indexed_financial_table_v2",
        confidence=_page_confidence(
            document,
            value.page_number,
            0.99 if table.scope == ConsolidationScope.CONSOLIDATED else 0.97,
        ),
    )
    metric = FinancialMetric(
        document_id=document.id,
        company_name=document.company_name or document.file_name,
        period=value.column_label,
        name=spec.name,
        display_name=spec.display_name,
        value=_parse_number(value.raw_value, numeric_scale),
        raw_value=value.raw_value,
        unit=spec.unit,
        currency=table.currency if spec.unit in MONETARY_UNITS else None,
        scale=numeric_scale,
        period_type=spec.period_type,
        scope=table.scope,
        statement_type=table.statement_type,
        row_label=row.label,
        confidence=evidence.confidence,
        evidence_ids=[evidence.id],
        reported_growth_pct=(
            _growth_from_summary_row(row)
            if table.statement_type == StatementType.SUMMARY and value_index == 0
            else None
        ),
    )
    return evidence, metric


def _extract_table(
    document: ParsedDocument, table: ParsedTable, specs: Sequence[MetricSpec]
) -> tuple[List[Evidence], List[FinancialMetric]]:
    evidence: List[Evidence] = []
    metrics: List[FinancialMetric] = []
    seen: set[tuple[str, str]] = set()
    for row in table.rows:
        spec = _match_spec(row.label, specs)
        if spec is None:
            continue
        for value_index, value in enumerate(row.values):
            key = (spec.name, value.column_label)
            if key in seen:
                continue
            item_evidence, metric = _fact_from_cell(
                document, table, row, spec, value_index
            )
            evidence.append(item_evidence)
            metrics.append(metric)
            seen.add(key)
    return evidence, metrics


def _extract_segment_table(
    document: ParsedDocument, table: ParsedTable
) -> tuple[List[Evidence], List[FinancialMetric]]:
    evidence: List[Evidence] = []
    metrics: List[FinancialMetric] = []
    dimension_names = {"industry": "行业", "product": "产品", "region": "地区"}
    for row in table.rows:
        if not row.dimension_type:
            continue
        dimension_label = dimension_names.get(row.dimension_type, row.dimension_type)
        for value_index, value in enumerate(row.values):
            if ":" not in value.column_label:
                continue
            period, value_kind = value.column_label.split(":", 1)
            if value_kind == "revenue":
                spec = MetricSpec(
                    "segment_revenue",
                    f"{dimension_label}收入：{row.label}",
                    (row.label,),
                    StatementType.SEGMENT_DISCLOSURE,
                )
            elif value_kind == "share":
                spec = MetricSpec(
                    "segment_revenue_share",
                    f"{dimension_label}收入占比：{row.label}",
                    (row.label,),
                    StatementType.SEGMENT_DISCLOSURE,
                    unit=MetricUnit.PERCENT,
                )
            else:
                continue
            item_evidence, metric = _fact_from_cell(
                document, table, row, spec, value_index
            )
            metric = metric.model_copy(
                update={
                    "period": period,
                    "dimensions": {row.dimension_type: row.label},
                }
            )
            evidence.append(item_evidence)
            metrics.append(metric)
    return evidence, metrics


def _extract_non_recurring_table(
    document: ParsedDocument, table: ParsedTable
) -> tuple[List[Evidence], List[FinancialMetric]]:
    """Extract disclosed non-recurring components without inventing a taxonomy."""

    evidence: List[Evidence] = []
    metrics: List[FinancialMetric] = []
    ignored_labels = {"项目", "说明", "适用不适用"}
    canonical_labels = (
        ("所得税影响额", "减：所得税影响额"),
        ("少数股东权益影响额", "减：少数股东权益影响额（税后）"),
        ("其他营业外收入和支出", "除上述各项之外的其他营业外收入和支出"),
        (
            "公允价值变动损益",
            "金融资产及负债的公允价值变动和处置损益",
        ),
        ("政府补助", "计入当期损益的政府补助"),
        ("委托他人投资或管理资产", "委托他人投资或管理资产的损益"),
        ("非流动资产处置损益", "非流动资产处置损益"),
    )
    for row in table.rows:
        label = re.sub(r"\s+", "", row.label).strip("：:")
        if not label or label in ignored_labels or "非经常性损益项目及金额" in label:
            continue
        is_total = label == "合计" or label.endswith("合计")
        canonical_label = next(
            (canonical for marker, canonical in canonical_labels if marker in label),
            row.label,
        )
        for value in row.values:
            section = _section_for_page(document.sections, value.page_number)
            item_evidence = Evidence(
                document_id=document.id,
                source_id=document.source_id,
                page_number=value.page_number,
                section_id=section.id if section else None,
                section_title=section.title if section else None,
                table_id=table.id,
                table_name=table.name,
                statement_type=table.statement_type,
                row_index=row.row_index,
                column_index=value.column_index,
                row_label=row.label,
                column_label=value.column_label,
                cell_value=value.raw_value,
                bbox=value.bbox,
                quote=row.raw_text,
                extraction_method="non_recurring_table_v1",
                confidence=0.98,
            )
            metric = FinancialMetric(
                document_id=document.id,
                company_name=document.company_name or document.file_name,
                period=value.column_label,
                name=(
                    "non_recurring_net_effect_reported"
                    if is_total
                    else "non_recurring_item"
                ),
                display_name=(
                    "非经常性损益净影响（披露）"
                    if is_total
                    else f"非经常性损益：{canonical_label}"
                ),
                value=_parse_number(value.raw_value, table.scale),
                raw_value=value.raw_value,
                unit=MetricUnit.MONEY,
                currency=table.currency,
                scale=table.scale,
                scope=table.scope,
                statement_type=table.statement_type,
                row_label=canonical_label,
                dimensions={} if is_total else {"item": canonical_label},
                confidence=item_evidence.confidence,
                evidence_ids=[item_evidence.id],
            )
            evidence.append(item_evidence)
            metrics.append(metric)
    return evidence, metrics


_NOTE_METRIC_NAMES = {
    "receivables_aging": ("receivable_aging_balance", "应收账款账龄"),
    "goodwill": ("goodwill_detail", "商誉明细"),
    "related_party": ("related_party_transaction", "关联方交易"),
}

# Column captions and heading fragments. Matched as substrings, not by equality:
# the text-layout reader concatenates a wrapped heading into a single label
# (e.g. "按账龄披露账龄账面余额"), which an equality check lets through and then
# reports as though it were a disclosed line item.
_NOTE_LABEL_NOISE = (
    "账龄披露",
    "期末余额",
    "期初余额",
    "账面余额",
    "坏账准备",
    "计提比例",
    "关联交易内容",
    "被投资单位名称",
    "形成商誉的事项",
    "本期发生额",
    "上期发生额",
    "获批的交易额度",
    "占同类交易",
)

# An aging bucket is the only thing an aging schedule discloses. Requiring the
# shape here means a stray heading cannot become a "bucket" with a balance.
_AGING_LABEL_RE = re.compile(
    r"^(?:\d+年以内|\d+个?月以内|\d+至\d+年|\d+-\d+年|\d+年以上|\d+年内|合计)$"
)


def _is_note_line_item(note_kind: Optional[str], label: str) -> bool:
    """Whether a note row label reads as a disclosed line item."""

    if not label or len(re.findall(r"[一-鿿A-Za-z0-9]", label)) < 2:
        return False
    if any(noise in label for noise in _NOTE_LABEL_NOISE):
        return False
    if note_kind == "receivables_aging":
        return bool(_AGING_LABEL_RE.match(label))
    return True


def _extract_note_table(
    document: ParsedDocument, table: ParsedTable
) -> tuple[List[Evidence], List[FinancialMetric]]:
    """Extract disclosure-note line items as dimensional facts.

    Note tables have no cross-issuer column contract, so each row becomes a
    dimensional observation keyed by its own disclosed label. They are never
    folded into the canonical concept catalog and never feed a formula — they
    exist to give the investigation stages concrete composition detail.
    """
    naming = _NOTE_METRIC_NAMES.get(table.note_kind or "")
    if not naming:
        return [], []
    metric_name, metric_prefix = naming
    evidence: List[Evidence] = []
    metrics: List[FinancialMetric] = []
    for row in table.rows:
        label = re.sub(r"\s+", "", row.label).strip("：:（）()")
        if not _is_note_line_item(table.note_kind, label):
            continue
        for value in row.values:
            section = _section_for_page(document.sections, value.page_number)
            item_evidence = Evidence(
                document_id=document.id,
                source_id=document.source_id,
                page_number=value.page_number,
                section_id=section.id if section else None,
                section_title=section.title if section else None,
                table_id=table.id,
                table_name=table.name,
                statement_type=table.statement_type,
                row_index=row.row_index,
                column_index=value.column_index,
                row_label=row.label,
                column_label=value.column_label,
                cell_value=value.raw_value,
                bbox=value.bbox,
                quote=row.raw_text,
                extraction_method=f"note_table_{table.note_kind}_v1",
                confidence=_page_confidence(document, value.page_number, 0.90),
            )
            metric = FinancialMetric(
                document_id=document.id,
                company_name=document.company_name or document.file_name,
                period=value.column_label,
                name=metric_name,
                display_name=f"{metric_prefix}：{label}",
                value=_parse_number(value.raw_value, table.scale),
                raw_value=value.raw_value,
                unit=MetricUnit.MONEY,
                currency=table.currency,
                scale=table.scale,
                scope=table.scope,
                statement_type=table.statement_type,
                row_label=label,
                # A note table can repeat a label across rows — a related-party
                # schedule lists 原材料 once per counterparty. The disclosed row
                # is therefore part of the fact's identity; collapsing on the
                # label alone would report two real figures as one conflict.
                dimensions={
                    table.note_kind or "note": label,
                    "disclosed_row": str(row.row_index),
                },
                confidence=item_evidence.confidence,
                evidence_ids=[item_evidence.id],
            )
            evidence.append(item_evidence)
            metrics.append(metric)
    return evidence, metrics


def _extract_audit_evidence(document: ParsedDocument) -> List[Evidence]:
    result: List[Evidence] = []
    audit_page = next(
        (
            page
            for page in document.pages
            if "审计意见类型" in re.sub(r"\s+", "", page.text)
        ),
        None,
    )
    if audit_page is None:
        return result
    section = _section_for_page(document.sections, audit_page.page_number)
    compact_lines = [
        line.strip() for line in audit_page.text.splitlines() if line.strip()
    ]
    opinion_line = next(
        (line for line in compact_lines if "审计意见类型" in line.replace(" ", "")),
        "审计意见类型未明确",
    )
    opinion_type = re.sub(r"^.*?审计意见类型\s*", "", opinion_line).strip()
    opinion_start = next(
        (index for index, line in enumerate(compact_lines) if line == "一、审计意见"),
        0,
    )
    opinion_quote = "\n".join(compact_lines[opinion_start : opinion_start + 12])
    result.append(
        Evidence(
            document_id=document.id,
            source_id=document.source_id,
            page_number=audit_page.page_number,
            section_id=section.id if section else None,
            section_title=section.title if section else None,
            table_name="审计报告",
            statement_type=StatementType.NOTE,
            row_label="审计意见类型",
            column_label="披露结论",
            cell_value=opinion_type,
            quote=opinion_quote,
            extraction_method="audit_opinion_v1",
            confidence=0.99,
        )
    )

    key_matter_text = []
    key_matter_page = audit_page.page_number
    collecting = False
    for page in document.pages[audit_page.page_number - 1 : audit_page.page_number + 3]:
        for line in (item.strip() for item in page.text.splitlines() if item.strip()):
            compact = line.replace(" ", "")
            if "三、关键审计事项" in compact:
                collecting = True
                key_matter_page = page.page_number
            if collecting:
                if compact.startswith("四、其他信息"):
                    collecting = False
                    break
                key_matter_text.append(line)
        if not collecting and key_matter_text:
            break
    if key_matter_text:
        quote = "\n".join(key_matter_text)[:2400]
        result.append(
            Evidence(
                document_id=document.id,
                source_id=document.source_id,
                page_number=key_matter_page,
                section_id=section.id if section else None,
                section_title=section.title if section else None,
                table_name="审计报告",
                statement_type=StatementType.NOTE,
                row_label="关键审计事项",
                column_label="审计师关注事项",
                quote=quote,
                extraction_method="key_audit_matters_v1",
                confidence=0.95,
            )
        )
    return result


def extract_financial_facts(
    document: ParsedDocument,
) -> Tuple[List[Evidence], List[FinancialMetric]]:
    """Extract facts from summary and consolidated three-statement tables.

    Parent-company statements remain indexed but are not silently mixed into the
    consolidated analytical scope.
    """

    all_evidence: List[Evidence] = []
    all_metrics: List[FinancialMetric] = []
    all_evidence.extend(_extract_audit_evidence(document))
    for table in document.tables:
        if table.statement_type == StatementType.SUMMARY:
            specs = SUMMARY_METRIC_SPECS
        elif table.statement_type == StatementType.NON_RECURRING_DISCLOSURE:
            evidence, metrics = _extract_non_recurring_table(document, table)
            all_evidence.extend(evidence)
            all_metrics.extend(metrics)
            continue
        elif table.statement_type == StatementType.SEGMENT_DISCLOSURE:
            evidence, metrics = _extract_segment_table(document, table)
            all_evidence.extend(evidence)
            all_metrics.extend(metrics)
            continue
        elif table.statement_type == StatementType.NOTE:
            evidence, metrics = _extract_note_table(document, table)
            all_evidence.extend(evidence)
            all_metrics.extend(metrics)
            continue
        elif table.scope == ConsolidationScope.CONSOLIDATED:
            specs = tuple(
                spec
                for spec in METRIC_SPECS
                if spec.statement_type == table.statement_type
            )
        else:
            continue
        evidence, metrics = _extract_table(document, table, specs)
        all_evidence.extend(evidence)
        all_metrics.extend(metrics)
    return all_evidence, all_metrics


# Kept as a stable import for existing callers while the implementation now covers
# indexed summary, balance-sheet, income-statement, and cash-flow tables.
extract_annual_report_summary = extract_financial_facts
