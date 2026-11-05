# LLM Research Assistant Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the LLM probability-pool lane with a frozen-evidence research assistant that writes a betting report and recommends probabilities, side and stake, subject only to deterministic hard-safety caps.

**Architecture:** New research-run and finding tables store the main-agent report and role-agent research. Evidence collection is frozen at T-30m. Seven role agents run in parallel; the main agent synthesizes their findings and outputs probabilities, side, stake and a report. A deterministic safety layer caps or rejects the recommendation. The existing ensemble tables remain for historical runs.

**Tech Stack:** Python 3.12, SQLAlchemy/Alembic, FastAPI, RQ, existing LLM provider and paper ledger.

## Global Constraints

- Role agents must not output H/D/A probabilities.
- Main agent is the only LLM component that outputs final probabilities.
- Frozen evidence only; no web browsing.
- Deterministic layer only enforces hard safety and caps; no second EV/Kelly selection.
- Separate LLM experiment and bankroll.
- Preserve old LLM data; new version `llm-assistant-v2`.
- No UI in this plan.
- No real money.
- Do not use `as any` or suppress type errors.

## Tasks

### Task 1: Research persistence

**Files:**
- Modify: `packages/db/models/llm.py`
- Modify: `packages/db/models/__init__.py`
- Create: Alembic migration under `alembic/versions/`
- Test: `tests/db/test_schema.py`

Add `LlmResearchRun` and `LlmResearchFinding` with fields in the spec. Add relations
and indexes. Test table creation and required fields.

### Task 2: Evidence packet v2

**Files:**
- Modify: `packages/llm/evidence.py`
- Test: `tests/llm/test_evidence.py`

Extend the packet with source audit, weather, news, standings, xG, venue and
market movement. Every section records availability and timestamps. Add stable
evidence refs. Test missing-source reporting and future-record exclusion.

### Task 3: Role schemas and prompts

**Files:**
- Create: `packages/llm/research.py`
- Create prompt files under `prompts/llm/research/`
- Test: `tests/llm/test_research.py`

Define role output validation. Add seven role prompts. Test evidence-ref
validation, abstain behavior and malformed JSON rejection.

### Task 4: Parallel role execution

**Files:**
- Modify: `packages/llm/orchestrator.py`
- Test: `tests/llm/test_orchestrator.py`

Run seven role calls concurrently with a bounded executor. Persist each finding
and raw response. Keep provider calls outside the SQLAlchemy session and persist
in the main thread. Test all-success, partial abstain and provider failure.

### Task 5: Main agent and report

**Files:**
- Create: `packages/llm/main_agent.py`
- Test: `tests/llm/test_main_agent.py`

Validate the main-agent JSON contract, probability vector, evidence refs, side
and stake. Reject abstain, missing evidence refs and malformed probabilities.

### Task 6: Hard-safety risk layer

**Files:**
- Modify: `packages/llm/ledger.py`
- Create: `packages/llm/risk.py`
- Test: `tests/llm/test_risk.py`

Implement only hard safety checks and stake caps from the spec. Use the LLM
experiment/account. Test each rejection and cap path.

### Task 7: Worker/API/version wiring

**Files:**
- Modify: `apps/worker/llm_jobs.py`
- Modify: `apps/api/llm_lab.py`
- Modify: `scripts/new_ledger_experiment.py`
- Test: `tests/api/test_llm.py`, `tests/apps/test_worker.py`

Add `FP_LLM_MODE=assistant` (default assistant for the new deploy). Add API
research-run endpoints. Create the `llm-assistant-v2` experiment. Keep old
ensemble mode available behind `FP_LLM_MODE=ensemble`.

### Task 8: Evaluation integration

**Files:**
- Modify: `packages/evaluation/report.py`
- Test: `tests/evaluation/test_report.py`

Include main-agent Brier/log-loss/calibration, report evidence-ref coverage,
role abstention, recommended-side accuracy, stake efficiency and accepted/rejected
risk decisions.
