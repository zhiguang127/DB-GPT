import asyncio
import hashlib
import io
import threading
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from dbgpt.component import SystemApp
from dbgpt.core.interface.file import (
    FileStorageClient,
    FileStorageSystem,
    LocalFileStorage,
)
from dbgpt.storage.metadata import DatabaseManager, Model
from dbgpt_serve.financial_analysis.models import FinancialRunEntity
from dbgpt_serve.financial_analysis.service import FinancialAnalysisService, now
from dbgpt_serve.session_file.serve import SessionFileServe

from .test_calculations import facts

BASE = "/api/v1/financial-analysis/runs"
FILES = "/api/v1/agent/files"
ALICE = {"user-id": "alice"}


@pytest.fixture
def stack(tmp_path):
    manager = DatabaseManager.build_from(
        "sqlite:///" + (tmp_path / "meta.db").as_posix(), base=Model
    )
    app = SystemApp(FastAPI())
    backend = LocalFileStorage(base_path=str(tmp_path / "blobs"))
    serve = SessionFileServe(
        app,
        db_url_or_db=manager,
        storage_client=FileStorageClient(
            storage_system=FileStorageSystem({backend.storage_type: backend})
        ),
        work_root=tmp_path / "work",
    )
    serve.on_init()
    manager.create_all()
    serve.init_app(app)
    try:
        with TestClient(app.app) as client:
            yield client, serve
    finally:
        asyncio.run(serve.async_before_stop())
        manager.engine.dispose()


def upload(client):
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    output = io.BytesIO()
    writer.write(output)
    response = client.post(
        FILES,
        headers=ALICE,
        data={"session_id": "s1"},
        files={"files": ("report.pdf", output.getvalue(), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    return response.json()["data"][0]["file_id"]


def extraction(path):
    return {
        "company_name": "测试股份有限公司",
        "report_year": "2024",
        "_meta": {"status": "parsed"},
        "facts": facts(),
        "document": {
            "id": "doc1",
            "pageCount": 1,
            "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        },
        "evidence": [
            {
                "id": "E1",
                "sourceDocumentId": "doc1",
                "page": 1,
                "snippet": "fixture",
                "qualityStatus": "warning",
            }
        ],
    }


def wait_run(client, run_id):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(
            f"{BASE}/{run_id}", headers=ALICE, params={"session_id": "s1"}
        )
        assert response.status_code == 200, response.text
        status = response.json()["data"]
        if status["status"] in {"completed", "failed"}:
            return status
        time.sleep(0.02)
    pytest.fail("Run never reached a terminal state")


def test_background_lifetime_scope_idempotency_and_snapshot(stack):
    client, serve = stack
    file_id = upload(client)
    gate, started = threading.Event(), threading.Event()
    paths = []

    def blocked_extract(path):
        paths.append(Path(path))
        started.set()
        assert gate.wait(5)
        assert Path(path).is_file()
        return extraction(path)

    serve._financial_analysis.extractor = blocked_extract
    request = {"session_id": "s1", "file_ids": [file_id], "request_id": str(uuid4())}
    try:
        created = client.post(BASE, headers=ALICE, json=request)
        assert created.status_code == 202, created.text
        run_id = created.json()["data"]["id"]
        assert started.wait(5)
        duplicate = client.post(BASE, headers=ALICE, json=request)
        assert duplicate.json()["data"]["id"] == run_id
        assert len(paths) == 1
        assert paths[0].is_file()
        for url in [f"{BASE}/{run_id}", f"{BASE}/{run_id}/report"]:
            assert (
                client.get(
                    url, headers={"user-id": "bob"}, params={"session_id": "s1"}
                ).status_code
                == 404
            )
            assert (
                client.get(
                    url, headers=ALICE, params={"session_id": "wrong"}
                ).status_code
                == 404
            )
        assert (
            client.get(
                f"{BASE}/{run_id}/report", headers=ALICE, params={"session_id": "s1"}
            ).status_code
            == 409
        )
    finally:
        gate.set()
    assert wait_run(client, run_id)["status"] == "completed"
    assert not paths[0].exists()
    response = client.get(
        f"{BASE}/{run_id}/report", headers=ALICE, params={"session_id": "s1"}
    )
    report = response.json()["data"]
    assert report["mode"] == "report"
    assert report["documents"][0]["fileId"] == file_id
    assert report["report"]["companyName"] == "测试股份有限公司"
    assert report["findings"] == []
    assert all(
        isinstance(c["result"], str) or c["result"] is None
        for c in report["calculations"]
    )
    assert (
        client.get(
            f"{BASE}/{run_id}/report", headers=ALICE, params={"session_id": "s1"}
        ).json()["data"]
        == report
    )
    serve._financial_analysis.close()
    reopened = FinancialAnalysisService(serve.registry)
    try:
        assert reopened.get("alice", "s1", run_id, report=True) == report
    finally:
        reopened.close()


def test_wrong_file_scope_failure_and_restart_recovery(stack):
    client, serve = stack
    file_id = upload(client)
    body = {"session_id": "s1", "file_ids": [file_id]}
    assert client.post(BASE, headers={"user-id": "bob"}, json=body).status_code == 404
    assert (
        client.post(
            BASE, headers=ALICE, json=dict(body, session_id="other")
        ).status_code
        == 404
    )
    assert (
        client.post(
            BASE, headers=ALICE, json=dict(body, file_ids=[file_id, file_id])
        ).status_code
        == 422
    )

    def fail(path):
        raise ValueError("不支持此 PDF")

    serve._financial_analysis.extractor = fail
    created = client.post(BASE, headers=ALICE, json=body).json()["data"]
    status = wait_run(client, created["id"])
    assert status["status"] == "failed"
    assert status["error"] == "不支持此 PDF"
    with serve.registry.dao.session() as session:
        interrupted = str(uuid4())
        session.add(
            FinancialRunEntity(
                id=interrupted,
                owner_id="alice",
                session_id="s1",
                file_id=file_id,
                status="running",
                stage="extract",
                created_at=now(),
                updated_at=now(),
            )
        )
    serve._financial_analysis.close()
    restarted = FinancialAnalysisService(serve.registry)
    try:
        assert restarted.get("alice", "s1", interrupted)["status"] == "failed"
        assert "重启" in restarted.get("alice", "s1", interrupted)["error"]
    finally:
        restarted.close()


def test_api_key_auth_is_shared_with_file_service(stack, monkeypatch):
    from dbgpt_serve.session_file.api import endpoints

    client, _ = stack
    monkeypatch.setattr(endpoints.get_session_file_config(), "api_keys", "test-secret")
    url = f"{BASE}/{uuid4()}"
    params = {"session_id": "s1"}
    assert client.get(url, params=params, headers=ALICE).status_code == 401
    assert (
        client.get(
            url, params=params, headers={"Authorization": "Bearer test-secret"}
        ).status_code
        == 401
    )
    assert (
        client.get(
            url, params=params, headers=dict(ALICE, Authorization="Bearer test-secret")
        ).status_code
        == 404
    )
