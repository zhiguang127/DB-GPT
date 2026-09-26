import { Alert, Button, InputNumber, Space, Spin } from 'antd';
import React, { useEffect, useState } from 'react';
import type { EvidenceExcerpt, SourceDocument, SourcePreviewAccess } from './types';

export const evidencePages = (evidence: EvidenceExcerpt) =>
  [...new Set([evidence.page, evidence.headerPage, evidence.unitPage])].filter(
    (page): page is number => page !== undefined && Number.isInteger(page) && page > 0,
  );

const PdfPagePreview: React.FC<{
  evidence: EvidenceExcerpt;
  document: SourceDocument;
  access: SourcePreviewAccess;
}> = ({ evidence, document, access }) => {
  const [page, setPage] = useState(evidence.page);
  const [image, setImage] = useState<{ page: number; url: string } | null>(null);
  const [error, setError] = useState('');
  const [downloadError, setDownloadError] = useState('');
  const [downloading, setDownloading] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let url: string | undefined;
    setImage(null);
    setError('');
    access
      .loadPage(document.id, page, controller.signal)
      .then(blob => {
        if (controller.signal.aborted) return;
        url = URL.createObjectURL(blob);
        setImage({ page, url });
      })
      .catch(cause => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : '页面加载失败');
      });
    return () => {
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [access, document.id, page, retry]);

  const download = async () => {
    setDownloading(true);
    setDownloadError('');
    try {
      await access.download(document);
    } catch (cause) {
      setDownloadError(cause instanceof Error ? cause.message : '下载失败');
    } finally {
      setDownloading(false);
    }
  };
  return (
    <section aria-label='原始 PDF 页面'>
      <Space wrap className='mb-3'>
        <Button disabled={page <= 1} onClick={() => setPage(value => value - 1)}>
          上一页
        </Button>
        <label>
          物理页码{' '}
          <InputNumber
            aria-label='PDF 物理页码'
            min={1}
            max={document.pageCount}
            precision={0}
            value={page}
            onChange={value => {
              if (
                value !== null &&
                Number.isInteger(value) &&
                value >= 1 &&
                (!document.pageCount || value <= document.pageCount)
              )
                setPage(value);
            }}
          />
        </label>
        <span>/ {document.pageCount ?? '未知'} 页</span>
        <Button
          disabled={!document.pageCount || page >= document.pageCount}
          onClick={() => setPage(value => value + 1)}
        >
          下一页
        </Button>
        <Button loading={downloading} onClick={() => void download()}>
          下载原 PDF
        </Button>
      </Space>
      <p>原 PDF 页面图像 · 从第 1 页开始计数，可能与报告印刷页码不同。</p>
      <Space wrap className='mb-3'>
        {evidencePages(evidence).map(target => (
          <Button key={target} size='small' onClick={() => setPage(target)}>
            {target === evidence.page ? '指标所在页' : target === evidence.headerPage ? '表头所在页' : '单位所在页'}{' '}
            {target}
          </Button>
        ))}
      </Space>
      {downloadError && <Alert type='error' message={downloadError} />}
      {error ? (
        <Alert
          type='warning'
          message={error}
          description={`来源：${document.fileName}，物理第 ${page} 页。下方摘录仍可核对。`}
          action={<Button onClick={() => setRetry(value => value + 1)}>重试</Button>}
        />
      ) : image?.page === page ? (
        // Original PDF raster, not an optimized remote web image.
        <img
          src={image.url}
          alt={`${document.fileName} · PDF 物理第 ${page} 页`}
          style={{ width: '100%', height: 'auto' }}
          onError={() => setError('页面图像加载失败，请重试或下载原 PDF。')}
        />
      ) : (
        <div role='status' className='p-8'>
          <Spin /> 正在加载物理第 {page} 页
        </div>
      )}
    </section>
  );
};
export default PdfPagePreview;
