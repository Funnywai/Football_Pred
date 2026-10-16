"""LightGBM training + calibration for the 1X2 (temperature scaling) and handicap (isotonic) targets."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import log_loss

from app.ml.features import FEATURE_COLUMNS, FEATURE_VERSION

TARGET_1X2 = "1x2"
TARGET_HANDICAP = "handicap"

LABEL_TO_INDEX = {"H": 0, "D": 1, "A": 2}
INDEX_TO_LABEL = {0: "H", 1: "D", 2: "A"}

DEFAULT_1X2_PARAMS: dict = {
    "objective": "multiclass",
    "num_class": 3,
    "learning_rate": 0.04,
    "num_leaves": 31,
    "min_child_samples": 30,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "seed": 42,
    "verbose": -1,
}

DEFAULT_HANDICAP_PARAMS: dict = {
    "objective": "binary",
    "learning_rate": 0.04,
    "num_leaves": 31,
    "min_child_samples": 30,
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "seed": 42,
    "verbose": -1,
}

NUM_BOOST_ROUND = 500
EARLY_STOPPING_ROUNDS = 50
VAL_FRACTION = 0.15
MIN_ROWS_FOR_VAL = 10
MIN_TRAIN_ROWS = 20
CALIBRATION_EPSILON = 1e-6
TEMPERATURE_BOUNDS = (0.05, 20.0)


@dataclass
class TrainedModel:
    target: str
    booster: lgb.Booster
    calibrators: list[IsotonicRegression]
    temperature: float | None = None
    feature_columns: list[str] = field(default_factory=lambda: list(FEATURE_COLUMNS))
    feature_version: str = FEATURE_VERSION
    metrics: dict = field(default_factory=dict)


def _matrix(df: pd.DataFrame) -> pd.DataFrame:
    return df[FEATURE_COLUMNS].astype(float)


def _labels_1x2(df: pd.DataFrame) -> np.ndarray:
    return df["label_1x2"].map(LABEL_TO_INDEX).astype(int).to_numpy()


def _labels_handicap(df: pd.DataFrame) -> np.ndarray:
    return (df["label_handicap"] == "H").astype(int).to_numpy()


def _temporal_val_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    if len(df) < MIN_ROWS_FOR_VAL:
        return df, None
    n_val = max(1, int(len(df) * VAL_FRACTION))
    return df.iloc[:-n_val], df.iloc[-n_val:]


def _fit_isotonic_binary(raw: np.ndarray, labels: np.ndarray) -> list[IsotonicRegression]:
    calibrator = IsotonicRegression(
        out_of_bounds="clip",
        y_min=CALIBRATION_EPSILON,
        y_max=1.0 - CALIBRATION_EPSILON,
    )
    calibrator.fit(raw, labels.astype(float))
    return [calibrator]


def _apply_isotonic_binary(calibrators: list[IsotonicRegression], raw: np.ndarray) -> np.ndarray:
    return np.clip(calibrators[0].predict(raw), 0.0, 1.0)


def _fit_isotonic_multiclass(raw: np.ndarray, labels: np.ndarray) -> list[IsotonicRegression]:
    calibrators: list[IsotonicRegression] = []
    for class_index in range(raw.shape[1]):
        calibrator = IsotonicRegression(
            out_of_bounds="clip",
            y_min=CALIBRATION_EPSILON,
            y_max=1.0 - CALIBRATION_EPSILON,
        )
        calibrator.fit(raw[:, class_index], (labels == class_index).astype(float))
        calibrators.append(calibrator)
    return calibrators


def _apply_isotonic_multiclass(
    calibrators: list[IsotonicRegression], raw: np.ndarray
) -> np.ndarray:
    calibrated = np.column_stack(
        [calibrator.predict(raw[:, index]) for index, calibrator in enumerate(calibrators)]
    )
    totals = calibrated.sum(axis=1, keepdims=True)
    totals[totals <= 0] = 1.0
    return calibrated / totals


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=1, keepdims=True)


def _temperature_nll(logits: np.ndarray, labels: np.ndarray, temperature: float) -> float:
    probs = _softmax(logits / temperature)
    picked = probs[np.arange(len(labels)), labels]
    return float(-np.mean(np.log(np.clip(picked, 1e-12, 1.0))))


def _fit_temperature(logits: np.ndarray, labels: np.ndarray) -> float:
    """Fit a positive scalar T minimising the multiclass NLL of softmax(logits / T).

    Golden-section search over ``TEMPERATURE_BOUNDS``; the NLL is unimodal in T.
    """
    lower, upper = TEMPERATURE_BOUNDS
    inv_phi = (np.sqrt(5.0) - 1.0) / 2.0
    x1 = upper - inv_phi * (upper - lower)
    x2 = lower + inv_phi * (upper - lower)
    f1 = _temperature_nll(logits, labels, x1)
    f2 = _temperature_nll(logits, labels, x2)
    for _ in range(64):
        if f1 < f2:
            upper, x2, f2 = x2, x1, f1
            x1 = upper - inv_phi * (upper - lower)
            f1 = _temperature_nll(logits, labels, x1)
        else:
            lower, x1, f1 = x1, x2, f2
            x2 = lower + inv_phi * (upper - lower)
            f2 = _temperature_nll(logits, labels, x2)
    return float((lower + upper) / 2.0)


def _train_booster(
    fit_df: pd.DataFrame,
    val_df: pd.DataFrame | None,
    label_fn,
    params: dict,
) -> lgb.Booster:
    train_set = lgb.Dataset(_matrix(fit_df), label=label_fn(fit_df))
    if val_df is None:
        return lgb.train(params, train_set, num_boost_round=200)
    val_set = lgb.Dataset(_matrix(val_df), label=label_fn(val_df), reference=train_set)
    return lgb.train(
        params,
        train_set,
        num_boost_round=NUM_BOOST_ROUND,
        valid_sets=[val_set],
        callbacks=[lgb.early_stopping(EARLY_STOPPING_ROUNDS, verbose=False)],
    )


def train_1x2(
    train_df: pd.DataFrame,
    calibration_df: pd.DataFrame,
    eval_df: pd.DataFrame,
    params: dict | None = None,
) -> TrainedModel:
    train_df = train_df.dropna(subset=["label_1x2"])
    calibration_df = calibration_df.dropna(subset=["label_1x2"])
    eval_df = eval_df.dropna(subset=["label_1x2"])
    if len(train_df) < MIN_TRAIN_ROWS:
        raise ValueError(f"need at least {MIN_TRAIN_ROWS} 1x2 training rows")
    if calibration_df.empty:
        raise ValueError("no 1x2 calibration rows")
    fit_df, val_df = _temporal_val_split(train_df)
    booster = _train_booster(fit_df, val_df, _labels_1x2, {**DEFAULT_1X2_PARAMS, **(params or {})})
    raw_logits = np.asarray(
        booster.predict(_matrix(calibration_df), raw_score=True)
    ).reshape(len(calibration_df), 3)
    temperature = _fit_temperature(raw_logits, _labels_1x2(calibration_df))
    model = TrainedModel(
        target=TARGET_1X2, booster=booster, calibrators=[], temperature=temperature
    )
    if not eval_df.empty:
        probs = predict_proba(model, eval_df[FEATURE_COLUMNS].to_dict("records"))
        model.metrics = evaluate_1x2(probs, eval_df["label_1x2"].tolist())
    return model


def train_handicap(
    train_df: pd.DataFrame,
    calibration_df: pd.DataFrame,
    eval_df: pd.DataFrame,
    params: dict | None = None,
) -> TrainedModel:
    train_df = train_df.dropna(subset=["label_handicap"])
    calibration_df = calibration_df.dropna(subset=["label_handicap"])
    eval_df = eval_df.dropna(subset=["label_handicap"])
    if len(train_df) < MIN_TRAIN_ROWS:
        raise ValueError(f"need at least {MIN_TRAIN_ROWS} handicap training rows")
    if calibration_df.empty:
        raise ValueError("no handicap calibration rows")
    fit_df, val_df = _temporal_val_split(train_df)
    booster = _train_booster(
        fit_df, val_df, _labels_handicap, {**DEFAULT_HANDICAP_PARAMS, **(params or {})}
    )
    raw_calibration = np.asarray(booster.predict(_matrix(calibration_df))).reshape(
        len(calibration_df)
    )
    calibrators = _fit_isotonic_binary(raw_calibration, _labels_handicap(calibration_df))
    model = TrainedModel(target=TARGET_HANDICAP, booster=booster, calibrators=calibrators)
    if not eval_df.empty:
        probs = predict_proba(model, eval_df[FEATURE_COLUMNS].to_dict("records"))
        model.metrics = evaluate_handicap(probs, eval_df["label_handicap"].tolist())
    return model


def predict_proba(
    model: TrainedModel,
    features: list[dict[str, float]],
    calibrated: bool = True,
) -> np.ndarray:
    """Calibrated probabilities: (n, 3) for 1X2, (n,) for handicap."""
    frame = pd.DataFrame(
        [
            {column: row.get(column, float("nan")) for column in model.feature_columns}
            for row in features
        ],
        columns=model.feature_columns,
    )
    if model.target == TARGET_1X2:
        if calibrated and model.temperature is not None:
            logits = np.asarray(model.booster.predict(frame, raw_score=True)).reshape(
                len(features), 3
            )
            return _softmax(logits / model.temperature)
        raw = np.asarray(model.booster.predict(frame)).reshape(len(features), 3)
        if calibrated and model.calibrators:
            return _apply_isotonic_multiclass(model.calibrators, raw)
        return raw
    raw = np.asarray(model.booster.predict(frame))
    raw = raw.reshape(len(features))
    if calibrated and model.calibrators:
        return _apply_isotonic_binary(model.calibrators, raw)
    return raw


def evaluate_1x2(probs: np.ndarray, labels: list[str]) -> dict:
    y = np.array([LABEL_TO_INDEX[label] for label in labels])
    onehot = np.eye(3)[y]
    brier = float(np.mean(np.sum((probs - onehot) ** 2, axis=1)))
    logloss = float(log_loss(y, probs, labels=[0, 1, 2]))
    return {"brier": brier, "logloss": logloss, "n": len(y)}


def evaluate_handicap(probs: np.ndarray, labels: list[str]) -> dict:
    y = np.array([1 if label == "H" else 0 for label in labels])
    brier = float(np.mean((probs - y) ** 2))
    logloss = float(log_loss(y, probs, labels=[0, 1]))
    return {"brier": brier, "logloss": logloss, "n": len(y)}


def save_artifact(model: TrainedModel, path: str | Path) -> None:
    joblib.dump(
        {
            "target": model.target,
            "booster": model.booster,
            "calibrators": model.calibrators,
            "temperature": model.temperature,
            "feature_columns": model.feature_columns,
            "feature_version": model.feature_version,
        },
        path,
    )


def load_artifact(path: str | Path) -> TrainedModel:
    payload = joblib.load(path)
    return TrainedModel(
        target=payload["target"],
        booster=payload["booster"],
        calibrators=payload["calibrators"],
        temperature=payload.get("temperature"),
        feature_columns=payload["feature_columns"],
        feature_version=payload["feature_version"],
    )
