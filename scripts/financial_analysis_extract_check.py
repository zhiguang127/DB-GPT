"""Validate user PDFs against visually reviewed amounts and physical pages."""

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
        "--baseline", type=Path, default=SKILL / "tests/sample-baselines.json"
    )
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / ".work/financial-analysis/round3"
    )
    args = parser.parse_args()
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
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
                expected_page = sample.get("metricPages", {}).get(code) or (
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
        for year, codes in sample.get("expectedMissing", {}).items():
            for code in codes:
                item = next(
                    f
                    for f in result["facts"]
                    if f["metricCode"] == code and f["fiscalPeriod"] == year
                )
                assert item["normalizedValue"] is None, (
                    code,
                    year,
                    "opening balance was relabelled as closing",
                )
        opening = sample.get("openingBalances", {})
        for code, expected in opening.get("values", {}).items():
            matches = [
                c
                for c in result["sourceObservations"]
                if c["metricCode"] == code
                and c["sourcePeriod"]["role"] == "opening"
                and c["sourcePeriod"]["date"] == opening["date"]
            ]
            assert len(matches) == 1 and Decimal(
                matches[0]["normalizedValue"]
            ) == Decimal(expected), (code, matches)
            assert matches[0]["evidence"]["page"] == opening["pages"][code]
            checked += 1
        for year, values in sample.get("preAdjustment", {}).items():
            for code, expected in values.items():
                matches = [
                    c
                    for c in result["sourceObservations"]
                    if c["metricCode"] == code
                    and c["fiscalPeriod"] == year
                    and c["sourcePeriod"]["adjustment"] == "before"
                ]
                assert len(matches) == 1 and Decimal(
                    matches[0]["normalizedValue"]
                ) == Decimal(expected), (code, matches)
                item = next(
                    f
                    for f in result["facts"]
                    if f["metricCode"] == code and f["fiscalPeriod"] == year
                )
                assert any(p["adjustment"] == "after" for p in item["sourcePeriods"])
                assert all(p["adjustment"] != "before" for p in item["sourcePeriods"])
                checked += 1
        if sample.get("statementPages"):
            pages = json.loads(
                Path(result["_meta"]["parseArtifact"]).read_text(encoding="utf-8")
            )
            for statement, numbers in sample["statementPages"].items():
                actual = {
                    p["page"]
                    for p in pages
                    for t in p["tables"]
                    if t["scope"] == "合并"
                    and t["statement"] == statement
                    and t["structure"]["status"] == "mapped"
                }
                assert actual == set(numbers), (statement, actual)
            assert result["_meta"]["tableIssues"] == []
        print(
            f"PASS {sample['name']}: {len(result['facts'])} facts, "
            f"{len(evidence)} sources, {time.monotonic() - start:.1f}s",
            flush=True,
        )
    print(f"PASS {checked} baseline values and applicable source/period checks")


if __name__ == "__main__":
    main()
