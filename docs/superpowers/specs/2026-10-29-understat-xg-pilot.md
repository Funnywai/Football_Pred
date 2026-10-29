# Understat xG pilot — 2026-10-29

> Status: free research pilot. No production schema/model changes. Shadow ledger remains disabled.
> Data: Understat top-five leagues, seasons 2017/18–2025/26; existing DB results/odds/features.

## 1. Verdict

**xG adds a small amount of information, but it is not enough to beat the market.**

- xG improves the raw model slightly, but the improvement is not statistically clear.
- The xG + market blend is essentially **market-level**, not better.
- No league shows a consistent xG edge.
- **Do not pay for StrikerAPI xG alone.** The next useful test would be a different data category (lineups/injuries), not more xG.

## 2. Data and coverage

| Item | Value |
|---|---:|
| Understat matches fetched | 16,111 |
| Matches mapped to DB | 14,536 (90.2%) |
| Matches with complete rolling xG features | 12,871 |
| Train rows (before 2023-07) | 9,702 |
| Calibration rows (2023-24) | 1,603 |
| Test rows (2024-25) | 1,566 |
| Leagues | EPL, La Liga, Serie A, Bundesliga, Ligue 1 |

Understat was fetched directly from `getLeagueData/{league}/{season}` (no API key, no paid credits). Team/date matching used normalized names plus fuzzy matching; 10% of matches remain unmapped, mostly historical team-name/date mismatches.

## 3. Features

Baseline: the deployed feature set (Elo, attack/defence, form, rest, shots/SoT, H2H, market prior).

xG additions (18 columns):

- rolling xG for/against over 3, 5, 10 matches, home and away
- xG difference and xGA difference over 3, 5, 10 matches

All rolling windows use only matches strictly before the target kickoff.

## 4. Test results — 2024-25 (n=1,566)

| Variant | Brier | Logloss |
|---|---:|---:|
| Market | **0.191077** | **0.965074** |
| Base model | 0.194206 | 0.980248 |
| xG model | 0.193103 | 0.975245 |
| Base + market blend (w=0.20) | 0.191363 | 0.966418 |
| xG + market blend (w=0.20) | 0.191158 | 0.965482 |

### xG model vs base model

- Brier: **-0.001102**, 95% CI [-0.002257, +0.000062]
- Logloss: **-0.005003**, 95% CI [-0.010271, +0.000368]

Directionally better, but the CI includes zero.

### xG model vs market

- Brier: **+0.002026**, 95% CI [+0.000577, +0.003477] → worse
- Logloss: **+0.010171**, 95% CI [+0.003153, +0.017249] → worse

### xG blend vs market

- Brier: **+0.000081**, 95% CI [-0.000214, +0.000378] → indistinguishable
- Logloss: **+0.000408**, 95% CI [-0.000992, +0.001821] → indistinguishable

### xG blend vs base blend

- Brier: **-0.000205**, 95% CI [-0.000439, +0.000029]
- Logloss: **-0.000936**, 95% CI [-0.001973, +0.000135]

The xG blend is marginally better than the base blend, but not better than the market.

## 5. By league

xG blend logloss vs market:

| League | n | xG blend | Market | Difference |
|---|---:|---:|---:|---:|
| Bundesliga | 270 | 0.998443 | 0.994855 | +0.003588 (worse) |
| EPL | 341 | 0.976452 | 0.976192 | +0.000260 (worse) |
| La Liga | 342 | 0.945632 | 0.946949 | -0.001317 (better) |
| Ligue 1 | 272 | 0.987415 | 0.988309 | -0.000894 (better) |
| Serie A | 341 | 0.930825 | 0.930021 | +0.000804 (worse) |

Two leagues are marginally better and three are worse; there is no consistent edge.

## 6. Feature importance

Market features still dominate. xG features enter the top 20, but they do not displace the market:

```text
market_away          10858
market_home           6317
market_draw           1624
away_xg_for_3          689
elo_home               680
defense_diff           663
elo_diff               635
defense_away           633
home_xg_against_10     560
defense_home           549
attack_diff            546
away_xg_against_10     539
xga_diff_3             534
away_xg_against_5      509
attack_home            505
home_xg_for_3          501
home_xg_against_3      500
shot_accuracy_home     484
xga_diff_10            484
xg_diff_10             475
```

This confirms the model is still a **market + team-strength** model; xG is a secondary signal.

## 7. Decision

1. **Do not buy StrikerAPI for xG alone.** The free pilot shows xG does not produce a market-beating edge.
2. **Do not enable shadow or real money.**
3. If continuing, test a genuinely different information category:
   - lineups / injuries / suspensions
   - multi-book opening→closing movement
   - late model at T-60min (separate from the 48h model)
4. If none of those is available or testable, **stop the betting experiment** and keep CLV monitoring only.

## 8. Cost

**$0.** Understat was fetched directly; no StrikerAPI credits were used for this pilot. No production code or schema changes.
