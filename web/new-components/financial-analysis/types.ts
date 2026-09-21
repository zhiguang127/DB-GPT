export type SupportStatus = 'supported' | 'partial' | 'unresolved';

export type QualityStatus = 'verified' | 'reviewed' | 'warning';

export type InformationKind = 'fact' | 'calculation' | 'analysis';

export interface AnalysisRun {
  id: string;
  agentName: string;
  modelName: string;
  skillName: 'financial-report-analyzer';
  status: 'completed';
  evidenceCoverage: number;
  completedAt: string;
}

export interface FinancialReport {
  id: string;
  companyName: string;
  shortName: string;
  stockCode: string;
  title: string;
  fiscalPeriod: string;
  statementScope: string;
  currency: string;
  sourceDocumentIds: string[];
  run: AnalysisRun;
}

export interface SourceDocument {
  id: string;
  fileName: string;
  reportType: string;
  fiscalPeriod: string;
  version: string;
}

export interface EvidenceExcerpt {
  id: string;
  sourceDocumentId: string;
  page: number;
  section?: string;
  table?: string;
  row?: string;
  column?: string;
  snippet: string;
  extractedValue?: string;
  qualityStatus: QualityStatus;
}

export interface FinancialFact {
  id: string;
  metricCode: string;
  metricName: string;
  rawValue: string;
  normalizedValue: number;
  displayValue: string;
  unit: string;
  fiscalPeriod: string;
  statementScope: string;
  evidenceExcerptIds: string[];
  qualityStatus: QualityStatus;
}

export interface CalculationTrace {
  id: string;
  name: string;
  kind: 'deterministic';
  formula: string;
  inputFactIds: string[];
  steps: string[];
  result: number;
  displayResult: string;
  unit: string;
}

export interface InlineTraceNode {
  kind: 'fact' | 'calculation' | 'evidence';
  refId: string;
  label?: string;
  displayValue?: string;
}

export interface AnalysisFinding {
  id: string;
  section: string;
  title: string;
  summary: string;
  supportStatus: SupportStatus;
  factIds: string[];
  calculationIds: string[];
  evidenceExcerptIds: string[];
  inlineTrace: InlineTraceNode[];
  counterEvidence?: string[];
  unresolvedQuestions?: string[];
}

export interface FinancialMetric {
  id: string;
  code: string;
  name: string;
  displayValue: string;
  change?: number;
  changeLabel?: string;
  changeUnit?: '%' | 'pp' | 'x';
  informationKind: Exclude<InformationKind, 'analysis'>;
  factIds?: string[];
  calculationId?: string;
  findingId?: string;
  citationLabel: string;
}

export interface AgentExecutionStep {
  id: string;
  order: number;
  type: 'skill' | 'read' | 'python' | 'analysis' | 'html';
  title: string;
  tool?: string;
  script?: string;
  detail: string;
  status: 'completed';
  capability: 'existing' | 'mock-extension';
}

export interface TrendPoint {
  year: string;
  metric: string;
  value: number;
}

export interface MockAnswer {
  question: string;
  answer: string;
  findingId: string;
}

export interface EvidenceSelection {
  findingId: string;
}
