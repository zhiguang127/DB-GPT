"""Local PDF parser with a lightweight report document map.

The adapter targets digitally generated PDFs first. It preserves page text and
builds deterministic section/table indexes without LLM inference. Two optional
capabilities sit behind explicit flags:

* OCR, for filings with no usable text layer. Recognized pages are marked so
  their evidence carries reduced confidence rather than passing as disclosed
  text.
* A second, ruling-based table reading (:mod:`table_geometry`) kept alongside
  the text-layout reading so the two can be compared instead of one silently
  overriding the other.
"""

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Iterable, Optional, Sequence

from ..domain.models import (
    ConsolidationScope,
    DocumentSection,
    ParsedDocument,
    ParsedPage,
    ParsedTable,
    ParsedTableRow,
    ParsedTableValue,
    ResearchSource,
    StatementType,
)
from ..domain.periods import PeriodKind, build_period, detect_report_kind
from ..ports.parser import DocumentParser
from .ocr import OcrUnavailableError, ocr_pdf_pages
from .table_geometry import extract_geometric_tables

logger = logging.getLogger(__name__)

NUMBER_RE = re.compile(r"(?<![\d])[-−－]?\d[\d,]*(?:\.\d+)?%?")
SEGMENT_VALUE_RE = re.compile(
    r"[-−－]?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d+%?|[-−－]?\d+(?:\.\d+)?%"
)
YEAR_RE = re.compile(r"(20\d{2})年")
STATEMENT_HEADING_RE = re.compile(
    r"^(?:\d+[、.]\s*)?(合并|母公司)"
    r"(资产负债表|利润表|现金流量表|所有者权益变动表)$"
)
SECTION_HEADING_RE = re.compile(r"^第[一二三四五六七八九十]+节\s*(.{2,40})$")
KNOWN_SECTION_TITLES = (
    "公司简介和主要财务指标",
    "公司业务概要",
    "经营情况讨论与分析",
    "重要事项",
    "股份变动及股东情况",
    "董事、监事、高级管理人员和员工情况",
    "公司治理",
    "公司债券相关情况",
    "财务报告",
)


def _metadata_from_name(path: Path) -> tuple[str | None, int | None]:
    parts = path.stem.split("__")
    company = parts[1].strip() if len(parts) > 1 else None
    year_match = re.search(r"(20\d{2})年", path.stem)
    return company, int(year_match.group(1)) if year_match else None


# Currency markers as they appear on a statement's 单位 line. Simplified-Chinese
# A-share filings state 人民币; the remaining entries let Hong Kong, Taiwan,
# Japanese and Korean filings resolve a currency instead of being forced to CNY.
_CURRENCY_MARKERS = (
    ("人民币", "CNY"),
    ("港币", "HKD"),
    ("港元", "HKD"),
    ("澳门元", "MOP"),
    ("澳门币", "MOP"),
    ("新台币", "TWD"),
    ("台币", "TWD"),
    ("日元", "JPY"),
    ("日圓", "JPY"),
    ("韩元", "KRW"),
    ("韓元", "KRW"),
    ("新加坡元", "SGD"),
    ("美元", "USD"),
    ("欧元", "EUR"),
)


def _detect_currency(text: str, default: str = "CNY") -> str:
    compact = text.replace(" ", "")
    for marker, code in _CURRENCY_MARKERS:
        if marker in compact:
            return code
    return default


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _statement_metadata(
    heading_match: re.Match[str],
) -> tuple[str, StatementType, ConsolidationScope] | None:
    scope_label, statement_label = heading_match.groups()
    statement_types = {
        "资产负债表": StatementType.BALANCE_SHEET,
        "利润表": StatementType.INCOME_STATEMENT,
        "现金流量表": StatementType.CASH_FLOW_STATEMENT,
    }
    statement_type = statement_types.get(statement_label)
    if statement_type is None:
        return None
    scope = (
        ConsolidationScope.CONSOLIDATED
        if scope_label == "合并"
        else ConsolidationScope.PARENT_COMPANY
    )
    return f"{scope_label}{statement_label}", statement_type, scope


def _unit_metadata(
    lines: Iterable[str], default_currency: str = "CNY"
) -> tuple[str, str, float]:
    head = "\n".join(list(lines)[:20]).replace(" ", "")
    currency = _detect_currency(head, default_currency)
    unit_line = next(
        (
            line
            for line in head.splitlines()
            if "单位" in line or "單位" in line or "UNIT" in line.upper()
        ),
        "",
    )
    # Currency can sit on either side of the multiplier (千港元 / 港币千元),
    # and Hong Kong filings also commonly use HK$'000. Detect the multiplier
    # independently from the currency instead of assuming 人民币元 word order.
    if re.search(r"百[万萬]|MILLION", unit_line, re.IGNORECASE):
        unit_label, scale = "百万元", 1_000_000.0
    elif re.search(r"[万萬]", unit_line):
        unit_label, scale = "万元", 10_000.0
    elif re.search(r"千|['’]000", unit_line):
        unit_label, scale = "千元", 1_000.0
    else:
        unit_label, scale = "元", 1.0
    return unit_label, currency, scale


def _canonical_periods(
    years: Sequence[str],
    kind: PeriodKind,
    quarter: Optional[int],
    *,
    instant: bool,
) -> list[str]:
    """Map disclosed column years onto canonical period identifiers.

    For an annual filing every column is the full year, which is what the
    original implementation assumed. For an interim filing the two axes differ:
    income and cash-flow columns cover the same interval in each year, while a
    balance sheet compares the current period end against the *prior year end* —
    so the comparative instant column stays a full-year identifier.
    """
    if kind == PeriodKind.ANNUAL:
        return [str(year) for year in years]
    result: list[str] = []
    for index, year in enumerate(years):
        value = int(year)
        if instant and index > 0:
            result.append(str(value))
        else:
            result.append(build_period(value, kind, quarter))
    return result


def _period_columns(
    lines: Sequence[str],
    report_year: Optional[int],
    kind: PeriodKind = PeriodKind.ANNUAL,
    quarter: Optional[int] = None,
    *,
    instant: bool = False,
) -> list[str]:
    for line in lines[:40]:
        years = YEAR_RE.findall(line)
        if len(years) >= 2:
            unique = list(dict.fromkeys(years))[:2]
            return _canonical_periods(unique, kind, quarter, instant=instant)
    if report_year:
        return _canonical_periods(
            [str(report_year), str(report_year - 1)], kind, quarter, instant=instant
        )
    return []


def _table_rows(
    segments: Sequence[tuple[int, str]],
    columns: Sequence[str],
    *,
    combine_wrapped_label: bool = False,
) -> list[ParsedTableRow]:
    """Recover row labels and value columns from layout-preserving page text."""

    rows: list[ParsedTableRow] = []
    pending_labels: list[str] = []
    awaiting_continuation: ParsedTableRow | None = None
    for page_number, raw_line in segments:
        line = _clean_line(raw_line)
        if not line:
            continue
        if YEAR_RE.search(line) and ("项目" in line or "年末" in line):
            pending_labels.clear()
            continue
        # Remove statement numbering before looking for financial values.
        value_line = re.sub(r"^(?:[一二三四五六七八九十]+|\d+)[、.]\s*", "", line)
        matches = list(NUMBER_RE.finditer(value_line))
        if not matches:
            if not line.endswith("年度报告全文") and not re.fullmatch(r"\d+", line):
                if (
                    awaiting_continuation is not None
                    and awaiting_continuation.page_number == page_number
                    and not line.endswith("：")
                ):
                    awaiting_continuation.label += line
                    awaiting_continuation.raw_text += f"\n{line}"
                    awaiting_continuation = None
                    continue
                pending_labels.append(line)
                pending_labels = pending_labels[-8 if combine_wrapped_label else -2 :]
            continue

        first = matches[0]
        label = value_line[: first.start()].strip(" ：:")
        tokens = [match.group(0) for match in matches]
        evidence_text = line
        used_pending_label = not label
        combined_pending_label = bool(
            label and pending_labels and combine_wrapped_label
        )
        if combined_pending_label:
            label = "".join([*pending_labels, label]).strip(" ：:")
            evidence_text = "\n".join([*pending_labels, line])
        elif not label:
            label = "".join(pending_labels).strip(" ：:")
            evidence_text = "\n".join([*pending_labels, line])
        pending_labels.clear()
        if not label or not columns:
            continue

        values = [
            ParsedTableValue(
                column_index=index,
                column_label=column,
                raw_value=token,
                page_number=page_number,
            )
            for index, (column, token) in enumerate(zip(columns, tokens))
        ]
        if values:
            row = ParsedTableRow(
                row_index=len(rows),
                label=label,
                values=values,
                page_number=page_number,
                raw_text=evidence_text,
            )
            rows.append(row)
            awaiting_continuation = (
                row if used_pending_label or combined_pending_label else None
            )
    return rows


def _summary_table_rows(
    segments: Sequence[tuple[int, str]], columns: Sequence[str]
) -> list[ParsedTableRow]:
    """Parse disclosed years, restatements and the YoY display column.

    A normal summary row is ``current, prior, YoY, third``. A restated row is
    ``current, prior-before, prior-after, YoY, third-before, third-after``.
    The analytical values must use the adjusted comparatives, while retaining
    the original row as evidence.
    """

    rows = _table_rows(segments, [f"raw_{index}" for index in range(10)])
    result: list[ParsedTableRow] = []
    for row in rows:
        values = row.values
        if len(columns) >= 3 and len(values) >= 6:
            values = [values[0], values[2], values[-1]]
        elif len(columns) >= 3 and len(values) >= 4:
            values = [values[0], values[1], values[3]]
        elif (
            len(columns) >= 3 and len(values) == 3 and values[2].raw_value.endswith("%")
        ):
            values = values[:2]
        else:
            values = values[: len(columns)]
        normalized_values = [
            value.model_copy(
                update={
                    "column_index": index,
                    "column_label": columns[index],
                }
            )
            for index, value in enumerate(values)
        ]
        result.append(
            row.model_copy(
                update={"row_index": len(result), "values": normalized_values}
            )
        )
    return result


def _build_sections(pages: Sequence[ParsedPage]) -> list[DocumentSection]:
    headings: list[tuple[int, str]] = []
    seen_titles: set[str] = set()
    for page in pages:
        for raw_line in page.text.splitlines():
            line = _clean_line(raw_line)
            match = SECTION_HEADING_RE.fullmatch(line)
            if not match or "…" in line or "..." in line:
                continue
            title = match.group(1).strip()
            known = next((item for item in KNOWN_SECTION_TITLES if item in title), None)
            if known and known not in seen_titles:
                headings.append((page.page_number, known))
                seen_titles.add(known)

    sections: list[DocumentSection] = []
    for index, (start_page, title) in enumerate(headings):
        next_page = (
            headings[index + 1][0] if index + 1 < len(headings) else len(pages) + 1
        )
        sections.append(
            DocumentSection(
                title=title,
                start_page=start_page,
                end_page=max(start_page, next_page - 1),
            )
        )
    return sections


def _build_statement_tables(
    pages: Sequence[ParsedPage],
    report_year: Optional[int],
    kind: PeriodKind = PeriodKind.ANNUAL,
    quarter: Optional[int] = None,
    default_currency: str = "CNY",
) -> list[ParsedTable]:
    tables: list[ParsedTable] = []
    active: dict | None = None
    seen_tables: set[tuple[StatementType, ConsolidationScope]] = set()

    def close_active() -> None:
        nonlocal active
        if not active:
            return
        segments = active["segments"]
        if segments:
            text_lines = [line for _, line in segments]
            columns = _period_columns(
                text_lines,
                report_year,
                kind,
                quarter,
                instant=active["statement_type"] == StatementType.BALANCE_SHEET,
            )
            unit_label, currency, scale = _unit_metadata(text_lines, default_currency)
            tables.append(
                ParsedTable(
                    name=active["name"],
                    statement_type=active["statement_type"],
                    scope=active["scope"],
                    start_page=active["start_page"],
                    end_page=segments[-1][0],
                    unit_label=unit_label,
                    currency=currency,
                    scale=scale,
                    columns=columns,
                    rows=_table_rows(segments, columns),
                )
            )
        active = None

    for page in pages:
        for raw_line in page.text.splitlines():
            line = _clean_line(raw_line)
            heading = STATEMENT_HEADING_RE.fullmatch(line.replace(" ", ""))
            if heading:
                close_active()
                metadata = _statement_metadata(heading)
                if metadata:
                    name, statement_type, scope = metadata
                    table_key = (statement_type, scope)
                    if table_key in seen_tables:
                        continue
                    seen_tables.add(table_key)
                    active = {
                        "name": name,
                        "statement_type": statement_type,
                        "scope": scope,
                        "start_page": page.page_number,
                        "segments": [],
                    }
                continue
            if active is not None:
                active["segments"].append((page.page_number, line))
    close_active()
    return tables


def _build_summary_tables(
    pages: Sequence[ParsedPage],
    report_year: Optional[int],
    kind: PeriodKind = PeriodKind.ANNUAL,
    quarter: Optional[int] = None,
    default_currency: str = "CNY",
) -> list[ParsedTable]:
    tables = []
    stop_markers = (
        "境内外会计准则下会计数据差异",
        "分季度主要财务指标",
        "非经常性损益项目及金额",
    )
    for page_index, page in enumerate(pages):
        compact = re.sub(r"\s+", "", page.text)
        if "主要会计数据和财务指标" not in compact:
            continue
        segments: list[tuple[int, str]] = []
        started = False
        finished = False
        for candidate in pages[page_index : page_index + 3]:
            for raw_line in candidate.text.splitlines():
                line = _clean_line(raw_line)
                if not line:
                    continue
                compact_line = line.replace(" ", "")
                if not started:
                    started = "主要会计数据和财务指标" in compact_line
                    continue
                if any(marker in compact_line for marker in stop_markers):
                    finished = True
                    break
                if line.endswith("年度报告全文") or re.fullmatch(r"\d+", line):
                    continue
                segments.append((candidate.page_number, line))
            if finished:
                break
        if not segments:
            continue
        if report_year:
            years = [str(report_year), str(report_year - 1), str(report_year - 2)]
        else:
            years = sorted(
                {
                    year
                    for _page_number, line in segments
                    for year in YEAR_RE.findall(line)
                },
                reverse=True,
            )[:3]
        if len(years) < 2:
            continue
        # The summary table mixes duration rows (revenue, profit) with instant
        # rows (total assets). Duration labelling is used because the extractor
        # keys instant rows off their own `PeriodType`, not the column label.
        columns = _canonical_periods(years[:3], kind, quarter, instant=False)
        unit_label, currency, scale = _unit_metadata(
            (line for _page_number, line in segments), default_currency
        )
        rows = _summary_table_rows(segments, columns)
        row_labels = {re.sub(r"\s+", "", row.label) for row in rows}
        if not any(
            "营业收入" in label or "归属于上市公司股东的净利润" in label
            for label in row_labels
        ):
            continue
        tables.append(
            ParsedTable(
                name="主要会计数据和财务指标",
                statement_type=StatementType.SUMMARY,
                scope=ConsolidationScope.CONSOLIDATED,
                start_page=rows[0].page_number,
                end_page=rows[-1].page_number,
                unit_label=unit_label,
                currency=currency,
                scale=scale,
                columns=columns,
                rows=rows,
            )
        )
        break
    return tables


def _build_non_recurring_tables(
    pages: Sequence[ParsedPage],
    report_year: Optional[int],
    kind: PeriodKind = PeriodKind.ANNUAL,
    quarter: Optional[int] = None,
    default_currency: str = "CNY",
) -> list[ParsedTable]:
    """Index the disclosed non-recurring item table, including three-year values."""

    for page_index, page in enumerate(pages):
        if "非经常性损益项目及金额" not in re.sub(r"\s+", "", page.text):
            continue
        segments: list[tuple[int, str]] = []
        started = False
        finished = False
        for candidate in pages[page_index : page_index + 3]:
            for raw_line in candidate.text.splitlines():
                line = _clean_line(raw_line)
                compact = line.replace(" ", "")
                if not started:
                    started = "非经常性损益项目及金额" in compact
                    if not started:
                        continue
                if (
                    not line
                    or line.endswith("年度报告全文")
                    or re.fullmatch(r"\d+", line)
                ):
                    continue
                segments.append((candidate.page_number, line))
                if compact.startswith("合计") and len(NUMBER_RE.findall(line)) >= 1:
                    finished = True
                    break
            if finished:
                break
        if not segments:
            continue
        years: list[str] = []
        for _, line in segments:
            found = YEAR_RE.findall(line)
            if len(found) >= 2:
                years = list(dict.fromkeys(found))[:3]
                break
        if not years and report_year:
            years = [str(report_year), str(report_year - 1), str(report_year - 2)]
        if not years:
            continue
        unit_label, currency, scale = _unit_metadata(
            (line for _, line in segments), default_currency
        )
        columns = _canonical_periods(years, kind, quarter, instant=False)
        rows = _table_rows(segments, columns, combine_wrapped_label=True)
        return [
            ParsedTable(
                name="非经常性损益项目及金额",
                statement_type=StatementType.NON_RECURRING_DISCLOSURE,
                scope=ConsolidationScope.CONSOLIDATED,
                start_page=page.page_number,
                end_page=segments[-1][0],
                unit_label=unit_label,
                currency=currency,
                scale=scale,
                columns=columns,
                rows=rows,
            )
        ]
    return []


def _build_segment_tables(
    pages: Sequence[ParsedPage],
    report_year: Optional[int],
    kind: PeriodKind = PeriodKind.ANNUAL,
    quarter: Optional[int] = None,
) -> list[ParsedTable]:
    for page_index, page in enumerate(pages):
        compact = re.sub(r"\s+", "", page.text)
        if "营业收入构成" not in compact:
            continue
        # A page break commonly falls between the section caption and the
        # first "分行业" row. Read ahead far enough to include all three
        # dimensions instead of requiring the caption and data on one page.
        candidate_pages = pages[page_index : page_index + 3]
        all_lines = [
            (candidate.page_number, _clean_line(line))
            for candidate in candidate_pages
            for line in candidate.text.splitlines()
            if _clean_line(line)
        ]
        years = []
        for _, line in all_lines:
            found = YEAR_RE.findall(line)
            if len(found) >= 2:
                years = list(dict.fromkeys(found))[:2]
                break
        if len(years) < 2 and report_year:
            years = [str(report_year), str(report_year - 1)]
        if len(years) < 2:
            continue
        periods = _canonical_periods(years[:2], kind, quarter, instant=False)
        columns = [
            f"{periods[0]}:revenue",
            f"{periods[0]}:share",
            f"{periods[1]}:revenue",
            f"{periods[1]}:share",
            "share_change",
        ]
        dimension_type: str | None = None
        pending_label: str | None = None
        rows: list[ParsedTableRow] = []
        dimension_labels = {
            "分行业": "industry",
            "分产品": "product",
            "分地区": "region",
        }
        for page_number, line in all_lines:
            compact_line = line.replace(" ", "")
            matched_dimension = next(
                (
                    value
                    for label, value in dimension_labels.items()
                    if compact_line == label
                ),
                None,
            )
            if matched_dimension:
                dimension_type = matched_dimension
                pending_label = None
                continue
            if dimension_type and (
                compact_line.startswith("（2）")
                or compact_line.startswith("(2)")
                or "占公司营业收入" in compact_line
            ):
                break
            if dimension_type is None:
                continue
            matches = list(SEGMENT_VALUE_RE.finditer(line))
            if len(matches) < 4:
                if (
                    matches == []
                    and not re.fullmatch(r"\d+", compact_line)
                    and not compact_line.endswith("年度报告全文")
                    and compact_line not in {"金额", "同比增减"}
                ):
                    if len(compact_line) <= 2 and rows and pending_label is None:
                        rows[-1].label += compact_line
                        rows[-1].raw_text += f"\n{line}"
                    else:
                        pending_label = line
                continue
            label = line[: matches[0].start()].strip(" ：:")
            if not label and pending_label:
                label = pending_label
            pending_label = None
            if not label or label in {"金额", "同比增减"}:
                continue
            tokens = [match.group(0) for match in matches[:5]]
            values = [
                ParsedTableValue(
                    column_index=index,
                    column_label=column,
                    raw_value=token,
                    page_number=page_number,
                )
                for index, (column, token) in enumerate(zip(columns, tokens))
            ]
            rows.append(
                ParsedTableRow(
                    row_index=len(rows),
                    label=label,
                    dimension_type=dimension_type,
                    values=values,
                    page_number=page_number,
                    raw_text=line,
                )
            )
        if rows:
            return [
                ParsedTable(
                    name="营业收入构成（分行业/产品/地区）",
                    statement_type=StatementType.SEGMENT_DISCLOSURE,
                    scope=ConsolidationScope.CONSOLIDATED,
                    start_page=rows[0].page_number,
                    end_page=rows[-1].page_number,
                    columns=columns,
                    rows=rows,
                )
            ]
    return []


# Notes the pipeline mines beyond the three statements. Each entry is
# (note_kind, table name, anchor markers, stop markers). Anchors are matched
# against whitespace-stripped page text so a wrapped heading still matches.
_NOTE_TABLE_SPECS = (
    (
        "receivables_aging",
        "应收账款账龄披露",
        ("按账龄披露",),
        ("（2）本期计提", "应收款项融资", "预付款项"),
    ),
    (
        "goodwill",
        "商誉明细",
        ("（1）商誉账面原值", "商誉账面原值"),
        ("（2）商誉减值准备", "长期待摊费用"),
    ),
    (
        "related_party",
        "关联方交易",
        ("购销商品、提供和接受劳务的关联交易",),
        ("（2）关联受托管理", "关联方应收应付款项"),
    ),
)

_NOTE_ROW_NOISE = ("年度报告全文", "单位：", "单位:")

# Anything that is not a CJK ideograph, letter or digit cannot carry meaning as
# a line-item name. Stray bracket fragments left behind by a wrapped cell would
# otherwise become a "line item" with a value attached to it.
_MEANINGFUL_LABEL_RE = re.compile(r"[一-鿿A-Za-z0-9]")

_AGING_ROW_RE = re.compile(
    r"^(?P<label>"
    r"\d+年以内(?:（含\d+年）)?|"
    r"\d+至\d+年|"
    r"\d+-\d+年|"
    r"\d+年以上|"
    r"合计"
    r")\s+(?P<values>.+)$"
)

_RELATED_PARTY_CONTENT_MARKERS = ("采购", "销售", "接受劳务", "提供劳务")


def _is_usable_note_label(label: str) -> bool:
    """A note row is only usable when its label reads as a disclosed item."""

    if not label:
        return False
    meaningful = _MEANINGFUL_LABEL_RE.findall(label)
    if len(meaningful) < 2:
        return False
    # A label made only of digits is a value that lost its row heading.
    return not re.fullmatch(r"[\d,.\s%()（）-]+", label)


def _is_note_structure_line(note_kind: str, compact: str) -> bool:
    """Drop headings before they can be joined to a wrapped line item."""

    common = (
        "情况表",
        "情况说明",
        "单位：",
        "单位:",
        "單位：",
        "年度报告全文",
    )
    if any(marker in compact for marker in common):
        return True
    if note_kind == "receivables_aging":
        return compact in {"按账龄披露", "账龄账面余额"}
    if note_kind == "goodwill":
        return (
            "被投资单位名" in compact
            or "称或形成商誉" in compact
            or compact in {"处置", "的事项的"}
        )
    if note_kind == "related_party":
        return "购销商品、提供和接受劳务的关联交易" in compact or compact.startswith(
            "关联方关联交易内容"
        )
    return False


def _aging_rows(
    segments: Sequence[tuple[int, str]], current_period: str
) -> list[ParsedTableRow]:
    """Parse an aging bucket without treating the digit in ``1年以内`` as data."""

    rows: list[ParsedTableRow] = []
    for page_number, raw_line in segments:
        line = _clean_line(raw_line)
        match = _AGING_ROW_RE.match(line)
        if not match:
            continue
        label = re.sub(r"（含\d+年）", "", match.group("label"))
        values = NUMBER_RE.findall(match.group("values"))
        if not values:
            continue
        rows.append(
            ParsedTableRow(
                row_index=len(rows),
                label=label,
                values=[
                    ParsedTableValue(
                        column_index=0,
                        column_label=current_period,
                        raw_value=values[0],
                        page_number=page_number,
                    )
                ],
                page_number=page_number,
                raw_text=line,
            )
        )
    return rows


def _related_party_rows(
    segments: Sequence[tuple[int, str]], columns: Sequence[str]
) -> list[ParsedTableRow]:
    rows = _table_rows(segments, columns, combine_wrapped_label=True)
    result: list[ParsedTableRow] = []
    for row in rows:
        label = row.label
        for marker in _RELATED_PARTY_CONTENT_MARKERS:
            if marker not in label:
                continue
            party, suffix = label.split(marker, 1)
            # A wrapped legal suffix can appear on the line after the amount:
            # ``...科技有限 采购 174,582.00`` / ``公司``.
            if suffix in {"公司", "有限公司", "股份有限公司"}:
                party += suffix
            label = party
            break
        label = label.strip("：:（）()")
        if not _is_usable_note_label(label):
            continue
        result.append(row.model_copy(update={"row_index": len(result), "label": label}))
    return result


def _goodwill_rows(
    segments: Sequence[tuple[int, str]], current_period: str, prior_period: str
) -> list[ParsedTableRow]:
    """Map goodwill opening/closing balances to prior/current periods.

    A goodwill roll-forward can contain acquisition and disposal columns between
    the opening and closing balances. Positional two-column parsing would label
    an acquisition as the prior-year value, so the first and last disclosed
    amounts are selected explicitly.
    """

    raw_rows = _table_rows(
        segments,
        [f"raw_{index}" for index in range(8)],
        combine_wrapped_label=True,
    )
    rows: list[ParsedTableRow] = []
    for row in raw_rows:
        if not _is_usable_note_label(row.label) or not row.values:
            continue
        current_value = row.values[-1].model_copy(
            update={"column_index": 0, "column_label": current_period}
        )
        values = [current_value]
        if len(row.values) > 1:
            values.append(
                row.values[0].model_copy(
                    update={"column_index": 1, "column_label": prior_period}
                )
            )
        rows.append(row.model_copy(update={"row_index": len(rows), "values": values}))
    return rows


def _build_note_tables(
    pages: Sequence[ParsedPage],
    report_period: str,
    prior_period: str,
    default_currency: str = "CNY",
) -> list[ParsedTable]:
    """Index selected disclosure notes as tables.

    These notes carry no fixed column contract across issuers, so the reader is
    intentionally conservative. Aging uses its disclosed current-period bucket;
    goodwill and related-party rows use at most the first two disclosed amounts.
    Every row keeps its raw text as evidence, and rows that fail to yield both a
    meaningful label and an amount are dropped rather than guessed.
    """
    tables: list[ParsedTable] = []
    for note_kind, name, anchors, stops in _NOTE_TABLE_SPECS:
        anchor_index = next(
            (
                index
                for index, page in enumerate(pages)
                if any(anchor in re.sub(r"\s+", "", page.text) for anchor in anchors)
            ),
            None,
        )
        if anchor_index is None:
            continue
        segments: list[tuple[int, str]] = []
        metadata_lines: list[str] = []
        started = False
        finished = False
        for candidate in pages[anchor_index : anchor_index + 3]:
            for raw_line in candidate.text.splitlines():
                line = _clean_line(raw_line)
                if not line:
                    continue
                compact = line.replace(" ", "")
                if not started:
                    started = any(anchor in compact for anchor in anchors)
                    if not started:
                        continue
                metadata_lines.append(line)
                if any(stop in compact for stop in stops):
                    finished = True
                    break
                if any(noise in compact for noise in _NOTE_ROW_NOISE):
                    continue
                if _is_note_structure_line(note_kind, compact):
                    continue
                if re.fullmatch(r"\d+", compact):
                    continue
                segments.append((candidate.page_number, line))
            if finished:
                break
        if not segments:
            continue
        unit_label, currency, scale = _unit_metadata(metadata_lines, default_currency)
        columns = (
            [report_period]
            if note_kind == "receivables_aging"
            else [report_period, prior_period]
        )
        if note_kind == "receivables_aging":
            rows = _aging_rows(segments, report_period)
        elif note_kind == "goodwill":
            rows = _goodwill_rows(segments, report_period, prior_period)
        elif note_kind == "related_party":
            rows = _related_party_rows(segments, columns)
        else:
            rows = [
                row
                for row in _table_rows(segments, columns)
                if _is_usable_note_label(row.label)
            ]
        if not rows:
            continue
        tables.append(
            ParsedTable(
                name=name,
                statement_type=StatementType.NOTE,
                scope=ConsolidationScope.CONSOLIDATED,
                start_page=rows[0].page_number,
                end_page=rows[-1].page_number,
                unit_label=unit_label,
                currency=currency,
                scale=scale,
                columns=columns,
                rows=rows,
                note_kind=note_kind,
            )
        )
    return tables


def build_document_index(
    pages: Sequence[ParsedPage],
    report_year: Optional[int],
    kind: PeriodKind = PeriodKind.ANNUAL,
    quarter: Optional[int] = None,
    default_currency: str = "CNY",
) -> tuple[list[DocumentSection], list[ParsedTable]]:
    sections = _build_sections(pages)
    tables = _build_summary_tables(pages, report_year, kind, quarter, default_currency)
    tables.extend(
        _build_non_recurring_tables(pages, report_year, kind, quarter, default_currency)
    )
    tables.extend(
        _build_statement_tables(pages, report_year, kind, quarter, default_currency)
    )
    tables.extend(_build_segment_tables(pages, report_year, kind, quarter))
    if report_year:
        current = build_period(report_year, kind, quarter)
        prior = build_period(report_year - 1, kind, quarter)
        tables.extend(_build_note_tables(pages, current, prior, default_currency))
    return sections, tables


class PdfPlumberParser:
    """Text-first PDF parser with physical page numbers and table indexes."""

    def __init__(self, enable_ocr: bool = False, enable_geometry: bool = True) -> None:
        self._enable_ocr = enable_ocr
        self._enable_geometry = enable_geometry

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() == ".pdf"

    def parse(
        self, source: ResearchSource, enable_ocr: Optional[bool] = None
    ) -> ParsedDocument:
        try:
            import pdfplumber
        except ImportError as exc:
            raise RuntimeError(
                "PDF parsing requires pdfplumber; install the dbgpt-ext rag extra."
            ) from exc

        ocr_allowed = self._enable_ocr if enable_ocr is None else enable_ocr

        path = Path(source.location).expanduser().resolve()
        company, report_year = _metadata_from_name(path)
        pages: list[ParsedPage] = []
        with pdfplumber.open(path) as pdf:
            for index, page in enumerate(pdf.pages, start=1):
                pages.append(
                    ParsedPage(
                        page_number=index,
                        text=page.extract_text() or "",
                        width=float(page.width),
                        height=float(page.height),
                    )
                )

            pages, ocr_page_count = self._ensure_text_layer(path, pages, ocr_allowed)

            first_pages = "\n".join(page.text for page in pages[:3])
            report_kind, quarter = detect_report_kind(first_pages or path.stem)
            if pages:
                if not company:
                    match = re.search(
                        r"([^\n]{2,50}(?:股份)?有限公司).*?(?:年度|半年度|季度)报告",
                        first_pages,
                    )
                    company = match.group(1).strip() if match else None
                if not report_year:
                    match = re.search(
                        r"(20\d{2})\s*年(?:年度|半年度|第[一二三四]季度|度)?报告",
                        first_pages,
                    )
                    report_year = int(match.group(1)) if match else None

            currency = _detect_currency(first_pages, "CNY")
            sections, tables = build_document_index(
                pages, report_year, report_kind, quarter, currency
            )
            geometric_tables = self._read_geometry(pdf, tables)

        if report_kind != PeriodKind.ANNUAL and not tables:
            # Interim periods are representable end to end, but the table
            # anchors are tuned to the annual layout. Fail loudly instead of
            # returning an empty document that reads like a corrupt file.
            raise ValueError(
                f"{path.name} 识别为非年度报告（{report_kind.value}），"
                "但未能匹配到任何可解析的报表结构。当前仅对年度报告版式做过校准，"
                "请上传年度报告，或将该版式补充到解析规则后重试。"
            )

        return ParsedDocument(
            source_id=source.id,
            file_name=path.name,
            media_type="application/pdf",
            company_name=company,
            report_year=report_year,
            content_sha256=_sha256(path),
            pages=pages,
            sections=sections,
            tables=tables,
            geometric_tables=geometric_tables,
            report_kind=report_kind.value,
            reporting_quarter=quarter,
            currency=currency,
            ocr_page_count=ocr_page_count,
        )

    def _ensure_text_layer(
        self, path: Path, pages: list[ParsedPage], ocr_allowed: bool
    ) -> tuple[list[ParsedPage], int]:
        """Return usable pages, recognizing them with OCR only if permitted."""

        extracted_character_count = sum(
            len(re.sub(r"\s+", "", page.text)) for page in pages
        )
        minimum_digital_text = max(200, len(pages) * 5)
        if extracted_character_count >= minimum_digital_text:
            return pages, 0
        if not ocr_allowed:
            raise ValueError(
                f"{path.name} 未检测到足够的数字文本层。如需处理扫描件，"
                "请在请求中开启 OCR（enable_ocr）或设置环境变量 "
                "DBGPT_FINANCIAL_OCR=1，并确认已安装 OCR 依赖。"
            )
        try:
            recognized = ocr_pdf_pages(path)
        except OcrUnavailableError as exc:
            raise ValueError(str(exc)) from exc
        geometry = {page.page_number: page for page in pages}
        ocr_pages = [
            ParsedPage(
                page_number=number,
                text=text,
                width=geometry[number].width if number in geometry else None,
                height=geometry[number].height if number in geometry else None,
                text_source="ocr",
            )
            for number, text in recognized
        ]
        return ocr_pages, len(ocr_pages)

    def _read_geometry(self, pdf, tables: Sequence[ParsedTable]) -> list[ParsedTable]:
        if not self._enable_geometry:
            return []
        statement_tables = [
            table
            for table in tables
            if table.statement_type
            in {
                StatementType.BALANCE_SHEET,
                StatementType.INCOME_STATEMENT,
                StatementType.CASH_FLOW_STATEMENT,
            }
            and table.scope == ConsolidationScope.CONSOLIDATED
        ]
        if not statement_tables:
            return []
        try:
            results: list[ParsedTable] = []
            for table in statement_tables:
                if not table.columns:
                    continue
                pages = list(range(table.start_page, table.end_page + 1))
                # Balance-sheet comparatives in interim filings use the prior
                # year end, while income/cash-flow comparatives use the prior
                # interim. Each statement therefore needs its own columns.
                results.extend(extract_geometric_tables(pdf, pages, table.columns))
            return results
        except Exception:  # pragma: no cover - never block the primary reading
            logger.exception("Geometric table reading failed; continuing text-only")
            return []


class PlainTextParser:
    """Compatibility parser used by small deterministic unit fixtures."""

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in {".txt", ".md"}

    def parse(
        self, source: ResearchSource, enable_ocr: Optional[bool] = None
    ) -> ParsedDocument:
        # Plain text always has a text layer, so the OCR switch is accepted for
        # port compatibility and ignored.
        del enable_ocr
        path = Path(source.location).expanduser().resolve()
        company, report_year = _metadata_from_name(path)
        text = path.read_text(encoding="utf-8")
        pages = [ParsedPage(page_number=1, text=text)]
        report_kind, quarter = detect_report_kind(f"{path.stem}\n{text[:2000]}")
        currency = _detect_currency(text[:2000], "CNY")
        sections, tables = build_document_index(
            pages, report_year, report_kind, quarter, currency
        )
        return ParsedDocument(
            source_id=source.id,
            file_name=path.name,
            media_type="text/plain",
            company_name=company,
            report_year=report_year,
            content_sha256=_sha256(path),
            pages=pages,
            sections=sections,
            tables=tables,
            report_kind=report_kind.value,
            reporting_quarter=quarter,
            currency=currency,
        )


def _ocr_enabled_by_environment() -> bool:
    return os.getenv("DBGPT_FINANCIAL_OCR", "").strip().lower() in {"1", "true", "yes"}


class ParserRegistry:
    def __init__(
        self, enable_ocr: Optional[bool] = None, enable_geometry: bool = True
    ) -> None:
        ocr = _ocr_enabled_by_environment() if enable_ocr is None else enable_ocr
        self._parsers: list[DocumentParser] = [
            PdfPlumberParser(enable_ocr=ocr, enable_geometry=enable_geometry),
            PlainTextParser(),
        ]

    def parse(
        self, source: ResearchSource, enable_ocr: Optional[bool] = None
    ) -> ParsedDocument:
        path = Path(source.location).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Financial research source not found: {path}")
        for parser in self._parsers:
            if parser.supports(path):
                return parser.parse(source, enable_ocr)
        raise ValueError(f"Unsupported financial research file type: {path.suffix}")
