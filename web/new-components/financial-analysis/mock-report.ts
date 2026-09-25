/** The only adapter allowed to import the unchanged demonstration dataset. */
import * as mock from './mock-data';
import type { ReportData } from './types';

export const mockReportData: ReportData = {
  schemaVersion: 1,
  revision: 'demo-1',
  mode: 'demo',
  report: mock.report,
  documents: mock.sourceDocuments.map(document => ({ ...document, sizeBytes: 7_864_320 })),
  evidence: mock.evidenceExcerpts,
  facts: mock.financialFacts,
  calculations: mock.calculationTraces,
  findings: mock.analysisFindings,
  metrics: mock.financialMetrics,
  steps: mock.agentExecutionSteps,
  trends: {
    revenue: mock.financialTrendData.filter(item => item.metric === '营业收入'),
    cashFlow: mock.financialTrendData.filter(item => item.metric !== '营业收入'),
    profit: ['2018', '2019'].flatMap(year =>
      ['net-profit', 'adjusted-profit'].map(metric => {
        const fact = mock.financialFactMap[`fact-${metric}-${year}`];
        return { year, metric: fact.metricName, value: Number(fact.normalizedValue) / 10000 };
      }),
    ),
    expenses: mock.expenseRateData,
    financialUnit: '亿元',
    profitUnit: '万元',
  },
  sections: {
    overview: { findingIds: mock.coreFindingIds },
    profitability: {
      title: '利润走弱，非经常性项目贡献了多少？',
      description: '归母净利润同比下降 15.49%，扣非归母净利润下降 26.61%。',
      findingIds: ['finding-earnings-quality', 'finding-expense-pressure'],
      calculationIds: ['calc-nonrecurring-impact', 'calc-nonrecurring-share'],
      evidenceIds: ['E35'],
    },
    cashflow: {
      findingIds: ['finding-cash-conversion'],
      calculationIds: ['calc-cash-profit-ratio'],
      comparisonLabel: '上年 0.77×',
    },
    balance: {
      description: '2019 年末 · 合并报表',
      findingIds: ['finding-balance-health'],
      factIds: ['fact-assets-2019', 'fact-liabilities-2019'],
    },
  },
  healthMetrics: [
    { id: 'debt', name: '资产负债率', displayValue: '21.14%', selection: { findingId: 'finding-balance-health' } },
    { id: 'cash', name: '现金利润比', displayValue: '0.57×', selection: { findingId: 'finding-cash-conversion' } },
    { id: 'current', name: '流动比率', displayValue: '4.06×' },
    { id: 'quick', name: '速动比率', displayValue: '3.42×' },
  ],
  statements: {
    unit: '元',
    periods: [
      { period: '2019 年度', label: '2019' },
      { period: '2018 年度', label: '2018' },
    ],
    rows: ['revenue', 'net-profit', 'adjusted-profit', 'ocf'].map(key => ({
      id: key,
      name: mock.financialFactMap[`fact-${key}-2019`].metricName,
      factIds: [`fact-${key}-2019`, `fact-${key}-2018`],
    })),
  },
  artifacts: [
    {
      id: 'artifact-financial-analysis',
      name: 'Financial Analysis Artifact.html',
      kind: 'html',
      detail: '分析报告 · HTML',
      sizeBytes: 186_420,
    },
    { id: 'trends', name: 'financial_trends.png', kind: 'png', detail: '图表输出 · PNG' },
    { id: 'ratios', name: 'financial_ratios.json', kind: 'json', detail: '结构化指标 · JSON' },
  ],
  agent: {
    userQuery:
      '请使用 financial-report-analyzer 深度分析这份 2019 年年度报告，重点检查盈利质量、现金流与费用压力，并生成可交互的财务分析报告。',
    summary:
      '分析已完成，三项发现值得关注：\n\n- 扣非归母净利润下降 **26.61%**，非经常性净影响占归母净利润 **24.78%**。\n- 现金利润比降至 **0.57×**。\n- 四项期间费用率合计上升 **7.21 个百分点**。\n\n已生成 **Financial Analysis**，可在右侧核查计算与来源。',
    groups: [
      {
        id: 'section-understand',
        title: '理解任务与读取资料',
        content: '读取用户上传的年度报告，并调用 financial-report-analyzer。',
        stepIds: mock.agentExecutionSteps.slice(0, 2).map(item => item.id),
      },
      {
        id: 'section-analysis',
        title: '财务分析与可视化',
        content: '执行确定性计算、图表生成与盈利质量分析。',
        stepIds: mock.agentExecutionSteps.slice(2, 6).map(item => item.id),
      },
      {
        id: 'section-artifact',
        title: '生成交付物',
        content: '生成财务分析报告与可追溯研究发现。',
        stepIds: mock.agentExecutionSteps.slice(6).map(item => item.id),
      },
    ],
  },
  demoQuestions: mock.mockAnswers.map((answer, index) => ({
    ...answer,
    label: ['利润为何下降？', '现金转化如何？', '非经常性损益', '偿债结构'][index],
    keywords: [['费用', '利润'], ['现金'], ['非经常', '扣非'], ['偿债', '负债']][index],
    priority: [3, 0, 1, 2][index],
  })),
};
