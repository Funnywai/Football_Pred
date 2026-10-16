import joblib
import numpy as np
import pandas as pd
import pytest

from app.ml.features import FEATURE_COLUMNS, FEATURE_VERSION
from app.ml.models import (
    TARGET_1X2,
    TrainedModel,
    _apply_isotonic_binary,
    _apply_isotonic_multiclass,
    _fit_isotonic_binary,
    _fit_isotonic_multiclass,
    _fit_temperature,
    _temperature_nll,
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


class _StubBooster:
    """Minimal booster double: fixed logits for raw_score, their softmax otherwise."""

    def __init__(self, logits: np.ndarray) -> None:
        self._logits = np.asarray(logits, dtype=float)

    def predict(self, frame, raw_score: bool = False) -> np.ndarray:
        logits = self._logits[: len(frame)]
        if raw_score:
            return logits
        shifted = logits - logits.max(axis=1, keepdims=True)
        exp = np.exp(shifted)
        return exp / exp.sum(axis=1, keepdims=True)


def test_train_1x2_fits_temperature_and_valid_distribution() -> None:
    df = _frame(600, seed=11)
    model = train_1x2(df.iloc[:420], df.iloc[420:480], df.iloc[480:])
    assert model.temperature is not None
    assert model.temperature > 0.0
    assert model.calibrators == []
    probs = predict_proba(model, df.iloc[480:][FEATURE_COLUMNS].to_dict("records"))
    assert probs.shape == (120, 3)
    assert np.isfinite(probs).all()
    assert (probs > 0.0).all()
    assert (probs < 1.0).all()
    assert np.allclose(probs.sum(axis=1), 1.0)


def test_temperature_not_worse_than_isotonic_on_small_noisy_calibration() -> None:
    rng = np.random.default_rng(7)
    n_cal, n_eval = 40, 4000

    def draw(n: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        strength = rng.normal(0.0, 1.5, n)
        logits = np.column_stack([strength, np.zeros(n), -strength])
        probs = np.exp(logits) / np.exp(logits).sum(axis=1, keepdims=True)
        labels = np.array([rng.choice(3, p=row) for row in probs])
        noisy = rng.uniform(size=n) < 0.15
        labels = np.where(noisy, rng.integers(0, 3, n), labels)
        return logits, probs, labels

    cal_logits, cal_probs, cal_labels = draw(n_cal)
    eval_logits, eval_probs, eval_labels = draw(n_eval)
    temperature = _fit_temperature(cal_logits, cal_labels)
    assert temperature > 0.0
    nll_temperature = _temperature_nll(eval_logits, eval_labels, temperature)
    assert np.isfinite(nll_temperature)
    calibrators = _fit_isotonic_multiclass(cal_probs, cal_labels)
    iso_probs = _apply_isotonic_multiclass(calibrators, eval_probs)
    nll_isotonic = float(
        -np.mean(np.log(np.clip(iso_probs[np.arange(n_eval), eval_labels], 1e-12, 1.0)))
    )
    assert nll_temperature <= nll_isotonic


def test_predict_proba_applies_temperature_to_fixed_logits() -> None:
    logits = np.array([[1.0, 0.0, -1.0]])
    model = TrainedModel(
        target=TARGET_1X2,
        booster=_StubBooster(logits),
        calibrators=[],
        temperature=2.0,
    )
    probs = predict_proba(model, [{}])
    assert np.allclose(probs, [[0.50648039, 0.30719589, 0.18632372]], atol=1e-6)
    raw = predict_proba(model, [{}], calibrated=False)
    assert np.allclose(raw, [[0.66524096, 0.24472847, 0.09003057]], atol=1e-6)


def test_legacy_model_without_temperature_uses_calibrators() -> None:
    rng = np.random.default_rng(3)
    n = 200
    probs = rng.uniform(0.05, 0.95, (n, 3))
    probs = probs / probs.sum(axis=1, keepdims=True)
    labels = np.array([rng.choice(3, p=row) for row in probs])
    calibrators = _fit_isotonic_multiclass(probs, labels)
    model = TrainedModel(
        target=TARGET_1X2,
        booster=_StubBooster(np.log(probs)),
        calibrators=calibrators,
    )
    assert model.temperature is None
    got = predict_proba(model, [{}])
    expected = _apply_isotonic_multiclass(calibrators, probs[:1])
    assert np.allclose(got, expected)


def test_load_legacy_artifact_without_temperature(tmp_path) -> None:
    rng = np.random.default_rng(4)
    n = 200
    probs = rng.uniform(0.05, 0.95, (n, 3))
    probs = probs / probs.sum(axis=1, keepdims=True)
    labels = np.array([rng.choice(3, p=row) for row in probs])
    calibrators = _fit_isotonic_multiclass(probs, labels)
    path = tmp_path / "legacy.joblib"
    joblib.dump(
        {
            "target": TARGET_1X2,
            "booster": _StubBooster(np.log(probs)),
            "calibrators": calibrators,
            "feature_columns": list(FEATURE_COLUMNS),
            "feature_version": FEATURE_VERSION,
        },
        path,
    )
    model = load_artifact(path)
    assert model.temperature is None
    got = predict_proba(model, [{}])
    expected = _apply_isotonic_multiclass(calibrators, probs[:1])
    assert np.allclose(got, expected)


def test_save_load_roundtrip_preserves_temperature(tmp_path) -> None:
    df = _frame(600, seed=5)
    model = train_1x2(df.iloc[:420], df.iloc[420:480], df.iloc[480:])
    path = tmp_path / "temperature.joblib"
    save_artifact(model, path)
    reloaded = load_artifact(path)
    assert reloaded.temperature == model.temperature
    rows = df.iloc[480:][FEATURE_COLUMNS].to_dict("records")
    assert np.allclose(predict_proba(model, rows), predict_proba(reloaded, rows))
