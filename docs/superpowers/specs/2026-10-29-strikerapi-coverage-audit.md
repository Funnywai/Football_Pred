# StrikerAPI coverage audit — 2026-10-29

> Status: read-only sample audit with the free tier. No backfill, no schema change.
> API key present on host; key values never printed.
> Credits: 500 free/month; **398 remaining** after this audit.

## 1. Verdict

**StrikerAPI is viable for the six competitions we need.**

Sampled 6/6 leagues for the 2026 season:

- xG present for both teams
- 22 starters returned per match (11 per side)
- 6–8 sportsbooks per match with opening/closing fields
- Historical EPL xG (2012) and lineups (2017) work
- Historical odds before June 2020 are **partial**; do not use them for opening/closing CLV

API-Football key is not present, so that provider was not audited. It is optional for this path; StrikerAPI already covers xG, lineups, and odds.

## 2. 2026 season sample

| League | Teams | Sample match | xG home/away | Starters | Books |
|---|---:|---|---|---:|---:|
| EPL | 20 | LIV 2–0 BHA | 0.96 / 1.82 | 22 | 8 |
| La Liga | 20 | SEV 2–0 OSA | 1.62 / 1.01 | 22 | 6 |
| Serie A | 20 | MON 1–4 NAP | 0.83 / 1.89 | 22 | 8 |
| Bundesliga | 18 | SCF 1–3 MUN | 1.63 / 2.33 | 22 | 8 |
| Ligue 1 | 18 | PSG 2–0 LYON | 1.37 / 0.82 | 22 | 8 |
| UCL | 36 | MUN 2–2 ARS | 2.19 / 2.85 | 22 | 8 |

`get_game` returns xG, player lines/starters, and the books' lines in one 5-credit call. `get_lineups` returns formations and starting XIs (5 credits). `get_odds` returns per-book opening/closing lines and de-vigged closing probabilities (5 credits).

EPL `get_lineups` sample: Liverpool 4-2-3-1, Brighton 4-2-3-1, 11 starters each.

## 3. Historical sample

| Check | Result |
|---|---|
| EPL 2012 xG shot map (Arsenal) | 400 located shots, 69 goals, xG 48.4 |
| EPL 2017 lineups (HUD vs ARS) | 11 starters each, formations present |
| EPL 2017 odds | Only **2 books**; opening/closing fields incomplete |
| EPL 2026 odds | 6–8 books; archive/final sources; opening/closing available |

The historical odds limitation matches StrikerAPI's own docs: opening/closing coverage starts June 2020. For CLV backtests, use **2020-06 onward**, not 2017.

## 4. Cost of a real backfill

StrikerAPI has no bulk export; `get_game` is the most efficient one-call-per-match path because it includes xG, lineups, and odds.

Approximate matches per season for the six competitions:

```text
EPL 380 + La Liga 380 + Serie A 380 + Bundesliga 306 + Ligue 1 306 + UCL ~125
= ~1,877 matches/season
```

Approximate credit cost:

```text
~1,877 matches × 5 credits = ~9,400 credits/season
1 season:  ~9,400 credits
2 seasons: ~18,800 credits
3 seasons: ~28,200 credits
5 seasons: ~47,000 credits
```

Plans:

| Plan | Credits/month | Price | Fit |
|---|---:|---:|---|
| Free | 500 | $0 | spot checks only |
| Starter | 10,000 | $19 | ~1 season |
| Pro | 30,000 | $49 | ~3 seasons |
| Scale | 125,000 | $149 | 5+ seasons |

**The free 500 credits are not enough for a real backfill.** They are enough for this audit and a few sample matches.

## 5. Existing DB xG coverage

The project already stores `match_stats.home_xg` / `away_xg`, but only:

```text
297 / 29,187 matches (1.0%)
```

That is not enough for rolling xG features. External xG is genuinely new information, not a duplicate.

## 6. Important timing/leakage constraints

- **Lineups** are published roughly 20–60 minutes before kickoff. They cannot be used in the current 48h model. Either:
  - do not use lineups in the 48h model, or
  - build a separate late model at T-60min with its own odds snapshot.
- **xG** is post-match data. For features, use only matches played before the target kickoff, and compute rolling xG as-of each kickoff.
- StrikerAPI's xG values are refit, not point-in-time. For strict backtests, use the shot locations and recompute xG from prior shots only.
- **Odds** before June 2020 are partial; use 2020+ for opening/closing CLV.

## 7. Recommendation

1. **Use StrikerAPI** for xG, lineups and multi-book odds.
2. Do **not** buy a plan for 5 seasons yet. First choose the minimum viable horizon:
   - 1 season: Starter $19
   - 3 seasons: Pro $49
   - 5 seasons: Scale $149
3. For the first model rebuild, 3 seasons is the sensible minimum for walk-forward validation: train on seasons 1–2, validate on season 3.
4. Add API-Football only if injuries/suspensions become a required feature; StrikerAPI gives lineups but not a dedicated injury history.
5. Do not use lineups in the 48h model; keep them for a separate late model.

## 8. Next implementation step

After choosing the horizon:

1. Add a StrikerAPI adapter with `get_game` and pagination.
2. Backfill match-level xG, lineups, and odds into a staging table.
3. Build **as-of** rolling features (xG for/against, shots, lineup strength, rest, odds movement).
4. Run feature ablation and walk-forward validation against the market baseline.
5. Only if Brier/logloss and CLV improve: train a new champion, then paper-test with 500 forward bets.

No code or data changes were made by this audit.
