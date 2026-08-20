"""SSE adapter for running financial research through the chat UI."""

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List

from dbgpt.configs.model_config import PILOT_PATH
from dbgpt.core import StorageConversation
from dbgpt_app.openapi.api_v1.react_final import AgentCitation, AgentFinalAnswer
from dbgpt_serve.conversation.serve import Serve as ConversationServe

from ..agent import FinancialResearchAgent
from ..domain.models import ResearchRequest, StageStatus
from .routing import financial_file_paths

logger = logging.getLogger(__name__)

STAGE_TITLES = {
    "initialize": "建立研究任务",
    "parse": "解析财报",
    "extract": "抽取指标与证据",
    "normalize": "统一指标口径",
    "derive": "计算派生指标",
    "validate": "校验和复算",
    "cross_check": "交叉核对表格识别",
    "detect_anomalies": "发现需要解释的异常",
    "investigate_earnings": "调查利润变化与核心盈利",
    "investigate_cash": "调查经营现金流变化",
    "investigate_capital": "调查资本回报与资产占用",
    "investigate_notes": "调查附注披露明细",
    "review_disclosures": "审阅审计与披露约束",
    "analyze_peers": "执行公司横向比较",
    "verify_findings": "验证研究结论",
    "analyze": "形成研究结论",
    "narrate": "生成受约束的结论叙述",
    "visualize": "生成图表",
    "render": "生成引用报告",
    "complete": "完成研究任务",
    # Persisted MVP jobs can still replay these historical stages.
    "analyze_growth": "研究增长质量",
    "analyze_profitability": "研究盈利能力",
    "analyze_cash_quality": "研究现金含量",
    "analyze_efficiency": "研究运营效率",
    "analyze_solvency": "研究偿债与财务结构",
    "analyze_segments": "研究业务与地区结构",
    "assess_risks": "扫描风险与异常",
}


def _sse_event(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _request_flag(ext_info: Dict[str, Any], key: str) -> bool:
    value = ext_info.get(key, False)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _terminal_events(
    storage_conv: Any,
    history_payload: str,
    final_answer: AgentFinalAnswer,
) -> tuple[str, str]:
    try:
        storage_conv.add_view_message(history_payload)
        storage_conv.end_current_round()
        storage_conv.save_to_storage()
    except Exception:
        logger.exception("Failed to persist financial research history")
    return (
        _sse_event(final_answer.to_sse_payload()),
        _sse_event({"type": "done"}),
    )


async def stream_financial_research(
    dialogue: Any, system_app: Any
) -> AsyncGenerator[str, None]:
    """Run the controlled workflow and adapt its progress to the chat protocol."""
    conv_id = dialogue.conv_uid or str(uuid.uuid4())
    conversation_serve = ConversationServe.get_instance(system_app)
    storage_conv = StorageConversation(
        conv_uid=conv_id,
        chat_mode=dialogue.chat_mode or "chat_react_agent",
        user_name=dialogue.user_name,
        sys_code=dialogue.sys_code,
        summary=dialogue.user_input,
        app_code=dialogue.app_code,
        conv_storage=conversation_serve.conv_storage,
        message_storage=conversation_serve.message_storage,
    )
    storage_conv.save_to_storage()
    storage_conv.start_new_round()
    storage_conv.add_user_message(str(dialogue.user_input or ""))

    ext_info = dialogue.ext_info if isinstance(dialogue.ext_info, dict) else {}
    request = ResearchRequest(
        file_paths=financial_file_paths(dialogue),
        question=str(dialogue.user_input or ""),
        output_dir=os.path.join(PILOT_PATH, "tmp", conv_id, "financial_research"),
        locale=str(ext_info.get("locale") or "zh_CN"),
        enable_ocr=_request_flag(ext_info, "enable_ocr"),
        enable_narration=_request_flag(ext_info, "enable_narration"),
    )
    event_queue: "asyncio.Queue[Any]" = asyncio.Queue()

    async def on_progress(event: Any, _state: Any) -> None:
        await event_queue.put(event)

    task = asyncio.create_task(FinancialResearchAgent().run(request, on_progress))
    history_steps: List[Dict[str, Any]] = []
    running_steps: Dict[str, Dict[str, Any]] = {}
    step_ids: Dict[str, str] = {}
    step_number = 0
    try:
        while not task.done() or not event_queue.empty():
            try:
                event = await asyncio.wait_for(event_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            stage = event.stage.value
            if event.status == StageStatus.STARTED:
                step_number += 1
                step_id = f"financial-step-{step_number}"
                step_ids[stage] = step_id
                running_steps[stage] = {
                    "id": step_id,
                    "title": STAGE_TITLES.get(stage, stage),
                    "detail": event.message,
                    "phase": "财报研究",
                    "thought": None,
                    "action": f"financial_{stage}",
                    "action_input": None,
                    "outputs": [],
                    "status": "running",
                }
                yield _sse_event(
                    {
                        "type": "step.start",
                        "step": step_number,
                        "id": step_id,
                        "title": STAGE_TITLES.get(stage, stage),
                        "detail": event.message,
                        "phase": "财报研究",
                    }
                )
                continue

            completed_step_id = step_ids.get(stage)
            if not completed_step_id:
                continue
            status = "failed" if event.status == StageStatus.FAILED else "done"
            yield _sse_event(
                {
                    "type": "step.chunk",
                    "id": completed_step_id,
                    "output_type": "text",
                    "content": event.message,
                }
            )
            yield _sse_event(
                {"type": "step.done", "id": completed_step_id, "status": status}
            )
            history_step = running_steps.pop(stage)
            history_step["outputs"].append(
                {"output_type": "text", "content": event.message}
            )
            history_step["status"] = status
            history_steps.append(history_step)

        state = await task
        if not state.report:
            raise RuntimeError("财报研究已结束，但没有生成 HTML 报告。")

        html_content = Path(state.report.path).read_text(encoding="utf-8")
        step_number += 1
        artifact_step_id = f"financial-step-{step_number}"
        artifact_content = {
            "title": state.report.title,
            "html": html_content,
            "file_path": state.report.path,
        }
        yield _sse_event(
            {
                "type": "step.start",
                "step": step_number,
                "id": artifact_step_id,
                "title": "可追溯研究报告",
                "detail": "HTML 报告已生成",
                "phase": "交付成果",
            }
        )
        yield _sse_event(
            {
                "type": "step.chunk",
                "id": artifact_step_id,
                "output_type": "html",
                "content": artifact_content,
            }
        )
        yield _sse_event(
            {"type": "step.done", "id": artifact_step_id, "status": "done"}
        )
        history_steps.append(
            {
                "id": artifact_step_id,
                "title": "可追溯研究报告",
                "detail": "HTML 报告已生成",
                "phase": "交付成果",
                "thought": None,
                "action": "financial_report",
                "action_input": None,
                "outputs": [{"output_type": "html", "content": artifact_content}],
                "status": "done",
            }
        )

        sources = {source.id: source for source in state.sources}
        citations = tuple(
            AgentCitation(
                index=index,
                id=evidence.id,
                source_name=(
                    f"{sources[evidence.source_id].display_name}"
                    f"（PDF 第 {evidence.page_number} 页）"
                ),
                excerpt=evidence.quote,
                path=sources[evidence.source_id].location,
            )
            for index, evidence in enumerate(state.evidence[:10], start=1)
        )
        companies = sorted({metric.company_name for metric in state.metrics})
        subject = (
            f"{len(companies)} 家公司"
            if len(companies) > 1
            else (companies[0] if companies else "该公司")
        )
        top_findings = state.analysis.get("top_findings", [])[:5]
        finding_summary = "\n".join(
            f"{index}. {finding['title']}：{finding['summary']}"
            for index, finding in enumerate(top_findings, start=1)
        )
        final_answer = AgentFinalAnswer(
            content=(
                f"已完成 {subject} 的财报调查。\n\n"
                f"核心结论：\n{finding_summary or '当前资料不足以形成核心结论。'}\n\n"
                "利润与现金流驱动、未决问题及来源证据见研究报告。"
            ),
            citations=citations,
        )
    except Exception as exc:
        logger.exception("Financial research agent failed")
        final_answer = AgentFinalAnswer(content=f"财报研究执行失败：{exc}")
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    history_payload = json.dumps(
        {
            "version": 1,
            "protocol_version": 2,
            "type": "react-agent",
            "agent_mode": "financial-research",
            "final_content": final_answer.content,
            "citations": [citation.to_dict() for citation in final_answer.citations],
            "steps": history_steps,
            "task_plan": [],
            "generated_images": [],
            "sub_agents": {},
        },
        ensure_ascii=False,
    )
    for terminal_event in _terminal_events(storage_conv, history_payload, final_answer):
        yield terminal_event
