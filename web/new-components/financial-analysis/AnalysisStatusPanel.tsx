import { Alert, Button, Space } from 'antd';
import React from 'react';
import { useReportData } from './ReportDataContext';

export interface AnalysisActions {
  retry: () => void;
  refresh: () => void;
  busy: boolean;
  error?: string;
}

const AnalysisStatusPanel: React.FC<{ actions?: AnalysisActions }> = ({ actions }) => {
  const { data } = useReportData();
  const analysis = data.analysis;
  if (data.mode !== 'report' || !analysis) return null;
  const messages = {
    running: '财务数据已就绪，正在生成模型分析',
    completed: '模型分析已生成，结论仍需核对',
    partial: '已保留部分分析，其他结论未生成或未通过校验',
    failed: '模型分析未完成，财务数据和原文仍可查看',
  };
  return (
    <Alert
      showIcon
      type={actions?.error || analysis.status === 'failed' || analysis.status === 'partial' ? 'warning' : 'info'}
      message={messages[analysis.status]}
      description={
        actions?.error ||
        analysis.error ||
        `${analysis.modelName} · 数字与引用已绑定，不能替代对提取结果和结论的人工核对。`
      }
      action={
        actions && (
          <Space wrap>
            {actions.error && <Button onClick={actions.refresh}>重新读取进度</Button>}
            {(analysis.status === 'failed' || analysis.status === 'partial') && (
              <Button loading={actions.busy} onClick={actions.retry}>
                重新分析此文件
              </Button>
            )}
          </Space>
        )
      }
    />
  );
};
export default AnalysisStatusPanel;
