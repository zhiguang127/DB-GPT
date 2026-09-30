/** A persisted agent artifact points to an authenticated report, never to HTML. */
export interface FinancialReportReference {
  kind: 'financial-report';
  runId: string;
  sessionId: string;
  revision: string;
  title: string;
}

export function isFinancialReportReference(value: unknown): value is FinancialReportReference {
  if (!value || typeof value !== 'object') return false;
  const ref = value as Record<string, unknown>;
  return (
    ref.kind === 'financial-report' &&
    typeof ref.runId === 'string' &&
    /^[a-f0-9-]{36}$/i.test(ref.runId) &&
    typeof ref.sessionId === 'string' &&
    /^[A-Za-z0-9_-]{1,255}$/.test(ref.sessionId) &&
    typeof ref.revision === 'string' &&
    ref.revision.length > 0 &&
    ref.revision.length <= 255 &&
    typeof ref.title === 'string' &&
    ref.title.length <= 500
  );
}

export function reportArtifactContent(content: any): any {
  if (isFinancialReportReference(content)) return content;
  return typeof content === 'string' ? content : content?.content || content?.html || String(content);
}
