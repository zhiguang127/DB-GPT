import type { ChartConfig } from '@/new-components/charts/AdvancedCharts';
import { LinkOutlined } from '@ant-design/icons';
import { Table, Tooltip } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import dynamic from 'next/dynamic';
import React from 'react';
import FindingCard from './FindingCard';
import styles from './financial-analysis.module.css';
import {
  analysisFindingMap,
  calculationTraceMap,
  coreFindingIds,
  expenseRateData,
  financialFactMap,
  financialMetrics,
  financialTrendData,
} from './mock-data';

const FinancialChart = dynamic(() => import('./FinancialChart'), {
  ssr: false,
  loading: () => <div className={styles.chartLoading} aria-label='正在加载图表' />,
});
export interface ReportSectionProps {
  onOpenEvidence: (findingId: string, evidenceId?: string) => void;
}
const Figure: React.FC<{ title: string; caption: string; config: ChartConfig }> = ({ title, caption, config }) => (
  <figure className={styles.figure}>
    <figcaption>
      <h3>{title}</h3>
      <span className={styles.meta}>{caption}</span>
    </figcaption>
    <FinancialChart
      config={{
        height: 280,
        showLegend: true,
        showGrid: false,
        showToolbar: false,
        enableZoom: false,
        smooth: false,
        animate: false,
        colors: ['#0069fe', '#94a3b8'],
        ...config,
      }}
    />
  </figure>
);
const HealthTable: React.FC<ReportSectionProps> = ({ onOpenEvidence }) => (
  <dl className={styles.ratioTable}>
    <div>
      <dt>资产负债率</dt>
      <dd>
        <button type='button' onClick={() => onOpenEvidence('finding-balance-health')}>
          21.14% <LinkOutlined />
        </button>
      </dd>
    </div>
    <div>
      <dt>现金利润比</dt>
      <dd>
        <button type='button' onClick={() => onOpenEvidence('finding-cash-conversion')}>
          0.57× <LinkOutlined />
        </button>
      </dd>
    </div>
    <div>
      <dt>流动比率</dt>
      <dd>4.06×</dd>
    </div>
    <div>
      <dt>速动比率</dt>
      <dd>3.42×</dd>
    </div>
  </dl>
);
export const OverviewTab: React.FC<ReportSectionProps> = ({ onOpenEvidence }) => (
  <div className={styles.reportFlow}>
    <section aria-label='财务快照' className={styles.snapshot}>
      {financialMetrics.map(metric => {
        const [value, unit] = metric.displayValue.split(' ');
        const change = metric.change;
        const evidenceId =
          metric.informationKind === 'fact' && metric.factIds?.length
            ? financialFactMap[metric.factIds[0]].evidenceExcerptIds[0]
            : undefined;
        return (
          <div className={styles.metric} key={metric.id}>
            <div className={styles.metricLabel}>
              {metric.name}
              <Tooltip
                title={`${metric.informationKind === 'fact' ? '披露事实' : '确定性计算'} · ${metric.citationLabel}`}
              >
                <button
                  type='button'
                  aria-label={`${metric.name}：查看${metric.citationLabel}`}
                  onClick={() => metric.findingId && onOpenEvidence(metric.findingId, evidenceId)}
                >
                  <LinkOutlined />
                </button>
              </Tooltip>
            </div>
            <div className={styles.metricValue}>
              {value}
              <span>{unit}</span>
            </div>
            {change !== undefined && (
              <div className={styles.metricChange} data-negative={change < 0 || metric.code === 'debt_ratio'}>
                {change > 0 ? '+' : ''}
                {change}
                {metric.changeUnit} <span>{metric.changeLabel}</span>
              </div>
            )}
          </div>
        );
      })}
    </section>
    <section aria-label='核心研究发现'>
      <FindingCard finding={analysisFindingMap[coreFindingIds[0]]} onOpenEvidence={onOpenEvidence} />
    </section>
    <section className={styles.reportSection}>
      <h2>业绩趋势</h2>
      <p className={styles.sectionDescription}>2017–2019 · 收入与利润分别呈现，保留各自金额尺度。</p>
      <div className={styles.trendFigures}>
        <Figure
          title='营业收入'
          caption='亿元 · 独立纵轴'
          config={{
            chartType: 'column',
            data: financialTrendData.filter(item => item.metric === '营业收入'),
            xField: 'year',
            yField: 'value',
            showLegend: false,
          }}
        />
        <Figure
          title='利润与经营现金流'
          caption='亿元'
          config={{
            chartType: 'line',
            data: financialTrendData.filter(item => item.metric !== '营业收入'),
            xField: 'year',
            yField: 'value',
            seriesField: 'metric',
          }}
        />
      </div>
    </section>
    <section className={styles.reportSection}>
      <h2>其他研究发现</h2>
      {coreFindingIds.slice(1).map(id => (
        <FindingCard key={id} finding={analysisFindingMap[id]} onOpenEvidence={onOpenEvidence} compact />
      ))}
    </section>
    <section className={styles.reportSection}>
      <h2>财务健康</h2>
      <HealthTable onOpenEvidence={onOpenEvidence} />
    </section>
  </div>
);
export const ProfitabilityTab: React.FC<ReportSectionProps> = ({ onOpenEvidence }) => (
  <div className={styles.reportFlow}>
    <section>
      <h2>利润走弱，非经常性项目贡献了多少？</h2>
      <p className={styles.sectionDescription}>归母净利润同比下降 15.49%，扣非归母净利润下降 26.61%。</p>
      <Figure
        title='归母与扣非归母净利润'
        caption='2018–2019 · 万元 · 披露事实'
        config={{
          chartType: 'column',
          data: ['2018', '2019'].flatMap(year =>
            ['net-profit', 'adjusted-profit'].map(metric => {
              const fact = financialFactMap[`fact-${metric}-${year}`];
              return { year, metric: fact.metricName, value: fact.normalizedValue / 10000 };
            }),
          ),
          xField: 'year',
          yField: 'value',
          seriesField: 'metric',
        }}
      />
    </section>
    <FindingCard finding={analysisFindingMap['finding-earnings-quality']} onOpenEvidence={onOpenEvidence} />
    <section className={styles.reportSection}>
      <h2>非经常性影响</h2>
      <p className={styles.sectionDescription}>{analysisFindingMap['finding-earnings-quality'].counterEvidence?.[0]}</p>
      <dl className={styles.ratioTable}>
        {['calc-nonrecurring-impact', 'calc-nonrecurring-share'].map(id => (
          <div key={id}>
            <dt>{calculationTraceMap[id].name}</dt>
            <dd>{calculationTraceMap[id].displayResult}</dd>
          </div>
        ))}
      </dl>
      <button
        type='button'
        className={styles.textLink}
        onClick={() => onOpenEvidence('finding-earnings-quality', 'E35')}
      >
        查看非经常性损益披露 · E35 →
      </button>
    </section>
    <section className={styles.reportSection}>
      <Figure
        title='期间费用率压力'
        caption='占营业收入比例（%） · 2018 vs 2019'
        config={{
          chartType: 'column',
          data: expenseRateData,
          xField: 'expense',
          yField: 'value',
          seriesField: 'year',
          colors: ['#94a3b8', '#0069fe'],
          height: 320,
        }}
      />
      <FindingCard finding={analysisFindingMap['finding-expense-pressure']} onOpenEvidence={onOpenEvidence} />
    </section>
  </div>
);
export const CashFlowTab: React.FC<ReportSectionProps> = ({ onOpenEvidence }) => (
  <div className={styles.reportFlow}>
    <section>
      <h2>现金创造能否支撑账面利润？</h2>
      <div className={styles.cashHeadline}>
        <strong>{calculationTraceMap['calc-cash-profit-ratio'].displayResult}</strong>
        <span>
          现金利润比 <span className={styles.meta}>／ 上年 0.77×</span>
        </span>
      </div>
      <Figure
        title='归母净利润与经营现金流'
        caption='2017–2019 · 亿元 · 披露事实'
        config={{
          chartType: 'line',
          data: financialTrendData.filter(item => item.metric !== '营业收入'),
          xField: 'year',
          yField: 'value',
          seriesField: 'metric',
          height: 340,
        }}
      />
    </section>
    <FindingCard finding={analysisFindingMap['finding-cash-conversion']} onOpenEvidence={onOpenEvidence} />
    <section className={styles.reportSection}>
      <h2>现金流驱动与待核查事项</h2>
      <dl className={styles.driverTable}>
        <div>
          <dt>正向对冲</dt>
          <dd>{analysisFindingMap['finding-cash-conversion'].counterEvidence?.[0]}</dd>
        </div>
        <div>
          <dt>待核查</dt>
          <dd>{analysisFindingMap['finding-cash-conversion'].unresolvedQuestions?.[0]}</dd>
        </div>
      </dl>
    </section>
  </div>
);
export const BalanceTab: React.FC<ReportSectionProps> = ({ onOpenEvidence }) => (
  <div className={styles.reportFlow}>
    <section>
      <h2>资本结构</h2>
      <p className={styles.sectionDescription}>2019 年末 · 合并报表</p>
      <dl className={styles.capitalTable}>
        {['fact-assets-2019', 'fact-liabilities-2019'].map(id => {
          const fact = financialFactMap[id];
          return (
            <div key={id}>
              <dt>{fact.metricName}</dt>
              <dd>
                {fact.displayValue}
                <button
                  type='button'
                  className={styles.textLink}
                  onClick={() => onOpenEvidence('finding-balance-health', fact.evidenceExcerptIds[0])}
                >
                  {fact.evidenceExcerptIds[0]} <LinkOutlined />
                </button>
              </dd>
            </div>
          );
        })}
      </dl>
    </section>
    <section className={styles.reportSection}>
      <h2>偿债与流动性</h2>
      <HealthTable onOpenEvidence={onOpenEvidence} />
    </section>
    <FindingCard finding={analysisFindingMap['finding-balance-health']} onOpenEvidence={onOpenEvidence} />
  </div>
);
interface StatementRow {
  key: string;
  item: string;
  value2019: string;
  value2018: string;
  evidence: string;
  evidenceId: string;
  findingId: string;
}
export const StatementsTab: React.FC<ReportSectionProps> = ({ onOpenEvidence }) => {
  const rows: StatementRow[] = ['revenue', 'net-profit', 'adjusted-profit', 'ocf'].map(key => {
    const current = financialFactMap[`fact-${key}-2019`];
    const previous = financialFactMap[`fact-${key}-2018`];
    return {
      key,
      item: current.metricName,
      value2019: current.rawValue,
      value2018: previous.rawValue,
      evidence: [...current.evidenceExcerptIds, ...previous.evidenceExcerptIds].join(' / '),
      evidenceId: current.evidenceExcerptIds[0],
      findingId: key === 'ocf' ? 'finding-cash-conversion' : 'finding-earnings-quality',
    };
  });
  const columns: ColumnsType<StatementRow> = [
    { title: '项目', dataIndex: 'item', key: 'item' },
    { title: '2019', dataIndex: 'value2019', key: 'value2019', align: 'right' },
    { title: '2018', dataIndex: 'value2018', key: 'value2018', align: 'right' },
    {
      title: '来源',
      key: 'evidence',
      render: (_, row) => (
        <button type='button' className={styles.textLink} onClick={() => onOpenEvidence(row.findingId, row.evidenceId)}>
          {row.evidence}
        </button>
      ),
    },
  ];
  return (
    <section>
      <h2>关键报表项目</h2>
      <p className={styles.sectionDescription}>合并报表 · 单位：元</p>
      <Table size='middle' columns={columns} dataSource={rows} pagination={false} scroll={{ x: 640 }} />
    </section>
  );
};
