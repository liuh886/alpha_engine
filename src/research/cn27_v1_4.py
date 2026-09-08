"""Third-order retrospective portfolio-risk experiments for frozen CN_27 V1.2."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
import yaml

from src.research.all_weather_alpha_rotation import (
    _one_way_cost,
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
from src.research.cn27_v1_2 import (
    _block_bootstrap_sharpe,
    _reference_volatility_exposure,
    compute_v1_2_features,
    execute_target_with_deferral,
    load_v1_3_contract,
    score_v1_2_features,
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


def load_v1_4_contract(path: str | Path) -> CN27DiscoveryContract:
    """Load the frozen overlay and verify both V1.2 evidence lineages."""

    spec_path = Path(path).resolve()
    root = spec_path.parents[2]
    overlay = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    if not isinstance(overlay, dict) or overlay.get("status") != "frozen_pre_screen":
        raise ValueError("CN_27 V1.4 risk-overlay contract must be frozen")
    if overlay.get("research_only") is not True or overlay.get("trade_ready") is not False:
        raise ValueError("CN_27 V1.4 must remain research-only")
    lineage = overlay["lineage"]
    model_contract = (root / str(lineage["model_contract"])).resolve()
    stability_contract = (root / str(lineage["stability_contract"])).resolve()
    if sha256_file(model_contract) != str(lineage["model_contract_sha256"]):
        raise ValueError("CN_27 V1.4 model contract hash mismatch")
    if sha256_file(stability_contract) != str(lineage["stability_contract_sha256"]):
        raise ValueError("CN_27 V1.4 stability contract hash mismatch")
    _verify_manifest(
        (root / str(lineage["model_manifest"])).resolve(),
        str(lineage["model_manifest_file_sha256"]),
        str(lineage["model_manifest_identity_sha256"]),
    )
    _verify_manifest(
        (root / str(lineage["stability_manifest"])).resolve(),
        str(lineage["stability_manifest_file_sha256"]),
        str(lineage["stability_manifest_identity_sha256"]),
    )
    base = load_v1_3_contract(stability_contract)
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
        "candidate_recipes",
        "parameter_perturbations",
        "robustness_tests",
        "selection_gate",
        "evidence",
        "stop_rules",
    ):
        merged[key] = copy.deepcopy(overlay[key])
    merged["frozen_signal"] = copy.deepcopy(overlay["frozen_signal"])
    recipe_ids = [str(row["id"]) for row in merged["candidate_recipes"]]
    if len(recipe_ids) != len(set(recipe_ids)):
        raise ValueError("CN_27 V1.4 recipe IDs must be unique")
    return replace(base, spec=merged, spec_path=spec_path)


def _capped_weights(raw: pd.Series, *, exposure: float, cap: float) -> dict[str, float]:
    if raw.empty or exposure <= 0.0:
        return {}
    if exposure > cap * len(raw) + 1e-12:
        exposure = cap * len(raw)
    result = pd.Series(0.0, index=raw.index, dtype=float)
    remaining = list(raw.index)
    remaining_total = float(exposure)
    positive = raw.clip(lower=0.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    while remaining:
        denominator = float(positive.loc[remaining].sum())
        proposed = (
            pd.Series(remaining_total / len(remaining), index=remaining)
            if denominator <= 1e-12
            else positive.loc[remaining] / denominator * remaining_total
        )
        capped = proposed.loc[proposed.gt(cap + 1e-12)].index.tolist()
        if not capped:
            result.loc[remaining] = proposed
            break
        result.loc[capped] = cap
        remaining_total -= cap * len(capped)
        remaining = [symbol for symbol in remaining if symbol not in capped]
    return {str(symbol): float(weight) for symbol, weight in result.items()}


def select_symbols(
    cross_section: pd.DataFrame,
    signal: Mapping[str, object],
    held_symbols: set[str],
    sector_by_symbol: Mapping[str, str],
) -> list[str]:
    ranked = cross_section.dropna(subset=["composite_score", "volatility_60"]).copy()
    ranked = ranked.sort_values(["composite_score", "symbol"], ascending=[False, True])
    rank_by_symbol = {
        str(symbol): rank
        for rank, symbol in enumerate(ranked["symbol"].astype(str), start=1)
    }
    top_k = int(signal["top_k"])
    buffer_rank = top_k + int(signal["exit_rank_buffer"])
    sector_cap = int(signal["maximum_names_per_sector"])
    retained = sorted(
        (s for s in held_symbols if rank_by_symbol.get(s, buffer_rank + 1) <= buffer_rank),
        key=lambda symbol: (rank_by_symbol[symbol], symbol),
    )
    selected: list[str] = []
    sector_counts: dict[str, int] = {}
    for symbol in (*retained, *ranked["symbol"].astype(str).tolist()):
        if len(selected) >= top_k:
            break
        if symbol in selected:
            continue
        sector = sector_by_symbol[symbol]
        if sector_counts.get(sector, 0) >= sector_cap:
            continue
        selected.append(symbol)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
    return selected


def shrink_covariance(returns: pd.DataFrame, shrinkage: float) -> pd.DataFrame:
    if not 0.0 <= shrinkage <= 1.0:
        raise ValueError("covariance shrinkage must be between zero and one")
    covariance = returns.cov(ddof=0).fillna(0.0)
    diagonal = pd.DataFrame(
        np.diag(np.diag(covariance.to_numpy(dtype=float))),
        index=covariance.index,
        columns=covariance.columns,
    )
    return covariance * (1.0 - shrinkage) + diagonal * shrinkage


def unit_risk_weights(
    selected: Sequence[str],
    covariance: pd.DataFrame,
    sector_by_symbol: Mapping[str, str],
    weighting: str,
) -> pd.Series:
    symbols = list(selected)
    if not symbols:
        return pd.Series(dtype=float)
    covariance = covariance.reindex(index=symbols, columns=symbols).fillna(0.0)
    variance = pd.Series(np.diag(covariance), index=symbols).clip(lower=1e-12)
    inverse_volatility = 1.0 / np.sqrt(variance)
    inverse_volatility /= inverse_volatility.sum()
    if weighting == "inverse_volatility":
        return inverse_volatility
    if weighting == "sector_equal_inverse_volatility":
        sectors = sorted({sector_by_symbol[symbol] for symbol in symbols})
        result = pd.Series(0.0, index=symbols)
        for sector in sectors:
            members = [symbol for symbol in symbols if sector_by_symbol[symbol] == sector]
            within = inverse_volatility.loc[members]
            result.loc[members] = within / within.sum() / len(sectors)
        return result
    standard_deviation = np.sqrt(variance)
    denominator = np.outer(standard_deviation, standard_deviation)
    correlation = covariance.to_numpy(dtype=float) / np.where(denominator > 0.0, denominator, 1.0)
    positive_average = pd.Series(
        np.maximum(correlation - np.eye(len(symbols)), 0.0).sum(axis=1)
        / max(1, len(symbols) - 1),
        index=symbols,
    )
    correlation_penalized = inverse_volatility / (1.0 + positive_average)
    correlation_penalized /= correlation_penalized.sum()
    if weighting == "correlation_penalized_inverse_volatility":
        return correlation_penalized
    if weighting == "shrinkage_minimum_variance":
        inverse = np.linalg.pinv(covariance.to_numpy(dtype=float), hermitian=True)
        raw = pd.Series(inverse @ np.ones(len(symbols)), index=symbols).clip(lower=0.0)
        return raw / raw.sum() if float(raw.sum()) > 1e-12 else inverse_volatility
    if weighting == "sector_correlation_blend":
        sector = unit_risk_weights(
            symbols, covariance, sector_by_symbol, "sector_equal_inverse_volatility"
        )
        blend = 0.5 * sector + 0.5 * correlation_penalized
        return blend / blend.sum()
    raise ValueError(f"unsupported V1.4 weighting: {weighting}")


def portfolio_target_weights(
    selected: Sequence[str],
    covariance: pd.DataFrame,
    sector_by_symbol: Mapping[str, str],
    recipe: Mapping[str, object],
    *,
    reference_exposure: float,
    minimum_exposure: float,
    maximum_exposure: float,
    maximum_single_weight: float,
) -> dict[str, float]:
    unit = unit_risk_weights(selected, covariance, sector_by_symbol, str(recipe["weighting"]))
    exposure_policy = str(recipe["exposure_policy"])
    if exposure_policy == "reference_volatility_target":
        exposure = reference_exposure
    elif exposure_policy == "portfolio_volatility_target":
        vector = unit.reindex(covariance.index).fillna(0.0).to_numpy(dtype=float)
        annual_volatility = float(
            np.sqrt(max(0.0, vector @ covariance.to_numpy(dtype=float) @ vector) * 252.0)
        )
        exposure = (
            float(recipe["portfolio_target_annual_volatility"]) / annual_volatility
            if annual_volatility > 1e-12
            else minimum_exposure
        )
    else:
        raise ValueError(f"unsupported V1.4 exposure policy: {exposure_policy}")
    exposure = float(np.clip(exposure, minimum_exposure, maximum_exposure))
    return _capped_weights(unit, exposure=exposure, cap=maximum_single_weight)


def run_risk_overlay_recipe(
    bars: pd.DataFrame,
    features: pd.DataFrame,
    contract: CN27DiscoveryContract,
    recipe: Mapping[str, object],
    *,
    cost_multiplier: float = 1.0,
    execution_delay_sessions: int = 1,
    rebalance_phase_offset: int = 0,
    scored_features: pd.DataFrame | None = None,
) -> DiscoveryBacktestResult:
    """Replay one frozen signal with an alternative trailing-only risk allocation."""

    if cost_multiplier <= 0.0:
        raise ValueError("cost multiplier must be positive")
    if execution_delay_sessions < 1:
        raise ValueError("execution delay must be at least one session")
    clean = normalise_long_bars(bars)
    assets = (*contract.candidate_symbols, contract.defensive_symbol)
    required = set(assets) | {contract.market_reference_symbol}
    if missing := sorted(required - set(clean["symbol"])):
        raise ValueError(f"V1.4 bars missing required instruments: {missing}")
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
            }
        )
        weights = after

        period = int(signal["rebalance_sessions"])
        if step >= rebalance_phase_offset and (step - rebalance_phase_offset) % period == 0:
            cross_section = cross_sections.get(date)
            if cross_section is not None:
                selected = select_symbols(
                    cross_section, signal, set(holdings), sector_by_symbol
                )
                lookback = int(recipe["covariance_lookback"])
                history = close_returns.loc[:date, selected].tail(lookback)
                covariance = shrink_covariance(
                    history, float(recipe["covariance_shrinkage"])
                )
                if str(recipe["id"]) == "p0_v1_2_control":
                    volatility = (
                        cross_section.set_index("symbol")["volatility_60"]
                        .reindex(selected)
                        .astype(float)
                    )
                    covariance = pd.DataFrame(
                        np.diag(np.square(volatility.to_numpy() / np.sqrt(252.0))),
                        index=selected,
                        columns=selected,
                    )
                stock_target = portfolio_target_weights(
                    selected,
                    covariance,
                    sector_by_symbol,
                    recipe,
                    reference_exposure=float(reference_exposure.get(date, 0.0)),
                    minimum_exposure=float(
                        constraints["reference_volatility_target"]["minimum_equity_exposure"]
                    ),
                    maximum_exposure=float(constraints["maximum_equity_exposure"]),
                    maximum_single_weight=float(
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


def _parameter_variants(
    recipe: Mapping[str, object], policy: Mapping[str, object]
) -> list[tuple[str, dict[str, object]]]:
    variants: list[tuple[str, dict[str, object]]] = []
    for multiplier in policy["covariance_lookback_multipliers"]:
        changed = dict(recipe)
        changed["covariance_lookback"] = max(
            20, int(round(float(recipe["covariance_lookback"]) * float(multiplier)))
        )
        variants.append((f"lookback_x{float(multiplier):.2f}", changed))
    if str(recipe["weighting"]) in {
        "correlation_penalized_inverse_volatility",
        "shrinkage_minimum_variance",
        "sector_correlation_blend",
    }:
        for offset in policy["covariance_shrinkage_offsets"]:
            changed = dict(recipe)
            changed["covariance_shrinkage"] = float(
                np.clip(float(recipe["covariance_shrinkage"]) + float(offset), 0.0, 1.0)
            )
            variants.append((f"shrinkage_{float(offset):+.2f}", changed))
    if str(recipe["exposure_policy"]) == "portfolio_volatility_target":
        for offset in policy["portfolio_target_volatility_offsets"]:
            changed = dict(recipe)
            changed["portfolio_target_annual_volatility"] = float(
                recipe["portfolio_target_annual_volatility"]
            ) + float(offset)
            variants.append((f"target_vol_{float(offset):+.2f}", changed))
    return variants


def run_v1_4_screen(
    contract_path: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run the complete predeclared screen and write immutable, hash-bound evidence."""

    contract = load_v1_4_contract(contract_path)
    bars = pd.read_csv(contract.prices_path, dtype={"symbol": str}, parse_dates=["date"])
    features = compute_v1_2_features(bars, contract)
    scoring_recipe = {**contract.spec["frozen_signal"], "id": "frozen_v1_2_signal"}
    scored, _ = score_v1_2_features(features, scoring_recipe, contract)
    fold_ids = tuple(str(row["id"]) for row in contract.spec["evaluation"]["chronological_folds"])
    robustness = contract.spec["robustness_tests"]
    bootstrap_policy = robustness["block_bootstrap"]
    parameter_policy = contract.spec["parameter_perturbations"]
    gate = contract.spec["selection_gate"]
    rows: list[dict[str, Any]] = []
    parameter_rows: list[dict[str, Any]] = []
    results: dict[str, DiscoveryBacktestResult] = {}
    bootstraps: dict[str, dict[str, Any]] = {}

    for recipe in contract.spec["candidate_recipes"]:
        recipe_id = str(recipe["id"])

        def execute(
            active_recipe: Mapping[str, object] = recipe,
            *,
            cost_multiplier: float = 1.0,
            delay: int = 1,
            phase: int = 0,
        ) -> DiscoveryBacktestResult:
            return run_risk_overlay_recipe(
                bars,
                features,
                contract,
                active_recipe,
                cost_multiplier=cost_multiplier,
                execution_delay_sessions=delay,
                rebalance_phase_offset=phase,
                scored_features=scored,
            )

        base = execute()
        stress = execute(cost_multiplier=float(robustness["cost_multiplier"]))
        delayed = execute(delay=int(robustness["execution_delay_sessions"]))
        period = int(contract.spec["frozen_signal"]["rebalance_sessions"])
        phase_offsets = sorted(
            {
                int(round(period * float(fraction)))
                for fraction in robustness["rebalance_phase_fractions"]
            }
        )
        phase_sharpes = {"0": float(base.metrics_by_window["development"]["sharpe_log_excess"])}
        for phase in phase_offsets:
            phase_result = execute(phase=phase)
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
        for label, variant in _parameter_variants(recipe, parameter_policy):
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
        bootstrap = _block_bootstrap_sharpe(
            base.daily["net_return"],
            samples=int(bootstrap_policy["samples"]),
            block_sessions=int(bootstrap_policy["block_sessions"]),
            seed=int(bootstrap_policy["seed"]),
        )
        full = base.metrics_by_window["development"]
        fold_sharpes = [
            float(base.metrics_by_window[fold]["sharpe_log_excess"]) for fold in fold_ids
        ]
        double_cost_sharpe = float(
            stress.metrics_by_window["development"]["sharpe_log_excess"]
        )
        delay_sharpe = float(delayed.metrics_by_window["development"]["sharpe_log_excess"])
        worst_timing = min(delay_sharpe, *phase_sharpes.values())
        rows.append(
            {
                "recipe_id": recipe_id,
                "weighting": str(recipe["weighting"]),
                "exposure_policy": str(recipe["exposure_policy"]),
                "full_total_return": float(full["total_return"]),
                "full_cagr": float(full["cagr"]),
                "full_annual_volatility": float(full["annual_volatility"]),
                "full_sharpe_log_excess": float(full["sharpe_log_excess"]),
                "full_maximum_drawdown": float(full["maximum_drawdown"]),
                "full_annual_one_way_turnover": float(full["annual_one_way_turnover"]),
                "double_cost_full_sharpe": double_cost_sharpe,
                "delay_two_full_sharpe": delay_sharpe,
                "phase_sharpes": json.dumps(phase_sharpes, sort_keys=True),
                "worst_timing_perturbation_sharpe": worst_timing,
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
            }
        )
        results[recipe_id] = base
        bootstraps[recipe_id] = bootstrap

    summary = pd.DataFrame(rows)
    control = summary.loc[summary["recipe_id"].eq("p0_v1_2_control")].iloc[0]
    control_drawdown = abs(float(control["full_maximum_drawdown"]))
    failures_by_recipe: dict[str, list[str]] = {}
    for index, row in summary.iterrows():
        failures: list[str] = []
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
            (
                control_drawdown - abs(float(row["full_maximum_drawdown"]))
                >= float(gate["minimum_drawdown_improvement_vs_control"]),
                "drawdown_improvement_vs_control",
            ),
        )
        failures.extend(name for passed, name in checks if not passed)
        summary.loc[index, "drawdown_improvement_vs_control"] = (
            control_drawdown - abs(float(row["full_maximum_drawdown"]))
        )
        summary.loc[index, "minimum_robustness_score"] = min(
            float(row["double_cost_full_sharpe"]),
            float(row["worst_timing_perturbation_sharpe"]),
            float(row["bootstrap_sharpe_percentile_05"]),
            float(row["parameter_neighborhood_minimum_sharpe"]),
        )
        summary.loc[index, "selection_gate_passed"] = not failures
        summary.loc[index, "failure_reasons"] = "+".join(failures)
        failures_by_recipe[str(row["recipe_id"])] = failures
    summary["selection_gate_passed"] = summary["selection_gate_passed"].astype(bool)
    summary = summary.sort_values(
        [
            "selection_gate_passed",
            "minimum_robustness_score",
            "full_maximum_drawdown",
            "full_annual_one_way_turnover",
            "recipe_id",
        ],
        ascending=[False, False, False, True, True],
    ).reset_index(drop=True)
    passing = summary.loc[summary["selection_gate_passed"]]
    selected_id = str(passing.iloc[0]["recipe_id"]) if not passing.empty else None
    selected_recipe = next(
        (dict(row) for row in contract.spec["candidate_recipes"] if row["id"] == selected_id),
        None,
    )
    decision_name = (
        "retrospective_risk_overlay_candidate_identified"
        if selected_id is not None
        else "no_risk_overlay_passed_frozen_gate"
    )
    selection: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": str(contract.spec["experiment_id"]),
        "decision": decision_name,
        "selected_recipe_id": selected_id,
        "selected_recipe": selected_recipe,
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
    write_json(output / "selected_recipe.json", selection)
    if selected_id is not None:
        results[selected_id].daily.reset_index().to_csv(
            output / "selected_daily.csv", index=False, date_format="%Y-%m-%d"
        )
        selected_bootstrap = bootstraps[selected_id]
    else:
        pd.DataFrame(columns=["date"]).to_csv(output / "selected_daily.csv", index=False)
        selected_bootstrap = {"available": False, "reason": "no candidate passed frozen gate"}
    write_json(output / "bootstrap.json", selected_bootstrap)
    decision = {
        "schema_version": "1.0",
        "decision": decision_name,
        "selected_recipe_id": selected_id,
        "all_selection_gates_passed": selected_id is not None,
        "control_recipe_audit": control.to_dict(),
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
            "# CN_27 V1.4 risk-overlay retrospective discovery",
            "",
            f"- Decision: `{decision_name}`",
            f"- Selected recipe: `{selected_id}`",
            "- Signal and pool unchanged from frozen V1.2: `true`",
            "- Fresh historical holdout: `false`",
            "- Research only: `true`; trade ready: `false`",
            "",
            "## Frozen-gate leader",
            "",
            f"- Recipe: `{leader['recipe_id']}`",
            f"- Full-window Sharpe: {float(leader['full_sharpe_log_excess']):.4f}",
            f"- Maximum drawdown: {float(leader['full_maximum_drawdown']):.2%}",
            f"- Bootstrap Sharpe p05: {float(leader['bootstrap_sharpe_percentile_05']):.4f}",
            f"- P(Sharpe > 1): {float(leader['bootstrap_probability_sharpe_above_one']):.2%}",
            f"- Parameter-neighborhood minimum Sharpe: {float(leader['parameter_neighborhood_minimum_sharpe']):.4f}",
            "",
            "## Interpretation boundary",
            "",
            "This is a third-order retrospective portfolio-construction test on fully consumed",
            "history. It may reject risk overlays or nominate one for prospective observation,",
            "but it cannot refresh the holdout, authorize promotion, or support live trading.",
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
            "model_manifest_file_sha256": str(
                contract.spec["lineage"]["model_manifest_file_sha256"]
            ),
            "stability_manifest_file_sha256": str(
                contract.spec["lineage"]["stability_manifest_file_sha256"]
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
