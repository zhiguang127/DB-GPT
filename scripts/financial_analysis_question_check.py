"""Ask five question categories against saved public-sample reports via Qwen."""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx

QUESTIONS = [
    ("profit", "本期归母净利润和扣非归母净利润如何变化？只依据已有计算回答。"),
    ("cash", "经营现金流对归母净利润的覆盖情况如何？"),
    ("expense", "本期销售费用率和管理费用率是多少？与上期相比有何变化？"),
    ("source", "本期营业收入是多少？请提供它的原文依据。"),
    ("missing", "列出公司前五大客户的具体名称和各自销售占比。"),
]


def check_run(base_url, run):
    with httpx.Client(
        base_url=base_url, timeout=75, headers={"user-id": "001"}
    ) as client:
        url = f"/api/v1/financial-analysis/runs/{run['run_id']}"
        params = {"session_id": run["session_id"]}
        response = client.get(url + "/report", params=params)
        response.raise_for_status()
        report = response.json()["data"]
        body = dict(
            session_id=run["session_id"], revision=report["revision"], question="收入"
        )
        assert (
            client.post(
                url + "/questions", json=dict(body, revision="stale")
            ).status_code
            == 409
        )
        assert (
            client.post(
                url + "/questions", json=dict(body, session_id="other")
            ).status_code
            == 404
        )
        assert (
            client.post(
                url + "/questions", json=body, headers={"user-id": "other"}
            ).status_code
            == 404
        )
        facts = {f["id"]: f for f in report["facts"]}
        calculations = {c["id"]: c for c in report["calculations"]}
        evidence = {e["id"] for e in report["evidence"]}
        results = []
        for category, question in QUESTIONS:
            started = time.monotonic()
            response = client.post(
                url + "/questions", json=dict(body, question=question)
            )
            if response.status_code != 200:
                results.append(
                    {
                        "category": category,
                        "statusCode": response.status_code,
                        "error": response.json().get("err_msg"),
                    }
                )
                print(
                    f"FAIL {run['sample']}: {category} HTTP {response.status_code}",
                    flush=True,
                )
                continue
            answer = response.json()["data"]
            assert answer["answerMode"] in {
                "validated",
                "references_only",
                "insufficient",
            }
            if answer["answerMode"] == "references_only":
                assert (
                    answer["insufficientEvidence"]
                    and "解释未通过校验" in answer["answer"]
                )
            assert (
                answer["runId"] == run["run_id"]
                and answer["revision"] == report["revision"]
            )
            assert "{{" not in answer["answer"]
            assert set(answer["factIds"]) <= facts.keys()
            assert set(answer["calculationIds"]) <= calculations.keys()
            assert set(answer["evidenceExcerptIds"]) <= evidence
            if category == "missing":
                assert answer["insufficientEvidence"]
            else:
                assert answer["citations"] and answer["evidenceExcerptIds"]
                for citation in answer["citations"]:
                    if "factId" in citation:
                        assert (
                            facts[citation["factId"]]["displayValue"]
                            in answer["answer"]
                        )
                    else:
                        assert (
                            calculations[citation["calculationId"]]["displayResult"]
                            in answer["answer"]
                        )
            results.append(
                dict(
                    category=category,
                    elapsedSeconds=round(time.monotonic() - started, 1),
                    **answer,
                )
            )
            print(
                f"PASS {run['sample']}: {category} ({answer['answerMode']})", flush=True
            )
        assert client.get(url + "/report", params=params).json()["data"] == report
        return {"sample": run["sample"], "answers": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:5670")
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    runs = json.loads(args.runs.read_text(encoding="utf-8"))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda run: check_run(args.base_url, run), runs))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    assert not any(
        "error" in answer for result in results for answer in result["answers"]
    ), "Some questions failed; see output JSON"
    print(
        "PASS real Qwen questions, reference values, insufficient context, "
        "scope and immutable reports"
    )


if __name__ == "__main__":
    main()
