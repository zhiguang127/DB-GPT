import { CheckCircleFilled } from '@ant-design/icons';
import React from 'react';
import styles from './financial-analysis.module.css';
import { agentExecutionSteps } from './mock-data';
const ExecutionProcessPanel: React.FC<{ activeStepId: string; onStepSelect: (stepId: string) => void }> = ({
  activeStepId,
  onStepSelect,
}) => {
  const activeStep = agentExecutionSteps.find(step => step.id === activeStepId) || agentExecutionSteps[0];
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
            <CheckCircleFilled />
            <span>{step.title}</span>
          </button>
        ))}
      </nav>
      <section className={styles.executionDetail}>
        <div className={styles.meta}>Step {activeStep.order} · Completed</div>
        <h2>{activeStep.title}</h2>
        <p>{activeStep.detail}</p>
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
