"""Focused tests for financial-research presentation and report completeness."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dbgpt_app.financial_research.domain.models import (
    AnalysisSection,
    AnalysisStatus,
    Evidence,
    FindingTone,
    ParsedDocument,
    PlanStatus,
    ReportArtifact,
    ResearchFinding,
    ResearchMode,
    ResearchPlanItem,
    ResearchRequest,
    ResearchStage,
    ResearchState,
    ResearchStatus,
    StageEvent,
    StageStatus,
)
from dbgpt_app.financial_research.domain.research_analysis import (
    synthesize_research,
)
from dbgpt_app.financial_research.infrastructure.reporting.renderer import (
    render_report,
)
from dbgpt_app.financial_research.presentation.streaming import (
    _select_summary_evidence,
    _task_plan_payload,
)


def _research_section() -> AnalysisSection:
    generic = [
        ResearchFinding(
            id=f"generic-{index}",
            title=f"其他重大事项 {index}",
            summary=f"第 {index} 项为独立的其他重大事项。",
            company_name="示例公司",
            topic_key=f"other_{index}",
            tone=FindingTone.WARNING,
            materiality=float(20 - index),
        )
        for index in range(8)
    ]
    receivables = ResearchFinding(
        id="receivables-focus",
        title="示例公司：应收账款账龄需要关注",
        summary="三年以上应收账款占比较高，需结合坏账准备继续核验。",
        company_name="示例公司",
        topic_key="note_receivables_aging",
        materiality=1.0,
    )
    return AnalysisSection(
        key="complete_section",
        title="完整章节标题",
        objective="覆盖所有已验证财务主题。",
        methodology="使用确定性指标与证据链逐项复核。",
        status=AnalysisStatus.PARTIAL,
        findings=[*generic, receivables],
        missing_inputs=["应收账款坏账准备明细"],
    )


def test_question_prioritizes_headline_without_dropping_full_analysis(
    tmp_path: Path,
):
    section = _research_section()
    question = "请重点分析应收账款风险"

    analysis = synthesize_research([], [section], [], question=question)

    assert analysis["top_findings"][0]["id"] == "receivables-focus"
    assert len(analysis["top_findings"]) == 8
    assert len(analysis["sections"][0]["findings"]) == 9
    omitted = next(
        finding
        for finding in section.findings
        if finding.id not in {item["id"] for item in analysis["top_findings"]}
    )

    state = ResearchState(
        request=ResearchRequest(question=question),
        status=ResearchStatus.COMPLETED,
        analysis_sections=[section],
        analysis=analysis,
    )
    artifact = render_report(state, tmp_path)
    html = Path(artifact.path).read_text(encoding="utf-8")

    assert question in html
    assert "完整分析正文" in html
    assert "完整章节标题" in html
    assert "覆盖所有已验证财务主题" in html
    assert "使用确定性指标与证据链逐项复核" in html
    assert "应收账款坏账准备明细" in html
    assert "已列入核心结论" in html
    # This finding was omitted from the capped executive summary but remains in
    # the complete section body exactly once.
    assert html.count(omitted.title) == 1


def test_task_plan_payload_groups_internal_stages_for_frontend():
    plan = [
        ResearchPlanItem(
            stage=stage, title=stage.value, description="内部步骤", status=status
        )
        for stage, status in (
            (ResearchStage.INITIALIZE, PlanStatus.COMPLETED),
            (ResearchStage.PARSE, PlanStatus.COMPLETED),
            (ResearchStage.EXTRACT, PlanStatus.COMPLETED),
            (ResearchStage.NORMALIZE, PlanStatus.RUNNING),
            (ResearchStage.DERIVE, PlanStatus.PENDING),
            (ResearchStage.INVESTIGATE_EARNINGS, PlanStatus.PENDING),
            (ResearchStage.VERIFY_FINDINGS, PlanStatus.PENDING),
            (ResearchStage.VISUALIZE, PlanStatus.FAILED),
        )
    ]

    payload = _task_plan_payload(plan)

    assert [item["status"] for item in payload] == [
        "completed",
        "in_progress",
        "pending",
        "pending",
        "pending",
        "cancelled",
    ]
    assert [item["content"].split("：", 1)[0] for item in payload] == [
        "资料准备",
        "事实底稿",
        "计算与校验",
        "专题调查",
        "结论形成",
        "报告交付",
    ]
    assert all(item["priority"] == "medium" for item in payload)


def test_report_uses_document_companies_when_one_has_no_metrics(tmp_path: Path):
    documents = [
        ParsedDocument(
            id=f"document-{suffix}",
            source_id=f"source-{suffix}",
            file_name=f"{suffix}.pdf",
            media_type="application/pdf",
            company_name=f"示例{suffix}公司",
        )
        for suffix in ("A", "B")
    ]
    state = ResearchState(
        request=ResearchRequest(),
        mode=ResearchMode.MULTI_COMPANY,
        documents=documents,
        analysis=synthesize_research([], [], []),
    )

    artifact = render_report(state, tmp_path)
    html = Path(artifact.path).read_text(encoding="utf-8")

    assert artifact.title == "2 家公司可追溯财务对比报告"
    assert "2 家公司 · 0 份 PDF" in html


def test_summary_citations_prefer_evidence_used_by_visible_findings():
    evidence = [
        Evidence(
            id=f"evidence-{index}",
            document_id="document",
            source_id="source",
            page_number=index,
            quote=f"证据 {index}",
            extraction_method="test",
        )
        for index in range(1, 4)
    ]

    selected = _select_summary_evidence(
        evidence,
        [{"evidence_ids": ["evidence-3", "evidence-2", "evidence-3"]}],
        limit=3,
    )

    assert [item.id for item in selected] == [
        "evidence-3",
        "evidence-2",
        "evidence-1",
    ]


@pytest.mark.asyncio
async def test_stream_persists_and_emits_real_research_plan(
    monkeypatch, tmp_path: Path
):
    from dbgpt_app.financial_research.presentation import streaming

    report_path = tmp_path / "report.html"
    report_path.write_text("<html><body>完整报告</body></html>", encoding="utf-8")
    plan_items = [
        ResearchPlanItem(
            stage=ResearchStage.INITIALIZE,
            title="建立来源",
            description="登记全部上传文件",
        ),
        ResearchPlanItem(
            stage=ResearchStage.PARSE,
            title="解析财报",
            description="解析所有上传文件",
        ),
    ]
    state = ResearchState(
        request=ResearchRequest(question="分析财报"),
        status=ResearchStatus.RUNNING,
        mode=ResearchMode.MULTI_COMPANY,
        plan=plan_items,
        documents=[
            ParsedDocument(
                id=f"document-{suffix}",
                source_id=f"source-{suffix}",
                file_name=f"{suffix}.pdf",
                media_type="application/pdf",
                company_name=f"示例{suffix}公司",
            )
            for suffix in ("A", "B")
        ],
        analysis={"top_findings": []},
        report=ReportArtifact(path=str(report_path), title="测试报告"),
    )

    class FakeAgent:
        async def run(self, _request, callback):
            assert _request.file_paths == ["/tmp/a.pdf", "/tmp/b.pdf"]
            state.plan[0].status = PlanStatus.RUNNING
            await callback(
                StageEvent(
                    stage=ResearchStage.INITIALIZE,
                    status=StageStatus.STARTED,
                    message="开始登记来源",
                ),
                state,
            )
            state.plan[0].status = PlanStatus.COMPLETED
            await callback(
                StageEvent(
                    stage=ResearchStage.INITIALIZE,
                    status=StageStatus.COMPLETED,
                    message="来源登记完成",
                ),
                state,
            )
            state.plan[1].status = PlanStatus.RUNNING
            await callback(
                StageEvent(
                    stage=ResearchStage.PARSE,
                    status=StageStatus.STARTED,
                    message="开始解析",
                ),
                state,
            )
            state.plan[1].status = PlanStatus.COMPLETED
            await callback(
                StageEvent(
                    stage=ResearchStage.PARSE,
                    status=StageStatus.COMPLETED,
                    message="解析完成",
                ),
                state,
            )
            state.status = ResearchStatus.COMPLETED
            return state

    class FakeStorageConversation:
        instances = []

        def __init__(self, **_kwargs):
            self.view_messages = []
            self.instances.append(self)

        def save_to_storage(self):
            return None

        def start_new_round(self):
            return None

        def add_user_message(self, _message):
            return None

        def add_view_message(self, message):
            self.view_messages.append(message)

        def end_current_round(self):
            return None

    monkeypatch.setattr(streaming, "FinancialResearchAgent", FakeAgent)
    monkeypatch.setattr(streaming, "StorageConversation", FakeStorageConversation)
    monkeypatch.setattr(
        streaming.ConversationServe,
        "get_instance",
        staticmethod(
            lambda _system_app: SimpleNamespace(
                conv_storage=object(), message_storage=object()
            )
        ),
    )
    dialogue = SimpleNamespace(
        conv_uid="conversation",
        chat_mode="chat_react_agent",
        user_name="tester",
        sys_code=None,
        user_input="分析财报",
        app_code=None,
        ext_info={"file_paths": ["/tmp/a.pdf", "/tmp/b.pdf"]},
    )

    events = [
        json.loads(item.removeprefix("data: ").strip())
        async for item in streaming.stream_financial_research(dialogue, object())
    ]
    plan_updates = [item["tasks"] for item in events if item["type"] == "plan.update"]
    history = json.loads(FakeStorageConversation.instances[0].view_messages[-1])
    final_event = next(item for item in events if item["type"] == "final")
    research_step_starts = [
        item
        for item in events
        if item["type"] == "step.start" and item["phase"] == "财报研究"
    ]
    research_step_ids = {item["id"] for item in research_step_starts}
    research_step_completions = [
        item
        for item in events
        if item["type"] == "step.done" and item["id"] in research_step_ids
    ]
    research_history_steps = [
        item
        for item in history["steps"]
        if item["action"].startswith("financial_phase_")
    ]

    assert plan_updates[0][0]["status"] == "in_progress"
    assert plan_updates[-1][0]["status"] == "completed"
    assert len(research_step_starts) == 1
    assert research_step_starts[0]["title"] == "资料准备"
    assert len(research_step_completions) == 1
    assert len(research_history_steps) == 1
    assert [item["content"] for item in research_history_steps[0]["outputs"]] == [
        "建立研究任务：来源登记完成",
        "解析财报：解析完成",
    ]
    assert history["task_plan"] == plan_updates[-1]
    assert history["task_plan"][0]["content"] == "资料准备：建立来源并解析全部财报"
    assert "已完成 2 家公司的财报调查" in final_event["content"]
