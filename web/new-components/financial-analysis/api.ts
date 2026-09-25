import type { ApiResponse } from '@/client/api';
import { GET, POST } from '@/client/api';
import type { ReportData } from './types';

export interface FinancialRunStatus {
  id: string;
  session_id: string;
  file_id: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  stage: string;
  error: string | null;
}
const base = '/api/v1/financial-analysis/runs';
function unwrap<T>(response: ApiResponse<T>): T {
  if (!response.data.success) throw new Error(response.data.err_msg || '财报请求失败');
  return response.data.data;
}
export async function createRun(sessionId: string, fileId: string, requestId: string) {
  return unwrap(
    await POST<unknown, FinancialRunStatus>(base, {
      session_id: sessionId,
      file_ids: [fileId],
      request_id: requestId,
    }),
  );
}
export async function getRun(sessionId: string, runId: string, signal?: AbortSignal) {
  return unwrap(
    await GET<unknown, FinancialRunStatus>(
      `${base}/${encodeURIComponent(runId)}`,
      { session_id: sessionId },
      { signal },
    ),
  );
}
export async function getReport(sessionId: string, runId: string, signal?: AbortSignal) {
  return unwrap(
    await GET<unknown, ReportData>(
      `${base}/${encodeURIComponent(runId)}/report`,
      { session_id: sessionId },
      { signal },
    ),
  );
}
export function requestError(error: unknown): string {
  const value = error as { response?: { data?: { err_msg?: string } }; message?: string };
  return value?.response?.data?.err_msg || value?.message || '请求失败，请重试';
}
