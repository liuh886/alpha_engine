"""Final evidence and pseudo-walk-forward audit for frozen CN_27 V1.2."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from src.research.all_weather_alpha_rotation import (
    _return_metrics,
    canonical_sha256,
    normalise_long_bars,
    sha256_file,
)
from src.research.cn27_sharpe_discovery import CN27DiscoveryContract, write_json
from src.research.cn27_v1_2 import (
    compute_v1_2_features,
    execute_target_with_deferral,
    load_v1_3_contract,
    run_robustness_recipe,
    score_v1_2_features,
)


@dataclass(frozen=True)
class CN27V12FinalContract:
    spec: dict[str, Any]
    spec_path: Path
    discovery: CN27DiscoveryContract
    selected_recipe: dict[str, Any]
    root: Path


def _verify_manifest(path: Path, expected_identity: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = dict(payload)
    identity = str(body.pop("manifest_identity_sha256", ""))
    if canonical_sha256(body) != identity or identity != expected_identity:
        raise ValueError(f"manifest identity mismatch: {path}")
    for name, expected in payload["outputs"].items():
        if sha256_file(path.parent / name) != expected:
            raise ValueError(f"manifest output hash mismatch: {name}")
    return payload


def load_cn27_v1_2_final_contract(path: str | Path) -> CN27V12FinalContract:
    spec_path = Path(path).resolve()
    root = spec_path.parents[2]
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict) or spec.get("status") != "frozen_retrospective_candidate":
        raise ValueError("CN_27 V1.2 final contract must be frozen")
    if spec.get("research_only") is not True or spec.get("trade_ready") is not False:
        raise ValueError("CN_27 V1.2 final contract must remain research-only")
    lineage = spec["lineage"]
    for prefix in ("robustness_discovery", "stability_discovery"):
        contract_path = (root / str(lineage[f"{prefix}_contract"])).resolve()
        manifest_path = (root / str(lineage[f"{prefix}_manifest"])).resolve()
        if sha256_file(contract_path) != str(lineage[f"{prefix}_contract_sha256"]):
            raise ValueError(f"{prefix} contract hash mismatch")
        if sha256_file(manifest_path) != str(lineage[f"{prefix}_manifest_file_sha256"]):
            raise ValueError(f"{prefix} manifest file hash mismatch")
        _verify_manifest(
            manifest_path,
            expected_identity=str(lineage[f"{prefix}_manifest_identity_sha256"]),
        )
    stability_path = (root / str(lineage["stability_discovery_contract"])).resolve()
    discovery = load_v1_3_contract(stability_path)
    selection_path = (
        root / str(lineage["stability_discovery_manifest"])
    ).resolve().parent / "selected_recipe.json"
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if selection["selection_identity_sha256"] != str(
        lineage["sealed_selection_identity_sha256"]
    ):
        raise ValueError("CN_27 V1.2 selection identity mismatch")
    recipe = dict(selection["selected_recipe"])
    expected_factors = {
        str(key): float(value) for key, value in spec["factor_model"]["combination"].items()
    }
    if recipe["factors"] != expected_factors:
        raise ValueError("CN_27 V1.2 factor combination differs from sealed selection")
    portfolio_mapping = {
        "rebalance_sessions": "rebalance_sessions",
        "top_k": "top_k",
        "exit_rank_buffer": "exit_rank_buffer",
        "maximum_names_per_sector": "maximum_names_per_sector",
        "weighting": "weighting",
        "equity_exposure": "equity_exposure",
        "absolute_momentum_filter": "absolute_momentum_filter",
    }
    for recipe_key, contract_key in portfolio_mapping.items():
        if recipe[recipe_key] != spec["portfolio"][contract_key]:
            raise ValueError(f"CN_27 V1.2 portfolio mismatch: {recipe_key}")
    return CN27V12FinalContract(
        spec=spec,
        spec_path=spec_path,
        discovery=discovery,
        selected_recipe=recipe,
        root=root,
    )


def select_walk_forward_recipe(
    candidate_metrics: Mapping[str, Mapping[str, Mapping[str, float]]],
    training_folds: tuple[str, ...],
) -> tuple[str, pd.DataFrame]:
    """Rank a frozen recipe menu using prior folds only."""

    rows: list[dict[str, Any]] = []
    for recipe_id, fold_metrics in candidate_metrics.items():
        sharpes = [float(fold_metrics[fold]["sharpe_log_excess"]) for fold in training_folds]
        turnovers = [
            float(fold_metrics[fold]["annual_one_way_turnover"]) for fold in training_folds
        ]
        rows.append(
            {
                "recipe_id": str(recipe_id),
                "minimum_prior_fold_sharpe": min(sharpes),
                "median_prior_fold_sharpe": float(np.median(sharpes)),
                "mean_prior_fold_turnover": float(np.mean(turnovers)),
            }
        )
    ranking = pd.DataFrame(rows).sort_values(
        [
            "minimum_prior_fold_sharpe",
            "median_prior_fold_sharpe",
            "mean_prior_fold_turnover",
            "recipe_id",
        ],
        ascending=[False, False, True, True],
    ).reset_index(drop=True)
    return str(ranking.iloc[0]["recipe_id"]), ranking


def contribution_attribution_v1_2(
    daily: pd.DataFrame,
    bars: pd.DataFrame,
    contract: CN27V12FinalContract,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    clean = normalise_long_bars(bars)
    calendar = pd.DatetimeIndex(daily.index)
    discovery = contract.discovery
    assets = (*discovery.candidate_symbols, discovery.defensive_symbol)
    open_returns = {
        symbol: clean.loc[clean["symbol"].eq(symbol)].set_index("date")["open"]
        .reindex(calendar)
        .ffill()
        .pct_change(fill_method=None)
        .fillna(0.0)
        for symbol in assets
    }
    sectors = {
        str(row["symbol"]).zfill(6): str(row["sector"])
        for row in discovery.pool["symbols"]
    }
    rows: list[dict[str, Any]] = []
    for date, daily_row in daily.iterrows():
        weights = json.loads(str(daily_row["return_weights"]))
        for symbol, weight in weights.items():
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "sector": sectors.get(symbol, "defensive_etf"),
                    "return_weight": float(weight),
                    "open_return": float(open_returns[symbol].loc[date]),
                    "gross_contribution": float(weight) * float(open_returns[symbol].loc[date]),
                }
            )
    attribution = pd.DataFrame(rows)
    reconciled = (
        attribution.groupby("date")["gross_contribution"].sum().reindex(calendar).fillna(0.0)
    )
    difference = reconciled - daily["gross_return"]
    if float(difference.abs().max()) > 1e-10:
        raise ValueError("CN_27 V1.2 attribution does not reconcile")
    stocks = attribution.loc[attribution["symbol"].isin(discovery.candidate_symbols)]
    name_positive = stocks.groupby("symbol")["gross_contribution"].sum().clip(lower=0.0)
    sector_positive = stocks.groupby("sector")["gross_contribution"].sum().clip(lower=0.0)
    name_total = float(name_positive.sum())
    sector_total = float(sector_positive.sum())
    summary = {
        "maximum_daily_reconciliation_error": float(difference.abs().max()),
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
    return attribution, summary


def _metrics_from_daily(daily: pd.DataFrame) -> dict[str, Any]:
    metrics = _return_metrics(
        daily["net_return"],
        annual_sessions=252,
        annual_risk_free_rate=0.02,
    )
    metrics["annual_one_way_turnover"] = float(
        daily["one_way_turnover"].sum() / (len(daily) / 252.0)
    )
    metrics["transaction_cost_paid"] = float(daily["transaction_cost"].sum())
    if "equity_exposure" in daily:
        metrics["average_equity_exposure"] = float(daily["equity_exposure"].mean())
    if "holding_count" in daily:
        metrics["average_holding_count"] = float(daily["holding_count"].mean())
    return metrics


def _candidate_paths(
    bars: pd.DataFrame,
    features: pd.DataFrame,
    discovery: CN27DiscoveryContract,
) -> dict[str, Any]:
    fold_ids = tuple(
        str(row["id"]) for row in discovery.spec["evaluation"]["chronological_folds"]
    )
    window_names = ("development", *fold_ids)
    score_cache: dict[str, pd.DataFrame] = {}
    paths: dict[str, Any] = {}
    for recipe in discovery.spec["candidate_recipes"]:
        definition = json.dumps(
            {
                "mode": recipe["factor_mode"],
                "factors": recipe.get("factors", recipe.get("factor_pool", [])),
            },
            sort_keys=True,
        )
        if definition not in score_cache:
            score_cache[definition] = score_v1_2_features(
                features, recipe, discovery
            )[0]
        paths[str(recipe["id"])] = run_robustness_recipe(
            bars,
            features,
            discovery,
            recipe,
            end_date=str(discovery.spec["evaluation"]["full_window"]["end"]),
            window_names=window_names,
            scored_features=score_cache[definition],
        )
    return paths


def expanding_walk_forward_audit(
    bars: pd.DataFrame,
    features: pd.DataFrame,
    contract: CN27V12FinalContract,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Select on prior folds and stitch the next-fold path with switch costs."""

    discovery = contract.discovery
    paths = _candidate_paths(bars, features, discovery)
    candidate_metrics = {
        recipe_id: result.metrics_by_window for recipe_id, result in paths.items()
    }
    fold_specs = {
        str(row["id"]): row for row in discovery.spec["evaluation"]["chronological_folds"]
    }
    validation_folds = [str(value) for value in contract.spec["walk_forward_audit"]["validation_folds"]]
    ordered_folds = list(fold_specs)
    clean = normalise_long_bars(bars)
    assets = (*discovery.candidate_symbols, discovery.defensive_symbol)
    calendar = pd.DatetimeIndex(
        clean.loc[clean["symbol"].eq(discovery.defensive_symbol), "date"]
        .drop_duplicates()
        .sort_values()
    )
    open_returns = {
        symbol: clean.loc[clean["symbol"].eq(symbol)].set_index("date")["open"]
        .reindex(calendar)
        .ffill()
        .pct_change(fill_method=None)
        .fillna(0.0)
        for symbol in assets
    }
    observed = {
        symbol: pd.Series(calendar.isin(clean.loc[clean["symbol"].eq(symbol), "date"]), index=calendar)
        for symbol in assets
    }
    locked = {
        symbol: pd.Series(
            np.isclose(item["high"], item["low"], rtol=0.0, atol=1e-12),
            index=item["date"],
        )
        .groupby(level=0)
        .last()
        .reindex(calendar)
        .fillna(False)
        for symbol in assets
        for item in [clean.loc[clean["symbol"].eq(symbol)].sort_values("date")]
    }
    cost_spec = {
        "stock_buy_rate": float(contract.spec["costs"]["stock_buy_rate"]),
        "stock_sell_rate": float(contract.spec["costs"]["stock_sell_rate"]),
        "etf_buy_rate": float(contract.spec["costs"]["etf_buy_rate"]),
        "etf_sell_rate": float(contract.spec["costs"]["etf_sell_rate"]),
    }
    previous_weights = {symbol: 0.0 for symbol in assets}
    previous_weights[discovery.defensive_symbol] = 1.0
    previous_weights["CASH"] = 0.0
    stitched_frames: list[pd.DataFrame] = []
    selections: list[dict[str, Any]] = []
    total_equity = 1.0

    for validation_fold in validation_folds:
        position = ordered_folds.index(validation_fold)
        training_folds = tuple(ordered_folds[:position])
        selected_id, ranking = select_walk_forward_recipe(candidate_metrics, training_folds)
        fold = fold_specs[validation_fold]
        candidate_sample = paths[selected_id].daily.loc[
            str(fold["start"]) : str(fold["end"])
        ]
        fold_rows: list[dict[str, Any]] = []
        active_target: dict[str, float] | None = None
        transition_cost = 0.0
        transition_turnover = 0.0
        for offset, (date, candidate_row) in enumerate(candidate_sample.iterrows()):
            relatives = {
                symbol: 1.0 + float(open_returns[symbol].loc[date]) for symbol in assets
            }
            gross_return = sum(
                float(previous_weights[symbol]) * (relatives[symbol] - 1.0)
                for symbol in assets
            )
            gross_factor = 1.0 + gross_return
            before = {
                symbol: float(previous_weights[symbol]) * relatives[symbol] / gross_factor
                for symbol in assets
            }
            before["CASH"] = float(previous_weights["CASH"]) / gross_factor
            if offset == 0 or float(candidate_row["one_way_turnover"]) > 1e-12:
                desired_raw = json.loads(str(candidate_row["asset_weights"]))
                active_target = {
                    symbol: float(desired_raw.get(symbol, 0.0)) for symbol in assets
                }
                active_target["CASH"] = max(0.0, 1.0 - sum(active_target.values()))
            if active_target is not None:
                tradable = {
                    symbol: bool(observed[symbol].loc[date])
                    and not bool(locked[symbol].loc[date])
                    for symbol in assets
                }
                after, cost, turnover, pending, target_drift = execute_target_with_deferral(
                    before,
                    active_target,
                    tradable,
                    candidate_symbols=discovery.candidate_symbols,
                    defensive_symbol=discovery.defensive_symbol,
                    cost_spec=cost_spec,
                )
                if not pending:
                    active_target = None
            else:
                after = before
                cost, turnover, target_drift = 0.0, 0.0, 0.0
            if offset == 0:
                transition_cost = float(cost)
                transition_turnover = float(turnover)
            net_return = gross_return - cost
            total_equity *= 1.0 + net_return
            holdings = sorted(
                symbol for symbol in discovery.candidate_symbols if after[symbol] > 1e-8
            )
            fold_rows.append(
                {
                    "date": date,
                    "gross_return": gross_return,
                    "transaction_cost": cost,
                    "net_return": net_return,
                    "equity": total_equity,
                    "one_way_turnover": turnover,
                    "equity_exposure": sum(
                        after[symbol] for symbol in discovery.candidate_symbols
                    ),
                    "etf_weight": after[discovery.defensive_symbol],
                    "cash_weight": after["CASH"],
                    "holding_count": len(holdings),
                    "holdings": json.dumps(holdings, ensure_ascii=False),
                    "return_weights": json.dumps(
                        {
                            symbol: previous_weights[symbol]
                            for symbol in assets
                            if previous_weights[symbol] > 1e-12
                        },
                        sort_keys=True,
                    ),
                    "asset_weights": json.dumps(
                        {
                            symbol: after[symbol]
                            for symbol in assets
                            if after[symbol] > 1e-12
                        },
                        sort_keys=True,
                    ),
                    "target_drift_due_to_trade_lock": target_drift,
                    "pending_execution": active_target is not None,
                    "walk_forward_recipe_id": selected_id,
                    "walk_forward_validation_fold": validation_fold,
                    "walk_forward_transition": offset == 0,
                }
            )
            previous_weights = after
        sample = pd.DataFrame(fold_rows).set_index("date")
        forward_metrics = _metrics_from_daily(sample)
        top = ranking.iloc[0]
        selections.append(
            {
                "validation_fold": validation_fold,
                "training_folds": "+".join(training_folds),
                "selected_recipe_id": selected_id,
                "minimum_prior_fold_sharpe": float(top["minimum_prior_fold_sharpe"]),
                "median_prior_fold_sharpe": float(top["median_prior_fold_sharpe"]),
                "mean_prior_fold_turnover": float(top["mean_prior_fold_turnover"]),
                "forward_sharpe_log_excess": float(forward_metrics["sharpe_log_excess"]),
                "forward_annual_one_way_turnover": float(
                    forward_metrics["annual_one_way_turnover"]
                ),
                "forward_maximum_drawdown": float(forward_metrics["maximum_drawdown"]),
                "transition_cost": float(transition_cost),
                "transition_one_way_turnover": float(transition_turnover),
            }
        )
        stitched_frames.append(sample)

    stitched = pd.concat(stitched_frames).sort_index()
    stitched["equity"] = (1.0 + stitched["net_return"]).cumprod()
    selection_frame = pd.DataFrame(selections)
    metrics = _metrics_from_daily(stitched)
    metrics["positive_validation_fold_share"] = float(
        selection_frame["forward_sharpe_log_excess"].gt(0.0).mean()
    )
    metrics["validation_fold_count"] = len(selection_frame)
    metrics["total_transition_cost"] = float(selection_frame["transition_cost"].sum())
    return selection_frame, stitched, metrics


def run_cn27_v1_2_evidence(
    contract_path: str | Path,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    contract = load_cn27_v1_2_final_contract(contract_path)
    discovery = contract.discovery
    bars = pd.read_csv(discovery.prices_path, dtype={"symbol": str}, parse_dates=["date"])
    features = compute_v1_2_features(bars, discovery)
    scored, _ = score_v1_2_features(features, contract.selected_recipe, discovery)
    folds = tuple(
        str(row["id"]) for row in discovery.spec["evaluation"]["chronological_folds"]
    )
    windows = ("development", *folds)

    def execute(*, cost: float = 1.0, delay: int = 1, phase: int = 0) -> Any:
        return run_robustness_recipe(
            bars,
            features,
            discovery,
            contract.selected_recipe,
            end_date=str(discovery.spec["evaluation"]["full_window"]["end"]),
            window_names=windows,
            cost_multiplier=cost,
            execution_delay_sessions=delay,
            rebalance_phase_offset=phase,
            scored_features=scored,
        )

    primary = execute()
    double_cost = execute(cost=float(contract.spec["costs"]["stress_multiplier"]))
    delayed = execute(delay=2)
    phases = {phase: execute(phase=phase) for phase in (10, 20)}
    attribution, attribution_summary = contribution_attribution_v1_2(
        primary.daily, bars, contract
    )
    walk_selection, walk_daily, walk_metrics = expanding_walk_forward_audit(
        bars, features, contract
    )
    full = primary.metrics_by_window["development"]
    stress_full = double_cost.metrics_by_window["development"]
    fold_sharpes = [float(primary.metrics_by_window[fold]["sharpe_log_excess"]) for fold in folds]
    timing_sharpes = {
        "delay_2": float(delayed.metrics_by_window["development"]["sharpe_log_excess"]),
        **{
            f"phase_{phase}": float(result.metrics_by_window["development"]["sharpe_log_excess"])
            for phase, result in phases.items()
        },
    }
    gate = contract.spec["support_gates"]
    checks = {
        "full_window_minimum_sharpe_log_excess": float(full["sharpe_log_excess"])
        >= float(gate["full_window_minimum_sharpe_log_excess"]),
        "full_window_maximum_annual_one_way_turnover": float(
            full["annual_one_way_turnover"]
        )
        <= float(gate["full_window_maximum_annual_one_way_turnover"]),
        "full_window_maximum_drawdown_magnitude": abs(float(full["maximum_drawdown"]))
        <= float(gate["full_window_maximum_drawdown_magnitude"]),
        "double_cost_full_window_minimum_sharpe_log_excess": float(
            stress_full["sharpe_log_excess"]
        )
        >= float(gate["double_cost_full_window_minimum_sharpe_log_excess"]),
        "minimum_positive_fold_share": float(np.mean(np.asarray(fold_sharpes) > 0.0))
        >= float(gate["minimum_positive_fold_share"]),
        "minimum_fold_sharpe_25th_percentile": float(np.quantile(fold_sharpes, 0.25))
        >= float(gate["minimum_fold_sharpe_25th_percentile"]),
        "minimum_worst_timing_perturbation_sharpe": min(timing_sharpes.values())
        >= float(gate["minimum_worst_timing_perturbation_sharpe"]),
        "minimum_stable_selected_factor_share": float(
            contract.spec["factor_model"]["stability_contract"][
                "stable_selected_factor_share"
            ]
        )
        >= float(gate["minimum_stable_selected_factor_share"]),
        "maximum_single_name_positive_contribution_share": float(
            attribution_summary["maximum_single_name_positive_contribution_share"]
        )
        <= float(gate["maximum_single_name_positive_contribution_share"]),
        "maximum_single_sector_positive_contribution_share": float(
            attribution_summary["maximum_single_sector_positive_contribution_share"]
        )
        <= float(gate["maximum_single_sector_positive_contribution_share"]),
        "walk_forward_minimum_sharpe_log_excess": float(walk_metrics["sharpe_log_excess"])
        >= float(gate["walk_forward_minimum_sharpe_log_excess"]),
        "walk_forward_minimum_positive_validation_fold_share": float(
            walk_metrics["positive_validation_fold_share"]
        )
        >= float(gate["walk_forward_minimum_positive_validation_fold_share"]),
        "walk_forward_maximum_annual_one_way_turnover": float(
            walk_metrics["annual_one_way_turnover"]
        )
        <= float(gate["walk_forward_maximum_annual_one_way_turnover"]),
        "walk_forward_maximum_drawdown_magnitude": abs(
            float(walk_metrics["maximum_drawdown"])
        )
        <= float(gate["walk_forward_maximum_drawdown_magnitude"]),
    }
    passed = all(checks.values())
    decision_value = (
        "historically_supported_pending_prospective_validation"
        if passed
        else "not_supported_by_frozen_v1_2_gates"
    )
    metrics = {
        "schema_version": "1.0",
        "model_version_id": str(contract.spec["model_version_id"]),
        "full_window": full,
        "double_cost_full_window": stress_full,
        "by_fold": {fold: primary.metrics_by_window[fold] for fold in folds},
        "fold_sharpe_25th_percentile": float(np.quantile(fold_sharpes, 0.25)),
        "positive_fold_share": float(np.mean(np.asarray(fold_sharpes) > 0.0)),
        "timing_perturbation_sharpes": timing_sharpes,
        "worst_timing_perturbation_sharpe": min(timing_sharpes.values()),
        "factor_stability": contract.spec["factor_model"]["stability_contract"],
        "attribution_summary": attribution_summary,
        "walk_forward": walk_metrics,
    }
    robustness_summary = pd.read_csv(
        contract.root
        / "artifacts/evidence/cn_27_v1_2_robustness_discovery_v1/candidate_summary.csv"
    )
    stability_summary = pd.read_csv(
        contract.root
        / "artifacts/evidence/cn_27_v1_3_stability_discovery_v1/candidate_summary.csv"
    )
    comparison = {
        "schema_version": "1.0",
        "cn_27_v1_2_final": full,
        "cn_27_v1_2_robustness_leader": robustness_summary.iloc[0].to_dict(),
        "cn_27_v1_1_corrected_control": robustness_summary.loc[
            robustness_summary["recipe_id"].eq("r0_v1_1_corrected_control")
        ].iloc[0].to_dict(),
        "stability_screen_selected": stability_summary.iloc[0].to_dict(),
    }
    decision = {
        "schema_version": "1.0",
        "model_version_id": str(contract.spec["model_version_id"]),
        "decision": decision_value,
        "all_support_gates_passed": passed,
        "support_gate_results": checks,
        "fresh_historical_holdout": False,
        "prospective_validation_required": True,
        "automatic_promotion_allowed": False,
        "selected_pool_readiness_claimed": False,
        "research_only": True,
        "trade_ready": False,
    }
    output = (
        (contract.root / str(contract.spec["evidence"]["output_dir"])).resolve()
        if output_dir is None
        else Path(output_dir).resolve()
    )
    output.mkdir(parents=True, exist_ok=True)
    primary.daily.reset_index().to_csv(output / "daily.csv", index=False, date_format="%Y-%m-%d")
    double_cost.daily.reset_index().to_csv(
        output / "double_cost_daily.csv", index=False, date_format="%Y-%m-%d"
    )
    attribution.to_csv(output / "attribution.csv", index=False, date_format="%Y-%m-%d")
    walk_selection.to_csv(output / "walk_forward_selection.csv", index=False)
    walk_daily.reset_index().to_csv(
        output / "walk_forward_daily.csv", index=False, date_format="%Y-%m-%d"
    )
    write_json(output / "metrics.json", metrics)
    write_json(output / "attribution.json", attribution_summary)
    write_json(output / "comparison.json", comparison)
    write_json(output / "decision.json", decision)
    report = "\n".join(
        [
            "# CN_27 V1.2 stable-factor low-turnover evidence",
            "",
            f"- Decision: `{decision_value}`",
            "- Research only: `true`; trade ready: `false`",
            "- Fresh historical holdout: `false`",
            f"- Full-window Sharpe: {float(full['sharpe_log_excess']):.4f}",
            f"- Annual one-way turnover: {float(full['annual_one_way_turnover']):.4f}x",
            f"- Maximum drawdown: {float(full['maximum_drawdown']):.2%}",
            f"- Double-cost Sharpe: {float(stress_full['sharpe_log_excess']):.4f}",
            f"- Worst timing perturbation Sharpe: {min(timing_sharpes.values()):.4f}",
            f"- Stable selected factor share: {float(contract.spec['factor_model']['stability_contract']['stable_selected_factor_share']):.0%}",
            f"- Walk-forward Sharpe: {float(walk_metrics['sharpe_log_excess']):.4f}",
            "",
            "## Limits",
            "",
            "The factor set was derived from already-consumed history. The expanding-fold audit",
            "uses prior-fold performance only, but it cannot restore historical freshness. This",
            "candidate requires at least 12 months of unchanged prospective validation.",
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
        "model_version_id": str(contract.spec["model_version_id"]),
        "identity": {
            "model_contract_sha256": sha256_file(contract.spec_path),
            "pool_sha256": sha256_file(discovery.pool_path),
            "source_prices_sha256": sha256_file(discovery.prices_path),
            "robustness_discovery_manifest_file_sha256": str(
                contract.spec["lineage"]["robustness_discovery_manifest_file_sha256"]
            ),
            "stability_discovery_manifest_file_sha256": str(
                contract.spec["lineage"]["stability_discovery_manifest_file_sha256"]
            ),
            "discovery_implementation_sha256": sha256_file(
                contract.root / "src/research/cn27_v1_2.py"
            ),
            "evidence_implementation_sha256": sha256_file(Path(__file__)),
        },
        "outputs": {name: sha256_file(output / name) for name in output_names},
        "decision": decision_value,
        "research_only": True,
        "trade_ready": False,
    }
    manifest["manifest_identity_sha256"] = canonical_sha256(manifest)
    write_json(output / "evidence_manifest.json", manifest)
    return {
        "decision": decision_value,
        "all_support_gates_passed": passed,
        "full_window": full,
        "double_cost_full_window": stress_full,
        "walk_forward": walk_metrics,
        "attribution_summary": attribution_summary,
        "manifest_identity_sha256": manifest["manifest_identity_sha256"],
        "research_only": True,
        "trade_ready": False,
    }
