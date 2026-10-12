import numpy as np
import pandas as pd
import pytest

from app.ml.features import FEATURE_COLUMNS
from app.ml.models import (
    TARGET_1X2,
    _apply_isotonic_binary,
    _fit_isotonic_binary,
    load_artifact,
    predict_proba,
    save_artifact,
    train_1x2,
    train_handicap,
)


def _frame(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({column: rng.normal(size=n) for column in FEATURE_COLUMNS})
    df["kickoff_time"] = pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC")
    df["match_id"] = range(n)
    strength = df["elo_diff"].to_numpy()
    logits = np.column_stack([strength, np.zeros(n), -strength])
    probs = np.exp(logits) / np.exp(logits).sum(axis=1, keepdims=True)
    labels = np.array(["H", "D", "A"])[
        [rng.choice(3, p=row) for row in probs]
    ]
    df["label_1x2"] = labels
    df["label_handicap"] = np.where(rng.uniform(size=n) < 1 / (1 + np.exp(-strength)), "H", "A")
    return df


def test_isotonic_binary_calibration_improves_brier() -> None:
    rng = np.random.default_rng(0)
    n = 4000
    p_true = rng.uniform(0.05, 0.95, n)
    y = (rng.uniform(size=n) < p_true).astype(int)
    raw = p_true**2  # deliberately miscalibrated
    calibrators = _fit_isotonic_binary(raw[:2000], y[:2000])
    calibrated = _apply_isotonic_binary(calibrators, raw[2000:])
    brier_raw = float(np.mean((raw[2000:] - y[2000:]) ** 2))
    brier_calibrated = float(np.mean((calibrated - y[2000:]) ** 2))
    assert brier_calibrated < brier_raw


def test_train_predict_evaluate_1x2(tmp_path) -> None:
    df = _frame(600, seed=1)
    model = train_1x2(df.iloc[:420], df.iloc[420:480], df.iloc[480:])
    probs = predict_proba(model, df.iloc[480:][FEATURE_COLUMNS].to_dict("records"))
    assert probs.shape == (120, 3)
    assert np.allclose(probs.sum(axis=1), 1.0)
    assert "brier" in model.metrics and "logloss" in model.metrics
    assert model.target == TARGET_1X2
    path = tmp_path / "m1x2.joblib"
    save_artifact(model, path)
    reloaded = load_artifact(path)
    again = predict_proba(reloaded, df.iloc[480:][FEATURE_COLUMNS].to_dict("records"))
    assert np.allclose(probs, again)


def test_train_handicap(tmp_path) -> None:
    df = _frame(400, seed=2)
    model = train_handicap(df.iloc[:280], df.iloc[280:320], df.iloc[320:])
    probs = predict_proba(model, df.iloc[320:][FEATURE_COLUMNS].to_dict("records"))
    assert probs.shape == (80,)
    assert ((probs >= 0) & (probs <= 1)).all()


def test_train_requires_rows() -> None:
    empty = _frame(5, seed=3)
    with pytest.raises(ValueError):
        train_1x2(empty.iloc[:0], empty.iloc[:0], empty.iloc[:0])


def test_calibrated_probs_stay_strictly_inside_unit_interval() -> None:
    df = _frame(600, seed=4)
    # The calibration slice contains no draws, so the "D" calibrator sees zero
    # positives; without an epsilon floor it emits exact 0.0 probabilities.
    calibration = df.iloc[420:480].copy()
    calibration["label_1x2"] = np.where(
        calibration["label_1x2"] == "D", "H", calibration["label_1x2"]
    )
    model = train_1x2(df.iloc[:420], calibration, df.iloc[480:])
    probs = predict_proba(model, df.iloc[480:][FEATURE_COLUMNS].to_dict("records"))
    assert (probs > 0.0).all()
    assert (probs < 1.0).all()
