"""Ruling-based table reading used as an independent second opinion.

The primary reader (:mod:`parsers`) recovers rows from layout-preserved page
text and assigns columns positionally. That is fast and works on the filings it
was tuned against, but a shifted column or a wrapped label can move a value into
the wrong period without any signal that it happened.

This module reads the same pages through pdfplumber's ruling detection, which
derives cells from the drawn table borders instead of from text order. The two
readings are deliberately kept apart so :func:`cross_check_extraction` can report
where they disagree rather than one silently overriding the other.

It also supplies the cell bounding boxes the text reader cannot produce, so
evidence gains a physical location on the page.
"""

import logging
import re
from typing import List, Optional, Sequence

from ..domain.models import (
    BoundingBox,
    ConsolidationScope,
    ParsedTable,
    ParsedTableRow,
    ParsedTableValue,
    StatementType,
)

logger = logging.getLogger(__name__)

_NUMERIC_CELL_RE = re.compile(r"^[-−－(]?\d[\d,]*(?:\.\d+)?\)?%?$")


def _clean_cell(value: Optional[str]) -> str:
    return re.sub(r"\s+", "", value or "")


def _is_numeric(value: str) -> bool:
    return bool(_NUMERIC_CELL_RE.match(value))


def _table_settings() -> dict:
    # "lines" only: financial statements in these filings are fully ruled, and
    # text-based strategies would just reproduce the primary reader's behaviour.
    return {
        "vertical_strategy": "lines",
        "horizontal_strategy": "lines",
        "intersection_tolerance": 5,
        "join_tolerance": 5,
    }


def extract_geometric_tables(
    pdf, pages_of_interest: Sequence[int], columns: Sequence[str]
) -> List[ParsedTable]:
    """Read ruled tables on the given physical pages.

    ``columns`` supplies the period labels already resolved by the primary
    reader, so both readings share one column vocabulary and can be compared.
    Any page that yields no ruled table is skipped silently — absence of a
    second reading is not itself a finding.
    """
    tables: List[ParsedTable] = []
    for page_number in pages_of_interest:
        if page_number < 1 or page_number > len(pdf.pages):
            continue
        page = pdf.pages[page_number - 1]
        try:
            found = page.find_tables(table_settings=_table_settings())
        except Exception as exc:  # pragma: no cover - pdfplumber edge cases
            logger.debug(
                "Geometry table detection failed on page %s: %s", page_number, exc
            )
            continue
        for table_index, table in enumerate(found):
            rows = _rows_from_table(table, page_number, columns)
            if not rows:
                continue
            tables.append(
                ParsedTable(
                    name=f"几何识别表格 P{page_number}#{table_index + 1}",
                    statement_type=StatementType.COMPUTED,
                    scope=ConsolidationScope.UNSPECIFIED,
                    start_page=page_number,
                    end_page=page_number,
                    columns=list(columns),
                    rows=rows,
                    strategy="geometry",
                )
            )
    return tables


def _rows_from_table(
    table, page_number: int, columns: Sequence[str]
) -> List[ParsedTableRow]:
    try:
        extracted = table.extract()
    except Exception as exc:  # pragma: no cover - pdfplumber edge cases
        logger.debug("Geometry cell extraction failed on page %s: %s", page_number, exc)
        return []
    cell_boxes = _cell_boxes(table)
    rows: List[ParsedTableRow] = []
    for row_index, raw_row in enumerate(extracted or []):
        cells = [_clean_cell(cell) for cell in raw_row]
        label = next((cell for cell in cells if cell and not _is_numeric(cell)), "")
        if not label:
            continue
        numeric_positions = [
            (index, cell) for index, cell in enumerate(cells) if _is_numeric(cell)
        ]
        if not numeric_positions:
            continue
        values = [
            ParsedTableValue(
                column_index=order,
                column_label=columns[order],
                raw_value=cell,
                page_number=page_number,
                bbox=_box_for(cell_boxes, row_index, position),
            )
            for order, (position, cell) in enumerate(numeric_positions)
            if order < len(columns)
        ]
        if not values:
            continue
        rows.append(
            ParsedTableRow(
                row_index=len(rows),
                label=label,
                values=values,
                page_number=page_number,
                raw_text=" ".join(cell for cell in cells if cell),
            )
        )
    return rows


def _cell_boxes(table) -> dict:
    """Map ``(row, column)`` to a bounding box, when pdfplumber exposes cells."""

    boxes: dict = {}
    try:
        table_rows = table.rows
    except Exception:  # pragma: no cover - older pdfplumber
        return boxes
    for row_index, row in enumerate(table_rows):
        for column_index, cell in enumerate(getattr(row, "cells", []) or []):
            if not cell:
                continue
            x0, top, x1, bottom = cell
            boxes[(row_index, column_index)] = BoundingBox(
                x0=float(x0), top=float(top), x1=float(x1), bottom=float(bottom)
            )
    return boxes


def _box_for(boxes: dict, row_index: int, column_index: int) -> Optional[BoundingBox]:
    return boxes.get((row_index, column_index))
