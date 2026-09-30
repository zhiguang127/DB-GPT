"""Financial report tools owned by the current conversational agent turn."""

import asyncio
import json
from pathlib import Path
from uuid import uuid4

from dbgpt.agent.resource.tool.base import tool
from dbgpt_serve.financial_analysis.analysis import (
    REFERENCE,
    SYSTEM_PROMPT,
    InvalidFindings,
    model_context,
)
from dbgpt_serve.financial_analysis.questions import (
    reference_only_answer,
    validate_answer,
)

# Reuse the validation rules, not the standalone analyzer's "do not call tools"
# and "return only JSON" instructions. Here the active agent must publish.
PUBLICATION_RULES = (
    "下一步必须在本轮调用 publish_financial_report，不能 terminate 描述下一步计划。"
    "用工具参数 findings 提交结构化发现，通常四条，证据不足可以减少或传空数组。"
    "section 可为 overview、profitability、cashflow、balance。\n"
    + SYSTEM_PROMPT[SYSTEM_PROMPT.index("每条发现字段") :]
)

FINANCIAL_AGENT_PROMPT = """
## 财报分析与当前对话中的报告
分析年度报告时，先加载 financial-report-analyzer 技能，并使用
prepare_financial_report 提取和计算，然后由你根据返回的事实与计算撰写结论，
调用 publish_financial_report 校验并展示。财报使用这两个工具生成结构化报告，
不使用 html_interpreter、旧 HTML 模板或自行编写网页来替代财报组件。
工具返回的财报已显示在当前对话右侧，不要让用户跳转 /financial-analysis。
后续追问先调用 read_financial_report 读取当前对话的报告，不重复提取 PDF，
只引用已有事实、计算及原文，缺少数据就明确说明，不自行计算新指标或补造原因。
发布后用简短摘要完成回答，保留“部分分析”和待核对信息。
"""


def _service():
    from dbgpt._private.config import Config
    from dbgpt_serve.session_file.serve import SessionFileServe

    component = Config().SYSTEM_APP.get_component(
        SessionFileServe.name, SessionFileServe
    )
    return component.financial_analysis


async def financial_completion_error(state, *, service=None):
    """Require publication and a fresh scoped read before accepting a final answer."""
    if state.get("financial_pending"):
        return (
            "财务数据已提取，但你尚未发布分析。请在本轮调用 "
            "publish_financial_report 提交 findings，再完成回答。"
            "不要用未来计划代替执行；证据不足可以提交空 findings 数组。"
        )
    if state.get("financial_report_context"):
        return None
    from dbgpt_serve.session_file.api.endpoints import SessionFileApiError

    try:
        await asyncio.to_thread(
            (service or _service()).latest_agent_report,
            state["owner_id"],
            state["conv_id"],
        )
    except SessionFileApiError as exc:
        if exc.err_code == "REPORT_NOT_FOUND":
            return None
        raise
    return (
        "当前对话已有财报。请先调用 read_financial_report 读取已保存的真实数据，"
        "再依据本轮工具结果回答。不能直接复用聊天历史里的数字或页码。"
    )


def _artifact(report, session_id):
    return {
        "output_type": "html",
        "content": {
            "kind": "financial-report",
            "title": report["report"]["companyName"] + "财报分析",
            "runId": report["report"]["run"]["id"],
            "sessionId": session_id,
            "revision": report["revision"],
        },
    }


def _result(report, session_id, *, include_context=False, reading=False):
    summary = {
        "run_id": report["report"]["run"]["id"],
        "revision": report["revision"],
        "analysis": report.get("analysis"),
        "findings": report["findings"],
    }
    if include_context:
        summary["data"] = model_context(report)
        if reading:
            summary["answer_instructions"] = (
                "直接回答当前追问，无需重新发布报告。数字使用 {{fact:真实ID}} 或 "
                "{{calculation:真实ID}} 占位符，服务端会替换真实值。"
                "不要直接写年份、金额、比率或页码，也不要追加单位。"
                "可提示用户在右侧报告查看依据；来源页码由服务端补齐。"
                "资料不足明确说明，不补造原因。"
            )
        else:
            summary["publication_instructions"] = PUBLICATION_RULES
    return json.dumps(
        {
            "chunks": [
                _artifact(report, session_id),
                {
                    "output_type": "text",
                    "content": json.dumps(summary, ensure_ascii=False),
                },
            ]
        },
        ensure_ascii=False,
    )


def finalize_financial_answer(content, state):
    """Render/validate agent references before both SSE final and history save."""
    report = state.get("financial_report_context")
    if not report:
        return content
    if not state.get("financial_read"):
        # The narrative lives in validated findings. Completion text reflects
        # persisted status, rather than an unvalidated claim of full coverage.
        partial = report.get("analysis", {}).get("status") != "completed"
        return (
            ("当前为部分分析。" if partial else "分析已完成。")
            + report["agent"]["summary"]
            + "\n\n报告已在当前对话右侧展示，可查看数据、原文依据与下载。"
        )
    references = set(REFERENCE.findall(content))
    raw = json.dumps(
        {
            "answer": content,
            "factIds": [ref for kind, ref in references if kind == "fact"],
            "calculationIds": [
                ref for kind, ref in references if kind == "calculation"
            ],
            "evidenceExcerptIds": [],
            "insufficientEvidence": not references,
        },
        ensure_ascii=False,
    )
    context = model_context(report)
    try:
        answer = validate_answer(raw, context, report)
    except ValueError:
        try:
            answer = reference_only_answer(raw, context, report)
        except ValueError:
            return "回答未通过数字或引用校验，请在右侧报告查看依据或重新提问。"
    pages = sorted(
        {
            e["page"]
            for e in report["evidence"]
            if e["id"] in answer["evidenceExcerptIds"]
        }
    )
    suffix = (
        (
            "\n\n来源：原 PDF 物理第 "
            + "、".join(map(str, pages))
            + " 页，可在右侧报告的证据中查看原文。"
        )
        if pages
        else ""
    )
    return answer["answer"] + suffix


def make_financial_tools(state, *, service=None):
    """Bind owner/session to trusted turn state, never to model arguments."""

    def scope():
        owner, session_id = state.get("owner_id"), state.get("conv_id")
        if not owner or not session_id:
            raise ValueError("当前对话身份尚未就绪。")
        return service or _service(), owner, session_id

    @tool(
        description=(
            "提取当前对话 PDF 年报并执行确定性财务计算。"
            "返回原文引用、数字和待分析报告。"
            "你必须随后用 publish_financial_report 提交自己的结构化结论。"
            "file_id 可省略（仅一个 PDF 时）；多文件时必须指定当前附件的 file_id。"
        )
    )
    async def prepare_financial_report(file_id: str = "") -> str:
        backend, owner, session_id = scope()
        manifests = state.get("session_files", [])
        if manifests:
            candidates = [m for m in manifests if m.name.lower().endswith(".pdf")]
            if file_id:
                candidates = [m for m in candidates if m.file_id == file_id]
            if len(candidates) != 1:
                raise ValueError("请选择当前附件中的一份 PDF 年报。")
            selected_id = candidates[0].file_id
        else:
            if file_id:
                raise ValueError(
                    "当前选择的是首页示例文件，没有 file_id。"
                    "请省略 file_id，直接以空参数调用 prepare_financial_report。"
                )
            if not state.get("file_path"):
                raise ValueError("请先在当前对话上传或选择一份 PDF 年报。")
            # Legacy homepage examples are revalidated and registered durably;
            # no model-supplied path is accepted by this tool.
            selected_id = state.get("financial_legacy_file_id")
            if not selected_id:
                from dbgpt_app.openapi.api_v1.agentic_data_api import (
                    _legacy_upload_base_dir,
                )
                from dbgpt_app.openapi.api_v1.attachment_react_adapter import (
                    resolve_legacy_chat_file_path,
                )

                path = Path(
                    resolve_legacy_chat_file_path(
                        file_path=Path(state["file_path"]).as_posix(),
                        owner_id=owner,
                        base_dir=_legacy_upload_base_dir(),
                    )
                )
                if path.suffix.lower() != ".pdf":
                    raise ValueError("财报分析需要 PDF 年度报告。")

                def register():
                    with path.open("rb") as stream:
                        return backend.registry.ingest(
                            owner_id=owner,
                            session_id=session_id,
                            display_name=path.name,
                            media_type="application/pdf",
                            stream=stream,
                            size_bytes=path.stat().st_size,
                        ).file_id

                selected_id = await asyncio.to_thread(register)
                state["financial_legacy_file_id"] = selected_id

        attempts = state.setdefault("financial_runs", {})
        run_id = attempts.setdefault(selected_id, str(uuid4()))
        await asyncio.to_thread(
            backend.create,
            owner,
            session_id,
            selected_id,
            run_id,
            agent_model=state.get("model_name") or "conversation-agent",
        )
        deadline = asyncio.get_running_loop().time() + 150
        while True:
            run = await asyncio.to_thread(backend.get, owner, session_id, run_id)
            if run["status"] == "failed":
                raise ValueError(run["error"] or "财报提取失败。")
            if run.get("report_ready"):
                report = await asyncio.to_thread(
                    backend.get, owner, session_id, run_id, report=True
                )
                if report.get("analysis", {}).get("completedAt") is None:
                    state.setdefault("financial_pending", set()).add(run_id)
                state.update(financial_report_context=report, financial_read=False)
                return _result(report, session_id, include_context=True)
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("提取仍在后台执行，请稍后读取当前对话的报告。")
            await asyncio.sleep(0.3)

    @tool(
        description=(
            "提交当前智能体撰写的财报结论，校验数字和引用并在当前对话展示报告。"
            "参数 run_id、revision 来自 prepare_financial_report；"
            "findings 为结构化发现数组。"
            "使用 prepare 返回的占位符规则，不能提供 HTML 或修改事实。"
            "证据不足可传空数组保存数据报告；校验失败应修正后再提交。"
        )
    )
    async def publish_financial_report(
        run_id: str, revision: str, findings: list[dict]
    ) -> str:
        backend, owner, session_id = scope()
        try:
            report = await asyncio.to_thread(
                backend.publish_agent_report,
                owner,
                session_id,
                run_id,
                revision,
                findings,
            )
        except InvalidFindings as exc:
            return json.dumps(
                {
                    "chunks": [
                        {
                            "output_type": "text",
                            "content": "结论未通过校验，请修正引用和数字占位符后重试："
                            + json.dumps(exc.issue_counts),
                        }
                    ]
                },
                ensure_ascii=False,
            )
        state.setdefault("financial_pending", set()).discard(run_id)
        state.update(financial_report_context=report, financial_read=False)
        return _result(report, session_id)

    @tool(
        description=(
            "读取当前对话已保存的财报、真实数据及原文引用，用于继续追问或重新展示。"
            "run_id 可省略以读取当前对话最近报告；不能读取其他对话。"
        )
    )
    async def read_financial_report(run_id: str = "") -> str:
        backend, owner, session_id = scope()
        if run_id:
            report = await asyncio.to_thread(
                backend.get, owner, session_id, run_id, report=True
            )
        else:
            report = await asyncio.to_thread(
                backend.latest_agent_report, owner, session_id
            )
        state.update(financial_report_context=report, financial_read=True)
        return _result(report, session_id, include_context=True, reading=True)

    return [prepare_financial_report, publish_financial_report, read_financial_report]
