from __future__ import annotations

import hashlib
import time
from abc import ABC
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar, Self

import httpx

from packages.shared.time import utc_now


class AdapterError(Exception):
    """Base class for source adapter failures."""


class AdapterHTTPError(AdapterError):
    pass


class AdapterSchemaError(AdapterError):
    pass


class AdapterRateLimitedError(AdapterError):
    pass


class CoverageGapError(AdapterError):
    pass


def hash_text(raw_text: str) -> str:
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


class MinIntervalRateLimiter:
    def __init__(
        self,
        min_interval_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min_interval = min_interval_seconds
        self._clock = clock
        self._last_at: float | None = None

    def wait(self) -> None:
        now = self._clock()
        if self._last_at is not None:
            remaining = self._min_interval - (now - self._last_at)
            if remaining > 0:
                time.sleep(remaining)
        self._last_at = self._clock()


@dataclass(frozen=True)
class FetchResult:
    source_name: str
    source_url: str
    fetched_at: datetime
    http_status: int
    schema_version: str
    payload: Any
    payload_hash: str
    raw_text: str


class BaseAdapter(ABC):
    name = "base"
    tos_risk = "low"
    schema_version = "v1"
    data_kind = "live"
    is_live = True
    default_headers: ClassVar[dict[str, str]] = {
        "User-Agent": "football-pred/0.1 (personal research)"
    }

    def __init__(
        self,
        client: httpx.Client | None = None,
        limiter: MinIntervalRateLimiter | None = None,
    ) -> None:
        self._client = client or httpx.Client(
            timeout=20.0,
            headers=self.default_headers,
            follow_redirects=True,
        )
        self._owns_client = client is None
        self._limiter = limiter

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        limiter = kwargs.pop("limiter", None) or self._limiter
        if limiter is not None:
            limiter.wait()
        kwargs.setdefault("follow_redirects", True)
        try:
            response = self._client.request(method, url, **kwargs)
        except httpx.HTTPError as exc:
            raise AdapterHTTPError(f"{method} {url} failed: {exc}") from exc
        if response.status_code == 429:
            raise AdapterRateLimitedError(f"{method} {url} returned 429")
        if 300 <= response.status_code < 400:
            raise AdapterHTTPError(
                f"{method} {url} returned {response.status_code} after redirects"
            )
        if response.status_code >= 400:
            raise AdapterHTTPError(f"{method} {url} returned {response.status_code}")
        return response

    def _get_json(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        response = self._request("GET", url, params=params, headers=headers)
        text = response.text
        try:
            payload = response.json()
        except ValueError as exc:
            raise AdapterSchemaError(f"{url} did not return JSON") from exc
        return FetchResult(
            source_name=self.name,
            source_url=str(response.request.url),
            fetched_at=utc_now(),
            http_status=response.status_code,
            schema_version=self.schema_version,
            payload=payload,
            payload_hash=hash_text(text),
            raw_text=text,
        )

    def _get_text(
        self,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        response = self._request("GET", url, params=params, headers=headers)
        text = response.text
        return FetchResult(
            source_name=self.name,
            source_url=str(response.request.url),
            fetched_at=utc_now(),
            http_status=response.status_code,
            schema_version=self.schema_version,
            payload=text,
            payload_hash=hash_text(text),
            raw_text=text,
        )

    def _post_json(
        self,
        url: str,
        *,
        json_body: dict[str, Any],
        headers: dict[str, str] | None = None,
        limiter: MinIntervalRateLimiter | None = None,
    ) -> FetchResult:
        response = self._request(
            "POST", url, json=json_body, headers=headers, limiter=limiter
        )
        text = response.text
        try:
            payload = response.json()
        except ValueError as exc:
            raise AdapterSchemaError(f"{url} did not return JSON") from exc
        return FetchResult(
            source_name=self.name,
            source_url=str(response.request.url),
            fetched_at=utc_now(),
            http_status=response.status_code,
            schema_version=self.schema_version,
            payload=payload,
            payload_hash=hash_text(text),
            raw_text=text,
        )
