"""Investigation-led financial research with traceable causal chains."""

import re
from collections import defaultdict
from typing import Iterable, Optional, Sequence

from .analysis import analyze_metrics
from .localization import format_money
from .models import (
    MONEY_UNITS,
    AnalysisSection,
    AnalysisStatus,
    Computation,
    Evidence,
    FinancialAnomaly,
    FinancialMetric,
    FindingTone,
    InvestigationStatus,
    IssueSeverity,
    ParsedDocument,
    ResearchFinding,
    ResearchHypothesis,
    ValidationIssue,
)
from .periods import (
    period_display_name,
    period_sort_key,
    previous_comparable_period,
)


def _grouped(
    metrics: Iterable[FinancialMetric],
) -> dict[str, dict[str, list[FinancialMetric]]]:
    result: dict[str, dict[str, list[FinancialMetric]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for metric in metrics:
        result[metric.company_name][metric.name].append(metric)
    for company_metrics in result.values():
        for items in company_metrics.values():
            items.sort(key=lambda item: period_sort_key(item.period), reverse=True)
    return result


def _growth(current: float, previous: float) -> Optional[float]:
    if previous == 0:
        return None
    return (current - previous) / abs(previous) * 100


def _evidence_ids(metrics: Sequence[FinancialMetric]) -> list[str]:
    return list(
        dict.fromkeys(
            evidence_id for metric in metrics for evidence_id in metric.evidence_ids
        )
    )


def _unique_metrics(metrics: Iterable[FinancialMetric]) -> list[FinancialMetric]:
    return list({metric.id: metric for metric in metrics}.values())


def _money(value: float, currency: Optional[str] = "CNY") -> str:
    """Format an amount on the native 万 / 亿 scale for the metric's currency."""

    return format_money(value, currency)


def _metric_money(metric: FinancialMetric) -> str:
    return format_money(metric.value, metric.currency)


def _currency_of(company_values) -> Optional[str]:
    """The reporting currency for a company's metrics, for derived amounts.

    Differences and residuals are computed from metrics, so they inherit the
    currency of their inputs; validation already blocks a company-period from
    holding more than one.
    """
    for items in company_values.values():
        for item in items:
            if item.unit in MONEY_UNITS and item.currency:
                return item.currency
    return "CNY"


def _series_text(items: Sequence[FinancialMetric], *, money: bool = True) -> str:
    ordered = sorted(items, key=lambda item: period_sort_key(item.period))
    return " → ".join(
        f"{item.period}：{_metric_money(item) if money else f'{item.value:.2f}%'}"
        for item in ordered
    )


def _section_status(findings: Sequence[ResearchFinding]) -> AnalysisStatus:
    if not findings:
        return AnalysisStatus.INSUFFICIENT_DATA
    if any(finding.status != InvestigationStatus.SUPPORTED for finding in findings):
        return AnalysisStatus.PARTIAL
    return AnalysisStatus.COMPLETED


def _finding(
    *,
    title: str,
    summary: str,
    topic_key: str,
    metrics: Sequence[FinancialMetric],
    company: Optional[str] = None,
    period: Optional[str] = None,
    tone: FindingTone = FindingTone.NEUTRAL,
    status: InvestigationStatus = InvestigationStatus.SUPPORTED,
    calculation: Optional[str] = None,
    reasoning_steps: Sequence[str] = (),
    counter_evidence: Sequence[str] = (),
    unanswered_questions: Sequence[str] = (),
    materiality: float = 0.0,
) -> ResearchFinding:
    metric_list = _unique_metrics(metrics)
    return ResearchFinding(
        title=title,
        summary=summary,
        topic_key=topic_key,
        tone=tone,
        status=status,
        company_name=company,
        period=period,
        calculation=calculation,
        reasoning_steps=list(reasoning_steps),
        counter_evidence=list(counter_evidence),
        unanswered_questions=list(unanswered_questions),
        materiality=materiality,
        metric_ids=[metric.id for metric in metric_list],
        evidence_ids=_evidence_ids(metric_list),
    )


def _pair(
    items: Sequence[FinancialMetric],
) -> tuple[FinancialMetric, FinancialMetric] | None:
    """The latest observation paired with its prior-year equivalent.

    ``items`` is ordered newest-first. Taking ``items[1]`` blindly would pair an
    interim period with a full year once interim filings are in scope, so the
    comparative is matched by canonical period instead of by position.
    """
    if len(items) < 2:
        return None
    current = items[0]
    comparable = previous_comparable_period(current.period)
    previous = next((item for item in items[1:] if item.period == comparable), None)
    return (current, previous) if previous else None


def detect_financial_anomalies(
    metrics: Iterable[FinancialMetric],
) -> list[FinancialAnomaly]:
    """Select research questions from cross-metric and multi-period divergence."""

    anomalies: list[FinancialAnomaly] = []
    for company, values in _grouped(metrics).items():
        currency = _currency_of(values)
        revenue_pair = _pair(values.get("revenue", []))
        profit_pair = _pair(values.get("net_profit", []))
        adjusted_pair = _pair(values.get("non_recurring_net_profit", []))
        cash_pair = _pair(values.get("operating_cash_flow", []))
        roe = values.get("weighted_roe", [])

        if revenue_pair and profit_pair:
            revenue_growth = _growth(revenue_pair[0].value, revenue_pair[1].value)
            profit_growth = _growth(profit_pair[0].value, profit_pair[1].value)
            if revenue_growth is not None and profit_growth is not None:
                divergence = profit_growth - revenue_growth
                if abs(divergence) >= 5 or profit_growth < 0:
                    used = [*revenue_pair, *profit_pair]
                    anomalies.append(
                        FinancialAnomaly(
                            topic_key="earnings_quality",
                            company_name=company,
                            period=profit_pair[0].period,
                            signal=(
                                f"利润同比 {profit_growth:+.2f}%，收入同比 "
                                f"{revenue_growth:+.2f}%，两者相差 "
                                f"{divergence:+.2f} 个百分点"
                            ),
                            materiality=abs(divergence),
                            metric_ids=[item.id for item in used],
                            evidence_ids=_evidence_ids(used),
                        )
                    )

        if profit_pair and adjusted_pair:
            profit_growth = _growth(profit_pair[0].value, profit_pair[1].value)
            adjusted_growth = _growth(adjusted_pair[0].value, adjusted_pair[1].value)
            effect = profit_pair[0].value - adjusted_pair[0].value
            effect_share = (
                effect / abs(profit_pair[0].value) * 100
                if profit_pair[0].value
                else 0.0
            )
            if (
                abs(effect_share) >= 10
                or profit_growth is not None
                and adjusted_growth is not None
                and abs(adjusted_growth - profit_growth) >= 5
            ):
                used = [*profit_pair, *adjusted_pair]
                anomalies.append(
                    FinancialAnomaly(
                        topic_key="core_earnings",
                        company_name=company,
                        period=profit_pair[0].period,
                        signal=(
                            f"扣非利润与归母净利润差额为 "
                            f"{_money(effect, currency)}，"
                            f"相当于归母净利润的 {effect_share:.2f}%"
                        ),
                        materiality=abs(effect_share),
                        metric_ids=[item.id for item in used],
                        evidence_ids=_evidence_ids(used),
                    )
                )

        if cash_pair and profit_pair:
            cash_growth = _growth(cash_pair[0].value, cash_pair[1].value)
            profit_growth = _growth(profit_pair[0].value, profit_pair[1].value)
            divergence = (
                cash_growth - profit_growth
                if cash_growth is not None and profit_growth is not None
                else 0.0
            )
            if cash_pair[0].value < 0 or abs(divergence) >= 15:
                used = [*cash_pair, *profit_pair]
                signal = "经营现金流与利润方向不一致"
                if cash_growth is not None:
                    signal = (
                        f"经营现金流同比 {cash_growth:+.2f}%，与利润增速相差 "
                        f"{divergence:+.2f} 个百分点"
                    )
                anomalies.append(
                    FinancialAnomaly(
                        topic_key="cash_conversion",
                        company_name=company,
                        period=cash_pair[0].period,
                        signal=signal,
                        materiality=abs(divergence),
                        metric_ids=[item.id for item in used],
                        evidence_ids=_evidence_ids(used),
                    )
                )

        if len(roe) >= 3 and all(
            newer.value < older.value for newer, older in zip(roe, roe[1:])
        ):
            used = roe[:3]
            anomalies.append(
                FinancialAnomaly(
                    topic_key="capital_returns",
                    company_name=company,
                    period=roe[0].period,
                    signal=f"ROE 连续下降：{_series_text(used, money=False)}",
                    materiality=roe[2].value - roe[0].value,
                    metric_ids=[item.id for item in used],
                    evidence_ids=_evidence_ids(used),
                )
            )
    return anomalies


def formulate_hypotheses(
    anomalies: Iterable[FinancialAnomaly],
) -> list[ResearchHypothesis]:
    templates = {
        "earnings_quality": (
            (
                "毛利率是否下降",
                "成本或产品结构变化压缩了毛利",
                ("revenue", "operating_cost"),
            ),
            (
                "期间费用是否侵蚀利润",
                "销售、管理、研发或财务费用增长快于收入",
                (
                    "selling_expenses",
                    "administrative_expenses",
                    "research_and_development_expenses",
                    "finance_expenses",
                ),
            ),
        ),
        "core_earnings": (
            (
                "表面利润是否受到非经常性项目支撑",
                "非经常性损益缓冲了核心经营利润的下降",
                (
                    "net_profit",
                    "non_recurring_net_profit",
                    "non_recurring_item",
                ),
            ),
        ),
        "cash_conversion": (
            (
                "经营现金流下降由哪些收付项目造成",
                "销售回款或经营支出的变化造成现金流回落",
                ("operating_cash_inflow", "operating_cash_outflow"),
            ),
            (
                "营运资本是否形成现金占用",
                "应收、合同资产或存货增加占用了经营现金",
                ("accounts_receivable", "contract_assets", "inventory"),
            ),
        ),
        "capital_returns": (
            (
                "ROE 下行由效率还是盈利驱动",
                "利润率或资产周转下降拖累资本回报",
                ("net_margin", "asset_turnover", "weighted_roe"),
            ),
        ),
    }
    result: list[ResearchHypothesis] = []
    for anomaly in anomalies:
        for question, hypothesis, required in templates.get(anomaly.topic_key, ()):
            result.append(
                ResearchHypothesis(
                    anomaly_id=anomaly.id,
                    topic_key=anomaly.topic_key,
                    company_name=anomaly.company_name,
                    question=question,
                    hypothesis=hypothesis,
                    required_metrics=list(required),
                )
            )
    return result


def _set_hypothesis(
    hypotheses: Iterable[ResearchHypothesis],
    *,
    company: str,
    question_marker: str,
    status: InvestigationStatus,
    resolution: str,
    metrics: Sequence[FinancialMetric],
) -> None:
    for hypothesis in hypotheses:
        if (
            hypothesis.company_name != company
            or question_marker not in hypothesis.question
        ):
            continue
        hypothesis.status = status
        hypothesis.resolution = resolution
        hypothesis.metric_ids = [item.id for item in _unique_metrics(metrics)]
        hypothesis.evidence_ids = _evidence_ids(metrics)


PROFIT_BRIDGE_COMPONENTS = (
    ("revenue", "营业收入", 1),
    ("operating_cost", "营业成本", -1),
    ("taxes_and_surcharges", "税金及附加", -1),
    ("selling_expenses", "销售费用", -1),
    ("administrative_expenses", "管理费用", -1),
    ("research_and_development_expenses", "研发费用", -1),
    ("finance_expenses", "财务费用", -1),
    ("other_income", "其他收益", 1),
    ("investment_income", "投资收益", 1),
    ("fair_value_change_income", "公允价值变动收益", 1),
    ("credit_impairment_loss", "信用减值损失", 1),
    ("asset_impairment_loss", "资产减值损失", 1),
    ("asset_disposal_income", "资产处置收益", 1),
    ("non_operating_income", "营业外收入", 1),
    ("non_operating_expense", "营业外支出", -1),
    ("income_tax_expense", "所得税费用", -1),
    ("minority_profit", "少数股东损益", -1),
)


def _change_bridge(company_metrics, target_name: str, components):
    target_pair = _pair(company_metrics.get(target_name, []))
    if not target_pair:
        return None
    target_change = target_pair[0].value - target_pair[1].value
    drivers = []
    used: list[FinancialMetric] = [*target_pair]
    for name, label, sign in components:
        pair = _pair(company_metrics.get(name, []))
        if not pair:
            continue
        effect = sign * (pair[0].value - pair[1].value)
        drivers.append((label, effect, pair))
        used.extend(pair)
    explained = sum(effect for _, effect, _ in drivers)
    residual = target_change - explained
    # Reconciliation coverage is measured against the target movement. Using
    # gross absolute driver changes would overstate coverage when large positive
    # and negative effects cancel each other.
    denominator = max(abs(target_change), 1.0)
    coverage = max(0.0, 1 - abs(residual) / denominator) * 100
    return target_pair, target_change, drivers, residual, coverage, used


# Materiality floors for emitting a separate conclusion. They exist so that a
# rounding-level movement does not become its own headline; they are not risk
# thresholds and are never used to label a company good or bad.
_MARGIN_MATERIALITY_PP = 0.5
_EXPENSE_MATERIALITY_PP = 0.3
_BALANCE_MATERIALITY_SHARE = 0.02
_RECEIPTS_MATERIALITY_PP = 2.0

# Headlines are capped per company rather than globally so that a multi-company
# comparison does not crowd out every conclusion about the second issuer.
MAX_HEADLINES_PER_COMPANY = 8

_EXPENSE_RATIO_LABELS = (
    ("selling_expense_ratio", "销售费用率"),
    ("administrative_expense_ratio", "管理费用率"),
    ("research_expense_ratio", "研发费用率"),
    ("finance_expense_ratio", "财务费用率"),
)


def _expense_pressure_finding(
    company: str,
    values,
    bridge_drivers,
    revenue: Sequence[FinancialMetric],
    currency: Optional[str],
) -> Optional[ResearchFinding]:
    """A standalone conclusion on expense-ratio movement, when material."""

    moves: list[tuple[str, float, FinancialMetric, FinancialMetric]] = []
    for name, label in _EXPENSE_RATIO_LABELS:
        pair = _pair(values.get(name, []))
        if not pair:
            continue
        change = pair[0].value - pair[1].value
        if abs(change) >= _EXPENSE_MATERIALITY_PP:
            moves.append((label, change, pair[0], pair[1]))
    if not moves:
        return None
    ranked = sorted(moves, key=lambda item: abs(item[1]), reverse=True)
    total_change = sum(change for _, change, _, _ in ranked)
    used = [item for _, _, current, previous in ranked for item in (current, previous)]
    used.extend(revenue[:2])
    return _finding(
        title=(
            f"{company}：期间费用率合计"
            f"{'上升' if total_change > 0 else '下降'} {abs(total_change):.2f} 个百分点"
        ),
        summary=(
            "费用率变化按幅度排序为："
            + "；".join(
                f"{label} {change:+.2f} 个百分点（{previous.value:.2f}% → "
                f"{current.value:.2f}%）"
                for label, change, current, previous in ranked
            )
            + "。费用率以营业收入为分母，反映投入强度而非绝对金额变化。"
        ),
        topic_key="expense_pressure",
        metrics=used,
        company=company,
        period=ranked[0][2].period,
        tone=FindingTone.WATCH if total_change > 0 else FindingTone.POSITIVE,
        calculation="费用率=对应期间费用/营业收入*100",
        reasoning_steps=[
            "把费用压力从利润变动桥的金额口径转换为收入占比口径，"
            "以区分规模效应与投入强度变化。"
        ],
        materiality=abs(total_change),
    )


def investigate_earnings(
    metrics: Iterable[FinancialMetric],
    anomalies: Iterable[FinancialAnomaly] = (),
    hypotheses: Iterable[ResearchHypothesis] = (),
) -> AnalysisSection:
    del anomalies
    findings: list[ResearchFinding] = []
    missing: list[str] = []
    for company, values in _grouped(metrics).items():
        currency = _currency_of(values)
        revenue = values.get("revenue", [])
        profit = values.get("net_profit", [])
        adjusted = values.get("non_recurring_net_profit", [])
        if len(revenue) < 2 or len(profit) < 2:
            missing.append(f"{company}：至少两期收入和归母净利润")
            continue

        current_profit, previous_profit = profit[:2]
        revenue_growth = _growth(revenue[0].value, revenue[1].value)
        profit_growth = _growth(current_profit.value, previous_profit.value)
        reasoning: list[str] = []
        summary_parts: list[str] = []
        used: list[FinancialMetric] = [*revenue[:3], *profit[:3]]
        if len(revenue) >= 3 and len(profit) >= 3:
            summary_parts.append(
                f"三年收入轨迹为 {_series_text(revenue[:3])}；归母净利润为 "
                f"{_series_text(profit[:3])}。"
            )
            reasoning.append("先使用三年轨迹判断当期变化是单年波动还是延续趋势。")
        elif revenue_growth is not None and profit_growth is not None:
            summary_parts.append(
                f"收入同比 {revenue_growth:+.2f}%，归母净利润同比 "
                f"{profit_growth:+.2f}%。"
            )

        non_recurring_questions: list[str] = []
        adjusted_growth: Optional[float] = None
        components: list[FinancialMetric] = []
        if len(adjusted) >= 2:
            adjusted_growth = _growth(adjusted[0].value, adjusted[1].value)
            effect = current_profit.value - adjusted[0].value
            effect_share = (
                effect / abs(current_profit.value) * 100 if current_profit.value else 0
            )
            summary_parts.append(
                f"本期扣非净利润 {_money(adjusted[0].value, currency)}，同比 "
                f"{adjusted_growth:+.2f}%；归母与扣非差额 {_money(effect, currency)}，"
                f"占归母净利润 {effect_share:.2f}%。"
            )
            reasoning.append(
                "比较归母与扣非利润，判断报表利润是否受到非经常性项目支撑。"
            )
            used.extend(adjusted[:3])
            disclosed_effect = values.get("non_recurring_net_effect_reported", [])
            components = [
                item
                for item in values.get("non_recurring_item", [])
                if item.period == current_profit.period
            ]
            used.extend(disclosed_effect[:1])
            used.extend(components)
            if components:
                ranked = sorted(
                    components, key=lambda item: abs(item.value), reverse=True
                )
                component_text = "；".join(
                    f"{item.dimensions.get('item', item.row_label or '项目')} "
                    f"{_money(item.value, currency)}"
                    for item in ranked[:3]
                )
                summary_parts.append(f"披露构成中金额最大的项目为：{component_text}。")
                reasoning.append(
                    "继续读取非经常性损益明细，定位差额来源而非停留在差值。"
                )
            else:
                non_recurring_questions.append(
                    "非经常性损益差额具体由哪些项目构成、是否可持续？"
                )
        else:
            missing.append(f"{company}：两期扣非归母净利润")
            non_recurring_questions.append(
                "缺少扣非利润，无法判断核心盈利与表面利润的差异。"
            )

        bridge = _change_bridge(values, "net_profit", PROFIT_BRIDGE_COMPONENTS)
        counter_evidence: list[str] = []
        bridge_questions: list[str] = []
        bridge_drivers = []
        if bridge:
            _, target_change, drivers, residual, coverage, bridge_metrics = bridge
            bridge_drivers = drivers
            used.extend(bridge_metrics)
            negative = sorted(
                (item for item in drivers if item[1] < 0), key=lambda item: item[1]
            )
            positive = sorted(
                (item for item in drivers if item[1] > 0),
                key=lambda item: item[1],
                reverse=True,
            )
            if negative:
                summary_parts.append(
                    "利润变动桥识别的主要负向项为："
                    + "；".join(
                        f"{name} {_money(effect, currency)}"
                        for name, effect, _ in negative[:3]
                    )
                    + "。"
                )
            if positive:
                counter_evidence.append(
                    "正向对冲项："
                    + "；".join(
                        f"{name} +{_money(effect, currency)}"
                        for name, effect, _ in positive[:3]
                    )
                )
            reasoning.append(
                f"利润表变动桥解释归母净利润变化 {_money(target_change, currency)} 的 "
                f"{coverage:.1f}%，未解释差额 {_money(residual, currency)}。"
            )
            if coverage < 90:
                bridge_questions.append(
                    "利润变动桥仍有未解释差额，需补充缺失科目或核对合并口径。"
                )
        else:
            bridge_questions.append("缺少连续两期完整利润表，无法定位利润率变化来源。")

        title = "盈利变化与驱动"
        tone = FindingTone.NEUTRAL
        if (
            adjusted_growth is not None
            and profit_growth is not None
            and adjusted_growth < profit_growth - 5
        ):
            title = "核心经营盈利弱于表面利润表现"
            tone = FindingTone.WARNING
        elif profit_growth is not None and profit_growth < 0:
            title = "利润下降快于收入，驱动需要拆解"
            tone = FindingTone.WATCH

        unresolved = [*non_recurring_questions, *bridge_questions]
        status = (
            InvestigationStatus.SUPPORTED
            if not unresolved
            else InvestigationStatus.PARTIAL
        )
        findings.append(
            _finding(
                title=f"{company}：{title}",
                summary=" ".join(summary_parts),
                topic_key="earnings_quality",
                metrics=used,
                company=company,
                period=current_profit.period,
                tone=tone,
                status=status,
                calculation=(
                    "同比=(本期-上期)/|上期|；非经常性净影响=归母净利润-"
                    "扣非归母净利润；利润变动桥按收入/收益增加为正、"
                    "成本费用增加为负"
                ),
                reasoning_steps=reasoning,
                counter_evidence=counter_evidence,
                unanswered_questions=unresolved,
                materiality=abs(profit_growth or 0.0),
            )
        )

        # Separate mechanisms get separate conclusions. Folding them into the
        # single summary above is what made conclusion count independent of how
        # much evidence was actually extracted.
        gross_margins = values.get("gross_margin", [])
        if len(gross_margins) >= 2:
            margin_pair = _pair(gross_margins)
            if margin_pair:
                margin_change = margin_pair[0].value - margin_pair[1].value
                if abs(margin_change) >= _MARGIN_MATERIALITY_PP:
                    findings.append(
                        _finding(
                            title=(
                                f"{company}：毛利率"
                                f"{'下降' if margin_change < 0 else '上升'}"
                                f" {abs(margin_change):.2f} 个百分点"
                            ),
                            summary=(
                                f"毛利率由 {margin_pair[1].value:.2f}% 变为 "
                                f"{margin_pair[0].value:.2f}%，变化 "
                                f"{margin_change:+.2f} 个百分点。该变化直接作用于"
                                "营业利润，需与成本结构和产品结构一并解读。"
                            ),
                            topic_key="gross_margin",
                            metrics=[*margin_pair, *revenue[:2]],
                            company=company,
                            period=margin_pair[0].period,
                            tone=(
                                FindingTone.WATCH
                                if margin_change < 0
                                else FindingTone.POSITIVE
                            ),
                            calculation="毛利率=(营业收入-营业成本)/营业收入*100",
                            reasoning_steps=[
                                "毛利率变化独立于费用与非经常性项目，单独列示。"
                            ],
                            materiality=abs(margin_change),
                        )
                    )

        if components:
            ranked_components = sorted(
                components, key=lambda item: abs(item.value), reverse=True
            )
            share = (
                abs(
                    (current_profit.value - adjusted[0].value)
                    / current_profit.value
                    * 100
                )
                if adjusted and current_profit.value
                else 0.0
            )
            findings.append(
                _finding(
                    title=f"{company}：非经常性损益的具体构成",
                    summary=(
                        "披露的非经常性损益项目按金额排序为："
                        + "；".join(
                            f"{item.dimensions.get('item', item.row_label or '项目')} "
                            f"{_money(item.value, currency)}"
                            for item in ranked_components[:5]
                        )
                        + f"。合计影响相当于归母净利润的 {share:.2f}%。"
                    ),
                    topic_key="non_recurring_support",
                    metrics=[*ranked_components, *profit[:1], *adjusted[:1]],
                    company=company,
                    period=current_profit.period,
                    tone=(FindingTone.WATCH if share >= 20 else FindingTone.NEUTRAL),
                    calculation="逐项引用披露的非经常性损益明细，不重新归类",
                    reasoning_steps=[
                        "把归母与扣非的差额拆到披露的单个项目上，"
                        "以判断该差额是否会重复出现。"
                    ],
                    materiality=share,
                )
            )

        expense_findings = _expense_pressure_finding(
            company, values, bridge_drivers, revenue, currency
        )
        if expense_findings:
            findings.append(expense_findings)

        gross_margins = values.get("gross_margin", [])
        if len(gross_margins) >= 2:
            gross_change = gross_margins[0].value - gross_margins[1].value
            _set_hypothesis(
                hypotheses,
                company=company,
                question_marker="毛利率",
                status=(
                    InvestigationStatus.SUPPORTED
                    if gross_change < 0
                    else InvestigationStatus.REJECTED
                ),
                resolution=f"毛利率同比变化 {gross_change:+.2f} 个百分点。",
                metrics=gross_margins[:2],
            )
        expense_labels = {"销售费用", "管理费用", "研发费用", "财务费用"}
        expense_drivers = [item for item in bridge_drivers if item[0] in expense_labels]
        _set_hypothesis(
            hypotheses,
            company=company,
            question_marker="期间费用",
            status=(
                InvestigationStatus.SUPPORTED
                if any(item[1] < 0 for item in expense_drivers)
                else InvestigationStatus.REJECTED
                if expense_drivers
                else InvestigationStatus.UNRESOLVED
            ),
            resolution=(
                "；".join(
                    f"{name}对利润变化贡献 {_money(effect, currency)}"
                    for name, effect, _ in expense_drivers
                )
                or "缺少连续两期费用科目。"
            ),
            metrics=[item for _, _, pair in expense_drivers for item in pair],
        )
        _set_hypothesis(
            hypotheses,
            company=company,
            question_marker="非经常性项目",
            status=(
                InvestigationStatus.SUPPORTED
                if len(adjusted) >= 2 and components
                else InvestigationStatus.PARTIAL
                if len(adjusted) >= 2
                else InvestigationStatus.UNRESOLVED
            ),
            resolution=(
                "归母与扣非差额已与非经常性损益明细核对。"
                if components
                else "已确认归母与扣非差额，但尚未取得构成明细。"
            ),
            metrics=[*profit[:2], *adjusted[:2], *components],
        )

    return AnalysisSection(
        key="earnings_investigation",
        title="盈利与核心盈利调查",
        objective="解释利润为何变化，并区分持续经营盈利与非经常性支撑。",
        methodology="三年趋势、归母/扣非差异、非经常性明细和利润表变动桥联合验证。",
        status=_section_status(findings),
        findings=findings,
        missing_inputs=missing,
    )


CASH_BRIDGE_COMPONENTS = (
    ("cash_received_from_sales", "销售商品及劳务收到现金", 1),
    ("tax_refunds_received", "税费返还", 1),
    ("other_operating_cash_received", "其他经营现金流入", 1),
    ("cash_paid_for_goods", "采购支付现金", -1),
    ("cash_paid_to_employees", "职工支付现金", -1),
    ("taxes_paid", "税费支付现金", -1),
    ("other_operating_cash_paid", "其他经营现金流出", -1),
)

WORKING_CAPITAL_COMPONENTS = (
    ("accounts_receivable", "应收账款", -1),
    ("notes_and_accounts_receivable", "应收票据及应收账款", -1),
    ("receivables_financing", "应收款项融资", -1),
    ("contract_assets", "合同资产", -1),
    ("inventory", "存货", -1),
    ("prepayments", "预付款项", -1),
    ("accounts_payable", "应付账款", 1),
    ("notes_and_accounts_payable", "应付票据及应付账款", 1),
    ("contract_liabilities", "合同负债", 1),
    ("advances_from_customers", "预收款项", 1),
)


def _receipts_quality_finding(
    company: str,
    values,
    currency: Optional[str],
) -> Optional[ResearchFinding]:
    """A standalone conclusion on how much of revenue arrived as cash.

    Sales receipts include VAT while revenue does not, so the ratio is not
    expected to sit at 1.0 and no threshold is applied to it. What carries
    information is the movement between two comparable periods.
    """
    receipts = values.get("cash_received_from_sales", [])
    revenue = values.get("revenue", [])
    receipt_pair = _pair(receipts)
    revenue_pair = _pair(revenue)
    if not receipt_pair or not revenue_pair:
        return None
    if not revenue_pair[0].value or not revenue_pair[1].value:
        return None
    current_ratio = receipt_pair[0].value / revenue_pair[0].value * 100
    previous_ratio = receipt_pair[1].value / revenue_pair[1].value * 100
    change = current_ratio - previous_ratio
    if abs(change) < _RECEIPTS_MATERIALITY_PP:
        return None
    return _finding(
        title=(
            f"{company}：销售回款比率{'下降' if change < 0 else '上升'} "
            f"{abs(change):.2f} 个百分点"
        ),
        summary=(
            f"销售商品、提供劳务收到的现金相当于营业收入的比率由 "
            f"{previous_ratio:.2f}% 变为 {current_ratio:.2f}%，变化 "
            f"{change:+.2f} 个百分点。本期回款 "
            f"{_money(receipt_pair[0].value, currency)}，对应营业收入 "
            f"{_money(revenue_pair[0].value, currency)}。该比率含增值税，"
            "不应按 100% 解读，只比较同口径的期间变化。"
        ),
        topic_key="receipts_quality",
        metrics=[*receipt_pair, *revenue_pair],
        company=company,
        period=receipt_pair[0].period,
        tone=FindingTone.WATCH if change < 0 else FindingTone.POSITIVE,
        calculation="销售回款比率=销售商品、提供劳务收到的现金/营业收入*100",
        reasoning_steps=[
            "用收入的现金到账比例检查收入确认与现金回收之间是否出现背离。"
        ],
        materiality=abs(change),
    )


def investigate_cash_conversion(
    metrics: Iterable[FinancialMetric],
    anomalies: Iterable[FinancialAnomaly] = (),
    hypotheses: Iterable[ResearchHypothesis] = (),
) -> AnalysisSection:
    del anomalies
    findings: list[ResearchFinding] = []
    missing: list[str] = []
    for company, values in _grouped(metrics).items():
        currency = _currency_of(values)
        cash_flows = values.get("operating_cash_flow", [])
        profits = values.get("net_profit", [])
        ratios = values.get("cash_profit_ratio", [])
        if not cash_flows or not profits or not ratios:
            missing.append(f"{company}：经营现金流、归母净利润或现金利润比")
            continue
        current = cash_flows[0]
        used: list[FinancialMetric] = [
            *cash_flows[:3],
            *profits[:3],
            *ratios[:3],
        ]
        summary_parts: list[str] = []
        reasoning: list[str] = []
        unanswered: list[str] = []
        counter: list[str] = []
        if len(cash_flows) >= 3:
            summary_parts.append(
                f"三年经营现金流轨迹为 {_series_text(cash_flows[:3])}。"
            )
        summary_parts.append(
            f"本期经营现金流 {_money(current.value, currency)}，相当于归母净利润的 "
            f"{ratios[0].value:.2f} 倍；该比值只作为事实，不套用固定风险线。"
        )
        reasoning.append("先比较现金流、利润和历史轨迹，不使用无同行依据的绝对阈值。")

        total_bridge = _change_bridge(
            values,
            "operating_cash_flow",
            (
                ("operating_cash_inflow", "经营现金流入", 1),
                ("operating_cash_outflow", "经营现金流出", -1),
            ),
        )
        detail_bridge = _change_bridge(
            values, "operating_cash_flow", CASH_BRIDGE_COMPONENTS
        )
        bridge_supported = False
        if total_bridge:
            _, target_change, _, residual, coverage, bridge_metrics = total_bridge
            used.extend(bridge_metrics)
            bridge_supported = coverage >= 99
            reasoning.append(
                f"收付总额桥解释经营现金流变化 {_money(target_change, currency)} 的 "
                f"{coverage:.1f}%，残差 {_money(residual, currency)}。"
            )
        if detail_bridge:
            _, _, drivers, residual, coverage, bridge_metrics = detail_bridge
            used.extend(bridge_metrics)
            negative = sorted(
                (item for item in drivers if item[1] < 0), key=lambda item: item[1]
            )
            positive = sorted(
                (item for item in drivers if item[1] > 0),
                key=lambda item: item[1],
                reverse=True,
            )
            if negative:
                summary_parts.append(
                    "经营收付明细的主要负向变化为："
                    + "；".join(
                        f"{name} {_money(effect, currency)}"
                        for name, effect, _ in negative[:3]
                    )
                    + "。"
                )
            if positive:
                counter.append(
                    "现金流正向对冲："
                    + "；".join(
                        f"{name} +{_money(effect, currency)}"
                        for name, effect, _ in positive[:3]
                    )
                )
            reasoning.append(
                f"经营收付明细桥覆盖 {coverage:.1f}%，"
                f"残差 {_money(residual, currency)}。"
            )
        else:
            unanswered.append("缺少连续两期经营现金收付明细，无法解释现金流变化来源。")

        working_capital_signals = []
        for name, label, sign in WORKING_CAPITAL_COMPONENTS:
            pair = _pair(values.get(name, []))
            if not pair:
                continue
            delta = pair[0].value - pair[1].value
            cash_direction = sign * delta
            working_capital_signals.append((label, delta, cash_direction, pair))
            used.extend(pair)
        if working_capital_signals:
            ranked = sorted(
                working_capital_signals, key=lambda item: abs(item[1]), reverse=True
            )
            summary_parts.append(
                "期末营运资本余额变化中金额较大的项目为："
                + "；".join(
                    f"{label} {'+' if delta >= 0 else '-'}"
                    f"{_money(abs(delta), currency)}"
                    for label, delta, _, _ in ranked[:4]
                )
                + "。这些余额变化只用于形成原因线索，不直接等同于现金流影响。"
            )
            unanswered.append(
                "需结合现金流量表补充资料核验营运资本变动的实际现金影响。"
            )
        else:
            unanswered.append(
                "缺少两期应收、合同资产、存货和应付余额，无法检查营运资本线索。"
            )

        cash_growth = (
            _growth(cash_flows[0].value, cash_flows[1].value)
            if len(cash_flows) >= 2
            else None
        )
        profit_growth = (
            _growth(profits[0].value, profits[1].value) if len(profits) >= 2 else None
        )
        weaker = (
            cash_growth is not None
            and profit_growth is not None
            and cash_growth < profit_growth
        )
        status = (
            InvestigationStatus.SUPPORTED
            if bridge_supported and not unanswered
            else InvestigationStatus.PARTIAL
        )
        findings.append(
            _finding(
                title=(
                    f"{company}：现金转化走弱，收付驱动已定位"
                    if weaker and bridge_supported
                    else f"{company}：现金转化走弱，驱动尚待拆解"
                    if weaker
                    else f"{company}：现金转化及收付驱动"
                ),
                summary=" ".join(summary_parts),
                topic_key="cash_conversion",
                metrics=used,
                company=company,
                period=current.period,
                tone=(
                    FindingTone.WATCH
                    if weaker or current.value < 0
                    else FindingTone.NEUTRAL
                ),
                status=status,
                calculation=(
                    "现金利润比=经营现金流/归母净利润；经营现金流变化=流入变化-流出变化"
                ),
                reasoning_steps=reasoning,
                counter_evidence=counter,
                unanswered_questions=unanswered,
                materiality=abs((cash_growth or 0.0) - (profit_growth or 0.0)),
            )
        )

        if working_capital_signals:
            ranked_wc = sorted(
                working_capital_signals, key=lambda item: abs(item[1]), reverse=True
            )
            revenue_anchor = next(iter(values.get("revenue", [])), None)
            scale = abs(revenue_anchor.value) if revenue_anchor else 0.0
            leading = ranked_wc[0]
            share = (abs(leading[1]) / scale * 100) if scale else 0.0
            if not scale or abs(leading[1]) >= scale * _BALANCE_MATERIALITY_SHARE:
                absorbing = [item for item in ranked_wc if item[2] < 0]
                releasing = [item for item in ranked_wc if item[2] > 0]
                findings.append(
                    _finding(
                        title=f"{company}：营运资本占用的科目分布",
                        summary=(
                            "按余额变化对现金的方向划分——占用现金的科目为："
                            + (
                                "；".join(
                                    f"{label} {_money(abs(delta), currency)}"
                                    for label, delta, _, _ in absorbing[:4]
                                )
                                or "无"
                            )
                            + "；释放现金的科目为："
                            + (
                                "；".join(
                                    f"{label} {_money(abs(delta), currency)}"
                                    for label, delta, _, _ in releasing[:4]
                                )
                                or "无"
                            )
                            + "。余额变化是现金影响的线索，"
                            "不等于现金流量表的实际发生额。"
                        ),
                        topic_key="working_capital",
                        metrics=[item for _, _, _, pair in ranked_wc for item in pair],
                        company=company,
                        period=current.period,
                        tone=(FindingTone.WATCH if absorbing else FindingTone.NEUTRAL),
                        calculation=(
                            "资产类科目余额增加视为占用现金，负债类科目余额增加视为"
                            "释放现金；方向按科目性质取符号"
                        ),
                        reasoning_steps=[
                            "把营运资本从总额线索拆到具体科目，并标注现金方向。"
                        ],
                        unanswered_questions=[
                            "上述余额变化需与现金流量表补充资料核对，"
                            "才能确认实际现金影响。"
                        ],
                        materiality=share,
                    )
                )

        receipts = _receipts_quality_finding(company, values, currency)
        if receipts:
            findings.append(receipts)

        _set_hypothesis(
            hypotheses,
            company=company,
            question_marker="收付项目",
            status=(
                InvestigationStatus.SUPPORTED
                if bridge_supported
                else InvestigationStatus.PARTIAL
                if detail_bridge
                else InvestigationStatus.UNRESOLVED
            ),
            resolution=(
                "经营现金流入与流出变动已完成勾稽。"
                if bridge_supported
                else "经营收付明细未能完整解释现金流变化。"
            ),
            metrics=used,
        )
        _set_hypothesis(
            hypotheses,
            company=company,
            question_marker="营运资本",
            status=(
                InvestigationStatus.PARTIAL
                if working_capital_signals
                else InvestigationStatus.UNRESOLVED
            ),
            resolution=(
                "已识别期末余额变化，但尚未取得现金流量表补充资料完成现金桥。"
                if working_capital_signals
                else "缺少连续两期营运资本科目。"
            ),
            metrics=[
                item for _, _, _, pair in working_capital_signals for item in pair
            ],
        )
    return AnalysisSection(
        key="cash_investigation",
        title="经营现金流调查",
        objective="解释经营现金流为何变化，并区分已验证收付驱动与营运资本线索。",
        methodology="三年轨迹、利润匹配、经营收付桥和资产负债表余额变化交叉验证。",
        status=_section_status(findings),
        findings=findings,
        missing_inputs=missing,
    )


ASSET_COMPONENTS = (
    ("cash", "货币资金"),
    ("accounts_receivable", "应收账款"),
    ("notes_and_accounts_receivable", "应收票据及应收账款"),
    ("contract_assets", "合同资产"),
    ("inventory", "存货"),
    ("fixed_assets", "固定资产"),
    ("construction_in_progress", "在建工程"),
    ("other_non_current_assets", "其他非流动资产"),
)


def _asset_occupation_finding(
    company: str,
    asset_changes,
    assets: Sequence[FinancialMetric],
    currency: Optional[str],
) -> Optional[ResearchFinding]:
    """A standalone conclusion on where capital became tied up.

    Only balance movements that are material against total assets qualify, so a
    small reclassification between line items never becomes its own headline.
    """
    if not assets:
        return None
    base = abs(assets[0].value)
    if not base:
        return None
    material = [
        (label, delta, pair)
        for label, delta, pair in asset_changes
        if abs(delta) / base >= _BALANCE_MATERIALITY_SHARE
    ]
    if not material:
        return None
    ranked = sorted(material, key=lambda item: abs(item[1]), reverse=True)
    used = [item for _, _, pair in ranked for item in pair]
    used.extend(assets[:2])
    increases = [item for item in ranked if item[1] > 0]
    return _finding(
        title=f"{company}：资产占用集中在 {ranked[0][0]}",
        summary=(
            "占总资产 "
            f"{_BALANCE_MATERIALITY_SHARE * 100:.0f}% 以上的资产科目变化为："
            + "；".join(
                f"{label} {'+' if delta >= 0 else '-'}{_money(abs(delta), currency)}"
                f"（占期末总资产 {abs(delta) / base * 100:.2f}%）"
                for label, delta, _ in ranked[:4]
            )
            + "。余额变化说明资本占用去向，本身不等同于现金流出。"
        ),
        topic_key="asset_occupation",
        metrics=used,
        company=company,
        period=assets[0].period,
        tone=FindingTone.WATCH if increases else FindingTone.NEUTRAL,
        calculation="科目变化=本期期末余额-上期期末余额；占比以本期期末总资产为分母",
        reasoning_steps=[
            "先按对总资产的相对幅度筛选科目，再解释资本占用去向，"
            "避免把金额大但占比小的科目当作结论。"
        ],
        materiality=abs(ranked[0][1]) / base * 100,
    )


def _leverage_finding(
    company: str,
    values,
    currency: Optional[str],
) -> Optional[ResearchFinding]:
    """A standalone conclusion on financial structure, when it moved materially."""

    debt_ratio = _pair(values.get("debt_asset_ratio", []))
    if not debt_ratio:
        return None
    change = debt_ratio[0].value - debt_ratio[1].value
    if abs(change) < _MARGIN_MATERIALITY_PP:
        return None
    used: list[FinancialMetric] = [*debt_ratio]
    context: list[str] = []
    for name, label in (
        ("current_ratio", "流动比率"),
        ("quick_ratio", "速动比率"),
        ("interest_coverage", "利息保障倍数"),
    ):
        pair = _pair(values.get(name, []))
        if not pair:
            continue
        used.extend(pair)
        context.append(f"{label}由 {pair[1].value:.2f} 变为 {pair[0].value:.2f}")
    net_debt = values.get("net_debt", [])
    if net_debt:
        used.append(net_debt[0])
        context.append(f"期末净债务 {_money(net_debt[0].value, currency)}")
    return _finding(
        title=(
            f"{company}：资产负债率{'上升' if change > 0 else '下降'} "
            f"{abs(change):.2f} 个百分点"
        ),
        summary=(
            f"资产负债率由 {debt_ratio[1].value:.2f}% 变为 "
            f"{debt_ratio[0].value:.2f}%。"
            + ("；".join(context) + "。" if context else "")
            + "财务结构指标仅描述当期口径，不据此给出偿债能力评级。"
        ),
        topic_key="financial_structure",
        metrics=used,
        company=company,
        period=debt_ratio[0].period,
        tone=FindingTone.WATCH if change > 0 else FindingTone.NEUTRAL,
        calculation="资产负债率=负债合计/资产总计*100；净债务=短期借款+长期借款-货币资金",
        reasoning_steps=[
            "将杠杆变化与流动性和利息覆盖指标并列，避免用单一比率判断偿债风险。"
        ],
        materiality=abs(change),
    )


def investigate_capital_returns(
    metrics: Iterable[FinancialMetric],
    anomalies: Iterable[FinancialAnomaly] = (),
    hypotheses: Iterable[ResearchHypothesis] = (),
) -> AnalysisSection:
    del anomalies
    findings: list[ResearchFinding] = []
    missing: list[str] = []
    for company, values in _grouped(metrics).items():
        currency = _currency_of(values)
        roe = values.get("weighted_roe", [])
        assets = values.get("total_assets", [])
        revenue = values.get("revenue", [])
        turnover = values.get("asset_turnover", [])
        margins = values.get("net_margin", [])
        if not roe and not turnover:
            missing.append(f"{company}：ROE 或平均资产周转率")
            continue
        used: list[FinancialMetric] = [
            *roe[:3],
            *assets[:3],
            *revenue[:3],
            *turnover[:2],
            *margins[:2],
        ]
        summary_parts: list[str] = []
        reasoning: list[str] = []
        unanswered: list[str] = []
        if len(roe) >= 3:
            summary_parts.append(
                f"ROE 三年轨迹为 {_series_text(roe[:3], money=False)}。"
            )
        if len(turnover) >= 2:
            summary_parts.append(
                f"平均总资产周转率由 {turnover[1].value:.2f} 次变为 "
                f"{turnover[0].value:.2f} 次。"
            )
            reasoning.append(
                "使用平均资产口径判断资产效率，避免以期末资产替代平均资产。"
            )
        if len(margins) >= 2:
            summary_parts.append(
                f"同期净利率变化 {margins[0].value - margins[1].value:+.2f} 个百分点。"
            )
            reasoning.append("将 ROE 下行同时与利润率和资产周转变化对照。")

        asset_changes = []
        for name, label in ASSET_COMPONENTS:
            pair = _pair(values.get(name, []))
            if not pair:
                continue
            delta = pair[0].value - pair[1].value
            asset_changes.append((label, delta, pair))
            used.extend(pair)
        if asset_changes:
            ranked = sorted(asset_changes, key=lambda item: abs(item[1]), reverse=True)
            summary_parts.append(
                "资产端变化较大的项目为："
                + "；".join(
                    f"{label} {'+' if delta >= 0 else '-'}"
                    f"{_money(abs(delta), currency)}"
                    for label, delta, _ in ranked[:4]
                )
                + "。"
            )
            reasoning.append(
                "再定位资本占用发生在哪些资产科目，而不是只报告周转率结果。"
            )
        else:
            unanswered.append("缺少两期资产明细，无法定位资本占用科目。")

        segment_shares = [
            item
            for item in values.get("segment_revenue_share", [])
            if item.period == (revenue[0].period if revenue else item.period)
        ]
        if segment_shares:
            leaders = sorted(segment_shares, key=lambda item: item.value, reverse=True)
            leader = leaders[0]
            dimension, label = next(iter(leader.dimensions.items()))
            summary_parts.append(
                f"收入结构中“{label}”占比最高，为 {leader.value:.2f}%"
                f"（{dimension}口径）。"
            )
            used.extend(leaders[:3])

        declining_roe = len(roe) >= 2 and roe[0].value < roe[1].value
        status = (
            InvestigationStatus.SUPPORTED
            if not unanswered
            else InvestigationStatus.PARTIAL
        )
        findings.append(
            _finding(
                title=(
                    f"{company}：资本回报下行的盈利与效率线索"
                    if declining_roe
                    else f"{company}：资本回报与资产占用"
                ),
                summary=" ".join(summary_parts),
                topic_key="capital_returns",
                metrics=used,
                company=company,
                period=(roe[0].period if roe else turnover[0].period),
                tone=FindingTone.WATCH if declining_roe else FindingTone.NEUTRAL,
                status=status,
                calculation="ROE 使用披露值；总资产周转率=营业收入/平均总资产",
                reasoning_steps=reasoning,
                unanswered_questions=unanswered,
                materiality=(
                    abs(roe[0].value - roe[1].value) if len(roe) >= 2 else 0.0
                ),
            )
        )
        # Asset occupation and financial structure are separate questions from
        # the return trajectory, so they carry their own evidence-linked
        # conclusions instead of being compressed into the section headline.
        occupation = _asset_occupation_finding(company, asset_changes, assets, currency)
        if occupation:
            findings.append(occupation)
        leverage = _leverage_finding(company, values, currency)
        if leverage:
            findings.append(leverage)
        margin_declined = len(margins) >= 2 and margins[0].value < margins[1].value
        turnover_declined = len(turnover) >= 2 and turnover[0].value < turnover[1].value
        driver_inputs = [*margins[:2], *turnover[:2], *roe[:3]]
        _set_hypothesis(
            hypotheses,
            company=company,
            question_marker="ROE 下行",
            status=(
                InvestigationStatus.SUPPORTED
                if margin_declined or turnover_declined
                else InvestigationStatus.REJECTED
                if len(margins) >= 2 and len(turnover) >= 2
                else InvestigationStatus.PARTIAL
            ),
            resolution=(
                f"净利率下降={margin_declined}；平均资产周转率下降="
                f"{turnover_declined}。"
            ),
            metrics=driver_inputs,
        )
    return AnalysisSection(
        key="capital_investigation",
        title="资本回报与资产占用调查",
        objective="判断资本回报变化来自利润率、周转效率还是资产占用。",
        methodology="三年 ROE、平均资产周转率、净利率和资产科目变化联合分析。",
        status=_section_status(findings),
        findings=findings,
        missing_inputs=missing,
    )


_NOTE_TOPICS = (
    (
        "receivable_aging_balance",
        "receivables_aging",
        "应收账款账龄",
        "accounts_receivable",
        "应收账款",
    ),
    (
        "goodwill_detail",
        "goodwill",
        "商誉明细",
        "goodwill",
        "商誉",
    ),
    (
        "related_party_transaction",
        "related_party",
        "关联方购销及劳务交易",
        "revenue",
        "营业收入",
    ),
)


def _note_items(
    values, metric_name: str, dimension: str, period: Optional[str]
) -> list[FinancialMetric]:
    """Disclosed note rows for one period, excluding disclosed subtotals."""

    def is_component(item: FinancialMetric) -> bool:
        if dimension not in item.dimensions:
            return False
        if period is not None and item.period != period:
            return False
        label = item.row_label or ""
        # A disclosed subtotal is the sum of the rows around it; counting it as
        # a component would double the total and halve every share.
        return not label.endswith("合计") and label not in {"小计", "总计"}

    items = [item for item in values.get(metric_name, []) if is_component(item)]
    if dimension == "receivables_aging":
        # Some filings disclose both a rolled-up bucket ("3年以上") and its
        # detailed children ("3至4年" / "4至5年" / "5年以上"). Keeping both
        # double-counts the same receivable balance and distorts concentration.
        labels = {item.row_label or "" for item in items}
        overlapping_parents: set[str] = set()
        for label in labels:
            parent = re.fullmatch(r"(\d+)年以上", label)
            if not parent:
                continue
            threshold = int(parent.group(1))
            for other in labels - {label}:
                child = re.match(r"(\d+)(?:至|-)", other)
                open_bucket = re.fullmatch(r"(\d+)年以上", other)
                bucket_match = child or open_bucket
                lower_bound = int(bucket_match.group(1)) if bucket_match else -1
                if lower_bound >= threshold:
                    overlapping_parents.add(label)
                    break
        items = [item for item in items if item.row_label not in overlapping_parents]
    return sorted(items, key=lambda item: abs(item.value), reverse=True)


def investigate_notes(
    metrics: Iterable[FinancialMetric],
    anomalies: Iterable[FinancialAnomaly] = (),
    hypotheses: Iterable[ResearchHypothesis] = (),
) -> AnalysisSection:
    """Read disclosed notes as evidence about concentration and exposure.

    The three statements say what the totals are; the notes say what they are
    made of. Each topic produces a conclusion only when the note table was
    actually indexed, so an unavailable note becomes a recorded gap rather than
    a silently missing chapter.
    """
    del anomalies, hypotheses
    findings: list[ResearchFinding] = []
    missing: list[str] = []
    for company, values in _grouped(metrics).items():
        currency = _currency_of(values)
        for (
            metric_name,
            dimension,
            topic_label,
            anchor_name,
            anchor_label,
        ) in _NOTE_TOPICS:
            anchor = values.get(anchor_name, [])
            note_periods = {
                item.period for item in values.get(metric_name, []) if item.period
            }
            period = (
                anchor[0].period
                if anchor
                else max(note_periods, key=period_sort_key)
                if note_periods
                else None
            )
            items = _note_items(values, metric_name, dimension, period)
            if not items:
                missing.append(f"{company}：{topic_label}附注明细")
                continue
            total = sum(abs(item.value) for item in items)
            leader = items[0]
            share = abs(leader.value) / total * 100 if total else 0.0
            used = list(items[:6])
            context = ""
            reasoning = [
                f"读取{topic_label}附注，按金额排序识别集中度，"
                "不将附注明细与报表主表数字相互替代。"
            ]
            if anchor:
                used.append(anchor[0])
                base = abs(anchor[0].value)
                if base:
                    ratio_to_anchor = total / base * 100
                    if dimension == "receivables_aging":
                        context = (
                            f"账龄披露账面余额相当于同期主表{anchor_label}净额 "
                            f"{ratio_to_anchor:.2f}%；前者未扣减坏账准备，"
                            "两者不作为相等性勾稽。"
                        )
                    else:
                        context = (
                            f"明细合计相当于同期{anchor_label} {ratio_to_anchor:.2f}%。"
                        )
                    reasoning.append(
                        f"再以同期{anchor_label}为分母衡量该披露的相对规模。"
                    )
            if len(items) == 1:
                findings.append(
                    _finding(
                        title=f"{company}：{topic_label}仅披露「{leader.row_label}」一项",
                        summary=(
                            f"{topic_label}仅抽取到一项明细「{leader.row_label}」，"
                            f"金额为 {_money(leader.value, currency)}。"
                            + context
                            + "单项披露不计算集中度，避免把必然的 100% 作为风险信号。"
                        ),
                        topic_key=f"note_{dimension}",
                        metrics=used,
                        company=company,
                        period=leader.period,
                        calculation=(
                            f"单项金额/{anchor_label}"
                            if anchor and anchor[0].value != 0
                            else None
                        ),
                        reasoning_steps=reasoning,
                        materiality=0.0,
                    )
                )
                continue
            findings.append(
                _finding(
                    title=f"{company}：{topic_label}集中于「{leader.row_label}」",
                    summary=(
                        f"{topic_label}披露明细合计 {_money(total, currency)}，"
                        f"其中金额最大的「{leader.row_label}」为 "
                        f"{_money(leader.value, currency)}，占该披露 {share:.2f}%。"
                        + context
                        + "明细按披露原文列示，未做归类合并。"
                    ),
                    topic_key=f"note_{dimension}",
                    metrics=used,
                    company=company,
                    period=leader.period,
                    tone=FindingTone.WATCH if share >= 50 else FindingTone.NEUTRAL,
                    calculation=f"占比=单项金额/{topic_label}披露明细合计*100",
                    reasoning_steps=reasoning,
                    materiality=share,
                )
            )
    return AnalysisSection(
        key="notes_investigation",
        title="附注明细调查",
        objective="用应收账龄、商誉和关联方交易附注补充报表主表无法回答的结构问题。",
        methodology="逐附注表读取披露明细，计算集中度并与对应主表科目对照。",
        status=_section_status(findings),
        findings=findings,
        missing_inputs=missing,
    )


def analyze_peers(metrics: Iterable[FinancialMetric]) -> AnalysisSection:
    metric_list = list(metrics)
    companies = sorted({metric.company_name for metric in metric_list})
    if len(companies) < 2:
        return AnalysisSection(
            key="peer_comparison",
            title="同业比较",
            objective="仅在同期间、同口径下比较公司。",
            methodology="无至少两家公司时不生成伪横向判断。",
            status=AnalysisStatus.INSUFFICIENT_DATA,
            missing_inputs=["至少两家公司的同期间财报"],
        )
    common_periods = defaultdict(set)
    for metric in metric_list:
        common_periods[metric.period].add(metric.company_name)
    periods = [period for period, names in common_periods.items() if len(names) >= 2]
    if not periods:
        return AnalysisSection(
            key="peer_comparison",
            title="同业比较",
            objective="仅在同期间、同口径下比较公司。",
            methodology="无共同期间时不强行比较。",
            status=AnalysisStatus.INSUFFICIENT_DATA,
            missing_inputs=["多家公司共同覆盖的会计期间"],
        )
    period = max(periods, key=period_sort_key)
    comparisons = []
    used: list[FinancialMetric] = []
    for name in (
        "revenue",
        "net_margin",
        "weighted_roe",
        "cash_profit_ratio",
        "asset_turnover",
    ):
        items = [
            item for item in metric_list if item.period == period and item.name == name
        ]
        if len(items) < 2:
            continue
        ranked = sorted(items, key=lambda item: item.value, reverse=True)
        comparisons.append(
            f"{ranked[0].display_name}：{ranked[0].company_name}最高"
            f"（{ranked[0].value:,.2f}）"
        )
        used.extend(ranked)
    findings = []
    if comparisons:
        findings.append(
            _finding(
                title=f"{period_display_name(period)}同口径财务对比",
                summary="；".join(comparisons) + "。排名只呈现差异，不生成综合评分。",
                topic_key="peer_comparison",
                metrics=used,
                period=period,
                calculation="共同期间、相同概念和单位下逐指标排序",
                unanswered_questions=["仍需行业业务模式和公司规模差异解释排名原因。"],
                status=InvestigationStatus.PARTIAL,
            )
        )
    return AnalysisSection(
        key="peer_comparison",
        title="同业比较",
        objective="提供历史指标无法回答的横向背景。",
        methodology="限定共同期间与统一口径，逐指标比较且不做综合打分。",
        status=_section_status(findings),
        findings=findings,
        missing_inputs=[] if findings else ["至少两个共同指标"],
    )


def review_disclosures(
    metrics: Iterable[FinancialMetric],
    issues: Iterable[ValidationIssue],
    evidence: Iterable[Evidence] = (),
    documents: Iterable[ParsedDocument] = (),
) -> AnalysisSection:
    metric_list = list(metrics)
    evidence_list = list(evidence)
    document_companies = {
        document.id: document.company_name or document.file_name
        for document in documents
    }
    findings: list[ResearchFinding] = []
    missing: list[str] = []
    for document_id, company in document_companies.items():
        audit = next(
            (
                item
                for item in evidence_list
                if item.document_id == document_id
                and item.extraction_method == "audit_opinion_v1"
            ),
            None,
        )
        matter = next(
            (
                item
                for item in evidence_list
                if item.document_id == document_id
                and item.extraction_method == "key_audit_matters_v1"
            ),
            None,
        )
        if not audit and not matter:
            missing.append(f"{company}：审计意见和关键审计事项")
            continue
        parts = []
        evidence_ids = []
        tone = FindingTone.NEUTRAL
        if audit:
            opinion = audit.cell_value or "未明确"
            parts.append(f"审计意见为“{opinion}”")
            evidence_ids.append(audit.id)
            if "标准的无保留意见" not in opinion:
                tone = FindingTone.WARNING
        if matter:
            titles = re.findall(
                r"[（(][一二三四五六][）)]\s*([^\n]{2,30})", matter.quote
            )
            # `{2,30}` can match whitespace, which strips to an empty string and
            # rendered as a bare "、" in the report. Only keep candidates that
            # still read as a title after stripping.
            cleaned = [
                stripped
                for stripped in (title.strip(" \t：:　") for title in titles)
                if len(stripped) >= 2
            ]
            labels = "、".join(dict.fromkeys(cleaned[:4]))
            parts.append(f"关键审计事项包括 {labels or '需查阅原文的重大会计估计'}")
            evidence_ids.append(matter.id)
        findings.append(
            ResearchFinding(
                title=f"{company}：审计与重大估计",
                summary="；".join(parts) + "。该信息用于约束财务结论，不替代经营分析。",
                topic_key="audit_disclosures",
                tone=tone,
                company_name=company,
                evidence_ids=evidence_ids,
            )
        )

    serious = [
        issue
        for issue in issues
        if issue.severity in {IssueSeverity.ERROR, IssueSeverity.WARNING}
    ]
    if serious:
        serious_metric_ids = {
            metric_id for issue in serious for metric_id in issue.metric_ids
        }
        issue_metrics = [
            metric for metric in metric_list if metric.id in serious_metric_ids
        ]
        findings.append(
            ResearchFinding(
                title="数据质量风险",
                summary="；".join(issue.message for issue in serious[:5]),
                topic_key="data_quality",
                tone=FindingTone.WARNING,
                metric_ids=[item.id for item in issue_metrics],
                evidence_ids=_evidence_ids(issue_metrics),
            )
        )
    return AnalysisSection(
        key="disclosure_review",
        title="审计与披露约束",
        objective="识别审计意见、重大估计和数据质量对结论的限制。",
        methodology="直接引用审计报告及校验结果，不把程序完成状态当作研究结论。",
        status=_section_status(findings),
        findings=findings,
        missing_inputs=missing,
    )


def synthesize_research(
    metrics: Iterable[FinancialMetric],
    sections: Iterable[AnalysisSection],
    issues: Iterable[ValidationIssue],
    computations: Iterable[Computation] = (),
    anomalies: Iterable[FinancialAnomaly] = (),
    hypotheses: Iterable[ResearchHypothesis] = (),
) -> dict:
    metric_list = list(metrics)
    section_list = list(sections)
    issue_list = list(issues)
    computation_list = list(computations)
    anomaly_list = list(anomalies)
    hypothesis_list = list(hypotheses)
    result = analyze_metrics(metric_list)
    all_findings = [finding for section in section_list for finding in section.findings]
    tone_order = {
        FindingTone.WARNING: 0,
        FindingTone.WATCH: 1,
        FindingTone.NEUTRAL: 2,
        FindingTone.POSITIVE: 3,
    }
    status_order = {
        InvestigationStatus.SUPPORTED: 0,
        InvestigationStatus.PARTIAL: 1,
        InvestigationStatus.UNRESOLVED: 2,
        InvestigationStatus.REJECTED: 3,
    }
    # Headline selection is per company and ranked by materiality, so a filing
    # that supports more distinct conclusions surfaces more of them. The former
    # global cap of five meant a 200-page report and a 20-page one produced the
    # same number of headlines regardless of how much evidence each carried.
    top_findings: list[ResearchFinding] = []
    seen_topics: set[tuple[Optional[str], str]] = set()
    per_company: dict[Optional[str], int] = defaultdict(int)
    for finding in sorted(
        all_findings,
        key=lambda item: (
            tone_order[item.tone],
            status_order[item.status],
            -item.materiality,
        ),
    ):
        identity = (finding.company_name, finding.topic_key)
        if identity in seen_topics:
            continue
        if per_company[finding.company_name] >= MAX_HEADLINES_PER_COMPANY:
            continue
        seen_topics.add(identity)
        per_company[finding.company_name] += 1
        top_findings.append(finding)

    evidence_coverage = (
        sum(bool(metric.evidence_ids) for metric in metric_list)
        / len(metric_list)
        * 100
        if metric_list
        else 0.0
    )
    derived = [metric for metric in metric_list if not metric.is_reported]
    computed_ids = {item.metric_id for item in computation_list}
    computation_coverage = (
        sum(metric.id in computed_ids for metric in derived) / len(derived) * 100
        if derived
        else 100.0
    )
    limitations = list(
        dict.fromkeys(
            [
                *(
                    missing
                    for section in section_list
                    for missing in section.missing_inputs
                ),
                *(
                    question
                    for finding in all_findings
                    for question in finding.unanswered_questions
                ),
            ]
        )
    )
    result.update(
        {
            "sections": [section.model_dump(mode="json") for section in section_list],
            "top_findings": [
                finding.model_dump(mode="json") for finding in top_findings
            ],
            "anomalies": [item.model_dump(mode="json") for item in anomaly_list],
            "hypotheses": [item.model_dump(mode="json") for item in hypothesis_list],
            "quality": {
                "evidence_coverage_pct": evidence_coverage,
                "computation_coverage_pct": computation_coverage,
                "concept_count": len({metric.name for metric in metric_list}),
                "completed_sections": sum(
                    section.status == AnalysisStatus.COMPLETED
                    for section in section_list
                ),
                "partial_sections": sum(
                    section.status == AnalysisStatus.PARTIAL for section in section_list
                ),
                "insufficient_sections": sum(
                    section.status == AnalysisStatus.INSUFFICIENT_DATA
                    for section in section_list
                ),
                "total_sections": len(section_list),
                "reported_metrics": sum(metric.is_reported for metric in metric_list),
                "derived_metrics": len(derived),
                "computations": len(computation_list),
                "errors": sum(
                    issue.severity == IssueSeverity.ERROR for issue in issue_list
                ),
                "warnings": sum(
                    issue.severity == IssueSeverity.WARNING for issue in issue_list
                ),
            },
            "research_coverage": {
                "anomalies": len(anomaly_list),
                "hypotheses": len(hypothesis_list),
                "supported_hypotheses": sum(
                    item.status == InvestigationStatus.SUPPORTED
                    for item in hypothesis_list
                ),
                "partial_hypotheses": sum(
                    item.status == InvestigationStatus.PARTIAL
                    for item in hypothesis_list
                ),
                "unresolved_hypotheses": sum(
                    item.status == InvestigationStatus.UNRESOLVED
                    for item in hypothesis_list
                ),
            },
            "limitations": limitations,
            "insights": [finding.summary for finding in all_findings],
            "risks": [
                finding.summary
                for finding in all_findings
                if finding.tone in {FindingTone.WARNING, FindingTone.WATCH}
            ],
        }
    )
    return result
