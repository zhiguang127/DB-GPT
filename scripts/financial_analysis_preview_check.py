"""Check saved real reports against original PDF bytes and three source pages."""

import argparse
import hashlib
import io
import json
from pathlib import Path

import httpx
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5670")
    parser.add_argument(
        "--runs", type=Path, default=ROOT / ".work/financial-analysis/round5/runs.json"
    )
    parser.add_argument("--pdf-dir", type=Path, default=ROOT / "testpdf")
    parser.add_argument(
        "--extended",
        action="store_true",
        help="Also preview cost, expense, current-balance and inventory sources",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / ".work/financial-analysis/round5"
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        hashlib.sha256(p.read_bytes()).hexdigest(): p
        for p in args.pdf_dir.glob("*.pdf")
    }
    runs = json.loads(args.runs.read_text(encoding="utf-8"))
    checked = []
    with httpx.Client(base_url=args.base_url, timeout=40) as client:
        for run in runs:
            headers, params = {"user-id": "001"}, {"session_id": run["session_id"]}
            response = client.get(run["report_url"], headers=headers, params=params)
            response.raise_for_status()
            report = response.json()["data"]
            doc = report["documents"][0]
            base = (
                f"/api/v1/financial-analysis/runs/{run['run_id']}/documents/{doc['id']}"
            )
            downloaded = client.get(base + "/download", headers=headers, params=params)
            downloaded.raise_for_status()
            assert downloaded.content == files[doc["sha256"]].read_bytes()
            evidence = {e["id"]: e for e in report["evidence"]}
            pages = []
            metrics = ["revenue", "total_liabilities", "operating_cash_flow"]
            if args.extended:
                metrics += [
                    "cost_of_sales",
                    "selling_expenses",
                    "administrative_expenses",
                    "research_expenses",
                    "financial_expenses",
                    "current_assets",
                    "current_liabilities",
                    "inventory",
                ]
            for metric in metrics:
                fact = next(
                    f
                    for f in report["facts"]
                    if f["metricCode"] == metric
                    and f["fiscalPeriod"] == report["report"]["fiscalPeriod"]
                )
                selected = fact["evidenceExcerptIds"][0 if metric == "revenue" else -1]
                page = evidence[selected]["page"]
                if page in pages:
                    continue
                response = client.get(
                    f"{base}/pages/{page}", headers=headers, params=params
                )
                response.raise_for_status()
                assert response.headers["content-type"] == "image/png"
                with Image.open(io.BytesIO(response.content)) as image:
                    image.load()
                    assert 0 < max(image.size) <= 1800
                (args.output_dir / f"{run['sample']}-page-{page}.png").write_bytes(
                    response.content
                )
                pages.append(page)
            assert len(set(pages)) >= 3
            assert (
                client.get(
                    f"{base}/pages/{pages[0]}",
                    headers={"user-id": "other"},
                    params=params,
                ).status_code
                == 404
            )
            assert (
                client.get(
                    base + "/download", headers=headers, params={"session_id": "wrong"}
                ).status_code
                == 404
            )
            checked.append(
                {
                    "sample": run["sample"],
                    "pages": pages,
                    "download_sha256": doc["sha256"],
                }
            )
            print(
                f"PASS {run['sample']}: source pages {pages}, "
                "original bytes, scope checks",
                flush=True,
            )
    (args.output_dir / "preview-check.json").write_text(
        json.dumps(checked, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
