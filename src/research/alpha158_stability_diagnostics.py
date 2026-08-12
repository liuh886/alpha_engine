"""Run spec-bound factor diagnostics from one governed Alpha158 materialization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.research.paradigm import ResearchParadigmSpec, load_research_paradigm_spec
from src.research.qlib_execution_common import normalize_qlib_frame_index
from src.research.spec_bound_factor_diagnostics import (
    QlibFactorDiagnosticsRuntime,
    _factor_diagnostic,
    _selected_factor_specs,
    _window_date_map,
)

DIAGNOSTIC_ID = "cn_alpha158_cross_window_stability_v1"
PROFILE_ID = "cn_selected_alpha158_v1"
EXPECTED_POOL_ID = "cn_selected_equities_v3"
MINIMUM_FACTOR_COVERAGE_RATIO = 0.95
EXPECTED_WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON must be an object: {path}")
    return payload


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _load_symbols(spec: ResearchParadigmSpec, repository_root: Path) -> list[str]:
    path = repository_root / str(spec.universe["source"])
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("symbols"), list):
        raise ValueError("Alpha158 diagnostic universe must expose symbols list")
    symbols = [str(value).strip().upper() for value in payload["symbols"]]
    if len(symbols) != 130 or len(set(symbols)) != 130:
        raise ValueError("Alpha158 diagnostic universe must be exact CN130")
    return symbols


def _validate_bundle(
    bundle_root: Path,
    spec: ResearchParadigmSpec,
    selected: list[tuple[tuple[str, ...], Any]],
) -> dict[str, Any]:
    profiles = json.loads(
        (bundle_root / "model_data" / "training-profiles.json").read_text(encoding="utf-8")
    )
    if not isinstance(profiles, list):
        raise ValueError("training-profiles.json must be a list")
    profile = next((row for row in profiles if row.get("profile_id") == PROFILE_ID), None)
    if not isinstance(profile, dict) or profile.get("status") != "ready":
        raise ValueError("cn_selected_alpha158_v1 is not ready")

    manifest = _read_json(bundle_root / "alpha158" / "factor_panel_manifest.json")
    if manifest.get("market") != "cn" or manifest.get("pool_id") != EXPECTED_POOL_ID:
        raise ValueError("Alpha158 panel market/pool identity drifted")
    if int(manifest.get("expected_symbol_count", 0)) != 130:
        raise ValueError("Alpha158 panel expected symbol count drifted")
    if manifest.get("missing_symbols") or manifest.get("invalid_symbols") or manifest.get(
        "quarantined_symbols"
    ):
        raise ValueError("Alpha158 diagnostics require no missing/invalid/quarantined symbols")

    catalog = _read_json(bundle_root / "alpha158" / "factor_catalog.json")
    rows = catalog.get("factors")
    if not isinstance(rows, list) or len(rows) != 158:
        raise ValueError("Alpha158 catalog must contain exactly 158 factors")
    observed = {
        str(row["factor_id"]): str(row["implementation_hash"])
        for row in rows
        if isinstance(row, dict)
    }
    expected = {definition.factor_id: definition.implementation_hash for _, definition in selected}
    if observed != expected:
        raise ValueError("materialized Alpha158 catalog differs from canonical factor library")

    return {
        "training_profile": profile,
        "factor_panel_manifest": manifest,
        "factor_catalog": catalog,
    }


def _load_materialized_features(
    bundle_root: Path,
    symbols: list[str],
    factor_ids: list[str],
    *,
    start: str,
    end: str,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for symbol in symbols:
        path = bundle_root / "alpha158" / "panels" / f"{symbol}.csv.gz"
        if not path.is_file():
            raise ValueError(f"Alpha158 panel file is missing: {symbol}")
        frame = pd.read_csv(path, compression="gzip", usecols=["date", *factor_ids])
        frame["datetime"] = pd.to_datetime(frame.pop("date"), errors="raise")
        frame = frame.loc[
            (frame["datetime"] >= pd.Timestamp(start))
            & (frame["datetime"] <= pd.Timestamp(end))
        ].copy()
        frame["instrument"] = symbol
        frames.append(frame.set_index(["datetime", "instrument"]))
    return pd.concat(frames, axis=0).sort_index().replace([np.inf, -np.inf], np.nan)


def _classification(row: dict[str, Any]) -> dict[str, Any]:
    multiplier = -1.0 if row["recommended_orientation"] == "invert_score" else 1.0
    by_window = {
        str(item["window"]): (
            None
            if item.get("mean_rank_ic") is None
            else float(item["mean_rank_ic"]) * multiplier
        )
        for item in row["window_metrics"]
    }
    values = [by_window.get(window) for window in EXPECTED_WINDOWS]
    all_defined = all(value is not None for value in values)
    coverage_ok = float(row.get("coverage_ratio") or 0.0) >= MINIMUM_FACTOR_COVERAGE_RATIO
    stable = bool(all_defined and coverage_ok and all(float(value) > 0.0 for value in values))
    repair_2024 = bool(
        all_defined
        and coverage_ok
        and all(float(by_window[window]) > 0.0 for window in ("2024H1", "2024H2"))
        and all(float(by_window[window]) >= 0.0 for window in ("2025H1", "2025H2"))
    )
    mean_2024 = (
        None
        if not all_defined
        else float(np.mean([by_window["2024H1"], by_window["2024H2"]]))
    )
    mean_2025 = (
        None
        if not all_defined
        else float(np.mean([by_window["2025H1"], by_window["2025H2"]]))
    )
    regime_sensitive = bool(
        all_defined
        and mean_2024 not in (None, 0.0)
        and mean_2025 not in (None, 0.0)
        and np.sign(mean_2024) != np.sign(mean_2025)
    )
    return {
        "coverage_ok": coverage_ok,
        "all_four_windows_defined": all_defined,
        "cross_window_stable": stable,
        "repair_2024_candidate": repair_2024,
        "regime_sensitive": regime_sensitive,
        "oriented_mean_rank_ic_2024": mean_2024,
        "oriented_mean_rank_ic_2025": mean_2025,
        "oriented_window_rank_ic": by_window,
    }


def run_alpha158_stability_diagnostics(
    spec_path: str | Path,
    bundle_root: str | Path,
    *,
    repository_root: str | Path = ".",
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repository_root).resolve()
    bundle = Path(bundle_root).resolve()
    spec = load_research_paradigm_spec(spec_path)
    if spec.experiment_id != DIAGNOSTIC_ID or spec.market != "cn":
        raise ValueError("spec is not the governed CN Alpha158 stability diagnostic")
    if tuple(spec.factor_library["groups"]) != ("qlib_alpha158_all",):
        raise ValueError("diagnostic must use the full canonical Alpha158 group")
    if str(spec.walk_forward["test_end"]) != "2025-12-31":
        raise ValueError("diagnostic must not consume 2026 evidence")

    selected = _selected_factor_specs(spec)
    if len(selected) != 158:
        raise ValueError("diagnostic must resolve exactly 158 canonical factors")
    evidence = _validate_bundle(bundle, spec, selected)
    symbols = _load_symbols(spec, root)
    factor_ids = [definition.factor_id for _, definition in selected]
    start = str(spec.walk_forward["requested_train_start"])
    end = str(spec.walk_forward["test_end"])
    features = _load_materialized_features(bundle, symbols, factor_ids, start=start, end=end)

    runtime = QlibFactorDiagnosticsRuntime(market="cn", provider_uri=bundle / "provider")
    runtime.initialize(root)
    raw_returns = normalize_qlib_frame_index(
        runtime.features(symbols, [str(spec.strategy["return_expression"])], start, end)
    ).replace([np.inf, -np.inf], np.nan)
    raw_returns.columns = ["return"]
    available_dates = pd.DatetimeIndex(
        sorted(set(raw_returns.index.get_level_values("datetime")))
    )
    date_map, windows, window_policy = _window_date_map(available_dates, spec)
    included_labels = tuple(
        row["label"] for row in windows if row.get("status") == "included"
    )
    if included_labels != EXPECTED_WINDOWS:
        raise ValueError(f"diagnostic windows drifted: {included_labels}")

    returns = raw_returns["return"]
    diagnostics = [
        _factor_diagnostic(
            groups,
            definition,
            features[definition.factor_id],
            returns,
            date_map=date_map,
            requested_symbol_count=len(symbols),
            top_n=int(spec.strategy["top_n"]),
            bottom_n=int(spec.strategy["bottom_n"]),
        )
        for groups, definition in selected
    ]
    for row in diagnostics:
        row["stability"] = _classification(row)
    diagnostics.sort(
        key=lambda row: (
            bool(row["stability"]["cross_window_stable"]),
            float(row["stability"]["oriented_mean_rank_ic_2024"] or -999.0),
            float(row["oriented_rank_icir"] or -999.0),
        ),
        reverse=True,
    )
    for rank, row in enumerate(diagnostics, start=1):
        row["stability_rank"] = rank

    stable = [row["factor_id"] for row in diagnostics if row["stability"]["cross_window_stable"]]
    repair = [row["factor_id"] for row in diagnostics if row["stability"]["repair_2024_candidate"]]
    regime = [row["factor_id"] for row in diagnostics if row["stability"]["regime_sensitive"]]
    unusable = [
        row["factor_id"]
        for row in diagnostics
        if not row["stability"]["coverage_ok"] or not row["stability"]["all_four_windows_defined"]
    ]

    report = {
        "schema_version": "1.0",
        "experiment_id": DIAGNOSTIC_ID,
        "status": "completed",
        "diagnostic_only": True,
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
        "new_holdout_consumed": False,
        "market": "cn",
        "pool_id": EXPECTED_POOL_ID,
        "factor_count": 158,
        "minimum_factor_coverage_ratio": MINIMUM_FACTOR_COVERAGE_RATIO,
        "selection_windows": list(EXPECTED_WINDOWS),
        "sampled_rebalance_dates": len(date_map),
        "window_policy": window_policy,
        "windows": windows,
        "provider": runtime.metadata(),
        "factor_panel_lineage": {
            "catalog_sha256": evidence["factor_panel_manifest"].get("catalog_sha256"),
            "provider_manifest_sha256": evidence["factor_panel_manifest"].get(
                "provider_manifest_sha256"
            ),
            "source_role_manifest_sha256": evidence["factor_panel_manifest"].get(
                "source_role_manifest_sha256"
            ),
            "ready_symbol_count": evidence["factor_panel_manifest"].get(
                "ready_symbol_count"
            ),
            "expected_symbol_count": evidence["factor_panel_manifest"].get(
                "expected_symbol_count"
            ),
            "not_yet_applicable_symbols": evidence["factor_panel_manifest"].get(
                "not_yet_applicable_symbols", []
            ),
        },
        "classification_counts": {
            "cross_window_stable": len(stable),
            "repair_2024_candidates": len(repair),
            "regime_sensitive": len(regime),
            "not_usable": len(unusable),
        },
        "cross_window_stable_factor_ids": stable,
        "repair_2024_factor_ids": repair,
        "regime_sensitive_factor_ids": regime,
        "not_usable_factor_ids": unusable,
        "factors": diagnostics,
        "next_step": (
            "Review mechanisms only. Any model candidate requires a separate preregistered "
            "incremental experiment; no factor is promoted by this diagnostic."
        ),
    }
    output = (
        Path(output_path).resolve()
        if output_path is not None
        else bundle / "alpha158" / "research" / f"{DIAGNOSTIC_ID}.json"
    )
    _write_json(output, report)
    return report
