# Quarter-Line Phase 2a: Per-Target Dataset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Make `build_dataset` assemble a dataset **per target**, filtering rows to those carrying that target's label **before** the temporal split — the blocker that currently keeps the handicap model from ever training.

**Architecture:** `temporal_split` slices the frame chronologically. Today `build_dataset` splits **one** frame containing both targets' labels and `_train_challenger_sync` feeds the same slices to both trainers. Because `label_handicap` only exists where an HKJC HDC prior was available (i.e. only in the newest window), every handicap-labelled row lands in `eval` while `train`/`calibration` hold only `label_1x2` rows — so `train_handicap` always sees an empty (or calibration-less) slice. Phase 2a adds a `target` parameter to `build_dataset` that drops rows without that target's label before splitting, and makes `retrain` build one dataset per target while staying tolerant when a target has no data yet.

**Tech Stack:** unchanged (Python 3.11+, async SQLAlchemy 2.x, LightGBM, pytest, ruff).

## Global Constraints

- **Do not change `temporal_split`, `_frame`, `load_training_rows`, `load_market_priors`, `handicap_label`, or any feature logic.** This task only adds the per-target filter and the per-target plumbing in `retrain`/`_train_challenger_sync`.
- **1X2 behaviour must stay byte-for-byte.** With the 1X2 dataset, the filtering drops only rows whose `label_1x2` is null — in the current data that is **no** row (every confirmed result has a 1x2 label), so the 1X2 dataset must be identical to today's.
- **A target with no labelled rows must not break the other target**: `build_dataset` raises `ValueError` for an empty filtered frame; `retrain` catches it per target, logs, and continues with whichever target has data.
- **CLV stays 1X2-only**: `_eval_closing_priors` is computed from the 1X2 dataset's `eval` frame when that dataset exists, else `{}`.
- **No schema change / no migration.** No new settings. No changes to `app/ml/predict.py`, `app/services/ledger.py`, or the API.
- **No new heavy imports in `app/ml/dataset.py`**: do **not** import `app.ml.models` (it pulls LightGBM). Map the target string to its label column with a local dict and raise `KeyError`/`ValueError` on an unknown target.
- Gates: `uv run pytest` (live deselected) + `uv run ruff check .`. Chinese `type: 描述` commits. Branch `feat/per-target-dataset`. Never commit to `main`.

## Deferred (do NOT do these here)

- **Serving** (`p_eff` = `(1 + EV/S)/O`, half-line evaluation, `edge = p_eff - fair_prob`, `recommended_fraction = kelly_fraction(p_eff, O)`) and **placement** (removing the `is_whole_or_half` guard) — both are only meaningful once a handicap champion can train and HKJC HDC snapshots have accumulated. Separate plan.
- Emitting **two rows per quarter-line match** (one per half-line) in `_frame`. Also separate: it needs this per-target filtering first, and `temporal_split` is already match-safe (Phase 1 Task 3).

---

### Task 1: Per-target dataset + retrain plumbing

**Files:**
- Modify: `app/ml/dataset.py` (add `LABEL_COLUMNS`, add the `target` parameter to `build_dataset`)
- Modify: `app/ml/jobs.py` (`retrain` builds per-target datasets; `_train_challenger_sync` takes both)
- Test: `tests/test_ml_dataset.py`, `tests/test_ml_jobs.py` (append)

**Interfaces:**
- Produces: `build_dataset(session, settings, target: str = "1x2") -> Dataset`; `LABEL_COLUMNS: dict[str, str]`; `_train_challenger_sync(dataset_1x2: Dataset | None, dataset_handicap: Dataset | None, closing_priors: dict, settings: Settings, champion_paths: dict[str, str]) -> dict | None`.
- Consumes: existing `Dataset`, `temporal_split`, `_frame`, `load_training_rows`, `load_market_priors`, `train_1x2`, `train_handicap`, `_eval_closing_priors`, `TARGET_1X2`, `TARGET_HANDICAP` (from `app.ml.models`, already imported by `jobs.py`).

- [ ] **Step 1: Write the failing dataset tests**

Append to `tests/test_ml_dataset.py` (reuse its existing `make_db`/`seed_*` helpers and payload constants):

```python
async def test_build_dataset_per_target_puts_handicap_rows_in_every_slice(tmp_path) -> None:
    """The Phase-2a blocker: handicap labels exist only in the newest window."""
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            home = await seed_team(session, "Home")
            away = await seed_team(session, "Away")
            for index in range(40):
                kickoff = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index)
                await seed_finished_match(
                    session,
                    league,
                    season,
                    home,
                    away,
                    match_id_label=f"M{index}",
                    kickoff=kickoff,
                    home_score=2,
                    away_score=1,
                    had_payload=HAD,
                    hdc_payload=HDC if index >= 30 else None,
                )
            await session.commit()
        async with db.session_factory() as session:
            handicap = await build_dataset(session, _settings(), "handicap")
            one_x_two = await build_dataset(session, _settings(), "1x2")
        assert not handicap.train.empty
        assert not handicap.calibration.empty
        assert not handicap.eval.empty
        assert handicap.train["label_handicap"].notna().all()
        assert len(one_x_two.train) > len(handicap.train)
    finally:
        await db.dispose()


async def test_build_dataset_unknown_target_raises(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            with pytest.raises(KeyError):
                await build_dataset(session, _settings(), "corners")
    finally:
        await db.dispose()


async def test_build_dataset_empty_target_raises(tmp_path) -> None:
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            home = await seed_team(session, "Home")
            away = await seed_team(session, "Away")
            await seed_finished_match(
                session,
                league,
                season,
                home,
                away,
                match_id_label="M0",
                kickoff=datetime(2026, 1, 1, tzinfo=UTC),
                home_score=2,
                away_score=1,
                had_payload=HAD,
            )
            await session.commit()
        async with db.session_factory() as session:
            with pytest.raises(ValueError, match="no handicap training rows"):
                await build_dataset(session, _settings(), "handicap")
    finally:
        await db.dispose()
```

Add `timedelta` to that file's `datetime` import if missing, and make sure `pytest`, `build_dataset` are imported.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_ml_dataset.py -q`
Expected: FAIL — `build_dataset()` got an unexpected keyword `target` (currently it takes only `session, settings`), so the three new tests error out.

- [ ] **Step 3: Implement `build_dataset`**

In `app/ml/dataset.py`, above `build_dataset` add the map, then replace `build_dataset`:

```python
LABEL_COLUMNS: dict[str, str] = {"1x2": "label_1x2", "handicap": "label_handicap"}


async def build_dataset(
    session: AsyncSession, settings: Settings, target: str = "1x2"
) -> Dataset:
    """Assemble the training dataset for one target.

    Rows are filtered to those carrying that target's label **before** the temporal
    split: a target whose labels only exist in the newest window (handicap, once HKJC
    HDC snapshots start) would otherwise fill `eval` alone and leave `train` and
    `calibration` empty, so its model could never train.
    """
    label_column = LABEL_COLUMNS[target]
    rows = await load_training_rows(session, settings)
    if not rows:
        raise ValueError("no confirmed results in the configured history window")
    priors = await load_market_priors(session, rows, settings.ml_prior_lead_hours)
    frame = _frame(rows, priors)
    if label_column not in frame.columns:
        raise ValueError(f"dataset has no {label_column} column")
    frame = frame.dropna(subset=[label_column])
    if frame.empty:
        raise ValueError(f"no {target} training rows in the configured history window")
    train, calibration, evaluation = temporal_split(frame)
    return Dataset(train=train, calibration=calibration, eval=evaluation)
```

- [ ] **Step 4: Run the dataset tests**

Run: `uv run pytest tests/test_ml_dataset.py tests/test_ml_jobs.py -q`
Expected: the three new dataset tests PASS; existing dataset/jobs tests still pass (the 1X2 path is unchanged because no confirmed result has a null `label_1x2`).

- [ ] **Step 5: Write the failing retrain test**

Append to `tests/test_ml_jobs.py` (mirror that file's existing retrain test setup; seed HDC payloads so a handicap champion can exist). HDC only for the newest matches (`index >= 11` → 29 labelled rows) with `ml_min_train_rows=5`: the per-target handicap frame then holds ≥20 labelled rows in `train`, which is what `train_handicap`'s own hardcoded `MIN_TRAIN_ROWS = 20` (`app/ml/models.py`) requires — with only 10 labelled rows the handicap model is skipped and the test cannot pass. The 29-row seed also keeps the test RED against the pre-change code (its single-frame split leaves only ~17 labelled rows in `train`):

```python
async def test_retrain_trains_handicap_when_only_its_labels_are_new(tmp_path) -> None:
    """With per-target datasets the handicap model trains even though its labels
    only sit in the newest slice; 1x2 must still be trained in the same run."""
    db = await make_db(tmp_path)
    try:
        async with db.session_factory() as session:
            league, season = await seed_context(session)
            home = await seed_team(session, "Home")
            away = await seed_team(session, "Away")
            for index in range(40):
                kickoff = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=index)
                await seed_finished_match(
                    session,
                    league,
                    season,
                    home,
                    away,
                    match_id_label=f"M{index}",
                    kickoff=kickoff,
                    home_score=2,
                    away_score=1,
                    had_payload=HAD,
                    hdc_payload=HDC if index >= 11 else None,
                    snapshot_at_offset_hours=-49,
                )
            await session.commit()
        async with db.session_factory() as session:
            promoted = await retrain(
                db.session_factory,
                _settings(ml_min_train_rows=5, ml_artifact_dir=str(tmp_path / "artifacts")),
            )
        async with db.session_factory() as session:
            versions = (await session.execute(select(ModelVersion))).scalars().all()
        assert promoted == 2
        assert {version.target for version in versions} == {"1x2", "handicap"}
        assert {version.status for version in versions} == {"champion"}
    finally:
        await db.dispose()
```

- [ ] **Step 6: Implement the retrain plumbing**

In `app/ml/jobs.py`, replace `_train_challenger_sync` with the two-dataset version (keep the body of each branch as-is, only the dataset sources change):

```python
def _train_challenger_sync(
    dataset_1x2: Dataset | None,
    dataset_handicap: Dataset | None,
    closing_priors: dict[int, dict[str, float]],
    settings: Settings,
    champion_paths: dict[str, str],
) -> dict | None:
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
            clv = clv_metrics(_model_probs_1x2(model_1x2, dataset_1x2.eval), closing_priors)
            metrics = {**model_1x2.metrics, **clv}
            path = artifact_dir / f"1x2-{stamp}.joblib"
            save_artifact(model_1x2, path)
            result[TARGET_1X2] = {
                "path": str(path),
                "params": {"num_trees": int(model_1x2.booster.num_trees())},
                "metrics": metrics,
                "champion_metrics": _fresh_champion_metrics(
                    TARGET_1X2, champion_paths.get(TARGET_1X2), dataset_1x2.eval, closing_priors
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
                    TARGET_HANDICAP, champion_paths.get(TARGET_HANDICAP), dataset_handicap.eval, closing_priors
                ),
            }
    elif dataset_handicap is not None:
        logger.warning(
            "retrain skipped for handicap: %d train rows < %d",
            len(dataset_handicap.train),
            settings.ml_min_train_rows,
        )
    return result
```

Then in `retrain`, replace the single `build_dataset` call and the `_train_challenger_sync` call:

```python
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
```

Leave the rest of `retrain` (the `register_challenger` / `maybe_promote` loop and `track_run`) exactly as it is. Import `build_dataset` from `app.ml.dataset` if it is not already imported, and `Dataset` for the annotation.

- [ ] **Step 7: Run the full gates**

Run: `uv run pytest -q && uv run ruff check .`
Expected: all tests pass (the suite grows by 4 tests: 3 dataset + 1 retrain); ruff clean.

- [ ] **Step 8: Commit**

```bash
git add app/ml/dataset.py app/ml/jobs.py tests/test_ml_dataset.py tests/test_ml_jobs.py
git commit -m "feat: 資料集改為 per-target 過濾（先過濾再切分，解鎖讓球模型訓練）"
```

---

## Self-Review

- **Spec coverage:** the one requirement Oracle's staging named as "Step 0" — *filter rows per target before splitting so the handicap model can train* — is Task 1, with the failing test (`test_build_dataset_per_target_puts_handicap_rows_in_every_slice`) written first and reproducing the exact production symptom (all handicap labels in `eval`). Serving/placement are explicitly deferred with a reason.
- **Placeholder scan:** no TBD/TODO; every code step shows complete code; every run step shows the command and the expected result; the commit message is given.
- **Type consistency:** `build_dataset(session, settings, target: str = "1x2") -> Dataset` is used identically in the tests and in `retrain`; `LABEL_COLUMNS` is the only new module-level name; `_train_challenger_sync`'s new signature (`dataset_1x2, dataset_handicap, closing_priors, settings, champion_paths`) matches its only call site (the `asyncio.to_thread` in `retrain`); `_eval_closing_priors(session, dataset)` keeps its existing signature and is fed the 1X2 dataset.
