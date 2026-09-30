from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from dbgpt_serve.utils.auth import UserRequest


def _configure_example(tmp_path, monkeypatch, name: str):
    from dbgpt_app.openapi.api_v1 import examples_api

    source_path = tmp_path / "source.csv"
    source_path.write_text("value\n1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(examples_api, "CFG", SimpleNamespace(SYSTEM_APP=None))
    monkeypatch.setitem(
        examples_api.EXAMPLE_FILES,
        "test_example",
        {
            "source_path": "source.csv",
            "builtin_path": "source.csv",
            "name": name,
        },
    )
    monkeypatch.setattr(
        examples_api, "_resolve_example_source", lambda _: str(source_path)
    )
    return examples_api


@pytest.mark.asyncio
async def test_use_example_file_rejects_traversal_name(tmp_path, monkeypatch):
    examples_api = _configure_example(tmp_path, monkeypatch, "../../outside.csv")

    result = await examples_api.use_example_file(
        "test_example", UserRequest(user_id="alice")
    )

    assert result.success is False
    assert not (tmp_path / "outside.csv").exists()


@pytest.mark.asyncio
async def test_use_example_file_rejects_absolute_name(tmp_path, monkeypatch):
    outside_path = tmp_path / "outside.csv"
    examples_api = _configure_example(tmp_path, monkeypatch, str(outside_path))

    result = await examples_api.use_example_file(
        "test_example", UserRequest(user_id="alice")
    )

    assert result.success is False
    assert not outside_path.exists()


@pytest.mark.asyncio
async def test_use_example_file_rejects_windows_path_separator(tmp_path, monkeypatch):
    examples_api = _configure_example(tmp_path, monkeypatch, r"..\outside.csv")

    result = await examples_api.use_example_file(
        "test_example", UserRequest(user_id="alice")
    )

    assert result.success is False
    assert not (tmp_path / "python_uploads" / "alice" / r"..\outside.csv").exists()


@pytest.mark.asyncio
async def test_use_example_file_accepts_plain_name(tmp_path, monkeypatch):
    examples_api = _configure_example(tmp_path, monkeypatch, "report.csv")

    result = await examples_api.use_example_file(
        "test_example", UserRequest(user_id="alice")
    )

    target_path = tmp_path / "python_uploads" / "alice" / "report.csv"
    assert result.success is True
    assert result.data == target_path.as_posix()
    assert target_path.read_text(encoding="utf-8") == "value\n1\n"


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["report.csv", "浙江海翔药业__2019年__年度报告.pdf"])
async def test_example_response_can_be_sent_directly_to_chat(
    tmp_path, monkeypatch, name
):
    from dbgpt_app.openapi.api_v1 import agentic_data_api

    examples_api = _configure_example(tmp_path, monkeypatch, name)
    monkeypatch.setattr(
        agentic_data_api, "_legacy_upload_base_dir", lambda: str(tmp_path)
    )
    received = []

    async def stream(dialogue, *args, **kwargs):
        target = Path(dialogue.ext_info["file_path"])
        received.append(target)
        assert target.read_text(encoding="utf-8") == "value\n1\n"
        yield 'data: {"type":"done"}\n\n'

    monkeypatch.setattr(agentic_data_api, "_react_agent_stream", stream)
    app = FastAPI()
    app.include_router(examples_api.router, prefix="/api")
    app.include_router(agentic_data_api.router, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"user-id": "alice"},
    ) as client:
        example = await client.post(
            "/api/v1/examples/use", json={"example_id": "test_example"}
        )
        assert example.status_code == 200
        assert example.json()["success"] is True
        payload = {
            "conv_uid": "example-regression",
            "user_input": "分析示例",
            "ext_info": {"file_path": example.json()["data"]},
        }
        response = await client.post("/api/v1/chat/react-agent", json=payload)
        assert response.status_code == 200, response.text
        assert '"type":"done"' in response.text
        assert received == [(tmp_path / "python_uploads" / "alice" / name).resolve()]

        foreign = await client.post(
            "/api/v1/chat/react-agent", json=payload, headers={"user-id": "bob"}
        )
        assert foreign.status_code == 404
        assert len(received) == 1
