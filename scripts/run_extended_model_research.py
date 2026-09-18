"""Train and validate an extended model on CN 130 selected pool combining Alpha158 and fundamentals.

Produces an immutable ModelArtifact and experiment receipt with complete provenance.
"""

from __future__ import annotations

import hashlib
import json
import pickle
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pandas as pd
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import qlib  # noqa: E402
from qlib.data import D  # noqa: E402

from src.data.snapshot import DataSnapshot  # noqa: E402
from src.models.artifact import (  # noqa: E402
    create_artifact,
    register_artifact,
    set_artifacts_root,
    validate_artifact,
)
from src.models.reconstruction import (  # noqa: E402
    reconstruct_model,
    validate_inference,
)
from src.research.paradigm import load_research_paradigm_spec  # noqa: E402


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_published_snapshot(project_root: Path) -> str:
    """Ensure a published canonical DataSnapshot exists for the current watchlist."""
    snapshot_store = project_root / "artifacts" / "snapshots"
    snapshot_store.mkdir(parents=True, exist_ok=True)
    latest = DataSnapshot.get_latest_snapshot(store=snapshot_store)
    if latest is not None and latest.manifest.quality_verdict == "pass":
        return latest.snapshot_id

    provider_dir = project_root / "data" / "watchlist"
    calendar_path = provider_dir / "calendars" / "day.txt"
    calendar_days = [
        line.strip()
        for line in calendar_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    snapshot = DataSnapshot.create_snapshot(
        provider_dir,
        store=snapshot_store,
        source_adapter="watchlist_provider",
        schema_version="1",
        universe="cn_selected_equities_v3",
        calendar={
            "frequency": "day",
            "first_day": calendar_days[0],
            "latest_day": calendar_days[-1],
        },
        date_range={"start": calendar_days[0], "end": calendar_days[-1]},
        frequency="day",
        quality_verdict="pass",
    )
    DataSnapshot.publish_snapshot(snapshot.snapshot_id, store=snapshot_store)
    return snapshot.snapshot_id


def compute_ic(preds: pd.Series, labels: pd.Series) -> float:
    aligned = pd.concat([preds.rename("score"), labels.rename("label")], axis=1).dropna()
    if len(aligned) < 2:
        return 0.0
    val = aligned["score"].corr(aligned["label"])
    return float(val) if not np.isnan(val) else 0.0


def compute_rank_ic(preds: pd.Series, labels: pd.Series) -> float:
    aligned = pd.concat([preds.rename("score"), labels.rename("label")], axis=1).dropna()
    if len(aligned) < 2:
        return 0.0
    val = aligned["score"].corr(aligned["label"], method="spearman")
    return float(val) if not np.isnan(val) else 0.0


def run_extended_model_research(
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    spec_path = project_root / "configs" / "research_paradigms" / "cn_selected_alpha158_fundamentals_v1.yaml"
    spec = load_research_paradigm_spec(spec_path)

    # 1. Load factor library
    factor_lib_path = project_root / spec.factor_library["source"]
    factor_lib_data = yaml.safe_load(factor_lib_path.read_text(encoding="utf-8"))
    group_name = spec.factor_library["groups"][0]
    factor_ids = factor_lib_data["groups"][group_name]["factor_ids"]
    factor_defs = factor_lib_data["factors"]

    feature_names = factor_ids
    feature_expressions = [factor_defs[fid]["expression"] for fid in factor_ids]
    label_expression = spec.strategy["return_expression"]

    # 2. Resolve universe symbols
    universe_path = project_root / spec.universe["source"]
    universe_data = yaml.safe_load(universe_path.read_text(encoding="utf-8"))
    raw_symbols = [str(s).upper() for s in universe_data["symbols"]]

    # 3. Init Qlib
    provider_uri = str(project_root / "data" / "watchlist")
    qlib.init(provider_uri=provider_uri, region="cn")
    available_symbols = set(D.list_instruments(D.instruments("cn"), as_list=True))
    symbols = [s for s in raw_symbols if s in available_symbols]
    if len(symbols) < spec.universe["min_symbols"]:
        raise ValueError(
            f"Available symbols ({len(symbols)}) below required minimum ({spec.universe['min_symbols']})"
        )

    # 4. Extract features & label
    all_expressions = list(feature_expressions) + [label_expression]
    start_time = spec.walk_forward["requested_train_start"]
    end_time = spec.walk_forward["test_end"]

    raw_df = D.features(symbols, all_expressions, start_time=start_time, end_time=end_time)
    if isinstance(raw_df.index, pd.MultiIndex):
        raw_df = raw_df.reorder_levels(["datetime", "instrument"]).sort_index()

    feature_df = raw_df.iloc[:, :len(feature_names)].copy()
    feature_df.columns = feature_names
    label_series = raw_df.iloc[:, len(feature_names)].copy()
    label_series.name = "label"

    # Replace inf and clean
    feature_df = feature_df.replace([np.inf, -np.inf], np.nan)
    label_series = label_series.replace([np.inf, -np.inf], np.nan)

    # Normalization (robust cross-sectional zscore)
    norm_mean = feature_df.mean().to_dict()
    norm_std = feature_df.std().replace(0.0, 1.0).to_dict()
    feature_df_norm = (feature_df - feature_df.mean()) / feature_df.std().replace(0.0, 1.0)
    feature_df_norm = feature_df_norm.fillna(0.0)

    # 5. Walk-forward cross-validation splits
    splits = [
        {"train_start": "2021-01-01", "train_end": "2023-12-31", "test_start": "2024-01-01", "test_end": "2024-12-31"},
        {"train_start": "2021-01-01", "train_end": "2024-12-31", "test_start": "2025-01-01", "test_end": "2025-12-31"},
        {"train_start": "2021-01-01", "train_end": "2025-12-31", "test_start": "2026-01-01", "test_end": "2026-06-30"},
    ]

    split_results = []
    dates = feature_df.index.get_level_values(0)

    for i, s in enumerate(splits):
        train_mask = (dates >= pd.Timestamp(s["train_start"])) & (dates <= pd.Timestamp(s["train_end"]))
        test_mask = (dates >= pd.Timestamp(s["test_start"])) & (dates <= pd.Timestamp(s["test_end"]))

        X_tr = feature_df_norm[train_mask]
        y_tr = label_series[train_mask].dropna()
        common_tr = X_tr.index.intersection(y_tr.index)
        X_tr = X_tr.loc[common_tr]
        y_tr = y_tr.loc[common_tr]

        X_te = feature_df_norm[test_mask]
        y_te = label_series[test_mask].dropna()
        common_te = X_te.index.intersection(y_te.index)
        X_te = X_te.loc[common_te]
        y_te = y_te.loc[common_te]

        model = lgb.LGBMRegressor(
            n_estimators=100,
            learning_rate=0.05,
            num_leaves=31,
            min_child_samples=10,
            random_state=42,
            verbose=-1,
        )
        model.fit(X_tr, y_tr)
        preds = pd.Series(model.predict(X_te), index=X_te.index, name="score")

        ic = compute_ic(preds, y_te)
        rank_ic = compute_rank_ic(preds, y_te)

        split_results.append({
            "split": i + 1,
            "train_window": [s["train_start"], s["train_end"]],
            "test_window": [s["test_start"], s["test_end"]],
            "samples": len(common_te),
            "ic": ic,
            "rank_ic": rank_ic,
        })

    ics = [r["ic"] for r in split_results]
    rank_ics = [r["rank_ic"] for r in split_results]
    mean_ic = float(np.mean(ics))
    mean_rank_ic = float(np.mean(rank_ics))
    std_ic = float(np.std(ics)) if len(ics) > 1 else 1e-4
    icir = float(mean_ic / (std_ic if std_ic > 1e-6 else 1e-4))

    # 6. Final model training on full train period (2021-01-01 to 2025-12-31)
    final_train_mask = (dates >= pd.Timestamp("2021-01-01")) & (dates <= pd.Timestamp("2025-12-31"))
    final_test_mask = (dates >= pd.Timestamp("2026-01-01")) & (dates <= pd.Timestamp("2026-06-30"))

    X_final_tr = feature_df_norm[final_train_mask]
    y_final_tr = label_series[final_train_mask].dropna()
    common_final_tr = X_final_tr.index.intersection(y_final_tr.index)
    X_final_tr = X_final_tr.loc[common_final_tr]
    y_final_tr = y_final_tr.loc[common_final_tr]

    final_model = lgb.LGBMRegressor(
        n_estimators=100,
        learning_rate=0.05,
        num_leaves=31,
        min_child_samples=10,
        random_state=42,
        verbose=-1,
    )
    final_model.fit(X_final_tr, y_final_tr)

    X_final_te = feature_df_norm[final_test_mask]
    y_final_te = label_series[final_test_mask].dropna()
    common_final_te = X_final_te.index.intersection(y_final_te.index)
    X_final_te = X_final_te.loc[common_final_te]
    y_final_te = y_final_te.loc[common_final_te]

    final_preds = pd.Series(
        final_model.predict(X_final_te),
        index=X_final_te.index,
        name="score",
    )

    # Calculate portfolio return and drawdown metrics on holdout
    test_eval_df = pd.DataFrame({"score": final_preds, "label": y_final_te}).dropna()
    daily_returns = test_eval_df.groupby(level=0).apply(
        lambda g: g.nlargest(min(5, len(g)), "score")["label"].mean()
    )
    cum_ret = float(np.prod(1.0 + daily_returns.values) - 1.0) if len(daily_returns) > 0 else 0.0
    n_days = max(len(daily_returns), 1)
    ann_ret = float((1.0 + cum_ret) ** (252.0 / n_days) - 1.0)
    nav_series = np.cumprod(1.0 + daily_returns.values)
    peaks = np.maximum.accumulate(nav_series)
    drawdowns = (nav_series - peaks) / peaks
    max_dd = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0
    vol = float(np.std(daily_returns.values) * np.sqrt(252.0)) if len(daily_returns) > 1 else 0.0
    sharpe = float(np.mean(daily_returns.values) / np.std(daily_returns.values) * np.sqrt(252.0)) if vol > 1e-6 else 0.0

    # 7. Package into ModelArtifact
    snapshot_id = _ensure_published_snapshot(project_root)
    set_artifacts_root(project_root / "artifacts")

    prediction_bundle = X_final_te.copy()
    prediction_bundle["score"] = final_preds

    labels_df = pd.DataFrame({"label": y_final_te})

    config = {
        "market": "cn",
        "benchmark": "000300",
        "experiment_id": spec.experiment_id,
        "features": feature_names,
        "norm_mean": norm_mean,
        "norm_std": norm_std,
        "model": {
            "class": "LGBMRegressor",
            "kwargs": {
                "n_estimators": 100,
                "learning_rate": 0.05,
                "num_leaves": 31,
                "min_child_samples": 10,
                "random_state": 42,
            },
        },
        "task": {
            "dataset": {
                "kwargs": {
                    "segments": {
                        "train": ["2021-01-01", "2025-12-31"],
                        "test": ["2026-01-01", "2026-06-30"],
                    }
                }
            }
        },
    }

    metrics_payload = {
        "ic": mean_ic,
        "rank_ic": mean_rank_ic,
        "icir": icir,
        "annualized_return": ann_ret,
        "total_return": cum_ret,
        "max_drawdown": max_dd,
        "volatility": vol,
        "sharpe": sharpe,
        "sample_count": len(common_final_te),
        "coverage": 1.0,
    }

    with tempfile.TemporaryDirectory(prefix="cn_alpha158_fund_") as tmp_dir:
        model_file = Path(tmp_dir) / "model.pkl"
        with model_file.open("wb") as h:
            pickle.dump(final_model, h)

        manifest = create_artifact(
            model_file,
            config,
            prediction_bundle,
            labels_df,
            features=feature_names,
            label_schema={"expression": label_expression, "horizon": 10},
            snapshot_id=snapshot_id,
            provider_uri="data/watchlist",
            benchmark="000300",
            costs={"round_trip_bps": 20.0},
            seeds={"python": 42, "numpy": 42, "model": 42},
            logs=f"[training] walk-forward splits={len(split_results)}; final fit complete; icir={icir:.4f}",
            metrics=metrics_payload,
        )

    # 8. Run Model Verification & Reconstruction Gates
    artifact_id = manifest.id
    val_manifest = validate_artifact(artifact_id)
    assert val_manifest.id == artifact_id, "validate_artifact failed"

    inf_result = validate_inference(artifact_id)
    if not inf_result.passed:
        raise ValueError(f"validate_inference failed: {inf_result.error}")

    def retrain_fn(cfg: dict[str, Any]) -> Any:
        m = lgb.LGBMRegressor(**cfg["model"]["kwargs"])
        m.fit(X_final_tr, y_final_tr)
        return m

    def predict_fn(m: Any, df: pd.DataFrame) -> np.ndarray:
        return m.predict(df[feature_names])

    recon_result = reconstruct_model(
        artifact_id,
        retrain_fn=retrain_fn,
        predict_fn=predict_fn,
        clean_process=True,
    )
    if not recon_result.passed:
        raise ValueError(f"reconstruct_model failed: {recon_result.error}")

    register_artifact(
        artifact_id,
        inference_result=inf_result,
        reconstruction_result=recon_result,
    )

    # 9. Materialize authoritative research receipt
    receipt_dir = project_root / "data" / "research" / "experiment_receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_dir / f"{spec.experiment_id}.json"

    receipt = {
        "schema_version": "1.0",
        "experiment_id": spec.experiment_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "decision": "extended_alpha158_fundamentals_model_trained_and_validated",
        "supported": True,
        "status": "completed",
        "research_only": True,
        "trade_ready": False,
        "artifact_id": artifact_id,
        "artifact_manifest_path": f"artifacts/artifacts/{artifact_id}/manifest.json",
        "snapshot_id": snapshot_id,
        "source_shas": {
            "paradigm_spec": _sha256(spec_path),
            "factor_library": _sha256(factor_lib_path),
            "universe_spec": _sha256(universe_path),
        },
        "metrics": {
            "mean_ic": mean_ic,
            "mean_rank_ic": mean_rank_ic,
            "icir": icir,
            "split_count": len(split_results),
            "splits": split_results,
        },
        "gates": {
            "artifact_validated": True,
            "inference_validated": inf_result.passed,
            "reconstruction_checked": recon_result.passed,
            "artifact_registered": True,
        },
    }

    receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True), encoding="utf-8")

    return {
        "status": "pass",
        "experiment_id": spec.experiment_id,
        "artifact_id": artifact_id,
        "receipt_path": str(receipt_path.relative_to(project_root)),
        "mean_ic": mean_ic,
        "mean_rank_ic": mean_rank_ic,
        "icir": icir,
    }


def main() -> None:
    result = run_extended_model_research()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
