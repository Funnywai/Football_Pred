# Model Edge Audit — 2026-10-28

> Status: read-only audit. Shadow ledger disabled; production ledger has 0 bets.
> Scope: champion #7, live CLV records from 2026-10-18 to 2026-10-27.
> Question: which subgroups show a real edge, and which do not?

---

## 1. Executive verdict

**There is no credible profit edge in any subgroup.**

The model shows a **CLV-only edge** in two places:

- **Draws**: 71.0% beat rate, Wilson lower 61.1%
- **Closing odds 3–5 and 5–10**: 67.9% / 68.3% beat rate, Wilson lower 58.7% / 53.0%

But neither converts into profit:

- Flat 1-unit draw betting: **ROI -31.5%**, 95% CI [-58.9%, -0.9%]
- Current max-edge shadow rule: **ROI -41.8%**, 95% CI [-66.5%, -14.9%]

The current **max-edge, one-bet-per-match** rule is the worst of the tested rules. The least-bad rule (closing odds ≤ 3) is still **-4.7% ROI** with a weak CLV lower bound (38.6%), so it is not a green light either.

**Decision: do not enable shadow again, do not go live, and do not try to fix this with a selection threshold. The model needs recalibration or redesign.**

---

## 2. Data and method

| Item | Value |
|---|---:|
| Matches with confirmed labels | 93 |
| Outcome rows | 279 |
| Matches with a stored deployed prediction | 68 |
| Leagues | 6 |
| Date range | 2026-10-18 → 2026-10-27 |
| Results | H 46, D 18, A 29 |

Leagues: EPL 15, LALIGA 16, SERIEA 19, BUNDESLIGA 11, LIGUE1 14, UCL 18 matches.

Methods:

- **Probability**: deployed blended probability (`clv_records.model_prob`), not the raw gradient-boosting output.
- **Market**: de-vigged closing probability (`clv_records.closing_prob`).
- **Calibration**: per-match multiclass Brier and logloss, paired against the market; bootstrap 95% CIs over matches.
- **CLV**: `model_prob - closing_prob`; beat = model probability ≥ closing probability; Wilson lower bound.
- **ROI**: flat 1-unit stake at the closing decimal odds; win pays `odds − 1`, loss pays `−1`; bootstrap 95% CI.
- **Rule simulation**: one bet per match, chosen by the stated rule; settled at closing odds. This is a **post-hoc proxy** for the live shadow, not the exact execution price.
- **Credible edge** requires all of: at least 20 bets, ROI CI lower > 0, and CLV Wilson lower > 50%.

Limitations:

- 93 matches is a small sample; subgroup CIs are wide.
- 25 matches have CLV but no stored prediction, so rule simulations use 68 matches.
- Closing odds are a proxy for execution; the live shadow executes at the latest pre-kickoff price.
- Multiple subgroup comparisons increase the chance of a false positive; no subgroup survives the credible-edge test.
- Champion #7 only; no cross-model comparison.

---

## 3. Overall result

### Calibration

| Metric | Model | Market | Delta (model − market) | 95% CI of delta |
|---|---:|---:|---:|---:|
| Brier | 0.1793 | 0.1745 | **+0.0049** | [-0.0039, +0.0136] |
| Logloss | 0.9211 | 0.8959 | **+0.0253** | [-0.0125, +0.0622] |

The model is **worse on both point estimates**, but the CIs include zero. The model is better on Brier in only **36/93** matches and on logloss in **38/93**. This is not evidence of an edge; it is at best “not distinguishable from the market, with a worse point estimate.”

### CLV

| Metric | Value |
|---|---:|
| n | 279 |
| Beat rate | 55.56% |
| Wilson lower | **49.69%** |
| Mean edge | ≈ 0 |

The overall CLV lower bound is **below 50%**, so the overall CLV gate does not pass.

---

## 4. Calibration by league

| League | Matches | Model Brier | Market Brier | Delta Brier | 95% CI | Model better |
|---|---:|---:|---:|---:|---|---:|
| BUNDESLIGA | 11 | 0.2004 | 0.1982 | +0.0023 | [-0.0130, +0.0173] | 5/11 |
| EPL | 15 | 0.1871 | 0.1885 | -0.0014 | [-0.0227, +0.0128] | 5/15 |
| LALIGA | 16 | 0.1788 | 0.1720 | +0.0068 | [-0.0001, +0.0125] | 3/16 |
| LIGUE1 | 14 | 0.1972 | 0.1899 | +0.0073 | [-0.0146, +0.0294] | 6/14 |
| SERIEA | 19 | 0.1523 | 0.1542 | -0.0019 | [-0.0110, +0.0074] | 12/19 |
| UCL | 18 | 0.1751 | 0.1600 | +0.0151 | [-0.0204, +0.0499] | 5/18 |

No league has a calibration advantage with a CI that excludes zero.

- EPL and SERIEA are slightly better on point estimates, but the CIs cross zero.
- LALIGA is worse on logloss with a CI that is almost entirely positive (logloss delta +0.0363, CI [+0.0076, +0.0640]).
- UCL is worse on both point estimates, but the sample is too small to be conclusive.

**Calibration edge: none.** If anything, the model is overconfident in LALIGA and UCL.

---

## 5. CLV by subgroup

### By league

| League | n | Beat | Wilson lower | Mean edge |
|---|---:|---:|---:|---:|
| BUNDESLIGA | 33 | 48.5% | 32.5% | 0.0000 |
| EPL | 45 | 55.6% | 41.2% | 0.0000 |
| LALIGA | 48 | 60.4% | 46.3% | -0.0000 |
| LIGUE1 | 42 | 61.9% | 46.8% | -0.0000 |
| SERIEA | 57 | 50.9% | 38.3% | 0.0000 |
| UCL | 54 | 55.6% | 42.4% | -0.0000 |

No league has a Wilson lower bound above 50%. LIGUE1 and LALIGA look best, but both lower bounds are ~46–47%.

### By closing odds

| Odds bucket | n | Beat | Wilson lower | Mean edge | Flat ROI |
|---|---:|---:|---:|---:|---:|
| < 2 | 66 | 31.8% | 21.9% | -4.02% | -0.8% |
| 2–3 | 55 | 47.3% | 34.7% | +0.45% | -13.0% |
| 3–5 | 112 | **67.9%** | **58.7%** | +0.96% | **-21.4%** |
| 5–10 | 41 | **68.3%** | **53.0%** | +2.83% | **-39.5%** |
| ≥ 10 | 5 | 80.0% | 37.6% | +3.18% | -100.0% |

This is the central finding: **odds 3–5 and 5–10 have a CLV edge, but flat betting them loses money.** The model is good at being on the “right side” of closing-line movement for mid/long odds, but not good at picking the actual winner.

### By outcome

| Outcome | n | Beat | Wilson lower | Mean edge | Flat ROI |
|---|---:|---:|---:|---:|---:|
| H | 93 | 52.7% | 42.6% | +0.04% | -15.0% |
| D | 93 | **71.0%** | **61.1%** | +1.29% | **-31.5%** |
| A | 93 | 43.0% | 33.4% | -1.33% | -10.4% |

Draws have the strongest CLV signal and a **negative ROI with a CI excluding zero** (flat draw betting: -31.5%, 95% CI [-58.9%, -0.9%]). This is a calibration failure: the model systematically overestimates draws relative to the market, so it “beats the close” on draws while losing money.

**CLV-only edge: draws and odds 3–10. Profit edge: none.**

---

## 6. Rule-level ROI

All rules use one bet per match and settle at closing odds. Flat 1-unit stake.

| Rule | Bets | Win rate | Avg odds | ROI | 95% CI | CLV beat | CLV lower |
|---|---:|---:|---:|---:|---|---:|---:|
| **shadow_max_edge** | 68 | 26.5% | 3.62 | **-41.8%** | [-66.5%, -14.9%] | 64.7% | 52.8% |
| highest_prob | 68 | 32.4% | 3.10 | -32.3% | [-57.8%, -3.6%] | 66.2% | 54.3% |
| odds_cap_5 | 60 | 35.0% | 2.93 | -23.0% | [-52.2%, +9.4%] | 63.3% | 50.7% |
| **odds_cap_3** | 39 | 51.3% | 2.06 | **-4.7%** | [-37.0%, +28.3%] | 53.8% | 38.6% |
| edge_1pct | 13 | 23.1% | 4.44 | -34.5% | [-100%, +43.9%] | 69.2% | 42.4% |
| edge_2pct | 1 | 0.0% | 4.05 | -100% | — | 100% | 20.7% |
| favorite | 17 | 64.7% | 1.41 | -15.1% | [-46.1%, +14.0%] | 52.9% | 31.0% |
| underdog | 62 | 14.5% | 4.27 | **-55.3%** | [-80.8%, -25.6%] | 67.7% | 55.4% |
| all_positive | 105 | 28.6% | 3.70 | -26.6% | [-51.4%, +0.6%] | 64.8% | 55.3% |

Key conclusions:

1. **The current shadow rule is the worst tested rule.** Selecting the maximum positive edge concentrates the book on underdogs and draws, and loses heavily.
2. **Highest-probability positive edge** and **odds cap 5** improve ROI but remain negative.
3. **Odds cap 3** is the least bad (-4.7%), but its CLV lower bound is 38.6% and its ROI CI crosses zero. It is not evidence of an edge.
4. **Favorites only** loses -15.1%; **underdogs only** loses -55.3%. The problem is not just longshot selection; the model has no reliable side.
5. **All positive-edge outcomes** lose -26.6%, confirming this is not an artifact of one-per-match selection.

### Flat ROI by league (all outcomes)

| League | ROI | 95% CI |
|---|---:|---|
| BUNDESLIGA | -6.9% | [-57.3%, +53.4%] |
| EPL | -16.9% | [-52.7%, +24.9%] |
| LALIGA | -23.5% | [-56.0%, +11.6%] |
| LIGUE1 | -17.7% | [-53.8%, +21.6%] |
| SERIEA | -26.9% | [-55.9%, +6.1%] |
| UCL | -16.5% | [-54.4%, +28.1%] |

No league has positive ROI. All CIs include zero, so no league is even reliably profitable or reliably unprofitable on its own.

---

## 7. Which subgroups have an edge?

### Profit edge

**None.**

No subgroup with at least 20 bets has:

- ROI CI lower > 0, and
- CLV Wilson lower > 50%.

The best-looking cells (draws, odds 3–5, odds 5–10) have positive CLV but negative ROI. Small positive cells such as `A / odds < 2` (+3.9%, n=15) and `D / odds 2–3` (+10.4%, n=5) are too small to be credible and have CIs that include zero.

### CLV-only edge

| Subgroup | CLV beat | Wilson lower | ROI | Verdict |
|---|---:|---:|---:|---|
| Draws | 71.0% | 61.1% | -31.5% | CLV edge, no profit edge |
| Odds 3–5 | 67.9% | 58.7% | -21.4% | CLV edge, no profit edge |
| Odds 5–10 | 68.3% | 53.0% | -39.5% | CLV edge, no profit edge |
| Underdog max-edge | 67.7% | 55.4% | -55.3% | CLV edge, strongly negative profit |
| All positive-edge | 64.8% | 55.3% | -26.6% | CLV edge, no profit edge |

### Calibration edge

**None.** EPL and SERIEA are slightly better on point estimates, but their CIs include zero. LALIGA is worse on logloss with a CI excluding zero. No league is reliably better than the market.

### League edge

**None.** No league has CLV Wilson lower > 50% or positive ROI.

---

## 8. Why the model looks “right” on CLV but loses money

The first live shadow bet is a clean example:

- Match: Paris Saint Germain vs Lyon, 2026-10-26
- Pick: A (Lyon), odds 7.50
- Model probability at prediction: 15.23%
- Market probability at 48h: 14.93% → signal edge +0.31%
- Execution edge at 7.50: +3.48%
- Closing probability: 10.65% → model beat the close by +4.58 pp
- Result: PSG 2–0 → the bet lost.

The model was **on the right side of the closing line** and still lost. That is normal for a longshot; at 15% probability, the bet loses about 85% of the time. But the broader pattern is not just variance:

1. **Max-edge selection concentrates on longshots.** The model’s largest positive edges are on draws and underdogs, not on the most likely outcome.
2. **The model overestimates draws and longshots.** Draws have a 71% CLV beat rate but -31.5% flat ROI. This is the classic favorite–longshot bias: the model’s probability is higher than the market’s, but not high enough to overcome the true outcome frequency.
3. **CLV is a line-movement metric, not a profit metric.** It measures whether the model’s probability is above the closing probability, not whether the bet wins. A model can beat the close and lose money, especially on high-variance outcomes.
4. **The overall model is not better than the market.** Brier and logloss point estimates are worse; the CIs include zero. There is no calibration advantage to exploit.

---

## 9. Decision

### Do now

1. **Keep shadow disabled.** It is already `SHADOW_LEDGER_ENABLE=false`.
2. **Keep production at 0 bets.** Do not put real money anywhere.
3. **Do not tune the selection threshold as a fix.** The current max-edge rule is the worst; odds-cap and highest-prob rules improve but remain negative.
4. **Treat this as a model problem, not a betting-rule problem.**

### If research continues

The only worthwhile hypotheses from this audit:

- **Draw calibration**: the model has a CLV edge on draws but loses money; recalibrate draw probabilities and re-test.
- **Longshot calibration**: odds 5–10 have a CLV edge but -39.5% ROI; the model is overconfident on longshots.
- **Odds-cap-3 / highest-prob** as control rules, not as a production candidate.

The next model must beat the market on **out-of-sample Brier/logloss**, show **CLV Wilson lower > 50%**, and produce **positive ROI with a CI lower > 0** over at least 500 forward bets before any real money is considered.

### If no model improvement

Stop the betting experiment. The current system has no demonstrated profit edge; continuing to collect bets will only produce more evidence of that.

---

## 10. Acceptance / reproducibility

Data source: live `clv_records` joined to `predictions`, `matches`, `leagues`, and `results` on the host database, snapshot 2026-10-28.

Key checks:

```text
matches with labels: 93
outcome rows: 279
matches with stored predictions: 68
overall CLV: 55.56% beat, Wilson lower 49.69%
shadow max-edge ROI: -41.8%, 95% CI [-66.5%, -14.9%]
credible profit subgroup: NONE
```

This audit is read-only. It did not change the model, ledger, shadow data, or production configuration.

---

## 11. Addendum — raw model vs blend vs stacker (2026-10-29)

The first audit used the deployed blended probability. This addendum tests whether the **raw model** or a **model+market stacker** adds information beyond the market on the 73 eval matches that have both a 48h prior and closing odds.

| Variant | Brier | Logloss | CLV beat | CLV lower | Rule ROI | Rule bets |
|---|---:|---:|---:|---:|---:|---:|
| Market | **0.17825** | **0.92025** | 53.9% | 47.3% | — | 0 |
| Raw LightGBM | 0.18018 | 0.93278 | 52.5% | 45.9% | -43.7% | 73 |
| Calibrated model | 0.18088 | 0.93507 | 53.0% | 46.4% | -40.1% | 73 |
| Blend w=0.20 | 0.17858 | 0.92238 | 56.2% | 49.5% | -40.1% | 73 |
| Stacker model+market | 0.18003 | 0.92877 | 48.9% | 42.3% | -36.8% | 73 |
| Stacker market-only | 0.17881 | 0.92343 | 52.5% | 45.9% | -24.9% | 73 |

Key observations:

- The raw model is **worse than the market** on both Brier and logloss.
- The model+market stacker is also worse than the market; it does not recover an incremental signal.
- The raw model's max-edge rule has a **91.8% CLV beat rate** but **-43.7% ROI**. That is a selection artifact: the raw model is systematically overconfident, so max-edge selection chooses the most overestimated outcome, not the most valuable one.
- The blend dampens the overconfidence (CLV 56.2%, lower 49.5%) but still loses -40.1%.
- Feature importance is dominated by market features:

```text
market_home   13851
market_away   13759
market_draw    5669
elo_diff       5202
elo_home       2248
attack_home    2197
attack_diff    2147
attack_away    2136
defense_diff   1838
defense_away   1753
```

The model is primarily a **market + team-strength** model. It has no demonstrated incremental information on this sample. Adding more variations of the same features is unlikely to change that; the next attempt needs genuinely new information (lineups/injuries, xG/xA, fixture congestion/travel, motivation, sharper multi-book closing lines) or should stop.

**Go/no-go:** do not start a model rebuild on the existing feature set. First decide whether new data sources are available; if not, stop the betting experiment and keep CLV monitoring only.
