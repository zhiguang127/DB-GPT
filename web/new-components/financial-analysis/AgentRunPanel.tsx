import type { ArtifactItem, ExecutionStep, ThinkingSection } from '@/new-components/chat/content/ManusLeftPanel';
import dynamic from 'next/dynamic';
import React, { useMemo } from 'react';
import { agentExecutionSteps, report, sourceDocuments } from './mock-data';
import { AgentExecutionStep } from './types';

const ManusLeftPanel = dynamic(() => import('@/new-components/chat/content/ManusLeftPanel'), {
  ssr: false,
  loading: () => (
    <div className='space-y-4 p-5'>
      <div className='ml-auto h-20 w-4/5 animate-pulse rounded-2xl bg-gray-100 dark:bg-white/[0.05]' />
      <div className='h-44 animate-pulse rounded-xl bg-gray-50 dark:bg-white/[0.03]' />
      <div className='h-28 animate-pulse rounded-xl bg-gray-50 dark:bg-white/[0.03]' />
    </div>
  ),
});

interface AgentRunPanelProps {
  activeStepId: string;
  onStepSelect: (stepId: string) => void;
  onOpenArtifact: () => void;
  onOpenFiles: () => void;
}

const toManusStepType = (type: AgentExecutionStep['type']): ExecutionStep['type'] => {
  if (type === 'analysis') return 'task';
  return type;
};

const toExecutionStep = (step: AgentExecutionStep): ExecutionStep => ({
  id: step.id,
  type: toManusStepType(step.type),
  title: step.title,
  subtitle: step.script || step.tool,
  description: step.detail,
  status: 'completed',
  action: step.tool,
  actionInput: step.script ? { script: step.script } : undefined,
});

const inputFiles = [
  {
    file_id: 'mock-financial-report-2019',
    name: sourceDocuments[0].fileName,
    size: 7_864_320,
    media_type: 'application/pdf',
    kind: 'document',
    status: 'ready' as const,
    ordinal: 0,
  },
];

const artifacts: ArtifactItem[] = [
  {
    id: 'artifact-financial-analysis',
    type: 'html',
    name: 'Financial Analysis Artifact.html',
    content: { kind: 'financial-analysis-mock' },
    createdAt: new Date(report.run.completedAt).getTime(),
    downloadable: false,
    mimeType: 'text/html',
    size: 186_420,
  },
];

const userQuery =
  '请使用 financial-report-analyzer 深度分析这份 2019 年年度报告，重点检查盈利质量、现金流与费用压力，并生成可交互的财务分析报告。';

const assistantText = `分析已完成，三项发现值得关注：\n\n- 扣非归母净利润下降 **26.61%**，非经常性净影响占归母净利润 **24.78%**。\n- 现金利润比降至 **0.57×**。\n- 四项期间费用率合计上升 **7.21 个百分点**。\n\n已生成 **Financial Analysis**，可在右侧核查计算与来源。`;

const AgentRunPanel: React.FC<AgentRunPanelProps> = ({ activeStepId, onStepSelect, onOpenArtifact, onOpenFiles }) => {
  const sections = useMemo<ThinkingSection[]>(() => {
    const converted = agentExecutionSteps.map(toExecutionStep);
    return [
      {
        id: 'section-understand',
        title: '理解任务与读取资料',
        content: '读取用户上传的年度报告，并调用 financial-report-analyzer。',
        isCompleted: true,
        steps: converted.slice(0, 2),
      },
      {
        id: 'section-analysis',
        title: '财务分析与可视化',
        content: '执行确定性计算、图表生成与盈利质量分析。',
        isCompleted: true,
        steps: converted.slice(2, 6),
      },
      {
        id: 'section-artifact',
        title: '生成交付物',
        content: '生成财务分析报告与可追溯研究发现。',
        isCompleted: true,
        steps: converted.slice(6),
      },
    ];
  }, []);

  return (
    <ManusLeftPanel
      sections={sections}
      activeStepId={activeStepId}
      onStepClick={stepId => onStepSelect(stepId)}
      isWorking={false}
      userQuery={userQuery}
      attachedFiles={inputFiles}
      attachedSkill={{ name: report.run.skillName, id: report.run.skillName }}
      assistantText={assistantText}
      modelName={report.run.modelName}
      artifacts={artifacts}
      onArtifactClick={onOpenArtifact}
      onViewAllFiles={onOpenFiles}
    />
  );
};

export default AgentRunPanel;
