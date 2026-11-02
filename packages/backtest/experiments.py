from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from types import MappingProxyType

from packages.adapters.football_data_co_uk import (
    FootballDataCoUkAdapter,
    HistoricalMatchRow,
)
from packages.backtest.features import (
    ELO_HOME_ADVANTAGE,
    ELO_INITIAL,
    ELO_K,
    adjusted_had,
    elo_rating,
    elo_ratings,
    rest_days,
)
from packages.backtest.models import (
    DEFAULT_TEMPERATURE_GRID,
    ZERO,
    apply_temperature,
    dixon_coles_had,
    fit_temperature,
    fit_weighted_ratings,
    poisson_had,
    team_key,
)
from packages.backtest.walk_forward import (
    HAD_OUTCOMES,
    MIN_EV,
    CalibrationBin,
    calibration_bins,
    fit_historical_ratings,
    market_had_quote,
    multiclass_brier,
    multiclass_log_loss,
)

TRAIN_SEASONS: tuple[int, ...] = (2021, 2022, 2023)
VALIDATION_SEASON = 2024
HOLDOUT_SEASON = 2025
TRAIN_BLOCK = "train"
VALIDATION_BLOCK = "validation"
HOLDOUT_BLOCK = "holdout"
DEFAULT_MIN_TRAIN = 50

DECAY_GRID: tuple[Decimal, ...] = (
    Decimal("0.0"),
    Decimal("0.5"),
    Decimal("1.0"),
    Decimal("2.0"),
)
RHO_GRID: tuple[Decimal, ...] = (
    Decimal("-0.15"),
    Decimal("-0.10"),
    Decimal("-0.05"),
    Decimal("0.00"),
    Decimal("0.05"),
)
TEMPERATURE_GRID: tuple[Decimal, ...] = DEFAULT_TEMPERATURE_GRID

RAW_VARIANTS = ("poisson", "time_decay_poisson", "dixon_coles")
FEATURE_VARIANTS = ("elo_adjusted_poisson", "time_decay_elo", "rest_adjusted")
K_ELO_GRID: tuple[Decimal, ...] = (
    Decimal("0.0"),
    Decimal("0.1"),
    Decimal("0.2"),
    Decimal("0.3"),
)
K_REST_GRID: tuple[Decimal, ...] = (
    Decimal("0.0"),
    Decimal("0.005"),
    Decimal("0.01"),
    Decimal("0.02"),
)


def season_start_year_for(row: HistoricalMatchRow) -> int:
    """Prefer the source season label and fall back to the match date."""
    if row.season_start_year > 0:
        return row.season_start_year
    return row.played_on.year if row.played_on.month >= 7 else row.played_on.year - 1


def sort_historical_rows(
    rows: Iterable[HistoricalMatchRow],
) -> list[HistoricalMatchRow]:
    return sorted(
        rows,
        key=lambda row: (
            row.played_on,
            season_start_year_for(row),
            row.home_team,
            row.away_team,
        ),
    )


def load_historical_rows(
    seasons: Sequence[int],
    competition: str = "EPL",
    *,
    adapter: FootballDataCoUkAdapter | None = None,
) -> list[HistoricalMatchRow]:
    """Fetch and parse football-data.co.uk CSVs for the given season start years."""
    owned = adapter is None
    active = adapter or FootballDataCoUkAdapter()
    all_rows: list[HistoricalMatchRow] = []
    try:
        for season in seasons:
            fetched = active.fetch_league_csv(competition, season)
            all_rows.extend(
                FootballDataCoUkAdapter.parse_csv(fetched.raw_text, competition, season)
            )
    finally:
        if owned:
            active.close()
    return sort_historical_rows(all_rows)


def split_blocks(
    rows: Iterable[HistoricalMatchRow],
    *,
    train_seasons: Sequence[int] = TRAIN_SEASONS,
    validation_season: int = VALIDATION_SEASON,
    holdout_season: int = HOLDOUT_SEASON,
) -> dict[str, list[HistoricalMatchRow]]:
    train_set = set(train_seasons)
    blocks: dict[str, list[HistoricalMatchRow]] = {
        TRAIN_BLOCK: [],
        VALIDATION_BLOCK: [],
        HOLDOUT_BLOCK: [],
    }
    for row in sort_historical_rows(rows):
        season = season_start_year_for(row)
        if season in train_set:
            blocks[TRAIN_BLOCK].append(row)
        elif season == validation_season:
            blocks[VALIDATION_BLOCK].append(row)
        elif season == holdout_season:
            blocks[HOLDOUT_BLOCK].append(row)
    return blocks


@dataclass(frozen=True)
class ExperimentPrediction:
    row: HistoricalMatchRow
    block: str
    model: Mapping[str, Decimal]
    market: Mapping[str, Decimal] | None
    market_odds: tuple[Decimal, Decimal, Decimal] | None


def _fit_ratings(
    rows: Iterable[HistoricalMatchRow],
    *,
    condition_date: date,
    variant: str,
    decay: Decimal,
    prior_matches: float,
):
    if variant in ("poisson", "dixon_coles", "elo_adjusted_poisson") or decay == 0:
        return fit_historical_ratings(rows, as_of=condition_date, prior_matches=prior_matches)
    if variant in ("time_decay_poisson", "time_decay_elo", "rest_adjusted"):
        return fit_weighted_ratings(
            rows,
            as_of=condition_date,
            prior_matches=prior_matches,
            decay=decay,
        )
    raise ValueError(f"unknown variant {variant!r}")


def predict_rows(
    rows: Iterable[HistoricalMatchRow],
    *,
    predict_for: Iterable[HistoricalMatchRow],
    variant: str,
    decay: Decimal | float | str = ZERO,
    rho: Decimal | float | str = ZERO,
    temperature: Decimal | float | str | None = None,
    min_train: int = 0,
    prior_matches: float = 5.0,
    block: str = "",
    k_elo: Decimal | float | str = ZERO,
    k_rest: Decimal | float | str = ZERO,
    elo_k: Decimal | float | str = ELO_K,
    home_advantage: Decimal | float | str = ELO_HOME_ADVANTAGE,
) -> list[ExperimentPrediction]:
    """Predict each target row using only rows with a strictly earlier date."""
    if variant not in RAW_VARIANTS and variant not in FEATURE_VARIANTS:
        raise ValueError(f"unknown variant {variant!r}")
    if min_train < 0:
        raise ValueError("min_train must be non-negative")

    decay_value = Decimal(str(decay))
    rho_value = Decimal(str(rho))
    k_elo_value = Decimal(str(k_elo))
    k_rest_value = Decimal(str(k_rest))
    elo_k_value = Decimal(str(elo_k))
    home_advantage_value = Decimal(str(home_advantage))
    ordered = sort_historical_rows(rows)
    predictions: list[ExperimentPrediction] = []
    for row in sort_historical_rows(predict_for):
        prior_rows = [candidate for candidate in ordered if candidate.played_on < row.played_on]
        if len(prior_rows) < min_train:
            continue
        ratings = _fit_ratings(
            prior_rows,
            condition_date=row.played_on,
            variant=variant,
            decay=decay_value,
            prior_matches=prior_matches,
        )
        if not ratings.teams:
            continue
        if variant in FEATURE_VARIANTS:
            elo = elo_ratings(
                prior_rows,
                as_of=row.played_on,
                k=elo_k_value,
                home_advantage=home_advantage_value,
                initial=ELO_INITIAL,
            )
            model = adjusted_had(
                ratings,
                team_key(row.home_team),
                team_key(row.away_team),
                elo_home=elo_rating(elo, row.home_team, initial=ELO_INITIAL),
                elo_away=elo_rating(elo, row.away_team, initial=ELO_INITIAL),
                k_elo=k_elo_value,
                home_advantage=home_advantage_value,
                rest_home=rest_days(prior_rows, row.home_team, as_of=row.played_on),
                rest_away=rest_days(prior_rows, row.away_team, as_of=row.played_on),
                k_rest=k_rest_value if variant == "rest_adjusted" else ZERO,
            )
        elif variant == "dixon_coles":
            model = dixon_coles_had(
                ratings, team_key(row.home_team), team_key(row.away_team), rho=rho_value
            )
        else:
            model = poisson_had(ratings, team_key(row.home_team), team_key(row.away_team))
        if temperature is not None:
            model = apply_temperature(model, temperature)

        quote = market_had_quote(row)
        market = None
        market_odds = None
        if quote is not None:
            market = {
                "H": quote.probabilities[0],
                "D": quote.probabilities[1],
                "A": quote.probabilities[2],
            }
            market_odds = quote.odds
        predictions.append(
            ExperimentPrediction(
                row=row,
                block=block,
                model=MappingProxyType(model),
                market=MappingProxyType(market) if market is not None else None,
                market_odds=market_odds,
            )
        )
    return predictions


@dataclass(frozen=True)
class BlockMetrics:
    block: str
    matches: int
    matches_with_market: int
    brier_model: Decimal | None
    brier_market: Decimal | None
    log_loss_model: Decimal | None
    log_loss_market: Decimal | None
    bets_placed: int
    roi_model: Decimal | None
    calibration: Mapping[str, tuple[CalibrationBin, ...]]


@dataclass(frozen=True)
class ExperimentReport:
    variant: str
    params: Mapping[str, object]
    train_matches: int
    validation_matches: int
    holdout_matches: int
    validation: BlockMetrics
    holdout: BlockMetrics
    selected_params: Mapping[str, object]
    notes: str = ""


def _best_ev(
    probabilities: Mapping[str, Decimal],
    odds: tuple[Decimal, Decimal, Decimal],
) -> tuple[int, Decimal]:
    best_index = 0
    best_ev = probabilities[HAD_OUTCOMES[0]] * odds[0] - Decimal(1)
    for index in (1, 2):
        value = probabilities[HAD_OUTCOMES[index]] * odds[index] - Decimal(1)
        if value > best_ev:
            best_index = index
            best_ev = value
    return best_index, best_ev


def block_metrics(
    predictions: Sequence[ExperimentPrediction],
    *,
    block: str,
) -> BlockMetrics:
    evaluated = len(predictions)
    if evaluated == 0:
        return BlockMetrics(
            block=block,
            matches=0,
            matches_with_market=0,
            brier_model=None,
            brier_market=None,
            log_loss_model=None,
            log_loss_market=None,
            bets_placed=0,
            roi_model=None,
            calibration=MappingProxyType({}),
        )

    observations: list[tuple[Mapping[str, Decimal], str]] = []
    brier_model_total = Decimal(0)
    log_loss_model_total = Decimal(0)
    brier_market_total = Decimal(0)
    log_loss_market_total = Decimal(0)
    market_count = 0
    total_stake = Decimal(0)
    total_payout = Decimal(0)
    bets_placed = 0

    for prediction in predictions:
        actual = prediction.row.result
        observations.append((prediction.model, actual))
        brier_model_total += multiclass_brier(prediction.model, actual)
        log_loss_model_total += multiclass_log_loss(prediction.model, actual)

        if prediction.market is None or prediction.market_odds is None:
            continue
        market_count += 1
        brier_market_total += multiclass_brier(prediction.market, actual)
        log_loss_market_total += multiclass_log_loss(prediction.market, actual)

        best_index, best_ev = _best_ev(prediction.model, prediction.market_odds)
        if best_ev < MIN_EV:
            continue
        bets_placed += 1
        total_stake += Decimal(1)
        if actual == HAD_OUTCOMES[best_index]:
            total_payout += prediction.market_odds[best_index]

    return BlockMetrics(
        block=block,
        matches=evaluated,
        matches_with_market=market_count,
        brier_model=brier_model_total / Decimal(evaluated),
        brier_market=(brier_market_total / Decimal(market_count) if market_count > 0 else None),
        log_loss_model=log_loss_model_total / Decimal(evaluated),
        log_loss_market=(
            log_loss_market_total / Decimal(market_count) if market_count > 0 else None
        ),
        bets_placed=bets_placed,
        roi_model=((total_payout - total_stake) / total_stake if total_stake > 0 else None),
        calibration=MappingProxyType(calibration_bins(observations)),
    )


def _selection_key(
    predictions: Sequence[ExperimentPrediction],
) -> tuple[Decimal, Decimal]:
    metrics = block_metrics(predictions, block=VALIDATION_BLOCK)
    log_loss = metrics.log_loss_model
    brier = metrics.brier_model
    missing = Decimal("Infinity")
    return (
        missing if log_loss is None else log_loss,
        missing if brier is None else brier,
    )


def _pick_best(
    candidates: Sequence[tuple[str, Sequence[ExperimentPrediction]]],
) -> tuple[str, Sequence[ExperimentPrediction]]:
    return min(candidates, key=lambda item: _selection_key(item[1]))


def _select_temperature(
    predictions: Sequence[ExperimentPrediction],
    grid: Sequence[Decimal],
) -> Decimal:
    observations = [(prediction.model, prediction.row.result) for prediction in predictions]
    return fit_temperature(observations, grid=grid)


def _predict_block(
    rows: Sequence[HistoricalMatchRow],
    targets: Sequence[HistoricalMatchRow],
    *,
    variant: str,
    decay: Decimal,
    rho: Decimal,
    min_train: int,
    prior_matches: float,
    block: str,
    k_elo: Decimal = ZERO,
    k_rest: Decimal = ZERO,
    elo_k: Decimal = ELO_K,
    home_advantage: Decimal = ELO_HOME_ADVANTAGE,
) -> list[ExperimentPrediction]:
    return predict_rows(
        rows,
        predict_for=targets,
        variant=variant,
        decay=decay,
        rho=rho,
        min_train=min_train,
        prior_matches=prior_matches,
        block=block,
        k_elo=k_elo,
        k_rest=k_rest,
        elo_k=elo_k,
        home_advantage=home_advantage,
    )


def _calibrate_predictions(
    predictions: Sequence[ExperimentPrediction],
    temperature: Decimal,
) -> list[ExperimentPrediction]:
    return [
        replace(
            prediction, model=MappingProxyType(apply_temperature(prediction.model, temperature))
        )
        for prediction in predictions
    ]


def run_experiments(
    rows: Iterable[HistoricalMatchRow],
    *,
    train_seasons: Sequence[int] = TRAIN_SEASONS,
    validation_season: int = VALIDATION_SEASON,
    holdout_season: int = HOLDOUT_SEASON,
    min_train: int = DEFAULT_MIN_TRAIN,
    prior_matches: float = 5.0,
    decay_grid: Sequence[Decimal] = DECAY_GRID,
    rho_grid: Sequence[Decimal] = RHO_GRID,
    temperature_grid: Sequence[Decimal] = TEMPERATURE_GRID,
) -> list[ExperimentReport]:
    """Select hyperparameters on the validation season, then evaluate on holdout.

    Holdout rows are never touched until selection has finished.
    """
    all_rows = sort_historical_rows(rows)
    blocks = split_blocks(
        all_rows,
        train_seasons=train_seasons,
        validation_season=validation_season,
        holdout_season=holdout_season,
    )
    train_rows = blocks[TRAIN_BLOCK]
    validation_rows = blocks[VALIDATION_BLOCK]
    holdout_rows = blocks[HOLDOUT_BLOCK]

    validation_candidates: list[tuple[str, Sequence[ExperimentPrediction]]] = [
        (
            "poisson",
            _predict_block(
                all_rows,
                validation_rows,
                variant="poisson",
                decay=Decimal(0),
                rho=Decimal(0),
                min_train=min_train,
                prior_matches=prior_matches,
                block=VALIDATION_BLOCK,
            ),
        )
    ]

    decay_candidates: list[tuple[Decimal, list[ExperimentPrediction]]] = []
    for decay in decay_grid:
        decay_candidates.append(
            (
                Decimal(str(decay)),
                _predict_block(
                    all_rows,
                    validation_rows,
                    variant="time_decay_poisson",
                    decay=Decimal(str(decay)),
                    rho=Decimal(0),
                    min_train=min_train,
                    prior_matches=prior_matches,
                    block=VALIDATION_BLOCK,
                ),
            )
        )
    decay_name, best_decay_predictions = _pick_best(
        [(str(decay), preds) for decay, preds in decay_candidates]
    )
    best_decay = Decimal(decay_name)
    validation_candidates.append(("time_decay_poisson", best_decay_predictions))

    rho_candidates: list[tuple[Decimal, list[ExperimentPrediction]]] = []
    for rho in rho_grid:
        rho_candidates.append(
            (
                Decimal(str(rho)),
                _predict_block(
                    all_rows,
                    validation_rows,
                    variant="dixon_coles",
                    decay=Decimal(0),
                    rho=Decimal(str(rho)),
                    min_train=min_train,
                    prior_matches=prior_matches,
                    block=VALIDATION_BLOCK,
                ),
            )
        )
    rho_name, best_rho_predictions = _pick_best(
        [(str(rho), preds) for rho, preds in rho_candidates]
    )
    best_rho = Decimal(rho_name)
    validation_candidates.append(("dixon_coles", best_rho_predictions))

    best_raw_name, best_raw_validation = _pick_best(validation_candidates)
    temperature = _select_temperature(best_raw_validation, temperature_grid)

    decay_by_variant = {
        "poisson": Decimal(0),
        "dixon_coles": Decimal(0),
        "time_decay_poisson": best_decay,
    }

    def holdout_for(name: str) -> list[ExperimentPrediction]:
        return _predict_block(
            all_rows,
            holdout_rows,
            variant=name,
            decay=decay_by_variant[name],
            rho=best_rho if name == "dixon_coles" else Decimal(0),
            min_train=min_train,
            prior_matches=prior_matches,
            block=HOLDOUT_BLOCK,
        )

    poisson_holdout = holdout_for("poisson")
    decay_holdout = holdout_for("time_decay_poisson")
    rho_holdout = holdout_for("dixon_coles")
    raw_holdout = {
        "poisson": poisson_holdout,
        "time_decay_poisson": decay_holdout,
        "dixon_coles": rho_holdout,
    }
    calibrated_holdout = _calibrate_predictions(raw_holdout[best_raw_name], temperature)

    selection = MappingProxyType(
        {
            "selection_block": f"{validation_season}/{str(validation_season + 1)[-2:]}",
            "evaluation_block": f"{holdout_season}/{str(holdout_season + 1)[-2:]}",
            "selection_metric": "log_loss",
            "decay": str(best_decay),
            "rho": str(best_rho),
            "temperature": str(temperature),
            "base_variant": best_raw_name,
        }
    )
    train_count = len(train_rows)
    validation_count = len(validation_rows)
    holdout_count = len(holdout_rows)

    def report(
        variant: str,
        params: Mapping[str, object],
        validation: BlockMetrics,
        holdout: BlockMetrics,
        notes: str = "",
    ) -> ExperimentReport:
        return ExperimentReport(
            variant=variant,
            params=MappingProxyType(dict(params)),
            train_matches=train_count,
            validation_matches=validation_count,
            holdout_matches=holdout_count,
            validation=validation,
            holdout=holdout,
            selected_params=selection,
            notes=notes,
        )

    poisson_validation_metrics = block_metrics(validation_candidates[0][1], block=VALIDATION_BLOCK)
    decay_validation_metrics = block_metrics(best_decay_predictions, block=VALIDATION_BLOCK)
    rho_validation_metrics = block_metrics(best_rho_predictions, block=VALIDATION_BLOCK)
    raw_validation_metrics = {
        "poisson": poisson_validation_metrics,
        "time_decay_poisson": decay_validation_metrics,
        "dixon_coles": rho_validation_metrics,
    }

    return [
        report(
            "poisson",
            {"decay": "0", "rho": "0"},
            poisson_validation_metrics,
            block_metrics(poisson_holdout, block=HOLDOUT_BLOCK),
        ),
        report(
            "time_decay_poisson",
            {"decay": str(best_decay), "rho": "0"},
            decay_validation_metrics,
            block_metrics(decay_holdout, block=HOLDOUT_BLOCK),
        ),
        report(
            "dixon_coles",
            {"decay": "0", "rho": str(best_rho)},
            rho_validation_metrics,
            block_metrics(rho_holdout, block=HOLDOUT_BLOCK),
        ),
        report(
            "calibrated",
            {
                "base_variant": best_raw_name,
                "base_decay": str(decay_by_variant[best_raw_name]),
                "base_rho": str(best_rho if best_raw_name == "dixon_coles" else Decimal(0)),
                "temperature": str(temperature),
            },
            raw_validation_metrics[best_raw_name],
            block_metrics(calibrated_holdout, block=HOLDOUT_BLOCK),
            notes="validation metrics use T=1 because temperature is fitted on this block",
        ),
    ]


def _pick_best_value[KeyT](
    candidates: Sequence[tuple[KeyT, Sequence[ExperimentPrediction]]],
) -> tuple[KeyT, Sequence[ExperimentPrediction]]:
    return min(candidates, key=lambda item: _selection_key(item[1]))


def _feature_selection(
    *,
    validation_season: int,
    holdout_season: int,
    params: Mapping[str, object],
) -> Mapping[str, object]:
    selection: dict[str, object] = {
        "selection_block": f"{validation_season}/{str(validation_season + 1)[-2:]}",
        "evaluation_block": f"{holdout_season}/{str(holdout_season + 1)[-2:]}",
        "selection_metric": "log_loss",
    }
    selection.update(params)
    return MappingProxyType(selection)


def run_feature_experiments(
    rows: Iterable[HistoricalMatchRow],
    *,
    train_seasons: Sequence[int] = TRAIN_SEASONS,
    validation_season: int = VALIDATION_SEASON,
    holdout_season: int = HOLDOUT_SEASON,
    min_train: int = DEFAULT_MIN_TRAIN,
    prior_matches: float = 5.0,
    decay_grid: Sequence[Decimal] = DECAY_GRID,
    rho_grid: Sequence[Decimal] = RHO_GRID,
    temperature_grid: Sequence[Decimal] = TEMPERATURE_GRID,
    k_elo_grid: Sequence[Decimal] = K_ELO_GRID,
    k_rest_grid: Sequence[Decimal] = K_REST_GRID,
    elo_k: Decimal = ELO_K,
    home_advantage: Decimal = ELO_HOME_ADVANTAGE,
) -> list[ExperimentReport]:
    """Phase 3 baselines plus Elo and rest variants, all selected on validation.

    Elo scale and rest scale are chosen only from validation log-loss. The
    holdout block is first read after every selection is fixed.
    """
    all_rows = sort_historical_rows(rows)
    blocks = split_blocks(
        all_rows,
        train_seasons=train_seasons,
        validation_season=validation_season,
        holdout_season=holdout_season,
    )
    train_rows = blocks[TRAIN_BLOCK]
    validation_rows = blocks[VALIDATION_BLOCK]
    holdout_rows = blocks[HOLDOUT_BLOCK]

    base_reports = run_experiments(
        all_rows,
        train_seasons=train_seasons,
        validation_season=validation_season,
        holdout_season=holdout_season,
        min_train=min_train,
        prior_matches=prior_matches,
        decay_grid=decay_grid,
        rho_grid=rho_grid,
        temperature_grid=temperature_grid,
    )

    def predict_block(
        targets: Sequence[HistoricalMatchRow],
        *,
        variant: str,
        decay: Decimal,
        k_elo: Decimal = ZERO,
        k_rest: Decimal = ZERO,
        block: str,
    ) -> list[ExperimentPrediction]:
        return _predict_block(
            all_rows,
            targets,
            variant=variant,
            decay=decay,
            rho=ZERO,
            min_train=min_train,
            prior_matches=prior_matches,
            block=block,
            k_elo=k_elo,
            k_rest=k_rest,
            elo_k=elo_k,
            home_advantage=home_advantage,
        )

    def report(
        variant: str,
        params: Mapping[str, object],
        validation: BlockMetrics,
        holdout: BlockMetrics,
        notes: str = "",
    ) -> ExperimentReport:
        return ExperimentReport(
            variant=variant,
            params=MappingProxyType(dict(params)),
            train_matches=len(train_rows),
            validation_matches=len(validation_rows),
            holdout_matches=len(holdout_rows),
            validation=validation,
            holdout=holdout,
            selected_params=_feature_selection(
                validation_season=validation_season,
                holdout_season=holdout_season,
                params=params,
            ),
            notes=notes,
        )

    elo_candidates: list[tuple[Decimal, list[ExperimentPrediction]]] = []
    for k_elo in k_elo_grid:
        k_elo_value = Decimal(str(k_elo))
        elo_candidates.append(
            (
                k_elo_value,
                predict_block(
                    validation_rows,
                    variant="elo_adjusted_poisson",
                    decay=ZERO,
                    k_elo=k_elo_value,
                    block=VALIDATION_BLOCK,
                ),
            )
        )
    best_k_elo_poisson, best_elo_poisson_validation = _pick_best_value(elo_candidates)

    decay_elo_candidates: list[tuple[tuple[Decimal, Decimal], list[ExperimentPrediction]]] = []
    for decay in decay_grid:
        for k_elo in k_elo_grid:
            decay_value = Decimal(str(decay))
            k_elo_value = Decimal(str(k_elo))
            decay_elo_candidates.append(
                (
                    (decay_value, k_elo_value),
                    predict_block(
                        validation_rows,
                        variant="time_decay_elo",
                        decay=decay_value,
                        k_elo=k_elo_value,
                        block=VALIDATION_BLOCK,
                    ),
                )
            )
    (
        (
            best_decay_elo,
            best_k_elo_decay,
        ),
        best_decay_elo_validation,
    ) = _pick_best_value(decay_elo_candidates)

    rest_candidates: list[tuple[Decimal, list[ExperimentPrediction]]] = []
    for k_rest in k_rest_grid:
        k_rest_value = Decimal(str(k_rest))
        rest_candidates.append(
            (
                k_rest_value,
                predict_block(
                    validation_rows,
                    variant="rest_adjusted",
                    decay=best_decay_elo,
                    k_elo=best_k_elo_decay,
                    k_rest=k_rest_value,
                    block=VALIDATION_BLOCK,
                ),
            )
        )
    best_k_rest, best_rest_validation = _pick_best_value(rest_candidates)

    elo_poisson_holdout = predict_block(
        holdout_rows,
        variant="elo_adjusted_poisson",
        decay=ZERO,
        k_elo=best_k_elo_poisson,
        block=HOLDOUT_BLOCK,
    )
    decay_elo_holdout = predict_block(
        holdout_rows,
        variant="time_decay_elo",
        decay=best_decay_elo,
        k_elo=best_k_elo_decay,
        block=HOLDOUT_BLOCK,
    )
    rest_holdout = predict_block(
        holdout_rows,
        variant="rest_adjusted",
        decay=best_decay_elo,
        k_elo=best_k_elo_decay,
        k_rest=best_k_rest,
        block=HOLDOUT_BLOCK,
    )

    feature_reports = [
        report(
            "elo_adjusted_poisson",
            {"decay": "0", "k_elo": str(best_k_elo_poisson)},
            block_metrics(best_elo_poisson_validation, block=VALIDATION_BLOCK),
            block_metrics(elo_poisson_holdout, block=HOLDOUT_BLOCK),
        ),
        report(
            "time_decay_elo",
            {"decay": str(best_decay_elo), "k_elo": str(best_k_elo_decay)},
            block_metrics(best_decay_elo_validation, block=VALIDATION_BLOCK),
            block_metrics(decay_elo_holdout, block=HOLDOUT_BLOCK),
        ),
        report(
            "rest_adjusted",
            {
                "decay": str(best_decay_elo),
                "k_elo": str(best_k_elo_decay),
                "k_rest": str(best_k_rest),
            },
            block_metrics(best_rest_validation, block=VALIDATION_BLOCK),
            block_metrics(rest_holdout, block=HOLDOUT_BLOCK),
            notes="decay and k_elo inherited from the validation-selected time_decay_elo",
        ),
    ]
    return [*base_reports, *feature_reports]
