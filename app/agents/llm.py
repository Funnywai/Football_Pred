"""Small async OpenAI-compatible client for the C decision agent.

The client only talks JSON: one bounded chat completion per call. It never logs
request headers, and every error message is safe to persist because the API key
is never included.
"""

from __future__ import annotations

import json
import uuid

import httpx

from app.config import Settings

MAX_COMPLETION_TOKENS = 500
USER_AGENT = "football-pred-agent/1.0"


class AgentLLMError(RuntimeError):
    """The LLM endpoint failed, or returned output that is not a JSON object."""


def session_id_for(run_id: str, match_id: int) -> str:
    """Stable per (run, match) session id so retries share one conversation."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"football-pred:{run_id}:{match_id}"))


def redacted_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: "***" if key.lower() == "authorization" else value
        for key, value in headers.items()
    }


def _decode_content(content: object) -> dict[str, object]:
    if isinstance(content, list):
        content = "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    if isinstance(content, dict):
        return content
    if not isinstance(content, str) or not content.strip():
        raise AgentLLMError("LLM response has no message content")
    try:
        parsed: object = json.loads(content)
    except ValueError as exc:
        raise AgentLLMError("LLM message content is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise AgentLLMError("LLM JSON content is not an object")
    return parsed


class AgentLLMClient:
    def __init__(
        self, settings: Settings, *, http_client: httpx.AsyncClient | None = None
    ) -> None:
        self._base_url: str = settings.agent_llm_base_url.rstrip("/")
        self._api_key: str = settings.agent_llm_api_key
        self._model: str = settings.agent_llm_model
        self._temperature: float = settings.agent_llm_temperature
        self._owns_client: bool = http_client is None
        self._client: httpx.AsyncClient = http_client or httpx.AsyncClient(
            timeout=settings.agent_llm_timeout_seconds
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def complete(
        self,
        prompt: str,
        *,
        system: str | None = None,
        max_tokens: int = MAX_COMPLETION_TOKENS,
        session_id: str | None = None,
    ) -> dict[str, object]:
        if not self._base_url:
            raise AgentLLMError("agent_llm_base_url is not configured")
        if not self._api_key:
            raise AgentLLMError("agent_llm_api_key is not configured")
        messages: list[dict[str, str]] = []
        if system is not None:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
            "x-opencode-session": session_id or str(uuid.uuid4()),
        }
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            response = await self._client.post(
                f"{self._base_url}/chat/completions", headers=headers, json=payload
            )
        except httpx.HTTPError as exc:
            raise AgentLLMError(f"LLM request failed: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            raise AgentLLMError(f"LLM returned HTTP {response.status_code}")
        try:
            body: object = response.json()
        except ValueError as exc:
            raise AgentLLMError("LLM response body is not JSON") from exc
        if not isinstance(body, dict):
            raise AgentLLMError("LLM response body is not an object")
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices:
            raise AgentLLMError("LLM response has no choices")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        if not isinstance(message, dict):
            raise AgentLLMError("LLM response choice has no message")
        return _decode_content(message.get("content"))
