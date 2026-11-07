from __future__ import annotations

import json
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from packages.shared.config import Settings


class LlmProviderError(RuntimeError):
    """Raised when the configured LLM provider cannot return JSON."""


class LlmOutputTruncatedError(LlmProviderError):
    """Raised when the provider stops because the output token budget ran out."""


_TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_REQUEST_ATTEMPTS = 2
_BACKOFF_SECONDS = (15.0,)


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    content: str
    raw: dict[str, Any]
    provider: str
    model: str


class LlmProvider(Protocol):
    provider: str
    model: str

    def complete_json(self, system: str, user: str) -> ProviderResponse: ...


class MockProvider:
    provider = "mock"
    model = "mock-model"

    def __init__(self, responses: Sequence[str]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> ProviderResponse:
        self.calls.append((system, user))
        if not self._responses:
            raise LlmProviderError("mock provider has no response left")
        content = self._responses.pop(0)
        return ProviderResponse(
            content=content,
            raw={"content": content},
            provider=self.provider,
            model=self.model,
        )


class OpenAICompatibleProvider:
    provider = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 900,
        timeout_seconds: float = 60.0,
        session_id: str | None = None,
    ) -> None:
        if not api_key.strip():
            raise LlmProviderError("LLM API key is empty")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout_seconds = timeout_seconds
        self.session_id = session_id or f"football-llm-{uuid.uuid4()}"

    def _payload(
        self, system: str, user: str, *, max_tokens: int | None = None
    ) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
            "response_format": {"type": "json_object"},
        }

    def _post(
        self,
        client: httpx.Client,
        endpoint: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> httpx.Response:
        for attempt in range(_MAX_REQUEST_ATTEMPTS):
            try:
                response = client.post(endpoint, headers=headers, json=payload)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt + 1 >= _MAX_REQUEST_ATTEMPTS:
                    raise LlmProviderError(
                        "LLM provider request failed after "
                        f"{_MAX_REQUEST_ATTEMPTS} attempts: {exc}"
                    ) from exc
                time.sleep(_BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)])
                continue
            if response.status_code in _TRANSIENT_STATUS:
                if attempt + 1 >= _MAX_REQUEST_ATTEMPTS:
                    raise LlmProviderError(
                        f"LLM provider HTTP {response.status_code}: "
                        f"{response.text[:500]}"
                    )
                retry_after = response.headers.get("retry-after", "")
                delay = (
                    float(retry_after)
                    if retry_after.replace(".", "", 1).isdigit()
                    else _BACKOFF_SECONDS[min(attempt, len(_BACKOFF_SECONDS) - 1)]
                )
                time.sleep(min(delay, 60.0))
                continue
            return response
        raise LlmProviderError("LLM provider request failed")

    def _request_content(
        self, system: str, user: str, *, max_tokens: int | None = None
    ) -> tuple[str, dict[str, Any]]:
        endpoint = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "x-opencode-session": self.session_id,
        }
        budget = self.max_tokens if max_tokens is None else max_tokens
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = self._post(
                client,
                endpoint,
                headers,
                self._payload(system, user, max_tokens=budget),
            )
            if response.status_code == 400:
                payload = self._payload(system, user, max_tokens=budget)
                payload.pop("response_format", None)
                response = self._post(client, endpoint, headers, payload)
            if response.status_code >= 400:
                raise LlmProviderError(
                    f"LLM provider HTTP {response.status_code}: {response.text[:500]}"
                )
            body = response.json()
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LlmProviderError("LLM provider returned no choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            finish_reason = choices[0].get("finish_reason")
            details = (body.get("usage") or {}).get("completion_tokens_details") or {}
            reasoning_tokens = details.get("reasoning_tokens")
            if finish_reason == "length":
                raise LlmOutputTruncatedError(
                    "LLM output truncated: "
                    f"finish_reason=length, reasoning_tokens={reasoning_tokens}, "
                    f"max_tokens={budget}"
                )
            raise LlmProviderError(
                "LLM provider returned empty content "
                f"(finish_reason={finish_reason!r}, "
                f"reasoning_tokens={reasoning_tokens}, max_tokens={budget})"
            )
        return content, body

    def complete_json(self, system: str, user: str) -> ProviderResponse:
        attempts = 2
        max_budget = max(self.max_tokens, 32000)
        budget = self.max_tokens
        last_error: LlmProviderError | None = None
        for attempt in range(1, attempts + 1):
            prompt = user
            if attempt > 1:
                prompt = (
                    user
                    + "\n\nIMPORTANT: Your previous answer was not valid JSON. "
                    "Return ONLY one complete JSON object, with no prose and no truncation."
                )
            try:
                content, body = self._request_content(
                    system, prompt, max_tokens=budget
                )
            except LlmOutputTruncatedError:
                if budget < max_budget:
                    budget = min(budget * 2, max_budget)
                    continue
                raise
            try:
                normalized = normalize_json_content(content)
            except LlmProviderError as exc:
                last_error = exc
                continue
            return ProviderResponse(
                content=normalized,
                raw=body,
                provider=self.provider,
                model=self.model,
            )
        raise last_error or LlmProviderError("LLM provider did not return JSON")


class OllamaCloudProvider(OpenAICompatibleProvider):
    provider = "ollama_cloud"


class FallbackProvider:
    """Try the primary provider, then the fallback provider."""

    def __init__(self, primary: LlmProvider, fallback: LlmProvider) -> None:
        self._primary = primary
        self._fallback = fallback
        self.provider = primary.provider
        self.model = primary.model

    def complete_json(self, system: str, user: str) -> ProviderResponse:
        try:
            return self._primary.complete_json(system, user)
        except LlmProviderError as primary_error:
            try:
                return self._fallback.complete_json(system, user)
            except LlmProviderError as fallback_error:
                raise LlmProviderError(
                    f"primary provider failed: {primary_error}; "
                    f"fallback provider failed: {fallback_error}"
                ) from fallback_error


def build_provider(settings: Settings) -> LlmProvider | None:
    if not settings.llm_enabled:
        return None
    if settings.llm_provider == "mock":
        return MockProvider(())
    if settings.llm_provider not in {"openai_compatible", "opencode_go"}:
        raise LlmProviderError(f"unsupported LLM provider {settings.llm_provider!r}")
    primary = OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "",
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
        session_id=settings.llm_session_id or None,
    )
    fallback_key = (settings.llm_fallback_api_key or "").strip()
    if not fallback_key:
        return primary
    fallback = OllamaCloudProvider(
        base_url=settings.llm_fallback_base_url,
        api_key=fallback_key,
        model=settings.llm_fallback_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    return FallbackProvider(primary, fallback)


def normalize_json_content(content: str) -> str:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2 and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        raise LlmProviderError(f"provider content is not JSON: {exc}") from exc
    return text
