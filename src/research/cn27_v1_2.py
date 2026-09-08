"""Retrospective robustness research for CN_27 after the frozen V1.1 cycle."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from src.research.all_weather_alpha_rotation import (
    _one_way_cost,
    _return_metrics,
    canonical_sha256,
    normalise_long_bars,
    sha256_file,
)
from src.research.cn27_sharpe_discovery import (
    CN27DiscoveryContract,
    DiscoveryBacktestResult,
    _capped_inverse_volatility_weights,
    _window_metrics,
    write_json,
)


def load_v1_2_contract(path: str | Path) -> CN27DiscoveryContract:
    """Load the frozen V1.2 exploration contract and verify its complete lineage."""

    spec_path = Path(path).resolve()
    root = spec_path.parents[2]
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise ValueError("CN_27 V1.2 contract must be a YAML mapping")
    if spec.get("status") != "frozen_pre_screen":
        raise ValueError("CN_27 V1.2 contract must be frozen before screening")
    if spec.get("research_only") is not True or spec.get("trade_ready") is not False:
        raise ValueError("CN_27 V1.2 exploration must remain research-only")
    identity = spec["identity"]
    lineage = spec["lineage"]
    pool_path = (root / str(identity["pool_spec"])).resolve()
    prices_path = (root / str(identity["source_prices"])).resolve()
    predecessor_contract = (root / str(lineage["predecessor_contract"])).resolve()
    predecessor_manifest = (root / str(lineage["predecessor_manifest"])).resolve()
    expected_hashes = (
        (pool_path, str(identity["pool_sha256"])),
        (prices_path, str(identity["source_prices_sha256"])),
        (predecessor_contract, str(lineage["predecessor_contract_sha256"])),
        (predecessor_manifest, str(lineage["predecessor_manifest_file_sha256"])),
    )
    for source_path, expected in expected_hashes:
        if sha256_file(source_path) != expected:
            raise ValueError(f"CN_27 V1.2 identity hash mismatch: {source_path}")
    pool = yaml.safe_load(pool_path.read_text(encoding="utf-8"))
    symbols = tuple(str(row["symbol"]).zfill(6) for row in pool["symbols"])
    if len(symbols) != 27 or len(set(symbols)) != 27:
        raise ValueError("CN_27 V1.2 requires exactly 27 unique candidates")
    factor_ids = {str(row["id"]) for row in spec["factor_diagnostics"]["factors"]}
    if len(factor_ids) != len(spec["factor_diagnostics"]["factors"]):
        raise ValueError("CN_27 V1.2 factor IDs must be unique")
    recipe_ids = [str(row["id"]) for row in spec["candidate_recipes"]]
    if len(recipe_ids) != len(set(recipe_ids)):
        raise ValueError("CN_27 V1.2 recipe IDs must be unique")
    for recipe in spec["candidate_recipes"]:
        referenced = set(recipe.get("factors", recipe.get("factor_pool", [])))
        if referenced - factor_ids:
            raise ValueError(f"recipe references undeclared factors: {recipe['id']}")

    runtime_spec = copy.deepcopy(spec)
    full = runtime_spec["evaluation"]["full_window"]
    runtime_spec["windows"] = {"development": dict(full)}
    runtime_spec["windows"].update(
        {str(row["id"]): dict(row) for row in runtime_spec["evaluation"]["chronological_folds"]}
    )
    return CN27DiscoveryContract(
        spec=runtime_spec,
        pool=pool,
        spec_path=spec_path,
        pool_path=pool_path,
        prices_path=prices_path,
        candidate_symbols=symbols,
        defensive_symbol=str(identity["defensive_etf"]).zfill(6),
        market_reference_symbol=str(identity["market_reference"]).zfill(6),
    )


def load_v1_3_contract(path: str | Path) -> CN27DiscoveryContract:
    """Load a second-order stability experiment layered over frozen V1.2 evidence."""

    spec_path = Path(path).resolve()
    root = spec_path.parents[2]
    overlay = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    if not isinstance(overlay, dict) or overlay.get("status") != "frozen_pre_screen":
        raise ValueError("CN_27 V1.3 stability contract must be frozen")
    if overlay.get("research_only") is not True or overlay.get("trade_ready") is not False:
        raise ValueError("CN_27 V1.3 stability experiment must remain research-only")
    base_path = (root / str(overlay["base_experiment"]["contract"])).resolve()
    base_manifest_path = (
        root / str(overlay["base_experiment"]["evidence_manifest"])
    ).resolve()
    if sha256_file(base_path) != str(overlay["base_experiment"]["contract_sha256"]):
        raise ValueError("CN_27 V1.3 base contract hash mismatch")
    if sha256_file(base_manifest_path) != str(
        overlay["base_experiment"]["evidence_manifest_file_sha256"]
    ):
        raise ValueError("CN_27 V1.3 base manifest file hash mismatch")
    manifest = json.loads(base_manifest_path.read_text(encoding="utf-8"))
    manifest_body = dict(manifest)
    manifest_identity = str(manifest_body.pop("manifest_identity_sha256", ""))
    if canonical_sha256(manifest_body) != manifest_identity:
        raise ValueError("CN_27 V1.3 base manifest identity mismatch")
    if manifest_identity != str(
        overlay["base_experiment"]["evidence_manifest_identity_sha256"]
    ):
        raise ValueError("CN_27 V1.3 unexpected base manifest identity")
    for name, expected in manifest["outputs"].items():
        if sha256_file(base_manifest_path.parent / name) != expected:
            raise ValueError(f"CN_27 V1.3 base output hash mismatch: {name}")

    base = load_v1_2_contract(base_path)
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
        "objective",
        "candidate_recipes",
        "selection_gate",
        "evidence",
        "stop_rules",
    ):
        merged[key] = copy.deepcopy(overlay[key])
    merged["base_experiment"] = copy.deepcopy(overlay["base_experiment"])
    merged["iteration_semantics"] = copy.deepcopy(overlay["iteration_semantics"])
    recipe_ids = [str(row["id"]) for row in merged["candidate_recipes"]]
    if len(recipe_ids) != len(set(recipe_ids)):
        raise ValueError("CN_27 V1.3 recipe IDs must be unique")
    declared_factors = {
        str(row["id"]) for row in merged["factor_diagnostics"]["factors"]
    }
    for recipe in merged["candidate_recipes"]:
        referenced = set(recipe.get("factors", recipe.get("factor_pool", [])))
        if referenced - declared_factors:
            raise ValueError(f"V1.3 recipe references undeclared factors: {recipe['id']}")
    return replace(base, spec=merged, spec_path=spec_path)


def compute_v1_2_features(
    bars: pd.DataFrame,
    contract: CN27DiscoveryContract,
) -> pd.DataFrame:
    """Compute the frozen V1.2 trailing factors and delayed 20-session label."""

    clean = normalise_long_bars(bars)
    market_close = (
        clean.loc[clean["symbol"].eq(contract.market_reference_symbol)]
        .sort_values("date")
        .set_index("date")["close"]
    )
    rows: list[pd.DataFrame] = []
    horizon = int(contract.spec["factor_diagnostics"]["forward_horizon_sessions"])
    delay = int(contract.spec["factor_diagnostics"]["execution_delay_sessions"])
    for symbol in contract.candidate_symbols:
        item = (
            clean.loc[clean["symbol"].eq(symbol)]
            .sort_values("date")
            .reset_index(drop=True)
            .copy()
        )
        if item.empty:
            raise ValueError(f"CN_27 V1.2 candidate has no bars: {symbol}")
        close = item["close"]
        open_price = item["open"]
        returns = close.pct_change(fill_method=None)
        aligned_market_close = pd.Series(
            market_close.reindex(pd.DatetimeIndex(item["date"])).ffill().to_numpy(),
            index=item.index,
        )
        market_returns = aligned_market_close.pct_change(fill_method=None)
        market_return_60 = aligned_market_close.pct_change(60, fill_method=None)
        market_return_120 = aligned_market_close.pct_change(120, fill_method=None)
        momentum_5 = close.pct_change(5, fill_method=None)
        momentum_20 = close.pct_change(20, fill_method=None)
        momentum_60 = close.pct_change(60, fill_method=None)
        momentum_120 = close.pct_change(120, fill_method=None)
        vol20 = returns.rolling(20, min_periods=20).std(ddof=0) * np.sqrt(252)
        vol60 = returns.rolling(60, min_periods=60).std(ddof=0) * np.sqrt(252)
        vol120 = returns.rolling(120, min_periods=120).std(ddof=0) * np.sqrt(252)
        market_variance_60 = market_returns.rolling(60, min_periods=60).var(ddof=0)
        market_variance_120 = market_returns.rolling(120, min_periods=120).var(ddof=0)
        beta60 = returns.rolling(60, min_periods=60).cov(market_returns, ddof=0).div(
            market_variance_60.replace(0.0, np.nan)
        )
        beta120 = returns.rolling(120, min_periods=120).cov(market_returns, ddof=0).div(
            market_variance_120.replace(0.0, np.nan)
        )
        item["momentum_60"] = momentum_60
        item["volatility_20"] = vol20
        item["volatility_60"] = vol60
        item["short_term_reversal_5"] = -momentum_5
        item["trend_20"] = close / close.rolling(20, min_periods=20).mean() - 1.0
        item["trend_60"] = close / close.rolling(60, min_periods=60).mean() - 1.0
        item["trend_120"] = close / close.rolling(120, min_periods=120).mean() - 1.0
        item["risk_adjusted_momentum_20"] = momentum_20 / vol20.replace(0.0, np.nan)
        item["risk_adjusted_momentum_60"] = momentum_60 / vol60.replace(0.0, np.nan)
        item["risk_adjusted_momentum_120"] = momentum_120 / vol120.replace(0.0, np.nan)
        item["trend_efficiency_60"] = momentum_60 / returns.abs().rolling(
            60, min_periods=60
        ).sum().replace(0.0, np.nan)
        item["trend_efficiency_120"] = momentum_120 / returns.abs().rolling(
            120, min_periods=120
        ).sum().replace(0.0, np.nan)
        item["residual_momentum_60"] = momentum_60 - beta60 * market_return_60
        item["residual_momentum_120"] = momentum_120 - beta120 * market_return_120
        item["low_beta_60"] = -beta60
        item["low_market_correlation_60"] = -returns.rolling(
            60, min_periods=60
        ).corr(market_returns)
        item["low_volatility_60"] = -vol60
        item["drawdown_60"] = close / close.rolling(60, min_periods=60).max() - 1.0
        item["drawdown_120"] = close / close.rolling(120, min_periods=120).max() - 1.0
        item["volatility_contraction_20_60"] = -(vol20 / vol60.replace(0.0, np.nan))
        item["positive_day_share_60"] = returns.gt(0.0).rolling(
            60, min_periods=60
        ).mean()
        item["forward_return_20"] = (
            open_price.shift(-(delay + horizon)) / open_price.shift(-delay) - 1.0
        )
        item["label_realization_date"] = item["date"].shift(-(delay + horizon))
        rows.append(item)
    return pd.concat(rows, ignore_index=True).sort_values(["date", "symbol"]).reset_index(
        drop=True
    )


def v1_2_factor_diagnostics(
    features: pd.DataFrame,
    contract: CN27DiscoveryContract,
) -> pd.DataFrame:
    """Measure each factor independently in all six already-consumed time folds."""

    records: list[dict[str, object]] = []
    factors = [str(row["id"]) for row in contract.spec["factor_diagnostics"]["factors"]]
    minimum_size = int(contract.spec["factor_diagnostics"]["minimum_cross_section_size"])
    for fold in contract.spec["evaluation"]["chronological_folds"]:
        sample = features.loc[
            features["date"].between(fold["start"], fold["end"])
            & features["label_realization_date"].le(pd.Timestamp(fold["end"]))
        ]
        for factor in factors:
            values: list[float] = []
            for _, cross_section in sample.groupby("date", sort=True):
                valid = cross_section[[factor, "forward_return_20"]].dropna()
                if (
                    len(valid) >= minimum_size
                    and valid[factor].nunique() >= 2
                    and valid["forward_return_20"].nunique() >= 2
                ):
                    value = valid[factor].corr(valid["forward_return_20"], method="spearman")
                    if pd.notna(value):
                        values.append(float(value))
            series = pd.Series(values, dtype=float)
            records.append(
                {
                    "fold": str(fold["id"]),
                    "factor_id": factor,
                    "observations": len(series),
                    "mean_rank_ic": float(series.mean()) if not series.empty else np.nan,
                    "median_rank_ic": float(series.median()) if not series.empty else np.nan,
                    "positive_share": float(series.gt(0.0).mean()) if not series.empty else np.nan,
                }
            )
    return pd.DataFrame(records)


def _cap_factor_weights(weights: pd.Series, maximum: float) -> pd.Series:
    result = pd.Series(0.0, index=weights.index)
    remaining = list(weights.index)
    remaining_total = 1.0
    raw = weights.clip(lower=0.0)
    while remaining:
        denominator = float(raw.loc[remaining].sum())
        proposed = (
            pd.Series(remaining_total / len(remaining), index=remaining)
            if denominator <= 1e-12
            else raw.loc[remaining] / denominator * remaining_total
        )
        capped = proposed.loc[proposed.gt(maximum + 1e-12)].index.tolist()
        if not capped:
            result.loc[remaining] = proposed
            break
        result.loc[capped] = maximum
        remaining_total -= maximum * len(capped)
        remaining = [factor for factor in remaining if factor not in capped]
    return result


def _rolling_ic_weights(
    ranked: pd.DataFrame,
    recipe: Mapping[str, object],
    contract: CN27DiscoveryContract,
) -> pd.DataFrame:
    factors = [str(value) for value in recipe["factor_pool"]]
    dates = pd.DatetimeIndex(sorted(ranked["date"].unique()))
    daily_ic = pd.DataFrame(index=dates, columns=factors, dtype=float)
    minimum_size = int(contract.spec["factor_diagnostics"]["minimum_cross_section_size"])
    for date, cross_section in ranked.groupby("date", sort=True):
        for factor in factors:
            valid = cross_section[[factor, "forward_return_20"]].dropna()
            if (
                len(valid) >= minimum_size
                and valid[factor].nunique() >= 2
                and valid["forward_return_20"].nunique() >= 2
            ):
                daily_ic.loc[pd.Timestamp(date), factor] = valid[factor].corr(
                    valid["forward_return_20"], method="spearman"
                )
    policy = contract.spec["dynamic_factor_weighting"]
    available = daily_ic.shift(int(policy["label_availability_delay_sessions"]))
    rolling = available.rolling(
        int(policy["lookback_sessions"]),
        min_periods=int(policy["minimum_observations"]),
    ).mean()
    positive = rolling.clip(lower=0.0)
    normalized = positive.div(positive.sum(axis=1).replace(0.0, np.nan), axis=0)
    equal = pd.DataFrame(1.0 / len(factors), index=dates, columns=factors)
    normalized = normalized.fillna(equal)
    shrinkage = float(policy["equal_prior_shrinkage"])
    shrunk = normalized * (1.0 - shrinkage) + equal * shrinkage
    return shrunk.apply(
        _cap_factor_weights,
        axis=1,
        maximum=float(policy["maximum_factor_weight"]),
    )


def score_v1_2_features(
    features: pd.DataFrame,
    recipe: Mapping[str, object],
    contract: CN27DiscoveryContract,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """Create daily cross-sectional scores without using unavailable labels."""

    scored = features.copy()
    mode = str(recipe.get("factor_mode", "fixed"))
    if mode == "fixed":
        factor_weights = {
            str(key): float(value)
            for key, value in dict(recipe.get("factors", {})).items()
        }
        rank_columns: list[str] = []
        for factor, weight in factor_weights.items():
            column = f"rank_{factor}"
            scored[column] = scored.groupby("date", sort=False)[factor].rank(
                method="average", pct=True
            ) * float(weight)
            rank_columns.append(column)
        scored["composite_score"] = scored[rank_columns].sum(
            axis=1, min_count=len(rank_columns)
        )
        return scored, None
    if mode != "trailing_positive_rank_ic":
        raise ValueError(f"unsupported V1.2 factor mode: {mode}")
    factors = [str(value) for value in recipe["factor_pool"]]
    rank_columns = []
    for factor in factors:
        column = f"rank_{factor}"
        scored[column] = scored.groupby("date", sort=False)[factor].rank(
            method="average", pct=True
        )
        rank_columns.append(column)
    weights = _rolling_ic_weights(scored, recipe, contract)
    weight_lookup = weights.to_dict(orient="index")
    composite = pd.Series(0.0, index=scored.index)
    complete = pd.Series(True, index=scored.index)
    for factor, rank_column in zip(factors, rank_columns, strict=True):
        daily_weight = scored["date"].map(
            {date: values[factor] for date, values in weight_lookup.items()}
        )
        composite += scored[rank_column].fillna(0.0) * daily_weight
        complete &= scored[rank_column].notna()
    scored["composite_score"] = composite.where(complete)
    return scored, weights


def _select_v1_2_target_weights(
    cross_section: pd.DataFrame,
    recipe: Mapping[str, object],
    held_symbols: set[str],
    sector_by_symbol: Mapping[str, str],
    *,
    equity_exposure: float,
    maximum_single_weight: float,
) -> dict[str, float]:
    ranked = cross_section.dropna(subset=["composite_score", "volatility_20"]).copy()
    if str(recipe["absolute_momentum_filter"]) != "none":
        raise ValueError("V1.2 supports only the frozen no-filter policy")
    ranked = ranked.sort_values(["composite_score", "symbol"], ascending=[False, True])
    ranked["rank"] = np.arange(1, len(ranked) + 1)
    rank_by_symbol = dict(zip(ranked["symbol"], ranked["rank"], strict=True))
    top_k = int(recipe["top_k"])
    buffer_rank = top_k + int(recipe["exit_rank_buffer"])
    maximum_names = int(recipe["maximum_names_per_sector"])
    selected: list[str] = []
    sector_counts: dict[str, int] = {}
    retained = sorted(
        (
            symbol
            for symbol in held_symbols
            if rank_by_symbol.get(symbol, buffer_rank + 1) <= buffer_rank
        ),
        key=lambda symbol: (rank_by_symbol[symbol], symbol),
    )
    for symbol in (*retained, *ranked["symbol"].tolist()):
        if len(selected) >= top_k:
            break
        if symbol in selected:
            continue
        sector = sector_by_symbol[symbol]
        if sector_counts.get(sector, 0) >= maximum_names:
            continue
        selected.append(symbol)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
    exposure = min(float(equity_exposure), maximum_single_weight * len(selected))
    weighting = str(recipe["weighting"])
    if weighting == "equal":
        return {symbol: exposure / len(selected) for symbol in selected} if selected else {}
    volatility_column = {
        "inverse_volatility_20": "volatility_20",
        "inverse_volatility_60": "volatility_60",
    }.get(weighting)
    if volatility_column is None:
        raise ValueError(f"unsupported V1.2 weighting: {weighting}")
    volatility = dict(zip(ranked["symbol"], ranked[volatility_column], strict=True))
    return _capped_inverse_volatility_weights(
        selected,
        volatility,
        exposure=exposure,
        cap=maximum_single_weight,
    )


def _reference_volatility_exposure(
    bars: pd.DataFrame,
    contract: CN27DiscoveryContract,
) -> pd.Series:
    policy = contract.spec["portfolio_constraints"]["reference_volatility_target"]
    reference = (
        bars.loc[bars["symbol"].eq(contract.market_reference_symbol)]
        .sort_values("date")
        .set_index("date")["close"]
    )
    volatility = reference.pct_change(fill_method=None).rolling(
        int(policy["lookback_sessions"]),
        min_periods=int(policy["lookback_sessions"]),
    ).std(ddof=0) * np.sqrt(252)
    return (
        float(policy["target_annual_volatility"]) / volatility.replace(0.0, np.nan)
    ).clip(
        lower=float(policy["minimum_equity_exposure"]),
        upper=float(policy["maximum_equity_exposure"]),
    ).fillna(float(policy["minimum_equity_exposure"]))


def execute_target_with_deferral(
    before: Mapping[str, float],
    target: Mapping[str, float],
    tradable: Mapping[str, bool],
    *,
    candidate_symbols: tuple[str, ...],
    defensive_symbol: str,
    cost_spec: Mapping[str, float],
) -> tuple[dict[str, float], float, float, bool, float]:
    """Move tradable assets toward target and keep retrying any locked differences."""

    assets = (*candidate_symbols, defensive_symbol)
    fixed_total = sum(float(before[symbol]) for symbol in assets if not tradable[symbol])
    available = max(0.0, 1.0 - fixed_total)
    requested = sum(float(target[symbol]) for symbol in assets if tradable[symbol])
    scale = available / requested if requested > 1e-12 else 0.0
    after = {
        symbol: (
            float(before[symbol])
            if not tradable[symbol]
            else float(target[symbol]) * scale
        )
        for symbol in assets
    }
    after["CASH"] = max(0.0, 1.0 - sum(after.values()))
    cost, turnover, _, _ = _one_way_cost(
        before,
        after,
        candidate_symbols=candidate_symbols,
        defensive_symbol=defensive_symbol,
        cost_spec=cost_spec,
    )
    drift = sum(
        abs(float(after.get(symbol, 0.0)) - float(target.get(symbol, 0.0)))
        for symbol in (*assets, "CASH")
    )
    return after, float(cost), float(turnover), drift > 1e-10, float(drift)


def run_robustness_recipe(
    bars: pd.DataFrame,
    features: pd.DataFrame,
    contract: CN27DiscoveryContract,
    recipe: Mapping[str, object],
    *,
    end_date: str,
    window_names: tuple[str, ...],
    cost_multiplier: float = 1.0,
    execution_delay_sessions: int = 1,
    rebalance_phase_offset: int = 0,
    scored_features: pd.DataFrame | None = None,
) -> DiscoveryBacktestResult:
    """Run a recipe with real target deferral and configurable timing perturbations."""

    if cost_multiplier <= 0.0:
        raise ValueError("cost multiplier must be positive")
    if execution_delay_sessions < 1:
        raise ValueError("execution delay must be at least one session")
    clean = normalise_long_bars(bars)
    assets = (*contract.candidate_symbols, contract.defensive_symbol)
    required = set(assets) | {contract.market_reference_symbol}
    if missing := sorted(required - set(clean["symbol"])):
        raise ValueError(f"robustness bars missing required instruments: {missing}")
    by_symbol = {
        symbol: clean.loc[clean["symbol"].eq(symbol)].set_index("date").sort_index()
        for symbol in required
    }
    start = pd.Timestamp(contract.spec["windows"]["development"]["start"])
    cutoff = pd.Timestamp(end_date)
    calendar = pd.DatetimeIndex(by_symbol[contract.defensive_symbol].index)
    calendar = calendar[(calendar >= start) & (calendar <= cutoff)].sort_values().unique()
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
    scored = scored_features
    if scored is None:
        scored, _ = score_v1_2_features(features, recipe, contract)
    cross_sections = {
        pd.Timestamp(date): frame.copy()
        for date, frame in scored.loc[scored["date"].isin(calendar)].groupby(
            "date", sort=True
        )
    }
    sector_by_symbol = {
        str(row["symbol"]).zfill(6): str(row["sector"]) for row in contract.pool["symbols"]
    }
    reference_exposure = (
        _reference_volatility_exposure(clean, contract)
        if str(recipe["equity_exposure"]) == "reference_volatility_target_0_18"
        else None
    )
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
                "equity_exposure": sum(
                    after[symbol] for symbol in contract.candidate_symbols
                ),
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

        rebalance_sessions = int(recipe["rebalance_sessions"])
        if step >= rebalance_phase_offset and (
            step - rebalance_phase_offset
        ) % rebalance_sessions == 0:
            cross_section = cross_sections.get(date)
            if cross_section is not None:
                exposure_policy = str(recipe["equity_exposure"])
                if exposure_policy == "fixed_0_75":
                    exposure = float(constraints["maximum_equity_exposure"])
                elif exposure_policy == "reference_volatility_target_0_18":
                    assert reference_exposure is not None
                    exposure = float(reference_exposure.get(date, 0.0))
                else:
                    raise ValueError(
                        f"unsupported equity exposure policy: {exposure_policy}"
                    )
                stock_target = _select_v1_2_target_weights(
                    cross_section,
                    recipe,
                    set(holdings),
                    sector_by_symbol,
                    equity_exposure=exposure,
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
    return DiscoveryBacktestResult(
        recipe_id=str(recipe["id"]),
        daily=daily,
        metrics_by_window={
            name: _window_metrics(daily, contract, name) for name in window_names
        },
    )


def _factor_stability_summary(diagnostics: pd.DataFrame) -> pd.DataFrame:
    return (
        diagnostics.groupby("factor_id", as_index=False)
        .agg(
            positive_fold_count=("mean_rank_ic", lambda values: int((values > 0.0).sum())),
            median_fold_mean_rank_ic=("mean_rank_ic", "median"),
            worst_fold_mean_rank_ic=("mean_rank_ic", "min"),
            best_fold_mean_rank_ic=("mean_rank_ic", "max"),
            mean_daily_positive_share=("positive_share", "mean"),
        )
        .sort_values(
            ["positive_fold_count", "median_fold_mean_rank_ic", "factor_id"],
            ascending=[False, False, True],
        )
        .reset_index(drop=True)
    )


def _block_bootstrap_sharpe(
    returns: pd.Series,
    *,
    samples: int,
    block_sessions: int,
    seed: int,
) -> dict[str, Any]:
    values = returns.to_numpy(dtype=float)
    length = len(values)
    random = np.random.default_rng(seed)
    sharpes = np.empty(samples, dtype=float)
    daily_risk_free = np.log1p(0.02) / 252.0
    blocks_needed = int(np.ceil(length / block_sessions))
    for sample in range(samples):
        starts = random.integers(0, length, size=blocks_needed)
        indices = np.concatenate(
            [np.arange(start, start + block_sessions) % length for start in starts]
        )[:length]
        log_returns = np.log1p(values[indices])
        volatility = float(log_returns.std(ddof=0))
        sharpes[sample] = (
            (float(log_returns.mean()) - daily_risk_free) / volatility * np.sqrt(252)
            if volatility > 1e-12
            else np.nan
        )
    valid = sharpes[np.isfinite(sharpes)]
    return {
        "method": "circular_moving_block_bootstrap",
        "samples": int(samples),
        "block_sessions": int(block_sessions),
        "seed": int(seed),
        "sharpe_percentile_05": float(np.quantile(valid, 0.05)),
        "sharpe_percentile_50": float(np.quantile(valid, 0.50)),
        "sharpe_percentile_95": float(np.quantile(valid, 0.95)),
        "probability_sharpe_above_zero": float(np.mean(valid > 0.0)),
        "probability_sharpe_above_one": float(np.mean(valid > 1.0)),
        "interpretation": "uncertainty conditional on consumed history; not a fresh validation",
    }


def _fixed_factor_weight_rows(recipe: Mapping[str, object]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": "fixed", "factor_id": str(factor), "weight": float(weight)}
            for factor, weight in dict(recipe.get("factors", {})).items()
        ]
    )


def run_v1_2_screen(
    contract_path: str | Path,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run the frozen V1.2 candidate and robustness matrix on consumed history."""

    contract = load_v1_2_contract(contract_path)
    return _run_frozen_screen(contract, output_dir=output_dir)


def run_v1_3_screen(
    contract_path: str | Path,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run the frozen second-order factor-stability screen."""

    contract = load_v1_3_contract(contract_path)
    return _run_frozen_screen(contract, output_dir=output_dir)


def _run_frozen_screen(
    contract: CN27DiscoveryContract,
    *,
    output_dir: str | Path | None,
) -> dict[str, Any]:
    bars = pd.read_csv(contract.prices_path, dtype={"symbol": str}, parse_dates=["date"])
    features = compute_v1_2_features(bars, contract)
    diagnostics = v1_2_factor_diagnostics(features, contract)
    stability = _factor_stability_summary(diagnostics)
    fold_ids = tuple(
        str(row["id"]) for row in contract.spec["evaluation"]["chronological_folds"]
    )
    window_names = ("development", *fold_ids)
    score_cache: dict[str, tuple[pd.DataFrame, pd.DataFrame | None]] = {}
    results: dict[str, tuple[DiscoveryBacktestResult, pd.DataFrame | None]] = {}
    rows: list[dict[str, Any]] = []
    gate = contract.spec["selection_gate"]
    phase_fractions = contract.spec["robustness_tests"]["rebalance_phase_fractions"]

    for recipe in contract.spec["candidate_recipes"]:
        mode = str(recipe["factor_mode"])
        factor_definition = recipe.get("factors", recipe.get("factor_pool", []))
        score_key = json.dumps(
            {"mode": mode, "factor_definition": factor_definition},
            sort_keys=True,
        )
        if score_key not in score_cache:
            score_cache[score_key] = score_v1_2_features(features, recipe, contract)
        scored, factor_weights = score_cache[score_key]

        def execute(
            *, cost_multiplier: float = 1.0, delay: int = 1, phase: int = 0
        ) -> DiscoveryBacktestResult:
            return run_robustness_recipe(
                bars,
                features,
                contract,
                recipe,
                end_date=str(contract.spec["evaluation"]["full_window"]["end"]),
                window_names=window_names,
                cost_multiplier=cost_multiplier,
                execution_delay_sessions=delay,
                rebalance_phase_offset=phase,
                scored_features=scored,
            )

        base = execute()
        stress = execute(cost_multiplier=float(contract.spec["costs"]["stress_multiplier"]))
        delayed = execute(delay=2)
        period = int(recipe["rebalance_sessions"])
        phase_offsets = sorted(
            {int(round(period * float(fraction))) for fraction in phase_fractions}
        )
        phase_sharpes: dict[str, float] = {"0": base.metrics_by_window["development"]["sharpe_log_excess"]}
        for phase in phase_offsets:
            if phase == 0:
                continue
            phase_result = execute(phase=phase)
            phase_sharpes[str(phase)] = float(
                phase_result.metrics_by_window["development"]["sharpe_log_excess"]
            )
        full = base.metrics_by_window["development"]
        double_cost_sharpe = float(
            stress.metrics_by_window["development"]["sharpe_log_excess"]
        )
        delay_two_sharpe = float(
            delayed.metrics_by_window["development"]["sharpe_log_excess"]
        )
        fold_sharpes = [
            float(base.metrics_by_window[fold]["sharpe_log_excess"]) for fold in fold_ids
        ]
        fold_positive_share = float(np.mean(np.asarray(fold_sharpes) > 0.0))
        fold_25 = float(np.quantile(fold_sharpes, 0.25))
        worst_timing = min(delay_two_sharpe, *phase_sharpes.values())
        minimum_robustness = min(double_cost_sharpe, worst_timing)
        factors = list(recipe.get("factors", recipe.get("factor_pool", [])))
        stable_factors = stability.loc[
            stability["factor_id"].isin(factors) & stability["positive_fold_count"].ge(4)
        ]
        stable_factor_share = len(stable_factors) / len(factors) if factors else 0.0
        failures: list[str] = []
        checks = [
            (
                float(full["annual_one_way_turnover"])
                <= float(gate["maximum_full_window_annual_one_way_turnover"]),
                "turnover",
            ),
            (
                abs(float(full["maximum_drawdown"]))
                <= float(gate["maximum_full_window_drawdown_magnitude"]),
                "drawdown",
            ),
            (
                float(full["sharpe_log_excess"])
                >= float(gate["minimum_full_window_sharpe_log_excess"]),
                "full_sharpe",
            ),
            (
                double_cost_sharpe
                >= float(gate["minimum_double_cost_full_window_sharpe_log_excess"]),
                "double_cost_sharpe",
            ),
            (
                fold_positive_share >= float(gate["minimum_positive_fold_share"]),
                "positive_fold_share",
            ),
            (
                fold_25 >= float(gate["minimum_fold_sharpe_25th_percentile"]),
                "fold_sharpe_25th_percentile",
            ),
            (
                worst_timing
                >= float(gate["minimum_worst_timing_perturbation_sharpe"]),
                "timing_perturbation_sharpe",
            ),
        ]
        if "minimum_stable_selected_factor_share" in gate:
            checks.append(
                (
                    stable_factor_share
                    >= float(gate["minimum_stable_selected_factor_share"]),
                    "stable_selected_factor_share",
                )
            )
        failures.extend(name for passed, name in checks if not passed)
        rows.append(
            {
                "recipe_id": str(recipe["id"]),
                "factor_mode": mode,
                "full_total_return": float(full["total_return"]),
                "full_cagr": float(full["cagr"]),
                "full_annual_volatility": float(full["annual_volatility"]),
                "full_sharpe_log_excess": float(full["sharpe_log_excess"]),
                "full_maximum_drawdown": float(full["maximum_drawdown"]),
                "full_annual_one_way_turnover": float(full["annual_one_way_turnover"]),
                "full_transaction_cost_paid": float(full["transaction_cost_paid"]),
                "double_cost_full_sharpe": double_cost_sharpe,
                "delay_two_full_sharpe": delay_two_sharpe,
                "phase_sharpes": json.dumps(phase_sharpes, sort_keys=True),
                "worst_timing_perturbation_sharpe": worst_timing,
                "minimum_robustness_sharpe": minimum_robustness,
                "fold_sharpes": json.dumps(fold_sharpes),
                "minimum_fold_sharpe": min(fold_sharpes),
                "fold_sharpe_25th_percentile": fold_25,
                "median_fold_sharpe": float(np.median(fold_sharpes)),
                "positive_fold_share": fold_positive_share,
                "stable_selected_factor_share": stable_factor_share,
                "selection_gate_passed": not failures,
                "failure_reasons": "+".join(failures),
            }
        )
        results[str(recipe["id"])] = (base, factor_weights)

    summary = pd.DataFrame(rows).sort_values(
        [
            "selection_gate_passed",
            "minimum_robustness_sharpe",
            "fold_sharpe_25th_percentile",
            "full_annual_one_way_turnover",
            "full_maximum_drawdown",
            "recipe_id",
        ],
        ascending=[False, False, False, True, False, True],
    ).reset_index(drop=True)
    passing = summary.loc[summary["selection_gate_passed"]]
    selected_id = str(passing.iloc[0]["recipe_id"]) if not passing.empty else None
    selected_recipe = next(
        (
            dict(recipe)
            for recipe in contract.spec["candidate_recipes"]
            if recipe["id"] == selected_id
        ),
        None,
    )
    selection: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": str(contract.spec["experiment_id"]),
        "decision": (
            "retrospective_candidate_identified"
            if selected_recipe is not None
            else "no_candidate_passed_frozen_robustness_gate"
        ),
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
    diagnostics.to_csv(output / "factor_diagnostics.csv", index=False)
    stability.to_csv(output / "factor_stability_summary.csv", index=False)
    summary.to_csv(output / "candidate_summary.csv", index=False)
    write_json(output / "selected_recipe.json", selection)

    if selected_id is not None:
        selected_result, selected_weights = results[selected_id]
        selected_result.daily.reset_index().to_csv(
            output / "selected_daily.csv", index=False, date_format="%Y-%m-%d"
        )
        if selected_weights is None:
            weight_rows = _fixed_factor_weight_rows(selected_recipe or {})
        else:
            weight_rows = (
                selected_weights.rename_axis("date")
                .reset_index()
                .melt(id_vars="date", var_name="factor_id", value_name="weight")
            )
            weight_rows["date"] = pd.to_datetime(weight_rows["date"]).dt.strftime("%Y-%m-%d")
        weight_rows.to_csv(output / "selected_factor_weights.csv", index=False)
        bootstrap_policy = contract.spec["robustness_tests"]["block_bootstrap"]
        bootstrap = _block_bootstrap_sharpe(
            selected_result.daily["net_return"],
            samples=int(bootstrap_policy["samples"]),
            block_sessions=int(bootstrap_policy["block_sessions"]),
            seed=int(bootstrap_policy["seed"]),
        )
    else:
        pd.DataFrame(columns=["date"]).to_csv(output / "selected_daily.csv", index=False)
        pd.DataFrame(columns=["date", "factor_id", "weight"]).to_csv(
            output / "selected_factor_weights.csv", index=False
        )
        bootstrap = {"available": False, "reason": "no candidate passed frozen gate"}
    write_json(output / "bootstrap.json", bootstrap)

    control_id = str(contract.spec["candidate_recipes"][0]["id"])
    control = summary.loc[summary["recipe_id"].eq(control_id)].iloc[0]
    decision = {
        "schema_version": "1.0",
        "decision": selection["decision"],
        "selected_recipe_id": selected_id,
        "all_selection_gates_passed": selected_id is not None,
        "control_recipe_audit": {
            "recipe_id": control_id,
            "full_sharpe_log_excess": float(control["full_sharpe_log_excess"]),
            "annual_one_way_turnover": float(control["full_annual_one_way_turnover"]),
            "maximum_drawdown": float(control["full_maximum_drawdown"]),
        },
        "fresh_historical_holdout": False,
        "prospective_validation_required": True,
        "automatic_promotion_allowed": False,
        "research_only": True,
        "trade_ready": False,
    }
    if control_id == "r0_v1_1_corrected_control":
        decision["control_recipe_audit"]["trade_lock_episodes"] = 3
    write_json(output / "decision.json", decision)
    leader = summary.iloc[0]
    report = "\n".join(
        [
            "# CN_27 V1.2 retrospective robustness discovery",
            "",
            f"- Decision: `{selection['decision']}`",
            f"- Selected recipe: `{selected_id}`",
            "- Fresh historical holdout: `false`",
            "- Research only: `true`; trade ready: `false`",
            "",
            "## Frozen-gate leader",
            "",
            f"- Full-window Sharpe: {float(leader['full_sharpe_log_excess']):.4f}",
            f"- Annual one-way turnover: {float(leader['full_annual_one_way_turnover']):.4f}x",
            f"- Maximum drawdown: {float(leader['full_maximum_drawdown']):.2%}",
            f"- Fold Sharpe 25th percentile: {float(leader['fold_sharpe_25th_percentile']):.4f}",
            f"- Worst timing perturbation Sharpe: {float(leader['worst_timing_perturbation_sharpe']):.4f}",
            "",
            "## Interpretation boundary",
            "",
            "All six folds and all robustness variants use already-consumed history. This run can",
            "reject fragile ideas and nominate a retrospective candidate, but cannot create a fresh",
            "holdout or authorize promotion. Any candidate still requires unchanged prospective data.",
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
        "experiment_id": str(contract.spec["experiment_id"]),
        "identity": {
            "contract_sha256": sha256_file(contract.spec_path),
            "pool_sha256": sha256_file(contract.pool_path),
            "source_prices_sha256": sha256_file(contract.prices_path),
            "predecessor_manifest_file_sha256": str(
                contract.spec["lineage"]["predecessor_manifest_file_sha256"]
            ),
            "implementation_sha256": sha256_file(Path(__file__)),
        },
        "outputs": {name: sha256_file(output / name) for name in output_names},
        "selection_identity_sha256": selection["selection_identity_sha256"],
        "decision": selection["decision"],
        "research_only": True,
        "trade_ready": False,
    }
    manifest["manifest_identity_sha256"] = canonical_sha256(manifest)
    write_json(output / "evidence_manifest.json", manifest)
    return {
        "decision": selection["decision"],
        "selected_recipe_id": selected_id,
        "leader": leader.to_dict(),
        "bootstrap": bootstrap,
        "manifest_identity_sha256": manifest["manifest_identity_sha256"],
        "research_only": True,
        "trade_ready": False,
    }
