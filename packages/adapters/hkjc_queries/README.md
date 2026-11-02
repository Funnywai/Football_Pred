# HKJC captured GraphQL queries

HKJC accepts only query strings that its own website sends. These files are
captured from the official site and replayed unchanged, apart from trimming
surrounding whitespace. The loader (`loader.py`) fails closed when a file is
missing, empty, or not GraphQL.

## Provenance

Captured 2026-11-01 from the official HKJC football site.

| File | Official operation | Notes |
| --- | --- | --- |
| `had.graphql` | `query matchList` | 3,063 chars; same text as HDC/HIL |
| `hdc.graphql` | `query matchList` | HDC group uses `fbOddsTypes: ["HDC","EDC"]` |
| `hil.graphql` | `query matchList` | HIL group uses `fbOddsTypes: ["HIL","EHL"]` |
| `match_results.graphql` | `query matchResults` | date-based (`startDate`/`endDate`) |

- Endpoint: `https://info.cld.hkjc.com/graphql/base/`
- Source: official `https://bet.hkjc.com/football` JavaScript bundle (`main.js`)
- Query version: `captured-2026-11` (`FP_HKJC_QUERY_VERSION`)
- Live sample match: `50079081` (front-end id `FB8142`, RPL, 2026-11-01)
- Live results sample: `startDate=2026-10-30`, `endDate=2026-10-31`,
  `startIndex=1`, `endIndex=10`, `teamId=None` (10 matches, total 163)

The live site uses **one parameterized `matchList` query** for all three
markets; only the `fbOddsTypes` variable changes. Identical text in
`had.graphql`, `hdc.graphql` and `hil.graphql` is expected, not a capture bug.

## Capture procedure (re-capture)

1. Run `uv run playwright install chromium`.
2. Run `uv run python scripts/capture_hkjc_queries.py`.
3. In the opened browser, open HAD, HDC and HIL for one match, and a finished
   result page if available.
4. Press Enter. The script writes all four files.

The script identifies a request by `operationName`/`fbOddsTypes` first, then by
a unique query-text match. It refuses to write a missing key or a capture whose
text does not start with the expected official operation. Duplicate `matchList`
text across HAD/HDC/HIL is allowed by design.

## Live shapes the adapter consumes

Odds (`matchList` response):

```
data.matches[] -> id, matchDate, foPools[]
  foPools[] -> oddsType, status, updateAt, lines[]
    lines[] -> condition, status, main, combinations[]
      combinations[] -> str ("H"/"D"/"A"/"L"), status,
                        offerEarlySettlement ("Offer"/"NoOffer"/"TempNotOffer"),
                        currentOdds (string)
```

Only `SELLINGSTARTED` pools and `AVAILABLE` lines/combinations become bettable.
Odds are converted from strings to `Decimal`. `offerEarlySettlement` is
normalized to a boolean (`"Offer"` -> true, `"NoOffer"`/`"TempNotOffer"` ->
false) and the raw string is preserved on each line.

Results (`matchResults` response):

```
data.matches[] -> id, matchDate, results[], poolInfo{}
  results[] -> homeResult, awayResult, payoutConfirmed, stageId, resultType, sequence
  poolInfo  -> payoutRefundPools[], refundPools[]   (match level)
```

Full-time is `stageId == 5`, `resultType == 1`, `payoutConfirmed == true`, with
non-negative scores; the highest `sequence` wins.

## Rules

- Never hand write or edit these query strings. If HKJC changes its whitelist,
  re-run the capture and update `FP_HKJC_QUERY_VERSION`.
- Keep `FP_HKJC_RESULT_SEMANTICS` at `unverified` until a known UCL extra-time
  match has been checked against the live `matchResults` response.
- `payoutRefundPools` and `refundPools` live at `match.poolInfo`. Both appeared
  as lists of strings in the live sample; objects are also accepted by the
  parser. Re-run the capture if the live response uses a third shape.
- `homeResult`/`awayResult` are stored as raw values. They are never treated as
  90-minute scores; `goals_90_from_result` returns `None` unless the result is
  complete, and it raises for UCL while semantics are `unverified`.

## Verification gates

### Gate A: UCL result semantics — PENDING

Capture `matchResults` for one known UCL match that went to extra time. Compare
`homeResult` and `awayResult` against the known 90-minute score and the known
final score. Only set `FP_HKJC_RESULT_SEMANTICS=regulation_time` when the fields
match the 90-minute score. Otherwise leave it unverified and UCL settlement
stays blocked.

Status: **not executed.** The 2026-11-01 live sample contains no UCL match, so
there is no evidence yet. Do not claim 90-minute semantics.

### Gate B: refund pool shape — SHAPE RECORDED, REFUND SEMANTICS CONSERVATIVE

Live evidence from 10 finished matches on 2026-10-30/31:

- `payoutRefundPools` and `refundPools` are at `match.poolInfo`, not at the
  result row.
- Both are lists of strings in this sample; the parser also accepts objects.
- `refundPools` was empty for all 10 matches.
- `payoutRefundPools` enumerated every settled pool, including `HAD`, `HDC` and
  `HIL`, even for a normal 4-1 result. It is a payout/refund coverage list, not
  a refund marker.

Consequence: the adapter stores `payoutRefundPools` as
`payout_refund_pool_codes` for provenance, while `refunded_markets()` trusts
only `refundPools`. No actual refunded-pool fixture has been observed yet; a
refund must not be inferred from `payoutRefundPools`.

Evidence location: `.superpowers/sdd/hkjc_live/results.json` (sample), mirrored
for tests at `tests/fixtures/hkjc/results.json`; covered by
`test_live_payout_refund_pools_are_not_refund_markets` and
`test_match_level_refund_pools_accept_strings_and_objects`.
