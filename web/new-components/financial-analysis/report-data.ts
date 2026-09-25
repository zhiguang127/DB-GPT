import type { EvidenceSelection, ReportData } from './types';

export const isDefined = <T>(value: T | undefined | null): value is T => value != null;
const indexById = <T extends { id: string }>(items: T[]): Record<string, T | undefined> =>
  Object.fromEntries(items.map(item => [item.id, item]));

export function indexReport(data: ReportData) {
  return {
    financialFactMap: indexById(data.facts),
    calculationTraceMap: indexById(data.calculations),
    analysisFindingMap: indexById(data.findings),
    evidenceExcerptMap: indexById(data.evidence),
    sourceDocumentMap: indexById(data.documents),
  };
}

export function resolveEvidence(data: ReportData, selection: EvidenceSelection) {
  const maps = indexReport(data);
  const finding = selection.findingId ? maps.analysisFindingMap[selection.findingId] : undefined;
  const metric = data.metrics.find(item => item.id === selection.metricId);
  const calculationIds = new Set([
    ...(finding?.calculationIds ?? []),
    ...[selection.calculationId, metric?.calculationId].filter(isDefined),
  ]);
  const calculations = [...calculationIds].map(id => maps.calculationTraceMap[id]).filter(isDefined);
  const factIds = new Set([
    ...(finding?.factIds ?? []),
    ...(metric?.factIds ?? []),
    ...[selection.factId].filter(isDefined),
    ...calculations.flatMap(item => item.inputFactIds),
    ...data.facts
      .filter(item => selection.evidenceId && item.evidenceExcerptIds.includes(selection.evidenceId))
      .map(item => item.id),
  ]);
  const facts = [...factIds].map(id => maps.financialFactMap[id]).filter(isDefined);
  const evidenceIds = new Set([
    ...(finding?.evidenceExcerptIds ?? []),
    ...facts.flatMap(item => item.evidenceExcerptIds),
    ...[selection.evidenceId].filter(isDefined),
  ]);
  const evidence = [...evidenceIds].map(id => maps.evidenceExcerptMap[id]).filter(isDefined);
  const documents = [...new Set(evidence.map(item => item.sourceDocumentId))]
    .map(id => maps.sourceDocumentMap[id])
    .filter(isDefined);
  return { finding, metric, calculations, facts, evidence, documents };
}

export function periodRange(points: Array<{ year: string }>) {
  const periods = [...new Set(points.map(item => item.year))].sort();
  return periods.length > 1 ? `${periods[0]}–${periods[periods.length - 1]}` : periods[0] || '期间未提供';
}

export const runStatusLabels = { pending: 'Pending', running: 'Running', completed: 'Completed', failed: 'Failed' };
