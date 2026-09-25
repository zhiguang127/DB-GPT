import React, { createContext, useContext, useMemo } from 'react';
import { indexReport } from './report-data';
import type { ReportData } from './types';

const ReportContext = createContext<(ReturnType<typeof indexReport> & { data: ReportData }) | null>(null);

export const ReportDataProvider: React.FC<React.PropsWithChildren<{ data: ReportData }>> = ({ data, children }) => {
  const value = useMemo(() => ({ data, ...indexReport(data) }), [data]);
  return <ReportContext.Provider value={value}>{children}</ReportContext.Provider>;
};

export function useReportData() {
  const value = useContext(ReportContext);
  if (!value) throw new Error('Financial analysis requires a ReportDataProvider');
  return value;
}
