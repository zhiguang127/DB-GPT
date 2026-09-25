"""PDF upload check; optional Skill extraction, never modifies report templates.

Use --isolated for the real session-file stack with disposable SQLite/storage,
or --base-url for an already running DB-GPT server. Add --model to check a real
model response (one short request); otherwise no model is invoked.
Add --check-skill with --model to verify attachment-to-Skill execution as well.
This checks connectivity and source identity, not numerical extraction accuracy.
"""

import argparse
import asyncio
import hashlib
import io
import json
import logging
import os
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

import httpx
import pdfplumber

BASE = "/api/v1/agent/files"


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def unwrap(response):
    response.raise_for_status()
    payload = response.json()
    require(payload.get("success") is True, payload.get("err_code") or "API failed")
    return payload["data"]


def request_headers(owner):
    headers = {"user-id": owner}
    if os.environ.get("DBGPT_SMOKE_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["DBGPT_SMOKE_API_KEY"]
    return headers


def check_model(client, model, owner):
    """Check actual completion content, not just worker registration or HTTP 200."""
    expected = "MODEL_OK_" + uuid.uuid4().hex[:12]
    response = client.post(
        "/api/v1/chat/completions",
        headers=request_headers(owner),
        json={
            "conv_uid": "financial-model-check-" + uuid.uuid4().hex,
            "chat_mode": "chat_normal",
            "model_name": model,
            "user_input": "Reply with exactly this text: " + expected,
            "max_new_tokens": 64,
            "temperature": 0,
            "incremental": False,
        },
    )
    response.raise_for_status()
    answer = ""
    for line in response.text.splitlines():
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if raw == "[DONE]":
            continue
        payload = json.loads(raw)
        require(not payload.get("error"), "Model returned an error")
        for choice in payload.get("choices", []):
            content = choice.get("message", {}).get("content")
            if content:
                answer = content
    require(answer.strip() == expected, "Model did not return the expected response")


def check_skill(client, model, owner, session, file_id):
    """Require tool execution, structured extraction output and a completed stream."""
    prompt = (
        "本次只做财报读取链路验收。直接调用 execute_skill_script_file，"
        'skill_name="financial-report-analyzer"，'
        'script_file_name="extract_financials.py"，'
        "args.file_path 使用本轮附件路径。取得脚本结果后立即调用 terminate，"
        "报告公司名称、年份、营业收入和归母净利润，并说明自动提取结果待人工核对。"
        "不要生成图表或HTML，不计算比率，不联网，不委派子代理，不修改文件或模板。"
    )
    actions = {}
    statuses = {}
    extractions = {}
    text_chunks = {}
    final_received = False
    done_received = False
    with client.stream(
        "POST",
        "/api/v1/chat/react-agent",
        headers=request_headers(owner),
        timeout=240,
        json={
            "conv_uid": session,
            "chat_mode": "chat_normal",
            "model_name": model,
            "user_input": prompt,
            "temperature": 0,
            "ext_info": {
                "file_ids": [file_id],
                "skill_name": "financial-report-analyzer",
            },
        },
    ) as response:
        response.raise_for_status()
        for line in response.iter_lines():
            if not line.startswith("data:") or line[5:].strip() == "[DONE]":
                continue
            event = json.loads(line[5:].strip())
            kind = event.get("type")
            step_id = event.get("id")
            require(kind != "error", "Agent emitted an error")
            if kind == "step.meta":
                args = event.get("action_input") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                if isinstance(args, dict):
                    actions[step_id] = (event.get("action"), args)
            elif kind == "step.done":
                statuses[step_id] = event.get("status")
            elif kind == "step.chunk" and event.get("output_type") == "text":
                content = event.get("content")
                if isinstance(content, str):
                    text_chunks.setdefault(step_id, []).append(content)
            elif kind == "final":
                final_received = bool(event.get("content"))
            elif kind == "done":
                done_received = True
    require(final_received and done_received, "Agent did not complete the response")
    # The SSE endpoint splits long tool output into 800-character chunks.
    # Parse only after reassembling each step, not each individual chunk.
    for step_id, chunks in text_chunks.items():
        try:
            data = json.loads("".join(chunks))
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and data.get("_meta"):
            extractions[step_id] = data
    for step_id, (action, args) in actions.items():
        if (
            action == "execute_skill_script_file"
            and args.get("skill_name") == "financial-report-analyzer"
            and args.get("script_file_name") == "extract_financials.py"
            and statuses.get(step_id) == "done"
            and extractions.get(step_id, {}).get("company_name")
            and not extractions[step_id].get("error")
        ):
            return extractions[step_id]
    raise RuntimeError("No successful financial extraction tool output was received")


@contextmanager
def isolated_client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from dbgpt.component import SystemApp
    from dbgpt.core.interface.file import (
        FileStorageClient,
        FileStorageSystem,
        LocalFileStorage,
    )
    from dbgpt.storage.metadata import DatabaseManager, Model
    from dbgpt_serve.session_file.config import ServeConfig
    from dbgpt_serve.session_file.serve import SessionFileServe

    with tempfile.TemporaryDirectory(prefix="financial-smoke-") as folder:
        root = Path(folder)
        manager = DatabaseManager.build_from(
            "sqlite:///" + (root / "metadata.db").as_posix(), base=Model
        )
        app = SystemApp(FastAPI())
        storage = LocalFileStorage(base_path=str(root / "blobs"))
        serve = SessionFileServe(
            app,
            config=ServeConfig(),
            db_url_or_db=manager,
            storage_client=FileStorageClient(
                storage_system=FileStorageSystem({storage.storage_type: storage})
            ),
            work_root=root / "work",
        )
        try:
            serve.on_init()
            manager.create_all()
            serve.init_app(app)
            with TestClient(app.app) as client:
                yield client, serve.registry
        finally:
            asyncio.run(serve.async_before_stop())
            manager.engine.dispose()


def check_upload(client, pdf_path, owner, registry=None, skill_model=None):
    source = pdf_path.read_bytes()
    require(source.startswith(b"%PDF-"), "Input is not a PDF")
    session = "financial-smoke-" + uuid.uuid4().hex
    headers = request_headers(owner)
    params = {"session_id": session}
    file_id = None
    try:
        capabilities = unwrap(client.get(BASE + "/capabilities", headers=headers))
        require(".pdf" in capabilities["supported_extensions"], "PDF not supported")
        uploaded = unwrap(
            client.post(
                BASE,
                data=params,
                files={"files": (pdf_path.name, source, "application/pdf")},
                headers=headers,
            )
        )
        require(len(uploaded) == 1, "Expected exactly one uploaded file")
        item = uploaded[0]
        file_id = item["file_id"]
        require(item["status"] in ("ready", "partial"), "PDF inspection failed")
        require(item["size"] == len(source), "File size changed")
        listed = unwrap(client.get(BASE, params=params, headers=headers))
        require(any(f["file_id"] == file_id for f in listed), "File missing from list")
        preview = unwrap(
            client.get(f"{BASE}/{file_id}/preview", params=params, headers=headers)
        )
        require(bool(preview["preview"]), "PDF preview is empty")
        download = client.get(
            f"{BASE}/{file_id}/download", params=params, headers=headers
        )
        download.raise_for_status()
        require(download.content == source, "Downloaded bytes differ from original")
        with pdfplumber.open(io.BytesIO(download.content)) as pdf:
            page_count = len(pdf.pages)
            require(bool(pdf.pages[0].extract_text()), "First page has no text")
        denied = client.get(
            f"{BASE}/{file_id}/download",
            params={"session_id": session + "-wrong"},
            headers=headers,
        )
        require(denied.status_code == 404, "Cross-session access was not denied")
        if registry is not None:
            from dbgpt_app.openapi.api_v1.attachment_react_adapter import (
                open_session_attachments,
            )

            context = open_session_attachments(
                registry, owner_id=owner, session_id=session, file_ids=(file_id,)
            )
            local_path = Path(context.primary_local_path)
            try:
                require(local_path.read_bytes() == source, "Attachment bytes differ")
            finally:
                context.close()
            require(not local_path.exists(), "Turn attachment was not cleaned up")
        if skill_model:
            extracted = check_skill(client, skill_model, owner, session, file_id)
            require(
                extracted.get("document", {}).get("sha256")
                == hashlib.sha256(source).hexdigest(),
                "Skill extraction used a different PDF",
            )
            require(bool(extracted.get("facts")), "Skill returned no structured facts")
            require(bool(extracted.get("evidence")), "Skill returned no sources")
        return {
            "mode": "isolated" if registry is not None else "live-server",
            "upload": "passed",
            "preview_status": preview["status"],
            "preview_truncated": preview["truncated"],
            "download_sha256": hashlib.sha256(source).hexdigest(),
            "pdf_pages": page_count,
            "cross_session_denied": True,
            "attachment_lifecycle": "passed" if registry is not None else "not_checked",
            "model": "not_checked",
            "skill_execution": "passed" if skill_model else "not_checked",
            "extraction_accuracy": "not_checked",
        }
    finally:
        if file_id is not None:
            unwrap(client.delete(f"{BASE}/{file_id}", params=params, headers=headers))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True, type=Path)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--isolated", action="store_true")
    mode.add_argument("--base-url", help="Running DB-GPT, e.g. http://127.0.0.1:5670")
    parser.add_argument("--owner", default="001")
    parser.add_argument("--model", help="Also check a real model, e.g. qwen-plus")
    parser.add_argument(
        "--check-skill", action="store_true", help="Run the financial Skill via Agent"
    )
    args = parser.parse_args()
    if args.model and args.isolated:
        parser.error("--model requires --base-url")
    if args.check_skill and not args.model:
        parser.error("--check-skill requires --model and --base-url")
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    if args.isolated:
        with isolated_client() as (client, registry):
            result = check_upload(client, args.pdf, args.owner, registry)
    else:
        with httpx.Client(
            base_url=args.base_url, timeout=180, trust_env=False
        ) as client:
            if args.model:
                check_model(client, args.model, args.owner)
            result = check_upload(
                client,
                args.pdf,
                args.owner,
                skill_model=args.model if args.check_skill else None,
            )
            if args.model:
                result["model"] = "passed"
                result["model_name"] = args.model
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
