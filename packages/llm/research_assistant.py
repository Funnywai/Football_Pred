from __future__ import annotations

import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.db.models import (
    LlmEvidencePacket,
    LlmResearchFinding,
    LlmResearchRun,
    Match,
)
from packages.ledger.service import LedgerService
from packages.llm.evidence import build_evidence_packet
from packages.llm.prompts.registry import PromptRegistry
from packages.llm.providers import LlmProvider, normalize_json_content
from packages.llm.research import (
    ROLE_AGENTS,
    MainAgentDecision,
    ResearchFinding,
)
from packages.llm.risk import (
    LLM_ASSISTANT_MODEL_VERSION,
    apply_research_risk,
    llm_research_experiment,
)
from packages.shared.time import ensure_utc, utc_now

PROMPT_VERSION = "research-v2"
MIN_ACTIVE_FINDINGS = 2
_DEFAULT_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts" / "llm" / "research"


class ResearchAssistantError(RuntimeError):
    pass


def _role_user_prompt(
    role_prompt: str,
    packet: dict[str, Any],
    allowed_refs: set[str],
) -> str:
    schema = """{
  "agent_id": "string",
  "summary": "string",
  "key_findings": ["string"],
  "confidence": 0.0,
  "direction": "H|D|A|neutral|abstain",
  "evidence_refs": ["string"],
  "uncertainties": ["string"],
  "abstain": false,
  "abstain_reason": null
}"""
    return (
        f"{role_prompt}\n\n"
        f"EVIDENCE_PACKET:\n{json.dumps(packet, sort_keys=True, default=str)}\n\n"
        f"ALLOWED_EVIDENCE_REFS:\n{json.dumps(sorted(allowed_refs))}\n\n"
        f"OUTPUT_SCHEMA:\n{schema}\n\n"
        "Return JSON only. Role agents must not output H/D/A probabilities or stake."
    )


def _main_user_prompt(
    prompt: str,
    packet: dict[str, Any],
    findings: list[dict[str, Any]],
    available_bankroll: Decimal,
) -> str:
    schema = """{
  "report": {
    "summary": "string",
    "key_findings": ["string"],
    "market_view": "string",
    "risks": ["string"],
    "reasoning": "string"
  },
  "probabilities": {"H": 0.0, "D": 0.0, "A": 0.0},
  "recommended_side": "H|D|A|abstain",
  "recommended_stake_pct": 0.0,
  "confidence": 0.0,
  "evidence_refs": ["string"],
  "abstain": false,
  "abstain_reason": null
}"""
    return (
        f"{prompt}\n\n"
        f"EVIDENCE_PACKET:\n{json.dumps(packet, sort_keys=True, default=str)}\n\n"
        f"ROLE_FINDINGS:\n{json.dumps(findings, sort_keys=True, default=str)}\n\n"
        f"LLM_BANKROLL_AVAILABLE: {available_bankroll}\n"
        "HARD_SAFETY_RULES: max stake 2% of available bankroll; "
        "no bets after kickoff; odds must be fresh; minimum stake 1.00 HKD; "
        "risk layer may cap or reject your recommendation.\n\n"
        f"OUTPUT_SCHEMA:\n{schema}\n\n"
        "Return JSON only. You are the only component allowed to produce final H/D/A probabilities."
    )


def _role_call(
    provider: LlmProvider,
    *,
    agent_id: str,
    system: str,
    user: str,
) -> tuple[str, Any, str | None, int]:
    started = time.perf_counter()
    try:
        response = provider.complete_json(system, user)
        latency_ms = int((time.perf_counter() - started) * 1000)
        return agent_id, response, None, latency_ms
    except Exception as exc:  # noqa: BLE001 - persist per-role failure
        latency_ms = int((time.perf_counter() - started) * 1000)
        return agent_id, None, str(exc), latency_ms


def _parse_finding(
    agent_id: str,
    response: Any,
    allowed_refs: set[str],
) -> ResearchFinding:
    content = normalize_json_content(response.content)
    finding = ResearchFinding.model_validate_json(content)
    if finding.agent_id != agent_id:
        raise ValueError(f"agent_id mismatch: expected {agent_id}, got {finding.agent_id}")
    unknown = sorted(set(finding.evidence_refs) - allowed_refs)
    if unknown:
        raise ValueError(f"unknown evidence refs: {unknown}")
    return finding


def run_llm_research_assistant(
    session: Session,
    match_id: uuid.UUID,
    *,
    provider: LlmProvider,
    prompt_dir: Path | None = None,
    as_of: Any | None = None,
    stage: str = "T-30m",
    max_workers: int = 7,
) -> dict[str, Any]:
    match = session.get(Match, match_id)
    if match is None:
        raise ResearchAssistantError(f"unknown match {match_id}")
    cutoff = ensure_utc(as_of or utc_now())
    packet, evidence_hash = build_evidence_packet(
        session, match_id, as_of=cutoff, stage=stage
    )
    packet_row = session.scalar(
        select(LlmEvidencePacket).where(
            LlmEvidencePacket.match_id == match.id,
            LlmEvidencePacket.stage == stage,
            LlmEvidencePacket.packet_hash == evidence_hash,
        )
    )
    if packet_row is None:
        packet_row = LlmEvidencePacket(
            match_id=match.id,
            stage=stage,
            as_of=cutoff,
            packet_hash=evidence_hash,
            packet=packet,
        )
        session.add(packet_row)
        session.flush()
    allowed_refs = set(packet.get("source_refs", []))
    registry = PromptRegistry.from_directory(prompt_dir or _DEFAULT_PROMPT_DIR)
    system = registry.get("system").text
    experiment = llm_research_experiment(session)
    available_bankroll = LedgerService(
        session, experiment_id=experiment.id
    ).available_bankroll()

    run = LlmResearchRun(
        match_id=match.id,
        stage=stage,
        as_of=cutoff,
        evidence_hash=evidence_hash,
        model_version=LLM_ASSISTANT_MODEL_VERSION,
        prompt_version=PROMPT_VERSION,
        provider=provider.provider,
        status="running",
        abstain=False,
    )
    session.add(run)
    session.flush()

    calls: dict[str, tuple[str, str]] = {}
    for agent_id, _name, _scope in ROLE_AGENTS:
        role_prompt = registry.get(f"{agent_id}").text
        calls[agent_id] = (
            system,
            _role_user_prompt(role_prompt, packet, allowed_refs),
        )

    results: list[tuple[str, Any, str | None, int]] = []
    if max_workers <= 1:
        for agent_id, (role_system, role_user) in calls.items():
            results.append(
                _role_call(
                    provider,
                    agent_id=agent_id,
                    system=role_system,
                    user=role_user,
                )
            )
    else:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(calls))) as executor:
            futures = {
                executor.submit(
                    _role_call,
                    provider,
                    agent_id=agent_id,
                    system=role_system,
                    user=role_user,
                ): agent_id
                for agent_id, (role_system, role_user) in calls.items()
            }
            for future in as_completed(futures):
                results.append(future.result())

    findings: list[ResearchFinding] = []
    finding_payloads: list[dict[str, Any]] = []
    for agent_id, response, error, latency_ms in sorted(results, key=lambda item: item[0]):
        finding: ResearchFinding | None = None
        if error is None and response is not None:
            try:
                finding = _parse_finding(agent_id, response, allowed_refs)
            except Exception as exc:  # noqa: BLE001 - malformed role output is a finding
                error = str(exc)
        if finding is None:
            finding = ResearchFinding(
                agent_id=agent_id,
                summary="",
                key_findings=[],
                confidence=Decimal(0),
                direction="abstain",
                evidence_refs=[],
                uncertainties=[],
                abstain=True,
                abstain_reason=error or "role call failed",
            )
        findings.append(finding)
        finding_payloads.append(
            {
                "agent_id": finding.agent_id,
                "summary": finding.summary,
                "key_findings": finding.key_findings,
                "confidence": str(finding.confidence),
                "direction": finding.direction,
                "evidence_refs": finding.evidence_refs,
                "uncertainties": finding.uncertainties,
                "abstain": finding.abstain,
            }
        )
        session.add(
            LlmResearchFinding(
                run_id=run.id,
                agent_id=agent_id,
                summary=finding.summary,
                findings=finding.key_findings,
                confidence=finding.confidence,
                direction=finding.direction,
                evidence_refs=finding.evidence_refs,
                uncertainties=finding.uncertainties,
                abstain=finding.abstain,
                raw_response=response.content if response is not None else None,
                error=error,
                latency_ms=latency_ms,
            )
        )
    session.flush()

    active = [finding for finding in findings if not finding.abstain]
    if len(active) < MIN_ACTIVE_FINDINGS:
        run.status = "abstained"
        run.abstain = True
        run.error = (
            f"only {len(active)} active role findings; "
            f"at least {MIN_ACTIVE_FINDINGS} required"
        )
        session.flush()
        return _result(run, findings, None, None)

    main_user = _main_user_prompt(
        registry.get("main_agent").text,
        packet,
        finding_payloads,
        available_bankroll,
    )
    decision: MainAgentDecision | None = None
    response = None
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            if attempt == 0:
                prompt = main_user
            else:
                prompt = (
                    "You previously returned this JSON:\n"
                    + (response.content if response is not None else "")
                    + "\n\nIt failed validation:\n"
                    + str(last_error)
                    + "\n\nReturn ONE complete JSON object with ALL of: report, "
                    "probabilities (H, D, A numeric values summing to 1), "
                    "recommended_side (H|D|A|abstain), recommended_stake_pct "
                    "(0 when abstaining), confidence, evidence_refs, abstain, "
                    "abstain_reason. Even when abstaining you MUST include "
                    "probabilities, recommended_side='abstain', "
                    "recommended_stake_pct=0 and confidence."
                )
            response = provider.complete_json(system, prompt)
            decision = MainAgentDecision.model_validate_json(
                normalize_json_content(response.content)
            )
            unknown = sorted(set(decision.evidence_refs) - allowed_refs)
            if unknown:
                raise ValueError(f"unknown evidence refs: {unknown}")
            break
        except ValueError as exc:  # schema or evidence-ref violation: repair once
            last_error = exc
            decision = None
        except Exception as exc:  # noqa: BLE001 - persist failed run
            run.status = "failed"
            run.error = str(exc)
            session.flush()
            return _result(run, findings, None, None)
    if decision is None or response is None:
        run.status = "failed"
        run.error = str(last_error)
        session.flush()
        return _result(run, findings, None, None)

    run.raw_response = response.content
    run.provider = response.provider
    run.report = decision.report
    run.probabilities = {side: str(value) for side, value in decision.probabilities.items()}
    run.recommended_side = decision.recommended_side
    run.recommended_stake_pct = decision.recommended_stake_pct
    run.confidence = decision.confidence
    run.abstain = decision.abstain
    if not decision.abstain:
        risk = apply_research_risk(
            session,
            match=match,
            packet=packet,
            decision=decision,
            stage=stage,
        )
        run.risk = {
            "accepted": risk.accepted,
            "reason": risk.reason,
            "selection": risk.selection,
            "stake": str(risk.stake) if risk.stake is not None else None,
            "odds": str(risk.odds) if risk.odds is not None else None,
            "paper_bet_id": str(risk.paper_bet_id) if risk.paper_bet_id else None,
            "bankroll": str(risk.bankroll) if risk.bankroll is not None else None,
        }
        run.status = "bet" if risk.accepted else "no_bet"
    else:
        run.status = "abstained"
    session.flush()
    return _result(run, findings, decision, run.risk)


def _result(
    run: LlmResearchRun,
    findings: list[ResearchFinding],
    decision: MainAgentDecision | None,
    risk: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "run_id": str(run.id),
        "match_id": str(run.match_id),
        "status": run.status,
        "probabilities": run.probabilities,
        "recommended_side": run.recommended_side,
        "recommended_stake_pct": str(run.recommended_stake_pct)
        if run.recommended_stake_pct is not None
        else None,
        "confidence": str(run.confidence) if run.confidence is not None else None,
        "report": run.report,
        "findings": [
            {
                "agent_id": finding.agent_id,
                "direction": finding.direction,
                "abstain": finding.abstain,
                "confidence": str(finding.confidence),
            }
            for finding in findings
        ],
        "risk": risk,
        "paper_bet_id": str(risk["paper_bet_id"]) if risk and risk.get("paper_bet_id") else None,
        "decision": decision.model_dump(mode="json") if decision is not None else None,
    }
