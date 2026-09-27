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

from .analysis import SECTIONS, InvalidFindings, apply_findings, validate_findings
from .models import FinancialRunEntity as Run
from .questions import question_context, reference_only_answer, validate_answer
from .report import build_report

logger = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc).isoformat()


class FinancialAnalysisService:
    """Single-process local runner with durable completion and restart recovery.

    Uses the registry's own DB/session factory and owner-scoped materialization.
    The PDF is opened inside the worker and stays alive until extraction exits.
    """

    def __init__(self, registry, *, extractor=None, analyzer=None, answerer=None):
        self.registry = registry
        self.session = registry.dao.session
        self.extractor = extractor or self._extract
        self.analyzer = analyzer
        self.answerer = answerer
        self._question_slots = threading.BoundedSemaphore(2)
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
            # Data snapshots are committed before model work. Preserve them if
            # the process exited during analysis; do not leave a perpetual spinner.
            for row in session.query(Run).filter_by(
                status="completed", stage="analyze"
            ):
                report = json.loads(row.report_json)
                self._finish_report_analysis(
                    report, "failed", "服务重启，模型分析已中断；财务数据仍可查看。"
                )
                row.report_json = json.dumps(
                    report, ensure_ascii=False, allow_nan=False
                )
                row.stage, row.updated_at = "completed", now()

    @staticmethod
    def _public(row):
        result = {
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
        result["report_ready"] = bool(row.report_json)
        result["analysis_status"] = (
            json.loads(row.report_json).get("analysis", {}).get("status")
            if row.report_json
            else None
        )
        return result

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

    def ask(self, owner, session_id, run_id, revision, question):
        report = self.get(owner, session_id, run_id, report=True)
        if report["revision"] != revision:
            raise SessionFileApiError(
                409, "REPORT_CHANGED", "报告已更新，请刷新后重新提问。"
            )
        answerer = self.answerer
        if answerer is None:
            raise SessionFileApiError(
                503, "QUESTIONS_UNAVAILABLE", "追问服务尚未就绪，请稍后重试。"
            )
        if not self._question_slots.acquire(blocking=False):
            raise SessionFileApiError(
                429, "QUESTIONS_BUSY", "追问请求较多，请稍后重试。"
            )
        try:
            try:
                context = question_context(report, question)
                raw = answerer(report, question, owner, session_id)
                try:
                    answer = validate_answer(raw, context, report)
                    answer["answerMode"] = (
                        "insufficient" if not answer["citations"] else "validated"
                    )
                except ValueError:
                    answer = reference_only_answer(raw, context, report)
            except TimeoutError as exc:
                raise SessionFileApiError(
                    504, "QUESTION_TIMEOUT", "回答超时，请稍后重新发送问题。"
                ) from exc
            except ValueError as exc:
                raise SessionFileApiError(
                    502, "ANSWER_INVALID", "回答未通过数字或引用校验，请重新提问。"
                ) from exc
            except Exception as exc:
                raise SessionFileApiError(
                    503, "QUESTIONS_UNAVAILABLE", "追问暂不可用，请稍后重试。"
                ) from exc
            if self.get(owner, session_id, run_id, report=True)["revision"] != revision:
                raise SessionFileApiError(
                    409, "REPORT_CHANGED", "报告已更新，请刷新后重新提问。"
                )
            return dict(
                answer,
                runId=run_id,
                revision=revision,
                question=question,
                modelName=answerer.model,
            )
        finally:
            self._question_slots.release()

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
            analyzer = self.analyzer
            if analyzer is not None:
                report["analysis"] = {
                    "status": "running",
                    "modelName": analyzer.model,
                    "startedAt": now(),
                    "completedAt": None,
                    "error": None,
                    "rejectedCount": 0,
                }
                report["report"]["run"]["modelName"] = analyzer.model
                report["steps"].append(
                    {
                        "id": "analyze",
                        "order": len(report["steps"]) + 1,
                        "type": "analysis",
                        "title": "生成并校验模型分析",
                        "detail": "财务数据已保存，正在基于引用生成分析。",
                        "status": "running",
                        "capability": "existing",
                    }
                )
                report["agent"]["groups"].append(
                    {
                        "id": "analysis",
                        "title": "模型分析",
                        "stepIds": ["analyze"],
                        "content": "基于已保存事实和计算，生成并校验引用。",
                    }
                )
            self._update(run_id, stage="save")
            # Status and snapshot become visible in the same transaction.
            self._update(
                run_id,
                status="completed",
                stage="analyze" if analyzer is not None else "completed",
                completed_at=completed_at,
                report_json=json.dumps(report, ensure_ascii=False, allow_nan=False),
            )
            if analyzer is not None:
                self._analyze(run_id, report, analyzer, owner, session_id)
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
    def _finish_report_analysis(report, status, error=None, rejected=0):
        report["analysis"].update(
            status=status,
            error=error,
            completedAt=now(),
            rejectedCount=rejected,
        )
        report["revision"] = report["report"]["run"]["id"] + "-analysis-final"
        step = next(s for s in report["steps"] if s["id"] == "analyze")
        step["status"] = "failed" if status == "failed" else "completed"
        step["detail"] = error or (
            f"已保留 {len(report['findings'])} 条引用校验通过的分析；"
            f"{rejected} 条未通过校验。结论仍需人工核对。"
        )
        report["agent"]["summary"] = "财务事实、计算和原文已保存。\n\n" + step["detail"]

    def _analyze(self, run_id, report, analyzer, owner, session_id):
        # Catch model/validation failures here, separately from data processing.
        # Do not persist raw model output, provider errors, credentials or reasoning.
        rejected = 0
        try:
            raw = analyzer(report, owner, session_id)
            findings, rejected = validate_findings(raw, report)
            report = apply_findings(report, findings)
            covered = {f["sectionKey"] for f in findings}
            status = "partial" if rejected or covered != set(SECTIONS) else "completed"
            error = None
        except TimeoutError:
            status, error = "failed", "模型分析超时，财务数据和原文仍可查看。"
        except InvalidFindings as exc:
            rejected = exc.rejected_count
            logger.warning("Analysis rejected for run %s: %s", run_id, exc.issue_counts)
            status, error = "failed", "模型输出未通过数字或引用校验，财务数据仍可查看。"
        except ValueError:
            logger.warning("Analysis format invalid for run %s", run_id)
            status, error = (
                "failed",
                "模型输出未通过结构、数字或引用校验，财务数据仍可查看。",
            )
        except Exception:
            status, error = "failed", "模型分析暂不可用，财务数据和原文仍可查看。"
        self._finish_report_analysis(report, status, error, rejected)
        try:
            self._update(
                run_id,
                stage="completed",
                report_json=json.dumps(report, ensure_ascii=False, allow_nan=False),
            )
        except Exception:
            # The earlier data snapshot remains valid even if this write fails.
            logger.error("Could not persist analysis for run %s", run_id)

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
