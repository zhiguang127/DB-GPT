"""Bounded local background runs. No uploaded code or client paths are executed."""

import hashlib
import json
import logging
import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from dbgpt_serve.session_file.api.endpoints import SessionFileApiError
from dbgpt_serve.session_file.domain import FileScope

from .models import FinancialRunEntity as Run
from .report import build_report

logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc).isoformat()


class FinancialAnalysisService:
    """Single-process local runner with durable completion and restart recovery.

    Uses the registry's own DB/session factory and owner-scoped materialization.
    The PDF is opened inside the worker and stays alive until extraction exits.
    """

    def __init__(self, registry, *, extractor=None):
        self.registry = registry
        self.session = registry.dao.session
        self.extractor = extractor or self._extract
        self._lock = threading.Lock()
        self._slots = threading.BoundedSemaphore(4)
        self._preview_slots = threading.BoundedSemaphore(2)
        self._executor = ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="financial"
        )
        with self.session(commit=False) as session:
            engine = session.get_bind()
        Run.__table__.create(bind=engine, checkfirst=True)
        # This runner is intentionally for one local server process. Completed
        # snapshots survive restart; abandoned jobs are never left running.
        with self.session() as session:
            session.query(Run).filter(Run.status.in_(["pending", "running"])).update(
                {
                    Run.status: "failed",
                    Run.error: "服务重启，任务已中断，请重新分析。",
                    Run.updated_at: now(),
                    Run.completed_at: now(),
                },
                synchronize_session=False,
            )

    @staticmethod
    def _public(row):
        return {
            key: getattr(row, key)
            for key in [
                "id",
                "session_id",
                "file_id",
                "status",
                "stage",
                "created_at",
                "updated_at",
                "completed_at",
                "error",
            ]
        }

    def get(self, owner, session_id, run_id, *, report=False):
        with self.session(commit=False) as session:
            row = (
                session.query(Run)
                .filter_by(id=run_id, owner_id=owner, session_id=session_id)
                .first()
            )
            if row is None:
                raise SessionFileApiError(404, "RUN_NOT_FOUND", "未找到分析任务。")
            if report:
                if row.status != "completed" or not row.report_json:
                    raise SessionFileApiError(409, "REPORT_NOT_READY", "报告尚未完成。")
                return json.loads(row.report_json)
            return self._public(row)

    def create(self, owner, session_id, file_id, run_id):
        with self._lock:
            # Idempotent request IDs prevent a retry/double click from queuing
            # the same file twice. A new ID explicitly creates another attempt.
            with self.session(commit=False) as session:
                existing = session.query(Run).filter_by(id=run_id).first()
                if existing is not None:
                    if (existing.owner_id, existing.session_id, existing.file_id) != (
                        owner,
                        session_id,
                        file_id,
                    ):
                        raise SessionFileApiError(
                            409, "RUN_ID_CONFLICT", "任务标识不可复用。"
                        )
                    return self._public(existing)
            record = self.registry.get_file(
                owner_id=owner, session_id=session_id, file_id=file_id
            )
            if record is None:
                raise SessionFileApiError(
                    404, "FILE_NOT_FOUND", "未找到当前会话的文件。"
                )
            if not record.display_name.lower().endswith(".pdf"):
                raise SessionFileApiError(400, "PDF_REQUIRED", "请上传 PDF 年度报告。")
            if not self._slots.acquire(blocking=False):
                raise SessionFileApiError(
                    429, "RUN_QUEUE_FULL", "分析任务较多，请稍后重试。"
                )
            try:
                stamp = now()
                with self.session() as session:
                    row = Run(
                        id=run_id,
                        owner_id=owner,
                        session_id=session_id,
                        file_id=file_id,
                        status="pending",
                        stage="queued",
                        created_at=stamp,
                        updated_at=stamp,
                    )
                    session.add(row)
                    session.flush()
                    result = self._public(row)
                self._executor.submit(self._work, owner, session_id, file_id, run_id)
            except Exception:
                self._slots.release()
                self._update(
                    run_id,
                    status="failed",
                    error="无法启动分析任务，请重试。",
                    completed_at=now(),
                )
                raise
            return result

    def _update(self, run_id, **values):
        with self.session() as session:
            session.query(Run).filter_by(id=run_id).update(
                dict(values, updated_at=now()), synchronize_session=False
            )

    def _work(self, owner, session_id, file_id, run_id):
        try:
            self._update(run_id, status="running", stage="extract")
            opened = self.registry.open_download(
                owner_id=owner, session_id=session_id, file_id=file_id
            )
            if opened is None:
                raise ValueError("上传文件已不可用，请重新上传。")
            stream, record = opened
            try:
                scope = FileScope(owner_id=owner, session_id=session_id)
                with self.registry.materialize_local_file(
                    scope, stream, ".pdf"
                ) as path:
                    extracted = self.extractor(path)
            finally:
                stream.close()
            if extracted.get("document", {}).get("sha256") != record.sha256:
                raise ValueError("解析文件与上传文件不一致，任务已停止。")
            self._update(run_id, stage="calculate")
            completed_at = now()
            report = build_report(
                extracted, {"id": run_id, "completed_at": completed_at}, record
            )
            self._update(run_id, stage="save")
            # Status and snapshot become visible in the same transaction.
            self._update(
                run_id,
                status="completed",
                stage="completed",
                completed_at=completed_at,
                report_json=json.dumps(report, ensure_ascii=False, allow_nan=False),
            )
        except subprocess.TimeoutExpired:
            self._update(
                run_id,
                status="failed",
                error="PDF 解析超过 120 秒，请检查文件或缩小报告范围。",
                completed_at=now(),
            )
        except ValueError as exc:
            self._update(run_id, status="failed", error=str(exc), completed_at=now())
        except Exception:
            logger.exception("Financial analysis run %s failed", run_id)
            self._update(
                run_id,
                status="failed",
                error="财报处理失败，请检查文件后重新分析。",
                completed_at=now(),
            )
        finally:
            self._slots.release()

    @staticmethod
    def _extract(path):
        from dbgpt.configs.model_config import SKILLS_DIR

        script = (
            Path(SKILLS_DIR) / "financial-report-analyzer/scripts/extract_financials.py"
        )
        if not script.is_file():
            raise ValueError("财报提取脚本未安装，请检查 DBGPT_SKILLS_DIR 配置。")
        completed = subprocess.run(
            [sys.executable, str(script), json.dumps({"file_path": str(path)})],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if completed.returncode:
            raise ValueError("PDF 解析失败，文件可能损坏、加密或格式不受支持。")
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("提取脚本返回格式无效。") from exc
        if not isinstance(result, dict) or result.get("error"):
            raise ValueError("PDF 提取未成功，请检查文件。")
        return result

    def open_source(self, owner, session_id, run_id, document_id):
        report = self.get(owner, session_id, run_id, report=True)
        document = next(
            (d for d in report["documents"] if d["id"] == document_id), None
        )
        run = self.get(owner, session_id, run_id)
        if not document or document.get("fileId") != run["file_id"]:
            raise SessionFileApiError(
                404, "SOURCE_NOT_FOUND", "未找到此报告的来源文件。"
            )
        opened = self.registry.open_download(
            owner_id=owner, session_id=session_id, file_id=document["fileId"]
        )
        if opened is None:
            raise SessionFileApiError(
                404, "SOURCE_NOT_FOUND", "原文件已不可用；已保存的摘录仍可查看。"
            )
        stream, record = opened
        if record.sha256 != document.get("sha256"):
            stream.close()
            raise SessionFileApiError(
                409, "SOURCE_CHANGED", "来源文件与报告快照不一致。"
            )
        return stream, record, document

    def render_source_page(self, owner, session_id, run_id, document_id, page_number):
        stream, record, document = self.open_source(
            owner, session_id, run_id, document_id
        )
        try:
            if not 1 <= page_number <= document.get("pageCount", 0):
                raise SessionFileApiError(
                    404, "PAGE_NOT_FOUND", "PDF 物理页码超出范围。"
                )
            if not self._preview_slots.acquire(blocking=False):
                raise SessionFileApiError(
                    429, "PREVIEW_BUSY", "页面正在加载，请稍后重试。"
                )
            try:
                scope = FileScope(owner_id=owner, session_id=session_id)
                with self.registry.materialize_local_file(
                    scope, stream, ".pdf"
                ) as path:
                    if hashlib.sha256(path.read_bytes()).hexdigest() != record.sha256:
                        raise SessionFileApiError(
                            409, "SOURCE_CHANGED", "来源文件内容校验失败。"
                        )
                    completed = subprocess.run(
                        [
                            sys.executable,
                            str(Path(__file__).with_name("render_pdf.py")),
                            str(path),
                            str(page_number),
                        ],
                        capture_output=True,
                        timeout=20,
                        creationflags=subprocess.CREATE_NO_WINDOW
                        if os.name == "nt"
                        else 0,
                    )
                    if completed.returncode == 2:
                        raise SessionFileApiError(
                            404, "PAGE_NOT_FOUND", "PDF 物理页码超出范围。"
                        )
                    if completed.returncode or not completed.stdout.startswith(
                        b"\x89PNG\r\n\x1a\n"
                    ):
                        raise SessionFileApiError(
                            422, "PREVIEW_FAILED", "此页无法预览，请下载原 PDF 核对。"
                        )
                    return completed.stdout
            except subprocess.TimeoutExpired as exc:
                raise SessionFileApiError(
                    504, "PREVIEW_TIMEOUT", "页面渲染超时，请重试或下载原 PDF。"
                ) from exc
            finally:
                self._preview_slots.release()
        finally:
            stream.close()

    def close(self):
        self._executor.shutdown(wait=True)
