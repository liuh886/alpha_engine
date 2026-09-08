"""Governed factor and strategy discovery for a lower-turnover CN_27 successor."""

from __future__ import annotations

import json
from dataclasses import dataclass
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


@dataclass(frozen=True)
class CN27DiscoveryContract:
    spec: dict[str, Any]
    pool: dict[str, Any]
    spec_path: Path
    pool_path: Path
    prices_path: Path
    candidate_symbols: tuple[str, ...]
    defensive_symbol: str
    market_reference_symbol: str


@dataclass
class DiscoveryBacktestResult:
    recipe_id: str
    daily: pd.DataFrame
    metrics_by_window: dict[str, dict[str, Any]]


def _repository_root(path: Path) -> Path:
    for candidate in (path.resolve().parent, *path.resolve().parents):
        if (candidate / "AGENTS.md").is_file() and (candidate / "configs").is_dir():
            return candidate
    raise ValueError(f"cannot resolve repository root from {path}")


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected YAML mapping: {path}")
    return payload


def load_discovery_contract(path: str | Path) -> CN27DiscoveryContract:
    spec_path = Path(path).resolve()
    spec = _load_yaml(spec_path)
    root = _repository_root(spec_path)
    identity = spec.get("identity", {})
    pool_path = (root / str(identity.get("pool_spec", ""))).resolve()
    prices_path = (root / str(identity.get("source_prices", ""))).resolve()
    pool = _load_yaml(pool_path)
    if spec.get("status") != "frozen_pre_screen":
        raise ValueError("CN_27 discovery contract must be frozen before screening")
    if spec.get("research_only") is not True or spec.get("trade_ready") is not False:
        raise ValueError("CN_27 discovery must remain research-only")
    if sha256_file(pool_path) != str(identity.get("pool_sha256")):
        raise ValueError("CN_27 discovery pool hash mismatch")
    if sha256_file(prices_path) != str(identity.get("source_prices_sha256")):
        raise ValueError("CN_27 discovery source price hash mismatch")
    symbols = tuple(str(row["symbol"]).zfill(6) for row in pool["symbols"])
    if len(symbols) != 27 or len(set(symbols)) != 27:
        raise ValueError("CN_27 discovery requires exactly 27 unique candidates")
    factor_ids = [str(row["id"]) for row in spec["factor_diagnostics"]["factors"]]
    if len(factor_ids) != len(set(factor_ids)):
        raise ValueError("CN_27 discovery factor IDs must be unique")
    recipe_ids = [str(row["id"]) for row in spec["candidate_recipes"]]
    if len(recipe_ids) != len(set(recipe_ids)):
        raise ValueError("CN_27 discovery recipe IDs must be unique")
    return CN27DiscoveryContract(
        spec=spec,
        pool=pool,
        spec_path=spec_path,
        pool_path=pool_path,
        prices_path=prices_path,
        candidate_symbols=symbols,
        defensive_symbol=str(identity["defensive_etf"]).zfill(6),
        market_reference_symbol=str(identity["market_reference"]).zfill(6),
    )


def _downside_deviation(returns: pd.Series, window: int) -> pd.Series:
    downside_square = returns.clip(upper=0.0).pow(2)
    return downside_square.rolling(window, min_periods=window).mean().pow(0.5) * np.sqrt(252)


def compute_discovery_features(
    bars: pd.DataFrame,
    contract: CN27DiscoveryContract,
) -> pd.DataFrame:
    """Build scale-free, trailing-only factor values and delayed forward labels."""

    clean = normalise_long_bars(bars)
    rows: list[pd.DataFrame] = []
    horizon = int(contract.spec["factor_diagnostics"]["forward_horizon_sessions"])
    delay = int(contract.spec["factor_diagnostics"]["execution_delay_sessions"])
    for symbol in contract.candidate_symbols:
        item = clean.loc[clean["symbol"].eq(symbol)].sort_values("date").copy()
        if item.empty:
            raise ValueError(f"CN_27 candidate has no bars: {symbol}")
        close, open_price, volume = item["close"], item["open"], item["volume"]
        returns = close.pct_change(fill_method=None)
        sma20 = close.rolling(20, min_periods=20).mean()
        sma60 = close.rolling(60, min_periods=60).mean()
        vol20 = returns.rolling(20, min_periods=20).std(ddof=0) * np.sqrt(252)
        vol60 = returns.rolling(60, min_periods=60).std(ddof=0) * np.sqrt(252)
        item["momentum_5"] = close.pct_change(5, fill_method=None)
        item["momentum_20"] = close.pct_change(20, fill_method=None)
        item["momentum_60"] = close.pct_change(60, fill_method=None)
        item["momentum_120"] = close.pct_change(120, fill_method=None)
        item["trend_20"] = close / sma20 - 1.0
        item["trend_60"] = close / sma60 - 1.0
        item["slope_20_10"] = sma20 / sma20.shift(10) - 1.0
        item["low_volatility_20"] = -vol20
        item["low_volatility_60"] = -vol60
        item["low_downside_20"] = -_downside_deviation(returns, 20)
        item["low_downside_60"] = -_downside_deviation(returns, 60)
        item["drawdown_60"] = close / close.rolling(60, min_periods=60).max() - 1.0
        item["drawdown_120"] = close / close.rolling(120, min_periods=120).max() - 1.0
        item["risk_adjusted_momentum_20"] = item["momentum_20"] / vol20.replace(0.0, np.nan)
        item["risk_adjusted_momentum_60"] = item["momentum_60"] / vol60.replace(0.0, np.nan)
        volume_ratio = volume / volume.rolling(20, min_periods=20).mean() - 1.0
        item["volume_confirmation_20"] = item["momentum_20"] * volume_ratio
        item["volatility_20"] = vol20
        item["forward_return_10"] = (
            open_price.shift(-(delay + horizon)) / open_price.shift(-delay) - 1.0
        )
        rows.append(item)
    return pd.concat(rows, ignore_index=True).sort_values(["date", "symbol"]).reset_index(
        drop=True
    )


def factor_rank_ic_diagnostics(
    features: pd.DataFrame,
    contract: CN27DiscoveryContract,
    *,
    window_names: tuple[str, ...] = ("development", "selection_validation"),
) -> pd.DataFrame:
    """Calculate daily cross-sectional Spearman IC without reading the locked test."""

    records: list[dict[str, Any]] = []
    factor_rows = contract.spec["factor_diagnostics"]["factors"]
    minimum_size = int(contract.spec["factor_diagnostics"]["minimum_cross_section_size"])
    for window_name in window_names:
        window = contract.spec["windows"][window_name]
        sample = features.loc[features["date"].between(window["start"], window["end"])]
        for factor in factor_rows:
            factor_id = str(factor["id"])
            daily_values: list[float] = []
            for _, cross_section in sample.groupby("date", sort=True):
                valid = cross_section[[factor_id, "forward_return_10"]].dropna()
                if len(valid) < minimum_size:
                    continue
                if valid[factor_id].nunique() < 2 or valid["forward_return_10"].nunique() < 2:
                    continue
                value = valid[factor_id].corr(valid["forward_return_10"], method="spearman")
                if pd.notna(value):
                    daily_values.append(float(value) * int(factor["direction"]))
            values = pd.Series(daily_values, dtype=float)
            records.append(
                {
                    "window": window_name,
                    "factor_id": factor_id,
                    "information_family": str(factor["family"]),
                    "observations": int(len(values)),
                    "mean_rank_ic": float(values.mean()) if not values.empty else np.nan,
                    "median_rank_ic": float(values.median()) if not values.empty else np.nan,
                    "positive_share": float(values.gt(0.0).mean()) if not values.empty else np.nan,
                }
            )
    return pd.DataFrame(records)


def _cross_section_scores(features: pd.DataFrame, recipe: Mapping[str, Any]) -> pd.DataFrame:
    factor_weights = {str(key): float(value) for key, value in recipe["factors"].items()}
    scored = features.copy()
    if not factor_weights:
        scored["composite_score"] = 0.5
        return scored
    rank_columns: list[str] = []
    for factor_id, weight in factor_weights.items():
        rank_column = f"rank_{factor_id}"
        scored[rank_column] = scored.groupby("date", sort=False)[factor_id].rank(
            method="average", pct=True
        )
        rank_columns.append(rank_column)
        scored[rank_column] *= weight
    scored["composite_score"] = scored[rank_columns].sum(axis=1, min_count=len(rank_columns))
    return scored


def _regime_exposure(
    bars: pd.DataFrame,
    features: pd.DataFrame,
    contract: CN27DiscoveryContract,
) -> pd.Series:
    regime = contract.spec["regime_contract"]
    reference = (
        bars.loc[bars["symbol"].eq(contract.market_reference_symbol)]
        .sort_values("date")
        .set_index("date")["close"]
    )
    reference_sma = reference.rolling(
        int(regime["reference_sma_sessions"]),
        min_periods=int(regime["reference_sma_sessions"]),
    ).mean()
    reference_above = reference.gt(reference_sma)
    breadth_source = features[["date", "symbol", "trend_60"]].copy()
    breadth = breadth_source.assign(above=breadth_source["trend_60"].gt(0.0)).groupby(
        "date"
    )["above"].mean()
    dates = pd.DatetimeIndex(reference.index).sort_values().unique()
    exposure = pd.Series(float(regime["weak"]["equity_exposure"]), index=dates)
    medium_breadth = float(regime["medium"]["reference_above_sma_or_minimum_breadth"])
    medium = reference_above.reindex(dates).fillna(False) | breadth.reindex(dates).ge(
        medium_breadth
    ).fillna(False)
    strong = reference_above.reindex(dates).fillna(False) & breadth.reindex(dates).ge(
        float(regime["strong"]["minimum_breadth"])
    ).fillna(False)
    exposure.loc[medium] = float(regime["medium"]["equity_exposure"])
    exposure.loc[strong] = float(regime["strong"]["equity_exposure"])
    return exposure


def _capped_inverse_volatility_weights(
    symbols: list[str],
    volatility_by_symbol: Mapping[str, float],
    *,
    exposure: float,
    cap: float,
) -> dict[str, float]:
    if not symbols or exposure <= 0.0:
        return {}
    raw = {
        symbol: 1.0 / max(float(volatility_by_symbol[symbol]), 1e-6) for symbol in symbols
    }
    weights = {symbol: 0.0 for symbol in symbols}
    remaining = set(symbols)
    remaining_exposure = exposure
    while remaining:
        raw_total = sum(raw[symbol] for symbol in remaining)
        proposed = {
            symbol: remaining_exposure * raw[symbol] / raw_total for symbol in remaining
        }
        capped = {symbol for symbol, value in proposed.items() if value > cap + 1e-12}
        if not capped:
            weights.update(proposed)
            break
        for symbol in capped:
            weights[symbol] = cap
            remaining_exposure -= cap
            remaining.remove(symbol)
        if remaining_exposure <= 1e-12:
            break
    return weights


def _select_target_weights(
    cross_section: pd.DataFrame,
    recipe: Mapping[str, Any],
    held_symbols: set[str],
    sector_by_symbol: Mapping[str, str],
    *,
    equity_exposure: float,
    maximum_single_weight: float,
) -> dict[str, float]:
    ranked = cross_section.dropna(subset=["composite_score", "volatility_20"]).copy()
    momentum_filter = str(recipe["absolute_momentum_filter"])
    if momentum_filter == "momentum_60_positive":
        ranked = ranked.loc[ranked["momentum_60"].gt(0.0)]
    elif momentum_filter != "none":
        raise ValueError(f"unsupported absolute momentum filter: {momentum_filter}")
    ranked = ranked.sort_values(["composite_score", "symbol"], ascending=[False, True])
    ranked["rank"] = np.arange(1, len(ranked) + 1)
    rank_by_symbol = dict(zip(ranked["symbol"], ranked["rank"], strict=True))
    top_k = int(recipe["top_k"])
    buffer_rank = top_k + int(recipe["exit_rank_buffer"])
    cap_names = int(recipe["maximum_names_per_sector"])
    selected: list[str] = []
    sector_counts: dict[str, int] = {}

    retained = sorted(
        (symbol for symbol in held_symbols if rank_by_symbol.get(symbol, buffer_rank + 1) <= buffer_rank),
        key=lambda symbol: (rank_by_symbol[symbol], symbol),
    )
    for symbol in retained:
        sector = sector_by_symbol[symbol]
        if sector_counts.get(sector, 0) >= cap_names:
            continue
        selected.append(symbol)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
    for symbol in ranked["symbol"]:
        if len(selected) >= top_k:
            break
        if symbol in selected:
            continue
        sector = sector_by_symbol[symbol]
        if sector_counts.get(sector, 0) >= cap_names:
            continue
        selected.append(symbol)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1

    exposure = min(
        float(equity_exposure),
        float(maximum_single_weight) * len(selected),
    )
    if str(recipe["weighting"]) == "equal":
        return {symbol: exposure / len(selected) for symbol in selected} if selected else {}
    if str(recipe["weighting"]) == "inverse_volatility_20":
        volatility = dict(zip(ranked["symbol"], ranked["volatility_20"], strict=True))
        return _capped_inverse_volatility_weights(
            selected,
            volatility,
            exposure=exposure,
            cap=maximum_single_weight,
        )
    raise ValueError(f"unsupported weighting: {recipe['weighting']}")


def _window_metrics(
    daily: pd.DataFrame,
    contract: CN27DiscoveryContract,
    window_name: str,
) -> dict[str, Any]:
    window = contract.spec["windows"][window_name]
    sample = daily.loc[str(window["start"]) : str(window["end"])]
    if len(sample) != int(window["sessions"]):
        raise ValueError(
            f"{window_name} requires {window['sessions']} sessions, observed {len(sample)}"
        )
    metrics = _return_metrics(
        sample["net_return"],
        annual_sessions=252,
        annual_risk_free_rate=0.02,
    )
    years = len(sample) / 252.0
    metrics["annual_one_way_turnover"] = float(sample["one_way_turnover"].sum() / years)
    metrics["transaction_cost_paid"] = float(sample["transaction_cost"].sum())
    metrics["average_equity_exposure"] = float(sample["equity_exposure"].mean())
    metrics["average_holding_count"] = float(sample["holding_count"].mean())
    return metrics


def run_discovery_recipe(
    bars: pd.DataFrame,
    features: pd.DataFrame,
    contract: CN27DiscoveryContract,
    recipe: Mapping[str, Any],
    *,
    end_date: str,
    window_names: tuple[str, ...],
    cost_multiplier: float = 1.0,
) -> DiscoveryBacktestResult:
    """Run one scheduled-rebalance recipe with next-open execution and trade deferral."""

    if cost_multiplier <= 0.0:
        raise ValueError("cost multiplier must be positive")
    clean = normalise_long_bars(bars)
    assets = (*contract.candidate_symbols, contract.defensive_symbol)
    required = set(assets) | {contract.market_reference_symbol}
    if missing := sorted(required - set(clean["symbol"])):
        raise ValueError(f"discovery bars missing required instruments: {missing}")
    by_symbol = {
        symbol: clean.loc[clean["symbol"].eq(symbol)].set_index("date").sort_index()
        for symbol in required
    }
    start = pd.Timestamp(contract.spec["windows"]["development"]["start"])
    cutoff = pd.Timestamp(end_date)
    calendar = pd.DatetimeIndex(by_symbol[contract.defensive_symbol].index)
    calendar = calendar[(calendar >= start) & (calendar <= cutoff)].sort_values().unique()
    opens = {
        symbol: by_symbol[symbol]["open"].reindex(calendar).ffill() for symbol in assets
    }
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
    scored = _cross_section_scores(features, recipe)
    cross_sections = {
        pd.Timestamp(date): frame.copy()
        for date, frame in scored.loc[scored["date"].isin(calendar)].groupby("date", sort=True)
    }
    sector_by_symbol = {
        str(row["symbol"]).zfill(6): str(row["sector"]) for row in contract.pool["symbols"]
    }
    regime_exposure = _regime_exposure(clean, features, contract)
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
    pending_target = {symbol: 0.0 for symbol in contract.candidate_symbols}
    pending_target[contract.defensive_symbol] = 1.0
    pending_target["CASH"] = 0.0
    pending_execution = True
    daily_rows: list[dict[str, Any]] = []
    equity = 1.0

    for step, date in enumerate(calendar):
        relatives = {symbol: 1.0 + float(open_returns.loc[date, symbol]) for symbol in assets}
        gross_return = sum(weights[symbol] * (relatives[symbol] - 1.0) for symbol in assets)
        gross_factor = 1.0 + gross_return
        before = {symbol: weights[symbol] * relatives[symbol] / gross_factor for symbol in assets}
        before["CASH"] = weights["CASH"] / gross_factor
        if pending_execution:
            tradable = {
                symbol: bool(observed[symbol].loc[date]) and not bool(locked[symbol].loc[date])
                for symbol in assets
            }
            fixed_total = sum(before[symbol] for symbol in assets if not tradable[symbol])
            available = max(0.0, 1.0 - fixed_total)
            requested = sum(pending_target[symbol] for symbol in assets if tradable[symbol])
            scale = available / requested if requested > 1e-12 else 0.0
            after = {
                symbol: before[symbol]
                if not tradable[symbol]
                else pending_target[symbol] * scale
                for symbol in assets
            }
            after["CASH"] = max(0.0, 1.0 - sum(after.values()))
            cost, turnover, _, _ = _one_way_cost(
                before,
                after,
                candidate_symbols=contract.candidate_symbols,
                defensive_symbol=contract.defensive_symbol,
                cost_spec=cost_spec,
            )
            target_drift = sum(
                abs(after.get(symbol, 0.0) - pending_target.get(symbol, 0.0))
                for symbol in (*assets, "CASH")
            )
            pending_execution = False
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
                    {symbol: weights[symbol] for symbol in assets if weights[symbol] > 1e-12},
                    sort_keys=True,
                ),
                "asset_weights": json.dumps(
                    {symbol: after[symbol] for symbol in assets if after[symbol] > 1e-12},
                    sort_keys=True,
                ),
                "target_drift_due_to_trade_lock": target_drift,
            }
        )
        weights = after

        if step % int(recipe["rebalance_sessions"]) == 0:
            cross_section = cross_sections.get(date)
            if cross_section is not None:
                exposure_policy = str(recipe["equity_exposure"])
                if exposure_policy == "fixed_0_75":
                    exposure = float(constraints["maximum_equity_exposure"])
                elif exposure_policy == "market_regime_0_20_0_45_0_75":
                    exposure = float(regime_exposure.get(date, 0.0))
                else:
                    raise ValueError(f"unsupported equity exposure policy: {exposure_policy}")
                stock_target = _select_target_weights(
                    cross_section,
                    recipe,
                    set(holdings),
                    sector_by_symbol,
                    equity_exposure=exposure,
                    maximum_single_weight=float(constraints["maximum_single_security_weight"]),
                )
                pending_target = {
                    symbol: float(stock_target.get(symbol, 0.0))
                    for symbol in contract.candidate_symbols
                }
                pending_target[contract.defensive_symbol] = 1.0 - sum(stock_target.values())
                pending_target["CASH"] = 0.0
                pending_execution = True

    daily = pd.DataFrame(daily_rows).set_index("date")
    metrics_by_window = {
        name: _window_metrics(daily, contract, name) for name in window_names
    }
    return DiscoveryBacktestResult(
        recipe_id=str(recipe["id"]),
        daily=daily,
        metrics_by_window=metrics_by_window,
    )


def _select_screen_candidate(
    results: list[DiscoveryBacktestResult],
    contract: CN27DiscoveryContract,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    gate = contract.spec["selection_gate"]
    rows: list[dict[str, Any]] = []
    for result in results:
        metrics = result.metrics_by_window
        sharpes = [float(metrics[name]["sharpe_log_excess"]) for name in metrics]
        turnovers = [float(metrics[name]["annual_one_way_turnover"]) for name in metrics]
        drawdowns = [abs(float(metrics[name]["maximum_drawdown"])) for name in metrics]
        failures: list[str] = []
        if max(turnovers) > float(gate["maximum_annual_one_way_turnover_each_window"]):
            failures.append("turnover")
        if max(drawdowns) > float(gate["maximum_drawdown_magnitude_each_window"]):
            failures.append("drawdown")
        if min(sharpes) < float(gate["minimum_sharpe_each_selection_window"]):
            failures.append("sharpe")
        rows.append(
            {
                "recipe_id": result.recipe_id,
                "minimum_selection_sharpe": min(sharpes),
                "mean_selection_sharpe": float(np.mean(sharpes)),
                "maximum_annual_one_way_turnover": max(turnovers),
                "maximum_drawdown_magnitude": max(drawdowns),
                "selection_gate_passed": not failures,
                "failure_reasons": "+".join(failures),
            }
        )
    summary = pd.DataFrame(rows).sort_values(
        [
            "selection_gate_passed",
            "minimum_selection_sharpe",
            "mean_selection_sharpe",
            "maximum_annual_one_way_turnover",
            "maximum_drawdown_magnitude",
            "recipe_id",
        ],
        ascending=[False, False, False, True, True, True],
    )
    passing = summary.loc[summary["selection_gate_passed"]]
    selected_id = str(passing.iloc[0]["recipe_id"]) if not passing.empty else None
    recipe = next(
        (row for row in contract.spec["candidate_recipes"] if row["id"] == selected_id),
        None,
    )
    selection: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": str(contract.spec["experiment_id"]),
        "decision": "candidate_selected_for_locked_test" if recipe else "no_candidate_selected",
        "selected_recipe_id": selected_id,
        "selected_recipe": recipe,
        "ranking_rule": str(gate["primary_ranking"]),
        "locked_test_metrics_observed": False,
        "fresh_historical_holdout": False,
        "research_only": True,
        "trade_ready": False,
    }
    selection["selection_identity_sha256"] = canonical_sha256(selection)
    return summary.reset_index(drop=True), selection


def run_discovery_screen(
    contract_path: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Screen frozen recipes on development and validation without opening locked test."""

    contract = load_discovery_contract(contract_path)
    bars = pd.read_csv(contract.prices_path, dtype={"symbol": str}, parse_dates=["date"])
    validation_end = pd.Timestamp(
        contract.spec["windows"]["selection_validation"]["end"]
    )
    screen_bars = bars.loc[bars["date"].le(validation_end)].copy()
    features = compute_discovery_features(screen_bars, contract)
    diagnostics = factor_rank_ic_diagnostics(features, contract)
    window_names = ("development", "selection_validation")
    results = [
        run_discovery_recipe(
            screen_bars,
            features,
            contract,
            recipe,
            end_date=validation_end.date().isoformat(),
            window_names=window_names,
        )
        for recipe in contract.spec["candidate_recipes"]
    ]
    if any(result.daily.index.max() > validation_end for result in results):
        raise ValueError("screening emitted locked-test rows")
    metric_rows = [
        {"recipe_id": result.recipe_id, "window": window, **metrics}
        for result in results
        for window, metrics in result.metrics_by_window.items()
    ]
    metrics = pd.DataFrame(metric_rows)
    summary, selection = _select_screen_candidate(results, contract)
    screen_daily = pd.concat(
        [result.daily.reset_index().assign(recipe_id=result.recipe_id) for result in results],
        ignore_index=True,
    )

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    diagnostics.to_csv(output / "factor_diagnostics.csv", index=False)
    metrics.to_csv(output / "candidate_window_metrics.csv", index=False)
    summary.to_csv(output / "candidate_summary.csv", index=False)
    screen_daily.to_csv(output / "screen_daily.csv", index=False, date_format="%Y-%m-%d")
    write_json(output / "selection.json", selection)
    outputs = {
        name: sha256_file(output / name)
        for name in (
            "factor_diagnostics.csv",
            "candidate_window_metrics.csv",
            "candidate_summary.csv",
            "screen_daily.csv",
            "selection.json",
        )
    }
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "experiment_id": str(contract.spec["experiment_id"]),
        "stage": "development_and_selection_validation_screen",
        "latest_evaluated_date": validation_end.date().isoformat(),
        "locked_test_opened": False,
        "identity": discovery_identity(contract),
        "selection_identity_sha256": selection["selection_identity_sha256"],
        "outputs": outputs,
        "research_only": True,
        "trade_ready": False,
    }
    manifest["manifest_identity_sha256"] = canonical_sha256(manifest)
    write_json(output / "evidence_manifest.json", manifest)
    return {
        "decision": selection["decision"],
        "selected_recipe_id": selection["selected_recipe_id"],
        "selection_identity_sha256": selection["selection_identity_sha256"],
        "manifest_identity_sha256": manifest["manifest_identity_sha256"],
        "locked_test_opened": False,
        "research_only": True,
        "trade_ready": False,
    }


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


def discovery_identity(contract: CN27DiscoveryContract) -> dict[str, str]:
    identity = {
        "experiment_contract_sha256": sha256_file(contract.spec_path),
        "pool_sha256": sha256_file(contract.pool_path),
        "source_prices_sha256": sha256_file(contract.prices_path),
        "implementation_sha256": sha256_file(Path(__file__)),
    }
    identity["identity_sha256"] = canonical_sha256(identity)
    return identity
