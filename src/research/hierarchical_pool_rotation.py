"""Generic hierarchical cross-sectional rotation for versioned market pools."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from src.research.focus_watchlist_signal import (
    canonical_sha256,
    compute_focus_indicators,
    generate_signal_history,
    load_focus_signal_spec,
    load_long_ohlcv_csv,
    sha256_file,
    validate_focus_signal_spec,
)
from src.research.research_artifacts import write_json


BASKET_SCORE_FIELDS = (
    "median_relative_momentum_63_vs_benchmark",
    "median_momentum_20",
    "breadth_above_sma50",
    "median_drawdown_from_63d_high",
)
SECURITY_SCORE_FIELDS = (
    "relative_momentum_63_vs_benchmark",
    "momentum_20",
    "drawdown_from_63d_high",
    "realized_volatility_20",
)
EXPECTED_LAYERS = (
    "market_regime",
    "basket_cross_section",
    "security_cross_section",
    "security_timing",
)


def _load_yaml(path: str | Path, *, label: str) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a YAML mapping")
    return payload


def _repository_root(spec_path: Path) -> Path:
    resolved = spec_path.resolve()
    if len(resolved.parents) < 3:
        raise ValueError(f"cannot resolve repository root from {spec_path}")
    return resolved.parents[2]


def _candidate_symbols(pool: Mapping[str, Any]) -> list[str]:
    return [
        str(symbol)
        for basket in pool.get("baskets", {}).values()
        for symbol in basket.get("symbols", [])
    ]


def _validate_weighted_components(
    components: Mapping[str, Any],
    expected: tuple[str, ...],
    *,
    label: str,
) -> None:
    if set(components) != set(expected):
        raise ValueError(f"unexpected {label} components")
    weights = [float(components[field]["weight"]) for field in expected]
    if not np.isclose(sum(weights), 1.0):
        raise ValueError(f"{label} weights must sum to one")
    for field in expected:
        direction = str(components[field].get("direction", ""))
        if direction not in {"higher_is_better", "lower_is_better"}:
            raise ValueError(f"invalid {label} direction for {field}")


def validate_hierarchical_contract(
    spec: Mapping[str, Any],
    pool: Mapping[str, Any],
) -> None:
    if str(spec.get("market")) != str(pool.get("market")):
        raise ValueError("spec and pool market must match")
    if list(spec.get("architecture", {}).get("layers", [])) != list(EXPECTED_LAYERS):
        raise ValueError("unexpected hierarchical rotation architecture")
    if spec.get("architecture", {}).get("cross_market_ranking_allowed") is not False:
        raise ValueError("cross-market ranking must remain disabled")
    if spec.get("objective", {}).get("model_fitting") is not False:
        raise ValueError("deterministic v1/v2 cannot fit a model")

    baskets = pool.get("baskets", {})
    references = pool.get("references", {})
    if not isinstance(baskets, dict) or len(baskets) < 2:
        raise ValueError("pool must contain at least two baskets")
    if not isinstance(references, dict) or len(references) < 2:
        raise ValueError("pool must contain benchmark and context references")

    benchmark = str(spec.get("market_regime", {}).get("reference", ""))
    context = str(spec.get("sector_context", {}).get("reference", ""))
    if benchmark not in references:
        raise ValueError(f"benchmark {benchmark} is absent from pool references")
    if context not in references:
        raise ValueError(f"context {context} is absent from pool references")
    if references[benchmark].get("role") != "market_regime_and_benchmark":
        raise ValueError("benchmark reference role is invalid")

    candidates = _candidate_symbols(pool)
    if not candidates or len(candidates) != len(set(candidates)):
        raise ValueError("candidate symbols must be non-empty and unique")
    if set(candidates).intersection(references):
        raise ValueError("references cannot be trading candidates")
    for name, basket in baskets.items():
        if len(list(basket.get("symbols", []))) < 2:
            raise ValueError(f"basket {name} must contain at least two symbols")

    metadata = pool.get("symbol_metadata", {})
    if metadata and set(metadata) != set(candidates):
        raise ValueError("symbol metadata must match candidate membership")

    rotation = spec.get("rotation", {})
    if int(rotation.get("rebalance_every_n_benchmark_sessions", 0)) <= 0:
        raise ValueError("rotation frequency must be positive")
    if int(rotation.get("maximum_selected_baskets", 0)) <= 0:
        raise ValueError("maximum selected baskets must be positive")
    if int(rotation.get("maximum_selected_symbols_per_basket", 0)) <= 0:
        raise ValueError("maximum symbols per basket must be positive")
    _validate_weighted_components(
        rotation.get("score", {}).get("components", {}),
        BASKET_SCORE_FIELDS,
        label="basket score",
    )

    selection = spec.get("security_selection", {})
    if selection.get("state_is_absolute_filter_not_primary_rank") is not True:
        raise ValueError("state must remain an absolute filter")
    _validate_weighted_components(
        selection.get("cross_section", {}).get("components", {}),
        SECURITY_SCORE_FIELDS,
        label="security score",
    )
    if any(bool(value) for value in spec.get("parameter_search", {}).values()):
        raise ValueError("parameter search must remain disabled")


def load_hierarchical_contract(
    spec_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    resolved_spec = Path(spec_path).resolve()
    spec = _load_yaml(resolved_spec, label="hierarchical rotation spec")
    root = _repository_root(resolved_spec)
    pool_path = root / str(spec["pool_spec"])
    pool = _load_yaml(pool_path, label="hierarchical rotation pool")
    validate_hierarchical_contract(spec, pool)
    return spec, pool, resolved_spec, pool_path


def build_runtime_timing_spec(
    spec: Mapping[str, Any],
    pool: Mapping[str, Any],
    *,
    repository_root: Path,
) -> tuple[dict[str, Any], Path]:
    timing = spec["architecture"]["security_timing_component"]
    formula_path = repository_root / str(timing["formula_source"])
    runtime = copy.deepcopy(load_focus_signal_spec(formula_path))

    candidates = _candidate_symbols(pool)
    benchmark = str(spec["market_regime"]["reference"])
    context = str(spec["sector_context"]["reference"])
    aliases: dict[str, str] = {}
    for display, metadata in pool["references"].items():
        provider = str(metadata.get("provider_symbol", display))
        if provider != str(display):
            aliases[str(display)] = provider
    for display, metadata in pool.get("symbol_metadata", {}).items():
        provider = str(metadata.get("provider_symbol", display))
        if provider != str(display):
            aliases[str(display)] = provider

    runtime["market"] = str(spec["market"])
    runtime["benchmark"] = benchmark
    runtime["universe"] = {
        "source": str(pool["pool_id"]),
        "universe_id": str(pool["pool_id"]),
        "membership_mode": "fixed_predeclared",
        "symbols": [*candidates, benchmark, context],
        "signal_symbols": candidates,
        "market_reference_symbols": [benchmark],
        "sector_reference_symbols": [context],
        "provider_aliases": aliases,
        "minimum_sessions_for_full_evaluation": 504,
        "insufficient_history_policy": "short_history_diagnostic_or_forward_only",
        "silent_exclusion_allowed": False,
    }
    runtime["signal"]["market_regime"]["reference"] = benchmark
    runtime["signal"]["sector_context"]["reference"] = context
    runtime["risk"]["symbol_tiers"] = {symbol: "core" for symbol in candidates}
    runtime["risk"]["reference_roles"] = {
        str(symbol): str(metadata.get("role", "informational_context"))
        for symbol, metadata in pool["references"].items()
    }
    validate_focus_signal_spec(runtime)
    return runtime, formula_path


def build_pool_identity(
    pool: Mapping[str, Any],
    *,
    pool_path: Path,
) -> dict[str, Any]:
    baskets = {
        str(name): [str(symbol) for symbol in basket["symbols"]]
        for name, basket in pool["baskets"].items()
    }
    references = {str(symbol): dict(metadata) for symbol, metadata in pool["references"].items()}
    symbol_metadata = {
        str(symbol): dict(metadata) for symbol, metadata in pool.get("symbol_metadata", {}).items()
    }
    membership = {
        "pool_id": str(pool["pool_id"]),
        "market": str(pool["market"]),
        "status": str(pool.get("status", "frozen")),
        "baskets": baskets,
        "references": references,
        "symbol_metadata": symbol_metadata,
        "primary_basket_only": bool(pool["primary_basket_only"]),
    }
    candidates = [symbol for members in baskets.values() for symbol in members]
    return {
        "schema_version": "1.0",
        "pool_id": str(pool["pool_id"]),
        "market": str(pool["market"]),
        "status": str(pool.get("status", "frozen")),
        "authoritative_for_performance": bool(pool.get("authoritative_for_performance", True)),
        "pool_file_sha256": sha256_file(pool_path),
        "membership_identity_sha256": canonical_sha256(membership),
        "candidate_count": len(candidates),
        "basket_count": len(baskets),
        "baskets": baskets,
        "references": references,
        "symbol_metadata": symbol_metadata,
    }


def compute_hierarchical_indicators(
    prices: pd.DataFrame,
    timing_spec: Mapping[str, Any],
) -> pd.DataFrame:
    indicators = compute_focus_indicators(prices, timing_spec)
    enriched: list[pd.DataFrame] = []
    for _, raw in indicators.groupby("symbol", sort=False):
        group = raw.sort_values("date").copy()
        returns = group["close"].pct_change()
        group["momentum_20"] = group["close"] / group["close"].shift(20) - 1.0
        group["high_63"] = group["close"].rolling(63, min_periods=63).max()
        group["drawdown_from_63d_high"] = group["close"] / group["high_63"] - 1.0
        group["realized_volatility_20"] = returns.rolling(20, min_periods=20).std()
        group["relative_momentum_63_vs_benchmark"] = group["rel_mom_63_vs_qqq"]
        enriched.append(group)
    return (
        pd.concat(enriched, ignore_index=True)
        .sort_values(["symbol", "date"])
        .reset_index(drop=True)
    )


def _state_frame(signal_history: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in signal_history:
        indicators = dict(row.get("indicators", {}))
        rows.append(
            {
                "date": pd.Timestamp(row["date"]),
                "symbol": str(row["symbol"]),
                "state": str(row["state"]),
                "reason_codes": list(row.get("reason_codes", [])),
                "trailing_stop_3atr": indicators.get("trailing_stop_3atr"),
            }
        )
    return pd.DataFrame(rows)


def _next_session_map(dates: pd.Series) -> dict[pd.Timestamp, pd.Timestamp | None]:
    ordered = [pd.Timestamp(value) for value in sorted(dates.dropna().unique())]
    return {
        date: ordered[index + 1] if index + 1 < len(ordered) else None
        for index, date in enumerate(ordered)
    }


def _rotation_dates(
    indicators: pd.DataFrame,
    spec: Mapping[str, Any],
) -> list[pd.Timestamp]:
    benchmark = str(spec["market_regime"]["reference"])
    dates = [
        pd.Timestamp(value)
        for value in sorted(
            indicators.loc[indicators["symbol"] == benchmark, "date"].dropna().unique()
        )
    ]
    anchor = pd.Timestamp(spec["rotation"]["rotation_anchor_date"])
    eligible = [date for date in dates if date >= anchor]
    step = int(spec["rotation"]["rebalance_every_n_benchmark_sessions"])
    return eligible[::step]


def _rank_percentile(
    values: pd.Series,
    *,
    direction: str,
) -> pd.Series:
    ascending = direction == "higher_is_better"
    return values.rank(method="average", pct=True, ascending=ascending)


def _basket_snapshots(
    date: pd.Timestamp,
    indicators: pd.DataFrame,
    states: pd.DataFrame,
    spec: Mapping[str, Any],
    pool: Mapping[str, Any],
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    eligibility = spec["rotation"]["eligibility"]
    state_filter = spec["security_selection"]["absolute_state_filter"]
    positive_states = {state for state, weight in state_filter.items() if float(weight) > 0}

    for basket_name, basket in pool["baskets"].items():
        members = [str(symbol) for symbol in basket["symbols"]]
        day = indicators[(indicators["date"] == date) & indicators["symbol"].isin(members)].copy()
        ready = day.dropna(
            subset=[
                "relative_momentum_63_vs_benchmark",
                "momentum_20",
                "sma_50",
                "drawdown_from_63d_high",
            ]
        )
        count = int(ready.shape[0])
        coverage = count / len(members)
        breadth = None if ready.empty else float((ready["close"] > ready["sma_50"]).mean())
        relative = (
            None if ready.empty else float(ready["relative_momentum_63_vs_benchmark"].median())
        )
        momentum = None if ready.empty else float(ready["momentum_20"].median())
        drawdown = None if ready.empty else float(ready["drawdown_from_63d_high"].median())
        reasons: list[str] = []
        if count < int(eligibility["minimum_eligible_constituents"]):
            reasons.append("BASKET_INSUFFICIENT_ELIGIBLE_CONSTITUENTS")
        if coverage < float(eligibility["minimum_constituent_coverage_ratio"]):
            reasons.append("BASKET_INSUFFICIENT_COVERAGE")
        if breadth is None or breadth < float(eligibility["minimum_breadth_above_sma50"]):
            reasons.append("BASKET_BREADTH_BELOW_GATE")
        if bool(eligibility["require_positive_median_relative_momentum_63"]) and (
            relative is None or relative <= 0
        ):
            reasons.append("BASKET_RELATIVE_MOMENTUM_NONPOSITIVE")
        state_day = states[(states["date"] == date) & states["symbol"].isin(members)]
        snapshots.append(
            {
                "date": date.date().isoformat(),
                "basket": str(basket_name),
                "members": members,
                "eligible_constituent_count": count,
                "constituent_coverage_ratio": float(coverage),
                "state_eligible_security_count": int(
                    state_day["state"].isin(positive_states).sum()
                ),
                "median_relative_momentum_63_vs_benchmark": relative,
                "median_momentum_20": momentum,
                "breadth_above_sma50": breadth,
                "median_drawdown_from_63d_high": drawdown,
                "pre_score_eligible": not reasons,
                "composite_percentile": None,
                "score_gate_passed": False,
                "selected": False,
                "reason_codes": reasons,
            }
        )

    eligible_indexes = [index for index, row in enumerate(snapshots) if row["pre_score_eligible"]]
    components = spec["rotation"]["score"]["components"]
    for field in BASKET_SCORE_FIELDS:
        values = pd.Series(
            [float(snapshots[index][field]) for index in eligible_indexes],
            index=eligible_indexes,
            dtype="float64",
        )
        ranks = _rank_percentile(values, direction=str(components[field]["direction"]))
        for index, value in ranks.items():
            snapshots[int(index)][f"{field}_percentile"] = float(value)
    minimum = float(spec["rotation"]["score"]["minimum_composite_percentile"])
    for index in eligible_indexes:
        composite = sum(
            float(snapshots[index][f"{field}_percentile"]) * float(components[field]["weight"])
            for field in BASKET_SCORE_FIELDS
        )
        snapshots[index]["composite_percentile"] = float(composite)
        snapshots[index]["score_gate_passed"] = composite >= minimum
        if composite < minimum:
            snapshots[index]["reason_codes"].append("BASKET_COMPOSITE_BELOW_GATE")
    return snapshots


def _security_scores(
    date: pd.Timestamp,
    basket_name: str,
    members: list[str],
    indicators: pd.DataFrame,
    states: pd.DataFrame,
    spec: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    day = indicators[(indicators["date"] == date) & indicators["symbol"].isin(members)][
        ["symbol", *SECURITY_SCORE_FIELDS]
    ]
    state_day = states[(states["date"] == date) & states["symbol"].isin(members)].merge(
        day, on="symbol", how="left", validate="one_to_one"
    )

    selection = spec["security_selection"]
    state_filter = {
        str(key): float(value) for key, value in selection["absolute_state_filter"].items()
    }
    priorities = {
        str(key): int(value) for key, value in selection["cross_section"]["state_priority"].items()
    }
    state_day["exposure_multiplier"] = state_day["state"].map(state_filter).fillna(0.0)
    state_day["state_priority"] = state_day["state"].map(priorities).fillna(0).astype(int)
    state_day["absolute_state_eligible"] = state_day["exposure_multiplier"] > 0
    state_day["indicator_complete"] = state_day[list(SECURITY_SCORE_FIELDS)].notna().all(axis=1)
    eligible = state_day[
        state_day["absolute_state_eligible"] & state_day["indicator_complete"]
    ].copy()

    cross_section = selection["cross_section"]
    components = cross_section["components"]
    for field in SECURITY_SCORE_FIELDS:
        eligible[f"{field}_percentile"] = _rank_percentile(
            eligible[field], direction=str(components[field]["direction"])
        )
    if eligible.empty:
        eligible["security_composite_percentile"] = pd.Series(dtype="float64")
    else:
        eligible["security_composite_percentile"] = sum(
            eligible[f"{field}_percentile"] * float(components[field]["weight"])
            for field in SECURITY_SCORE_FIELDS
        )
    minimum = float(cross_section["minimum_composite_percentile"])
    eligible["score_gate_passed"] = eligible["security_composite_percentile"] >= minimum
    eligible = eligible.sort_values(
        ["security_composite_percentile", "state_priority", "symbol"],
        ascending=[False, False, True],
    )
    limit = int(spec["rotation"]["maximum_selected_symbols_per_basket"])
    selected = eligible[eligible["score_gate_passed"]].head(limit)
    selected_symbols = set(selected["symbol"].astype(str))
    by_symbol = eligible.set_index("symbol", drop=False)

    score_rows: list[dict[str, Any]] = []
    for _, row in state_day.sort_values("symbol").iterrows():
        symbol = str(row["symbol"])
        scored = symbol in by_symbol.index
        score_row = by_symbol.loc[symbol] if scored else None
        reasons: list[str] = []
        if not bool(row["absolute_state_eligible"]):
            reasons.append("SECURITY_ABSOLUTE_STATE_INELIGIBLE")
        if not bool(row["indicator_complete"]):
            reasons.append("SECURITY_SCORE_INPUT_INCOMPLETE")
        gate = bool(score_row["score_gate_passed"]) if scored else False
        if scored and not gate:
            reasons.append("SECURITY_COMPOSITE_BELOW_GATE")
        within_selected = symbol in selected_symbols
        if within_selected:
            reasons.append("SECURITY_SELECTED_WITHIN_BASKET")
        elif gate:
            reasons.append("SECURITY_NOT_SELECTED_SCORE_ORDER")
        payload: dict[str, Any] = {
            "date": date.date().isoformat(),
            "basket": basket_name,
            "symbol": symbol,
            "state": str(row["state"]),
            "absolute_state_eligible": bool(row["absolute_state_eligible"]),
            "indicator_complete": bool(row["indicator_complete"]),
            "security_composite_percentile": (
                None if not scored else float(score_row["security_composite_percentile"])
            ),
            "score_gate_passed": gate,
            "within_basket_selected": within_selected,
            "portfolio_selected": False,
            "reason_codes": reasons,
        }
        for field in SECURITY_SCORE_FIELDS:
            payload[field] = None if pd.isna(row[field]) else float(row[field])
            payload[f"{field}_percentile"] = (
                None if not scored else float(score_row[f"{field}_percentile"])
            )
        score_rows.append(payload)

    selected_rows: list[dict[str, Any]] = []
    for _, row in selected.iterrows():
        selected_rows.append(
            {
                "symbol": str(row["symbol"]),
                "state": str(row["state"]),
                "state_priority": int(row["state_priority"]),
                "security_composite_percentile": float(row["security_composite_percentile"]),
                "relative_momentum_63_vs_benchmark": float(
                    row["relative_momentum_63_vs_benchmark"]
                ),
                "momentum_20": float(row["momentum_20"]),
                "drawdown_from_63d_high": float(row["drawdown_from_63d_high"]),
                "realized_volatility_20": float(row["realized_volatility_20"]),
                "exposure_multiplier": float(row["exposure_multiplier"]),
                "state_reason_codes": list(row["reason_codes"]),
                "trailing_stop_3atr": row["trailing_stop_3atr"],
            }
        )
    return selected_rows, score_rows


def build_hierarchical_rotation_history(
    indicators: pd.DataFrame,
    signal_history: list[dict[str, Any]],
    spec: Mapping[str, Any],
    pool: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    states = _state_frame(signal_history)
    benchmark_symbol = str(spec["market_regime"]["reference"])
    benchmark = indicators[indicators["symbol"] == benchmark_symbol].set_index("date")
    next_sessions = _next_session_map(benchmark.reset_index()["date"])
    basket_history: list[dict[str, Any]] = []
    security_history: list[dict[str, Any]] = []
    rotations: list[dict[str, Any]] = []

    for date in _rotation_dates(indicators, spec):
        snapshots = _basket_snapshots(date, indicators, states, spec, pool)
        provisional: dict[str, list[dict[str, Any]]] = {}
        security_rows_by_basket: dict[str, list[dict[str, Any]]] = {}
        for snapshot in snapshots:
            basket = str(snapshot["basket"])
            selected, score_rows = _security_scores(
                date,
                basket,
                list(snapshot["members"]),
                indicators,
                states,
                spec,
            )
            provisional[basket] = selected
            security_rows_by_basket[basket] = score_rows

        benchmark_row = benchmark.loc[date]
        risk_on = bool(benchmark_row["risk_on"]) if not pd.isna(benchmark_row["risk_on"]) else False
        selected_baskets: list[str] = []
        selected_map: dict[str, list[dict[str, Any]]] = {}
        rotation_reasons: list[str] = []
        if not risk_on:
            rotation_reasons.append("ROTATION_MARKET_RISK_OFF")
        else:
            candidates = sorted(
                [
                    row
                    for row in snapshots
                    if row["score_gate_passed"] and provisional[str(row["basket"])]
                ],
                key=lambda row: (-float(row["composite_percentile"]), str(row["basket"])),
            )
            for snapshot in candidates[: int(spec["rotation"]["maximum_selected_baskets"])]:
                basket = str(snapshot["basket"])
                selected_baskets.append(basket)
                selected_map[basket] = provisional[basket]
                snapshot["selected"] = True
                snapshot["reason_codes"].append("BASKET_SELECTED")
            if not selected_baskets:
                rotation_reasons.append("ROTATION_NO_ELIGIBLE_BASKET")

        selected_set = set(selected_baskets)
        for snapshot in snapshots:
            basket = str(snapshot["basket"])
            if snapshot["score_gate_passed"] and not provisional[basket]:
                snapshot["reason_codes"].append("BASKET_NO_CROSS_SECTION_ELIGIBLE_SECURITY")
            elif snapshot["score_gate_passed"] and basket not in selected_set:
                snapshot["reason_codes"].append("BASKET_NOT_SELECTED_SCORE_ORDER")
            basket_history.append(snapshot)
            for row in security_rows_by_basket[basket]:
                row["basket_selected"] = basket in selected_set
                row["portfolio_selected"] = basket in selected_set and row["within_basket_selected"]
                security_history.append(row)

        actionable = next_sessions.get(date)
        rotations.append(
            {
                "date": date.date().isoformat(),
                "actionable_from": (None if actionable is None else actionable.date().isoformat()),
                "market": str(spec["market"]),
                "benchmark": benchmark_symbol,
                "risk_on": risk_on,
                "market_regime": str(benchmark_row["market_regime"]),
                "selected_baskets": selected_baskets,
                "selected_symbols_by_basket": selected_map,
                "reason_codes": rotation_reasons or ["ROTATION_SELECTION_COMPLETED"],
            }
        )
    return basket_history, security_history, rotations


def build_hierarchical_portfolio_history(
    indicators: pd.DataFrame,
    signal_history: list[dict[str, Any]],
    rotations: list[dict[str, Any]],
    spec: Mapping[str, Any],
) -> list[dict[str, Any]]:
    states = _state_frame(signal_history).set_index(["date", "symbol"])
    benchmark_symbol = str(spec["market_regime"]["reference"])
    benchmark = indicators[indicators["symbol"] == benchmark_symbol].sort_values("date")
    next_sessions = _next_session_map(benchmark["date"])
    rotations_by_date = {pd.Timestamp(row["date"]): row for row in rotations}
    multipliers = {
        str(state): float(value)
        for state, value in spec["security_selection"]["absolute_state_filter"].items()
    }

    current_rotation: dict[str, Any] | None = None
    history: list[dict[str, Any]] = []
    for _, benchmark_row in benchmark.iterrows():
        date = pd.Timestamp(benchmark_row["date"])
        if date in rotations_by_date:
            current_rotation = rotations_by_date[date]
        risk_on = bool(benchmark_row["risk_on"]) if not pd.isna(benchmark_row["risk_on"]) else False
        selected_baskets = (
            [] if current_rotation is None else list(current_rotation["selected_baskets"])
        )
        selected_map = (
            {} if current_rotation is None else dict(current_rotation["selected_symbols_by_basket"])
        )
        positions: list[dict[str, Any]] = []
        reasons: list[str] = []
        if not risk_on:
            reasons.append("PORTFOLIO_MARKET_RISK_OFF")
        if not selected_baskets:
            reasons.append("PORTFOLIO_NO_SELECTED_BASKET")

        basket_weight = 1.0 / len(selected_baskets) if selected_baskets else 0.0
        for basket in selected_baskets:
            selected = list(selected_map.get(basket, []))
            symbol_weight = basket_weight / len(selected) if selected else 0.0
            for selected_row in selected:
                symbol = str(selected_row["symbol"])
                state = "MISSING"
                state_reasons = ["MISSING_STATE_FAIL_CLOSED"]
                trailing_stop = None
                if (date, symbol) in states.index:
                    state_row = states.loc[(date, symbol)]
                    if isinstance(state_row, pd.DataFrame):
                        raise ValueError(f"duplicate signal state for {date} {symbol}")
                    state = str(state_row["state"])
                    state_reasons = list(state_row["reason_codes"])
                    trailing_stop = state_row["trailing_stop_3atr"]
                multiplier = multipliers.get(state, 0.0)
                target = symbol_weight * multiplier if risk_on else 0.0
                positions.append(
                    {
                        "basket": basket,
                        "symbol": symbol,
                        "state": state,
                        "security_composite_percentile": selected_row[
                            "security_composite_percentile"
                        ],
                        "target_weight": float(target),
                        "state_multiplier": float(multiplier),
                        "state_reason_codes": state_reasons,
                        "trailing_stop_3atr": trailing_stop,
                    }
                )
        gross = float(sum(row["target_weight"] for row in positions))
        if gross > float(spec["portfolio"]["maximum_gross_exposure"]) + 1e-12:
            raise ValueError("portfolio gross exposure exceeds frozen maximum")
        actionable = next_sessions.get(date)
        history.append(
            {
                "date": date.date().isoformat(),
                "actionable_from": (None if actionable is None else actionable.date().isoformat()),
                "market": str(spec["market"]),
                "benchmark": benchmark_symbol,
                "rotation_date": (None if current_rotation is None else current_rotation["date"]),
                "risk_on": risk_on,
                "market_regime": str(benchmark_row["market_regime"]),
                "selected_baskets": selected_baskets,
                "positions": positions,
                "gross_exposure": gross,
                "cash_weight": float(1.0 - gross),
                "reason_codes": reasons or ["PORTFOLIO_ROTATION_ACTIVE"],
            }
        )
    return history


def run_hierarchical_pool_rotation(
    *,
    spec_path: str | Path,
    prices_csv: str | Path,
    output_dir: str | Path,
    authoritative_mode: bool = False,
) -> dict[str, Any]:
    spec, pool, resolved_spec, pool_path = load_hierarchical_contract(spec_path)
    pool_authoritative = bool(pool.get("authoritative_for_performance", True))
    spec_authoritative = bool(spec.get("authoritative_validation_allowed", True))
    if authoritative_mode and not (pool_authoritative and spec_authoritative):
        raise ValueError("draft pool/spec cannot run in authoritative mode")

    root = _repository_root(resolved_spec)
    timing_spec, formula_path = build_runtime_timing_spec(spec, pool, repository_root=root)
    prices_path = Path(prices_csv).resolve()
    prices = load_long_ohlcv_csv(prices_path, timing_spec)
    indicators = compute_hierarchical_indicators(prices, timing_spec)
    signal_history, _ = generate_signal_history(indicators, timing_spec)
    basket_scores, security_scores, rotations = build_hierarchical_rotation_history(
        indicators, signal_history, spec, pool
    )
    portfolio = build_hierarchical_portfolio_history(indicators, signal_history, rotations, spec)

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    pool_identity = build_pool_identity(pool, pool_path=pool_path)
    payloads: dict[str, dict[str, Any]] = {
        "pool_identity.json": pool_identity,
        "basket_score_history.json": {
            "schema_version": "1.0",
            "experiment_id": spec["experiment_id"],
            "rows": basket_scores,
        },
        "security_score_history.json": {
            "schema_version": "1.0",
            "experiment_id": spec["experiment_id"],
            "rows": security_scores,
        },
        "rotation_history.json": {
            "schema_version": "1.0",
            "experiment_id": spec["experiment_id"],
            "rows": rotations,
        },
        "portfolio_state_history.json": {
            "schema_version": "1.0",
            "experiment_id": spec["experiment_id"],
            "rows": portfolio,
        },
    }
    for filename, payload in payloads.items():
        write_json(output / filename, payload)

    decision = {
        "schema_version": "1.0",
        "experiment_id": spec["experiment_id"],
        "decision": "generic_hierarchical_rotation_engine_ready",
        "market": str(spec["market"]),
        "benchmark": str(spec["benchmark"]),
        "pool_id": str(pool["pool_id"]),
        "pool_status": str(pool.get("status", "frozen")),
        "pool_authoritative_for_performance": pool_authoritative,
        "spec_authoritative_validation_allowed": spec_authoritative,
        "authoritative_mode": authoritative_mode,
        "research_only": True,
        "trade_ready": False,
        "performance_evaluated": False,
        "reserved_performance_opened": False,
        "candidate_count": pool_identity["candidate_count"],
        "basket_count": pool_identity["basket_count"],
        "rotation_count": len(rotations),
        "security_score_row_count": len(security_scores),
    }
    write_json(output / "decision.json", decision)

    output_hashes = {
        filename: sha256_file(output / filename) for filename in [*payloads, "decision.json"]
    }
    manifest = {
        "schema_version": "1.0",
        "experiment_id": spec["experiment_id"],
        "market": str(spec["market"]),
        "provider_identity_sha256": sha256_file(prices_path),
        "rotation_spec_identity_sha256": sha256_file(resolved_spec),
        "pool_file_identity_sha256": sha256_file(pool_path),
        "pool_membership_identity_sha256": pool_identity["membership_identity_sha256"],
        "timing_formula_identity_sha256": sha256_file(formula_path),
        "input": {"prices_csv": str(prices_path)},
        "outputs": output_hashes,
        "manifest_identity_sha256": canonical_sha256(
            {
                "provider": sha256_file(prices_path),
                "spec": sha256_file(resolved_spec),
                "pool": pool_identity["membership_identity_sha256"],
                "formula": sha256_file(formula_path),
                "basket_scores": len(basket_scores),
                "security_scores": len(security_scores),
                "rotations": len(rotations),
                "portfolio_rows": len(portfolio),
            }
        ),
    }
    write_json(output / "evidence_manifest.json", manifest)
    return decision
