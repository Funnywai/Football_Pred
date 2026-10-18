"""Read-only, reproducible backtest of the deployed 1x2 production rule.

The rule replicated here is exactly the one serving uses:

1. ``p_model`` = champion artifact ``predict_proba`` on the eval feature row.
2. ``p_prior`` = the eval frame's 48h de-vigged market columns
   (``market_home`` / ``market_draw`` / ``market_away``).
3. ``p_blend = blend_probs(p_model, p_prior, ml_blend_weight)``.
4. ``signal_edge = p_blend - p_prior[outcome]``.
5. Execution price = the latest HKJC HAD snapshot strictly before kickoff
   (``load_market_priors(..., 0)``), falling back to the football-data close.
6. A bet is selected when ``signal_edge > ml_value_edge_threshold`` AND
   ``p_blend * execution_odds > 1.0 + ml_exec_edge_buffer``.
7. Kelly fraction = ``kelly_fraction(p_blend, execution_odds)``; the report
   carries both a flat-1u ROI (primary) and a stake-weighted Kelly ROI.
8. CLV = ``p_blend - closing_de_vigged_prob`` for selected bets, plus the
   fraction of bets whose blended probability beats the close. CLV is NOT
   profit: the execution price and the "close" are the same latest
   pre-kickoff snapshot, so this measures model-vs-close probability, not a
   price taken earlier versus a later close.
9. Flat ROI = ``mean(payout) - 1`` where ``payout = execution_odds`` on a win
   and ``0`` otherwise.

Everything except ``run_backtest`` is pure and unit-testable without a DB.
``run_backtest`` only reads: it never commits, writes, or migrates.
"""

from __future__ import annotations

import calendar
import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.ml.dataset import build_dataset, load_market_priors
from app.ml.features import FEATURE_COLUMNS, MatchRow
from app.ml.models import TARGET_1X2, evaluate_1x2, load_artifact, predict_proba
from app.ml.predict import blend_probs
from app.ml.registry import get_champion
from app.ml.value import kelly_fraction

OUTCOMES_1X2 = ("H", "D", "A")
_OUTCOME_INDEX = {outcome: index for index, outcome in enumerate(OUTCOMES_1X2)}

NOTES = (
    (
        "CLV compares the blended probability to the closing de-vigged probability from the "
        "same latest pre-kickoff snapshot; it is not a price-taken-vs-later-close measure and "
        "is not profit."
    ),
    (
        "Historical close odds are HKJC where available and B365 (football-data) otherwise, "
        "so ROI and CLV are directional, not exact live-venue results."
    ),
    (
        "Flat 1u ROI is the primary comparable number; Kelly ROI is stake-weighted using the "
        "configured fractional Kelly sizing (whole-dollar floor and minimum stake ignored)."
    ),
    (
        "execution_source_counts covers every outcome row with an execution price, not only "
        "selected bets."
    ),
    "Eval is the out-of-sample temporal slice; the champion was not trained on it.",
)


@dataclass(frozen=True)
class Candidate:
    """One (match, outcome) row of the eval frame with its prices and probabilities."""

    match_id: int
    kickoff_time: datetime
    outcome: str
    label: str
    p_model: float
    p_prior: float | None
    p_blend: float
    exec_odds: float | None
    exec_source: str
    closing_prob: float | None


@dataclass(frozen=True)
class SelectedBet:
    """A candidate that cleared the value test, with its Kelly stake and 1u payout."""

    candidate: Candidate
    stake_fraction: float
    payout: float


@dataclass(frozen=True)
class BacktestParams:
    """The deployed rule's thresholds and sizing knobs."""

    threshold: float
    exec_edge_buffer: float
    kelly_multiplier: float
    max_stake_fraction: float


@dataclass(frozen=True)
class ReportContext:
    """Everything the report needs that is not derived from the candidates."""

    config: dict
    since: datetime | None
    until: datetime | None
    model_metrics: dict
    market_metrics: dict
    blend_metrics: dict


def passes_value_test(
    p_blend: float,
    p_prior: float | None,
    exec_odds: float | None,
    *,
    threshold: float,
    buffer: float,
) -> bool:
    """The deployed value test: signal edge AND execution-price safety margin.

    ``signal_edge = p_blend - p_prior`` must strictly exceed ``threshold`` and
    ``p_blend * exec_odds`` must strictly exceed ``1 + buffer``. A missing prior
    or execution price can never be a bet.
    """
    if p_prior is None or exec_odds is None:
        return False
    if p_blend - p_prior <= threshold:
        return False
    return p_blend * exec_odds > 1.0 + buffer


def select_bets(candidates: Sequence[Candidate], params: BacktestParams) -> list[SelectedBet]:
    """Apply the value test and fractional-Kelly sizing to every candidate.

    ``stake_fraction = min(kelly_fraction(p_blend, odds) * kelly_multiplier,
    max_stake_fraction)`` — the same fractional Kelly and 5% cap the ledger uses,
    expressed as a fraction of bankroll. ``payout`` is the per-1u return at the
    execution price (``odds`` on a win, ``0`` otherwise).
    """
    bets: list[SelectedBet] = []
    for candidate in candidates:
        odds = candidate.exec_odds
        if odds is None:
            continue
        if not passes_value_test(
            candidate.p_blend,
            candidate.p_prior,
            odds,
            threshold=params.threshold,
            buffer=params.exec_edge_buffer,
        ):
            continue
        stake = min(
            kelly_fraction(candidate.p_blend, odds) * params.kelly_multiplier,
            params.max_stake_fraction,
        )
        payout = odds if candidate.label == candidate.outcome else 0.0
        bets.append(SelectedBet(candidate=candidate, stake_fraction=stake, payout=payout))
    return bets


def flat_roi(payouts: Sequence[float]) -> float | None:
    """Flat 1u ROI: ``mean(payout) - 1``; ``None`` for an empty sample."""
    if not payouts:
        return None
    return sum(payouts) / len(payouts) - 1.0


def kelly_roi(stakes: Sequence[float], payouts: Sequence[float]) -> float | None:
    """Stake-weighted ROI: ``sum(stake * payout) / sum(stake) - 1``.

    ``None`` when there is no stake (empty sample or every Kelly fraction is 0).
    """
    total = sum(stakes)
    if total <= 0.0:
        return None
    weighted = sum(stake * payout for stake, payout in zip(stakes, payouts, strict=True))
    return weighted / total - 1.0


def normal_ci95(values: Sequence[float]) -> list[float] | None:
    """Normal 95% CI: ``mean ± 1.96 * sd / sqrt(n)``; ``None`` when ``n < 2``."""
    array = np.asarray(values, dtype=float)
    if array.size < 2:
        return None
    mean = float(array.mean())
    half = 1.96 * float(array.std(ddof=1)) / math.sqrt(array.size)
    return [mean - half, mean + half]


def wilson_interval(successes: int, n: int, z: float = 1.96) -> list[float] | None:
    """Wilson score interval for a binomial fraction; ``None`` when ``n <= 0``."""
    if n <= 0:
        return None
    proportion = successes / n
    denominator = 1.0 + z * z / n
    center = (proportion + z * z / (2.0 * n)) / denominator
    half = (
        z
        * math.sqrt(proportion * (1.0 - proportion) / n + z * z / (4.0 * n * n))
        / denominator
    )
    return [max(0.0, center - half), min(1.0, center + half)]


def _mean_or_none(values: Sequence[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _kelly_ci95(stakes: Sequence[float], payouts: Sequence[float]) -> list[float] | None:
    """Normal CI for the stake-weighted ROI, computed on per-bet weighted returns.

    ``r_i = stake_i * payout_i / mean_stake - 1`` has mean equal to ``kelly_roi``,
    so the normal interval on ``r_i`` is the interval for the Kelly ROI.
    """
    total = sum(stakes)
    if total <= 0.0 or not stakes:
        return None
    mean_stake = total / len(stakes)
    returns = [
        stake * payout / mean_stake - 1.0
        for stake, payout in zip(stakes, payouts, strict=True)
    ]
    return normal_ci95(returns)


def build_report(
    candidates: Sequence[Candidate],
    params: BacktestParams,
    context: ReportContext,
) -> dict:
    """Assemble the deterministic, JSON-serializable backtest report.

    Candidates are sorted by ``(match_id, outcome)`` with outcomes in H/D/A order.
    Every metric is ``None`` when its sample is empty; ``bet_rate`` is ``0.0``
    when there are no outcome rows. No division by zero is possible.
    """
    ordered = sorted(
        candidates,
        key=lambda candidate: (candidate.match_id, _OUTCOME_INDEX[candidate.outcome]),
    )
    bets = select_bets(ordered, params)
    stakes = [bet.stake_fraction for bet in bets]
    payouts = [bet.payout for bet in bets]

    clv_edges: list[float] = []
    clv_beats: list[float] = []
    fair_payouts: list[float] = []
    for bet in bets:
        closing = bet.candidate.closing_prob
        if closing is None:
            continue
        clv_edges.append(bet.candidate.p_blend - closing)
        clv_beats.append(1.0 if bet.candidate.p_blend >= closing else 0.0)
        if closing > 0.0:
            fair_payouts.append(
                1.0 / closing if bet.candidate.label == bet.candidate.outcome else 0.0
            )

    by_outcome: dict[str, dict] = {}
    for outcome in OUTCOMES_1X2:
        outcome_bets = [bet for bet in bets if bet.candidate.outcome == outcome]
        outcome_edges: list[float] = []
        outcome_beats: list[float] = []
        for bet in outcome_bets:
            closing = bet.candidate.closing_prob
            if closing is None:
                continue
            outcome_edges.append(bet.candidate.p_blend - closing)
            outcome_beats.append(1.0 if bet.candidate.p_blend >= closing else 0.0)
        by_outcome[outcome] = {
            "n_bets": len(outcome_bets),
            "roi": flat_roi([bet.payout for bet in outcome_bets]),
            "win_rate": _mean_or_none(
                [1.0 if bet.candidate.label == outcome else 0.0 for bet in outcome_bets]
            ),
            "clv_mean_edge": _mean_or_none(outcome_edges),
            "clv_fraction": _mean_or_none(outcome_beats),
        }

    execution_source_counts = {"hkjc": 0, "football_data": 0}
    for candidate in ordered:
        if candidate.exec_odds is None:
            continue
        if candidate.exec_source in execution_source_counts:
            execution_source_counts[candidate.exec_source] += 1

    kickoffs = [candidate.kickoff_time for candidate in ordered]
    window = {
        "since": _iso(context.since),
        "until": _iso(context.until),
        "first_kickoff": _iso(min(kickoffs)) if kickoffs else None,
        "last_kickoff": _iso(max(kickoffs)) if kickoffs else None,
        "matches": len({candidate.match_id for candidate in ordered}),
        "outcomes": len(ordered),
    }

    return {
        "config": context.config,
        "window": window,
        "n_bets": len(bets),
        "bet_rate": len(bets) / len(ordered) if ordered else 0.0,
        "skipped_no_price": sum(1 for candidate in ordered if candidate.exec_odds is None),
        "skipped_no_prior": sum(1 for candidate in ordered if candidate.p_prior is None),
        "roi_real": flat_roi(payouts),
        "roi_real_ci95": normal_ci95([payout - 1.0 for payout in payouts]),
        "roi_fair": flat_roi(fair_payouts),
        "roi_kelly": kelly_roi(stakes, payouts),
        "roi_kelly_ci95": _kelly_ci95(stakes, payouts),
        "clv_mean_edge": _mean_or_none(clv_edges),
        "clv_mean_edge_ci95": normal_ci95(clv_edges),
        "clv_fraction": _mean_or_none(clv_beats),
        "clv_fraction_ci95": wilson_interval(int(sum(clv_beats)), len(clv_beats)),
        "clv_n": len(clv_edges),
        "model_brier": context.model_metrics.get("brier"),
        "model_logloss": context.model_metrics.get("logloss"),
        "market_brier": context.market_metrics.get("brier"),
        "market_logloss": context.market_metrics.get("logloss"),
        "blend_brier": context.blend_metrics.get("brier"),
        "blend_logloss": context.blend_metrics.get("logloss"),
        "by_outcome": by_outcome,
        "execution_source_counts": execution_source_counts,
        "notes": list(NOTES),
    }


def format_report(report: dict) -> str:
    """Render the report as a compact human-readable table."""
    config = report["config"]
    window = report["window"]
    lines = [
        f"1x2 backtest — champion {config['champion_id']} ({config['champion_artifact']})",
        (
            f"window: {window['first_kickoff']} → {window['last_kickoff']}  "
            f"matches={window['matches']} outcomes={window['outcomes']}"
        ),
        (
            f"config: blend={config['blend_weight']:.2f} "
            f"edge>{config['value_edge_threshold']:.3f} "
            f"buffer={config['exec_edge_buffer']:.3f} "
            f"prior_lead={config['prior_lead_hours']}h "
            f"kelly={config['kelly_multiplier']:.2f} "
            f"cap={config['max_stake_fraction']:.2f}"
        ),
        (
            f"bets: {report['n_bets']} ({_fmt_rate(report['bet_rate'])})  "
            f"skipped_no_price={report['skipped_no_price']} "
            f"skipped_no_prior={report['skipped_no_prior']}"
        ),
        (
            f"ROI flat 1u: {_fmt_pct(report['roi_real'])}  "
            f"CI95 {_fmt_ci(report['roi_real_ci95'])}"
        ),
        f"ROI fair (diagnostic): {_fmt_pct(report['roi_fair'])}",
        (
            f"ROI kelly:   {_fmt_pct(report['roi_kelly'])}  "
            f"CI95 {_fmt_ci(report['roi_kelly_ci95'])}"
        ),
        (
            f"CLV: mean edge {_fmt_num(report['clv_mean_edge'])}  "
            f"beat {_fmt_rate(report['clv_fraction'])}  n={report['clv_n']}"
        ),
        (
            f"calibration: model brier {_fmt_num(report['model_brier'])} "
            f"logloss {_fmt_num(report['model_logloss'])} | "
            f"blend brier {_fmt_num(report['blend_brier'])} "
            f"logloss {_fmt_num(report['blend_logloss'])} | "
            f"market brier {_fmt_num(report['market_brier'])} "
            f"logloss {_fmt_num(report['market_logloss'])}"
        ),
        "by outcome:",
    ]
    for outcome, row in report["by_outcome"].items():
        lines.append(
            f"  {outcome}: n={row['n_bets']} roi={_fmt_pct(row['roi'])} "
            f"win={_fmt_rate(row['win_rate'])} clv={_fmt_num(row['clv_mean_edge'])} "
            f"beat={_fmt_rate(row['clv_fraction'])}"
        )
    lines.append(
        f"execution: hkjc={report['execution_source_counts']['hkjc']} "
        f"football_data={report['execution_source_counts']['football_data']}"
    )
    lines.append("notes:")
    lines.extend(f"  - {note}" for note in report["notes"])
    return "\n".join(lines)


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.2%}"


def _fmt_rate(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def _fmt_num(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.4f}"


def _fmt_ci(interval: Sequence[float] | None) -> str:
    if interval is None:
        return "n/a"
    return f"[{interval[0]:+.2%}, {interval[1]:+.2%}]"


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _months_before(now: datetime, months: int) -> datetime:
    """Calendar-month subtraction (no dateutil dependency)."""
    month_index = now.year * 12 + (now.month - 1) - months
    year, month = divmod(month_index, 12)
    month += 1
    day = min(now.day, calendar.monthrange(year, month)[1])
    return now.replace(year=year, month=month, day=day)


def _filter_window(frame: pd.DataFrame, since: datetime, until: datetime | None) -> pd.DataFrame:
    if frame.empty:
        return frame
    kickoffs = pd.to_datetime(frame["kickoff_time"], utc=True)
    mask = kickoffs >= pd.Timestamp(since)
    if until is not None:
        mask &= kickoffs <= pd.Timestamp(until)
    return frame.loc[mask].copy()


def _prior_probs(
    home: float | None,
    draw: float | None,
    away: float | None,
) -> dict[str, float] | None:
    """The eval frame's 48h de-vigged prior, or ``None`` when any leg is missing."""
    if home is None or draw is None or away is None:
        return None
    try:
        values = [float(home), float(draw), float(away)]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in values):
        return None
    return {"H": values[0], "D": values[1], "A": values[2]}


def _empty_metrics() -> dict:
    return {"brier": None, "logloss": None, "n": 0}


async def run_backtest(
    session: AsyncSession,
    settings: Settings,
    months: int = 24,
    target: str = TARGET_1X2,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict:
    """Load the eval slice, champion, and closing prices, then build the report.

    Read-only: ``build_dataset``, ``get_champion``, ``load_artifact``, and
    ``load_market_priors`` only read. The eval frame is the out-of-sample
    temporal slice; the champion is never retrained here.
    """
    if target != TARGET_1X2:
        raise ValueError(f"backtest supports only {TARGET_1X2!r}, got {target!r}")
    now = datetime.now(UTC)
    window_since = _as_utc(since) if since is not None else _months_before(now, months)
    window_until = _as_utc(until) if until is not None else None

    dataset = await build_dataset(session, settings, target)
    frame = _filter_window(dataset.eval, window_since, window_until)

    champion = await get_champion(session, target)
    if champion is None:
        raise ValueError(f"no champion model for target {target!r}")
    model = load_artifact(champion.artifact_path)

    params = BacktestParams(
        threshold=settings.ml_value_edge_threshold,
        exec_edge_buffer=settings.ml_exec_edge_buffer,
        kelly_multiplier=settings.ledger_kelly_multiplier,
        max_stake_fraction=settings.ledger_max_stake_fraction,
    )
    config = {
        "target": target,
        "blend_weight": settings.ml_blend_weight,
        "value_edge_threshold": settings.ml_value_edge_threshold,
        "exec_edge_buffer": settings.ml_exec_edge_buffer,
        "prior_lead_hours": settings.ml_prior_lead_hours,
        "kelly_multiplier": settings.ledger_kelly_multiplier,
        "max_stake_fraction": settings.ledger_max_stake_fraction,
        "champion_id": champion.id,
        "champion_artifact": champion.artifact_path,
        "champion_promoted_at": _iso(champion.promoted_at),
    }
    if frame.empty:
        return build_report(
            [],
            params,
            ReportContext(
                config=config,
                since=window_since,
                until=window_until,
                model_metrics=_empty_metrics(),
                market_metrics=_empty_metrics(),
                blend_metrics=_empty_metrics(),
            ),
        )

    model_probs = predict_proba(model, frame[FEATURE_COLUMNS].to_dict("records"))
    match_ids = frame["match_id"].tolist()
    kickoffs = frame["kickoff_time"].tolist()
    labels = frame["label_1x2"].tolist()
    market_home = frame["market_home"].tolist()
    market_draw = frame["market_draw"].tolist()
    market_away = frame["market_away"].tolist()
    rows = [
        MatchRow(
            match_id=int(match_id_value),
            kickoff_time=_as_utc(kickoff_value),
            home_team_id=0,
            away_team_id=0,
            league_code="",
            season_label="",
        )
        for match_id_value, kickoff_value in zip(match_ids, kickoffs, strict=True)
    ]
    closing_priors = await load_market_priors(session, rows, 0)

    candidates: list[Candidate] = []
    calibration_labels: list[str] = []
    calibration_model: list[list[float]] = []
    calibration_blend: list[list[float]] = []
    calibration_market: list[list[float]] = []
    for index, (match_id_value, kickoff_value, label, home, draw, away) in enumerate(
        zip(match_ids, kickoffs, labels, market_home, market_draw, market_away, strict=True)
    ):
        if not isinstance(label, str) or label not in OUTCOMES_1X2:
            continue
        match_id = int(match_id_value)
        kickoff = _as_utc(kickoff_value)
        prior_probs = _prior_probs(home, draw, away)
        model_map = {
            outcome: float(model_probs[index][position])
            for position, outcome in enumerate(OUTCOMES_1X2)
        }
        blended = blend_probs(model_map, prior_probs, settings.ml_blend_weight)
        if prior_probs is not None:
            calibration_labels.append(label)
            calibration_model.append([model_map[outcome] for outcome in OUTCOMES_1X2])
            calibration_blend.append([blended[outcome] for outcome in OUTCOMES_1X2])
            calibration_market.append([prior_probs[outcome] for outcome in OUTCOMES_1X2])
        prior = closing_priors.get(match_id)
        for outcome in OUTCOMES_1X2:
            exec_odds = prior.had_odds.get(outcome) if prior and prior.had_odds else None
            closing_prob = prior.had_probs.get(outcome) if prior and prior.had_probs else None
            exec_source = (
                prior.source if prior is not None and exec_odds is not None else "none"
            )
            candidates.append(
                Candidate(
                    match_id=match_id,
                    kickoff_time=kickoff,
                    outcome=outcome,
                    label=label,
                    p_model=model_map[outcome],
                    p_prior=prior_probs[outcome] if prior_probs is not None else None,
                    p_blend=blended[outcome],
                    exec_odds=exec_odds,
                    exec_source=exec_source,
                    closing_prob=closing_prob,
                )
            )

    if calibration_labels:
        model_metrics = evaluate_1x2(np.asarray(calibration_model), calibration_labels)
        market_metrics = evaluate_1x2(np.asarray(calibration_market), calibration_labels)
        blend_metrics = evaluate_1x2(np.asarray(calibration_blend), calibration_labels)
    else:
        model_metrics = _empty_metrics()
        market_metrics = _empty_metrics()
        blend_metrics = _empty_metrics()

    return build_report(
        candidates,
        params,
        ReportContext(
            config=config,
            since=window_since,
            until=window_until,
            model_metrics=model_metrics,
            market_metrics=market_metrics,
            blend_metrics=blend_metrics,
        ),
    )
