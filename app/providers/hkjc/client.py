import asyncio
import gzip
import json
import time
from typing import Any

import httpx


class HkjcGraphQLError(RuntimeError):
    """Raised when the HKJC GraphQL endpoint fails or returns GraphQL errors."""


class HkjcGraphQLClient:
    """Minimal async HKJC GraphQL client.

    Sends the four headers the spec verified, throttles to at most one request
    per ``throttle_seconds``, retries 5xx/timeouts with exponential backoff, and
    transparently handles gzip-encoded responses.
    """

    def __init__(
        self,
        url: str,
        referer: str,
        origin: str,
        user_agent: str,
        throttle_seconds: float = 1.5,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = url
        self._headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "Referer": referer,
            "Origin": origin,
            "User-Agent": user_agent,
        }
        self._throttle_seconds = throttle_seconds
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._client = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client = client is None
        self._lock = asyncio.Lock()
        self._last_request_at = 0.0

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def execute(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        payload = {"query": query, "variables": variables}
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            await self._throttle()
            try:
                response = await self._client.post(self._url, headers=self._headers, json=payload)
            except httpx.HTTPError as exc:
                last_error = exc
                await self._backoff(attempt)
                continue
            if response.status_code >= 500:
                last_error = HkjcGraphQLError(f"HKJC returned HTTP {response.status_code}")
                await self._backoff(attempt)
                continue
            if response.status_code >= 400:
                raise HkjcGraphQLError(
                    f"HKJC returned HTTP {response.status_code}: {response.text[:200]}"
                )
            body = self._decode_json(response)
            if body.get("errors"):
                raise HkjcGraphQLError(f"HKJC GraphQL errors: {body['errors']}")
            data = body.get("data")
            if not isinstance(data, dict):
                raise HkjcGraphQLError("HKJC response missing 'data' object")
            return data
        raise HkjcGraphQLError(
            f"HKJC request failed after {self._max_retries + 1} attempts: {last_error}"
        )

    async def _throttle(self) -> None:
        async with self._lock:
            elapsed = time.monotonic() - self._last_request_at
            wait = self._throttle_seconds - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()

    async def _backoff(self, attempt: int) -> None:
        if self._backoff_base > 0:
            await asyncio.sleep(min(self._backoff_base * (2**attempt), 8.0))

    @staticmethod
    def _decode_json(response: httpx.Response) -> dict[str, Any]:
        content = response.content
        if content[:2] == b"\x1f\x8b":
            content = gzip.decompress(content)
        return json.loads(content.decode("utf-8"))
