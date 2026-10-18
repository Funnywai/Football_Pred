"""As-of-kickoff feature builder.

Every feature row is computed from state that only accumulates from matches
with a strictly earlier kickoff time, so the builder is leakage-safe by
construction: adding future matches never changes an earlier row, and matches
sharing a kickoff time cannot leak into each other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.ml.labels import parse_handicap_line

FEATURE_VERSION = "v2"

ELO_INITIAL = 1500.0
ELO_K = 20.0
ELO_HOME_ADVANTAGE = 65.0
FORM_WINDOW = 5
STRENGTH_WINDOW = 10
H2H_WINDOW = 5
DEFAULT_REST_DAYS = 7.0
STATS_WINDOW = 10
STATS_AVAILABILITY_LEAD = timedelta(hours=48)

LEAGUE_CODES: dict[str, int] = {
    "EPL": 0,
    "LALIGA": 1,
    "SERIEA": 2,
    "BUNDESLIGA": 3,
    "LIGUE1": 4,
    "UCL": 5,
}

FEATURE_COLUMNS: list[str] = [
    "elo_home", "elo_away", "elo_diff",
    "attack_home", "defense_home", "attack_away", "defense_away",
    "attack_diff", "defense_diff",
    "sot_for_home", "sot_against_home", "sot_for_away", "sot_against_away",
    "sot_diff_for", "sot_diff_against", "shot_accuracy_home", "shot_accuracy_away",
    "form_points_home", "form_gd_home", "form_points_away", "form_gd_away",
    "home_form_points", "away_form_points",
    "rest_days_home", "rest_days_away",
    "league_code", "matchday_index",
    "h2h_net_gd",
    "market_home", "market_draw", "market_away",
    "hdc_line", "market_hdc_home", "market_hdc_away",
    "has_market_prior", "has_hdc_prior",
]


@dataclass(frozen=True)
class MatchRow:
    """One match as seen by the feature builder (scores optional for upcoming)."""

    match_id: int
    kickoff_time: datetime
    home_team_id: int
    away_team_id: int
    league_code: str
    season_label: str
    home_score: int | None = None
    away_score: int | None = None
    home_shots: int | None = None
    away_shots: int | None = None
    home_sot: int | None = None
    away_sot: int | None = None
    home_xg: float | None = None
    away_xg: float | None = None
    home_corners: int | None = None
    away_corners: int | None = None
    stats_available_at: datetime | None = None


@dataclass(frozen=True)
class MarketPrior:
    """De-vigged market probabilities and raw odds for one match."""

    had_probs: dict[str, float] | None = None
    had_odds: dict[str, float] | None = None
    hdc_line: float | None = None
    hdc_probs: dict[str, float] | None = None
    hdc_odds: dict[str, float] | None = None
    source: str = "none"


@dataclass(frozen=True)
class FeatureRow:
    match_id: int
    kickoff_time: datetime
    features: dict[str, float]


def hkjc_had_odds(payload: dict) -> dict[str, float] | None:
    """Extract {"H","D","A"} current odds from an HKJC HAD pool payload."""
    lines = payload.get("lines") or []
    if not lines:
        return None
    odds: dict[str, float] = {}
    for combination in lines[0].get("combinations") or []:
        key = combination.get("str")
        value = combination.get("currentOdds")
        if key in {"H", "D", "A"} and value is not None:
            odds[key] = float(value)
    if set(odds) != {"H", "D", "A"}:
        return None
    return odds


def hkjc_hdc_main(payload: dict) -> tuple[float, dict[str, float]] | None:
    """Extract the main HDC line and its {"H","A"} odds from a pool payload."""
    for line in payload.get("lines") or []:
        if not line.get("main"):
            continue
        parsed = parse_handicap_line(line.get("condition"))
        if parsed is None:
            continue
        odds: dict[str, float] = {}
        for combination in line.get("combinations") or []:
            key = combination.get("str")
            value = combination.get("currentOdds")
            if key in {"H", "A"} and value is not None:
                odds[key] = float(value)
        if set(odds) == {"H", "A"}:
            return parsed, odds
    return None


def football_data_close_odds(payload: dict) -> dict[str, float] | None:
    """Closing {"H","D","A"} odds from a football-data snapshot payload.

    Prefers Pinnacle ("PS") as the sharp prior, then the market average ("Avg"),
    then Bet365 ("B365").
    """
    bookmakers = payload.get("odds") or {}
    for bookmaker in ("PS", "Avg", "B365"):
        entry = bookmakers.get(bookmaker)
        if not entry:
            continue
        close = entry.get("close") or []
        if len(close) != 3 or any(value is None for value in close):
            continue
        return {"H": float(close[0]), "D": float(close[1]), "A": float(close[2])}
    return None


@dataclass(frozen=True)
class _TeamStats:
    available_at: datetime
    sot_for: int
    sot_against: int
    shots_for: int | None
    shots_against: int | None


@dataclass
class _TeamHistory:
    results: list[tuple[int, int]] = field(default_factory=list)
    home_results: list[tuple[int, int]] = field(default_factory=list)
    away_results: list[tuple[int, int]] = field(default_factory=list)
    stats: list[_TeamStats] = field(default_factory=list)
    last_kickoff: datetime | None = None
    season_counts: dict[str, int] = field(default_factory=dict)


class _State:
    def __init__(self) -> None:
        self.teams: dict[int, _TeamHistory] = {}
        self.elo: dict[int, float] = {}
        self.h2h: dict[tuple[int, int], list[tuple[int, int]]] = {}
        self.goals_total = 0
        self.team_matches = 0

    def team(self, team_id: int) -> _TeamHistory:
        return self.teams.setdefault(team_id, _TeamHistory())

    def elo_of(self, team_id: int) -> float:
        return self.elo.get(team_id, ELO_INITIAL)

    def scoring_baseline(self) -> float:
        if self.team_matches == 0:
            return 1.0
        baseline = self.goals_total / (2.0 * self.team_matches)
        return baseline if baseline > 0 else 1.0


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _form(results: list[tuple[int, int]]) -> tuple[float, float]:
    window = results[-FORM_WINDOW:]
    points = 0.0
    gd = 0.0
    for goals_for, goals_against in window:
        gd += goals_for - goals_against
        if goals_for > goals_against:
            points += 3.0
        elif goals_for == goals_against:
            points += 1.0
    return points, gd


def _strength(results: list[tuple[int, int]], baseline: float) -> tuple[float, float]:
    window = results[-STRENGTH_WINDOW:]
    if not window:
        return 1.0, 1.0
    attack = _mean([float(gf) for gf, _ in window]) / baseline
    defense = _mean([float(ga) for _, ga in window]) / baseline
    return attack, defense


def _rest_days(last_kickoff: datetime | None, kickoff: datetime) -> float:
    if last_kickoff is None:
        return DEFAULT_REST_DAYS
    return (kickoff - last_kickoff).total_seconds() / 86400.0


def _h2h_net(state: _State, home_team_id: int, away_team_id: int) -> float:
    key = (min(home_team_id, away_team_id), max(home_team_id, away_team_id))
    entries = state.h2h.get(key, [])[-H2H_WINDOW:]
    if not entries:
        return 0.0
    nets = [net if stored_home == home_team_id else -net for stored_home, net in entries]
    return _mean([float(value) for value in nets])


def _stats_window(history: _TeamHistory, kickoff: datetime) -> list[_TeamStats]:
    """Last ``STATS_WINDOW`` matches whose stats were available 48h before kickoff.

    The guard is time-based, not match-order-based: football-data publishes after
    the match, so a match played inside the 48h window must not contribute even
    though it is chronologically earlier.
    """
    cutoff = kickoff - STATS_AVAILABILITY_LEAD
    eligible = [entry for entry in history.stats if entry.available_at <= cutoff]
    return eligible[-STATS_WINDOW:]


def _shot_accuracy(entries: list[_TeamStats]) -> float:
    """Mean SOT/shots; matches with zero or missing shots are skipped (NaN)."""
    values = [
        entry.sot_for / entry.shots_for
        for entry in entries
        if entry.shots_for is not None and entry.shots_for > 0
    ]
    return _mean(values) if values else float("nan")


def _stats_features(
    home: _TeamHistory, away: _TeamHistory, kickoff: datetime
) -> dict[str, float]:
    nan = float("nan")
    home_window = _stats_window(home, kickoff)
    away_window = _stats_window(away, kickoff)
    sot_for_home = _mean([float(entry.sot_for) for entry in home_window]) if home_window else nan
    sot_against_home = (
        _mean([float(entry.sot_against) for entry in home_window]) if home_window else nan
    )
    sot_for_away = _mean([float(entry.sot_for) for entry in away_window]) if away_window else nan
    sot_against_away = (
        _mean([float(entry.sot_against) for entry in away_window]) if away_window else nan
    )
    return {
        "sot_for_home": sot_for_home,
        "sot_against_home": sot_against_home,
        "sot_for_away": sot_for_away,
        "sot_against_away": sot_against_away,
        "sot_diff_for": sot_for_home - sot_for_away,
        "sot_diff_against": sot_against_home - sot_against_away,
        "shot_accuracy_home": _shot_accuracy(home_window),
        "shot_accuracy_away": _shot_accuracy(away_window),
    }


def _features_for(state: _State, row: MatchRow, prior: MarketPrior | None) -> dict[str, float]:
    home = state.team(row.home_team_id)
    away = state.team(row.away_team_id)
    baseline = state.scoring_baseline()
    elo_home = state.elo_of(row.home_team_id)
    elo_away = state.elo_of(row.away_team_id)
    attack_home, defense_home = _strength(home.results, baseline)
    attack_away, defense_away = _strength(away.results, baseline)
    form_points_home, form_gd_home = _form(home.results)
    form_points_away, form_gd_away = _form(away.results)
    home_form_points, _ = _form(home.home_results)
    away_form_points, _ = _form(away.away_results)
    matchday_index = home.season_counts.get(row.season_label, 0) + 1
    nan = float("nan")
    features = {
        "elo_home": elo_home,
        "elo_away": elo_away,
        "elo_diff": elo_home - elo_away,
        "attack_home": attack_home,
        "defense_home": defense_home,
        "attack_away": attack_away,
        "defense_away": defense_away,
        "attack_diff": attack_home - attack_away,
        "defense_diff": defense_home - defense_away,
        **_stats_features(home, away, row.kickoff_time),
        "form_points_home": form_points_home,
        "form_gd_home": form_gd_home,
        "form_points_away": form_points_away,
        "form_gd_away": form_gd_away,
        "home_form_points": home_form_points,
        "away_form_points": away_form_points,
        "rest_days_home": _rest_days(home.last_kickoff, row.kickoff_time),
        "rest_days_away": _rest_days(away.last_kickoff, row.kickoff_time),
        "league_code": float(LEAGUE_CODES.get(row.league_code, -1)),
        "matchday_index": float(matchday_index),
        "h2h_net_gd": _h2h_net(state, row.home_team_id, row.away_team_id),
        "market_home": nan,
        "market_draw": nan,
        "market_away": nan,
        "hdc_line": nan,
        "market_hdc_home": nan,
        "market_hdc_away": nan,
        "has_market_prior": 0.0,
        "has_hdc_prior": 0.0,
    }
    if prior is not None and prior.had_probs is not None:
        features["market_home"] = prior.had_probs.get("H", nan)
        features["market_draw"] = prior.had_probs.get("D", nan)
        features["market_away"] = prior.had_probs.get("A", nan)
        features["has_market_prior"] = 1.0
    if prior is not None and prior.hdc_line is not None and prior.hdc_probs is not None:
        features["hdc_line"] = prior.hdc_line
        features["market_hdc_home"] = prior.hdc_probs.get("H", nan)
        features["market_hdc_away"] = prior.hdc_probs.get("A", nan)
        features["has_hdc_prior"] = 1.0
    return features


def _update(state: _State, row: MatchRow) -> None:
    if row.home_score is None or row.away_score is None:
        return
    home_score = row.home_score
    away_score = row.away_score
    home = state.team(row.home_team_id)
    away = state.team(row.away_team_id)
    home.results.append((home_score, away_score))
    away.results.append((away_score, home_score))
    home.home_results.append((home_score, away_score))
    away.away_results.append((away_score, home_score))
    home.last_kickoff = row.kickoff_time
    away.last_kickoff = row.kickoff_time
    home.season_counts[row.season_label] = home.season_counts.get(row.season_label, 0) + 1
    away.season_counts[row.season_label] = away.season_counts.get(row.season_label, 0) + 1
    state.goals_total += home_score + away_score
    state.team_matches += 1
    elo_home = state.elo_of(row.home_team_id)
    elo_away = state.elo_of(row.away_team_id)
    expected_home = 1.0 / (1.0 + 10.0 ** ((elo_away - elo_home - ELO_HOME_ADVANTAGE) / 400.0))
    if home_score > away_score:
        actual_home = 1.0
    elif home_score == away_score:
        actual_home = 0.5
    else:
        actual_home = 0.0
    state.elo[row.home_team_id] = elo_home + ELO_K * (actual_home - expected_home)
    state.elo[row.away_team_id] = elo_away + ELO_K * ((1.0 - actual_home) - (1.0 - expected_home))
    key = (min(row.home_team_id, row.away_team_id), max(row.home_team_id, row.away_team_id))
    state.h2h.setdefault(key, []).append((row.home_team_id, home_score - away_score))
    if (
        row.stats_available_at is not None
        and row.home_sot is not None
        and row.away_sot is not None
    ):
        home.stats.append(
            _TeamStats(
                available_at=row.stats_available_at,
                sot_for=row.home_sot,
                sot_against=row.away_sot,
                shots_for=row.home_shots,
                shots_against=row.away_shots,
            )
        )
        away.stats.append(
            _TeamStats(
                available_at=row.stats_available_at,
                sot_for=row.away_sot,
                sot_against=row.home_sot,
                shots_for=row.away_shots,
                shots_against=row.home_shots,
            )
        )


def build_feature_rows(
    rows: list[MatchRow],
    market_priors: dict[int, MarketPrior] | None = None,
) -> list[FeatureRow]:
    """Build one feature row per match, strictly as-of kickoff.

    Rows are processed in (kickoff_time, match_id) order. All matches sharing a
    kickoff time see the same pre-kickoff state; their results are applied only
    afterwards, so simultaneous matches cannot leak into each other.
    """
    priors = market_priors or {}
    ordered = sorted(rows, key=lambda row: (row.kickoff_time, row.match_id))
    state = _State()
    output: list[FeatureRow] = []
    index = 0
    while index < len(ordered):
        kickoff = ordered[index].kickoff_time
        group: list[MatchRow] = []
        while index < len(ordered) and ordered[index].kickoff_time == kickoff:
            group.append(ordered[index])
            index += 1
        for row in group:
            output.append(
                FeatureRow(
                    match_id=row.match_id,
                    kickoff_time=row.kickoff_time,
                    features=_features_for(state, row, priors.get(row.match_id)),
                )
            )
        for row in group:
            _update(state, row)
    return output
