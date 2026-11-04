from __future__ import annotations

import json
import time
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models import (
    LlmAgentOutput,
    LlmAgentRun,
    LlmEnsemblePrediction,
    LlmEvidencePacket,
    Match,
)
from packages.llm.aggregation.log_opinion import aggregate_predictions
from packages.llm.domain import AgentPrediction
from packages.llm.evidence import build_evidence_packet
from packages.llm.ledger import place_llm_paper_bet
from packages.llm.prompts.registry import PromptRegistry
from packages.llm.providers import LlmProvider, LlmProviderError, normalize_json_content
from packages.llm.roster import AGENTS
from packages.shared.time import ensure_utc, utc_now

MODEL_VERSION = "llm-ensemble-v1"

SPECIALIST_SCHEMA = """{
  "agent_id": "string",
  "match_id": "uuid",
  "stage": "T-30m",
  "as_of": "ISO-8601 UTC",
  "probabilities": {"H": 0.0, "D": 0.0, "A": 0.0},
  "confidence": 0.0,
  "data_quality": 0.0,
  "key_factors": ["string"],
  "evidence_refs": ["string"],
  "uncertainties": ["string"],
  "abstain": false,
  "abstain_reason": null
}"""
RED_TEAM_SCHEMA = """{
  "objections": ["string"],
  "consensus_fragility": 0.0,
  "recommended_abstain": false
}"""
JUDGE_SCHEMA = """{
  "main_disagreement": "string",
  "abstain_recommendation": false,
  "reasoning_summary": "string"
}"""


class LlmOrchestrationError(RuntimeError):
    """Raised when the LLM lane cannot produce a usable ensemble."""


def _prompt_registry(prompt_dir) -> PromptRegistry:
    return PromptRegistry.from_directory(prompt_dir)


def _specialist_user_prompt(prompt: str, packet: dict[str, Any]) -> str:
    return (
        f"{prompt}\n\n"
        f"EVIDENCE_PACKET:\n{json.dumps(packet, sort_keys=True, default=str)}\n\n"
        f"OUTPUT_SCHEMA:\n{SPECIALIST_SCHEMA}\n"
        "Return JSON only."
    )


def _critic_user_prompt(prompt: str, packet: dict[str, Any], outputs: list[dict[str, Any]]) -> str:
    return (
        f"{prompt}\n\n"
        f"EVIDENCE_PACKET:\n{json.dumps(packet, sort_keys=True, default=str)}\n\n"
        f"SPECIALIST_OUTPUTS:\n{json.dumps(outputs, sort_keys=True, default=str)}\n\n"
        f"OUTPUT_SCHEMA:\n{RED_TEAM_SCHEMA}\n"
        "Return JSON only."
    )


def _judge_user_prompt(
    prompt: str,
    packet: dict[str, Any],
    outputs: list[dict[str, Any]],
    red_team: dict[str, Any] | None,
) -> str:
    return (
        f"{prompt}\n\n"
        f"EVIDENCE_PACKET:\n{json.dumps(packet, sort_keys=True, default=str)}\n\n"
        f"SPECIALIST_OUTPUTS:\n{json.dumps(outputs, sort_keys=True, default=str)}\n\n"
        f"RED_TEAM:\n{json.dumps(red_team, sort_keys=True, default=str)}\n\n"
        f"OUTPUT_SCHEMA:\n{JUDGE_SCHEMA}\n"
        "Return JSON only."
    )


def _persist_run(
    session: Session,
    *,
    packet_id: uuid.UUID,
    match_id: uuid.UUID,
    stage: str,
    agent_id: str,
    prompt_name: str,
    prompt_sha256: str,
    provider: LlmProvider,
    status: str,
    raw_response: str | None,
    error: str | None,
    latency_ms: int | None,
) -> LlmAgentRun:
    run = LlmAgentRun(
        packet_id=packet_id,
        match_id=match_id,
        stage=stage,
        agent_id=agent_id,
        prompt_name=prompt_name,
        prompt_sha256=prompt_sha256,
        provider=provider.provider,
        model=provider.model,
        status=status,
        raw_response=raw_response,
        error=error,
        latency_ms=latency_ms,
    )
    session.add(run)
    session.flush()
    return run


def _run_specialist(
    session: Session,
    *,
    packet_id: uuid.UUID,
    packet: dict[str, Any],
    match_id: uuid.UUID,
    stage: str,
    agent_id: str,
    prompt_registry: PromptRegistry,
    provider: LlmProvider,
) -> AgentPrediction | None:
    prompt = prompt_registry.get(agent_id)
    system = prompt_registry.get("system")
    started = time.perf_counter()
    raw: str | None = None
    try:
        response = provider.complete_json(
            system.text,
            _specialist_user_prompt(prompt.text, packet),
        )
        raw = response.content
        data = json.loads(normalize_json_content(response.content))
        data.setdefault("agent_id", agent_id)
        data.setdefault("match_id", str(match_id))
        data.setdefault("stage", stage)
        data.setdefault("as_of", packet["as_of"])
        if data.get("abstain") is True:
            data["probabilities"] = {
                "H": "0.333333",
                "D": "0.333333",
                "A": "0.333334",
            }
        prediction = AgentPrediction.model_validate(data)
        latency_ms = int((time.perf_counter() - started) * 1000)
        run = _persist_run(
            session,
            packet_id=packet_id,
            match_id=match_id,
            stage=stage,
            agent_id=agent_id,
            prompt_name=prompt.name,
            prompt_sha256=prompt.sha256,
            provider=provider,
            status="succeeded",
            raw_response=raw,
            error=None,
            latency_ms=latency_ms,
        )
        session.add(
            LlmAgentOutput(
                run_id=run.id,
                match_id=match_id,
                stage=stage,
                agent_id=agent_id,
                probabilities={
                    key: str(value) for key, value in prediction.probabilities.items()
                },
                confidence=prediction.confidence,
                data_quality=prediction.data_quality,
                abstain=prediction.abstain,
                output=prediction.model_dump(mode="json"),
            )
        )
        session.flush()
        return prediction
    except (LlmProviderError, ValueError, json.JSONDecodeError) as exc:
        _persist_run(
            session,
            packet_id=packet_id,
            match_id=match_id,
            stage=stage,
            agent_id=agent_id,
            prompt_name=prompt.name,
            prompt_sha256=prompt.sha256,
            provider=provider,
            status="failed",
            raw_response=raw,
            error=str(exc)[:2000],
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return None


def _run_json_agent(
    session: Session,
    *,
    packet_id: uuid.UUID,
    match_id: uuid.UUID,
    stage: str,
    agent_id: str,
    system: str,
    user: str,
    prompt_name: str,
    prompt_sha256: str,
    provider: LlmProvider,
) -> dict[str, Any] | None:
    started = time.perf_counter()
    raw: str | None = None
    try:
        response = provider.complete_json(system, user)
        raw = response.content
        data = json.loads(normalize_json_content(response.content))
        if not isinstance(data, dict):
            raise TypeError("agent output must be a JSON object")
        _persist_run(
            session,
            packet_id=packet_id,
            match_id=match_id,
            stage=stage,
            agent_id=agent_id,
            prompt_name=prompt_name,
            prompt_sha256=prompt_sha256,
            provider=provider,
            status="succeeded",
            raw_response=raw,
            error=None,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return data
    except (LlmProviderError, ValueError, TypeError, json.JSONDecodeError) as exc:
        _persist_run(
            session,
            packet_id=packet_id,
            match_id=match_id,
            stage=stage,
            agent_id=agent_id,
            prompt_name=prompt_name,
            prompt_sha256=prompt_sha256,
            provider=provider,
            status="failed",
            raw_response=raw,
            error=str(exc)[:2000],
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return None


def run_llm_prediction(
    session: Session,
    match_id: uuid.UUID,
    *,
    as_of: datetime | None = None,
    stage: str = "T-30m",
    provider: LlmProvider,
    prompt_dir,
) -> dict[str, Any]:
    match = session.get(Match, match_id)
    if match is None:
        raise LlmOrchestrationError(f"unknown match {match_id}")
    cutoff = ensure_utc(as_of or utc_now())
    packet, packet_hash = build_evidence_packet(
        session, match_id, as_of=cutoff, stage=stage
    )
    packet_row = session.scalar(
        select(LlmEvidencePacket).where(
            LlmEvidencePacket.match_id == match_id,
            LlmEvidencePacket.stage == stage,
            LlmEvidencePacket.packet_hash == packet_hash,
        )
    )
    if packet_row is None:
        packet_row = LlmEvidencePacket(
            match_id=match_id,
            stage=stage,
            as_of=cutoff,
            packet_hash=packet_hash,
            packet=packet,
        )
        session.add(packet_row)
        session.flush()

    registry = _prompt_registry(prompt_dir)
    predictions: list[AgentPrediction] = []
    output_payloads: list[dict[str, Any]] = []
    for agent in AGENTS:
        if agent.kind != "specialist":
            continue
        prediction = _run_specialist(
            session,
            packet_id=packet_row.id,
            packet=packet,
            match_id=match_id,
            stage=stage,
            agent_id=agent.agent_id,
            prompt_registry=registry,
            provider=provider,
        )
        if prediction is not None:
            predictions.append(prediction)
            output_payloads.append(prediction.model_dump(mode="json"))

    red_prompt = registry.get("red_team_agent")
    system = registry.get("system")
    red_team = _run_json_agent(
        session,
        packet_id=packet_row.id,
        match_id=match_id,
        stage=stage,
        agent_id="red_team_agent",
        system=system.text,
        user=_critic_user_prompt(red_prompt.text, packet, output_payloads),
        prompt_name=red_prompt.name,
        prompt_sha256=red_prompt.sha256,
        provider=provider,
    )
    judge_prompt = registry.get("judge_agent")
    judge = _run_json_agent(
        session,
        packet_id=packet_row.id,
        match_id=match_id,
        stage=stage,
        agent_id="judge_agent",
        system=system.text,
        user=_judge_user_prompt(judge_prompt.text, packet, output_payloads, red_team),
        prompt_name=judge_prompt.name,
        prompt_sha256=judge_prompt.sha256,
        provider=provider,
    )

    active = [prediction for prediction in predictions if not prediction.abstain]
    if len(active) < 3:
        raise LlmOrchestrationError(
            f"only {len(active)} active specialist outputs; at least 3 required"
        )
    weights = {
        prediction.agent_id: Decimal(1) / Decimal(len(active))
        for prediction in active
    }
    probabilities = aggregate_predictions(active, weights)
    ensemble = LlmEnsemblePrediction(
        match_id=match_id,
        stage=stage,
        packet_id=packet_row.id,
        probabilities={outcome.value: str(value) for outcome, value in probabilities.items()},
        weights={agent_id: str(weight) for agent_id, weight in weights.items()},
        active_agents=[prediction.agent_id for prediction in active],
        red_team=red_team,
        judge=judge,
        model_version=MODEL_VERSION,
    )
    session.add(ensemble)
    session.flush()
    paper_bet = place_llm_paper_bet(
        session,
        match_id=match_id,
        stage=stage,
        model_version=MODEL_VERSION,
        probabilities=ensemble.probabilities,
        packet=packet,
        red_team=red_team,
        judge=judge,
    )
    return {
        "match_id": str(match_id),
        "stage": stage,
        "packet_id": str(packet_row.id),
        "prediction_id": str(ensemble.id),
        "probabilities": {key: str(value) for key, value in probabilities.items()},
        "active_agents": ensemble.active_agents,
        "model_version": MODEL_VERSION,
        "paper_bet_id": str(paper_bet.id) if paper_bet is not None else None,
        "paper_bet_status": paper_bet.status.value if paper_bet is not None else "no_bet",
    }
