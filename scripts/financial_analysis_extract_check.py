"""Validate the two user-supplied PDFs against the reviewed six-metric baseline."""

import argparse
import hashlib
import json
import logging
import sys
import time
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "financial-report-analyzer"
sys.path.insert(0, str(SKILL / "scripts"))
from financial_document import extract_document  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf-dir", type=Path, default=ROOT / "testpdf")
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / ".work/financial-analysis/round3"
    )
    args = parser.parse_args()
    baseline = json.loads(
        (SKILL / "tests/sample-baselines.json").read_text(encoding="utf-8")
    )
    files = {
        hashlib.sha256(p.read_bytes()).hexdigest(): p
        for p in args.pdf_dir.glob("*.pdf")
    }
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    checked = 0
    for sample in baseline["samples"]:
        path = files.get(sample["sha256"])
        if path is None:
            raise AssertionError(f"Missing exact baseline PDF: {sample['name']}")
        start = time.monotonic()
        result = extract_document(path, artifact_dir=args.output_dir)
        (args.output_dir / f"{sample['name']}-result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        assert result["document"]["pageCount"] == sample["pageCount"]
        evidence = {e["id"]: e for e in result["evidence"]}
        assert len(evidence) == len(result["evidence"]), "Duplicate evidence IDs"
        for year, values in sample["values"].items():
            for code, expected in values.items():
                fact = next(
                    f
                    for f in result["facts"]
                    if f["metricCode"] == code and f["fiscalPeriod"] == year
                )
                assert fact["extractionStatus"] == "parsed", (code, year, fact)
                assert Decimal(fact["normalizedValue"]) == Decimal(expected), (
                    code,
                    year,
                    fact,
                )
                sources = [evidence[e] for e in fact["evidenceExcerptIds"]]
                expected_page = (
                    sample["liabilitiesPage"]
                    if code == "total_liabilities"
                    else sample["summaryPage"]
                )
                assert any(e["page"] == expected_page for e in sources), (
                    code,
                    year,
                    sources,
                )
                for source in sources:
                    assert (
                        1
                        <= source["headerPage"]
                        <= source["page"]
                        <= sample["pageCount"]
                    )
                    assert source["extractedValue"] in source["snippet"]
                    assert source["column"] in source["headerSnippet"]
                    assert source["sourceDocumentId"] == result["document"]["id"]
                checked += 1
        print(
            f"PASS {sample['name']}: {len(result['facts'])} facts, "
            f"{len(evidence)} sources, {time.monotonic() - start:.1f}s",
            flush=True,
        )
    print(
        f"PASS {checked} baseline values, "
        "including comparison periods and a negative cash flow"
    )


if __name__ == "__main__":
    main()
