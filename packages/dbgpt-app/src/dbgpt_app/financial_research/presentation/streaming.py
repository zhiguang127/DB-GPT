"""SSE adapter for running financial research through the chat UI."""

import asyncio
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, Iterable, List, Sequence

from dbgpt.configs.model_config import PILOT_PATH
from dbgpt.core import StorageConversation
from dbgpt_app.openapi.api_v1.react_final import AgentCitation, AgentFinalAnswer
from dbgpt_serve.conversation.serve import Serve as ConversationServe

from ..agent import FinancialResearchAgent
from ..domain.models import ResearchMode, ResearchRequest, StageStatus
from ..domain.normalization import identified_company_names
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

# Domain stages remain deliberately fine-grained for checkpoints and audit.
# The chat UI should present meaningful research phases, not market every
# millisecond-scale deterministic function as an independent "task".
RESEARCH_PHASES = (
    ("prepare", ("initialize", "parse"), "资料准备", "建立来源并解析全部财报"),
    (
        "facts",
        ("extract", "normalize", "cross_check"),
        "事实底稿",
        "抽取指标、统一口径并交叉核对",
    ),
    (
        "audit",
        ("derive", "validate", "detect_anomalies", "assess_risks"),
        "计算与校验",
        "复算派生指标、隔离错误事实并识别异常",
    ),
    (
        "investigate",
        (
            "investigate_earnings",
            "investigate_cash",
            "investigate_capital",
            "investigate_notes",
            "analyze_peers",
            "review_disclosures",
            "analyze_growth",
            "analyze_profitability",
            "analyze_cash_quality",
            "analyze_efficiency",
            "analyze_solvency",
            "analyze_segments",
        ),
        "专题调查",
        "调查盈利、现金、资本、附注、同行与披露约束",
    ),
    (
        "conclude",
        ("verify_findings", "analyze", "narrate"),
        "结论形成",
        "验证证据链并形成完整研究结论",
    ),
    (
        "deliver",
        ("visualize", "render"),
        "报告交付",
        "生成图表与可追溯研究报告",
    ),
)

_PHASE_BY_STAGE = {
    stage: (key, title, description)
    for key, stages, title, description in RESEARCH_PHASES
    for stage in stages
}


def _sse_event(payload: Dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _request_flag(ext_info: Dict[str, Any], key: str) -> bool:
    value = ext_info.get(key, False)
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _plan_item_status(item: Any) -> str:
    raw_status = getattr(item, "status", "pending")
    return str(getattr(raw_status, "value", raw_status))


def _public_task_status(items: Sequence[Any]) -> str:
    statuses = [_plan_item_status(item) for item in items]
    if "failed" in statuses:
        # The task card has no failed state. ``cancelled`` keeps a failed phase
        # out of the active/done counts without falsely presenting it as done.
        return "cancelled"
    if statuses and all(status == "completed" for status in statuses):
        return "completed"
    if "running" in statuses or "completed" in statuses:
        return "in_progress"
    return "pending"


def _task_plan_snapshot(
    plan: Iterable[Any],
) -> tuple[List[Dict[str, str]], Dict[str, str]]:
    """Group audited domain stages into honest user-facing research phases."""

    items_by_stage: Dict[str, List[Any]] = {}
    for item in plan:
        raw_stage = getattr(item, "stage", "")
        stage = str(getattr(raw_stage, "value", raw_stage))
        items_by_stage.setdefault(stage, []).append(item)

    tasks: List[Dict[str, str]] = []
    phase_statuses: Dict[str, str] = {}
    grouped_stages: set[str] = set()
    for key, stages, title, description in RESEARCH_PHASES:
        phase_items = [
            item for stage in stages for item in items_by_stage.get(stage, [])
        ]
        if not phase_items:
            continue
        status = _public_task_status(phase_items)
        phase_statuses[key] = status
        grouped_stages.update(stage for stage in stages if stage in items_by_stage)
        tasks.append(
            {
                "content": f"{title}：{description}",
                "status": status,
                "priority": "medium",
            }
        )

    # Persisted plans from older versions may contain a stage unknown to the
    # current grouping. Keep it visible rather than silently dropping it.
    for stage, items in items_by_stage.items():
        if stage in grouped_stages:
            continue
        status = _public_task_status(items)
        key = f"stage:{stage}"
        phase_statuses[key] = status
        tasks.append(
            {
                "content": STAGE_TITLES.get(stage, stage),
                "status": status,
                "priority": "medium",
            }
        )
    return tasks, phase_statuses


def _task_plan_payload(plan: Iterable[Any]) -> List[Dict[str, str]]:
    """Return the grouped task card payload used by live and history views."""

    tasks, _ = _task_plan_snapshot(plan)
    return tasks


def _phase_for_stage(stage: str) -> tuple[str, str, str]:
    phase = _PHASE_BY_STAGE.get(stage)
    if phase:
        return phase
    title = STAGE_TITLES.get(stage, stage)
    return f"stage:{stage}", title, title


def _select_summary_evidence(
    evidence: Sequence[Any],
    findings: Sequence[Dict[str, Any]],
    limit: int = 10,
) -> List[Any]:
    """Prefer evidence cited by the chat headlines, then fill remaining slots."""
    if limit <= 0:
        return []
    by_id = {item.id: item for item in evidence}
    selected: List[Any] = []
    selected_ids: set[str] = set()

    def add(evidence_id: str) -> None:
        item = by_id.get(evidence_id)
        if item is None or evidence_id in selected_ids or len(selected) >= limit:
            return
        selected.append(item)
        selected_ids.add(evidence_id)

    for finding in findings:
        for evidence_id in finding.get("evidence_ids", []):
            add(evidence_id)
    for item in evidence:
        add(item.id)
    return selected


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
    # A single-slot queue applies backpressure to the deterministic workflow.
    # Without it, millisecond-scale stages can enqueue the whole plan before
    # the SSE generator gets a chance to flush even the first update, making
    # six sequential phases appear as one final batch in the browser.
    event_queue: "asyncio.Queue[Any]" = asyncio.Queue(maxsize=1)

    async def on_progress(event: Any, state: Any) -> None:
        # Serialize immediately: ``state`` is mutated in place by later stages.
        task_plan, phase_statuses = _task_plan_snapshot(state.plan)
        await event_queue.put((event, task_plan, phase_statuses))

    task = asyncio.create_task(FinancialResearchAgent().run(request, on_progress))
    history_steps: List[Dict[str, Any]] = []
    history_task_plan: List[Dict[str, str]] = []
    streamed_task_plan: List[Dict[str, str]] = []
    running_steps: Dict[str, Dict[str, Any]] = {}
    step_ids: Dict[str, str] = {}
    step_number = 0
    try:
        while not task.done() or not event_queue.empty():
            try:
                (
                    event,
                    current_task_plan,
                    current_phase_statuses,
                ) = await asyncio.wait_for(event_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                continue
            history_task_plan = current_task_plan
            if current_task_plan != streamed_task_plan:
                streamed_task_plan = current_task_plan
                yield _sse_event({"type": "plan.update", "tasks": current_task_plan})
            stage = event.stage.value
            phase_key, phase_title, phase_description = _phase_for_stage(stage)
            if event.status == StageStatus.STARTED:
                if phase_key in step_ids:
                    # Fine-grained stage starts remain in the phase output, but
                    # do not create another user-facing pseudo-task.
                    yield _sse_event(
                        {
                            "type": "step.chunk",
                            "id": step_ids[phase_key],
                            "output_type": "text",
                            "content": f"开始 {STAGE_TITLES.get(stage, stage)}",
                        }
                    )
                    continue
                step_number += 1
                step_id = f"financial-step-{step_number}"
                step_ids[phase_key] = step_id
                running_steps[phase_key] = {
                    "id": step_id,
                    "title": phase_title,
                    "detail": phase_description,
                    "phase": "财报研究",
                    "thought": None,
                    "action": f"financial_phase_{phase_key}",
                    "action_input": None,
                    "outputs": [],
                    "status": "running",
                }
                yield _sse_event(
                    {
                        "type": "step.start",
                        "step": step_number,
                        "id": step_id,
                        "title": phase_title,
                        "detail": phase_description,
                        "phase": "财报研究",
                    }
                )
                continue

            completed_step_id = step_ids.get(phase_key)
            if not completed_step_id:
                continue
            status = "failed" if event.status == StageStatus.FAILED else "done"
            stage_result = f"{STAGE_TITLES.get(stage, stage)}：{event.message}"
            yield _sse_event(
                {
                    "type": "step.chunk",
                    "id": completed_step_id,
                    "output_type": "text",
                    "content": stage_result,
                }
            )
            history_step = running_steps[phase_key]
            history_step["outputs"].append(
                {"output_type": "text", "content": stage_result}
            )
            phase_status = current_phase_statuses.get(phase_key)
            if phase_status not in {"completed", "cancelled"}:
                continue
            yield _sse_event(
                {"type": "step.done", "id": completed_step_id, "status": status}
            )
            history_step = running_steps.pop(phase_key)
            history_step["status"] = status
            history_steps.append(history_step)

        state = await task
        history_task_plan = _task_plan_payload(state.plan)
        if history_task_plan != streamed_task_plan:
            streamed_task_plan = history_task_plan
            yield _sse_event({"type": "plan.update", "tasks": history_task_plan})
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

        top_findings = state.analysis.get("top_findings", [])[:5]
        sources = {source.id: source for source in state.sources}
        summary_evidence = _select_summary_evidence(
            state.evidence, top_findings, limit=10
        )
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
            for index, evidence in enumerate(summary_evidence, start=1)
        )
        companies = identified_company_names(state.metrics, state.documents)
        subject = (
            f"{len(companies)} 家公司"
            if len(companies) > 1
            else (
                f"{len(state.documents)} 份财报"
                if state.mode == ResearchMode.MULTI_COMPANY and len(state.documents) > 1
                else (companies[0] if companies else "该公司")
            )
        )
        finding_summary = "\n".join(
            f"{index}. {finding['title']}：{finding['summary']}"
            for index, finding in enumerate(top_findings, start=1)
        )
        final_answer = AgentFinalAnswer(
            content=(
                f"已完成 {subject}的财报调查。\n\n"
                f"核心结论：\n{finding_summary or '当前资料不足以形成核心结论。'}\n\n"
                "聊天仅展示前 5 条重点结论；全部分析章节、未决问题及来源证据"
                "见完整研究报告。"
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
            "task_plan": history_task_plan,
            "generated_images": [],
            "sub_agents": {},
        },
        ensure_ascii=False,
    )
    for terminal_event in _terminal_events(storage_conv, history_payload, final_answer):
        yield terminal_event
