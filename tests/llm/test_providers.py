from __future__ import annotations

import json

import httpx
import pytest
import respx

from packages.llm.providers import LlmProviderError, OpenAICompatibleProvider

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
