import React, { useEffect, useRef, useState } from 'react';
import { useReportData } from './ReportDataContext';
import styles from './financial-analysis.module.css';
import type { FinancialExport, ReportExportAccess } from './types';

const ReportExports: React.FC<{ access: ReportExportAccess }> = ({ access }) => {
  const { data } = useReportData();
  const [files, setFiles] = useState<FinancialExport[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const gate = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    const controller = new AbortController();
    access
      .list(controller.signal)
      .then(value => {
        if (!controller.signal.aborted)
          setFiles(previous => [...previous, ...value.filter(item => !previous.some(saved => saved.id === item.id))]);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError('导出文件列表读取失败。');
      });
    return () => {
      mounted.current = false;
      controller.abort();
    };
  }, [access]);
  const download = async (format?: 'json' | 'html', file?: FinancialExport) => {
    if (gate.current) return;
    gate.current = true;
    setBusy(true);
    setError('');
    try {
      const generated = file || (await access.create(format!, data.revision));
      if (!mounted.current) return;
      setFiles(previous => [generated, ...previous.filter(item => item.id !== generated.id)]);
      await access.download(generated);
    } catch (cause) {
      if (mounted.current) setError(cause instanceof Error ? cause.message : '导出失败，请重试。');
    } finally {
      gate.current = false;
      if (mounted.current) setBusy(false);
    }
  };
  return (
    <>
      <p className={styles.meta}>
        <button
          type='button'
          className={styles.textLink}
          disabled={busy || data.analysis?.status === 'running'}
          onClick={() => void download('json')}
        >
          导出 JSON
        </button>
        {' · '}
        <button
          type='button'
          className={styles.textLink}
          disabled={busy || data.analysis?.status === 'running'}
          onClick={() => void download('html')}
        >
          导出 HTML
        </button>
        {busy && ' · 正在准备文件…'}
        {data.analysis?.status === 'running' && ' · 分析结束后可导出'}
      </p>
      {error && (
        <p role='status' className={styles.meta}>
          {error}
        </p>
      )}
      {files.map(file => (
        <div className={styles.fileRow} key={file.id}>
          <div>
            <strong>{file.file_name}</strong>
            <div className={styles.meta}>
              {(file.size_bytes / 1024).toFixed(1)} KB · {file.revision}
            </div>
          </div>
          <button
            type='button'
            className={styles.textLink}
            disabled={busy}
            onClick={() => void download(undefined, file)}
          >
            下载 →
          </button>
        </div>
      ))}
    </>
  );
};
export default ReportExports;
