import io
import subprocess

from PIL import Image
from pypdf import PdfWriter

from .test_runs import ALICE, BASE, FILES, extraction, wait_run


def completed_report(client, serve):
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_blank_page(width=300, height=200)
    content = io.BytesIO()
    writer.write(content)
    source = content.getvalue()
    uploaded = client.post(
        FILES,
        headers=ALICE,
        data={"session_id": "s1"},
        files={"files": ("两页.pdf", source, "application/pdf")},
    )
    file_id = uploaded.json()["data"][0]["file_id"]

    def extract(path):
        result = extraction(path)
        result["document"]["pageCount"] = 2
        return result

    serve._financial_analysis.extractor = extract
    created = client.post(
        BASE, headers=ALICE, json={"session_id": "s1", "file_ids": [file_id]}
    )
    run_id = created.json()["data"]["id"]
    assert wait_run(client, run_id)["status"] == "completed"
    return run_id, file_id, source


def test_physical_pages_download_and_owner_scope(stack):
    client, serve = stack
    run_id, file_id, original = completed_report(client, serve)
    url = f"{BASE}/{run_id}/documents/doc1"
    params = {"session_id": "s1"}
    for number, expected in [(1, (1190, 1684)), (2, (600, 400))]:
        response = client.get(f"{url}/pages/{number}", headers=ALICE, params=params)
        assert response.status_code == 200, response.text[:200]
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == "private, no-store"
        with Image.open(io.BytesIO(response.content)) as image:
            assert image.size == expected  # Distinct page shapes detect off-by-one.
    download = client.get(f"{url}/download", headers=ALICE, params=params)
    assert download.status_code == 200
    assert download.content == original
    assert download.headers["content-type"] == "application/pdf"
    assert "filename*=UTF-8''" in download.headers["content-disposition"]
    for suffix in ["pages/1", "download"]:
        assert (
            client.get(
                f"{url}/{suffix}", headers={"user-id": "bob"}, params=params
            ).status_code
            == 404
        )
        assert (
            client.get(
                f"{url}/{suffix}", headers=ALICE, params={"session_id": "wrong"}
            ).status_code
            == 404
        )
        assert (
            client.get(
                f"{BASE}/{run_id}/documents/other/{suffix}",
                headers=ALICE,
                params=params,
            ).status_code
            == 404
        )
    assert client.get(f"{url}/pages/0", headers=ALICE, params=params).status_code == 422
    assert client.get(f"{url}/pages/3", headers=ALICE, params=params).status_code == 404
    assert not list(serve.registry.work_root.rglob("*.pdf"))
    assert (
        client.delete(f"{FILES}/{file_id}", headers=ALICE, params=params).status_code
        == 200
    )
    assert client.get(f"{url}/pages/1", headers=ALICE, params=params).status_code == 404
    assert (
        client.get(f"{url}/download", headers=ALICE, params=params).status_code == 404
    )
    assert (
        client.get(f"{BASE}/{run_id}/report", headers=ALICE, params=params).status_code
        == 200
    )


def test_timeout_releases_preview_slot_and_temporary_file(stack, monkeypatch):
    client, serve = stack
    run_id, _, _ = completed_report(client, serve)
    url = f"{BASE}/{run_id}/documents/doc1/pages/1"

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("renderer", 20)

    with monkeypatch.context() as scoped:
        scoped.setattr(subprocess, "run", timeout)
        for _ in range(3):
            response = client.get(url, headers=ALICE, params={"session_id": "s1"})
            assert response.status_code == 504
            assert response.json()["err_code"] == "PREVIEW_TIMEOUT"
    assert not list(serve.registry.work_root.rglob("*.pdf"))
    assert (
        client.get(url, headers=ALICE, params={"session_id": "s1"}).status_code == 200
    )


def test_source_hash_mismatch_fails_closed(stack):
    import json

    from dbgpt_serve.financial_analysis.models import FinancialRunEntity

    client, serve = stack
    run_id, _, _ = completed_report(client, serve)
    with serve.registry.dao.session() as session:
        row = session.query(FinancialRunEntity).filter_by(id=run_id).one()
        report = json.loads(row.report_json)
        report["documents"][0]["sha256"] = "0" * 64
        row.report_json = json.dumps(report)
    for suffix in ["pages/1", "download"]:
        response = client.get(
            f"{BASE}/{run_id}/documents/doc1/{suffix}",
            headers=ALICE,
            params={"session_id": "s1"},
        )
        assert response.status_code == 409
        assert response.json()["err_code"] == "SOURCE_CHANGED"
