import { FilePdfOutlined } from '@ant-design/icons';
import { Select } from 'antd';
import React, { useEffect, useMemo, useRef } from 'react';
import { supportLabels } from './FindingCard';
import styles from './financial-analysis.module.css';
import {
  analysisFindingMap,
  analysisFindings,
  calculationTraceMap,
  evidenceExcerptMap,
  financialFactMap,
  sourceDocumentMap,
} from './mock-data';
import { EvidenceExcerpt } from './types';

interface EvidencePanelProps {
  findingId: string;
  evidenceId?: string;
  onFindingChange: (findingId: string) => void;
  onOpenSource: (evidence: EvidenceExcerpt) => void;
}
const EvidencePanel: React.FC<EvidencePanelProps> = ({ findingId, evidenceId, onFindingChange, onOpenSource }) => {
  const finding = analysisFindingMap[findingId] || analysisFindings[0];
  const selectedRef = useRef<HTMLDivElement>(null);
  const resolved = useMemo(() => {
    const calculations = finding.calculationIds.map(id => calculationTraceMap[id]).filter(Boolean);
    // Include all calculation inputs and an explicitly selected citation, even when
    // the KPI is broader than the finding (e.g. revenue and ROE in earnings quality).
    const factIds = new Set([...finding.factIds, ...calculations.flatMap(item => item.inputFactIds)]);
    if (evidenceId)
      Object.values(financialFactMap)
        .filter(fact => fact.evidenceExcerptIds.includes(evidenceId))
        .forEach(fact => factIds.add(fact.id));
    const facts = Array.from(factIds)
      .map(id => financialFactMap[id])
      .filter(Boolean);
    const evidenceIds = new Set([...finding.evidenceExcerptIds, ...facts.flatMap(fact => fact.evidenceExcerptIds)]);
    if (evidenceId) evidenceIds.add(evidenceId);
    const evidence = Array.from(evidenceIds)
      .map(id => evidenceExcerptMap[id])
      .filter(Boolean);
    const documents = Array.from(new Set(evidence.map(item => item.sourceDocumentId)))
      .map(id => sourceDocumentMap[id])
      .filter(Boolean);
    return { calculations, facts, evidence, documents };
  }, [finding, evidenceId]);
  useEffect(() => {
    if (!evidenceId) return;
    const frame = requestAnimationFrame(() => {
      selectedRef.current?.scrollIntoView({ block: 'center' });
      selectedRef.current?.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [evidenceId, findingId]);

  return (
    <div className={styles.evidencePanel}>
      <label className={styles.meta} htmlFor='financial-finding-select'>
        研究发现
      </label>
      <Select
        id='financial-finding-select'
        className={styles.findingSelect}
        value={finding.id}
        onChange={onFindingChange}
        options={analysisFindings.map(item => ({ value: item.id, label: item.title }))}
      />
      <section className={styles.evidenceSection}>
        <h2>
          <span>01</span> Agent 分析
        </h2>
        <h3 className={styles.evidenceFindingTitle}>{finding.title}</h3>
        <p>{finding.summary}</p>
        <span className={styles.support} data-status={finding.supportStatus}>
          ● {supportLabels[finding.supportStatus]}
        </span>
        {finding.counterEvidence?.map(item => (
          <p className={styles.researchNote} key={item}>
            <strong>对冲证据</strong>
            {item}
          </p>
        ))}
        {finding.unresolvedQuestions?.map(item => (
          <p className={styles.researchNote} key={item}>
            <strong>待核查</strong>
            {item}
          </p>
        ))}
      </section>
      <section className={styles.evidenceSection}>
        <h2>
          <span>02</span> 确定性计算
        </h2>
        {resolved.calculations.map(calculation => (
          <div className={styles.calculationDetail} key={calculation.id}>
            <h3>{calculation.name}</h3>
            <div className={styles.meta}>{calculation.formula}</div>
            <div className={styles.calculationSteps}>
              {calculation.steps.map(step => (
                <div key={step}>{step}</div>
              ))}
            </div>
            <strong className={styles.calculationResult}>{calculation.displayResult}</strong>
          </div>
        ))}
      </section>
      <section className={styles.evidenceSection}>
        <h2>
          <span>03</span> 披露事实
        </h2>
        <div className={styles.evidenceFacts}>
          {resolved.facts.map(fact => (
            <div key={fact.id}>
              <div>
                <h3>{fact.metricName}</h3>
                <span className={styles.meta}>
                  {fact.fiscalPeriod} · {fact.statementScope}
                </span>
              </div>
              <div>
                <strong>{fact.displayValue}</strong>
                <div className={styles.citations}>
                  {fact.evidenceExcerptIds.map(id => (
                    <button type='button' key={id} onClick={() => onOpenSource(evidenceExcerptMap[id])}>
                      {id} · PDF {evidenceExcerptMap[id].page}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>
      <section className={styles.evidenceSection}>
        <h2>
          <span>04</span> 原始证据
        </h2>
        {resolved.evidence.map(evidence => (
          <div
            key={evidence.id}
            ref={evidence.id === evidenceId ? selectedRef : undefined}
            tabIndex={-1}
            className={styles.excerpt}
            data-selected={evidence.id === evidenceId}
          >
            <div className={styles.excerptHeading}>
              <strong>
                {evidence.id} · PDF {evidence.page}
              </strong>
              <button type='button' className={styles.textLink} onClick={() => onOpenSource(evidence)}>
                定位原文 →
              </button>
            </div>
            <div className={styles.meta}>
              {sourceDocumentMap[evidence.sourceDocumentId].fileName} · {evidence.section}
            </div>
            <div className={styles.meta}>
              {[evidence.table, evidence.row, evidence.column].filter(Boolean).join(' / ')}
            </div>
            <blockquote>{evidence.snippet}</blockquote>
            <div className={styles.excerptHeading}>
              <span className={styles.meta}>{evidence.extractedValue && `提取值：${evidence.extractedValue}`}</span>
              <span
                className={styles.support}
                data-status={evidence.qualityStatus === 'verified' ? 'supported' : 'partial'}
              >
                {evidence.qualityStatus === 'verified' ? '已核验' : '待复核'}
              </span>
            </div>
          </div>
        ))}
      </section>
      <section className={styles.evidenceSection}>
        <h2>
          <span>05</span> 来源文件
        </h2>
        {resolved.documents.map(document => (
          <div className={styles.fileRow} key={document.id}>
            <FilePdfOutlined />
            <div>
              <strong>{document.fileName}</strong>
              <div className={styles.meta}>
                {document.reportType} · {document.fiscalPeriod} · {document.version}
              </div>
            </div>
            <button
              type='button'
              className={styles.textLink}
              onClick={() => onOpenSource(resolved.evidence.find(item => item.sourceDocumentId === document.id)!)}
            >
              查看 →
            </button>
          </div>
        ))}
      </section>
    </div>
  );
};
export default EvidencePanel;
