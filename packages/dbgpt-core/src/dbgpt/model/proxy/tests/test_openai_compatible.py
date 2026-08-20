"""Tests for generic OpenAI-compatible request options."""

from unittest.mock import patch

from dbgpt.core import ModelMessage, ModelRequest
from dbgpt.model.proxy.llms.chatgpt import (
    OpenAICompatibleDeployModelParameters,
    OpenAILLMClient,
)


class _FakeOpenAIClient:
    default_headers = {}


def test_enable_thinking_is_sent_in_extra_body():
    client = OpenAILLMClient(
        api_key="test-key",
        model="qwen-max",
        openai_client=_FakeOpenAIClient(),
        openai_kwargs={"extra_body": {"enable_thinking": False}},
    )
    request = ModelRequest(
        model="qwen-max",
        messages=[ModelMessage(role="user", content="hi")],
    )

    payload = client._build_request(request)

    assert payload["extra_body"] == {"enable_thinking": False}


def test_new_client_maps_enable_thinking_parameter():
    parameters = OpenAICompatibleDeployModelParameters(
        name="qwen-max",
        api_key="test-key",
        enable_thinking=False,
    )

    with patch.object(OpenAILLMClient, "__init__", return_value=None) as init:
        OpenAILLMClient.new_client(parameters)

    assert init.call_args.kwargs["openai_kwargs"] == {
        "extra_body": {"enable_thinking": False}
    }


def test_new_client_does_not_send_qwen_option_to_openai_models():
    parameters = OpenAICompatibleDeployModelParameters(
        name="gpt-4o",
        api_key="test-key",
        enable_thinking=False,
    )

    with patch.object(OpenAILLMClient, "__init__", return_value=None) as init:
        OpenAILLMClient.new_client(parameters)

    assert init.call_args.kwargs["openai_kwargs"] == {}
