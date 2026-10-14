# Ledger execution price (Sub-system C follow-up)

> Date: 2026-10-14
> Scope: **`place_bets` only** — the price a paper bet is recorded at, and the Kelly stake
> derived from it. No schema change, no migration, no API change, no ML change.
> Related: `docs/superpowers/specs/2026-10-12-paper-ledger-design.md` (sub-system C),
> `2026-10-12-football-agent-ml-engine-design.md` (the market prior).

---

## 1. Context and problem

Today the ledger records every bet at `Prediction.market_odds`, and sizes it with
`Prediction.recommended_fraction`. Both were computed by sub-system B from the **market
prior** — the last HKJC snapshot strictly before `kickoff − ML_PRIOR_LEAD_HOURS` (48h).

That prior is the right *information set* for the model (features must match training,
and B's spec defines it as the serving-time information set). It is the wrong *execution
price*: a bet placed now is recorded at a price that was quoted up to two days ago and
that no longer exists. The resulting P&L is not realizable and cannot be compared with a
real book.

## 2. Decision (hybrid)

| Purpose | Price used | Status |
| --- | --- | --- |
| Model features, training, serving-time market prior | last HKJC snapshot strictly before `kickoff − 48h` | **unchanged** |
| Ledger **execution price**, Kelly fraction, recorded odds and edge | last HKJC snapshot strictly before `kickoff` (i.e. the latest one we hold at placement time) | **new** |

CLV is unaffected: it is computed in the ML layer as model fair price vs closing price
(`clv_metrics(model_probs, closing_priors)`), and the ledger's execution price never
enters it.

## 3. Rules for `place_bets`

Selection (unchanged): champion prediction, `recommended_fraction > 0` (the *signal* —
the model's edge against its information set), match not yet kicked off, and no bet for
the same `(match_id, target, outcome)` in any status.

For each candidate, at placement time:

1. Load HKJC HAD priors with `lead_hours = 0` (`load_hkjc_priors`) — this is exactly "the
   latest HKJC snapshot before kickoff", i.e. what is obtainable now.
2. **Skip** the candidate when there is no HKJC snapshot (`had_odds is None`) or its
   payload does not yield this outcome. No fabricated price.
3. `exec_odds = had_odds[outcome]`; `implied = had_probs[outcome]` (de-vigged from the
   same snapshot, same three outcomes, same methodology as B).
4. `edge = prediction.prob − implied` — the edge **at the execution price**.
5. `fraction = kelly_fraction(prediction.prob, exec_odds)`; **skip when `fraction <= 0`**
   (the price moved against us: the value is gone). The stored
   `recommended_fraction` is deliberately **not** used for sizing — it would size the bet
   as if we had the prior's better price.
6. `stake = _size_stake(bankroll_batch_start, fraction, settings)`; skip below minimum
   (unchanged, whole HKD, floored).
7. Record `odds = exec_odds`, `edge = edge`, `kelly_multiplier` unchanged,
   `bankroll_at_place` unchanged.

Handicap (`HDC`) candidates keep today's behaviour (sized and recorded from the signal):
there is no handicap champion yet, and per-target handicap rules are deferred to
Phase 2b. Documented so it is not mistaken for an oversight.

## 4. Consequence for existing records

`ledger_bets.odds` and `ledger_bets.edge` change meaning for bets placed after this
change: "the price/edge the signal was measured at" becomes "the price/edge actually
taken". Bets already placed keep their stored values — no backfill. Both meanings are
valid readings of the same columns only if the row's placement date is considered, so
the change is called out in the README's performance section.

## 5. Tests (TDD — each must fail before the implementation)

1. Execution price **better** than the prior → `odds` = execution price, and the stake is
   sized from `kelly_fraction(prob, execution price)` (not from `recommended_fraction`).
2. Execution price moved **against** us → Kelly fraction ≤ 0 → **no bet placed**.
3. No pre-kickoff HKJC snapshot for the match → **no bet placed** (no price, no bet).
4. Guard: a candidate whose snapshot payload lacks the outcome → no bet.
5. Existing ledger tests are updated where they pin the old semantics (notably
   `test_place_sizes_and_locks_fields`, whose stake/edge are derived from the old rule).

## 6. Non-goals

- No change to sub-system B (priors, features, `recommended_fraction`, `market_odds`).
- No schema change, no migration, no backfill of historical bets.
- No change to settlement, payout rounding, or staking caps.
- No handicap execution pricing (deferred with Phase 2b).

## 7. Acceptance

On the host, after a `predict` + `ledger` cycle:

```sql
select b.match_id, b.target, b.outcome, b.odds, b.edge, b.stake,
       p.market_odds as signal_odds, p.edge as signal_edge
from ledger_bets b join predictions p
  on p.match_id = b.match_id and p.target = b.target
 and p.outcome = b.outcome and p.model_version_id = b.model_version_id
order by b.match_id;
```

`b.odds` must equal the most recent HKJC HAD snapshot price for that match (visible in
`odds_snapshots`), not the 48h-prior price; `b.edge` must be derived from it.
