#!/usr/bin/env python3
"""Publish CN_27 V1.3 as a user-directed formal research baseline.

The frozen historical screen remains unsupported.  This publisher reconstructs
the exact k2 row-level evidence, verifies it against the sealed summary, records
the explicit governance exception, and creates native preview/formal Bundle v2
artifacts without claiming that prospective validation passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.artifacts.formal_evidence_standard import validate_formal_evidence_bundle
from src.artifacts.formal_preview_builder import build_preview_bundle
from src.artifacts.model_run_bundle_v2 import canonical_json_bytes
from src.artifacts.model_run_exporter import update_catalog
from src.artifacts.native_formal_promotion import promote_preview_bundle
from src.governance.active_strategy_catalog import (
    assert_formal_catalog_matches_active_strategies,
    load_active_strategy_catalog,
)
from src.research.all_weather_alpha_rotation import canonical_sha256, sha256_file
from src.research.cn27_v1_2 import (
    _block_bootstrap_sharpe,
    compute_v1_2_features,
    score_v1_2_features,
)
from src.research.cn27_v1_3 import concentration_audit, contribution_attribution
from src.research.cn27_v1_3_projected import (
    load_projected_discovery_contract,
    run_projected_recipe,
)


MODEL_ID = "cn_27_v1_3"
STRATEGY_ID = "cn_27"
FAMILY_ID = "cn_27_rotation"
RECIPE_ID = "k2_projected_22_45_n8"
EXPERIMENT_ID = "cn_27_v1_3_projected_concentration_discovery_v1"
BACKTEST_ID = "cn_27_v1_3-through-2026_09_04"
GENERATED_AT = "2026-09-07T12:00:00+08:00"
EVIDENCE_CUTOFF = "2026-09-04"
FAILED_GATES = ["timing_perturbation_sharpe", "bootstrap_p05"]
CONTRACT = Path(
    "configs/research_experiments/cn_27_v1_3_projected_concentration_discovery_v1.yaml"
)
DISCOVERY_ROOT = Path(
    "artifacts/evidence/cn_27_v1_3_projected_concentration_discovery_v1"
)
CANDIDATE = Path("configs/research_candidates/cn_27_v1_3_prospective_challenger.yaml")
MODEL_CONTRACT = Path("configs/models/cn_27_v1_3.yaml")


class Cn27V13PublicationError(ValueError):
    """Raised when the user-directed publication boundary cannot be proven."""


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Cn27V13PublicationError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise Cn27V13PublicationError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload))


def _repository_path(path: Path) -> str:
    return path.resolve().relative_to(Path.cwd().resolve()).as_posix()


def _close(left: object, right: object, label: str) -> None:
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        raise Cn27V13PublicationError(f"non-numeric comparison: {label}")
    if abs(float(left) - float(right)) > 1e-10:
        raise Cn27V13PublicationError(f"historical evidence drifted: {label}")


def _verify_discovery() -> tuple[dict[str, Any], pd.Series]:
    manifest_path = DISCOVERY_ROOT / "evidence_manifest.json"
    manifest = _object(manifest_path)
    body = dict(manifest)
    identity = str(body.pop("manifest_identity_sha256", ""))
    if (
        manifest.get("experiment_id") != EXPERIMENT_ID
        or manifest.get("decision") != "no_projected_candidate_passed_frozen_gate"
        or manifest.get("research_only") is not True
        or manifest.get("trade_ready") is not False
        or canonical_sha256(body) != identity
    ):
        raise Cn27V13PublicationError("sealed projected discovery boundary drifted")
    for name, expected in manifest.get("outputs", {}).items():
        path = DISCOVERY_ROOT / str(name)
        if not path.is_file() or _sha256(path) != expected:
            raise Cn27V13PublicationError(f"sealed discovery output drifted: {name}")
    summary = pd.read_csv(DISCOVERY_ROOT / "candidate_summary.csv")
    matches = summary.loc[summary["recipe_id"].eq(RECIPE_ID)]
    if len(matches) != 1:
        raise Cn27V13PublicationError("k2 candidate summary identity drifted")
    row = matches.iloc[0]
    failures = str(row["failure_reasons"]).split("+")
    if bool(row["selection_gate_passed"]) or failures != FAILED_GATES:
        raise Cn27V13PublicationError("k2 failed gates must remain explicit")
    return manifest, row


def build_promotion_receipt() -> dict[str, Any]:
    manifest, row = _verify_discovery()
    receipt = {
        "schema_version": "cn_27_v1_3_user_directed_promotion_v1",
        "model_id": MODEL_ID,
        "strategy_id": STRATEGY_ID,
        "selected_candidate": RECIPE_ID,
        "decision": "promoted_by_explicit_user_governance_exception",
        "promotion_date": "2026-09-07",
        "promotion_authority": {
            "kind": "explicit_user_direction",
            "instruction": "publish_now_and_accumulate_prospective_evidence_over_time",
        },
        "source_experiment": {
            "experiment_id": EXPERIMENT_ID,
            "manifest": (DISCOVERY_ROOT / "evidence_manifest.json").as_posix(),
            "manifest_sha256": _sha256(DISCOVERY_ROOT / "evidence_manifest.json"),
            "manifest_identity_sha256": manifest["manifest_identity_sha256"],
            "contract": CONTRACT.as_posix(),
            "contract_sha256": _sha256(CONTRACT),
            "candidate_contract": CANDIDATE.as_posix(),
            "candidate_contract_sha256": _sha256(CANDIDATE),
            "original_decision": manifest["decision"],
        },
        "preregistered_gate_result": {
            "passed": 19,
            "total": 21,
            "supported": False,
            "failed_gates": [
                {
                    "gate": "timing_perturbation_sharpe",
                    "observed": float(row["worst_timing_perturbation_sharpe"]),
                    "required": 0.90,
                },
                {
                    "gate": "bootstrap_p05",
                    "observed": float(row["bootstrap_sharpe_percentile_05"]),
                    "required": 0.30,
                },
            ],
        },
        "positive_historical_evidence": {
            key: float(row[key])
            for key in (
                "full_total_return",
                "full_cagr",
                "full_annual_volatility",
                "full_sharpe_log_excess",
                "full_maximum_drawdown",
                "full_annual_one_way_turnover",
                "double_cost_full_sharpe",
                "positive_fold_share",
                "fold_sharpe_25th_percentile",
                "parameter_neighborhood_minimum_sharpe",
                "leave_one_sector_out_minimum_sharpe",
            )
        },
        "prospective_validation": {
            "status": "pending",
            "contract": "configs/research_experiments/cn_27_v1_3_prospective_validation_v1.yaml",
            "observation_start_strictly_after": "2026-09-04",
            "minimum_calendar_months": 12,
            "minimum_expected_sessions": 240,
            "gate_passed": False,
        },
        "governance_interpretation": {
            "automatic_promotion": False,
            "formal_acceptance_supported_by_preregistered_gates": False,
            "research_baseline_promotion_authorized": True,
            "failed_evidence_retained": True,
            "selected_pool_readiness_claimed": False,
            "model_selection_reopened": False,
        },
        "research_only": True,
        "trade_ready": False,
    }
    receipt["receipt_identity_sha256"] = canonical_sha256(receipt)
    return receipt


def _benchmark_path(bars: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.Series:
    benchmark = (
        bars.loc[bars["symbol"].astype(str).str.zfill(6).eq("000300")]
        .sort_values("date")
        .set_index("date")["open"]
        .reindex(dates)
        .ffill()
        .pct_change(fill_method=None)
        .fillna(0.0)
    )
    return benchmark.astype(float)


def _action(previous: float, target: float) -> str:
    if previous <= 1e-12:
        return "BUY"
    if target <= 1e-12:
        return "SELL"
    return "INCREASE" if target > previous else "DECREASE"


def build_source_package(
    promotion_path: Path,
    *,
    generated_at: str = GENERATED_AT,
) -> dict[str, Any]:
    manifest, retained = _verify_discovery()
    promotion = _object(promotion_path)
    if (
        promotion.get("decision") != "promoted_by_explicit_user_governance_exception"
        or promotion.get("receipt_identity_sha256")
        != canonical_sha256(
            {key: value for key, value in promotion.items() if key != "receipt_identity_sha256"}
        )
        or promotion.get("research_only") is not True
        or promotion.get("trade_ready") is not False
    ):
        raise Cn27V13PublicationError("promotion receipt boundary drifted")

    contract = load_projected_discovery_contract(CONTRACT)
    recipe = next(
        (dict(row) for row in contract.spec["candidate_recipes"] if row["id"] == RECIPE_ID),
        None,
    )
    if recipe is None:
        raise Cn27V13PublicationError("frozen k2 recipe is missing")
    bars = pd.read_csv(contract.prices_path, dtype={"symbol": str}, parse_dates=["date"])
    features = compute_v1_2_features(bars, contract)
    scoring_recipe = {**contract.spec["frozen_signal"], "id": "frozen_v1_2_signal"}
    scored, _ = score_v1_2_features(features, scoring_recipe, contract)
    result = run_projected_recipe(
        bars,
        features,
        contract,
        recipe,
        scored_features=scored,
    )
    full = result.metrics_by_window["development"]
    comparisons = {
        "total_return": "full_total_return",
        "cagr": "full_cagr",
        "annual_volatility": "full_annual_volatility",
        "sharpe_log_excess": "full_sharpe_log_excess",
        "maximum_drawdown": "full_maximum_drawdown",
        "annual_one_way_turnover": "full_annual_one_way_turnover",
        "transaction_cost_paid": "full_transaction_cost_paid",
    }
    for observed, expected in comparisons.items():
        _close(full[observed], retained[expected], observed)

    bootstrap_policy = contract.spec["robustness_tests"]["block_bootstrap"]
    bootstrap = _block_bootstrap_sharpe(
        result.daily["net_return"],
        samples=int(bootstrap_policy["samples"]),
        block_sessions=int(bootstrap_policy["block_sessions"]),
        seed=int(bootstrap_policy["seed"]),
    )
    _close(
        bootstrap["sharpe_percentile_05"],
        retained["bootstrap_sharpe_percentile_05"],
        "bootstrap_sharpe_percentile_05",
    )
    audit, audit_summary = concentration_audit(result.daily, contract)
    attribution, attribution_summary = contribution_attribution(result.daily, bars, contract)
    for key, value in audit_summary.items():
        _close(value, retained[key], key)
    for key in (
        "maximum_single_name_positive_contribution_share",
        "maximum_single_sector_positive_contribution_share",
    ):
        _close(attribution_summary[key], retained[key], key)

    daily = result.daily.copy()
    dates = pd.DatetimeIndex(daily.index)
    benchmark_return = _benchmark_path(bars, dates)
    benchmark_equity = (1.0 + benchmark_return).cumprod()
    open_returns = {
        symbol: (
            bars.loc[bars["symbol"].astype(str).str.zfill(6).eq(symbol)]
            .sort_values("date")
            .set_index("date")["open"]
            .reindex(dates)
            .ffill()
            .pct_change(fill_method=None)
            .fillna(0.0)
        )
        for symbol in (*contract.candidate_symbols, contract.defensive_symbol)
    }
    previous: dict[str, float] = {"CASH": 1.0}
    report: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    names = {
        str(row["symbol"]).zfill(6): str(row["name"])
        for row in contract.pool["symbols"]
    }
    sectors = {
        str(row["symbol"]).zfill(6): str(row["sector"])
        for row in contract.pool["symbols"]
    }
    for date, row in daily.iterrows():
        date_text = pd.Timestamp(date).date().isoformat()
        weights = {key: float(value) for key, value in json.loads(str(row["asset_weights"])).items()}
        if float(row["cash_weight"]) > 1e-12:
            weights["CASH"] = float(row["cash_weight"])
        report.append(
            {
                "date": date_text,
                "gross_return": float(row["gross_return"]),
                "transaction_cost": float(row["transaction_cost"]),
                "net_return": float(row["net_return"]),
                "account": float(row["equity"]),
                "benchmark_return": float(benchmark_return.loc[date]),
                "benchmark_account": float(benchmark_equity.loc[date]),
                "drawdown": float(row["equity"] / daily.loc[:date, "equity"].max() - 1.0),
                "one_way_turnover": float(row["one_way_turnover"]),
                "equity_exposure": float(row["equity_exposure"]),
                "etf_weight": float(row["etf_weight"]),
                "cash_weight": float(row["cash_weight"]),
                "holding_count": int(row["holding_count"]),
                "pending_execution": bool(row["pending_execution"]),
                "target_drift_due_to_trade_lock": float(row["target_drift_due_to_trade_lock"]),
            }
        )
        for symbol, weight in sorted(weights.items()):
            if symbol == "CASH":
                name, sector, role = "Cash", "cash", "cash"
            elif symbol == contract.defensive_symbol:
                name, sector, role = "Dividend ETF 515180", "defensive_etf", "defensive_etf"
            else:
                name, sector, role = names[symbol], sectors[symbol], "candidate_equity"
            positions.append(
                {
                    "date": date_text,
                    "instrument": symbol,
                    "name": name,
                    "sector": sector,
                    "role": role,
                    "weight": weight,
                }
            )
        gross_factor = 1.0 + float(row["gross_return"])
        before = {
            symbol: previous.get(symbol, 0.0)
            * (1.0 + float(open_returns[symbol].loc[date]))
            / gross_factor
            for symbol in previous
            if symbol != "CASH"
        }
        before["CASH"] = previous.get("CASH", 0.0) / gross_factor
        changes = {
            symbol: weights.get(symbol, 0.0) - before.get(symbol, 0.0)
            for symbol in sorted(set(weights) | set(before))
        }
        changed_total = sum(abs(value) for value in changes.values())
        for symbol, delta in changes.items():
            if abs(delta) <= 1e-12:
                continue
            trades.append(
                {
                    "date": date_text,
                    "instrument": symbol,
                    "action": _action(before.get(symbol, 0.0), weights.get(symbol, 0.0)),
                    "previous_weight": before.get(symbol, 0.0),
                    "target_weight": weights.get(symbol, 0.0),
                    "weight_delta": delta,
                    "transaction_cost": (
                        float(row["transaction_cost"]) * abs(delta) / changed_total
                        if changed_total > 1e-12
                        else 0.0
                    ),
                    "reason": "scheduled_rank_and_project_or_locked_target_retry",
                }
            )
        previous = weights

    attribution_rows = attribution.copy()
    attribution_rows["date"] = pd.to_datetime(attribution_rows["date"]).dt.strftime("%Y-%m-%d")
    attribution_payload = attribution_rows.to_dict(orient="records")
    gross_by_symbol = attribution.groupby(["symbol", "sector"], as_index=False)[
        "gross_contribution"
    ].sum()
    for row in gross_by_symbol.to_dict(orient="records"):
        attribution_payload.append(
            {
                "date": None,
                "symbol": row["symbol"],
                "sector": row["sector"],
                "gross_contribution": float(row["gross_contribution"]),
                "attribution_level": "full_window_instrument",
            }
        )

    window_summary: list[dict[str, Any]] = [
        {"test": "chronological_fold", "fold": name, **metrics}
        for name, metrics in result.metrics_by_window.items()
        if name != "development"
    ]
    window_summary.extend(
        {
            "test": "timing_perturbation",
            "variant": key,
            "sharpe_log_excess": float(value),
        }
        for key, value in json.loads(str(retained["phase_sharpes"])).items()
    )
    window_summary.append(
        {
            "test": "execution_delay",
            "variant": "two_sessions",
            "sharpe_log_excess": float(retained["delay_two_full_sharpe"]),
        }
    )
    parameters = pd.read_csv(DISCOVERY_ROOT / "parameter_robustness.csv")
    for row in parameters.loc[parameters["recipe_id"].eq(RECIPE_ID)].to_dict(orient="records"):
        window_summary.append({"test": "parameter_neighborhood", **row})
    sectors_frame = pd.read_csv(DISCOVERY_ROOT / "leave_one_sector_out.csv")
    for row in sectors_frame.loc[sectors_frame["recipe_id"].eq(RECIPE_ID)].to_dict(orient="records"):
        window_summary.append({"test": "leave_one_sector_out", **row})
    window_summary.extend(
        [
            {
                "test": "block_bootstrap",
                "samples": int(bootstrap_policy["samples"]),
                "block_sessions": int(bootstrap_policy["block_sessions"]),
                **bootstrap,
            },
            {
                "test": "frozen_gate_result",
                "supported": False,
                "passed": 19,
                "total": 21,
                "failed_gates": FAILED_GATES,
            },
        ]
    )

    benchmark_total = float(benchmark_equity.iloc[-1] - 1.0)
    total_return = float(full["total_return"])
    package = {
        "schema_version": "1.0.0",
        "record_type": "formal_model_backtest",
        "backtest_id": BACKTEST_ID,
        "model_id": MODEL_ID,
        "display_name": "CN_27 V1.3",
        "market": "cn",
        "benchmark": "000300",
        "publication_status": "accepted_formal_baseline",
        "generated_at": generated_at,
        "evidence_cutoff": EVIDENCE_CUTOFF,
        "research_only": True,
        "trade_ready": False,
        "trace_frequency": "daily_open_to_open",
        "date_range": {
            "start": dates.min().date().isoformat(),
            "end": dates.max().date().isoformat(),
        },
        "metrics": {
            "Total Return": total_return,
            "Annualized Return": float(full["cagr"]),
            "Benchmark Return": benchmark_total,
            "Compounded Relative Excess Return": (1.0 + total_return) / (1.0 + benchmark_total) - 1.0,
            "Annualized Volatility": float(full["annual_volatility"]),
            "Sharpe Ratio": float(full["sharpe_log_excess"]),
            "Max Drawdown": float(full["maximum_drawdown"]),
            "Turnover": float(full["annual_one_way_turnover"]),
            "Transaction Cost": float(full["transaction_cost_paid"]),
        },
        "portfolio_contract": {
            "universe": "cn_all_weather_alpha_rotation_v1",
            "universe_size": 27,
            "candidate": RECIPE_ID,
            "signal": "frozen_v1_2_seven_factor_cross_sectional_percentile_rank",
            "top_k": 12,
            "maximum_names_per_sector": 3,
            "weighting": "shrinkage_minimum_variance_then_minimum_distance_concentration_projection",
            "maximum_single_equity_sleeve_share": 0.22,
            "maximum_sector_equity_sleeve_share": 0.45,
            "minimum_effective_names": 8.0,
            "maximum_single_absolute_weight": 0.15,
            "defensive_etf": "515180",
            "benchmark": "000300",
            "horizon_sessions": 1,
            "holding_sessions": 30,
            "rebalance_sessions": 30,
            "execution_delay_sessions": 1,
            "cost_bps": 10,
            "cost_contract": "asymmetric_stock_5_10bps_etf_2_2bps",
        },
        "report": report,
        "positions": positions,
        "trades": trades,
        "attribution": attribution_payload,
        "window_summary": window_summary,
        "evidence": {
            "source_experiment_manifest": (DISCOVERY_ROOT / "evidence_manifest.json").as_posix(),
            "source_experiment_manifest_sha256": _sha256(
                DISCOVERY_ROOT / "evidence_manifest.json"
            ),
            "source_experiment_manifest_identity_sha256": manifest[
                "manifest_identity_sha256"
            ],
            "source_prices": contract.prices_path.relative_to(Path.cwd().resolve()).as_posix(),
            "source_prices_sha256": sha256_file(contract.prices_path),
            "pool": contract.pool_path.relative_to(Path.cwd().resolve()).as_posix(),
            "pool_sha256": sha256_file(contract.pool_path),
            "promotion_receipt": promotion_path.as_posix(),
            "promotion_receipt_sha256": _sha256(promotion_path),
            "promotion_authority": promotion["promotion_authority"],
            "historical_evidence_recomputed": True,
            "exact_historical_reproduction": True,
            "model_selection_reopened": False,
            "preregistered_gates_supported": False,
            "failed_gates": FAILED_GATES,
            "prospective_gate_status": "pending",
            "selected_pool_readiness_claimed": False,
            "row_counts": {
                "performance": len(report),
                "positions": len(positions),
                "trades": len(trades),
                "attribution": len(attribution_payload),
                "robustness": len(window_summary),
            },
        },
        "evidence_completeness": {
            "status": "complete",
            "performance_trace": "exact_recomputed_and_sealed_daily_open_to_open",
            "holdings": "exact_daily_post_execution_weights",
            "trades": "derived_from_consecutive_exact_daily_weights",
            "attribution": "exact_reconciled_daily_gross_contributions",
            "risk_states": "equity_exposure_etf_cash_and_pending_execution_retained",
            "robustness": "frozen_folds_cost_timing_parameter_sector_and_bootstrap_results",
            "not_applicable": ["brokerage_quantity", "brokerage_fill_price"],
            "missing": [],
        },
        "freshness": {
            "schema_version": "1.0.0",
            "status": "frozen_historical_evidence_prospective_pending",
            "latest_completed_session": EVIDENCE_CUTOFF,
            "prospective_observation_start_strictly_after": EVIDENCE_CUTOFF,
            "prospective_gate_status": "pending",
            "model_selection_reopened": False,
        },
        "interpretation_notes": [
            "CN_27 V1.3 is a user-directed formal research baseline in its own strategy family.",
            "The frozen historical gate remains unsupported because timing perturbation Sharpe and bootstrap p05 failed.",
            "The row-level path was deterministically reconstructed from the frozen k2 recipe and matched to the sealed summary; no model selection was reopened.",
            "The 27-name strategy-specific pool does not claim CN130 selected-pool readiness.",
            "Prospective validation is pending and may accumulate without parameter, pool, cost, or execution changes.",
            "Research evidence only; not authorization for live or automated trading.",
        ],
    }
    return package


def _manifests_with_replacement(
    root: Path,
    catalog_path: Path,
    replacement: Path,
) -> list[Path]:
    catalog = _object(catalog_path)
    rows = catalog.get("records")
    if not isinstance(rows, list):
        raise Cn27V13PublicationError(f"catalog records missing: {catalog_path}")
    manifests = [replacement]
    for row in rows:
        if not isinstance(row, Mapping) or row.get("model_version_id") == MODEL_ID:
            continue
        path = root / str(row.get("manifest_path") or "")
        if not path.is_file() or _sha256(path) != row.get("manifest_sha256"):
            raise Cn27V13PublicationError(f"retained catalog manifest drifted: {path}")
        manifests.append(path)
    return manifests


def _update_freshness(path: Path) -> None:
    payload = _object(path)
    required = payload.get("required_models")
    if not isinstance(required, list):
        raise Cn27V13PublicationError("formal freshness required_models is missing")
    if MODEL_ID not in required:
        required.append(MODEL_ID)
    payload["required_models"] = required
    _write(path, payload)


def publish(
    *,
    promotion_output: Path,
    source_output: Path,
    preview_root: Path,
    formal_root: Path,
    publication_receipt: Path,
    strategy_catalog: Path,
) -> dict[str, Any]:
    preview_root = preview_root.resolve()
    formal_root = formal_root.resolve()
    strategy_catalog = strategy_catalog.resolve()
    promotion = build_promotion_receipt()
    _write(promotion_output, promotion)
    package = build_source_package(promotion_output)
    _write(source_output, package)

    active = load_active_strategy_catalog(strategy_catalog)
    strategy = active.by_strategy_id.get(STRATEGY_ID)
    if (
        strategy is None
        or strategy.model_version_id != MODEL_ID
        or strategy.model_family_id != FAMILY_ID
    ):
        raise Cn27V13PublicationError("active CN_27 strategy identity is missing")
    preview_manifest = build_preview_bundle(source_output, strategy, output_root=preview_root)
    formal_manifest = promote_preview_bundle(preview_manifest.parent, formal_root, strategy)
    validate_formal_evidence_bundle(formal_manifest.parent)
    update_catalog(
        _manifests_with_replacement(preview_root, preview_root / "catalog.json", preview_manifest),
        catalog_path=preview_root / "catalog.json",
        channel="preview",
    )
    update_catalog(
        _manifests_with_replacement(formal_root, formal_root / "catalog.json", formal_manifest),
        catalog_path=formal_root / "catalog.json",
        channel="formal",
    )
    _update_freshness(formal_root / "freshness.json")
    formal_catalog = _object(formal_root / "catalog.json")
    assert_formal_catalog_matches_active_strategies(formal_catalog, active)
    receipt = {
        "schema_version": "cn_27_v1_3_formal_publication_v1",
        "status": "published_formal_research_baseline",
        "strategy_id": STRATEGY_ID,
        "model_family_id": FAMILY_ID,
        "model_version_id": MODEL_ID,
        "promotion_receipt": promotion_output.as_posix(),
        "promotion_receipt_sha256": _sha256(promotion_output),
        "source_package": source_output.as_posix(),
        "source_package_sha256": _sha256(source_output),
        "preview_manifest": _repository_path(preview_manifest),
        "preview_manifest_sha256": _sha256(preview_manifest),
        "formal_manifest": _repository_path(formal_manifest),
        "formal_manifest_sha256": _sha256(formal_manifest),
        "formal_bundle_catalog_sha256": _sha256(formal_root / "catalog.json"),
        "prospective_gate_status": "pending",
        "preregistered_gates_supported": False,
        "failed_gates": FAILED_GATES,
        "selected_pool_readiness_claimed": False,
        "model_selection_reopened": False,
        "research_only": True,
        "trade_ready": False,
    }
    receipt["receipt_identity_sha256"] = canonical_sha256(receipt)
    _write(publication_receipt, receipt)
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--promotion-output",
        type=Path,
        default=Path(
            "data/research/experiment_receipts/cn_27_v1_3_user_directed_promotion_v1.json"
        ),
    )
    parser.add_argument(
        "--source-output",
        type=Path,
        default=Path("data/research/historical_model_evidence/cn_27_v1_3.json"),
    )
    parser.add_argument("--preview-root", type=Path, default=Path("data/research/model_runs"))
    parser.add_argument(
        "--formal-root", type=Path, default=Path("data/research/formal_model_runs")
    )
    parser.add_argument(
        "--publication-receipt",
        type=Path,
        default=Path("data/research/experiment_receipts/cn_27_v1_3_formal_publication_v1.json"),
    )
    parser.add_argument(
        "--strategy-catalog", type=Path, default=Path("configs/strategies/registry.json")
    )
    args = parser.parse_args()
    receipt = publish(
        promotion_output=args.promotion_output,
        source_output=args.source_output,
        preview_root=args.preview_root,
        formal_root=args.formal_root,
        publication_receipt=args.publication_receipt,
        strategy_catalog=args.strategy_catalog,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
