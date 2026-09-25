import { ArrowLeftOutlined, InfoCircleOutlined } from '@ant-design/icons';
import { Tooltip } from 'antd';
import React from 'react';
import styles from './financial-analysis.module.css';
import { EvidenceExcerpt, SourceDocument } from './types';
interface SourcePreviewPanelProps {
  evidence: EvidenceExcerpt;
  document: SourceDocument;
  onBack: () => void;
}
const SourcePreviewPanel: React.FC<SourcePreviewPanelProps> = ({ evidence, document, onBack }) => (
  <div className={styles.sourcePanel}>
    <div className={styles.sourceToolbar}>
      <button type='button' className={styles.textLink} onClick={onBack}>
        <ArrowLeftOutlined /> 返回证据链
      </button>
      <Tooltip title='此视图按已提取片段排版，并非原始 PDF 页面图像。'>
        <button type='button' aria-label='来源预览说明'>
          <InfoCircleOutlined />
        </button>
      </Tooltip>
    </div>
    <div className={styles.sourceDocument}>
      <div className={styles.meta}>来源摘录 · {document.version}</div>
      <h2>{document.fileName}</h2>
      <p className={styles.sectionDescription}>
        {document.fiscalPeriod} · PDF Page {evidence.page}
      </p>
      <div className={styles.sourceSection}>{evidence.section || '来源片段'}</div>
      <p className={styles.meta}>{[evidence.table, evidence.row, evidence.column].filter(Boolean).join(' / ')}</p>
      <blockquote className={styles.sourceHighlight}>
        <span className={styles.meta}>{evidence.id}</span>
        <p>{evidence.snippet}</p>
      </blockquote>
      {evidence.extractedValue && (
        <dl className={styles.driverTable}>
          <div>
            <dt>提取值</dt>
            <dd>{evidence.extractedValue}</dd>
          </div>
        </dl>
      )}
      <div className={styles.sourcePage}>— {evidence.page} —</div>
    </div>
  </div>
);
export default SourcePreviewPanel;
