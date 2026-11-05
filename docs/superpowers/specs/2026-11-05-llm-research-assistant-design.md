# LLM Betting Research Assistant: Backend Refactor

## Status

Approved direction. Backend first; UI follows after the new pipeline is stable.

## Goal

Replace the current "LLM produces H/D/A probabilities, deterministic EV/Kelly places
the bet" flow with a research-assistant flow:

```text
evidence collection
→ role agents analyse their own domain
→ main agent synthesises findings and writes a betting report
→ main agent recommends probabilities, side and stake
→ deterministic risk layer applies hard safety caps
→ paper bet
→ settlement and evaluation
```

Role agents do not produce final H/D/A probabilities. The main agent is the only
LLM component that produces the final probability vector, betting report,
recommended side and recommended stake.

## Decisions

- Frozen evidence only; role agents cannot browse the web.
- Role agents output findings, confidence, direction/lean, evidence refs and
  uncertainties. No H/D/A probability.
- Main agent outputs the final H/D/A probability vector, report, side and stake.
- Deterministic risk layer does hard safety checks and caps only. It does not
  re-select a side and does not apply a second EV/Kelly selection model.
- Separate LLM experiment and bankroll.
- Paper-only.
- Preserve the existing LLM lane history by creating a new model/experiment
  version rather than editing old bets.

## Evidence Packet v2

At T-30m, freeze one packet for the match. Required sections:

```text
match: competition, season, kickoff, teams, venue, status
market: HAD snapshot, odds, de-vig, line status, pool status, movement
recent_matches: home and away, with venue and score
standings: competition position and points when available
weather: kickoff forecast when venue coordinates are available
lineups: confirmed/predicted lineups when available
availability: injuries, suspensions, doubtful, available
news: timestamped RSS/news items when available
xg: Understat/team xG when covered
source_audit: present/missing/stale, available_at, source_ref
```

Every fact must have a stable evidence ref. Missing sources must be explicit and
must not be invented. A packet is frozen by `as_of`; no record fetched later may
enter it.

## Role Agents

Seven role agents:

1. Environment
2. Availability
3. Market
4. Form
5. Tactical
6. News
7. Base rate

Each returns:

```json
{
  "agent_id": "environment_agent",
  "summary": "short synthesis",
  "key_findings": ["..."],
  "confidence": 0.0,
  "direction": "H|D|A|neutral|abstain",
  "evidence_refs": ["..."],
  "uncertainties": ["..."],
  "abstain": false,
  "abstain_reason": null
}
```

Rules:

- Cite only evidence refs present in the packet.
- If the role has no usable evidence, abstain.
- No probabilities, no stake, no bet instruction.
- Do not use facts outside the frozen packet.
- Raw response, prompt hash, model, latency and run status are persisted.

## Main Agent

The main agent receives the frozen packet, all role findings, the LLM bankroll and
the safety rules. It returns:

```json
{
  "report": {
    "summary": "...",
    "key_findings": ["..."],
    "market_view": "...",
    "risks": ["..."],
    "reasoning": "..."
  },
  "probabilities": {"H": 0.0, "D": 0.0, "A": 0.0},
  "recommended_side": "H|D|A|abstain",
  "recommended_stake_pct": 0.0,
  "confidence": 0.0,
  "evidence_refs": ["..."],
  "abstain": false,
  "abstain_reason": null
}
```

The main agent must use role findings only as analysis, not as additional
probabilities to average. It must cite evidence refs used in the report.

## Deterministic Hard-Safety Layer

The risk layer accepts or rejects the main agent's recommendation. It does not
recompute EV/Kelly and does not choose another side.

It rejects when:

```text
invalid probability vector
recommended_side is invalid or abstain
stake_pct < 0
stake exceeds 2% of available bankroll
stake exceeds available bankroll
stake would exceed total exposure cap
odds absent or older than 10 minutes
HAD line or pool unavailable
match missing or already kicked off
final stake below minimum
```

It caps stake by:

```text
min(
  main_agent_stake_pct * bankroll,
  2% of available bankroll,
  available bankroll,
  remaining exposure room
)
```

## Evidence Collection and Timing

```text
T-30m  collect and freeze evidence packet
T-30m  run 7 role agents in parallel
T-28m  main agent synthesis
T-26m  risk layer and paper bet
T-5m   closing odds snapshot
post   result settlement and evaluation
```

If the main agent does not finish before kickoff, no bet is placed.

## Persistence

New tables:

```text
llm_research_runs
- match_id, stage, as_of, evidence_hash
- model_version, prompt_version, status
- report, probabilities, recommended_side, recommended_stake_pct, confidence
- created_at

llm_research_findings
- run_id, agent_id, summary, findings, confidence, direction
- evidence_refs, uncertainties, abstain, raw_response, latency_ms
```

The existing `llm_evidence_packets`, `llm_agent_runs`, and `llm_ensemble_predictions`
remain for historical data. New assistant runs use the new tables.

## Experiment and Versioning

New LLM model version: `llm-assistant-v2`.
New LLM strategy version: `llm-assistant-g1`.
New LLM experiment label: `llm-assistant-v2`.
The active LLM experiment is archived only through the existing experiment
mechanism; old bets, decisions, reports and settlements remain auditable.

## Evaluation

The evaluation report will add assistant-specific sections:

- main-agent Brier / log-loss / calibration against same-time market
- report presence and evidence-ref coverage
- role-agent abstention and evidence coverage
- recommended side accuracy
- stake efficiency
- ROI / CLV / drawdown
- ablations: all roles vs no-news, no-market, no-environment; role contribution
- risk-layer accepted vs rejected recommendations

## API

Backend endpoints for the future UI:

```text
GET /llm/research-runs
GET /llm/research-runs/{id}
GET /llm/bets
GET /llm/equity
GET /llm/status
```

Existing `/llm/status` remains compatible during migration.

## Non-goals

- No live web browsing by agents.
- No real-money betting.
- No LLM direct database writes.
- No LLM settlement.
- No automatic model promotion from ROI alone.
