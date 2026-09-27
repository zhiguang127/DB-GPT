import hashlib
import json
import re
from copy import deepcopy
from uuid import uuid4

from dbgpt_serve.financial_analysis.models import FinancialRunEntity
from dbgpt_serve.financial_analysis.service import FinancialAnalysisService

from .test_runs import ALICE, BASE, extraction, upload, wait_run


def test_history_is_owner_scoped_ordered_and_paginated(saved):
    client, service, report, run_id = saved
    ids = [str(uuid4()) for _ in range(3)]
    with service.session() as session:
        for i, task_id in enumerate(ids):
            session.add(
                FinancialRunEntity(
                    id=task_id,
                    owner_id="bob" if i == 2 else "alice",
                    session_id="s-other",
                    file_id="missing-file",
                    status="failed",
                    stage="extract",
                    created_at=f"zz{i}",
                    updated_at="stamp",
                    error="文件已不可用。",
                )
            )
    first = client.get(BASE, headers=ALICE, params={"page_size": 1}).json()["data"]
    assert first["total"] == 3 and first["items"][0]["id"] == ids[1]
    second = client.get(BASE, headers=ALICE, params={"page_size": 1, "page": 2}).json()[
        "data"
    ]
    assert second["items"][0]["id"] == ids[0]
    last = client.get(BASE, headers=ALICE, params={"page_size": 1, "page": 3}).json()[
        "data"
    ]
    item = last["items"][0]
    assert item["id"] == run_id and item["title"] == report["report"]["companyName"]
    reopened = client.get(
        f"{BASE}/{item['id']}/report",
        headers=ALICE,
        params={"session_id": item["session_id"]},
    )
    assert reopened.json()["data"] == report
    assert "report_json" not in item and "owner_id" not in item
    other = client.get(BASE, headers={"user-id": "bob"}).json()["data"]
    assert [r["id"] for r in other["items"]] == [ids[2]]
    for params in [{"page": 0}, {"page_size": 1000}]:
        assert client.get(BASE, headers=ALICE, params=params).status_code == 422


def test_exports_match_one_revision_are_persisted_and_scope_checked(saved, tmp_path):
    client, service, report, run_id = saved
    shell = tmp_path / "runtime.html"
    shell.write_text(
        '<html><script type="application/json" id="financial-report-data">'
        '<!--FINANCIAL_REPORT_JSON--></script></html>',
        encoding="utf-8",
    )
    service.export_runtime = shell
    report["report"]["companyName"] = '</script><script>alert("unsafe")</script>&公司'
    service._update(run_id, report_json=json.dumps(report))
    url = f"{BASE}/{run_id}/exports"
    body = {"session_id": "s1", "revision": report["revision"], "format": "json"}
    assert (
        client.get(url, headers=ALICE, params={"session_id": "s1"}).json()["data"] == []
    )
    records = []
    for kind in ["json", "html"]:
        response = client.post(url, headers=ALICE, json=dict(body, format=kind))
        assert response.status_code == 200, response.text
        record = response.json()["data"]
        assert (
            client.post(url, headers=ALICE, json=dict(body, format=kind)).json()["data"]
            == record
        )
        records.append(record)
        downloaded = client.get(
            f"{url}/{record['id']}", headers=ALICE, params={"session_id": "s1"}
        )
        assert len(downloaded.content) == record["size_bytes"]
        assert hashlib.sha256(downloaded.content).hexdigest() == record["sha256"]
        assert "attachment" in downloaded.headers["content-disposition"]
        if kind == "json":
            assert downloaded.json() == report
        else:
            assert "<script>alert" not in downloaded.text
            embedded = re.search(
                r'id="financial-report-data">(.*?)</script>', downloaded.text, re.S
            ).group(1)
            assert json.loads(embedded) == report
        assert (
            client.get(
                f"{url}/{record['id']}",
                headers={"user-id": "bob"},
                params={"session_id": "s1"},
            ).status_code
            == 404
        )
        assert (
            client.get(
                f"{url}/{record['id']}", headers=ALICE, params={"session_id": "wrong"}
            ).status_code
            == 404
        )
    listing = client.get(url, headers=ALICE, params={"session_id": "s1"}).json()["data"]
    assert len(listing) == 2 and all("content" not in item for item in listing)
    assert (
        client.post(url, headers=ALICE, json=dict(body, revision="stale")).status_code
        == 409
    )
    assert client.post(url, headers={"user-id": "bob"}, json=body).status_code == 404
    assert (
        client.post(url, headers=ALICE, json=dict(body, format="pdf")).status_code
        == 422
    )
    assert service.get("alice", "s1", run_id, report=True) == report
    reopened = FinancialAnalysisService(service.registry, export_runtime=shell)
    try:
        assert len(reopened.list_exports("alice", "s1", run_id)) == 2
        content, _ = reopened.download_export("alice", "s1", run_id, records[0]["id"])
        assert json.loads(content) == report
        changed = deepcopy(report)
        changed["revision"] = "another-revision"
        reopened._update(run_id, report_json=json.dumps(changed))
        new = reopened.create_export("alice", "s1", run_id, "another-revision", "json")
        assert new["id"] != records[0]["id"]
        assert (
            json.loads(
                reopened.download_export("alice", "s1", run_id, records[0]["id"])[0]
            )
            == report
        )
    finally:
        reopened.close()


def test_exports_do_not_register_missing_runtime_or_running_analysis(saved, tmp_path):
    client, service, report, run_id = saved
    service.export_runtime = tmp_path / "missing.html"
    url = f"{BASE}/{run_id}/exports"
    body = {"session_id": "s1", "revision": report["revision"], "format": "html"}
    assert client.post(url, headers=ALICE, json=body).status_code == 503
    assert service.list_exports("alice", "s1", run_id) == []
    report["analysis"] = {"status": "running"}
    service._update(run_id, report_json=json.dumps(report))
    assert (
        client.post(url, headers=ALICE, json=dict(body, format="json")).status_code
        == 409
    )
    assert service.list_exports("alice", "s1", run_id) == []


def test_completed_data_snapshot_has_measured_stages(stack):
    client, serve = stack
    serve._financial_analysis.extractor = extraction
    run_id = client.post(
        BASE, headers=ALICE, json={"session_id": "s1", "file_ids": [upload(client)]}
    ).json()["data"]["id"]
    assert wait_run(client, run_id)["status"] == "completed"
    report = serve._financial_analysis.get("alice", "s1", run_id, report=True)
    assert report["report"]["run"]["startedAt"]
    for step in report["steps"]:
        assert step["elapsedMs"] >= 0 and step["completedAt"] >= step["startedAt"]
