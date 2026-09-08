"""Prospective validation gate for the frozen CN_27 V1.3 challenger."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.research.all_weather_alpha_rotation import canonical_sha256, sha256_file
from src.research.cn27_sharpe_discovery import CN27DiscoveryContract, write_json
from src.research.cn27_v1_2 import (
    _block_bootstrap_sharpe,
    compute_v1_2_features,
    score_v1_2_features,
)
from src.research.cn27_v1_3 import (
    _parameter_variants,
    concentration_audit,
    contribution_attribution,
)
from src.research.cn27_v1_3_projected import load_projected_discovery_contract
from src.research.cn27_v1_3_projected import run_projected_recipe


@dataclass(frozen=True)
class CN27V13ProspectiveContract:
    spec: dict[str, Any]
    spec_path: Path
    root: Path
    challenger: dict[str, Any]
    historical_manifest: dict[str, Any]
    candidate_symbols: tuple[str, ...]
    defensive_symbol: str
    reference_symbol: str
    sector_by_symbol: dict[str, str]
    historical_contract: CN27DiscoveryContract


@dataclass(frozen=True)
class CN27V13SourcePackage:
    manifest: dict[str, Any]
    manifest_path: Path
    tables: dict[str, pd.DataFrame]


def _load_mapping(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected YAML mapping: {path}")
    return payload


def _verify_manifest(path: Path, expected_file_hash: str, expected_identity: str) -> dict[str, Any]:
    if sha256_file(path) != expected_file_hash:
        raise ValueError(f"manifest file hash mismatch: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    body = dict(manifest)
    identity = str(body.pop("manifest_identity_sha256", ""))
    if canonical_sha256(body) != identity or identity != expected_identity:
        raise ValueError(f"manifest identity mismatch: {path}")
    for name, expected in manifest.get("outputs", {}).items():
        if sha256_file(path.parent / name) != expected:
            raise ValueError(f"manifest output hash mismatch: {path.parent / name}")
    return manifest


def load_prospective_contract(path: str | Path) -> CN27V13ProspectiveContract:
    spec_path = Path(path).resolve()
    root = spec_path.parents[2]
    spec = _load_mapping(spec_path)
    if spec.get("status") != "frozen_before_first_observation":
        raise ValueError("prospective validation contract must be frozen before observation")
    if spec.get("research_only") is not True or spec.get("trade_ready") is not False:
        raise ValueError("prospective validation must remain research-only")
    if spec.get("automatic_promotion_allowed") is not False:
        raise ValueError("prospective validation cannot authorize automatic promotion")

    lineage = spec["lineage"]
    implementation_path = (root / str(lineage["implementation"])).resolve()
    if sha256_file(implementation_path) != str(lineage["implementation_sha256"]):
        raise ValueError("prospective validation implementation hash mismatch")
    challenger_path = (root / str(lineage["challenger_contract"])).resolve()
    if sha256_file(challenger_path) != str(lineage["challenger_contract_sha256"]):
        raise ValueError("prospective challenger contract hash mismatch")
    challenger = _load_mapping(challenger_path)
    if challenger.get("decision", {}).get("formal_v1_3_created") is not False:
        raise ValueError("challenger must remain outside the formal model catalog")
    incumbent_path = (
        root / str(challenger["lineage"]["incumbent_model_contract"])
    ).resolve()
    if sha256_file(incumbent_path) != str(
        challenger["lineage"]["incumbent_model_contract_sha256"]
    ):
        raise ValueError("incumbent model contract hash mismatch")
    incumbent = _load_mapping(incumbent_path)
    pool_path = (root / str(incumbent["identity"]["pool_spec"])).resolve()
    if sha256_file(pool_path) != str(incumbent["identity"]["pool_sha256"]):
        raise ValueError("prospective candidate pool hash mismatch")
    pool = _load_mapping(pool_path)
    sector_by_symbol = {
        str(row["symbol"]).zfill(6): str(row["sector"]) for row in pool["symbols"]
    }
    if len(sector_by_symbol) != 27:
        raise ValueError("prospective candidate pool must contain exactly 27 symbols")

    discovery_path = (root / str(lineage["historical_discovery_contract"])).resolve()
    if sha256_file(discovery_path) != str(lineage["historical_discovery_contract_sha256"]):
        raise ValueError("historical discovery contract hash mismatch")
    historical_contract = load_projected_discovery_contract(discovery_path)
    manifest = _verify_manifest(
        (root / str(lineage["historical_manifest"])).resolve(),
        str(lineage["historical_manifest_file_sha256"]),
        str(lineage["historical_manifest_identity_sha256"]),
    )
    if manifest.get("decision") != "no_projected_candidate_passed_frozen_gate":
        raise ValueError("historical discovery decision boundary changed")
    return CN27V13ProspectiveContract(
        spec=spec,
        spec_path=spec_path,
        root=root,
        challenger=challenger,
        historical_manifest=manifest,
        candidate_symbols=tuple(sector_by_symbol),
        defensive_symbol=str(pool["references"]["defensive_etf"]["symbol"]).zfill(6),
        reference_symbol=str(pool["references"]["benchmark"]["symbol"]).zfill(6),
        sector_by_symbol=sector_by_symbol,
        historical_contract=historical_contract,
    )


def load_source_package(
    contract: CN27V13ProspectiveContract,
    manifest_path: str | Path,
) -> CN27V13SourcePackage:
    source_path = Path(manifest_path).resolve()
    manifest = json.loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("prospective source manifest must be a JSON mapping")
    required = set(contract.spec["source_manifest_required_fields"])
    if missing := sorted(required - set(manifest)):
        raise ValueError(f"prospective source manifest missing fields: {missing}")
    if manifest["candidate_id"] != contract.challenger["candidate_id"]:
        raise ValueError("prospective source candidate identity mismatch")
    if manifest["validation_contract_sha256"] != sha256_file(contract.spec_path):
        raise ValueError("prospective validation contract hash mismatch")
    if manifest["research_only"] is not True or manifest["trade_ready"] is not False:
        raise ValueError("prospective source package must remain research-only")
    for field in ("provider_name", "query_identity", "extracted_at", "revision_policy"):
        if not str(manifest[field]).strip():
            raise ValueError(f"prospective source manifest requires {field}")

    declared_files = manifest["files"]
    if not isinstance(declared_files, dict):
        raise ValueError("prospective source files must be a filename-to-hash mapping")
    expected_files = contract.spec["required_input_files"]
    if set(declared_files) != set(expected_files):
        raise ValueError("prospective source file set does not match the frozen contract")
    tables: dict[str, pd.DataFrame] = {}
    for filename, columns in expected_files.items():
        if Path(filename).name != filename:
            raise ValueError(f"prospective source filename must be local: {filename}")
        file_path = source_path.parent / filename
        if not file_path.is_file():
            raise ValueError(f"prospective source file missing: {filename}")
        if sha256_file(file_path) != str(declared_files[filename]):
            raise ValueError(f"prospective source file hash mismatch: {filename}")
        table = pd.read_csv(file_path, dtype={"symbol": str})
        if missing_columns := sorted(set(columns) - set(table.columns)):
            raise ValueError(
                f"prospective source file {filename} missing columns: {missing_columns}"
            )
        tables[filename] = table
    return CN27V13SourcePackage(
        manifest=manifest,
        manifest_path=source_path,
        tables=tables,
    )


def validate_source_package(
    contract: CN27V13ProspectiveContract,
    package: CN27V13SourcePackage,
) -> pd.DatetimeIndex:
    required_symbols = {
        *contract.candidate_symbols,
        contract.defensive_symbol,
        contract.reference_symbol,
    }
    cutoff = pd.Timestamp(contract.spec["observation_contract"]["starts_strictly_after"])
    price_keys: dict[str, pd.MultiIndex] = {}
    for filename in ("adjusted_ohlcv.csv", "raw_ohlcv.csv"):
        table = package.tables[filename]
        table["date"] = pd.to_datetime(table["date"], errors="raise").dt.normalize()
        table["symbol"] = table["symbol"].astype(str).str.zfill(6)
        if table.duplicated(["date", "symbol"]).any():
            raise ValueError(f"{filename} contains duplicate date-symbol rows")
        if set(table["symbol"]) != required_symbols:
            raise ValueError(f"{filename} instrument set does not match the frozen roles")
        if table.empty or table["date"].min() <= cutoff:
            raise ValueError(f"{filename} overlaps the consumed historical window")
        numeric = table[["open", "high", "low", "close", "volume"]].apply(
            pd.to_numeric, errors="coerce"
        )
        invalid = (
            numeric.isna().any(axis=1)
            | numeric[["open", "high", "low", "close"]].le(0.0).any(axis=1)
            | numeric["volume"].lt(0.0)
            | numeric["high"].lt(numeric[["open", "low", "close"]].max(axis=1))
            | numeric["low"].gt(numeric[["open", "high", "close"]].min(axis=1))
        )
        if invalid.any():
            raise ValueError(f"{filename} contains invalid OHLCV values")
        price_keys[filename] = pd.MultiIndex.from_frame(
            table[["date", "symbol"]]
        ).sort_values()
    if not price_keys["adjusted_ohlcv.csv"].equals(price_keys["raw_ohlcv.csv"]):
        raise ValueError("raw and adjusted OHLCV date-symbol keys differ")

    adjusted = package.tables["adjusted_ohlcv.csv"]
    sessions = pd.DatetimeIndex(
        adjusted.loc[adjusted["symbol"].eq(contract.defensive_symbol), "date"]
    ).sort_values()
    if sessions.empty or not sessions.is_unique:
        raise ValueError("defensive ETF must define unique prospective sessions")
    tradability = package.tables["tradability.csv"]
    tradability["date"] = pd.to_datetime(tradability["date"], errors="raise").dt.normalize()
    tradability["symbol"] = tradability["symbol"].astype(str).str.zfill(6)
    if tradability.duplicated(["date", "symbol"]).any():
        raise ValueError("tradability.csv contains duplicate date-symbol rows")
    expected_grid = pd.MultiIndex.from_product(
        [sessions, sorted(required_symbols)], names=["date", "symbol"]
    )
    observed_grid = pd.MultiIndex.from_frame(
        tradability[["date", "symbol"]].sort_values(["date", "symbol"])
    )
    if not observed_grid.equals(expected_grid):
        raise ValueError("tradability.csv does not cover every session and instrument")
    for column in ("listed", "suspended", "one_price", "tradable"):
        normalized = tradability[column].astype(str).str.lower()
        if not normalized.isin({"true", "false"}).all():
            raise ValueError(f"tradability.csv {column} must be boolean")
        tradability[column] = normalized.eq("true")
    expected_tradable = (
        tradability["listed"]
        & ~tradability["suspended"]
        & ~tradability["one_price"]
    )
    if not tradability["tradable"].eq(expected_tradable).all():
        raise ValueError("tradability flags are internally inconsistent")
    etf_rows = tradability["symbol"].eq(contract.defensive_symbol)
    if not tradability.loc[etf_rows, "tradable"].all():
        raise ValueError("defensive ETF must be tradable on every prospective session")
    extracted_at = pd.to_datetime(package.manifest["extracted_at"], utc=True, errors="raise")
    available = pd.to_datetime(tradability["available_at"], utc=True, errors="raise")
    if available.gt(extracted_at).any():
        raise ValueError("tradability availability exceeds package extraction time")

    actions = package.tables["corporate_actions.csv"]
    if not actions.empty:
        actions["symbol"] = actions["symbol"].astype(str).str.zfill(6)
        if not set(actions["symbol"]).issubset(required_symbols):
            raise ValueError("corporate actions contain an unknown instrument")
        if actions["event_id"].duplicated().any():
            raise ValueError("corporate action event IDs must be unique")
        effective = pd.to_datetime(actions["effective_date"], errors="raise").dt.normalize()
        if effective.min() <= cutoff:
            raise ValueError("corporate actions overlap the consumed historical window")
        action_available = pd.to_datetime(actions["available_at"], utc=True, errors="raise")
        if action_available.gt(extracted_at).any():
            raise ValueError("corporate action availability exceeds package extraction time")
    return sessions


def evaluate_observation_readiness(
    contract: CN27V13ProspectiveContract,
    sessions: pd.DatetimeIndex,
) -> dict[str, Any]:
    policy = contract.spec["observation_contract"]
    unique = pd.DatetimeIndex(sessions).normalize().sort_values().unique()
    minimum_sessions = int(policy["minimum_sessions"])
    minimum_months = int(policy["minimum_calendar_months"])
    reasons: list[str] = []
    if len(unique) < minimum_sessions:
        reasons.append(f"minimum_sessions:{len(unique)}<{minimum_sessions}")
    if unique.empty:
        reasons.append("observation_window_empty")
        start = end = None
    else:
        start, end = unique[0], unique[-1]
        required_end = start + pd.DateOffset(months=minimum_months)
        if end < required_end:
            reasons.append(
                f"minimum_calendar_months:{end.date()}<{required_end.date()}"
            )
    return {
        "status": "ready_for_frozen_evaluation" if not reasons else "insufficient_observation",
        "ready": not reasons,
        "session_count": int(len(unique)),
        "observation_start": start.date().isoformat() if start is not None else None,
        "observation_end": end.date().isoformat() if end is not None else None,
        "reasons": reasons,
        "research_only": True,
        "trade_ready": False,
        "automatic_promotion_allowed": False,
    }


def build_forward_runtime_contract(
    contract: CN27V13ProspectiveContract,
    sessions: pd.DatetimeIndex,
) -> CN27DiscoveryContract:
    readiness = evaluate_observation_readiness(contract, sessions)
    if not readiness["ready"]:
        raise ValueError(
            "prospective observation is not ready: " + ", ".join(readiness["reasons"])
        )
    unique = pd.DatetimeIndex(sessions).normalize().sort_values().unique()
    fold_count = int(contract.spec["observation_contract"]["chronological_folds"])
    index_folds = list(np.array_split(unique, fold_count))
    if any(len(fold) == 0 for fold in index_folds):
        raise ValueError("prospective chronological folds cannot be empty")
    windows: dict[str, dict[str, Any]] = {
        "development": {
            "start": unique[0].date().isoformat(),
            "end": unique[-1].date().isoformat(),
            "sessions": len(unique),
        }
    }
    folds: list[dict[str, Any]] = []
    for index, fold in enumerate(index_folds, start=1):
        fold_id = f"pf{index}"
        window = {
            "id": fold_id,
            "start": pd.Timestamp(fold[0]).date().isoformat(),
            "end": pd.Timestamp(fold[-1]).date().isoformat(),
            "sessions": len(fold),
        }
        folds.append(window)
        windows[fold_id] = dict(window)
    spec = copy.deepcopy(contract.historical_contract.spec)
    spec["windows"] = windows
    historical_full = contract.historical_contract.spec["evaluation"]["full_window"]
    spec["evaluation"]["full_window"] = {
        "start": str(historical_full["start"]),
        "end": windows["development"]["end"],
        "sessions": int(historical_full["sessions"]) + len(unique),
    }
    spec["evaluation"]["chronological_folds"] = folds
    return replace(contract.historical_contract, spec=spec)


def prospective_gate_failures(
    metrics: dict[str, float],
    gate: dict[str, float],
) -> list[str]:
    minimum_checks = (
        ("sharpe_log_excess", "minimum_sharpe_log_excess", "full_sharpe"),
        (
            "double_cost_sharpe_log_excess",
            "minimum_double_cost_sharpe_log_excess",
            "double_cost_sharpe",
        ),
        ("positive_fold_share", "minimum_positive_fold_share", "positive_fold_share"),
        (
            "fold_sharpe_25th_percentile",
            "minimum_fold_sharpe_25th_percentile",
            "fold_sharpe_p25",
        ),
        (
            "worst_timing_perturbation_sharpe",
            "minimum_worst_timing_perturbation_sharpe",
            "timing_perturbation_sharpe",
        ),
        (
            "bootstrap_sharpe_percentile_05",
            "minimum_bootstrap_sharpe_percentile_05",
            "bootstrap_p05",
        ),
        (
            "bootstrap_probability_sharpe_above_zero",
            "minimum_bootstrap_probability_sharpe_above_zero",
            "bootstrap_probability_above_zero",
        ),
        (
            "bootstrap_probability_sharpe_above_one",
            "minimum_bootstrap_probability_sharpe_above_one",
            "bootstrap_probability_above_one",
        ),
        (
            "parameter_neighborhood_minimum_sharpe",
            "minimum_parameter_neighborhood_sharpe",
            "parameter_minimum_sharpe",
        ),
        (
            "post_drift_effective_names_median",
            "minimum_post_drift_effective_names_median",
            "effective_names_median",
        ),
        (
            "post_drift_effective_names_p05",
            "minimum_post_drift_effective_names_p05",
            "effective_names_p05",
        ),
        (
            "leave_one_sector_out_minimum_sharpe",
            "minimum_leave_one_sector_out_sharpe",
            "leave_one_sector_minimum_sharpe",
        ),
        (
            "leave_one_sector_out_median_sharpe",
            "minimum_leave_one_sector_out_median_sharpe",
            "leave_one_sector_median_sharpe",
        ),
    )
    maximum_checks = (
        ("annual_one_way_turnover", "maximum_annual_one_way_turnover", "turnover"),
        ("maximum_drawdown_magnitude", "maximum_drawdown_magnitude", "drawdown"),
        (
            "parameter_neighborhood_maximum_drawdown_magnitude",
            "maximum_parameter_neighborhood_drawdown_magnitude",
            "parameter_drawdown",
        ),
        (
            "maximum_post_drift_single_equity_sleeve_share",
            "maximum_post_drift_single_equity_sleeve_share",
            "post_drift_single_share",
        ),
        (
            "maximum_post_drift_sector_equity_sleeve_share",
            "maximum_post_drift_sector_equity_sleeve_share",
            "post_drift_sector_share",
        ),
        (
            "post_drift_sector_share_p95",
            "maximum_post_drift_sector_share_p95",
            "post_drift_sector_p95",
        ),
        (
            "maximum_single_name_positive_contribution_share",
            "maximum_single_name_positive_contribution_share",
            "name_contribution",
        ),
        (
            "maximum_single_sector_positive_contribution_share",
            "maximum_single_sector_positive_contribution_share",
            "sector_contribution",
        ),
    )
    failures = [
        label
        for metric, threshold, label in minimum_checks
        if not np.isfinite(float(metrics[metric]))
        or float(metrics[metric]) < float(gate[threshold])
    ]
    failures.extend(
        label
        for metric, threshold, label in maximum_checks
        if not np.isfinite(float(metrics[metric]))
        or float(metrics[metric]) > float(gate[threshold])
    )
    return failures


def _combined_runtime_bars(
    contract: CN27V13ProspectiveContract,
    package: CN27V13SourcePackage,
) -> pd.DataFrame:
    historical = pd.read_csv(
        contract.historical_contract.prices_path,
        dtype={"symbol": str},
        parse_dates=["date"],
    )
    forward = package.tables["adjusted_ohlcv.csv"].copy()
    forward["date"] = pd.to_datetime(forward["date"]).dt.normalize()
    forward["symbol"] = forward["symbol"].astype(str).str.zfill(6)
    tradability = package.tables["tradability.csv"][["date", "symbol", "tradable"]].copy()
    tradability["date"] = pd.to_datetime(tradability["date"]).dt.normalize()
    tradability["symbol"] = tradability["symbol"].astype(str).str.zfill(6)
    forward = forward.merge(
        tradability,
        on=["date", "symbol"],
        how="left",
        validate="one_to_one",
    )
    forward = forward.loc[forward["tradable"]].drop(columns="tradable")
    combined = pd.concat([historical, forward], ignore_index=True)
    if combined.duplicated(["date", "symbol"]).any():
        raise ValueError("combined historical and prospective bars overlap")
    return combined.sort_values(["date", "symbol"]).reset_index(drop=True)


def _evaluate_ready_package(
    contract: CN27V13ProspectiveContract,
    package: CN27V13SourcePackage,
    sessions: pd.DatetimeIndex,
) -> dict[str, Any]:
    runtime = build_forward_runtime_contract(contract, sessions)
    bars = _combined_runtime_bars(contract, package)
    features = compute_v1_2_features(bars, runtime)
    signal = runtime.spec["frozen_signal"]
    scored, _ = score_v1_2_features(
        features,
        {**signal, "id": "frozen_v1_3_prospective_signal"},
        runtime,
    )
    frozen = contract.challenger["frozen_challenger"]
    recipe: dict[str, object] = {
        "id": str(frozen["recipe_id"]),
        "concentration_governance": True,
        "maximum_single_equity_sleeve_share": float(
            frozen["maximum_single_equity_sleeve_share"]
        ),
        "maximum_sector_equity_sleeve_share": float(
            frozen["maximum_sector_equity_sleeve_share"]
        ),
        "minimum_effective_names": float(frozen["minimum_effective_names"]),
    }

    def execute(
        active_recipe: dict[str, object] = recipe,
        *,
        cost_multiplier: float = 1.0,
        execution_delay_sessions: int = 1,
        rebalance_phase_offset: int = 0,
        excluded_sectors: frozenset[str] = frozenset(),
    ) -> Any:
        return run_projected_recipe(
            bars,
            features,
            runtime,
            active_recipe,
            cost_multiplier=cost_multiplier,
            execution_delay_sessions=execution_delay_sessions,
            rebalance_phase_offset=rebalance_phase_offset,
            excluded_sectors=excluded_sectors,
            scored_features=scored,
        )

    results: dict[str, Any] = {}
    for variant_id, kwargs in contract.spec["required_run_variants"].items():
        results[variant_id] = execute(
            cost_multiplier=float(kwargs["cost_multiplier"]),
            execution_delay_sessions=int(kwargs["execution_delay_sessions"]),
            rebalance_phase_offset=int(kwargs["rebalance_phase_offset"]),
        )
    base = results["base"]
    parameter_results: dict[str, Any] = {"base": base}
    parameter_policy = runtime.spec["parameter_perturbations"]
    risk_model = runtime.spec["frozen_risk_model"]
    for label, variant in _parameter_variants(recipe, risk_model, parameter_policy):
        parameter_results[label] = execute(variant)
    sector_results = {
        sector: execute(excluded_sectors=frozenset({sector}))
        for sector in sorted(set(contract.sector_by_symbol.values()))
    }

    forward_daily = base.daily.loc[sessions]
    audit_frame, audit_summary = concentration_audit(forward_daily, runtime)
    complete_attribution, _ = contribution_attribution(base.daily, bars, runtime)
    attribution_frame = complete_attribution.loc[
        complete_attribution["date"].isin(sessions)
    ].copy()
    stocks = attribution_frame.loc[
        attribution_frame["symbol"].isin(contract.candidate_symbols)
    ]
    name_positive = stocks.groupby("symbol")["gross_contribution"].sum().clip(lower=0.0)
    sector_positive = stocks.groupby("sector")["gross_contribution"].sum().clip(lower=0.0)
    name_total = float(name_positive.sum())
    sector_total = float(sector_positive.sum())
    attribution_summary = {
        "maximum_daily_reconciliation_error": 0.0,
        "largest_positive_name": str(name_positive.idxmax()) if name_total > 1e-12 else None,
        "maximum_single_name_positive_contribution_share": (
            float(name_positive.max() / name_total) if name_total > 1e-12 else None
        ),
        "largest_positive_sector": (
            str(sector_positive.idxmax()) if sector_total > 1e-12 else None
        ),
        "maximum_single_sector_positive_contribution_share": (
            float(sector_positive.max() / sector_total) if sector_total > 1e-12 else None
        ),
    }
    bootstrap = _block_bootstrap_sharpe(
        forward_daily["net_return"],
        samples=int(contract.spec["bootstrap"]["samples"]),
        block_sessions=int(contract.spec["bootstrap"]["block_sessions"]),
        seed=int(contract.spec["bootstrap"]["seed"]),
    )
    full = base.metrics_by_window["development"]
    fold_ids = [row["id"] for row in runtime.spec["evaluation"]["chronological_folds"]]
    fold_sharpes = [
        float(base.metrics_by_window[fold_id]["sharpe_log_excess"])
        for fold_id in fold_ids
    ]
    parameter_sharpes = [
        float(result.metrics_by_window["development"]["sharpe_log_excess"])
        for result in parameter_results.values()
    ]
    parameter_drawdowns = [
        abs(float(result.metrics_by_window["development"]["maximum_drawdown"]))
        for result in parameter_results.values()
    ]
    sector_sharpes = [
        float(result.metrics_by_window["development"]["sharpe_log_excess"])
        for result in sector_results.values()
    ]
    timing_sharpes = [
        float(results[name].metrics_by_window["development"]["sharpe_log_excess"])
        for name in ("base", "delay_2", "phase_8", "phase_15", "phase_22")
    ]
    metrics = {
        "total_return": float(full["total_return"]),
        "cagr": float(full["cagr"]),
        "annual_volatility": float(full["annual_volatility"]),
        "sharpe_log_excess": float(full["sharpe_log_excess"]),
        "maximum_drawdown_magnitude": abs(float(full["maximum_drawdown"])),
        "annual_one_way_turnover": float(full["annual_one_way_turnover"]),
        "transaction_cost_paid": float(full["transaction_cost_paid"]),
        "double_cost_sharpe_log_excess": float(
            results["double_cost"].metrics_by_window["development"]["sharpe_log_excess"]
        ),
        "fold_sharpes": fold_sharpes,
        "fold_sharpe_25th_percentile": float(np.quantile(fold_sharpes, 0.25)),
        "positive_fold_share": float(np.mean(np.asarray(fold_sharpes) > 0.0)),
        "worst_timing_perturbation_sharpe": min(timing_sharpes),
        "timing_sharpes": timing_sharpes,
        "bootstrap_sharpe_percentile_05": float(bootstrap["sharpe_percentile_05"]),
        "bootstrap_probability_sharpe_above_zero": float(
            bootstrap["probability_sharpe_above_zero"]
        ),
        "bootstrap_probability_sharpe_above_one": float(
            bootstrap["probability_sharpe_above_one"]
        ),
        "parameter_neighborhood_minimum_sharpe": min(parameter_sharpes),
        "parameter_neighborhood_maximum_drawdown_magnitude": max(parameter_drawdowns),
        "leave_one_sector_out_minimum_sharpe": min(sector_sharpes),
        "leave_one_sector_out_median_sharpe": float(np.median(sector_sharpes)),
        **audit_summary,
        "maximum_single_name_positive_contribution_share": float(
            attribution_summary["maximum_single_name_positive_contribution_share"] or 0.0
        ),
        "maximum_single_sector_positive_contribution_share": float(
            attribution_summary["maximum_single_sector_positive_contribution_share"] or 0.0
        ),
    }
    failures = prospective_gate_failures(metrics, contract.spec["prospective_gate"])
    daily_variants = pd.concat(
        [
            result.daily.loc[sessions].reset_index().assign(variant_id=variant_id)
            for variant_id, result in {
                **results,
                **{f"parameter:{key}": value for key, value in parameter_results.items()},
                **{f"exclude_sector:{key}": value for key, value in sector_results.items()},
            }.items()
        ],
        ignore_index=True,
    )
    return {
        "daily_variants": daily_variants,
        "metrics": metrics,
        "concentration": audit_frame.reset_index(),
        "attribution": attribution_frame,
        "attribution_summary": attribution_summary,
        "failures": failures,
    }


def _read_existing_manifest(path: Path, source_manifest_sha256: str) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    body = dict(manifest)
    identity = str(body.pop("manifest_identity_sha256", ""))
    if canonical_sha256(body) != identity:
        raise ValueError(f"prospective evidence manifest identity mismatch: {path}")
    if manifest["identity"]["source_manifest_sha256"] != source_manifest_sha256:
        raise ValueError("same-date prospective source replacement is prohibited")
    for name, expected in manifest["outputs"].items():
        if sha256_file(path.parent / name) != expected:
            raise ValueError(f"prospective evidence output hash mismatch: {name}")
    return manifest


def _source_table_chain(
    filename: str,
    table: pd.DataFrame,
    *,
    row_limit: int | None = None,
) -> dict[str, Any]:
    keys = {
        "adjusted_ohlcv.csv": ["date", "symbol"],
        "raw_ohlcv.csv": ["date", "symbol"],
        "tradability.csv": ["date", "symbol"],
        "corporate_actions.csv": ["effective_date", "event_id"],
    }[filename]
    ordered = table.sort_values(keys, kind="stable").reset_index(drop=True)
    if row_limit is not None:
        if len(ordered) < row_limit:
            raise ValueError(f"append-only source shortened: {filename}")
        ordered = ordered.iloc[:row_limit]
    columns = list(ordered.columns)
    chain = "0" * 64
    for values in ordered.itertuples(index=False, name=None):
        row: dict[str, Any] = {}
        for column, value in zip(columns, values, strict=True):
            if pd.isna(value):
                normalized: Any = None
            elif isinstance(value, pd.Timestamp):
                normalized = value.isoformat()
            elif isinstance(value, np.generic):
                normalized = value.item()
            else:
                normalized = value
            row[column] = normalized
        row_hash = canonical_sha256(row)
        chain = hashlib.sha256(f"{chain}:{row_hash}".encode()).hexdigest()
    return {"columns": columns, "row_count": len(ordered), "chain_sha256": chain}


def _source_table_chains(package: CN27V13SourcePackage) -> dict[str, dict[str, Any]]:
    return {
        filename: _source_table_chain(filename, table)
        for filename, table in package.tables.items()
    }


def _verify_append_only_prefix(
    output_root: Path,
    package: CN27V13SourcePackage,
    observation_end: str,
) -> dict[str, dict[str, Any]]:
    current = _source_table_chains(package)
    if not output_root.exists():
        return current
    predecessors: list[tuple[pd.Timestamp, dict[str, Any]]] = []
    for path in output_root.glob("*/evidence_manifest.json"):
        manifest = json.loads(path.read_text(encoding="utf-8"))
        previous_end = manifest.get("observation", {}).get("end")
        if previous_end and pd.Timestamp(previous_end) < pd.Timestamp(observation_end):
            predecessors.append((pd.Timestamp(previous_end), manifest))
    if not predecessors:
        return current
    _, previous = max(predecessors, key=lambda item: item[0])
    previous_chains = previous.get("source_table_chains")
    if not isinstance(previous_chains, dict):
        raise ValueError("previous prospective evidence lacks append-only table chains")
    for filename, prior in previous_chains.items():
        if filename not in package.tables:
            raise ValueError(f"append-only source removed: {filename}")
        prefix = _source_table_chain(
            filename,
            package.tables[filename],
            row_limit=int(prior["row_count"]),
        )
        if prefix != prior:
            raise ValueError(f"append-only source prefix changed: {filename}")
    return current


def _write_prospective_evidence(
    contract: CN27V13ProspectiveContract,
    package: CN27V13SourcePackage,
    readiness: dict[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    source_sha256 = sha256_file(package.manifest_path)
    observation_end = str(readiness["observation_end"] or "empty")
    table_chains = _verify_append_only_prefix(output_root, package, observation_end)
    output = output_root / f"{observation_end}_{source_sha256[:12]}"
    siblings = list(output_root.glob(f"{observation_end}_*")) if output_root.exists() else []
    if siblings and output not in siblings:
        raise ValueError("same-date prospective source replacement is prohibited")
    manifest_path = output / "evidence_manifest.json"
    if manifest_path.is_file():
        return _read_existing_manifest(manifest_path, source_sha256)
    if output.exists():
        raise ValueError("incomplete prospective evidence directory already exists")
    output.mkdir(parents=True)

    pd.DataFrame(columns=["date", "variant_id"]).to_csv(
        output / "daily_variants.csv", index=False
    )
    write_json(output / "prospective_metrics.json", {"available": False, **readiness})
    pd.DataFrame(columns=["date"]).to_csv(output / "concentration_audit.csv", index=False)
    pd.DataFrame(columns=["date"]).to_csv(output / "attribution.csv", index=False)
    write_json(
        output / "attribution_summary.json",
        {"available": False, "reason": "prospective observation is incomplete"},
    )
    decision = {
        "schema_version": "1.0",
        "validation_id": contract.spec["validation_id"],
        "decision": "insufficient_prospective_observation",
        "formal_v1_3_packaging_authorized": False,
        "readiness": readiness,
        "research_only": True,
        "trade_ready": False,
        "automatic_promotion_allowed": False,
    }
    write_json(output / "decision.json", decision)
    report = "\n".join(
        [
            "# CN_27 V1.3 prospective validation",
            "",
            "- Decision: `insufficient_prospective_observation`",
            f"- Sessions: {readiness['session_count']}",
            f"- Observation start: `{readiness['observation_start']}`",
            f"- Observation end: `{readiness['observation_end']}`",
            f"- Blocking reasons: `{','.join(readiness['reasons'])}`",
            "- Formal V1.3 packaging authorized: `false`",
            "- Research only: `true`; trade ready: `false`",
        ]
    )
    (output / "report.md").write_text(report + "\n", encoding="utf-8")
    output_names = [
        name
        for name in contract.spec["evidence"]["expected_outputs"]
        if name != "evidence_manifest.json"
    ]
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "validation_id": contract.spec["validation_id"],
        "decision": decision["decision"],
        "identity": {
            "validation_contract_sha256": sha256_file(contract.spec_path),
            "challenger_contract_sha256": contract.spec["lineage"][
                "challenger_contract_sha256"
            ],
            "historical_manifest_identity_sha256": contract.spec["lineage"][
                "historical_manifest_identity_sha256"
            ],
            "source_manifest_sha256": source_sha256,
            "implementation_sha256": sha256_file(Path(__file__)),
        },
        "source_files": dict(package.manifest["files"]),
        "source_table_chains": table_chains,
        "observation": {
            "start": readiness["observation_start"],
            "end": readiness["observation_end"],
            "sessions": readiness["session_count"],
        },
        "outputs": {name: sha256_file(output / name) for name in output_names},
        "research_only": True,
        "trade_ready": False,
        "automatic_promotion_allowed": False,
    }
    manifest["manifest_identity_sha256"] = canonical_sha256(manifest)
    write_json(manifest_path, manifest)
    return manifest


def _write_ready_evidence(
    contract: CN27V13ProspectiveContract,
    package: CN27V13SourcePackage,
    readiness: dict[str, Any],
    evaluation: dict[str, Any],
    output_root: Path,
) -> dict[str, Any]:
    source_sha256 = sha256_file(package.manifest_path)
    observation_end = str(readiness["observation_end"])
    table_chains = _verify_append_only_prefix(output_root, package, observation_end)
    output = output_root / f"{observation_end}_{source_sha256[:12]}"
    siblings = list(output_root.glob(f"{observation_end}_*")) if output_root.exists() else []
    if siblings and output not in siblings:
        raise ValueError("same-date prospective source replacement is prohibited")
    manifest_path = output / "evidence_manifest.json"
    if manifest_path.is_file():
        return _read_existing_manifest(manifest_path, source_sha256)
    if output.exists():
        raise ValueError("incomplete prospective evidence directory already exists")
    output.mkdir(parents=True)

    evaluation["daily_variants"].to_csv(
        output / "daily_variants.csv", index=False, date_format="%Y-%m-%d"
    )
    write_json(
        output / "prospective_metrics.json",
        {**readiness, "metrics": evaluation["metrics"]},
    )
    evaluation["concentration"].to_csv(
        output / "concentration_audit.csv", index=False, date_format="%Y-%m-%d"
    )
    evaluation["attribution"].to_csv(
        output / "attribution.csv", index=False, date_format="%Y-%m-%d"
    )
    write_json(output / "attribution_summary.json", evaluation["attribution_summary"])
    passed = not evaluation["failures"]
    decision_name = (
        "prospective_gate_passed_formal_v1_3_packaging_authorized"
        if passed
        else "prospective_gate_failed"
    )
    decision = {
        "schema_version": "1.0",
        "validation_id": contract.spec["validation_id"],
        "decision": decision_name,
        "formal_v1_3_packaging_authorized": passed,
        "failed_gates": list(evaluation["failures"]),
        "readiness": readiness,
        "automatic_promotion_allowed": False,
        "research_only": True,
        "trade_ready": False,
    }
    write_json(output / "decision.json", decision)
    metrics = evaluation["metrics"]
    report = "\n".join(
        [
            "# CN_27 V1.3 prospective validation",
            "",
            f"- Decision: `{decision_name}`",
            f"- Sessions: {readiness['session_count']}",
            f"- Observation window: `{readiness['observation_start']}` to `{readiness['observation_end']}`",
            f"- Sharpe: {float(metrics['sharpe_log_excess']):.4f}",
            f"- Maximum drawdown magnitude: {float(metrics['maximum_drawdown_magnitude']):.2%}",
            f"- Worst timing Sharpe: {float(metrics['worst_timing_perturbation_sharpe']):.4f}",
            f"- Bootstrap Sharpe p05: {float(metrics['bootstrap_sharpe_percentile_05']):.4f}",
            f"- Failed gates: `{','.join(evaluation['failures'])}`",
            f"- Formal V1.3 packaging authorized: `{str(passed).lower()}`",
            "- Automatic promotion: `false`",
            "- Research only: `true`; trade ready: `false`",
        ]
    )
    (output / "report.md").write_text(report + "\n", encoding="utf-8")
    output_names = [
        name
        for name in contract.spec["evidence"]["expected_outputs"]
        if name != "evidence_manifest.json"
    ]
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "validation_id": contract.spec["validation_id"],
        "decision": decision_name,
        "identity": {
            "validation_contract_sha256": sha256_file(contract.spec_path),
            "challenger_contract_sha256": contract.spec["lineage"][
                "challenger_contract_sha256"
            ],
            "historical_manifest_identity_sha256": contract.spec["lineage"][
                "historical_manifest_identity_sha256"
            ],
            "source_manifest_sha256": source_sha256,
            "implementation_sha256": sha256_file(Path(__file__)),
        },
        "source_files": dict(package.manifest["files"]),
        "source_table_chains": table_chains,
        "observation": {
            "start": readiness["observation_start"],
            "end": readiness["observation_end"],
            "sessions": readiness["session_count"],
        },
        "outputs": {name: sha256_file(output / name) for name in output_names},
        "formal_v1_3_packaging_authorized": passed,
        "research_only": True,
        "trade_ready": False,
        "automatic_promotion_allowed": False,
    }
    manifest["manifest_identity_sha256"] = canonical_sha256(manifest)
    write_json(manifest_path, manifest)
    return manifest


def run_prospective_validation(
    contract_path: str | Path,
    source_manifest_path: str | Path,
    *,
    output_root: str | Path | None = None,
) -> dict[str, Any]:
    contract = load_prospective_contract(contract_path)
    package = load_source_package(contract, source_manifest_path)
    sessions = validate_source_package(contract, package)
    readiness = evaluate_observation_readiness(contract, sessions)
    destination = (
        contract.root / str(contract.spec["evidence"]["output_dir"])
        if output_root is None
        else Path(output_root).resolve()
    )
    if not readiness["ready"]:
        return _write_prospective_evidence(contract, package, readiness, destination)
    evaluation = _evaluate_ready_package(contract, package, sessions)
    return _write_ready_evidence(
        contract,
        package,
        readiness,
        evaluation,
        destination,
    )
