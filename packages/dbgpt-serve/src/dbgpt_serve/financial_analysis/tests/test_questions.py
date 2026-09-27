import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from dbgpt_serve.financial_analysis.models import FinancialRunEntity
from dbgpt_serve.financial_analysis.questions import (
    QwenQuestionAnswerer,
    question_context,
    reference_only_answer,
    validate_answer,
)

from .test_analysis import report_fixture
from .test_runs import ALICE, BASE


def draft():
    return {
        "answer": "披露数据显示{{fact:revenue2024}}，可点击依据核对原文。",
        "factIds": ["revenue2024"],
        "calculationIds": [],
        "evidenceExcerptIds": [],
        "insufficientEvidence": False,
    }


def test_question_context_filters_topics_without_paths_or_other_periods():
    report = report_fixture()
    report["documents"][0]["fileName"] = "private-path.pdf"
    context = question_context(report, "现金转化如何？")
    assert {f["id"] for f in context["facts"]} == {
        f["id"]
        for f in report["facts"]
        if f["metricCode"] in {"operating_cash_flow", "net_profit", "revenue"}
    }
    assert "private-path" not in json.dumps(context)
    context = question_context(report, "扣非利润变化？")
    assert any("non_recurring" in f["id"] for f in context["facts"])


def test_answer_uses_canonical_numbers_and_existing_formula_inputs():
    report = report_fixture()
    context = question_context(report, "营业收入是多少？")
    answer = validate_answer(json.dumps(draft()), context, report)
    assert "2024 年revenue 200.00 元" in answer["answer"]
    assert answer["supportStatus"] == "partial"
    assert answer["citations"] == [{"factId": "revenue2024"}]
    assert answer["evidenceExcerptIds"]
    item = dict(
        draft(),
        factIds=[],
        calculationIds=["calc-debt_ratio-2024"],
        answer="{{calculation:calc-debt_ratio-2024}}，需结合流动性核对。",
    )
    answer = validate_answer(
        json.dumps(item), question_context(report, "负债率"), report
    )
    assert set(answer["factIds"]) == {"total_assets2024", "total_liabilities2024"}
    assert answer["citations"] == [{"calculationId": "calc-debt_ratio-2024"}]
    # Declared inputs of an actually cited calculation are legitimate support.
    item["factIds"] = ["total_assets2024", "total_liabilities2024"]
    answer = validate_answer(
        json.dumps(item), question_context(report, "负债率"), report
    )
    assert answer["citations"] == [{"calculationId": "calc-debt_ratio-2024"}]


@pytest.mark.parametrize(
    "changes",
    [
        {"answer": "营收999亿元"},
        {"answer": "{{fact:revenue2024}}亿元"},
        {"answer": "{{fact:other-run}}"},
        {"answer": "收入上涨百分之二十"},
        {"factIds": ["other-run"]},
        {"factIds": ["revenue2024", "revenue2023"]},
        {"evidenceExcerptIds": ["other-source"]},
        {"answer": "没有依据但非常安全"},
        {"extra": "untrusted"},
    ],
)
def test_answer_rejects_unreferenced_numbers_unknown_and_unused_refs(changes):
    report = report_fixture()
    with pytest.raises(ValueError):
        validate_answer(
            json.dumps(dict(draft(), **changes)),
            question_context(report, "收入"),
            report,
        )


def test_context_does_not_allow_references_outside_selected_facts():
    report = report_fixture()
    with pytest.raises(ValueError):
        validate_answer(json.dumps(draft()), question_context(report, "负债"), report)


def test_missing_evidence_uses_fixed_no_support_answer():
    report = report_fixture()
    item = dict(
        draft(), answer="可以凭经验预测未来利润", factIds=[], insufficientEvidence=True
    )
    answer = validate_answer(
        json.dumps(item), question_context(report, "客户名单"), report
    )
    assert "不足以回答" in answer["answer"]
    assert "预测" not in answer["answer"]
    assert answer["citations"] == [] and answer["supportStatus"] == "unresolved"


def test_rejected_prose_fallback_only_contains_canonical_referenced_data():
    report = report_fixture()
    context = question_context(report, "收入")
    raw = json.dumps(dict(draft(), answer="{{fact:revenue2024}}且利润暴涨999亿元"))
    answer = reference_only_answer(raw, context, report)
    assert answer["answerMode"] == "references_only"
    assert answer["insufficientEvidence"] and "未通过校验" in answer["answer"]
    assert "暴涨" not in answer["answer"] and "999" not in answer["answer"]
    assert "200.00 元" in answer["answer"] and answer["evidenceExcerptIds"]
    for changes in [
        {"factIds": ["other-run"]},
        {"answer": "收入999亿元", "factIds": []},
        {"evidenceExcerptIds": ["unknown"]},
    ]:
        with pytest.raises(ValueError):
            reference_only_answer(json.dumps(dict(draft(), **changes)), context, report)
    answer = reference_only_answer(
        json.dumps(dict(draft(), answer="收入999亿元")), context, report
    )
    assert "999" not in answer["answer"] and "200.00 元" in answer["answer"]


@pytest.fixture
def saved(stack):
    client, serve = stack
    service = serve._financial_analysis
    report = report_fixture()
    run_id = str(uuid4())
    report["report"]["run"]["id"] = run_id
    with service.session() as session:
        session.add(
            FinancialRunEntity(
                id=run_id,
                owner_id="alice",
                session_id="s1",
                file_id="file",
                status="completed",
                stage="completed",
                created_at="stamp",
                updated_at="stamp",
                report_json=json.dumps(report),
            )
        )
    service.answerer = SimpleNamespace(model="test-qwen")
    return client, service, report, run_id


class Answerer:
    model = "test-qwen"

    def __init__(self, callback):
        self.callback = callback

    def __call__(self, report, question, owner, session_id):
        assert owner == "alice" and session_id == "s1"
        return self.callback(report, question)


def ask(saved, **changes):
    client, _, report, run_id = saved
    body = dict(session_id="s1", revision=report["revision"], question="收入是多少？")
    body.update(changes)
    return client.post(f"{BASE}/{run_id}/questions", headers=ALICE, json=body)


def test_question_api_preserves_report_and_scope_revision_checks_precede_model(saved):
    client, service, report, run_id = saved
    calls = []
    service.answerer = Answerer(lambda r, q: calls.append(q) or json.dumps(draft()))
    answer = ask(saved).json()["data"]
    assert answer["runId"] == run_id and answer["revision"] == report["revision"]
    assert service.get("alice", "s1", run_id, report=True) == report
    body = dict(session_id="s1", revision=report["revision"], question="收入")
    assert (
        client.post(
            f"{BASE}/{run_id}/questions", headers={"user-id": "bob"}, json=body
        ).status_code
        == 404
    )
    assert ask(saved, session_id="other").status_code == 404
    assert ask(saved, revision="old-revision").status_code == 409
    for value in ["", "   ", "问" * 1001, 123]:
        assert ask(saved, question=value).status_code == 422
    assert len(calls) == 1


@pytest.mark.parametrize(
    "error,expected",
    [
        (TimeoutError("secret-key"), 504),
        (ValueError("secret-key"), 502),
        (RuntimeError("secret-key"), 503),
    ],
)
def test_api_errors_hide_provider_details_and_release_slots(saved, error, expected):
    _, service, report, run_id = saved

    def fail(*args):
        raise error

    service.answerer = Answerer(fail)
    response = ask(saved)
    assert response.status_code == expected
    assert "secret-key" not in response.text
    assert service.get("alice", "s1", run_id, report=True) == report
    service.answerer = Answerer(lambda *_: json.dumps(draft()))
    assert ask(saved).status_code == 200


def test_unavailable_and_busy_questions_do_not_mutate_report(saved):
    _, service, report, run_id = saved
    service.answerer = None
    assert ask(saved).status_code == 503
    service.answerer = Answerer(lambda *_: pytest.fail("Should not call model"))
    assert service._question_slots.acquire(False)
    assert service._question_slots.acquire(False)
    try:
        assert ask(saved).status_code == 429
    finally:
        service._question_slots.release()
        service._question_slots.release()
    assert service.get("alice", "s1", run_id, report=True) == report


def test_revision_change_during_question_discards_answer(saved):
    _, service, report, run_id = saved

    def change_revision(*args):
        updated = deepcopy(report)
        updated["revision"] = "new-revision"
        service._update(run_id, report_json=json.dumps(updated))
        return json.dumps(draft())

    service.answerer = Answerer(change_revision)
    assert ask(saved).status_code == 409


def test_api_marks_reference_only_fallback_and_still_rejects_unknown_ids(saved):
    _, service, report, run_id = saved
    service.answerer = Answerer(
        lambda *_: json.dumps(dict(draft(), answer="{{fact:revenue2024}}增加999元"))
    )
    answer = ask(saved).json()["data"]
    assert answer["answerMode"] == "references_only"
    assert "999" not in answer["answer"] and answer["citations"]
    service.answerer = Answerer(
        lambda *_: json.dumps(dict(draft(), factIds=["another-run"]))
    )
    assert ask(saved).status_code == 502
    assert service.get("alice", "s1", run_id, report=True) == report


def test_qwen_question_bridge_repair_and_timeout(monkeypatch):
    import dbgpt.model
    from dbgpt.core import ModelOutput
    from dbgpt.model.cluster import WorkerManagerFactory

    requests, canceled = [], []

    class Client:
        async def generate(self, request):
            requests.append(deepcopy(request))
            if request.model == "slow":
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    canceled.append(True)
                    raise
            raw = (
                "invalid"
                if request.model == "invalid" or len(request.messages) == 2
                else json.dumps(draft())
            )
            return ModelOutput(error_code=0, text=raw)

    monkeypatch.setattr(
        WorkerManagerFactory,
        "get_instance",
        lambda _: SimpleNamespace(create=lambda: object()),
    )
    monkeypatch.setattr(dbgpt.model, "DefaultLLMClient", lambda *a, **kw: Client())

    async def scenario():
        answerer = QwenQuestionAnswerer(object(), asyncio.get_running_loop())
        raw = await asyncio.to_thread(answerer, report_fixture(), "收入", "alice", "s1")
        assert json.loads(raw)["factIds"]
        assert len(requests) == 2
        assert requests[0].context.user_name == "alice" and requests[0].tools is None
        invalid = QwenQuestionAnswerer(
            object(), asyncio.get_running_loop(), model="invalid"
        )
        raw = await asyncio.to_thread(invalid, report_fixture(), "收入", "alice", "s1")
        with pytest.raises(ValueError):
            validate_answer(
                raw, question_context(report_fixture(), "收入"), report_fixture()
            )
        assert (
            len(requests) == 4
        )  # Initial call plus at most one correction per question.
        slow = QwenQuestionAnswerer(
            object(), asyncio.get_running_loop(), model="slow", timeout=0.01
        )
        with pytest.raises(TimeoutError):
            await asyncio.to_thread(slow, report_fixture(), "收入", "alice", "s1")
        assert canceled

    asyncio.run(scenario())
