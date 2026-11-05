# V2 Market-Shrunk Challenger: Backend Design

## Status

Approved design, backend implementation first. UI is deferred until explicitly requested.

## Goal

Run a second deterministic paper-betting lane alongside g1, without changing g1's
model, strategy, ledger, or execution path. The challenger tests whether blending
Poisson probabilities with de-vigged market probabilities reduces overconfident
longshot edges and improves calibration/ROI on the same matches.

## Non-goals

- Do not stop, edit, or re-key the active g1 experiment.
- Do not promote the challenger automatically.
- Do not tune parameters from live results.
- Do not change settlement source or HKJC semantics.
- Do not build UI in this phase.
- Do not implement LLM fine-tuning.

## Lanes and experiments

- Existing lane: `deterministic` (g1, `poisson-v1`, `g1`).
- New lane: `challenger`.
- Challenger experiment:
  - label: `v2-market-shrunk`
  - lane: `challenger`
  - model version: `poisson-v2-shrunk`
  - strategy version: `g1`
  - initial bankroll: `FP_INITIAL_BANKROLL` (currently 10,000 HKD)
  - separate `BankrollAccount`
- Both lanes remain active simultaneously.
- `decision_slot_key` already includes `experiment_id`, so decision and bet
  identity remain lane-local.
- Existing settlement already reads each bet's `experiment_id`; both lanes settle
  independently without schema changes.

## V2 model

Use the existing Poisson probability as the base model.

De-vig the T-30m HAD odds proportionally:

```text
q(H) = (1 / odds_H) / ((1 / odds_H) + (1 / odds_D) + (1 / odds_A))
q(D) = ...
q(A) = ...
```

Blend:

```text
p_v2(H) = w * p_poisson(H) + (1 - w) * q(H)
p_v2(D) = ...
p_v2(A) = ...
```

Initial fixed parameter:

```text
w = 0.50
```

`w` is versioned and fixed for this challenger. Do not adjust it using the current
live ledger. A future weight grid or parameter study must create a new model
version and experiment.

If any HAD side is missing, odds are invalid, de-vig is non-finite, or the
resulting probabilities do not sum to 1 within tolerance, the challenger skips
the match. g1 continues normally.

The challenger uses the same `g1` EV, Kelly, stake-cap, and no-bet policy as the
base lane. The only intended change is the probability vector.

## Decision flow

At T-30m, reuse the existing single `OddsSnapshot`:

```text
ingest odds once
  -> g1 decide_match (unchanged)
  -> challenger decide_match (new)
  -> commit
```

Requirements:

- g1's `DecisionLog`, `PaperBet`, bankroll, and analysis run key are unchanged.
- Challenger writes its own `DecisionLog` and optional `PaperBet` under the
  challenger experiment.
- Challenger predictions are saved with `model_version="poisson-v2-shrunk"`.
- Any challenger exception must be isolated so it cannot roll back a successful
  g1 bet.
- If no active challenger experiment exists, challenger is a no-op.
- Retries must be idempotent through the existing decision-slot and bet-intent
  uniqueness rules.

## Model and API boundary

New pure functions under `packages/models/`:

- proportional de-vig from decimal HAD odds
- blend Poisson probabilities with market probabilities
- preserve score distribution for EV/Kelly/settlement

New decision entry point for a named lane/experiment, while the existing
`decide_match()` remains the g1 entry point.

Backend API for future UI:

```text
GET /dashboard/challenger
GET /dashboard/challenger/bets
```

Both return the active challenger experiment, ledger summary, counts, and
challenger bets. The existing deterministic dashboard endpoints remain scoped to
g1.

## Failure and edge cases

- Missing challenger experiment: skip silently, record nothing.
- Missing/invalid odds: challenger `skipped`; g1 unaffected.
- Challenger save/decision failure: rollback challenger savepoint only; g1 still
  commits.
- Duplicate trigger: existing slot/bet idempotency prevents duplicate bets.
- Settlement remains HKJC-confirmed and per-experiment.
- UCL league-phase exception remains unchanged; UCL knockout remains gated.

## Testing

Unit:

- de-vig probabilities sum to 1 and handle invalid odds
- blend formula respects `w=0.5`
- score distribution remains valid and EV/Kelly run on blended probabilities
- missing/invalid odds skip challenger only

Integration:

- one T-30m trigger creates one g1 decision and one challenger decision
- g1 bet and challenger bet use different experiments and bankroll accounts
- challenger failure does not remove/rollback the g1 bet
- retry creates no duplicate bets
- settlement updates both lanes independently
- challenger API is scoped only to the challenger experiment

## Rollout

1. Add backend and tests.
2. Create the challenger experiment with the new lane.
3. Deploy backend and observe one match end-to-end.
4. Collect matched g1/challenger evidence.
5. Only after a separate promotion decision create a new g1 experiment if the
   challenger wins; never overwrite the existing g1 experiment in place.
