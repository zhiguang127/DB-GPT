"""Canonical facts supported by the PDF financial-statement extractor.

The catalog is intentionally explicit. A fact is only emitted when a row in a
known table matches one of these aliases; unknown rows remain in the parsed table
index instead of being guessed into a financial concept.
"""

from dataclasses import dataclass
from typing import Sequence, Tuple

from .models import MetricUnit, PeriodType, StatementType


@dataclass(frozen=True)
class MetricSpec:
    name: str
    display_name: str
    aliases: Tuple[str, ...]
    statement_type: StatementType
    unit: MetricUnit = MetricUnit.MONEY
    period_type: PeriodType = PeriodType.DURATION
    exclude: Tuple[str, ...] = ()


def _balance(
    name: str, display_name: str, *aliases: str, exclude: Tuple[str, ...] = ()
) -> MetricSpec:
    return MetricSpec(
        name,
        display_name,
        aliases or (display_name,),
        StatementType.BALANCE_SHEET,
        period_type=PeriodType.INSTANT,
        exclude=exclude,
    )


def _income(
    name: str,
    display_name: str,
    *aliases: str,
    unit: MetricUnit = MetricUnit.MONEY,
    exclude: Tuple[str, ...] = (),
) -> MetricSpec:
    return MetricSpec(
        name,
        display_name,
        aliases or (display_name,),
        StatementType.INCOME_STATEMENT,
        unit=unit,
        exclude=exclude,
    )


def _cash(name: str, display_name: str, *aliases: str) -> MetricSpec:
    return MetricSpec(
        name,
        display_name,
        aliases or (display_name,),
        StatementType.CASH_FLOW_STATEMENT,
    )


BALANCE_SHEET_SPECS: Sequence[MetricSpec] = (
    _balance("cash", "货币资金"),
    _balance("trading_financial_assets", "交易性金融资产"),
    _balance("notes_receivable", "应收票据", exclude=("及应收账款",)),
    _balance("accounts_receivable", "应收账款", exclude=("票据及",)),
    _balance("notes_and_accounts_receivable", "应收票据及应收账款"),
    _balance("receivables_financing", "应收款项融资"),
    _balance("prepayments", "预付款项"),
    _balance("other_receivables", "其他应收款"),
    _balance("inventory", "存货"),
    _balance("contract_assets", "合同资产"),
    _balance("other_current_assets", "其他流动资产"),
    _balance("current_assets", "流动资产合计"),
    _balance("long_term_receivables", "长期应收款"),
    _balance("long_term_equity_investment", "长期股权投资"),
    _balance("investment_property", "投资性房地产"),
    _balance("fixed_assets", "固定资产"),
    _balance("construction_in_progress", "在建工程"),
    _balance("right_of_use_assets", "使用权资产"),
    _balance("intangible_assets", "无形资产"),
    _balance("development_expenditure", "开发支出"),
    _balance("goodwill", "商誉"),
    _balance("long_term_deferred_expenses", "长期待摊费用"),
    _balance("deferred_tax_assets", "递延所得税资产"),
    _balance("other_non_current_assets", "其他非流动资产"),
    _balance("non_current_assets", "非流动资产合计"),
    _balance("total_assets", "资产总计", "资产总计", "资产总额"),
    _balance("short_term_borrowings", "短期借款"),
    _balance("trading_financial_liabilities", "交易性金融负债"),
    _balance("notes_payable", "应付票据", exclude=("及应付账款",)),
    _balance("accounts_payable", "应付账款", exclude=("票据及",)),
    _balance("notes_and_accounts_payable", "应付票据及应付账款"),
    _balance("advances_from_customers", "预收款项"),
    _balance("contract_liabilities", "合同负债"),
    _balance("employee_benefits_payable", "应付职工薪酬"),
    _balance("taxes_payable", "应交税费"),
    _balance("other_payables", "其他应付款"),
    _balance("current_portion_non_current_liabilities", "一年内到期的非流动负债"),
    _balance("other_current_liabilities", "其他流动负债"),
    _balance("current_liabilities", "流动负债合计"),
    _balance("long_term_borrowings", "长期借款"),
    _balance("bonds_payable", "应付债券"),
    _balance("lease_liabilities", "租赁负债"),
    _balance("long_term_payables", "长期应付款"),
    _balance("provisions", "预计负债"),
    _balance("deferred_income", "递延收益"),
    _balance("deferred_tax_liabilities", "递延所得税负债"),
    _balance("other_non_current_liabilities", "其他非流动负债"),
    _balance("non_current_liabilities", "非流动负债合计"),
    _balance("total_liabilities", "负债合计"),
    _balance("share_capital", "股本", "股本", "实收资本（或股本）"),
    _balance("capital_reserve", "资本公积"),
    _balance("treasury_stock", "库存股", "减：库存股"),
    _balance("other_comprehensive_income", "其他综合收益"),
    _balance("surplus_reserve", "盈余公积"),
    _balance("retained_earnings", "未分配利润"),
    _balance(
        "shareholder_equity",
        "归属于母公司所有者权益",
        "归属于母公司所有者权益合计",
        "归属于上市公司股东的净资产",
    ),
    _balance("minority_interests", "少数股东权益"),
    _balance("total_equity", "所有者权益合计", "所有者权益合计", "股东权益合计"),
    _balance("total_liabilities_and_equity", "负债和所有者权益总计"),
)


INCOME_STATEMENT_SPECS: Sequence[MetricSpec] = (
    _income("total_operating_revenue", "营业总收入"),
    _income("revenue", "营业收入", exclude=("营业总收入",)),
    _income("total_operating_cost", "营业总成本"),
    _income("operating_cost", "营业成本", exclude=("营业总成本",)),
    _income("taxes_and_surcharges", "税金及附加"),
    _income("selling_expenses", "销售费用"),
    _income("administrative_expenses", "管理费用"),
    _income("research_and_development_expenses", "研发费用"),
    _income("finance_expenses", "财务费用"),
    _income("interest_expense", "利息费用"),
    _income("interest_income", "利息收入"),
    _income("other_income", "其他收益"),
    _income("investment_income", "投资收益"),
    _income("fair_value_change_income", "公允价值变动收益"),
    _income("credit_impairment_loss", "信用减值损失"),
    _income("asset_impairment_loss", "资产减值损失"),
    _income("asset_disposal_income", "资产处置收益"),
    _income("operating_profit", "营业利润"),
    _income("non_operating_income", "营业外收入"),
    _income("non_operating_expense", "营业外支出"),
    _income("total_profit", "利润总额"),
    _income("income_tax_expense", "所得税费用"),
    _income("net_profit_total", "净利润", exclude=("归属于",)),
    _income(
        "net_profit",
        "归母净利润",
        "归属于母公司所有者的净利润",
        "归属于母公司股东的净利润",
        "归属于上市公司股东的净利润",
        exclude=("扣除非",),
    ),
    _income("minority_profit", "少数股东损益"),
    _income("comprehensive_income", "综合收益总额"),
    _income(
        "parent_comprehensive_income",
        "归属于母公司所有者的综合收益总额",
    ),
    _income("basic_eps", "基本每股收益", unit=MetricUnit.MONEY_PER_SHARE),
    _income("diluted_eps", "稀释每股收益", unit=MetricUnit.MONEY_PER_SHARE),
)


CASH_FLOW_SPECS: Sequence[MetricSpec] = (
    _cash("cash_received_from_sales", "销售商品、提供劳务收到的现金"),
    _cash("tax_refunds_received", "收到的税费返还"),
    _cash("other_operating_cash_received", "收到其他与经营活动有关的现金"),
    _cash("operating_cash_inflow", "经营活动现金流入小计"),
    _cash("cash_paid_for_goods", "购买商品、接受劳务支付的现金"),
    _cash("cash_paid_to_employees", "支付给职工以及为职工支付的现金"),
    _cash("taxes_paid", "支付的各项税费"),
    _cash("other_operating_cash_paid", "支付其他与经营活动有关的现金"),
    _cash("operating_cash_outflow", "经营活动现金流出小计"),
    _cash("operating_cash_flow", "经营活动产生的现金流量净额"),
    _cash("investing_cash_inflow", "投资活动现金流入小计"),
    _cash(
        "cash_received_from_asset_disposals",
        "处置固定资产、无形资产和其他长期资产收回的现金净额",
    ),
    _cash(
        "cash_paid_for_long_term_assets",
        "购建固定资产、无形资产和其他长期资产支付的现金",
    ),
    _cash("investing_cash_outflow", "投资活动现金流出小计"),
    _cash("investing_cash_flow", "投资活动产生的现金流量净额"),
    _cash("financing_cash_inflow", "筹资活动现金流入小计"),
    _cash("cash_received_from_borrowings", "取得借款收到的现金"),
    _cash("cash_paid_for_debt", "偿还债务支付的现金"),
    _cash(
        "cash_paid_for_dividends_and_interest",
        "分配股利、利润或偿付利息支付的现金",
    ),
    _cash("financing_cash_outflow", "筹资活动现金流出小计"),
    _cash("financing_cash_flow", "筹资活动产生的现金流量净额"),
    _cash("fx_effect_on_cash", "汇率变动对现金及现金等价物的影响"),
    _cash("net_increase_in_cash", "现金及现金等价物净增加额"),
    _cash("cash_at_beginning", "期初现金及现金等价物余额"),
    _cash("cash_at_end", "期末现金及现金等价物余额"),
)


SUMMARY_METRIC_SPECS: Sequence[MetricSpec] = (
    MetricSpec("revenue", "营业收入", ("营业收入",), StatementType.SUMMARY),
    MetricSpec(
        "non_recurring_net_profit",
        "扣除非经常性损益后的净利润",
        ("归属于上市公司股东的扣除非", "扣除非经常性损益"),
        StatementType.SUMMARY,
    ),
    MetricSpec(
        "net_profit",
        "归母净利润",
        ("归属于上市公司股东的净利润",),
        StatementType.SUMMARY,
        exclude=("扣除非",),
    ),
    MetricSpec(
        "operating_cash_flow",
        "经营活动现金流量净额",
        ("经营活动产生的现金流量净额",),
        StatementType.SUMMARY,
    ),
    MetricSpec(
        "basic_eps",
        "基本每股收益",
        ("基本每股收益",),
        StatementType.SUMMARY,
        unit=MetricUnit.MONEY_PER_SHARE,
    ),
    MetricSpec(
        "diluted_eps",
        "稀释每股收益",
        ("稀释每股收益",),
        StatementType.SUMMARY,
        unit=MetricUnit.MONEY_PER_SHARE,
    ),
    MetricSpec(
        "weighted_roe",
        "加权平均净资产收益率",
        ("加权平均净资产收益率",),
        StatementType.SUMMARY,
        unit=MetricUnit.PERCENT,
    ),
    MetricSpec(
        "total_assets",
        "资产总额",
        ("资产总额", "总资产"),
        StatementType.SUMMARY,
        period_type=PeriodType.INSTANT,
    ),
    MetricSpec(
        "shareholder_equity",
        "归属于上市公司股东的净资产",
        ("归属于上市公司股东的净资产",),
        StatementType.SUMMARY,
        period_type=PeriodType.INSTANT,
    ),
)


METRIC_SPECS: Sequence[MetricSpec] = (
    *BALANCE_SHEET_SPECS,
    *INCOME_STATEMENT_SPECS,
    *CASH_FLOW_SPECS,
)


SUPPORTED_FACT_COUNT = len({spec.name for spec in METRIC_SPECS})
