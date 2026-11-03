from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from packages.shared.config import Settings


class LlmProviderError(RuntimeError):
    """Raised when the configured LLM provider cannot return JSON."""


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

    def _payload(self, system: str, user: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "response_format": {"type": "json_object"},
        }

    def complete_json(self, system: str, user: str) -> ProviderResponse:
        endpoint = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "x-opencode-session": self.session_id,
        }
        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(endpoint, headers=headers, json=self._payload(system, user))
            if response.status_code == 400:
                payload = self._payload(system, user)
                payload.pop("response_format", None)
                response = client.post(endpoint, headers=headers, json=payload)
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
            raise LlmProviderError("LLM provider returned empty content")
        return ProviderResponse(
            content=content,
            raw=body,
            provider=self.provider,
            model=self.model,
        )


def build_provider(settings: Settings) -> LlmProvider | None:
    if not settings.llm_enabled:
        return None
    if settings.llm_provider == "mock":
        return MockProvider(())
    if settings.llm_provider not in {"openai_compatible", "opencode_go"}:
        raise LlmProviderError(f"unsupported LLM provider {settings.llm_provider!r}")
    return OpenAICompatibleProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key or "",
        model=settings.llm_model,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
        session_id=settings.llm_session_id or None,
    )


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
