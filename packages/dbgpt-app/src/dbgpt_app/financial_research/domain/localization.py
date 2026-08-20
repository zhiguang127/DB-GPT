"""Locale-aware value formatting and enum display labels.

Two defects motivated this module:

1. Money was rendered as ``百万元`` — a calque of "millions". Chinese financial
   writing scales on 万 (10^4) and 亿 (10^8), so ``318.02 百万元`` has to read
   ``3.18 亿元``.
2. Enum members were printed by ``.value`` straight into a ``lang="zh-CN"``
   report, so hundreds of raw tokens (``consolidated``, ``balance_sheet``,
   ``supported`` …) appeared in Chinese prose.

Labels are keyed by locale so a second locale is a data change, not a code
change. This is deliberately a display map rather than gettext: the domain still
holds Chinese literals in generated prose, so wiring the whole module into
``dbgpt.util.i18n_utils`` remains outstanding work. Keeping the map here means
that refactor has a single place to hook into.
"""

from typing import Dict, Optional, Tuple

from .models import (
    AnalysisStatus,
    ConsolidationScope,
    FindingTone,
    InvestigationStatus,
    IssueSeverity,
    MetricUnit,
    PeriodType,
    PlanStatus,
    ResearchStatus,
    StatementType,
)
from .periods import period_display_name

DEFAULT_LOCALE = "zh_CN"

# Money unit words per currency: (base, 万-scale, 亿-scale).
_CURRENCY_UNITS: Dict[str, Dict[str, Tuple[str, str, str]]] = {
    "zh_CN": {
        "CNY": ("元", "万元", "亿元"),
        "HKD": ("港元", "万港元", "亿港元"),
        "MOP": ("澳门元", "万澳门元", "亿澳门元"),
        "TWD": ("新台币元", "万新台币元", "亿新台币元"),
        "JPY": ("日元", "万日元", "亿日元"),
        "KRW": ("韩元", "万韩元", "亿韩元"),
        "USD": ("美元", "万美元", "亿美元"),
        "EUR": ("欧元", "万欧元", "亿欧元"),
        "SGD": ("新加坡元", "万新加坡元", "亿新加坡元"),
    }
}

_UNKNOWN_CURRENCY_UNITS = ("元", "万元", "亿元")

_HUNDRED_MILLION = 100_000_000.0
_TEN_THOUSAND = 10_000.0


def money_units(
    currency: Optional[str], locale: str = DEFAULT_LOCALE
) -> Tuple[str, str, str]:
    table = _CURRENCY_UNITS.get(locale, _CURRENCY_UNITS[DEFAULT_LOCALE])
    return table.get(currency or "CNY", _UNKNOWN_CURRENCY_UNITS)


def format_money(
    value: float,
    currency: Optional[str] = "CNY",
    locale: str = DEFAULT_LOCALE,
) -> str:
    """Format an amount on the native 万 / 亿 scale.

    The scale is chosen from the magnitude so that a figure always reads at a
    human size: 亿 above 10^8, 万 above 10^4, bare currency below that.
    """
    base, ten_thousand, hundred_million = money_units(currency, locale)
    magnitude = abs(value)
    if magnitude >= _HUNDRED_MILLION:
        return f"{value / _HUNDRED_MILLION:,.2f} {hundred_million}"
    if magnitude >= _TEN_THOUSAND:
        return f"{value / _TEN_THOUSAND:,.2f} {ten_thousand}"
    return f"{value:,.2f} {base}"


def money_scale_for(
    values, currency: Optional[str] = "CNY", locale: str = DEFAULT_LOCALE
) -> Tuple[float, str]:
    """Pick one shared divisor and unit word for a whole series.

    Charts must not mix scales across bars, so the unit is chosen from the
    largest magnitude in the series and applied uniformly.
    """
    base, ten_thousand, hundred_million = money_units(currency, locale)
    magnitudes = [abs(float(item)) for item in values if item is not None]
    peak = max(magnitudes) if magnitudes else 0.0
    if peak >= _HUNDRED_MILLION:
        return _HUNDRED_MILLION, hundred_million
    if peak >= _TEN_THOUSAND:
        return _TEN_THOUSAND, ten_thousand
    return 1.0, base


def format_percent(value: float) -> str:
    return f"{value:.2f}%"


def format_ratio(value: float) -> str:
    return f"{value:.2f}"


# --- Enum display labels ----------------------------------------------------

_LABELS: Dict[str, Dict[str, Dict[str, str]]] = {
    "zh_CN": {
        "statement_type": {
            StatementType.SUMMARY.value: "主要财务指标",
            StatementType.BALANCE_SHEET.value: "资产负债表",
            StatementType.INCOME_STATEMENT.value: "利润表",
            StatementType.CASH_FLOW_STATEMENT.value: "现金流量表",
            StatementType.SEGMENT_DISCLOSURE.value: "分部披露",
            StatementType.NON_RECURRING_DISCLOSURE.value: "非经常性损益披露",
            StatementType.NOTE.value: "附注",
            StatementType.COMPUTED.value: "派生计算",
        },
        "scope": {
            ConsolidationScope.CONSOLIDATED.value: "合并口径",
            ConsolidationScope.PARENT_COMPANY.value: "母公司口径",
            ConsolidationScope.UNSPECIFIED.value: "口径未标明",
        },
        "investigation_status": {
            InvestigationStatus.SUPPORTED.value: "证据支持",
            InvestigationStatus.PARTIAL.value: "部分支持",
            InvestigationStatus.UNRESOLVED.value: "尚未查明",
            InvestigationStatus.REJECTED.value: "证据否定",
        },
        "analysis_status": {
            AnalysisStatus.COMPLETED.value: "已完成",
            AnalysisStatus.PARTIAL.value: "部分完成",
            AnalysisStatus.INSUFFICIENT_DATA.value: "资料不足",
        },
        "tone": {
            FindingTone.POSITIVE.value: "积极",
            FindingTone.NEUTRAL.value: "中性",
            FindingTone.WATCH.value: "需关注",
            FindingTone.WARNING.value: "警示",
        },
        "severity": {
            IssueSeverity.INFO.value: "提示",
            IssueSeverity.WARNING.value: "警告",
            IssueSeverity.ERROR.value: "错误",
        },
        "period_type": {
            PeriodType.INSTANT.value: "时点",
            PeriodType.DURATION.value: "期间",
        },
        "plan_status": {
            PlanStatus.PENDING.value: "待执行",
            PlanStatus.RUNNING.value: "执行中",
            PlanStatus.COMPLETED.value: "已完成",
            PlanStatus.FAILED.value: "已失败",
        },
        "research_status": {
            ResearchStatus.PENDING.value: "待执行",
            ResearchStatus.RUNNING.value: "执行中",
            ResearchStatus.COMPLETED.value: "已完成",
            ResearchStatus.FAILED.value: "已失败",
        },
        "unit": {
            MetricUnit.MONEY.value: "货币金额",
            MetricUnit.CNY.value: "货币金额",
            MetricUnit.PERCENT.value: "%",
            MetricUnit.MONEY_PER_SHARE.value: "每股金额",
            MetricUnit.CNY_PER_SHARE.value: "每股金额",
            MetricUnit.RATIO.value: "倍",
        },
    }
}


def _enum_key(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


class Labels:
    """Locale-bound enum label lookup used by templates and streaming.

    Unknown members fall back to the raw value so a newly added enum member
    degrades to its identifier instead of raising during report rendering.
    """

    def __init__(self, locale: str = DEFAULT_LOCALE) -> None:
        self.locale = locale
        self._table = _LABELS.get(locale, _LABELS[DEFAULT_LOCALE])

    def _lookup(self, group: str, value) -> str:
        key = _enum_key(value)
        return self._table.get(group, {}).get(key, key)

    def statement_type(self, value) -> str:
        return self._lookup("statement_type", value)

    def scope(self, value) -> str:
        return self._lookup("scope", value)

    def investigation_status(self, value) -> str:
        return self._lookup("investigation_status", value)

    def analysis_status(self, value) -> str:
        return self._lookup("analysis_status", value)

    def tone(self, value) -> str:
        return self._lookup("tone", value)

    def severity(self, value) -> str:
        return self._lookup("severity", value)

    def period_type(self, value) -> str:
        return self._lookup("period_type", value)

    def plan_status(self, value) -> str:
        return self._lookup("plan_status", value)

    def research_status(self, value) -> str:
        return self._lookup("research_status", value)

    def unit(self, value) -> str:
        return self._lookup("unit", value)

    def money(self, value: float, currency: Optional[str] = "CNY") -> str:
        return format_money(value, currency, self.locale)

    def amount(self, value: float, unit, currency: Optional[str] = None) -> str:
        """Render a value with the notation its unit calls for.

        Monetary amounts scale onto 万 / 亿 and carry the currency word; rates
        and multiples keep their own suffix. Accepts either a ``MetricUnit`` or
        its raw string so templates can pass serialized payloads unchanged.
        """
        key = _enum_key(unit)
        if key in {MetricUnit.MONEY.value, MetricUnit.CNY.value}:
            return format_money(value, currency or "CNY", self.locale)
        if key == MetricUnit.PERCENT.value:
            return format_percent(value)
        if key == MetricUnit.RATIO.value:
            return f"{format_ratio(value)} 倍"
        if key in {
            MetricUnit.MONEY_PER_SHARE.value,
            MetricUnit.CNY_PER_SHARE.value,
        }:
            base, _, _ = money_units(currency or "CNY", self.locale)
            return f"{value:,.4f} {base}/股"
        return f"{value:,.2f}"

    def metric(self, metric) -> str:
        """Formatted value for a :class:`FinancialMetric`-shaped object."""

        return self.amount(metric.value, metric.unit, getattr(metric, "currency", None))

    def period(self, value: str) -> str:
        return period_display_name(value)


def get_labels(locale: str = DEFAULT_LOCALE) -> Labels:
    return Labels(locale)


def all_label_values(locale: str = DEFAULT_LOCALE) -> set:
    """Every raw enum key that has a display label, for leak-detection tests."""

    table = _LABELS.get(locale, _LABELS[DEFAULT_LOCALE])
    return {key for group in table.values() for key in group}
