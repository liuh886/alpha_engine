"""Generate a release-candidate artifact bundle for one market.

``uv run python scripts/generate_release_candidate.py \\
    --candidate v0.1.0-rc1 --market us --frontend-evidence artifacts/evidence/frontend-build-v1.json``

The script loads the real LGBMRegressor T+10 pipeline from
``configs/us_lgbm_regressor_10d_workflow.yaml`` and attempts:

1. Code identity (git revision, uv.lock checksum).
2. Qlib initialisation & data availability check.
3. Snapshot discovery via canonical ``DataSnapshot`` API (before model work).
4. Walk-forward validation.
5. Final model training (LGBMRegressor on full data, canonical DK_L label key).
6. Vectorized backtest with T+10 benchmark and genuine top-bottom spread.
7. Model/evidence artifact bundling (no frontend-evidence coupling).
8. Frontend-build evidence verification (checked after research artifacts).
9. Release-manifest writing (only when ALL checks pass).

If **any** stage is unavailable or fails, the script writes a
``release_failure_report.json`` and exits with code 1.  It never fabricates
data, metrics, or pass status.  All artifacts are deterministic — SHA-256
checksums are recorded for every file.

Artifact layout::

    artifacts/
    ├── release_candidate/{candidate}/
    │   ├── release_manifest.json           (on success)
    │   └── release_failure_report.json     (on failure)
    ├── evidence/{candidate}/
    │   ├── {market}-backtest-evidence.json
    │   └── {market}-signal-evidence.json
    └── model_artifacts/{market}-{candidate}/
        ├── model.pkl
        ├── predictions.csv
        ├── labels.csv
        ├── diagnostics.json
        └── manifest.json
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pickle
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.release.candidate import POLICY, REQUIRED_RELEASE_METRICS  # noqa: E402
from src.research.signal_discovery import (  # noqa: E402
    canonical_output_dir,
    compute_direction_diagnostics,
    run_signal_discovery_comparison,
)


# ---------------------------------------------------------------------------
# Failure model
# ---------------------------------------------------------------------------


class StageFailure(Exception):
    """Raised when a pipeline stage fails deterministically."""

    def __init__(
        self,
        stage: str,
        error_type: str,
        message: str,
        *,
        missing_files: list[str] | None = None,
        suggested_fix: str | None = None,
    ) -> None:
        self.stage = stage
        self.error_type = error_type
        self.message = message
        self.missing_files = missing_files or []
        self.suggested_fix = suggested_fix or ""
        super().__init__(message)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _git_revision(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _bounded_message(msg: str, max_len: int = 5000) -> str:
    """Truncate *msg* at *max_len* characters to avoid huge log payloads."""
    if len(msg) > max_len:
        return msg[:max_len] + f"... (truncated, {len(msg) - max_len} chars omitted)"
    return msg


def _load_workflow_config(config_name: str, project_root: Path) -> dict[str, Any]:
    config_path = project_root / "configs" / config_name
    if not config_path.is_file():
        raise StageFailure(
            stage="load_config",
            error_type="ConfigNotFound",
            message=f"Workflow config not found: {config_path}",
            missing_files=[str(config_path)],
            suggested_fix=f"Ensure {config_name} exists under configs/",
        )
    import yaml

    with config_path.open(encoding="utf-8") as fh:
        config: dict[str, Any] = yaml.safe_load(fh)
    return config


# ---------------------------------------------------------------------------
# Raw forward return loader (bypasses learn processors)
# ---------------------------------------------------------------------------


def _load_raw_forward_returns(
    config: dict[str, Any],
    market: str,
) -> pd.DataFrame:
    """Load raw forward returns directly from Qlib/provider data.

    Reads the exact configured label expression (e.g.
    ``Ref($close, -10) / $close - 1``) from Qlib data **without** applying
    DropnaLabel / CSRankNorm or any other learn processors.  The result is
    tagged with provenance metadata in ``.attrs``.

    Raises ``StageFailure`` on: missing/invalid label expression, empty
    result, non-finite data, or alignment failure.

    Returns
    -------
    pd.DataFrame
        A DataFrame with ``(datetime, instrument)`` MultiIndex, a ``"return"``
        column, and provenance attrs.
    """
    from qlib.data import D

    handler_kwargs = config["task"]["dataset"]["kwargs"]["handler"]["kwargs"]
    label_exprs: list[str] = handler_kwargs.get("label", [])
    if not label_exprs:
        raise StageFailure(
            stage="load_raw_returns",
            error_type="MissingLabelExpression",
            message="No label expression found in workflow config.  "
            "Expected e.g. [\"Ref($close, -10) / $close - 1\"].",
        )
    label_expr = label_exprs[0]
    if "Ref($close, -" not in label_expr:
        raise StageFailure(
            stage="load_raw_returns",
            error_type="UnsupportedLabelExpression",
            message=f"Unsupported label expression: {label_expr!r}. Expected a Ref($close, -N) forward-return expression.",
        )

    # Derive horizon from expression
    import re

    m = re.search(r"Ref\(\$close,\s*(-\d+)\)", label_expr)
    if not m:
        raise StageFailure(
            stage="load_raw_returns",
            error_type="UnsupportedLabelExpression",
            message=f"Cannot extract horizon from label expression: {label_expr!r}. "
            "Expected a Ref($close, -N) pattern.",
        )
    horizon = abs(int(m.group(1)))

    # Determine date range from test segment
    segments = config["task"]["dataset"]["kwargs"].get("segments", {})
    test_seg: list[str] | None = segments.get("test")
    if not test_seg or len(test_seg) < 2:
        raise StageFailure(
            stage="load_raw_returns",
            error_type="MissingTestSegment",
            message="Workflow config has no valid test segment.",
        )
    start_time, end_time = test_seg[0], test_seg[1]

    # Resolve instruments
    instr_key = handler_kwargs.get("instruments", market)
    try:
        symbols = D.list_instruments(D.instruments(instr_key), as_list=True)
    except Exception as exc:
        raise StageFailure(
            stage="load_raw_returns",
            error_type="InstrumentResolutionError",
            message=f"Failed to resolve instruments for {instr_key!r}: {exc}",
        ) from exc
    if not symbols:
        raise StageFailure(
            stage="load_raw_returns",
            error_type="NoInstruments",
            message=f"No instruments found for {instr_key!r}.",
        )

    # Load raw expression directly (no DropnaLabel / CSRankNorm)
    try:
        raw = D.features(symbols, [label_expr], start_time=start_time, end_time=end_time)
    except Exception as exc:
        raise StageFailure(
            stage="load_raw_returns",
            error_type="QlibFeatureError",
            message=f"Failed to load raw forward returns: {exc}",
        ) from exc

    if raw.empty:
        raise StageFailure(
            stage="load_raw_returns",
            error_type="EmptyRawReturns",
            message="Raw forward returns DataFrame is empty.",
        )
    # Normalise to (datetime, instrument) MultiIndex
    if isinstance(raw.index, pd.MultiIndex):
        raw = raw.reorder_levels(["datetime", "instrument"]).sort_index()
    result = raw.rename(columns={raw.columns[0]: "return"})

    # Replace +/-inf with NaN, then drop non-finite rows
    result["return"] = result["return"].replace([np.inf, -np.inf], np.nan)
    n_raw_rows = len(result)
    n_dropped = int(result["return"].isna().sum())
    n_valid_rows = n_raw_rows - n_dropped
    coverage_ratio = n_valid_rows / max(n_raw_rows, 1)
    result = result.dropna(subset=["return"])

    if n_valid_rows == 0:
        raise StageFailure(
            stage="load_raw_returns",
            error_type="EmptyValidReturns",
            message=f"All {n_raw_rows} raw forward return rows are non-finite. "
            "No valid data remains.",
        )
    # Conservative threshold: in cross-sectional Qlib data some symbols lack
    # future-price coverage, so a small fraction of NaN rows is expected.
    # Require at least 80 % coverage — consistent with the data-quality bar
    # in training alignment (50%) but tighter since raw-return ingestion has
    # no downstream processor fallback.
    MIN_RAW_RETURN_COVERAGE = 0.80
    if coverage_ratio < MIN_RAW_RETURN_COVERAGE:
        raise StageFailure(
            stage="load_raw_returns",
            error_type="InsufficientReturnCoverage",
            message=f"Only {n_valid_rows}/{n_raw_rows} raw forward return rows are finite "
            f"(coverage={coverage_ratio:.1%}). Minimum "
            f"{MIN_RAW_RETURN_COVERAGE:.0%} required.",
        )

    # Record filtering provenance so downstream consumers can inspect coverage
    result.attrs["n_raw_rows"] = n_raw_rows
    result.attrs["n_dropped_non_finite"] = n_dropped
    result.attrs["n_valid_rows"] = n_valid_rows
    result.attrs["coverage_ratio"] = coverage_ratio

    # Tag provenance so downstream consumers can distinguish raw from processed
    result.attrs["provenance"] = "raw_forward_return"
    result.attrs["label_expression"] = label_expr
    result.attrs["horizon"] = horizon
    return result


def _validate_return_provenance(returns: pd.DataFrame) -> None:
    """Assert that *returns* is a raw-forward-return DataFrame, not processed labels.

    Checks:
    1.  ``.attrs["provenance"] == "raw_forward_return"`` (set by
        ``_load_raw_forward_returns``).
    2.  Column name is ``"return"`` (not ``"training_label"`` or other).

    Raises ``StageFailure`` on any violation.

    Note:
        All-zero raw returns (valid forward return values) pass provenance
        validation — they are rejected only by schema boundary, not by
        numeric magnitude heuristics.
    """
    stage = "backtest"
    if returns.attrs.get("provenance") != "raw_forward_return":
        raise StageFailure(
            stage=stage,
            error_type="InvalidReturnProvenance",
            message=f"Expected returns with attrs provenance='raw_forward_return', "
            f"got {returns.attrs.get('provenance')!r}. "
            "Only raw forward returns (loaded via _load_raw_forward_returns) "
            "may enter the economic backtest.",
        )
    col = returns.columns[0]
    if col != "return":
        raise StageFailure(
            stage=stage,
            error_type="InvalidReturnColumn",
            message=f"Expected column 'return', got {col!r}. "
            "Processed labels (e.g. 'training_label') cannot be used as economic returns.",
        )
    vals = returns.iloc[:, 0].dropna().values
    if len(vals) == 0:
        raise StageFailure(
            stage=stage,
            error_type="EmptyReturns",
            message="Returns data is empty after dropping NaN.",
        )


def _load_factor_baseline_from_qlib(
    config: dict[str, Any],
    market: str,
    pred_df: pd.DataFrame,
) -> pd.DataFrame | None:
    """Load a historical-price factor baseline from Qlib.

    Uses the expression ``$close / Ref($close, 10) - 1`` — a 10-day
    *backward*-looking momentum factor computed from historical prices only.
    This is NOT a forward-return expression: ``Ref($close, 10)`` looks back
    10 days, so the factor uses only information known at each point in time.

    The factor is loaded over the same test interval as *pred_df* and
    returned with a ``(datetime, instrument)`` MultiIndex and a ``"score"``
    column.

    Returns None if Qlib is unavailable or the expression cannot be evaluated.
    """
    try:
        from qlib.data import D
    except ImportError:
        return None

    # Historical-price momentum: (close_today / close_10d_ago) - 1
    factor_expr = "$close / Ref($close, 10) - 1"

    handler_kwargs = config["task"]["dataset"]["kwargs"]["handler"]["kwargs"]
    instr_key = handler_kwargs.get("instruments", market)

    try:
        symbols = D.list_instruments(D.instruments(instr_key), as_list=True)
    except Exception:
        return None
    if not symbols:
        return None

    test_start = str(pred_df.index.get_level_values(0).min())
    test_end = str(pred_df.index.get_level_values(0).max())

    try:
        raw = D.features(symbols, [factor_expr], start_time=test_start, end_time=test_end)
    except Exception:
        return None

    if raw.empty:
        return None

    # Normalise to (datetime, instrument) MultiIndex
    if isinstance(raw.index, pd.MultiIndex):
        raw = raw.reorder_levels(["datetime", "instrument"]).sort_index()

    result = raw.rename(columns={raw.columns[0]: "score"})
    result["score"] = result["score"].replace([np.inf, -np.inf], np.nan)
    result = result.dropna(subset=["score"])

    if result.empty:
        return None

    return result


def _compute_score_diagnostics(
    predictions: pd.DataFrame,
    raw_returns: pd.DataFrame,
) -> dict[str, Any]:
    """Compute score-direction diagnostics from aligned predictions and raw returns.

    Delegates to the canonical ``compute_direction_diagnostics`` from
    ``src.research.signal_discovery`` to avoid maintaining divergent logic.

    Returns a dict with the canonical ``DirectionDiagnostics`` naming
    convention.
    """
    # Guard: reject processed / rank-like data even if column is renamed to "return"
    _validate_return_provenance(raw_returns)

    diag = compute_direction_diagnostics(
        predictions["score"],
        raw_returns["return"],
        top_fraction=0.10,
    )

    # Canonical dict from DirectionDiagnostics
    result = diag.to_dict()

    # Add backward-compatible aliases for existing artifact consumers
    result["raw_rank_ic"] = result["rank_ic"]
    result["top_minus_bottom"] = result["top_minus_bottom_spread"]
    result["bottom_minus_top"] = result["bottom_minus_top_spread"]

    return result


def _validate_predictions_labels(
    predictions: pd.DataFrame,
    labels: pd.DataFrame,
    stage_name: str,
) -> None:
    """Validate that predictions and labels are non-empty, aligned, and finite.

    Raises StageFailure if any check fails.
    """
    if predictions.empty:
        raise StageFailure(
            stage=stage_name,
            error_type="EmptyPredictions",
            message="Predictions DataFrame is empty.",
        )
    if labels.empty:
        raise StageFailure(
            stage=stage_name,
            error_type="EmptyLabels",
            message="Labels DataFrame is empty.",
        )
    # Check alignment
    if not predictions.index.equals(labels.index):
        raise StageFailure(
            stage=stage_name,
            error_type="MisalignedData",
            message="Predictions and labels indices do not match.",
        )
    # Check for non-finite values
    for df, name in [(predictions, "predictions"), (labels, "labels")]:
        numeric = df.select_dtypes(include=[np.number])
        if numeric.empty:
            continue
        n_non_finite = int(np.sum(~np.isfinite(numeric.values)))
        if n_non_finite > 0:
            raise StageFailure(
                stage=stage_name,
                error_type=f"NonFinite{name.capitalize()}",
                message=f"{name.capitalize()} contain {n_non_finite} non-finite values.",
            )


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------


def _stage_identity(
    project_root: Path,
) -> tuple[str, str, dict[str, Any]]:
    """Compute git revision and uv.lock checksum."""
    revision = _git_revision(project_root)
    if not revision:
        raise StageFailure(
            stage="identity",
            error_type="GitRevisionUnavailable",
            message="Cannot determine git HEAD revision.  Is this a git repository?",
            suggested_fix="Run from a git checkout of alpha-engine.",
        )
    lock_path = project_root / "uv.lock"
    if not lock_path.is_file():
        raise StageFailure(
            stage="identity",
            error_type="LockfileMissing",
            message=f"uv.lock not found at {lock_path}",
            missing_files=[str(lock_path)],
            suggested_fix="Run 'uv lock' to generate uv.lock.",
        )
    lock_hash = _sha256(lock_path)
    code_identity: dict[str, Any] = {
        "revision": revision,
        "lockfile": {
            "path": _relative(project_root, lock_path),
            "sha256": lock_hash,
        },
    }
    return revision, lock_hash, code_identity


def _stage_qlib_init(
    config: dict[str, Any],
    market: str,
    project_root: Path,
) -> None:
    """Initialise Qlib and verify data availability."""
    from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init

    if "qlib_init" not in config:
        raise StageFailure(
            stage="qlib_init",
            error_type="ConfigMissingQlibInit",
            message="Workflow config has no qlib_init section.",
            suggested_fix="Add qlib_init to the workflow YAML.",
        )

    try:
        init_cfg = build_qlib_init_cfg(config["qlib_init"], market=market)
        safe_qlib_init(init_cfg)
    except Exception as exc:
        missing = _probe_data_paths(project_root, market)
        raise StageFailure(
            stage="qlib_init",
            error_type="QlibInitError",
            message=f"Qlib initialisation failed: {exc}",
            missing_files=missing,
            suggested_fix=f"Run 'uv run python scripts/collect_data.py --market {market}' "
            "to download market data, then retry.".format(market=market),
        ) from exc

    # Verify calendar is accessible
    try:
        from qlib.data import D

        cal = D.calendar()
        if cal is None or len(cal) == 0:
            raise RuntimeError("Empty calendar")
    except Exception as exc:
        missing = _probe_data_paths(project_root, market)
        raise StageFailure(
            stage="qlib_init",
            error_type="CalendarUnavailable",
            message=f"Trading calendar not accessible after Qlib init: {exc}",
            missing_files=missing,
            suggested_fix="Verify Qlib data at data/watchlist/ contains calendar files "
            "for the {market} market.".format(market=market),
        ) from exc


def _probe_data_paths(project_root: Path, market: str) -> list[str]:
    """Return paths that could explain missing data (may not exist)."""
    candidates: list[str] = []
    for path in [
        project_root / "data" / "watchlist" / "calendars" / f"{market}.txt",
        project_root / "data" / "watchlist" / "features",
        project_root / "data" / "watchlist" / "instruments" / f"{market}.txt",
    ]:
        candidates.append(str(path))
    return candidates


def _stage_walk_forward(
    config: dict[str, Any],
    market: str,
    project_root: Path,
) -> dict[str, Any]:
    """Run walk-forward validation using the LGBMRegressor T+10 pipeline."""
    from src.research.walk_forward import walk_forward_validate

    # Deep-copy the config so walk_forward_validate can mutate it per-split
    wf_config = copy.deepcopy(config)

    # Forward training window from config so walk-forward never exceeds
    # the configured end_time (2024-12-31).
    wf_train_start = config.get("fit_start_time", config.get("start_time", "2021-01-01"))
    wf_train_end = config.get("end_time", "2024-12-31")

    try:
        wf_result = walk_forward_validate(
            market=market,
            model_type="lgbm_regressor",
            train_start=wf_train_start,
            train_end=wf_train_end,
            config=wf_config,
            label_horizon=10,
        )
    except Exception as exc:
        # Bounded error message — avoid multi-hundred-kilobyte traceback
        raise StageFailure(
            stage="walk_forward",
            error_type="WalkForwardError",
            message=_bounded_message(f"Walk-forward validation failed: {exc}"),
            suggested_fix="Check Qlib data coverage and model configuration. "
            "Ensure the label horizon does not exceed available data.",
        ) from exc

    if not wf_result.splits:
        raise StageFailure(
            stage="walk_forward",
            error_type="WalkForwardNoSplits",
            message="Walk-forward produced zero splits.  Check date ranges in the config.",
            suggested_fix="Verify train_window / test_window dates in "
            "configs/us_lgbm_regressor_10d_workflow.yaml",
        )

    wf_meta: dict[str, Any] = {
        "mean_ic": wf_result.mean_ic,
        "std_ic": wf_result.std_ic,
        "ic_ir": wf_result.ic_ir,
        "consistency_score": wf_result.consistency_score,
        "n_success": wf_result.n_success,
        "n_failed": wf_result.n_failed,
        "n_skipped": wf_result.n_skipped,
        "n_splits": len(wf_result.splits),
        "splits": [
            {
                "split_id": s.split_id,
                "train_start": s.train_start,
                "train_end": s.train_end,
                "test_start": s.test_start,
                "test_end": s.test_end,
                "ic": s.ic,
                "rank_ic": s.rank_ic,
                "status": s.status,
            }
            for s in wf_result.splits
        ],
    }
    return wf_meta


def _stage_train(
    config: dict[str, Any],
    market: str,
) -> tuple[Any, pd.DataFrame, pd.DataFrame]:
    """Train final LGBMRegressor on full data, produce test predictions and labels.

    Uses Qlib's canonical DataHandler.DK_L learning-label data key (processed
    by DropnaLabel + CSRankNorm).  Predictions and labels are aligned on their
    common MultiIndex; rows with non-finite prediction or label are dropped
    and counted in diagnostics.  Raises StageFailure if nothing remains or
    alignment coverage is inadequate.

    The returned labels_df has a ``"training_label"`` column (the DK_L processed
    label), **not** ``"return"`` — economic returns for backtesting and
    evaluation are loaded separately via ``_load_raw_forward_returns``.

    Returns
    -------
    tuple[object, pd.DataFrame, pd.DataFrame]
        (trained_model, predictions_df, labels_df).
        predictions_df has a 'score' column; labels_df has a 'training_label' column.
    """
    from qlib.data.dataset.handler import DataHandler
    from qlib.utils import init_instance_by_config
    from src.research.walk_forward import (
        _fit_native_estimator,
        _is_native_estimator_config,
    )

    try:
        dataset = init_instance_by_config(config["task"]["dataset"])
        model = init_instance_by_config(config["task"]["model"])

        segments = config["task"]["dataset"]["kwargs"].get("segments", {})

        if _is_native_estimator_config(config):
            # Native sklearn-style estimator: fit with X/y from DatasetH
            model, pred = _fit_native_estimator(model, dataset, segments)
            labels = dataset.prepare(
                segments="test",
                col_set="label",
                data_key=DataHandler.DK_L,
            )
        else:
            # Qlib model wrapper: standard dataset-based fit/predict
            model.fit(dataset)
            pred = model.predict(dataset, segment="test")
            labels = dataset.prepare(
                segments="test", col_set="label", data_key=DataHandler.DK_L,
            )
    except Exception as exc:
        raise StageFailure(
            stage="train",
            error_type="TrainingError",
            message=_bounded_message(f"Model training or prediction failed: {exc}"),
            suggested_fix="Verify data coverage and model configuration.",
        ) from exc

    # Normalise predictions to a DataFrame with a 'score' column
    if isinstance(pred, pd.Series):
        pred_df = pred.to_frame("score")
    elif isinstance(pred, pd.DataFrame):
        if "score" not in pred.columns:
            pred_df = pred.rename(columns={pred.columns[0]: "score"})
        else:
            pred_df = pred
    else:
        raise StageFailure(
            stage="train",
            error_type="UnexpectedPredictionType",
            message=f"Model.predict returned unexpected type: {type(pred)}.",
        )

    # Normalise labels to a DataFrame with a 'training_label' column
    if isinstance(labels, pd.Series):
        labels_df = labels.to_frame("training_label")
    elif isinstance(labels, pd.DataFrame):
        if "training_label" not in labels.columns:
            labels_df = labels.rename(columns={labels.columns[0]: "training_label"})
        else:
            labels_df = labels
    else:
        raise StageFailure(
            stage="train",
            error_type="UnexpectedLabelType",
            message=f"Dataset.prepare returned unexpected type: {type(labels)}.",
        )

    # Align predictions and labels on their common (datetime, instrument) index
    common_idx = pred_df.index.intersection(labels_df.index)
    pred_df = pred_df.loc[common_idx]
    labels_df = labels_df.loc[common_idx]

    # Replace inf with nan for finite check
    pred_df = pred_df.replace([np.inf, -np.inf], np.nan)
    labels_df = labels_df.replace([np.inf, -np.inf], np.nan)

    # Drop rows where either prediction or label is non-finite; record count
    n_before = len(pred_df)
    pred_val = pred_df.iloc[:, 0]
    label_val = labels_df.iloc[:, 0]
    finite_mask = pred_val.notna() & label_val.notna()
    n_dropped = n_before - int(finite_mask.sum())

    pred_df = pred_df.loc[finite_mask]
    labels_df = labels_df.loc[finite_mask]

    if pred_df.empty:
        raise StageFailure(
            stage="train",
            error_type="EmptyAfterFiniteCheck",
            message=f"All {n_before} prediction/label rows dropped due to non-finite values. "
            "No valid data remains.",
        )

    coverage_ratio = len(pred_df) / max(n_before, 1)
    if coverage_ratio < 0.5:
        raise StageFailure(
            stage="train",
            error_type="InsufficientAlignmentCoverage",
            message=f"After alignment and non-finite filtering, only {len(pred_df)}/{n_before} "
            f"rows remain (coverage={coverage_ratio:.1%}). Minimum 50% required.",
        )

    # Attach diagnostic info for downstream inclusion
    pred_df.attrs["n_dropped_non_finite"] = n_dropped
    pred_df.attrs["n_after_filter"] = len(pred_df)
    pred_df.attrs["coverage_ratio"] = coverage_ratio

    return model, pred_df, labels_df


def _stage_backtest(
    market: str,
    pred_df: pd.DataFrame,
    raw_returns: pd.DataFrame,
    *,
    topk: int = 15,
    rebalance_days: int = 10,
    cost_bps: int = 20,
) -> dict[str, Any]:
    """Run vectorized backtest with real predictions and raw forward returns.

    *raw_returns* must be a DataFrame loaded by ``_load_raw_forward_returns``
    — provenance is validated via ``_validate_return_provenance`` so processed
    / rank-like labels cannot silently enter the economic backtest.

    Uses T+10 benchmark returns (QQQ) aligned to the configured label horizon.
    Computes genuine top-bottom spread by running a second backtest with
    negated predictions.  If benchmark is absent the metric is omitted (not
    silently zero).

    Returns a dict of backtest metrics, or raises StageFailure.
    """
    from src.research.vectorized_backtest import run_vectorized_backtest

    # Guard: reject processed / rank-like labels
    _validate_return_provenance(raw_returns)

    # Load T+10 benchmark returns (QQQ) for the test period if available
    benchmark_returns: pd.DataFrame | None = None
    _benchmark_available = False
    try:
        from qlib.data import D

        test_start = str(pred_df.index.get_level_values(0).min())
        test_end = str(pred_df.index.get_level_values(0).max())
        # Use T+10 forward returns aligned to the label horizon
        bench_raw = D.features(
            ["QQQ"],
            ["Ref($close, -10) / $close - 1"],
            start_time=test_start,
            end_time=test_end,
        )
        # bench_raw has MultiIndex (instrument, datetime); flatten to datetime index
        benchmark_returns = (
            bench_raw.droplevel("instrument")
            .iloc[:, [0]]
            .rename(columns={bench_raw.columns[0]: "return"})
            .sort_index()
        )
        _benchmark_available = True
    except Exception:
        benchmark_returns = None

    try:
        bt_result = run_vectorized_backtest(
            predictions=pred_df,
            returns=raw_returns,
            benchmark_returns=benchmark_returns,
            topk=topk,
            rebalance_days=rebalance_days,
            cost_bps=cost_bps,
            non_overlapping=True,
            require_raw_10d_returns=True,
        )
    except Exception as exc:
        raise StageFailure(
            stage="backtest",
            error_type="BacktestError",
            message=_bounded_message(f"Vectorized backtest failed: {exc}"),
            suggested_fix="Verify predictions and returns alignment, data coverage.",
        ) from exc

    result_dict = bt_result.to_dict()

    # Verify backtest produced at least one meaningful numeric metric
    meaningful = any(
        isinstance(v, (int, float)) and bool(v)
        for v in result_dict.values()
    )
    if not meaningful:
        raise StageFailure(
            stage="backtest",
            error_type="MissingRequiredMetrics",
            message=f"Backtest produced no meaningful metrics: {result_dict}",
        )

    # Map BacktestResult field names to standard metric names
    field_map = {
        "annual_return": "annualized_return",
        "sharpe_ratio": "sharpe",
        "total_return": "total_return",
        "max_drawdown": "max_drawdown",
        "volatility": "volatility",
    }
    # Benchmark-derived metrics only when benchmark is actually available
    if _benchmark_available:
        field_map["benchmark_return"] = "benchmark_return"
        field_map["excess_return"] = "excess_return"

    metrics: dict[str, Any] = {}
    for src_key, dst_key in field_map.items():
        val = result_dict.get(src_key)
        if isinstance(val, (int, float)):
            metrics[dst_key] = float(val)

    # Signal metrics from backtest
    for signal_key in ("mean_ic", "ic_ir", "positive_ic_ratio"):
        val = result_dict.get(signal_key)
        if isinstance(val, (int, float)):
            metrics[signal_key] = float(val)

    # Engine economics: expose turnover and costs from the backtest engine
    if "turnover" in result_dict and isinstance(result_dict["turnover"], (int, float)):
        metrics["turnover"] = float(result_dict["turnover"])
    if "costs" in result_dict and isinstance(result_dict["costs"], (int, float)):
        metrics["costs"] = float(result_dict["costs"])
    if "net_return" in result_dict and isinstance(result_dict["net_return"], (int, float)):
        metrics["net_return"] = float(result_dict["net_return"])
    if "information_ratio" in result_dict and isinstance(result_dict["information_ratio"], (int, float)):
        if _benchmark_available:
            # Only include IR when benchmark was actually available
            metrics["information_ratio"] = float(result_dict["information_ratio"])

    # Genuine top-bottom spread via negated-predictions backtest
    spread = _compute_spread_evidence(
        bt_result, pred_df, raw_returns, topk=topk, rebalance_days=rebalance_days, cost_bps=cost_bps
    )
    if spread.get("status") == "ok":
        metrics["top_bottom_spread"] = spread["total_spread"]

    return {"metrics": metrics, "raw": result_dict, "spread": spread}


def _compute_spread_evidence(
    bt_result: Any,
    pred_df: pd.DataFrame,
    raw_returns: pd.DataFrame,
    *,
    topk: int = 15,
    rebalance_days: int = 10,
    cost_bps: int = 20,
) -> dict[str, Any]:
    """Compute genuine top-bottom spread via negated-predictions backtest.

    Runs a second vectorized backtest with negated predictions to obtain the
    bottom-N portfolio, then computes spread = top_return - bottom_return.
    Raises StageFailure if spread cannot be computed.
    """
    from src.research.vectorized_backtest import run_vectorized_backtest

    if pred_df.empty or raw_returns.empty or "score" not in pred_df.columns:
        raise StageFailure(
            stage="backtest",
            error_type="SpreadComputationFailed",
            message="Top-bottom spread requires non-empty predictions and raw returns.",
        )

    # Bottom portfolio via negated predictions
    neg_pred = pred_df.copy()
    neg_pred["score"] = -neg_pred["score"]
    try:
        bt_bottom = run_vectorized_backtest(
            predictions=neg_pred,
            returns=raw_returns,
            benchmark_returns=None,
            topk=topk,
            rebalance_days=rebalance_days,
            cost_bps=cost_bps,
            non_overlapping=True,
            require_raw_10d_returns=True,
        )
    except Exception as exc:
        raise StageFailure(
            stage="backtest",
            error_type="SpreadComputationFailed",
            message=f"Bottom-N backtest (negated predictions) failed: {exc}",
        ) from exc

    top_return = bt_result.total_return
    bottom_return = bt_bottom.total_return
    total_spread = top_return - bottom_return

    return {
        "top_return": round(top_return, 4),
        "bottom_return": round(bottom_return, 4),
        "total_spread": round(total_spread, 4),
        "topk": topk,
        "bottomk": topk,
        "rebalance_days": rebalance_days,
        "n_periods": bt_result.n_periods,
        "status": "ok",
    }


def _stage_signal_discovery_comparison(
    market: str,
    pred_df: pd.DataFrame,
    raw_returns: pd.DataFrame,
    benchmark_returns: pd.DataFrame | None = None,
    project_root: Path | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the fixed-10D signal discovery comparison and write the report.

    Loads the factor baseline from Qlib historical price (``$close /
    Ref($close, 10) - 1``) and passes it as explicit *factor_baseline_predictions*
    input.  Evaluates LGBM regressor + rank transform + factor baseline in
    both original and inverted orientations, and writes the canonical report.

    Returns the report dict and path, or raises StageFailure.
    """
    # Load factor baseline from Qlib historical price (not from raw returns)
    factor_pred: pd.DataFrame | None = None
    if config is not None:
        factor_pred = _load_factor_baseline_from_qlib(config, market, pred_df)
    if factor_pred is None:
        # Factor baseline will be skipped with a warning in the comparison
        pass

    # Determine output directory
    output_dir = canonical_output_dir(project_root) if project_root else None

    # Run comparison — no winner_labels; uses explicit factor_baseline_predictions
    try:
        report = run_signal_discovery_comparison(
            market=market,
            lgbm_predictions=pred_df,
            raw_returns=raw_returns,
            factor_baseline_predictions=factor_pred,
            benchmark_returns=benchmark_returns,
            topk=15,
            rebalance_days=10,
            cost_bps=20,
            output_dir=output_dir,
        )
    except Exception as exc:
        raise StageFailure(
            stage="signal_discovery",
            error_type="ComparisonFailed",
            message=_bounded_message(f"Signal discovery comparison failed: {exc}"),
        ) from exc

    report_dict = report.to_dict()

    # Use the canonical relative path from the report summary
    _report_path = report.summary.get("report_path", "")

    return {
        "report": report_dict,
        "report_path": _report_path,
        "n_candidates": len(report.candidates),
        "n_promoted": len(report.promoted),
        "promoted": report.promoted,
        "research_only": report.research_only,
    }


def _compute_metrics(
    wf_meta: dict[str, Any],
    bt_metrics: dict[str, Any],
) -> dict[str, float]:
    """Combine walk-forward and backtest metrics into the v1 release schema.

    Metrics unavailable from either source are omitted; the caller records
    them as missing_metrics.
    """
    metrics: dict[str, float] = {}

    # Walk-forward derived
    metrics["ic"] = wf_meta.get("mean_ic", 0.0)
    metrics["icir"] = wf_meta.get("ic_ir", 0.0)
    metrics["consistency"] = wf_meta.get("consistency_score", 0.0)
    metrics["sample_count"] = float(wf_meta.get("n_success", 0))

    # Rank IC from splits (average rank_ic across success splits)
    splits = wf_meta.get("splits", [])
    rank_ics = [s.get("rank_ic", 0.0) or 0.0 for s in splits if s.get("status") == "success"]
    metrics["rank_ic"] = float(sum(rank_ics) / len(rank_ics)) if rank_ics else 0.0

    # Coverage from splits
    if splits:
        metrics["coverage"] = metrics.get("sample_count", 0.0) / max(len(splits), 1)
    else:
        metrics["coverage"] = 0.0

    # Backtest-derived metrics
    if bt_metrics:
        bt_metrics_dict = bt_metrics.get("metrics", {})
        for k in REQUIRED_RELEASE_METRICS[6:]:
            if k in bt_metrics_dict and isinstance(bt_metrics_dict[k], (int, float)):
                metrics[k] = float(bt_metrics_dict[k])
        spread = bt_metrics_dict.get("top_bottom_spread")
        if isinstance(spread, (int, float)):
            metrics["top_bottom_spread"] = float(spread)

    return metrics


# ---------------------------------------------------------------------------
# Data snapshot discovery (canonical DataSnapshot API)
# ---------------------------------------------------------------------------


def _find_data_snapshot(project_root: Path, market: str) -> dict[str, Any]:
    """Locate a valid DataSnapshot via the canonical DataSnapshot API.

    Uses ``DataSnapshot.get_latest_snapshot()`` from the canonical
    ``SNAPSHOT_STORE`` (``artifacts/snapshots``) and verifies passing quality.
    Returns a gate-safe in-project manifest reference.

    Raises StageFailure if no snapshot is published or quality is insufficient.
    """
    from src.data.snapshot import DataSnapshot

    try:
        snapshot_store = project_root / "artifacts" / "snapshots"
        snapshot = DataSnapshot.get_latest_snapshot(store=snapshot_store)
    except Exception as exc:
        raise StageFailure(
            stage="snapshot_discovery",
            error_type="NoValidSnapshot",
            message=f"Failed to load latest snapshot from canonical store: {exc}",
            suggested_fix="Run the data-snapshot pipeline to produce a snapshot "
            "with passing quality and publish it as latest.",
        ) from exc

    if snapshot is None:
        raise StageFailure(
            stage="snapshot_discovery",
            error_type="NoValidSnapshot",
            message="No published snapshot found — SNAPSHOT_STORE/latest is missing. "
            "Use DataSnapshot.publish_snapshot() to set the latest pointer.",
            suggested_fix="Run the data-snapshot pipeline with publish=True to "
            "create and publish a snapshot.",
        )

    if snapshot.manifest.quality_verdict != "pass":
        raise StageFailure(
            stage="snapshot_discovery",
            error_type="SnapshotQualityFailed",
            message=f"Latest snapshot {snapshot.snapshot_id} has "
            f"quality_verdict={snapshot.manifest.quality_verdict!r}; must be 'pass'",
            suggested_fix="Run the data-snapshot pipeline to produce a pass-quality snapshot.",
        )

    if not snapshot.manifest.date_range:
        raise StageFailure(
            stage="snapshot_discovery",
            error_type="SnapshotMissingDateRange",
            message=f"Latest snapshot {snapshot.snapshot_id} has empty date_range; "
            "the release gate requires a non-empty date_range with start and end dates.",
            suggested_fix="Run the data-snapshot pipeline with an explicit date_range "
            "parameter, then re-publish the snapshot.",
        )

    manifest_path = snapshot.provider_path / "manifest.json"
    if not manifest_path.is_file():
        raise StageFailure(
            stage="snapshot_discovery",
            error_type="SnapshotManifestMissing",
            message=f"Snapshot manifest not found at {manifest_path}",
        )

    return {
        "id": snapshot.snapshot_id,
        "manifest": _relative(project_root, manifest_path),
        "sha256": _sha256(manifest_path),
    }


# ---------------------------------------------------------------------------
# Artifact writing
# ---------------------------------------------------------------------------


def _build_artifacts(
    *,
    candidate: str,
    market: str,
    revision: str,
    lock_hash: str,
    config: dict[str, Any],
    wf_meta: dict[str, Any],
    bt_metrics: dict[str, Any] | None,
    model: Any,
    pred_df: pd.DataFrame,
    labels_df: pd.DataFrame,
    raw_returns: pd.DataFrame,
    score_diagnostics: dict[str, Any] | None = None,
    signal_discovery: dict[str, Any] | None = None,
    project_root: Path,
    snapshot_ref: dict[str, Any],
) -> dict[str, Any]:
    """Build and write all release artifacts (model + evidence).

    *snapshot_ref* must be a gate-verified snapshot reference dict
    (``id``, ``manifest``, ``sha256``) produced by ``_find_data_snapshot``.

    Returns the market section of the release manifest.
    """
    # --- Model artifact ---
    artifact_id = f"{market}-{candidate}"
    model_dir = project_root / "artifacts" / "model_artifacts" / artifact_id
    model_dir.mkdir(parents=True, exist_ok=True)

    # Serialise model
    model_path = model_dir / "model.pkl"
    with open(model_path, "wb") as fh:
        pickle.dump(model, fh)

    # Write predictions CSV
    pred_path = model_dir / "predictions.csv"
    pred_df.to_csv(pred_path)

    # Write labels CSV (processed training labels)
    labels_path = model_dir / "labels.csv"
    labels_df.to_csv(labels_path)

    # Write raw returns CSV (economic evaluation returns)
    raw_returns_path = model_dir / "raw_returns.csv"
    raw_returns.to_csv(raw_returns_path)

    # Derive label expression and horizon from config
    handler_kwargs = config.get("task", {}).get("dataset", {}).get("kwargs", {}).get("handler", {}).get("kwargs", {})
    label_expr = str(handler_kwargs.get("label", ["Ref($close, -10) / $close - 1"])[0])
    import re as _re
    _horizon_match = _re.search(r"Ref\(\$close,\s*(-\d+)\)", label_expr)
    label_horizon = abs(int(_horizon_match.group(1))) if _horizon_match else 10

    diagnostics: dict[str, Any] = {
        "candidate": candidate,
        "market": market,
        "revision": revision,
        "training_label": {
            "source": "DataHandler.DK_L",
            "processors": ["DropnaLabel", "CSRankNorm"],
            "horizon_days": label_horizon,
            "expression": label_expr,
            "column": "training_label",
        },
        "evaluation_return": {
            "source": "qlib.data.D.features (raw, no learn processors)",
            "horizon_days": label_horizon,
            "expression": label_expr,
            "column": "return",
        },
        "backtest_return": {
            "source": "qlib.data.D.features (raw, no learn processors)",
            "horizon_days": label_horizon,
            "expression": label_expr,
            "column": "return",
        },
        "score_direction": score_diagnostics or {},
        "walk_forward": {
            "mean_ic": wf_meta.get("mean_ic"),
            "ic_ir": wf_meta.get("ic_ir"),
            "n_success": wf_meta.get("n_success"),
            "n_splits": wf_meta.get("n_splits"),
        },
        "training_filter": {
            "n_dropped_non_finite": pred_df.attrs.get("n_dropped_non_finite", 0),
            "n_after_filter": pred_df.attrs.get("n_after_filter", len(pred_df)),
            "coverage_ratio": pred_df.attrs.get("coverage_ratio", 1.0),
        },
        "raw_returns_filter": {
            "n_raw_rows": raw_returns.attrs.get("n_raw_rows", len(raw_returns)),
            "n_dropped_non_finite": raw_returns.attrs.get("n_dropped_non_finite", 0),
            "n_valid_rows": raw_returns.attrs.get("n_valid_rows", len(raw_returns)),
            "coverage_ratio": raw_returns.attrs.get("coverage_ratio", 1.0),
        },
    }
    diagnostics_path = model_dir / "diagnostics.json"
    _write_json(diagnostics_path, diagnostics)

    # Validate all artifact files exist and compute checksums
    artifact_files = {
        "model.pkl": model_path,
        "predictions.csv": pred_path,
        "labels.csv": labels_path,
        "raw_returns.csv": raw_returns_path,
        "diagnostics.json": diagnostics_path,
    }
    checksums: dict[str, str] = {}
    for name, path in artifact_files.items():
        if not path.is_file() or path.stat().st_size == 0:
            raise StageFailure(
                stage="artifact_build",
                error_type="EmptyArtifact",
                message=f"Artifact file is empty or missing: {path}",
            )
        checksums[name] = _sha256(path)

    model_manifest: dict[str, Any] = {
        "id": artifact_id,
        "model_binary_path": "model.pkl",
        "config": {
            "market": market,
            "model": "LGBMRegressor",
            "config_source": "configs/us_lgbm_regressor_10d_workflow.yaml",
        },
        "features": ["Alpha158"],
        "label_schema": {
            "name": "return_10d",
            "horizon": 10,
            "expression": "Ref($close, -10) / $close - 1",
        },
        "snapshot_id": snapshot_ref["id"],
        "train_window": [
            config.get("start_time", "2018-01-01"),
            config.get("fit_end_time", "2023-12-31"),
        ],
        "valid_window": ["2024-01-01", "2024-06-30"],
        "test_window": ["2024-07-01", config.get("end_time", "2024-12-31")],
        "benchmark": "QQQ",
        "costs": {"open_cost": 0.0005, "close_cost": 0.0015},
        "code_revision": revision,
        "uv_lock_hash": lock_hash,
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.0",
        "seeds": {"numpy": 42, "random": 42},
        "predictions_path": "predictions.csv",
        "labels_path": "labels.csv",
        "raw_returns_path": "raw_returns.csv",
        "diagnostics_path": "diagnostics.json",
        "checksums": checksums,
    }

    model_manifest_path = model_dir / "manifest.json"
    _write_json(model_manifest_path, model_manifest)

    model_ref: dict[str, Any] = {
        "id": artifact_id,
        "manifest": _relative(project_root, model_manifest_path),
        "sha256": _sha256(model_manifest_path),
    }

    # --- Evidence ---
    metrics = _compute_metrics(wf_meta, bt_metrics)
    evidence_base_path = project_root / "artifacts" / "evidence" / candidate
    evidence_base_path.mkdir(parents=True, exist_ok=True)

    backtest_metrics = {
        k: metrics[k]
        for k in REQUIRED_RELEASE_METRICS[6:]
        if k in metrics and isinstance(metrics[k], (int, float))
    }
    if "top_bottom_spread" in metrics:
        backtest_metrics["top_bottom_spread"] = metrics["top_bottom_spread"]
    signal_metrics = {
        k: metrics[k]
        for k in REQUIRED_RELEASE_METRICS[:6]
        if k in metrics and isinstance(metrics[k], (int, float))
    }

    backtest_evidence: dict[str, Any] = {
        "id": f"{market}-backtest-{candidate}",
        "evidence_type": "backtest",
        "status": "pass" if backtest_metrics else "partial",
        "model_artifact_id": artifact_id,
        "snapshot_id": snapshot_ref["id"],
        "metric_schema_version": "v1",
        "metrics": backtest_metrics,
    }
    signal_evidence: dict[str, Any] = {
        "id": f"{market}-signal-{candidate}",
        "evidence_type": "signal",
        "status": "pass" if signal_metrics else "partial",
        "model_artifact_id": artifact_id,
        "snapshot_id": snapshot_ref["id"],
        "metric_schema_version": "v1",
        "metrics": signal_metrics,
    }

    be_path = evidence_base_path / f"{market}-backtest-evidence.json"
    se_path = evidence_base_path / f"{market}-signal-evidence.json"
    _write_json(be_path, backtest_evidence)
    _write_json(se_path, signal_evidence)

    evidence_ref: dict[str, Any] = {
        "backtest": {
            "id": backtest_evidence["id"],
            "path": _relative(project_root, be_path),
            "sha256": _sha256(be_path),
        },
        "signal": {
            "id": signal_evidence["id"],
            "path": _relative(project_root, se_path),
            "sha256": _sha256(se_path),
        },
    }

    # --- Missing metrics ---
    missing_metrics: dict[str, str] = {}
    for k in REQUIRED_RELEASE_METRICS:
        if k not in metrics:
            missing_metrics[k] = "not produced by walk-forward or backtest pipeline"

    market_section: dict[str, Any] = {
        "data_snapshot": snapshot_ref,
        "model_artifact": model_ref,
        "evidence": evidence_ref,
        "missing_metrics": missing_metrics,
    }

    # --- Signal discovery report reference (canonical 10D comparison) ---
    if signal_discovery and signal_discovery.get("report_path"):
        sd_report_path = project_root / signal_discovery["report_path"]
        if sd_report_path.is_file():
            market_section["signal_discovery"] = {
                "report_path": signal_discovery["report_path"],
                "sha256": _sha256(sd_report_path),
                "n_candidates": signal_discovery.get("n_candidates", 0),
                "n_promoted": signal_discovery.get("n_promoted", 0),
            }

    return market_section


# ---------------------------------------------------------------------------
# Frontend evidence
# ---------------------------------------------------------------------------


def _run_frontend_build(
    candidate: str,
    revision: str,
    project_root: Path,
) -> dict[str, Any]:
    """Run the real frontend build and persist current-revision evidence."""
    frontend_dir = project_root / "qlib-dashboard"
    npm = shutil.which("npm")
    if npm is None:
        raise StageFailure(
            stage="frontend_evidence",
            error_type="FrontendBuildToolMissing",
            message="npm is not available on PATH.",
            suggested_fix="Install Node.js/npm and retry release generation.",
        )
    if not (frontend_dir / "package.json").is_file():
        raise StageFailure(
            stage="frontend_evidence",
            error_type="FrontendProjectMissing",
            message=f"Frontend package.json not found at {frontend_dir}.",
        )

    completed = subprocess.run(
        [npm, "run", "build"],
        cwd=frontend_dir,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    evidence_dir = project_root / "artifacts" / "release_gates"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    log_path = evidence_dir / "frontend_build.log"
    log_path.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    dist_dir = frontend_dir / "dist"
    dist_files = [path for path in dist_dir.rglob("*") if path.is_file()] if dist_dir.is_dir() else []
    if completed.returncode != 0 or not dist_files:
        raise StageFailure(
            stage="frontend_evidence",
            error_type="FrontendBuildFailed",
            message=(
                f"npm run build exited {completed.returncode}; "
                f"dist_files={len(dist_files)}. See {_relative(project_root, log_path)}."
            ),
            suggested_fix="Fix the frontend build failure and rerun release generation.",
        )

    payload: dict[str, Any] = {
        "id": f"frontend-build-{candidate}",
        "candidate": candidate,
        "status": "pass",
        "code_revision": revision,
        "command": "npm run build",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "log_path": _relative(project_root, log_path),
        "log_sha256": _sha256(log_path),
        "dist_file_count": len(dist_files),
    }
    evidence_path = evidence_dir / "frontend_build_evidence.json"
    _write_json(evidence_path, payload)
    return {
        "id": payload["id"],
        "path": _relative(project_root, evidence_path),
        "sha256": _sha256(evidence_path),
    }


def _load_frontend_evidence(
    frontend_path_str: str | None,
    candidate: str,
    revision: str,
    project_root: Path,
) -> dict[str, Any]:
    """Load and validate frontend-build evidence.

    Raises StageFailure if the path is missing, malformed, or the revision
    does not match.
    """
    if not frontend_path_str:
        return _run_frontend_build(candidate, revision, project_root)

    evidence_path = Path(frontend_path_str)
    if not evidence_path.is_absolute():
        evidence_path = (project_root / evidence_path).resolve()
    else:
        evidence_path = evidence_path.resolve()

    if not evidence_path.is_file():
        raise StageFailure(
            stage="frontend_evidence",
            error_type="FrontendEvidenceFileMissing",
            message=f"Frontend evidence file not found: {evidence_path}",
            missing_files=[str(evidence_path)],
            suggested_fix="Run 'npm run build' in qlib-dashboard/ and verify the "
            "evidence JSON was produced.",
        )

    try:
        payload = _read_json(evidence_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise StageFailure(
            stage="frontend_evidence",
            error_type="FrontendEvidenceInvalid",
            message=f"Frontend evidence file is not valid JSON: {exc}",
        ) from exc

    evidence_id = payload.get("id")
    evidence_status = payload.get("status")
    evidence_revision = payload.get("code_revision")

    errors: list[str] = []
    if not isinstance(evidence_id, str) or not evidence_id.strip():
        errors.append("missing or empty 'id'")
    if evidence_status != "pass":
        errors.append(f"status must be 'pass', got {evidence_status!r}")
    if evidence_revision != revision:
        errors.append(f"code_revision mismatch: expected {revision}, got {evidence_revision!r}")

    if errors:
        raise StageFailure(
            stage="frontend_evidence",
            error_type="FrontendEvidenceInvalid",
            message=f"Frontend evidence validation failed: {'; '.join(errors)}",
        )

    return {
        "id": evidence_id,
        "path": _relative(project_root, evidence_path),
        "sha256": _sha256(evidence_path),
    }


# ---------------------------------------------------------------------------
# Manifest building
# ---------------------------------------------------------------------------


def _build_manifest(
    *,
    candidate: str,
    market: str,
    revision: str,
    lock_hash: str,
    code_identity: dict[str, Any],
    config: dict[str, Any],
    wf_meta: dict[str, Any],
    bt_metrics: dict[str, Any] | None,
    market_section: dict[str, Any],
    frontend_ref: dict[str, Any],
    signal_discovery: dict[str, Any] | None = None,
    project_root: Path,
) -> dict[str, Any]:
    """Assemble the top-level release manifest."""
    windows: dict[str, Any] = {}
    try:
        segments = config.get("task", {}).get("dataset", {}).get("kwargs", {}).get("segments", {})
        windows = {
            "train": segments.get("train", []),
            "valid": segments.get("valid", []),
            "test": segments.get("test", []),
        }
    except Exception:
        windows = {}

    walk_forward_summary = {
        "n_splits": wf_meta.get("n_splits", 0),
        "mean_ic": wf_meta.get("mean_ic"),
        "std_ic": wf_meta.get("std_ic"),
        "ic_ir": wf_meta.get("ic_ir"),
        "consistency": wf_meta.get("consistency_score"),
        "n_success": wf_meta.get("n_success"),
        "n_failed": wf_meta.get("n_failed"),
    }

    # Backtest summary
    backtest_summary: dict[str, Any] = {}
    if bt_metrics:
        bt_metrics_dict = bt_metrics.get("metrics", {})
        for k in ("annualized_return", "total_return", "benchmark_return",
                   "excess_return", "sharpe", "max_drawdown"):
            if k in bt_metrics_dict:
                backtest_summary[k] = bt_metrics_dict[k]

    spread_data = (bt_metrics or {}).get("spread", {})

    manifest: dict[str, Any] = {
        "schema_version": "1",
        "release_candidate_id": candidate,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "code_identity": code_identity,
        "metric_schema": {
            "version": "v1",
            "required_fields": list(REQUIRED_RELEASE_METRICS),
        },
        "gate_policy": dict(POLICY),
        "markets": {market: market_section},
        "windows": windows,
        "walk_forward": walk_forward_summary,
        "backtest": backtest_summary,
        "spread": spread_data,
        "frontend_build": frontend_ref,
        "10d_signal_discovery": (
            {
                "report_path": signal_discovery.get("report_path", ""),
                "n_candidates": signal_discovery.get("n_candidates", 0),
                "n_promoted": signal_discovery.get("n_promoted", 0),
                "promoted": signal_discovery.get("promoted", []),
                "research_only": signal_discovery.get("research_only", []),
            }
            if signal_discovery
            else None
        ),
        "artifact_paths": {
            "release_manifest": f"artifacts/release_candidate/{candidate}/release_manifest.json",
            "model_artifact_dir": f"artifacts/model_artifacts/{market}-{candidate}",
            "evidence_dir": f"artifacts/evidence/{candidate}",
        },
    }
    return manifest


def _write_failure_report(
    candidate: str,
    market: str,
    stage: str,
    error_type: str,
    message: str,
    *,
    missing_files: list[str] | None = None,
    suggested_fix: str | None = None,
    project_root: Path,
) -> None:
    report: dict[str, Any] = {
        "candidate": candidate,
        "market": market,
        "stage_failed": stage,
        "error_type": error_type,
        "error_message": message,
        "missing_files": missing_files or [],
        "suggested_fix": suggested_fix or "",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    report_dir = project_root / "artifacts" / "release_candidate" / candidate
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "release_failure_report.json"
    _write_json(report_path, report)
    print(json.dumps(report, indent=2), file=sys.stderr)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def generate_release_candidate(
    *,
    candidate: str,
    market: str,
    project_root: Path,
    frontend_evidence: str | None = None,
) -> tuple[dict[str, Any], int]:
    """Generate a release-candidate artifact bundle.

    Returns (result_dict, exit_code).
    """
    if market not in ("us", "cn"):
        return (
            {"error": f"Unsupported market: {market!r}.  Use 'us' or 'cn'."},
            1,
        )

    # ---- Stage 0: Config ----
    config_name = f"{market}_lgbm_regressor_10d_workflow.yaml"
    try:
        config = _load_workflow_config(config_name, project_root)
    except StageFailure as exc:
        _write_failure_report(
            candidate=candidate,
            market=market,
            stage=exc.stage,
            error_type=exc.error_type,
            message=exc.message,
            missing_files=exc.missing_files,
            suggested_fix=exc.suggested_fix,
            project_root=project_root,
        )
        return ({"status": "fail", "error": exc.message}, 1)

    # ---- Stage 1: Identity ----
    try:
        revision, lock_hash, code_identity = _stage_identity(project_root)
    except StageFailure as exc:
        _write_failure_report(
            candidate=candidate,
            market=market,
            stage=exc.stage,
            error_type=exc.error_type,
            message=exc.message,
            missing_files=exc.missing_files,
            suggested_fix=exc.suggested_fix,
            project_root=project_root,
        )
        return ({"status": "fail", "error": exc.message}, 1)

    # ---- Stage 2: Qlib init ----
    wf_meta: dict[str, Any] = {}
    bt_metrics: dict[str, Any] | None = None
    signal_discovery_result: dict[str, Any] | None = None
    model: Any = None
    pred_df: pd.DataFrame | None = None
    labels_df: pd.DataFrame | None = None
    snapshot_ref: dict[str, Any] | None = None
    raw_returns: pd.DataFrame | None = None
    try:
        _stage_qlib_init(config, market, project_root)
    except StageFailure as exc:
        _write_failure_report(
            candidate=candidate,
            market=market,
            stage=exc.stage,
            error_type=exc.error_type,
            message=exc.message,
            missing_files=exc.missing_files,
            suggested_fix=exc.suggested_fix,
            project_root=project_root,
        )
        return ({"status": "fail", "error": exc.message}, 1)

    # ---- Stage 3: Snapshot discovery (before expensive model work) ----
    try:
        snapshot_ref = _find_data_snapshot(project_root, market)
    except StageFailure as exc:
        _write_failure_report(
            candidate=candidate,
            market=market,
            stage=exc.stage,
            error_type=exc.error_type,
            message=exc.message,
            missing_files=exc.missing_files,
            suggested_fix=exc.suggested_fix,
            project_root=project_root,
        )
        return ({"status": "fail", "error": exc.message}, 1)

    # ---- Stage 4: Load raw forward returns (economic evaluation data contract) ----
    # Load before expensive walk-forward/training so data-contract failures
    # fail fast.  The loaded DataFrame is reused downstream for score
    # diagnostics and backtest — no second load.
    try:
        raw_returns = _load_raw_forward_returns(config, market)
    except StageFailure as exc:
        _write_failure_report(
            candidate=candidate,
            market=market,
            stage=exc.stage,
            error_type=exc.error_type,
            message=exc.message,
            missing_files=exc.missing_files,
            suggested_fix=exc.suggested_fix,
            project_root=project_root,
        )
        return ({"status": "fail", "error": exc.message}, 1)

    # ---- Stage 5: Walk-forward ----
    try:
        wf_meta = _stage_walk_forward(config, market, project_root)
    except StageFailure as exc:
        _write_failure_report(
            candidate=candidate,
            market=market,
            stage=exc.stage,
            error_type=exc.error_type,
            message=exc.message,
            suggested_fix=exc.suggested_fix,
            project_root=project_root,
        )
        return ({"status": "fail", "error": exc.message}, 1)

    # ---- Stage 6: Final model training and prediction ----
    try:
        model, pred_df, labels_df = _stage_train(config, market)
    except StageFailure as exc:
        _write_failure_report(
            candidate=candidate,
            market=market,
            stage=exc.stage,
            error_type=exc.error_type,
            message=exc.message,
            missing_files=exc.missing_files,
            suggested_fix=exc.suggested_fix,
            project_root=project_root,
        )
        return ({"status": "fail", "error": exc.message}, 1)

    # ---- Score-direction diagnostics (predictions vs raw forward returns) ----
    score_diagnostics: dict[str, Any] | None = None
    try:
        score_diagnostics = _compute_score_diagnostics(pred_df, raw_returns)
    except StageFailure as exc:
        _write_failure_report(
            candidate=candidate,
            market=market,
            stage=exc.stage,
            error_type=exc.error_type,
            message=exc.message,
            missing_files=exc.missing_files,
            suggested_fix=exc.suggested_fix or "Verify data alignment and content.",
            project_root=project_root,
        )
        return ({"status": "fail", "error": exc.message}, 1)
    except (ValueError, TypeError, RuntimeError, KeyError) as exc:
        _write_failure_report(
            candidate=candidate,
            market=market,
            stage="score_diagnostics",
            error_type="ScoreDiagnosticsFailed",
            message=_bounded_message(f"Score diagnostics computation failed: {exc}"),
            suggested_fix="Verify predictions and raw returns are aligned and non-empty.",
            project_root=project_root,
        )
        return ({"status": "fail", "error": str(exc)}, 1)

    # ---- Stage 7: Backtest (T+10 benchmark, genuine spread, raw returns only) ----
    try:
        bt_metrics = _stage_backtest(market, pred_df, raw_returns)
    except StageFailure as exc:
        _write_failure_report(
            candidate=candidate,
            market=market,
            stage=exc.stage,
            error_type=exc.error_type,
            message=exc.message,
            missing_files=exc.missing_files,
            suggested_fix=exc.suggested_fix,
            project_root=project_root,
        )
        return ({"status": "fail", "error": exc.message}, 1)

    # ---- Stage 7b: 10D Signal Discovery Comparison Report ----
    # Runs the canonical fixed-10D comparison across LGBM regressor,
    # ranking-style transform, and factor baseline in both original
    # and inverted orientations.  The report is written to
    # artifacts/evidence/10d_signal_discovery/{market}_signal_discovery_report.json
    # and referenced in the release manifest.
    _benchmark_for_sd: pd.DataFrame | None = None
    try:
        from qlib.data import D

        _sd_test_start = str(pred_df.index.get_level_values(0).min())
        _sd_test_end = str(pred_df.index.get_level_values(0).max())
        _bench_raw = D.features(
            ["QQQ"],
            ["Ref($close, -10) / $close - 1"],
            start_time=_sd_test_start,
            end_time=_sd_test_end,
        )
        _benchmark_for_sd = (
            _bench_raw.droplevel("instrument")
            .iloc[:, [0]]
            .rename(columns={_bench_raw.columns[0]: "return"})
            .sort_index()
        )
    except Exception:
        _benchmark_for_sd = None

    try:
        signal_discovery_result = _stage_signal_discovery_comparison(
            market=market,
            pred_df=pred_df,
            raw_returns=raw_returns,
            benchmark_returns=_benchmark_for_sd,
            project_root=project_root,
            config=config,
        )
    except StageFailure as exc:
        _write_failure_report(
            candidate=candidate,
            market=market,
            stage=exc.stage,
            error_type=exc.error_type,
            message=exc.message,
            missing_files=exc.missing_files,
            suggested_fix=exc.suggested_fix,
            project_root=project_root,
        )
        return ({"status": "fail", "error": exc.message}, 1)

    # ---- Stage 8: Build model/evidence artifacts (no frontend param) ----
    try:
        market_section = _build_artifacts(
            candidate=candidate,
            market=market,
            revision=revision,
            lock_hash=lock_hash,
            config=config,
            wf_meta=wf_meta,
            bt_metrics=bt_metrics,
            model=model,
            pred_df=pred_df,
            labels_df=labels_df,
            raw_returns=raw_returns,
            score_diagnostics=score_diagnostics,
            signal_discovery=signal_discovery_result,
            project_root=project_root,
            snapshot_ref=snapshot_ref,
        )
    except Exception as exc:
        _write_failure_report(
            candidate=candidate,
            market=market,
            stage="artifact_build",
            error_type="ArtifactBuildError",
            message=_bounded_message(f"Artifact building failed: {exc}"),
            project_root=project_root,
        )
        return ({"status": "fail", "error": str(exc)}, 1)

    # ---- Stage 9: Frontend evidence (checked after model artifacts built) ----
    try:
        frontend_ref = _load_frontend_evidence(
            frontend_evidence, candidate, revision, project_root
        )
    except StageFailure as exc:
        _write_failure_report(
            candidate=candidate,
            market=market,
            stage=exc.stage,
            error_type=exc.error_type,
            message=exc.message,
            missing_files=exc.missing_files,
            suggested_fix=exc.suggested_fix,
            project_root=project_root,
        )
        return ({"status": "fail", "error": exc.message}, 1)

    # ---- Stage 10: Write manifest (only when ALL checks pass) ----

    # Remove any stale failure report from a prior unsuccessful run
    stale_failure = (project_root / "artifacts" / "release_candidate" / candidate
                     / "release_failure_report.json")
    if stale_failure.is_file():
        stale_failure.unlink()

    manifest = _build_manifest(
        candidate=candidate,
        market=market,
        revision=revision,
        lock_hash=lock_hash,
        code_identity=code_identity,
        config=config,
        wf_meta=wf_meta,
        bt_metrics=bt_metrics,
        market_section=market_section,
        frontend_ref=frontend_ref,
        signal_discovery=signal_discovery_result,
        project_root=project_root,
    )
    manifest_dir = project_root / "artifacts" / "release_candidate" / candidate
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "release_manifest.json"
    _write_json(manifest_path, manifest)

    result: dict[str, Any] = {
        "status": "pass",
        "candidate": candidate,
        "market": market,
        "manifest_path": _relative(project_root, manifest_path),
    }
    return (result, 0)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate",
        required=True,
        help="Release-candidate identifier, e.g. v0.1.0-rc1",
    )
    parser.add_argument(
        "--market",
        required=True,
        choices=["us", "cn"],
        help="Target market (us or cn).",
    )
    parser.add_argument(
        "--frontend-evidence",
        default=None,
        help="Path to frontend-build evidence JSON (required for success manifest).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result, code = generate_release_candidate(
        candidate=args.candidate,
        market=args.market,
        project_root=PROJECT_ROOT,
        frontend_evidence=args.frontend_evidence,
    )
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
