"""Minimum-distance constrained projection for the CN_27 V1.3 completion cycle."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any
from typing import Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import minimize
import yaml

from src.research.all_weather_alpha_rotation import (
    canonical_sha256,
    normalise_long_bars,
    sha256_file,
)
from src.research.cn27_sharpe_discovery import (
    CN27DiscoveryContract,
    DiscoveryBacktestResult,
    _window_metrics,
    write_json,
)
from src.research.cn27_v1_3 import (
    _parameter_variants,
    concentration_audit,
    concentration_metrics,
    contribution_attribution,
)
from src.research.cn27_v1_3_staggered import load_staggered_discovery_contract
from src.research.cn27_v1_2 import (
    _block_bootstrap_sharpe,
    compute_v1_2_features,
    _reference_volatility_exposure,
    execute_target_with_deferral,
    score_v1_2_features,
)
from src.research.cn27_v1_4 import (
    _capped_weights,
    select_symbols,
    shrink_covariance,
    unit_risk_weights,
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


def load_projected_discovery_contract(path: str | Path) -> CN27DiscoveryContract:
    spec_path = Path(path).resolve()
    root = spec_path.parents[2]
    overlay = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    if not isinstance(overlay, dict) or overlay.get("status") != "frozen_pre_screen":
        raise ValueError("CN_27 V1.3 projected-concentration contract must be frozen")
    if overlay.get("research_only") is not True or overlay.get("trade_ready") is not False:
        raise ValueError("CN_27 V1.3 projected discovery must remain research-only")
    lineage = overlay["lineage"]
    base_path = (root / str(lineage["staggered_contract"])).resolve()
    if sha256_file(base_path) != str(lineage["staggered_contract_sha256"]):
        raise ValueError("CN_27 V1.3 staggered contract hash mismatch")
    _verify_manifest(
        (root / str(lineage["staggered_manifest"])).resolve(),
        str(lineage["staggered_manifest_file_sha256"]),
        str(lineage["staggered_manifest_identity_sha256"]),
    )
    base = load_staggered_discovery_contract(base_path)
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
        raise ValueError("CN_27 V1.3 projected recipe IDs must be unique")
    return replace(base, spec=merged, spec_path=spec_path)


def project_minimum_variance_weights(
    minimum_variance: pd.Series,
    sector_by_symbol: Mapping[str, str],
    *,
    maximum_single_share: float,
    maximum_sector_share: float,
    minimum_effective_names: float,
) -> tuple[pd.Series, dict[str, float]]:
    raw = minimum_variance.clip(lower=0.0).astype(float)
    if raw.empty or float(raw.sum()) <= 1e-12:
        raise ValueError("minimum-variance weights must have positive mass")
    raw /= raw.sum()
    symbols = list(raw.index)
    sectors = sorted({sector_by_symbol[symbol] for symbol in symbols})
    initial = np.full(len(symbols), 1.0 / len(symbols), dtype=float)
    effective_constraint_target = minimum_effective_names + 1e-6
    constraints: list[dict[str, object]] = [
        {
            "type": "eq",
            "fun": lambda values: float(values.sum() - 1.0),
            "jac": lambda values: np.ones_like(values),
        },
        {
            "type": "ineq",
            "fun": lambda values: float(
                1.0 / effective_constraint_target - values @ values
            ),
            "jac": lambda values: -2.0 * values,
        },
    ]
    for sector in sectors:
        mask = np.asarray(
            [1.0 if sector_by_symbol[symbol] == sector else 0.0 for symbol in symbols]
        )
        constraints.append(
            {
                "type": "ineq",
                "fun": lambda values, mask=mask: float(
                    maximum_sector_share - mask @ values
                ),
                "jac": lambda values, mask=mask: -mask,
            }
        )
    def objective(values: np.ndarray) -> float:
        return float(0.5 * np.square(values - raw.to_numpy()).sum())
    starts = [
        initial,
        0.75 * initial + 0.25 * raw.to_numpy(),
        0.50 * initial + 0.50 * raw.to_numpy(),
    ]
    feasible_results: list[tuple[float, Any, pd.Series, dict[str, float]]] = []
    messages: list[str] = []
    for start in starts:
        result = minimize(
            fun=objective,
            x0=start,
            jac=lambda values: values - raw.to_numpy(),
            bounds=[(0.0, maximum_single_share)] * len(symbols),
            constraints=constraints,
            method="SLSQP",
            options={"ftol": 1e-10, "maxiter": 1000, "disp": False},
        )
        projected = pd.Series(result.x, index=symbols).clip(lower=0.0)
        projected /= projected.sum()
        metrics = concentration_metrics(projected, sector_by_symbol)
        feasible = (
            abs(float(projected.sum()) - 1.0) <= 1e-8
            and metrics["maximum_single_share"] <= maximum_single_share + 1e-8
            and metrics["maximum_sector_share"] <= maximum_sector_share + 1e-8
            and metrics["effective_names"] + 1e-8 >= minimum_effective_names
        )
        messages.append(
            f"{result.message}; single={metrics['maximum_single_share']:.12f}; "
            f"sector={metrics['maximum_sector_share']:.12f}; "
            f"effective={metrics['effective_names']:.12f}; sum={projected.sum():.12f}"
        )
        if result.success and feasible:
            feasible_results.append((objective(projected.to_numpy()), result, projected, metrics))
    if not feasible_results:
        raise ValueError(
            "minimum-distance concentration projection had no confirmed solution: "
            + " | ".join(messages)
        )
    _, result, projected, metrics = min(feasible_results, key=lambda row: row[0])
    return projected, {
        **metrics,
        "projection_distance": float(np.linalg.norm(projected.to_numpy() - raw.to_numpy())),
        "optimizer_iterations": float(result.nit),
        "optimizer_reported_success": 1.0,
        "optimizer_confirmed_solution_count": float(len(feasible_results)),
    }


def projected_portfolio_target_weights(
    selected: Sequence[str],
    covariance: pd.DataFrame,
    sector_by_symbol: Mapping[str, str],
    recipe: Mapping[str, object],
    *,
    reference_exposure: float,
    minimum_exposure: float,
    maximum_exposure: float,
    maximum_single_absolute_weight: float,
) -> tuple[dict[str, float], dict[str, float]]:
    symbols = list(selected)
    if not symbols:
        return {}, {
            "maximum_single_share": 0.0,
            "maximum_sector_share": 0.0,
            "effective_names": 0.0,
            "projection_distance": 0.0,
            "optimizer_iterations": 0.0,
        }
    minimum_variance = unit_risk_weights(
        symbols, covariance, sector_by_symbol, "shrinkage_minimum_variance"
    )
    if bool(recipe.get("concentration_governance", True)):
        unit, diagnostics = project_minimum_variance_weights(
            minimum_variance,
            sector_by_symbol,
            maximum_single_share=float(recipe["maximum_single_equity_sleeve_share"]),
            maximum_sector_share=float(recipe["maximum_sector_equity_sleeve_share"]),
            minimum_effective_names=float(recipe["minimum_effective_names"]),
        )
    else:
        unit = minimum_variance
        diagnostics = {
            **concentration_metrics(unit, sector_by_symbol),
            "projection_distance": 0.0,
            "optimizer_iterations": 0.0,
        }
    exposure = float(np.clip(reference_exposure, minimum_exposure, maximum_exposure))
    absolute = _capped_weights(
        unit,
        exposure=exposure,
        cap=maximum_single_absolute_weight,
    )
    realized = concentration_metrics(absolute, sector_by_symbol)
    return absolute, {**diagnostics, **{f"target_{key}": value for key, value in realized.items()}}


def run_projected_recipe(
    bars: pd.DataFrame,
    features: pd.DataFrame,
    contract: CN27DiscoveryContract,
    recipe: Mapping[str, object],
    *,
    cost_multiplier: float = 1.0,
    execution_delay_sessions: int = 1,
    rebalance_phase_offset: int = 0,
    excluded_sectors: frozenset[str] = frozenset(),
    scored_features: pd.DataFrame | None = None,
) -> DiscoveryBacktestResult:
    if cost_multiplier <= 0.0:
        raise ValueError("cost multiplier must be positive")
    if execution_delay_sessions < 1:
        raise ValueError("execution delay must be at least one session")
    clean = normalise_long_bars(bars)
    assets = (*contract.candidate_symbols, contract.defensive_symbol)
    required = set(assets) | {contract.market_reference_symbol}
    if missing := sorted(required - set(clean["symbol"])):
        raise ValueError(f"projected V1.3 bars missing required instruments: {missing}")
    by_symbol = {
        symbol: clean.loc[clean["symbol"].eq(symbol)].set_index("date").sort_index()
        for symbol in required
    }
    full_calendar = pd.DatetimeIndex(by_symbol[contract.defensive_symbol].index).sort_values().unique()
    full_closes = pd.DataFrame(
        {
            symbol: by_symbol[symbol]["close"].reindex(full_calendar).ffill()
            for symbol in contract.candidate_symbols
        },
        index=full_calendar,
    )
    close_returns = full_closes.pct_change(fill_method=None)
    start = pd.Timestamp(contract.spec["evaluation"]["full_window"]["start"])
    cutoff = pd.Timestamp(contract.spec["evaluation"]["full_window"]["end"])
    calendar = full_calendar[(full_calendar >= start) & (full_calendar <= cutoff)]
    opens = {symbol: by_symbol[symbol]["open"].reindex(calendar).ffill() for symbol in assets}
    observed = {
        symbol: pd.Series(calendar.isin(by_symbol[symbol].index), index=calendar)
        for symbol in assets
    }
    locked = {
        symbol: pd.Series(
            np.isclose(
                by_symbol[symbol]["high"],
                by_symbol[symbol]["low"],
                rtol=0.0,
                atol=1e-12,
            ),
            index=by_symbol[symbol].index,
        )
        .reindex(calendar)
        .fillna(False)
        for symbol in assets
    }
    open_returns = pd.DataFrame(
        {
            symbol: opens[symbol].pct_change(fill_method=None).fillna(0.0)
            for symbol in assets
        },
        index=calendar,
    )
    signal = contract.spec["frozen_signal"]
    runtime_recipe = {**contract.spec["frozen_risk_model"], **recipe}
    scoring_recipe = {**signal, "id": str(recipe["id"])}
    scored = scored_features
    if scored is None:
        scored, _ = score_v1_2_features(features, scoring_recipe, contract)
    cross_sections = {
        pd.Timestamp(date): frame.copy()
        for date, frame in scored.loc[scored["date"].isin(calendar)].groupby("date", sort=True)
    }
    sector_by_symbol = {
        str(row["symbol"]).zfill(6): str(row["sector"]) for row in contract.pool["symbols"]
    }
    excluded_symbols = {
        symbol for symbol, sector in sector_by_symbol.items() if sector in excluded_sectors
    }
    reference_exposure = _reference_volatility_exposure(clean, contract)
    constraints = contract.spec["portfolio_constraints"]
    cost_spec = {
        "stock_buy_rate": float(contract.spec["costs"]["primary"]["stock_buy"])
        * cost_multiplier,
        "stock_sell_rate": float(contract.spec["costs"]["primary"]["stock_sell"])
        * cost_multiplier,
        "etf_buy_rate": float(contract.spec["costs"]["primary"]["etf_buy"])
        * cost_multiplier,
        "etf_sell_rate": float(contract.spec["costs"]["primary"]["etf_sell"])
        * cost_multiplier,
    }
    weights = {symbol: 0.0 for symbol in assets}
    weights["CASH"] = 1.0
    active_target: dict[str, float] | None = {
        **{symbol: 0.0 for symbol in contract.candidate_symbols},
        contract.defensive_symbol: 1.0,
        "CASH": 0.0,
    }
    scheduled_targets: dict[int, dict[str, float]] = {}
    daily_rows: list[dict[str, object]] = []
    equity = 1.0
    latest_target_diagnostics: dict[str, float] = {}

    for step, date in enumerate(calendar):
        if step in scheduled_targets:
            active_target = scheduled_targets.pop(step)
        relatives = {symbol: 1.0 + float(open_returns.loc[date, symbol]) for symbol in assets}
        gross_return = sum(weights[symbol] * (relatives[symbol] - 1.0) for symbol in assets)
        gross_factor = 1.0 + gross_return
        before = {symbol: weights[symbol] * relatives[symbol] / gross_factor for symbol in assets}
        before["CASH"] = weights["CASH"] / gross_factor
        if active_target is not None:
            tradable = {
                symbol: bool(observed[symbol].loc[date]) and not bool(locked[symbol].loc[date])
                for symbol in assets
            }
            after, cost, turnover, pending, target_drift = execute_target_with_deferral(
                before,
                active_target,
                tradable,
                candidate_symbols=contract.candidate_symbols,
                defensive_symbol=contract.defensive_symbol,
                cost_spec=cost_spec,
            )
            if not pending:
                active_target = None
        else:
            after = before
            cost, turnover, target_drift = 0.0, 0.0, 0.0
        net_return = gross_return - cost
        equity *= 1.0 + net_return
        holdings = sorted(
            symbol for symbol in contract.candidate_symbols if after[symbol] > 1e-8
        )
        daily_rows.append(
            {
                "date": date,
                "gross_return": gross_return,
                "transaction_cost": cost,
                "net_return": net_return,
                "equity": equity,
                "one_way_turnover": turnover,
                "equity_exposure": sum(after[symbol] for symbol in contract.candidate_symbols),
                "etf_weight": after[contract.defensive_symbol],
                "cash_weight": after["CASH"],
                "holding_count": len(holdings),
                "holdings": json.dumps(holdings, ensure_ascii=False),
                "return_weights": json.dumps(
                    {
                        symbol: weights[symbol]
                        for symbol in assets
                        if weights[symbol] > 1e-12
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
                **latest_target_diagnostics,
            }
        )
        weights = after
        period = int(signal["rebalance_sessions"])
        if step >= rebalance_phase_offset and (step - rebalance_phase_offset) % period == 0:
            cross_section = cross_sections.get(date)
            if cross_section is not None:
                eligible = cross_section.loc[~cross_section["symbol"].isin(excluded_symbols)]
                selected = select_symbols(
                    eligible,
                    signal,
                    set(holdings) - excluded_symbols,
                    sector_by_symbol,
                )
                history = close_returns.loc[:date, selected].tail(
                    int(runtime_recipe["covariance_lookback"])
                )
                covariance = shrink_covariance(
                    history, float(runtime_recipe["covariance_shrinkage"])
                )
                stock_target, latest_target_diagnostics = projected_portfolio_target_weights(
                    selected,
                    covariance,
                    sector_by_symbol,
                    runtime_recipe,
                    reference_exposure=float(reference_exposure.get(date, 0.0)),
                    minimum_exposure=float(
                        constraints["reference_volatility_target"]["minimum_equity_exposure"]
                    ),
                    maximum_exposure=float(constraints["maximum_equity_exposure"]),
                    maximum_single_absolute_weight=float(
                        constraints["maximum_single_security_weight"]
                    ),
                )
                target = {
                    symbol: float(stock_target.get(symbol, 0.0))
                    for symbol in contract.candidate_symbols
                }
                target[contract.defensive_symbol] = 1.0 - sum(stock_target.values())
                target["CASH"] = 0.0
                scheduled_targets[step + execution_delay_sessions] = target

    daily = pd.DataFrame(daily_rows).set_index("date")
    fold_ids = tuple(str(row["id"]) for row in contract.spec["evaluation"]["chronological_folds"])
    return DiscoveryBacktestResult(
        recipe_id=str(recipe["id"]),
        daily=daily,
        metrics_by_window={
            name: _window_metrics(daily, contract, name)
            for name in ("development", *fold_ids)
        },
    )


def _gate_failures(
    row: Mapping[str, object],
    gate: Mapping[str, object],
    parameter_policy: Mapping[str, object],
) -> list[str]:
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
    return [name for passed, name in checks if not passed]


def run_projected_discovery_screen(
    contract_path: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    contract = load_projected_discovery_contract(contract_path)
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
    rows: list[dict[str, Any]] = []
    parameter_rows: list[dict[str, Any]] = []
    sector_rows: list[dict[str, Any]] = []
    results: dict[str, DiscoveryBacktestResult] = {}
    audits: dict[str, tuple[pd.DataFrame, dict[str, float]]] = {}
    attributions: dict[str, tuple[pd.DataFrame, dict[str, Any]]] = {}
    bootstraps: dict[str, dict[str, Any]] = {}
    for recipe in contract.spec["candidate_recipes"]:
        recipe_id = str(recipe["id"])

        def execute(
            active_recipe: Mapping[str, object] = recipe,
            *,
            cost_multiplier: float = 1.0,
            delay: int = 1,
            phase: int = 0,
            excluded: frozenset[str] = frozenset(),
        ) -> DiscoveryBacktestResult:
            return run_projected_recipe(
                bars,
                features,
                contract,
                active_recipe,
                cost_multiplier=cost_multiplier,
                execution_delay_sessions=delay,
                rebalance_phase_offset=phase,
                excluded_sectors=excluded,
                scored_features=scored,
            )

        base = execute()
        stress = execute(cost_multiplier=float(robustness["cost_multiplier"]))
        delayed = execute(delay=int(robustness["execution_delay_sessions"]))
        phase_sharpes = {"0": float(base.metrics_by_window["development"]["sharpe_log_excess"])}
        for phase in robustness["rebalance_phase_offsets"]:
            phase_result = execute(phase=int(phase))
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
        for label, variant in _parameter_variants(recipe, risk_model, parameter_policy):
            variant_result = execute(variant)
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
            sector_result = execute(excluded=frozenset({sector}))
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
        double_cost_sharpe = float(stress.metrics_by_window["development"]["sharpe_log_excess"])
        delay_sharpe = float(delayed.metrics_by_window["development"]["sharpe_log_excess"])
        rows.append(
            {
                "recipe_id": recipe_id,
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
                **audit[1],
                "maximum_single_name_positive_contribution_share": float(
                    attribution[1]["maximum_single_name_positive_contribution_share"]
                ),
                "maximum_single_sector_positive_contribution_share": float(
                    attribution[1]["maximum_single_sector_positive_contribution_share"]
                ),
            }
        )
        results[recipe_id] = base
        audits[recipe_id] = audit
        attributions[recipe_id] = attribution
        bootstraps[recipe_id] = bootstrap

    summary = pd.DataFrame(rows)
    failures_by_recipe: dict[str, list[str]] = {}
    for index, row in summary.iterrows():
        failures = _gate_failures(row, gate, parameter_policy)
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
        "retrospective_projected_candidate_identified"
        if selected_id is not None
        else "no_projected_candidate_passed_frozen_gate"
    )
    selection: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": str(contract.spec["experiment_id"]),
        "decision": decision_name,
        "selected_recipe_id": selected_id,
        "selected_recipe": selected_recipe,
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
        results[selected_id].daily.reset_index().to_csv(
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
    write_json(
        output / "decision.json",
        {
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
        },
    )
    leader = summary.iloc[0]
    report = "\n".join(
        [
            "# CN_27 V1.3 minimum-distance projection discovery",
            "",
            f"- Decision: `{decision_name}`",
            f"- Selected recipe: `{selected_id}`",
            "- Projection: minimum squared distance to shrinkage-minimum-variance weights",
            "- Fresh historical holdout: `false`",
            "- Research only: `true`; trade ready: `false`",
            "",
            "## Frozen-gate leader",
            "",
            f"- Recipe: `{leader['recipe_id']}`",
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
            "This sixth-order retrospective test uses fully consumed history. It is the last",
            "new historical mechanism in the V1.3 completion cycle. Passing may nominate a",
            "research-only candidate but cannot create fresh validation or authorize trading.",
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
            "staggered_manifest_file_sha256": str(
                contract.spec["lineage"]["staggered_manifest_file_sha256"]
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
