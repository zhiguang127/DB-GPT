import { CheckCircleFilled } from '@ant-design/icons';
import React from 'react';
import { useReportData } from './ReportDataContext';
import styles from './financial-analysis.module.css';
import { runStatusLabels } from './report-data';
export interface AnalysisActions {
  retry: () => void;
  refresh: () => void;
  busy: boolean;
  error?: string;
}

const analysisStatusLabels = {
  running: '分析中',
  completed: '分析完成',
  partial: '部分分析',
  failed: '分析未完成',
};

const ExecutionProcessPanel: React.FC<{
  activeStepId?: string;
  onStepSelect: (stepId: string) => void;
  analysisActions?: AnalysisActions;
}> = ({ activeStepId, onStepSelect, analysisActions }) => {
  const { data } = useReportData();
  const agentExecutionSteps = data.steps;
  const activeStep = agentExecutionSteps.find(step => step.id === activeStepId) || agentExecutionSteps[0];
  if (!activeStep) return <div className={styles.executionPanel}>暂无执行记录</div>;
  const analysis = data.mode === 'report' && activeStep.id === 'analyze' ? data.analysis : undefined;
  return (
    <div className={styles.executionPanel}>
      <nav aria-label='执行步骤' className={styles.executionSteps}>
        {agentExecutionSteps.map(step => (
          <button
            type='button'
            key={step.id}
            aria-current={step.id === activeStep.id ? 'step' : undefined}
            onClick={() => onStepSelect(step.id)}
          >
            {step.status === 'completed' && <CheckCircleFilled />}
            <span>{step.title}</span>
          </button>
        ))}
      </nav>
      <section className={styles.executionDetail}>
        <div className={styles.meta}>
          Step {activeStep.order} ·{' '}
          {analysis ? analysisStatusLabels[analysis.status] : runStatusLabels[activeStep.status]}
        </div>
        <h2>{activeStep.title}</h2>
        <p>{activeStep.detail}</p>
        {analysis && analysisActions && (
          <>
            {analysisActions.error && (
              <p>
                {analysisActions.error}{' '}
                <button type='button' className={styles.textLink} onClick={analysisActions.refresh}>
                  重新读取进度
                </button>
              </p>
            )}
            {(analysis.status === 'partial' || analysis.status === 'failed') && (
              <button
                type='button'
                className={styles.textLink}
                disabled={analysisActions.busy}
                onClick={analysisActions.retry}
              >
                {analysisActions.busy ? '正在创建任务…' : '重新分析此文件'}
              </button>
            )}
          </>
        )}
        <dl className={styles.driverTable}>
          {activeStep.tool && (
            <div>
              <dt>工具</dt>
              <dd>{activeStep.tool}</dd>
            </div>
          )}
          {activeStep.script && (
            <div>
              <dt>脚本</dt>
              <dd>{activeStep.script}</dd>
            </div>
          )}
        </dl>
      </section>
    </div>
  );
};
export default ExecutionProcessPanel;
