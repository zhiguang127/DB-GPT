"""Dependency-light deterministic SVG chart rendering."""

from collections import defaultdict
from html import escape
from pathlib import Path
from typing import Iterable, List, Optional

from ...domain.localization import money_scale_for
from ...domain.models import MONEY_UNITS, ChartArtifact, FinancialMetric
from ...domain.periods import period_display_name, period_sort_key

# Every text node carries this explicitly. Inline in the report the SVG would
# inherit the page font, but each chart is also written as a standalone file and
# may be opened directly or converted to PDF/PNG — where an unset font-family
# falls back to a host default that frequently has no CJK glyphs, rendering
# every Chinese label as tofu boxes.
CJK_FONT_STACK = (
    "&quot;Noto Sans CJK SC&quot;,&quot;Source Han Sans SC&quot;,"
    "&quot;Microsoft YaHei&quot;,&quot;PingFang SC&quot;,sans-serif"
)


def _text(
    x: float,
    y: float,
    content: str,
    *,
    size: int,
    fill: str,
    anchor: Optional[str] = None,
    weight: Optional[str] = None,
) -> str:
    attributes = [
        f'x="{x:.1f}"',
        f'y="{y:.1f}"',
        f'font-family="{CJK_FONT_STACK}"',
        f'font-size="{size}"',
        f'fill="{fill}"',
    ]
    if anchor:
        attributes.append(f'text-anchor="{anchor}"')
    if weight:
        attributes.append(f'font-weight="{weight}"')
    return f"<text {' '.join(attributes)}>{escape(content)}</text>"


def _currency_of(metrics: Iterable[FinancialMetric]) -> Optional[str]:
    for metric in metrics:
        if metric.unit in MONEY_UNITS and metric.currency:
            return metric.currency
    return "CNY"


def _write_svg(
    path: Path, title: str, labels: list[str], series: list[tuple[str, list[float]]]
) -> None:
    width, height = 920, 420
    left, right, top, bottom = 90, 30, 65, 70
    chart_width = width - left - right
    chart_height = height - top - bottom
    values = [value for _name, data in series for value in data]
    min_value = min([0.0, *values])
    max_value = max([0.0, *values])
    value_range = max_value - min_value or 1
    zero_y = top + chart_height * max_value / value_range
    group_width = chart_width / max(len(labels), 1)
    bar_width = min(54, group_width / max(len(series) + 1, 2))
    colors = ["#356df3", "#20a57a", "#f59e0b", "#7c5ce7"]

    parts = [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}">'
        ),
        '<rect width="100%" height="100%" rx="16" fill="#ffffff"/>',
        _text(left, 34, title, size=22, fill="#172033", weight="700"),
        (
            f'<line x1="{left}" y1="{zero_y:.1f}" '
            f'x2="{left + chart_width}" y2="{zero_y:.1f}" '
            'stroke="#94a3b8"/>'
        ),
    ]
    for tick in range(5):
        value = min_value + value_range * tick / 4
        y = top + chart_height - chart_height * (value - min_value) / value_range
        parts.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{left + chart_width}" '
            f'y2="{y:.1f}" stroke="#edf0f6"/>'
        )
        parts.append(
            _text(
                left - 10,
                y + 4,
                f"{value:,.1f}",
                size=12,
                fill="#64748b",
                anchor="end",
            )
        )
    for label_index, label in enumerate(labels):
        center = left + group_width * (label_index + 0.5)
        parts.append(
            _text(
                center,
                height - 30,
                label,
                size=13,
                fill="#475569",
                anchor="middle",
            )
        )
        for series_index, (series_name, data) in enumerate(series):
            if label_index >= len(data):
                continue
            value = data[label_index]
            value_y = (
                top + chart_height - chart_height * (value - min_value) / value_range
            )
            bar_height = abs(zero_y - value_y)
            x = (
                center
                + (series_index - (len(series) - 1) / 2) * (bar_width + 8)
                - bar_width / 2
            )
            y = min(zero_y, value_y)
            color = colors[series_index % len(colors)]
            parts.append(
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" '
                f'height="{bar_height:.1f}" rx="4" fill="{color}"/>'
            )
            label_y = (
                max(y - 7, top + 12)
                if value >= 0
                else min(y + bar_height + 16, height - bottom + 20)
            )
            parts.append(
                _text(
                    x + bar_width / 2,
                    label_y,
                    f"{value:,.1f}",
                    size=11,
                    fill="#334155",
                    anchor="middle",
                )
            )
    for series_index, (series_name, _data) in enumerate(series):
        x = left + series_index * 130
        parts.append(
            f'<rect x="{x}" y="{height - 14}" width="10" height="10" '
            f'rx="2" fill="{colors[series_index % len(colors)]}"/>'
        )
        parts.append(_text(x + 16, height - 5, series_name, size=12, fill="#475569"))
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def generate_charts(
    metrics: Iterable[FinancialMetric], output_dir: Path
) -> List[ChartArtifact]:
    output_dir.mkdir(parents=True, exist_ok=True)
    metric_list = list(metrics)
    companies = sorted({metric.company_name for metric in metric_list})
    if len(companies) > 1:
        return _generate_peer_charts(metric_list, companies, output_dir)
    return _generate_company_charts(metric_list, output_dir)


def _generate_company_charts(
    metrics: List[FinancialMetric], output_dir: Path
) -> List[ChartArtifact]:
    grouped = defaultdict(list)
    for metric in metrics:
        grouped[metric.name].append(metric)

    money_names = ["revenue", "net_profit", "operating_cash_flow"]
    available_names = [name for name in money_names if grouped.get(name)]
    labels = [grouped[name][0].display_name for name in available_names]
    periods = sorted(
        {item.period for item in metrics}, key=period_sort_key, reverse=True
    )[:3]
    currency = _currency_of(item for name in available_names for item in grouped[name])
    # One divisor and unit word for the whole chart: mixing 万 and 亿 between
    # bars would make the axis meaningless.
    divisor, unit_word = money_scale_for(
        [
            item.value
            for name in available_names
            for item in grouped[name]
            if item.period in periods
        ],
        currency,
    )
    series_by_period = []
    for period in periods:
        values = []
        for name in available_names:
            item = next(
                (
                    candidate
                    for candidate in grouped[name]
                    if candidate.period == period
                ),
                None,
            )
            values.append((item.value / divisor) if item else 0)
        series_by_period.append((period_display_name(period), values))

    artifacts: List[ChartArtifact] = []
    if labels and series_by_period:
        path = output_dir / "key_metrics.svg"
        _write_svg(path, f"核心指标趋势（{unit_word}）", labels, series_by_period)
        artifacts.append(ChartArtifact(title="核心指标对比", path=str(path)))

    rate_labels = []
    rate_series = []
    for name in ("weighted_roe", "net_margin"):
        items = sorted(
            grouped.get(name, []),
            key=lambda item: period_sort_key(item.period),
            reverse=True,
        )
        if not items:
            continue
        rate_labels.append(items[0].display_name)
        rate_series.append(items)
    if rate_labels:
        periods = sorted(
            {item.period for items in rate_series for item in items},
            key=period_sort_key,
            reverse=True,
        )[:2]
        data = []
        for period in periods:
            values = []
            for items in rate_series:
                item = next(
                    (candidate for candidate in items if candidate.period == period),
                    None,
                )
                values.append(item.value if item else 0)
            data.append((period_display_name(period), values))
        path = output_dir / "profitability.svg"
        _write_svg(path, "盈利能力趋势（%）", rate_labels, data)
        artifacts.append(ChartArtifact(title="盈利能力指标", path=str(path)))

    for name, title, file_name in (
        ("cash_profit_ratio", "利润现金含量趋势（倍）", "cash_quality.svg"),
        ("asset_turnover", "资产周转效率趋势（次）", "asset_efficiency.svg"),
    ):
        items = grouped.get(name, [])
        if not items:
            continue
        ratio_periods = sorted(
            {item.period for item in items}, key=period_sort_key, reverse=True
        )[:3]
        ratio_data = [
            (
                period_display_name(period),
                [next(item.value for item in items if item.period == period)],
            )
            for period in ratio_periods
        ]
        path = output_dir / file_name
        _write_svg(path, title, [items[0].display_name], ratio_data)
        artifacts.append(ChartArtifact(title=title, path=str(path)))
    return artifacts


def _generate_peer_charts(
    metrics: List[FinancialMetric], companies: List[str], output_dir: Path
) -> List[ChartArtifact]:
    company_counts = defaultdict(set)
    for metric in metrics:
        company_counts[metric.period].add(metric.company_name)
    periods = [
        period
        for period, period_companies in company_counts.items()
        if len(period_companies) > 1
    ]
    if not periods:
        return []
    period = max(periods, key=period_sort_key)

    artifacts: List[ChartArtifact] = []
    money_specs = (
        ("revenue", "营业收入"),
        ("net_profit", "归母净利润"),
        ("operating_cash_flow", "经营现金流"),
    )
    money_names = {name for name, _ in money_specs}
    comparable = [
        metric
        for metric in metrics
        if metric.period == period and metric.name in money_names
    ]
    currency = _currency_of(comparable)
    divisor, unit_word = money_scale_for(
        [metric.value for metric in comparable], currency
    )
    money_series = []
    for name, display_name in money_specs:
        values = []
        for company in companies:
            item = next(
                (
                    metric
                    for metric in metrics
                    if metric.company_name == company
                    and metric.period == period
                    and metric.name == name
                ),
                None,
            )
            values.append((item.value / divisor) if item else 0)
        if any(value != 0 for value in values):
            money_series.append((display_name, values))
    if money_series:
        path = output_dir / "peer_key_metrics.svg"
        _write_svg(
            path,
            f"{period_display_name(period)}公司核心指标对比（{unit_word}）",
            companies,
            money_series,
        )
        artifacts.append(ChartArtifact(title="公司核心指标对比", path=str(path)))

    profitability_series = []
    for name, display_name in (
        ("weighted_roe", "加权平均净资产收益率"),
        ("net_margin", "净利率"),
    ):
        values = []
        for company in companies:
            item = next(
                (
                    metric
                    for metric in metrics
                    if metric.company_name == company
                    and metric.period == period
                    and metric.name == name
                ),
                None,
            )
            values.append(item.value if item else 0)
        if any(value != 0 for value in values):
            profitability_series.append((display_name, values))
    if profitability_series:
        path = output_dir / "peer_profitability.svg"
        _write_svg(
            path,
            f"{period_display_name(period)}公司盈利能力对比（%）",
            companies,
            profitability_series,
        )
        artifacts.append(ChartArtifact(title="公司盈利能力对比", path=str(path)))

    for name, title, file_name in (
        ("cash_profit_ratio", "公司利润现金含量对比（倍）", "peer_cash_quality.svg"),
        ("asset_turnover", "公司资产周转效率对比（次）", "peer_efficiency.svg"),
    ):
        values = []
        for company in companies:
            item = next(
                (
                    metric
                    for metric in metrics
                    if metric.company_name == company
                    and metric.period == period
                    and metric.name == name
                ),
                None,
            )
            values.append(item.value if item else 0)
        if not any(value != 0 for value in values):
            continue
        path = output_dir / file_name
        # The period label already carries its own granularity (2024 / 2024H1),
        # so appending 年 would read "2024H1 年".
        _write_svg(path, f"{period} {title}", companies, [(title, values)])
        artifacts.append(ChartArtifact(title=title, path=str(path)))
    return artifacts
