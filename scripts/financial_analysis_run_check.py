"""Real upload -> background run -> saved report check, with both baseline PDFs."""

import argparse
import hashlib
import json
import logging
import time
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
from financial_analysis_smoke import isolated_client

ROOT = Path(__file__).resolve().parents[1]
BASE = "/api/v1/financial-analysis/runs"
FILES = "/api/v1/agent/files"


@contextmanager
def client_context(url):
    if url:
        with httpx.Client(base_url=url, timeout=180) as client:
            yield client
    else:
        with isolated_client() as (client, _):
            yield client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url")
    parser.add_argument("--pdf-dir", type=Path, default=ROOT / "testpdf")
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / ".work/financial-analysis/round4"
    )
    parser.add_argument(
        "--keep", action="store_true", help="Keep live sample uploads for manual review"
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    baseline = json.loads(
        (
            ROOT / "skills/financial-report-analyzer/tests/sample-baselines.json"
        ).read_text(encoding="utf-8")
    )
    files = {
        hashlib.sha256(p.read_bytes()).hexdigest(): p
        for p in args.pdf_dir.glob("*.pdf")
    }
    reviewed = []
    with client_context(args.base_url) as client:
        for sample in baseline["samples"]:
            path = files[sample["sha256"]]
            session_id = "financial-run-check-" + uuid4().hex
            headers = {"user-id": "001"}
            upload = client.post(
                FILES,
                headers=headers,
                data={"session_id": session_id},
                files={"files": (path.name, path.read_bytes(), "application/pdf")},
            )
            assert upload.status_code == 200, upload.text
            file_id = upload.json()["data"][0]["file_id"]
            try:
                body = {
                    "session_id": session_id,
                    "file_ids": [file_id],
                    "request_id": str(uuid4()),
                }
                started = time.monotonic()
                created = client.post(BASE, headers=headers, json=body)
                assert created.status_code == 202, created.text
                run_id = created.json()["data"]["id"]
                params = {"session_id": session_id}
                assert (
                    client.post(BASE, headers=headers, json=body).json()["data"]["id"]
                    == run_id
                )
                while True:
                    status = client.get(
                        f"{BASE}/{run_id}", headers=headers, params=params
                    ).json()["data"]
                    if status["status"] in {"completed", "failed"}:
                        break
                    assert time.monotonic() - started < 150, "Run timeout"
                    time.sleep(0.25)
                assert status["status"] == "completed", status
                report_url = f"{BASE}/{run_id}/report"
                report = client.get(report_url, headers=headers, params=params).json()[
                    "data"
                ]
                assert report["documents"][0]["sha256"] == sample["sha256"]
                assert report["documents"][0]["fileName"] == path.name
                for year, values in sample["values"].items():
                    for code, expected in values.items():
                        fact = next(
                            f
                            for f in report["facts"]
                            if f["fiscalPeriod"] == year and f["metricCode"] == code
                        )
                        assert Decimal(fact["normalizedValue"]) == Decimal(expected)
                assert len(report["calculations"]) == 8
                assert all(
                    c["result"] is not None and isinstance(c["result"], str)
                    for c in report["calculations"]
                )
                assert (
                    client.get(report_url, headers=headers, params=params).json()[
                        "data"
                    ]
                    == report
                )
                assert (
                    client.get(
                        report_url, headers={"user-id": "other"}, params=params
                    ).status_code
                    == 404
                )
                assert (
                    client.get(
                        report_url, headers=headers, params={"session_id": "wrong"}
                    ).status_code
                    == 404
                )
                (args.output_dir / (sample["name"] + "-report.json")).write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                reviewed.append(
                    {
                        "sample": sample["name"],
                        "run_id": run_id,
                        "session_id": session_id,
                        "file_id": file_id,
                        "report_url": report_url,
                        "page": f"http://localhost:3000/financial-analysis?run_id={run_id}&session_id={session_id}",
                    }
                )
                print(
                    f"PASS {sample['name']}: uploaded, calculated, persisted; "
                    f"{time.monotonic() - started:.1f}s",
                    flush=True,
                )
            finally:
                if not args.keep:
                    deleted = client.delete(
                        f"{FILES}/{file_id}",
                        headers=headers,
                        params={"session_id": session_id},
                    )
                    assert deleted.status_code == 200
    (args.output_dir / "runs.json").write_text(
        json.dumps(reviewed, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("PASS two PDFs, eight calculations each, repeated reads and scope isolation")


if __name__ == "__main__":
    main()
