"""Staggered-sleeve timing diversification for the CN_27 V1.3 completion cycle."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from typing import Mapping, Sequence

import numpy as np
import pandas as pd
import yaml

from src.research.all_weather_alpha_rotation import canonical_sha256, sha256_file
from src.research.cn27_sharpe_discovery import (
    CN27DiscoveryContract,
    DiscoveryBacktestResult,
    _window_metrics,
    write_json,
)
from src.research.cn27_v1_2 import (
    _block_bootstrap_sharpe,
    compute_v1_2_features,
    score_v1_2_features,
)
from src.research.cn27_v1_3 import (
    _parameter_variants,
    concentration_audit,
    contribution_attribution,
    load_v1_3_discovery_contract,
    run_v1_3_discovery_recipe,
)


def _verify_manifest(path: Path, expected_file_hash: str, expected_identity: str) -> None:
    if sha256_file(path) != expected_file_hash:
        raise ValueError(f"lineage manifest file hash mismatch: {path}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    body = dict(manifest)
    identity = str(body.pop("manifest_identity_sha256", ""))
    if canonical_sha256(body) != identity or identity != expected_identity:
        raise ValueError(f"lineage manifest identity mismatch: {path}")
    for name, expected in manifest.get("outputs", {}).items():
        if sha256_file(path.parent / name) != expected:
            raise ValueError(f"lineage output hash mismatch: {path.parent / name}")


def load_staggered_discovery_contract(path: str | Path) -> CN27DiscoveryContract:
    spec_path = Path(path).resolve()
    root = spec_path.parents[2]
    overlay = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    if not isinstance(overlay, dict) or overlay.get("status") != "frozen_pre_screen":
        raise ValueError("CN_27 V1.3 staggered-sleeve contract must be frozen")
    if overlay.get("research_only") is not True or overlay.get("trade_ready") is not False:
        raise ValueError("CN_27 V1.3 staggered discovery must remain research-only")
    lineage = overlay["lineage"]
    base_path = (root / str(lineage["concentration_contract"])).resolve()
    if sha256_file(base_path) != str(lineage["concentration_contract_sha256"]):
        raise ValueError("CN_27 V1.3 concentration contract hash mismatch")
    _verify_manifest(
        (root / str(lineage["concentration_manifest"])).resolve(),
        str(lineage["concentration_manifest_file_sha256"]),
        str(lineage["concentration_manifest_identity_sha256"]),
    )
    base = load_v1_3_discovery_contract(base_path)
    merged = copy.deepcopy(base.spec)
    for key in (
        "experiment_id",
        "created_at",
        "status",
        "research_only",
        "trade_ready",
        "automatic_promotion_allowed",
        "fresh_historical_holdout",
        "historical_evidence_consumed",
        "selected_pool_readiness_claim_allowed",
        "iteration_semantics",
        "lineage",
        "objective",
        "frozen_signal",
        "frozen_risk_model",
        "frozen_constraint_recipes",
        "candidate_recipes",
        "parameter_perturbations",
        "robustness_tests",
        "selection_gate",
        "evidence",
        "stop_rules",
    ):
        merged[key] = copy.deepcopy(overlay[key])
    recipe_ids = [str(row["id"]) for row in merged["candidate_recipes"]]
    if len(recipe_ids) != len(set(recipe_ids)):
        raise ValueError("CN_27 V1.3 staggered recipe IDs must be unique")
    return replace(base, spec=merged, spec_path=spec_path)


def _combine_json_weights(
    payloads: Sequence[str],
    capital_weights: np.ndarray,
) -> dict[str, float]:
    combined: dict[str, float] = {}
    for payload, capital_weight in zip(payloads, capital_weights, strict=True):
        for symbol, weight in json.loads(str(payload)).items():
            combined[symbol] = combined.get(symbol, 0.0) + float(capital_weight) * float(weight)
    return {symbol: weight for symbol, weight in combined.items() if weight > 1e-12}


def combine_sleeve_results(
    results: Sequence[DiscoveryBacktestResult],
    contract: CN27DiscoveryContract,
    *,
    recipe_id: str,
    compute_metrics: bool = True,
) -> DiscoveryBacktestResult:
    if not results:
        raise ValueError("at least one sleeve result is required")
    calendar = results[0].daily.index
    if any(not result.daily.index.equals(calendar) for result in results[1:]):
        raise ValueError("all sleeves must use the same calendar")
    sleeve_values = np.full(len(results), 1.0 / len(results), dtype=float)
    combined_equity = 1.0
    rows: list[dict[str, object]] = []
    for date in calendar:
        start_weights = sleeve_values / sleeve_values.sum()
        day = [result.daily.loc[date] for result in results]
        gross_return = float(
            sum(weight * float(row["gross_return"]) for weight, row in zip(start_weights, day))
        )
        cost = float(
            sum(weight * float(row["transaction_cost"]) for weight, row in zip(start_weights, day))
        )
        turnover = float(
            sum(weight * float(row["one_way_turnover"]) for weight, row in zip(start_weights, day))
        )
        sleeve_values *= np.asarray([1.0 + float(row["net_return"]) for row in day])
        end_weights = sleeve_values / sleeve_values.sum()
        previous_equity = combined_equity
        combined_equity = float(sleeve_values.sum())
        net_return = combined_equity / previous_equity - 1.0
        return_weights = _combine_json_weights(
            [str(row["return_weights"]) for row in day], start_weights
        )
        asset_weights = _combine_json_weights(
            [str(row["asset_weights"]) for row in day], end_weights
        )
        equity_exposure = sum(
            float(asset_weights.get(symbol, 0.0)) for symbol in contract.candidate_symbols
        )
        holdings = sorted(
            symbol
            for symbol in contract.candidate_symbols
            if float(asset_weights.get(symbol, 0.0)) > 1e-8
        )
        rows.append(
            {
                "date": date,
                "gross_return": gross_return,
                "transaction_cost": cost,
                "net_return": net_return,
                "equity": combined_equity,
                "one_way_turnover": turnover,
                "equity_exposure": equity_exposure,
                "etf_weight": float(asset_weights.get(contract.defensive_symbol, 0.0)),
                "cash_weight": float(asset_weights.get("CASH", 0.0)),
                "holding_count": len(holdings),
                "holdings": json.dumps(holdings, ensure_ascii=False),
                "return_weights": json.dumps(return_weights, sort_keys=True),
                "asset_weights": json.dumps(asset_weights, sort_keys=True),
                "target_drift_due_to_trade_lock": float(
                    sum(
                        weight * float(row["target_drift_due_to_trade_lock"])
                        for weight, row in zip(end_weights, day)
                    )
                ),
                "pending_execution": any(bool(row["pending_execution"]) for row in day),
            }
        )
        if abs(net_return - (gross_return - cost)) > 1e-10:
            raise ValueError("staggered sleeve accounting does not reconcile")
    daily = pd.DataFrame(rows).set_index("date")
    fold_ids = tuple(str(row["id"]) for row in contract.spec["evaluation"]["chronological_folds"])
    return DiscoveryBacktestResult(
        recipe_id=recipe_id,
        daily=daily,
        metrics_by_window=(
            {
                name: _window_metrics(daily, contract, name)
                for name in ("development", *fold_ids)
            }
            if compute_metrics
            else {}
        ),
    )


def run_staggered_recipe(
    bars: pd.DataFrame,
    features: pd.DataFrame,
    contract: CN27DiscoveryContract,
    recipe: Mapping[str, object],
    *,
    cost_multiplier: float = 1.0,
    execution_delay_sessions: int = 1,
    global_phase_offset: int = 0,
    excluded_sectors: frozenset[str] = frozenset(),
    constraint_override: Mapping[str, object] | None = None,
    scored_features: pd.DataFrame | None = None,
) -> DiscoveryBacktestResult:
    constraint_id = str(recipe["constraint_id"])
    base_constraint = dict(contract.spec["frozen_constraint_recipes"][constraint_id])
    if constraint_override:
        base_constraint.update(constraint_override)
    base_constraint["id"] = str(recipe["id"])
    period = int(contract.spec["frozen_signal"]["rebalance_sessions"])
    sleeves = [
        run_v1_3_discovery_recipe(
            bars,
            features,
            contract,
            base_constraint,
            cost_multiplier=cost_multiplier,
            execution_delay_sessions=execution_delay_sessions,
            rebalance_phase_offset=(int(offset) + global_phase_offset) % period,
            excluded_sectors=excluded_sectors,
            scored_features=scored_features,
        )
        for offset in recipe["sleeve_offsets"]
    ]
    return combine_sleeve_results(sleeves, contract, recipe_id=str(recipe["id"]))


def run_staggered_discovery_screen(
    contract_path: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    contract = load_staggered_discovery_contract(contract_path)
    bars = pd.read_csv(contract.prices_path, dtype={"symbol": str}, parse_dates=["date"])
    features = compute_v1_2_features(bars, contract)
    scoring_recipe = {**contract.spec["frozen_signal"], "id": "frozen_v1_2_signal"}
    scored, _ = score_v1_2_features(features, scoring_recipe, contract)
    fold_ids = tuple(str(row["id"]) for row in contract.spec["evaluation"]["chronological_folds"])
    sectors = sorted({str(row["sector"]) for row in contract.pool["symbols"]})
    robustness = contract.spec["robustness_tests"]
    bootstrap_policy = robustness["block_bootstrap"]
    parameter_policy = contract.spec["parameter_perturbations"]
    risk_model = contract.spec["frozen_risk_model"]
    gate = contract.spec["selection_gate"]
    sleeve_cache: dict[str, DiscoveryBacktestResult] = {}

    def execute(
        recipe: Mapping[str, object],
        *,
        constraint_override: Mapping[str, object] | None = None,
        cost_multiplier: float = 1.0,
        delay: int = 1,
        global_phase: int = 0,
        excluded: frozenset[str] = frozenset(),
    ) -> DiscoveryBacktestResult:
        constraint_id = str(recipe["constraint_id"])
        constraint = dict(contract.spec["frozen_constraint_recipes"][constraint_id])
        if constraint_override:
            constraint.update(constraint_override)
        constraint["id"] = constraint_id
        period = int(contract.spec["frozen_signal"]["rebalance_sessions"])
        sleeves: list[DiscoveryBacktestResult] = []
        for offset in recipe["sleeve_offsets"]:
            phase = (int(offset) + global_phase) % period
            key = json.dumps(
                {
                    "constraint": constraint,
                    "cost_multiplier": cost_multiplier,
                    "delay": delay,
                    "phase": phase,
                    "excluded": sorted(excluded),
                },
                sort_keys=True,
            )
            if key not in sleeve_cache:
                sleeve_cache[key] = run_v1_3_discovery_recipe(
                    bars,
                    features,
                    contract,
                    constraint,
                    cost_multiplier=cost_multiplier,
                    execution_delay_sessions=delay,
                    rebalance_phase_offset=phase,
                    excluded_sectors=excluded,
                    scored_features=scored,
                )
            sleeves.append(sleeve_cache[key])
        return combine_sleeve_results(sleeves, contract, recipe_id=str(recipe["id"]))

    rows: list[dict[str, Any]] = []
    parameter_rows: list[dict[str, Any]] = []
    sector_rows: list[dict[str, Any]] = []
    results: dict[str, DiscoveryBacktestResult] = {}
    audits: dict[str, tuple[pd.DataFrame, dict[str, float]]] = {}
    attributions: dict[str, tuple[pd.DataFrame, dict[str, Any]]] = {}
    bootstraps: dict[str, dict[str, Any]] = {}
    for recipe in contract.spec["candidate_recipes"]:
        recipe_id = str(recipe["id"])
        constraint = dict(
            contract.spec["frozen_constraint_recipes"][str(recipe["constraint_id"])]
        )
        base = execute(recipe)
        stress = execute(recipe, cost_multiplier=float(robustness["cost_multiplier"]))
        delayed = execute(recipe, delay=int(robustness["execution_delay_sessions"]))
        phase_sharpes = {
            "0": float(base.metrics_by_window["development"]["sharpe_log_excess"])
        }
        for phase in robustness["global_phase_offsets"]:
            phase_result = execute(recipe, global_phase=int(phase))
            phase_sharpes[str(phase)] = float(
                phase_result.metrics_by_window["development"]["sharpe_log_excess"]
            )
        parameter_sharpes = [float(base.metrics_by_window["development"]["sharpe_log_excess"])]
        parameter_drawdowns = [abs(float(base.metrics_by_window["development"]["maximum_drawdown"]))]
        parameter_rows.append(
            {
                "recipe_id": recipe_id,
                "variant": "base",
                "sharpe_log_excess": parameter_sharpes[-1],
                "maximum_drawdown_magnitude": parameter_drawdowns[-1],
            }
        )
        for label, variant in _parameter_variants(constraint, risk_model, parameter_policy):
            variant_result = execute(recipe, constraint_override=variant)
            metrics = variant_result.metrics_by_window["development"]
            parameter_sharpes.append(float(metrics["sharpe_log_excess"]))
            parameter_drawdowns.append(abs(float(metrics["maximum_drawdown"])))
            parameter_rows.append(
                {
                    "recipe_id": recipe_id,
                    "variant": label,
                    "sharpe_log_excess": parameter_sharpes[-1],
                    "maximum_drawdown_magnitude": parameter_drawdowns[-1],
                }
            )
        sector_sharpes: list[float] = []
        for sector in sectors:
            sector_result = execute(recipe, excluded=frozenset({sector}))
            metrics = sector_result.metrics_by_window["development"]
            sector_sharpes.append(float(metrics["sharpe_log_excess"]))
            sector_rows.append(
                {
                    "recipe_id": recipe_id,
                    "excluded_sector": sector,
                    "sharpe_log_excess": sector_sharpes[-1],
                    "maximum_drawdown": float(metrics["maximum_drawdown"]),
                    "annual_one_way_turnover": float(metrics["annual_one_way_turnover"]),
                }
            )
        bootstrap = _block_bootstrap_sharpe(
            base.daily["net_return"],
            samples=int(bootstrap_policy["samples"]),
            block_sessions=int(bootstrap_policy["block_sessions"]),
            seed=int(bootstrap_policy["seed"]),
        )
        audit = concentration_audit(base.daily, contract)
        attribution = contribution_attribution(base.daily, bars, contract)
        full = base.metrics_by_window["development"]
        fold_sharpes = [
            float(base.metrics_by_window[fold]["sharpe_log_excess"]) for fold in fold_ids
        ]
        double_cost_sharpe = float(
            stress.metrics_by_window["development"]["sharpe_log_excess"]
        )
        delay_sharpe = float(delayed.metrics_by_window["development"]["sharpe_log_excess"])
        concentration_summary = audit[1]
        attribution_summary = attribution[1]
        rows.append(
            {
                "recipe_id": recipe_id,
                "constraint_id": str(recipe["constraint_id"]),
                "sleeve_count": len(recipe["sleeve_offsets"]),
                "full_total_return": float(full["total_return"]),
                "full_cagr": float(full["cagr"]),
                "full_annual_volatility": float(full["annual_volatility"]),
                "full_sharpe_log_excess": float(full["sharpe_log_excess"]),
                "full_maximum_drawdown": float(full["maximum_drawdown"]),
                "full_annual_one_way_turnover": float(full["annual_one_way_turnover"]),
                "full_transaction_cost_paid": float(full["transaction_cost_paid"]),
                "double_cost_full_sharpe": double_cost_sharpe,
                "delay_two_full_sharpe": delay_sharpe,
                "phase_sharpes": json.dumps(phase_sharpes, sort_keys=True),
                "worst_timing_perturbation_sharpe": min(delay_sharpe, *phase_sharpes.values()),
                "fold_sharpes": json.dumps(fold_sharpes),
                "fold_sharpe_25th_percentile": float(np.quantile(fold_sharpes, 0.25)),
                "positive_fold_share": float(np.mean(np.asarray(fold_sharpes) > 0.0)),
                "bootstrap_sharpe_percentile_05": float(bootstrap["sharpe_percentile_05"]),
                "bootstrap_probability_sharpe_above_zero": float(
                    bootstrap["probability_sharpe_above_zero"]
                ),
                "bootstrap_probability_sharpe_above_one": float(
                    bootstrap["probability_sharpe_above_one"]
                ),
                "parameter_neighborhood_minimum_sharpe": min(parameter_sharpes),
                "parameter_neighborhood_median_sharpe": float(np.median(parameter_sharpes)),
                "parameter_neighborhood_maximum_drawdown_magnitude": max(parameter_drawdowns),
                "leave_one_sector_out_minimum_sharpe": min(sector_sharpes),
                "leave_one_sector_out_median_sharpe": float(np.median(sector_sharpes)),
                **concentration_summary,
                "maximum_single_name_positive_contribution_share": float(
                    attribution_summary["maximum_single_name_positive_contribution_share"]
                ),
                "maximum_single_sector_positive_contribution_share": float(
                    attribution_summary["maximum_single_sector_positive_contribution_share"]
                ),
            }
        )
        results[recipe_id] = base
        audits[recipe_id] = audit
        attributions[recipe_id] = attribution
        bootstraps[recipe_id] = bootstrap

    summary = pd.DataFrame(rows)
    failures_by_recipe: dict[str, list[str]] = {}
    parameter_policy = contract.spec["parameter_perturbations"]
    for index, row in summary.iterrows():
        checks = (
            (float(row["full_annual_one_way_turnover"]) <= float(gate["maximum_full_window_annual_one_way_turnover"]), "turnover"),
            (abs(float(row["full_maximum_drawdown"])) <= float(gate["maximum_full_window_drawdown_magnitude"]), "drawdown"),
            (float(row["full_sharpe_log_excess"]) >= float(gate["minimum_full_window_sharpe_log_excess"]), "full_sharpe"),
            (float(row["double_cost_full_sharpe"]) >= float(gate["minimum_double_cost_full_window_sharpe_log_excess"]), "double_cost_sharpe"),
            (float(row["positive_fold_share"]) >= float(gate["minimum_positive_fold_share"]), "positive_fold_share"),
            (float(row["fold_sharpe_25th_percentile"]) >= float(gate["minimum_fold_sharpe_25th_percentile"]), "fold_sharpe_25th_percentile"),
            (float(row["worst_timing_perturbation_sharpe"]) >= float(gate["minimum_worst_timing_perturbation_sharpe"]), "timing_perturbation_sharpe"),
            (float(row["bootstrap_sharpe_percentile_05"]) >= float(gate["minimum_bootstrap_sharpe_percentile_05"]), "bootstrap_p05"),
            (float(row["bootstrap_probability_sharpe_above_zero"]) >= float(gate["minimum_bootstrap_probability_sharpe_above_zero"]), "bootstrap_probability_above_zero"),
            (float(row["bootstrap_probability_sharpe_above_one"]) >= float(gate["minimum_bootstrap_probability_sharpe_above_one"]), "bootstrap_probability_above_one"),
            (float(row["parameter_neighborhood_minimum_sharpe"]) >= float(parameter_policy["minimum_neighborhood_sharpe"]), "parameter_minimum_sharpe"),
            (float(row["parameter_neighborhood_maximum_drawdown_magnitude"]) <= float(parameter_policy["maximum_neighborhood_drawdown_magnitude"]), "parameter_drawdown"),
            (float(row["maximum_post_drift_single_equity_sleeve_share"]) <= float(gate["maximum_post_drift_single_equity_sleeve_share"]), "post_drift_single_share"),
            (float(row["maximum_post_drift_sector_equity_sleeve_share"]) <= float(gate["maximum_post_drift_sector_equity_sleeve_share"]), "post_drift_sector_share"),
            (float(row["post_drift_sector_share_p95"]) <= float(gate["maximum_post_drift_sector_share_p95"]), "post_drift_sector_p95"),
            (float(row["post_drift_effective_names_median"]) >= float(gate["minimum_post_drift_effective_names_median"]), "effective_names_median"),
            (float(row["post_drift_effective_names_p05"]) >= float(gate["minimum_post_drift_effective_names_p05"]), "effective_names_p05"),
            (float(row["maximum_single_name_positive_contribution_share"]) <= float(gate["maximum_single_name_positive_contribution_share"]), "name_contribution"),
            (float(row["maximum_single_sector_positive_contribution_share"]) <= float(gate["maximum_single_sector_positive_contribution_share"]), "sector_contribution"),
            (float(row["leave_one_sector_out_minimum_sharpe"]) >= float(gate["minimum_leave_one_sector_out_sharpe"]), "leave_one_sector_minimum_sharpe"),
            (float(row["leave_one_sector_out_median_sharpe"]) >= float(gate["minimum_leave_one_sector_out_median_sharpe"]), "leave_one_sector_median_sharpe"),
        )
        failures = [name for passed, name in checks if not passed]
        summary.loc[index, "minimum_robustness_score"] = min(
            float(row["double_cost_full_sharpe"]),
            float(row["worst_timing_perturbation_sharpe"]),
            float(row["bootstrap_sharpe_percentile_05"]),
            float(row["parameter_neighborhood_minimum_sharpe"]),
            float(row["leave_one_sector_out_minimum_sharpe"]),
        )
        summary.loc[index, "selection_gate_passed"] = not failures
        summary.loc[index, "failure_reasons"] = "+".join(failures)
        failures_by_recipe[str(row["recipe_id"])] = failures
    summary["selection_gate_passed"] = summary["selection_gate_passed"].astype(bool)
    summary = summary.sort_values(
        [
            "selection_gate_passed",
            "minimum_robustness_score",
            "leave_one_sector_out_minimum_sharpe",
            "full_maximum_drawdown",
            "full_annual_one_way_turnover",
            "recipe_id",
        ],
        ascending=[False, False, False, False, True, True],
    ).reset_index(drop=True)
    passing = summary.loc[summary["selection_gate_passed"]]
    selected_id = str(passing.iloc[0]["recipe_id"]) if not passing.empty else None
    selected_recipe = next(
        (dict(row) for row in contract.spec["candidate_recipes"] if row["id"] == selected_id),
        None,
    )
    decision_name = (
        "retrospective_staggered_candidate_identified"
        if selected_id is not None
        else "no_staggered_candidate_passed_frozen_gate"
    )
    selection: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": str(contract.spec["experiment_id"]),
        "decision": decision_name,
        "selected_recipe_id": selected_id,
        "selected_recipe": selected_recipe,
        "frozen_constraint_recipe": (
            dict(contract.spec["frozen_constraint_recipes"][str(selected_recipe["constraint_id"])])
            if selected_recipe is not None
            else None
        ),
        "frozen_risk_model": dict(risk_model),
        "historical_evidence_consumed": True,
        "fresh_historical_holdout": False,
        "automatic_promotion_allowed": False,
        "research_only": True,
        "trade_ready": False,
    }
    selection["selection_identity_sha256"] = canonical_sha256(selection)
    output = (
        (contract.spec_path.parents[2] / str(contract.spec["evidence"]["output_dir"])).resolve()
        if output_dir is None
        else Path(output_dir).resolve()
    )
    output.mkdir(parents=True, exist_ok=True)
    summary.to_csv(output / "candidate_summary.csv", index=False)
    pd.DataFrame(parameter_rows).to_csv(output / "parameter_robustness.csv", index=False)
    pd.DataFrame(sector_rows).to_csv(output / "leave_one_sector_out.csv", index=False)
    write_json(output / "selected_recipe.json", selection)
    if selected_id is not None:
        selected = results[selected_id]
        selected.daily.reset_index().to_csv(
            output / "selected_daily.csv", index=False, date_format="%Y-%m-%d"
        )
        audits[selected_id][0].reset_index().to_csv(
            output / "concentration_audit.csv", index=False, date_format="%Y-%m-%d"
        )
        attributions[selected_id][0].to_csv(
            output / "attribution.csv", index=False, date_format="%Y-%m-%d"
        )
        write_json(output / "attribution_summary.json", attributions[selected_id][1])
        selected_bootstrap = bootstraps[selected_id]
    else:
        pd.DataFrame(columns=["date"]).to_csv(output / "selected_daily.csv", index=False)
        pd.DataFrame(columns=["date"]).to_csv(output / "concentration_audit.csv", index=False)
        pd.DataFrame(columns=["date"]).to_csv(output / "attribution.csv", index=False)
        write_json(output / "attribution_summary.json", {"available": False})
        selected_bootstrap = {"available": False, "reason": "no candidate passed frozen gate"}
    write_json(output / "bootstrap.json", selected_bootstrap)
    decision = {
        "schema_version": "1.0",
        "decision": decision_name,
        "selected_recipe_id": selected_id,
        "all_selection_gates_passed": selected_id is not None,
        "failure_reasons_by_recipe": failures_by_recipe,
        "fresh_historical_holdout": False,
        "prospective_validation_required": True,
        "automatic_promotion_allowed": False,
        "research_only": True,
        "trade_ready": False,
    }
    write_json(output / "decision.json", decision)
    leader = summary.iloc[0]
    report = "\n".join(
        [
            "# CN_27 V1.3 staggered-sleeve discovery",
            "",
            f"- Decision: `{decision_name}`",
            f"- Selected recipe: `{selected_id}`",
            "- Internal sleeve order netting: `false` (conservative cost treatment)",
            "- Fresh historical holdout: `false`",
            "- Research only: `true`; trade ready: `false`",
            "",
            "## Frozen-gate leader",
            "",
            f"- Recipe: `{leader['recipe_id']}`",
            f"- Sleeves: {int(leader['sleeve_count'])}",
            f"- Full-window Sharpe: {float(leader['full_sharpe_log_excess']):.4f}",
            f"- Maximum drawdown: {float(leader['full_maximum_drawdown']):.2%}",
            f"- Bootstrap Sharpe p05: {float(leader['bootstrap_sharpe_percentile_05']):.4f}",
            f"- Worst timing Sharpe: {float(leader['worst_timing_perturbation_sharpe']):.4f}",
            f"- Maximum post-drift sector share: {float(leader['maximum_post_drift_sector_equity_sleeve_share']):.2%}",
            f"- Median effective names: {float(leader['post_drift_effective_names_median']):.2f}",
            f"- Leave-one-sector minimum Sharpe: {float(leader['leave_one_sector_out_minimum_sharpe']):.4f}",
            "",
            "## Interpretation boundary",
            "",
            "This fifth-order retrospective test uses fully consumed history. It can nominate",
            "a formal research-only V1.3 candidate, but cannot create fresh validation, authorize",
            "promotion, or support live trading.",
        ]
    )
    (output / "report.md").write_text(report + "\n", encoding="utf-8")
    output_names = [
        name for name in contract.spec["evidence"]["expected_outputs"]
        if name != "evidence_manifest.json"
    ]
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": str(contract.spec["experiment_id"]),
        "identity": {
            "contract_sha256": sha256_file(contract.spec_path),
            "pool_sha256": sha256_file(contract.pool_path),
            "source_prices_sha256": sha256_file(contract.prices_path),
            "concentration_manifest_file_sha256": str(
                contract.spec["lineage"]["concentration_manifest_file_sha256"]
            ),
            "implementation_sha256": sha256_file(Path(__file__)),
        },
        "outputs": {name: sha256_file(output / name) for name in output_names},
        "selection_identity_sha256": selection["selection_identity_sha256"],
        "decision": decision_name,
        "research_only": True,
        "trade_ready": False,
    }
    manifest["manifest_identity_sha256"] = canonical_sha256(manifest)
    write_json(output / "evidence_manifest.json", manifest)
    return {
        "decision": decision_name,
        "selected_recipe_id": selected_id,
        "leader": leader.to_dict(),
        "bootstrap": selected_bootstrap,
        "manifest_identity_sha256": manifest["manifest_identity_sha256"],
        "research_only": True,
        "trade_ready": False,
    }
