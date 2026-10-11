import gzip
import json

import httpx
import pytest

from app.providers.hkjc.client import HkjcGraphQLClient, HkjcGraphQLError


def _client(handler, **kwargs) -> HkjcGraphQLClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HkjcGraphQLClient(
        url="https://example.test/graphql",
        referer="https://bet.hkjc.com/",
        origin="https://bet.hkjc.com",
        user_agent="test-agent",
        throttle_seconds=0.0,
        backoff_base=0.0,
        client=http,
        **kwargs,
    )


async def test_execute_sends_required_headers_and_returns_data():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"data": {"__typename": "Query"}})

    client = _client(handler)
    data = await client.execute("query { __typename }", {})
    assert data == {"__typename": "Query"}
    assert seen["headers"]["content-type"] == "application/json"
    assert seen["headers"]["referer"] == "https://bet.hkjc.com/"
    assert seen["headers"]["origin"] == "https://bet.hkjc.com"
    assert seen["headers"]["user-agent"] == "test-agent"
    assert seen["body"]["query"] == "query { __typename }"
    await client.aclose()


async def test_execute_decodes_gzip_body_without_content_encoding_header():
    def handler(request: httpx.Request) -> httpx.Response:
        raw = json.dumps({"data": {"ok": True}}).encode("utf-8")
        return httpx.Response(200, content=gzip.compress(raw))

    client = _client(handler)
    assert await client.execute("query { x }", {}) == {"ok": True}
    await client.aclose()


async def test_execute_raises_on_non_json_200_body():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>blocked</html>")

    client = _client(handler)
    with pytest.raises(HkjcGraphQLError):
        await client.execute("query { x }", {})
    await client.aclose()


async def test_execute_retries_on_500_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(500, text="boom")
        return httpx.Response(200, json={"data": {"ok": True}})

    client = _client(handler, max_retries=2)
    assert await client.execute("query { x }", {}) == {"ok": True}
    assert calls["n"] == 2
    await client.aclose()


async def test_execute_raises_on_graphql_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "WHITELIST_ERROR"}]})

    client = _client(handler)
    with pytest.raises(HkjcGraphQLError):
        await client.execute("query { x }", {})
    await client.aclose()


async def test_execute_raises_after_exhausting_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    client = _client(handler, max_retries=1)
    with pytest.raises(HkjcGraphQLError):
        await client.execute("query { x }", {})
    await client.aclose()
