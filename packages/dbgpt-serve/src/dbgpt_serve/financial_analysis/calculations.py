"""Decimal calculations over explicitly compatible financial facts."""

from decimal import Decimal, InvalidOperation, localcontext

REASONS = {
    "missing_input": "缺少可用输入事实",
    "incompatible_input": "输入期间、币种、单位或报表口径不一致",
    "zero_denominator": "分母为零",
}


def calculate(facts, year):
    index = {(f["metricCode"], f["fiscalPeriod"]): f for f in facts}
    traces = []

    def add(code, name, terms, formula, operation, unit, *, growth=False):
        inputs = [index.get(term) for term in terms]
        reason = None
        values = []
        for fact, (metric, period) in zip(inputs, terms):
            if (
                not fact
                or fact.get("normalizedValue") is None
                or fact.get("extractionStatus") != "parsed"
            ):
                reason = "missing_input"
                break
            expected_attribution = (
                "owners_of_parent"
                if metric in {"net_profit", "non_recurring_net_profit", "equity"}
                else "consolidated"
            )
            expected_type = (
                "instant"
                if metric in {"total_assets", "total_liabilities", "equity"}
                else "flow"
            )
            if (
                fact.get("currency"),
                fact.get("unit"),
                fact.get("statementScope"),
                fact.get("attribution"),
                fact.get("periodType"),
                fact.get("fiscalPeriod"),
            ) != ("CNY", "元", "合并", expected_attribution, expected_type, period):
                reason = "incompatible_input"
                break
            try:
                value = Decimal(str(fact["normalizedValue"]))
                if not value.is_finite():
                    raise InvalidOperation
                values.append(value)
            except InvalidOperation:
                reason = "missing_input"
                break
        result = None
        if reason is None:
            try:
                with localcontext() as ctx:
                    ctx.prec = 38
                    result = operation(*values)
            except (ZeroDivisionError, InvalidOperation):
                reason = "zero_denominator"
        steps = [
            f"{f['fiscalPeriod']} {f['metricName']} = {f['normalizedValue']} 元"
            for f in inputs
            if f and f.get("normalizedValue") is not None
        ]
        if growth and len(values) == 2 and values[1] < 0:
            steps.append("上期为负数：同比以其绝对值为分母。")
        if reason:
            steps.append(REASONS[reason])
        else:
            steps.append(f"结果 = {format(result, 'f')} {unit}")
        traces.append(
            {
                "id": f"calc-{code}-{year}",
                "code": code,
                "name": name,
                "kind": "deterministic",
                "formula": formula,
                "inputFactIds": [f["id"] for f in inputs if f],
                "steps": steps,
                "result": format(result, "f") if result is not None else None,
                "displayResult": f"{result:,.2f}{unit}"
                if result is not None
                else "不可计算",
                "unit": unit,
                "fiscalPeriod": year,
                "status": "unavailable" if reason else "calculated",
                "reason": reason,
            }
        )

    prior = str(int(year) - 1)
    for code, label in [
        ("revenue", "营业收入"),
        ("net_profit", "归母净利润"),
        ("non_recurring_net_profit", "扣非归母净利润"),
        ("operating_cash_flow", "经营现金流"),
    ]:
        add(
            code + "_yoy",
            label + "同比",
            [(code, year), (code, prior)],
            "（本期－上期）÷ |上期| × 100%",
            lambda current, previous: (current - previous) / abs(previous) * 100,
            "%",
            growth=True,
        )
    add(
        "nonrecurring_impact",
        "非经常性净影响",
        [("net_profit", year), ("non_recurring_net_profit", year)],
        "归母净利润－扣非归母净利润",
        lambda profit, adjusted: profit - adjusted,
        "元",
    )
    add(
        "nonrecurring_share",
        "非经常性净影响占归母净利润",
        [("net_profit", year), ("non_recurring_net_profit", year)],
        "（归母净利润－扣非归母净利润）÷ 归母净利润 × 100%",
        lambda profit, adjusted: (profit - adjusted) / profit * 100,
        "%",
    )
    add(
        "cash_profit_ratio",
        "经营现金流 / 归母净利润",
        [("operating_cash_flow", year), ("net_profit", year)],
        "经营活动现金流量净额 ÷ 归母净利润",
        lambda cash, profit: cash / profit,
        "×",
    )
    add(
        "debt_ratio",
        "资产负债率",
        [("total_liabilities", year), ("total_assets", year)],
        "总负债 ÷ 总资产 × 100%",
        lambda liabilities, assets: liabilities / assets * 100,
        "%",
    )
    return traces
