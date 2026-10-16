"""Scheduled ML jobs: predict upcoming matches, retrain (off the event loop)."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.ml.dataset import Dataset, build_dataset, load_hkjc_priors
from app.ml.features import FEATURE_COLUMNS, MatchRow
from app.ml.metrics import economic_backtest, expected_calibration_error
from app.ml.models import (
    TARGET_1X2,
    TARGET_HANDICAP,
    evaluate_1x2,
    evaluate_handicap,
    load_artifact,
    predict_proba,
    save_artifact,
    train_1x2,
    train_handicap,
)
from app.ml.predict import (
    load_champion,
    load_upcoming_matches,
    predict_upcoming_matches,
    upsert_predictions,
)
from app.ml.registry import get_champion, maybe_promote, register_challenger
from app.ml.value import clv_metrics
from app.services.runs import track_run

logger = logging.getLogger(__name__)

PREDICT_JOB_ID = "ml_predict"
RETRAIN_JOB_ID = "ml_retrain"
PREDICT_INTERVAL_SECONDS = 3600


async def predict_upcoming(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> int:
    async def work(session: AsyncSession) -> int:
        now = datetime.now(UTC)
        champion_1x2 = await load_champion(session, TARGET_1X2)
        champion_handicap = await load_champion(session, TARGET_HANDICAP)
        if champion_1x2 is None and champion_handicap is None:
            logger.info("no champion models yet; skipping prediction")
            return 0
        upcoming = await load_upcoming_matches(session, settings, now)
        rows = await predict_upcoming_matches(
            session, upcoming, champion_1x2, champion_handicap, settings
        )
        return await upsert_predictions(session, rows)

    return await track_run(session_factory, PREDICT_JOB_ID, work)


async def _eval_closing_priors(
    session: AsyncSession, dataset: Dataset
) -> dict[int, dict[str, float]]:
    rows = [
        MatchRow(
            match_id=int(record.match_id),
            kickoff_time=record.kickoff_time.to_pydatetime()
            if hasattr(record.kickoff_time, "to_pydatetime")
            else record.kickoff_time,
            home_team_id=0,
            away_team_id=0,
            league_code="EPL",
            season_label="",
        )
        for record in dataset.eval.itertuples()
    ]
    # CLV is measured against the true closing line, not the feature lead.
    priors = await load_hkjc_priors(session, rows, 0)
    return {
        match_id: prior.had_probs
        for match_id, prior in priors.items()
        if prior.had_probs is not None
    }


def _model_probs_1x2(model, frame: pd.DataFrame, probs=None) -> dict[int, dict[str, float]]:
    if probs is None:
        probs = predict_proba(model, frame[FEATURE_COLUMNS].to_dict("records"))
    return {
        int(match_id): {"H": float(row[0]), "D": float(row[1]), "A": float(row[2])}
        for match_id, row in zip(frame["match_id"].tolist(), probs, strict=True)
    }


def _market_probs_1x2(frame: pd.DataFrame) -> np.ndarray:
    """De-vigged market probabilities from the eval frame's serving-time prior columns."""
    return frame[["market_home", "market_draw", "market_away"]].to_numpy(dtype=float)


def _fresh_champion_metrics(
    target: str,
    path: str | None,
    eval_df: pd.DataFrame,
    closing_priors: dict,
    settings: Settings,
) -> dict | None:
    """Re-evaluate a stored champion on the CURRENT eval window (fix #6).

    Returns None when the champion cannot be evaluated (missing/corrupt artifact,
    empty label subset) — the caller then falls back to the stored metrics.
    """
    if path is None:
        return None
    subset = "label_1x2" if target == TARGET_1X2 else "label_handicap"
    try:
        frame = eval_df.dropna(subset=[subset])
        if frame.empty:
            logger.warning(
                "champion for %s has no %s rows in this eval window; "
                "falling back to stored metrics",
                target,
                subset,
            )
            return None
        model = load_artifact(path)
        probs = predict_proba(model, frame[FEATURE_COLUMNS].to_dict("records"))
        if target == TARGET_1X2:
            labels = frame["label_1x2"].tolist()
            metrics = evaluate_1x2(probs, labels)
            metrics.update(clv_metrics(_model_probs_1x2(model, frame, probs), closing_priors))
            metrics["ece"] = expected_calibration_error(probs, labels)
            metrics["roi"] = economic_backtest(
                probs,
                _market_probs_1x2(frame),
                labels,
                threshold=settings.ml_value_edge_threshold,
                exec_edge_buffer=getattr(settings, "ml_exec_edge_buffer", 0.0),
            )["roi"]
            return metrics
        return evaluate_handicap(probs, frame["label_handicap"].tolist())
    except Exception as exc:  # a broken champion must not block retraining
        logger.warning("could not re-evaluate champion for %s: %s", target, exc, exc_info=True)
        return None


def _train_challenger_sync(
    dataset_1x2: Dataset | None,
    dataset_handicap: Dataset | None,
    closing_priors: dict[int, dict[str, float]],
    settings: Settings,
    champion_paths: dict[str, str],
) -> dict:
    artifact_dir = Path(settings.ml_artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    result: dict = {}
    if dataset_1x2 is not None and len(dataset_1x2.train) >= settings.ml_min_train_rows:
        try:
            model_1x2 = train_1x2(dataset_1x2.train, dataset_1x2.calibration, dataset_1x2.eval)
        except ValueError as exc:
            logger.warning("1x2 training skipped: %s", exc)
        else:
            eval_frame = dataset_1x2.eval
            probs = predict_proba(model_1x2, eval_frame[FEATURE_COLUMNS].to_dict("records"))
            labels = eval_frame["label_1x2"].tolist()
            clv = clv_metrics(_model_probs_1x2(model_1x2, eval_frame, probs), closing_priors)
            metrics = {
                **model_1x2.metrics,
                **clv,
                "ece": expected_calibration_error(probs, labels),
                "roi": economic_backtest(
                    probs,
                    _market_probs_1x2(eval_frame),
                    labels,
                    threshold=settings.ml_value_edge_threshold,
                    exec_edge_buffer=getattr(settings, "ml_exec_edge_buffer", 0.0),
                )["roi"],
            }
            path = artifact_dir / f"1x2-{stamp}.joblib"
            save_artifact(model_1x2, path)
            result[TARGET_1X2] = {
                "path": str(path),
                "params": {"num_trees": int(model_1x2.booster.num_trees())},
                "metrics": metrics,
                "champion_metrics": _fresh_champion_metrics(
                    TARGET_1X2,
                    champion_paths.get(TARGET_1X2),
                    eval_frame,
                    closing_priors,
                    settings,
                ),
            }
    elif dataset_1x2 is not None:
        logger.warning(
            "retrain skipped for 1x2: %d train rows < %d",
            len(dataset_1x2.train),
            settings.ml_min_train_rows,
        )
    if dataset_handicap is not None and len(dataset_handicap.train) >= settings.ml_min_train_rows:
        try:
            model_handicap = train_handicap(
                dataset_handicap.train, dataset_handicap.calibration, dataset_handicap.eval
            )
        except ValueError as exc:
            logger.warning("handicap training skipped: %s", exc)
        else:
            path = artifact_dir / f"handicap-{stamp}.joblib"
            save_artifact(model_handicap, path)
            result[TARGET_HANDICAP] = {
                "path": str(path),
                "params": {"num_trees": int(model_handicap.booster.num_trees())},
                "metrics": model_handicap.metrics,
                "champion_metrics": _fresh_champion_metrics(
                    TARGET_HANDICAP,
                    champion_paths.get(TARGET_HANDICAP),
                    dataset_handicap.eval,
                    closing_priors,
                    settings,
                ),
            }
    elif dataset_handicap is not None:
        logger.warning(
            "retrain skipped for handicap: %d train rows < %d",
            len(dataset_handicap.train),
            settings.ml_min_train_rows,
        )
    return result


async def retrain(
    session_factory: async_sessionmaker[AsyncSession], settings: Settings
) -> int:
    async def work(session: AsyncSession) -> int:
        datasets: dict[str, Dataset | None] = {}
        for target in (TARGET_1X2, TARGET_HANDICAP):
            try:
                datasets[target] = await build_dataset(session, settings, target)
            except ValueError as exc:
                logger.warning("retrain skipped for %s: %s", target, exc)
                datasets[target] = None
        if all(dataset is None for dataset in datasets.values()):
            return 0
        closing_priors = (
            await _eval_closing_priors(session, datasets[TARGET_1X2])
            if datasets[TARGET_1X2] is not None
            else {}
        )
        champion_paths: dict[str, str] = {}
        for target in (TARGET_1X2, TARGET_HANDICAP):
            champion = await get_champion(session, target)
            if champion is not None:
                champion_paths[target] = champion.artifact_path
        result = await asyncio.to_thread(
            _train_challenger_sync,
            datasets[TARGET_1X2],
            datasets[TARGET_HANDICAP],
            closing_priors,
            settings,
            champion_paths,
        )
        if not result:
            return 0
        promoted = 0
        for target, payload in result.items():
            version = await register_challenger(
                session,
                target,
                settings.ml_1x2_model if target == TARGET_1X2 else settings.ml_handicap_model,
                payload["params"],
                payload["metrics"],
                payload["path"],
            )
            if await maybe_promote(
                session,
                version,
                settings.ml_champion_margin,
                champion_metrics=payload.get("champion_metrics"),
            ):
                promoted += 1
        return promoted

    return await track_run(session_factory, RETRAIN_JOB_ID, work)


def build_ml_scheduler(
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
    *,
    scheduler: AsyncIOScheduler | None = None,
) -> AsyncIOScheduler:
    """Register the ML jobs on an (optionally provided) AsyncIOScheduler."""
    scheduler = scheduler or AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        predict_upcoming,
        "interval",
        seconds=PREDICT_INTERVAL_SECONDS,
        args=[session_factory, settings],
        id=PREDICT_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        retrain,
        "interval",
        seconds=settings.ml_retrain_interval,
        args=[session_factory, settings],
        id=RETRAIN_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    return scheduler
