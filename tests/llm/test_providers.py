from __future__ import annotations

import json

import httpx
import pytest
import respx

from packages.llm.providers import (
    LlmOutputTruncatedError,
    LlmProviderError,
    OpenAICompatibleProvider,
)

URL = "https://llm.local/chat/completions"


def _content_response(content: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}]},
    )


@respx.mock
def test_complete_json_retries_once_after_truncated_content():
    route = respx.post(URL).mock(
        side_effect=[
            _content_response('{"a": "unterminated'),
            _content_response('{"a": 1}'),
        ]
    )
    provider = OpenAICompatibleProvider(
        base_url="https://llm.local", api_key="secret", model="test"
    )

    response = provider.complete_json("system", "user")

    assert response.content == '{"a": 1}'
    assert route.call_count == 2
    second = json.loads(route.calls[1].request.content)
    assert "not valid JSON" in second["messages"][1]["content"]


@respx.mock
def test_complete_json_raises_when_both_attempts_are_invalid():
    respx.post(URL).mock(
        return_value=_content_response('{"a": "unterminated')
    )
    provider = OpenAICompatibleProvider(
        base_url="https://llm.local", api_key="secret", model="test"
    )

    with pytest.raises(LlmProviderError, match="not JSON"):
        provider.complete_json("system", "user")


def _length_response(reasoning_tokens: int = 4000) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [
                {
                    "message": {
                        "content": None,
                        "reasoning_content": "thinking without JSON",
                    },
                    "finish_reason": "length",
                }
            ],
            "usage": {
                "completion_tokens_details": {"reasoning_tokens": reasoning_tokens}
            },
        },
    )


@respx.mock
def test_complete_json_escalates_budget_after_length_truncation():
    route = respx.post(URL).mock(
        side_effect=[_length_response(), _content_response('{"a": 1}')]
    )
    provider = OpenAICompatibleProvider(
        base_url="https://llm.local", api_key="secret", model="test", max_tokens=4000
    )

    response = provider.complete_json("system", "user")

    assert response.content == '{"a": 1}'
    assert route.call_count == 2
    second = json.loads(route.calls[1].request.content)
    assert second["max_tokens"] == 8000


@respx.mock
def test_complete_json_reports_finish_reason_for_empty_content():
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": None}, "finish_reason": "stop"}],
                "usage": {"completion_tokens_details": {"reasoning_tokens": 123}},
            },
        )
    )
    provider = OpenAICompatibleProvider(
        base_url="https://llm.local", api_key="secret", model="test"
    )

    with pytest.raises(
        LlmProviderError,
        match=r"empty content.*finish_reason='stop'.*reasoning_tokens=123",
    ):
        provider.complete_json("system", "user")


@respx.mock
def test_complete_json_raises_truncated_when_max_budget_is_exhausted():
    respx.post(URL).mock(return_value=_length_response())
    provider = OpenAICompatibleProvider(
        base_url="https://llm.local",
        api_key="secret",
        model="test",
        max_tokens=32000,
    )

    with pytest.raises(LlmOutputTruncatedError, match="finish_reason=length"):
        provider.complete_json("system", "user")
