"""Canonical reporting-period model.

Annual reports were the only shape the first implementation could represent: a
period was a bare four-digit year and every comparison assumed ``year - 1``.
Interim filings (半年度报告 / 季度报告) are routed to this agent, so periods must
be able to express them and still order and compare correctly.

Canonical forms
---------------
``2024``     full year (年度)
``2024H1``   first half year (半年度)
``2024Q1``   first quarter, and ``Q2``/``Q3``/``Q4`` likewise
``2024Q1-Q3`` first three quarters (前三季度), the CSRC third-quarter cumulative

Comparability rule: a period is only compared against the *same* interval of the
preceding year. ``2024H1`` compares to ``2023H1``, never to ``2023``.
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class PeriodKind(str, Enum):
    ANNUAL = "annual"
    HALF_YEAR = "half_year"
    QUARTER = "quarter"
    NINE_MONTH = "nine_month"


# Ordering within a year, so that sorting a mixed set stays deterministic.
_KIND_ORDER = {
    PeriodKind.QUARTER: 0,
    PeriodKind.HALF_YEAR: 1,
    PeriodKind.NINE_MONTH: 2,
    PeriodKind.ANNUAL: 3,
}

_ANNUAL_RE = re.compile(r"^(?P<year>20\d{2})$")
_HALF_RE = re.compile(r"^(?P<year>20\d{2})H1$")
_NINE_MONTH_RE = re.compile(r"^(?P<year>20\d{2})Q1-Q3$")
_QUARTER_RE = re.compile(r"^(?P<year>20\d{2})Q(?P<quarter>[1-4])$")


@dataclass(frozen=True)
class Period:
    """A parsed, canonical reporting period."""

    year: int
    kind: PeriodKind
    quarter: Optional[int] = None

    @property
    def canonical(self) -> str:
        if self.kind == PeriodKind.ANNUAL:
            return str(self.year)
        if self.kind == PeriodKind.HALF_YEAR:
            return f"{self.year}H1"
        if self.kind == PeriodKind.NINE_MONTH:
            return f"{self.year}Q1-Q3"
        return f"{self.year}Q{self.quarter}"

    @property
    def sort_key(self) -> tuple[int, int, int]:
        return (self.year, _KIND_ORDER[self.kind], self.quarter or 0)

    def previous_comparable(self) -> "Period":
        """The same interval one year earlier.

        Year-over-year is the only comparison the extractor can make safely: an
        interim period must never be compared against a full year, and a
        quarter must never be compared against the preceding quarter, because
        seasonality would be reported as growth.
        """
        return Period(year=self.year - 1, kind=self.kind, quarter=self.quarter)


def parse_period(value: str) -> Optional[Period]:
    """Parse a canonical period string, returning ``None`` when unrecognized."""

    if not isinstance(value, str):
        return None
    candidate = value.strip().upper().replace(" ", "")
    match = _ANNUAL_RE.match(candidate)
    if match:
        return Period(year=int(match.group("year")), kind=PeriodKind.ANNUAL)
    match = _HALF_RE.match(candidate)
    if match:
        return Period(year=int(match.group("year")), kind=PeriodKind.HALF_YEAR)
    # Nine-month must be tried before the plain quarter pattern.
    match = _NINE_MONTH_RE.match(candidate)
    if match:
        return Period(year=int(match.group("year")), kind=PeriodKind.NINE_MONTH)
    match = _QUARTER_RE.match(candidate)
    if match:
        return Period(
            year=int(match.group("year")),
            kind=PeriodKind.QUARTER,
            quarter=int(match.group("quarter")),
        )
    return None


def is_valid_period(value: str) -> bool:
    return parse_period(value) is not None


def previous_comparable_period(value: str) -> Optional[str]:
    """Canonical string for the prior-year equivalent interval."""

    period = parse_period(value)
    return period.previous_comparable().canonical if period else None


def period_sort_key(value: str) -> tuple[int, int, int]:
    """Sort key that keeps unparseable values last rather than raising."""

    period = parse_period(value)
    return period.sort_key if period else (-1, -1, -1)


def period_for_year_offset(value: str, offset: int) -> Optional[str]:
    period = parse_period(value)
    if not period:
        return None
    shifted = Period(
        year=period.year + offset, kind=period.kind, quarter=period.quarter
    )
    return shifted.canonical


def period_display_name(value: str) -> str:
    """Simplified-Chinese display label for a canonical reporting period."""

    period = parse_period(value)
    if period is None:
        return value
    if period.kind == PeriodKind.ANNUAL:
        return f"{period.year}年"
    if period.kind == PeriodKind.HALF_YEAR:
        return f"{period.year}年上半年"
    if period.kind == PeriodKind.NINE_MONTH:
        return f"{period.year}年前三季度"
    quarter_names = {1: "第一季度", 2: "第二季度", 3: "第三季度", 4: "第四季度"}
    return f"{period.year}年{quarter_names.get(period.quarter or 0, '季度')}"


# --- Document-level report kind detection -----------------------------------
#
# The column labels a parser can emit depend on what kind of filing it is
# reading. These markers are matched against the report title, not arbitrary
# body text, so a mention of "半年度" inside a note cannot reclassify a filing.

_REPORT_KIND_MARKERS = (
    ("半年度报告", PeriodKind.HALF_YEAR, None),
    ("第一季度报告", PeriodKind.QUARTER, 1),
    ("第三季度报告", PeriodKind.NINE_MONTH, None),
    ("三季度报告", PeriodKind.NINE_MONTH, None),
    ("第二季度报告", PeriodKind.QUARTER, 2),
    ("第四季度报告", PeriodKind.QUARTER, 4),
    ("季度报告", PeriodKind.QUARTER, 1),
    ("年度报告", PeriodKind.ANNUAL, None),
)


def detect_report_kind(title_text: str) -> tuple[PeriodKind, Optional[int]]:
    """Infer the filing's reporting interval from its title text.

    Defaults to annual, which is what the extraction catalog is built for.
    """
    compact = re.sub(r"\s+", "", title_text or "")
    for marker, kind, quarter in _REPORT_KIND_MARKERS:
        if marker in compact:
            return kind, quarter
    return PeriodKind.ANNUAL, None


def build_period(year: int, kind: PeriodKind, quarter: Optional[int] = None) -> str:
    """Canonical period string for a year and reporting interval."""

    if kind == PeriodKind.QUARTER and quarter is None:
        quarter = 1
    return Period(year=year, kind=kind, quarter=quarter).canonical
