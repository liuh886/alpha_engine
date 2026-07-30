"""Deterministic basket rotation for a versioned, user-curated small stock pool."""

from __future__ import annotations

import copy
import json
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


_SCORE_FIELDS = (
    "median_relative_momentum_63_vs_qqq",
    "median_momentum_20",
    "breadth_above_sma50",
    "median_drawdown_from_63d_high",
)


def _load_yaml_mapping(path: str | Path, *, label: str) -> dict[str, Any]:
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
    baskets = pool.get("baskets", {})
    return [
        str(symbol)
        for basket in baskets.values()
        for symbol in basket.get("symbols", [])
    ]


def validate_rotation_contract(
    spec: Mapping[str, Any],
    pool: Mapping[str, Any],
) -> None:
    baskets = pool.get("baskets", {})
    references = pool.get("references", {})
    if not isinstance(baskets, dict) or len(baskets) < 2:
        raise ValueError("rotation pool must contain at least two baskets")
    if set(references) != {"QQQ", "SOX"}:
        raise ValueError("rotation references must be exactly QQQ and SOX")

    symbols = _candidate_symbols(pool)
    if not symbols or len(symbols) != len(set(symbols)):
        raise ValueError("pool candidates must be non-empty and unique")
    if set(symbols).intersection(references):
        raise ValueError("reference instruments cannot be trading candidates")
    for name, basket in baskets.items():
        members = list(basket.get("symbols", []))
        if len(members) < 2:
            raise ValueError(f"basket {name} must contain at least two symbols")

    architecture = spec.get("architecture", {})
    timing = architecture.get("security_timing_component", {})
    if timing.get("source_universe_reused") is not False:
        raise ValueError("legacy timing universe must not be reused")
    if timing.get("candidate_universe_source") != "pool_spec.baskets":
        raise ValueError("candidate universe must come from the versioned pool")

    rotation = spec.get("rotation", {})
    if int(rotation.get("rebalance_every_n_qqq_sessions", 0)) <= 0:
        raise ValueError("rotation frequency must be positive")
    if int(rotation.get("maximum_selected_baskets", 0)) <= 0:
        raise ValueError("maximum selected baskets must be positive")
    if int(rotation.get("maximum_selected_symbols_per_basket", 0)) <= 0:
        raise ValueError("maximum symbols per basket must be positive")
    if not str(rotation.get("rotation_anchor_date", "")).strip():
        raise ValueError("rotation anchor date is required")

    components = rotation.get("score", {}).get("components", {})
    if set(components) != set(_SCORE_FIELDS):
        raise ValueError("unexpected basket score components")
    weights = [float(components[field]["weight"]) for field in _SCORE_FIELDS]
    if not np.isclose(sum(weights), 1.0):
        raise ValueError("basket score weights must sum to one")
    if any(components[field].get("direction") != "higher_is_better" for field in _SCORE_FIELDS):
        raise ValueError("all v1 basket score components must rank higher as better")

    parameter_search = spec.get("parameter_search", {})
    if not parameter_search or any(bool(value) for value in parameter_search.values()):
        raise ValueError("all parameter-search switches must remain disabled")
    if spec.get("objective", {}).get("model_fitting") is not False:
        raise ValueError("rotation v1 cannot fit a model")
    if spec.get("pool_governance", {}).get("membership_hash_required") is not True:
        raise ValueError("pool membership hash must be required")


def load_rotation_contract(
    spec_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    spec_path = Path(spec_path).resolve()
    spec = _load_yaml_mapping(spec_path, label="rotation spec")
    root = _repository_root(spec_path)
    pool_path = root / str(spec["pool_spec"])
    pool = _load_yaml_mapping(pool_path, label="pool spec")
    validate_rotation_contract(spec, pool)
    return spec, pool, spec_path, pool_path


def build_runtime_timing_spec(
    spec: Mapping[str, Any],
    pool: Mapping[str, Any],
    *,
    repository_root: Path,
) -> tuple[dict[str, Any], Path]:
    component = spec["architecture"]["security_timing_component"]
    formula_path = repository_root / str(component["formula_source"])
    runtime = copy.deepcopy(load_focus_signal_spec(formula_path))

    candidates = _candidate_symbols(pool)
    references = pool["references"]
    runtime["universe"] = {
        "source": str(pool["pool_id"]),
        "universe_id": str(pool["pool_id"]),
        "membership_mode": "fixed_predeclared",
        "symbols": [*candidates, "QQQ", "SOX"],
        "signal_symbols": candidates,
        "market_reference_symbols": ["QQQ"],
        "sector_reference_symbols": ["SOX"],
        "provider_aliases": {"SOX": str(references["SOX"]["provider_symbol"])},
        "minimum_sessions_for_full_evaluation": 504,
        "insufficient_history_policy": "short_history_diagnostic_or_forward_only",
        "silent_exclusion_allowed": False,
    }
    runtime["risk"]["symbol_tiers"] = {symbol: "core" for symbol in candidates}
    runtime["risk"]["reference_roles"] = {
        "QQQ": "market_regime_and_benchmark",
        "SOX": "semiconductor_sector_context",
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
    references = {
        str(symbol): dict(metadata)
        for symbol, metadata in pool["references"].items()
    }
    membership_payload = {
        "pool_id": str(pool["pool_id"]),
        "baskets": baskets,
        "references": references,
        "primary_basket_only": bool(pool["primary_basket_only"]),
    }
    candidates = [symbol for symbols in baskets.values() for symbol in symbols]
    return {
        "schema_version": "1.0",
        "pool_id": str(pool["pool_id"]),
        "pool_file_sha256": sha256_file(pool_path),
        "membership_identity_sha256": canonical_sha256(membership_payload),
        "candidate_count": len(candidates),
        "basket_count": len(baskets),
        "baskets": baskets,
        "references": references,
    }


def compute_rotation_indicators(
    prices: pd.DataFrame,
    timing_spec: Mapping[str, Any],
) -> pd.DataFrame:
    indicators = compute_focus_indicators(prices, timing_spec)
    enriched: list[pd.DataFrame] = []
    for _, raw_group in indicators.groupby("symbol", sort=False):
        group = raw_group.sort_values("date").copy()
        group["momentum_20"] = group["close"] / group["close"].shift(20) - 1.0
        group["high_63"] = group["close"].rolling(63, min_periods=63).max()
        group["drawdown_from_63d_high"] = group["close"] / group["high_63"] - 1.0
        enriched.append(group)
    return pd.concat(enriched, ignore_index=True).sort_values(
        ["symbol", "date"]
    ).reset_index(drop=True)


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
                "actionable_from": row.get("actionable_from"),
                "trailing_stop_3atr": indicators.get("trailing_stop_3atr"),
            }
        )
    return pd.DataFrame(rows)


def _next_session_map(reference_dates: pd.Series) -> dict[pd.Timestamp, pd.Timestamp | None]:
    dates = [pd.Timestamp(value) for value in sorted(reference_dates.dropna().unique())]
    return {
        date: dates[index + 1] if index + 1 < len(dates) else None
        for index, date in enumerate(dates)
    }


def _rotation_dates(
    indicators: pd.DataFrame,
    spec: Mapping[str, Any],
) -> list[pd.Timestamp]:
    qqq_dates = [
        pd.Timestamp(value)
        for value in sorted(
            indicators.loc[indicators["symbol"] == "QQQ", "date"].dropna().unique()
        )
    ]
    anchor = pd.Timestamp(spec["rotation"]["rotation_anchor_date"])
    eligible = [date for date in qqq_dates if date >= anchor]
    step = int(spec["rotation"]["rebalance_every_n_qqq_sessions"])
    return eligible[::step]


def _basket_snapshot(
    date: pd.Timestamp,
    basket_name: str,
    members: list[str],
    indicators: pd.DataFrame,
    states: pd.DataFrame,
    spec: Mapping[str, Any],
) -> dict[str, Any]:
    day = indicators[
        (indicators["date"] == date) & indicators["symbol"].isin(members)
    ].copy()
    metric_columns = (
        "rel_mom_63_vs_qqq",
        "momentum_20",
        "sma_50",
        "drawdown_from_63d_high",
    )
    ready = day.dropna(subset=list(metric_columns))
    eligible_count = int(ready.shape[0])
    coverage_ratio = eligible_count / len(members)
    breadth = None
    median_relative = None
    median_momentum = None
    median_drawdown = None
    if not ready.empty:
        breadth = float((ready["close"] > ready["sma_50"]).mean())
        median_relative = float(ready["rel_mom_63_vs_qqq"].median())
        median_momentum = float(ready["momentum_20"].median())
        median_drawdown = float(ready["drawdown_from_63d_high"].median())

    eligibility = spec["rotation"]["eligibility"]
    reasons: list[str] = []
    if eligible_count < int(eligibility["minimum_eligible_constituents"]):
        reasons.append("BASKET_INSUFFICIENT_ELIGIBLE_CONSTITUENTS")
    if coverage_ratio < float(eligibility["minimum_constituent_coverage_ratio"]):
        reasons.append("BASKET_INSUFFICIENT_COVERAGE")
    if breadth is None or breadth < float(eligibility["minimum_breadth_above_sma50"]):
        reasons.append("BASKET_BREADTH_BELOW_GATE")
    if (
        bool(eligibility["require_positive_median_relative_momentum_63"])
        and (median_relative is None or median_relative <= 0)
    ):
        reasons.append("BASKET_RELATIVE_MOMENTUM_NONPOSITIVE")

    state_day = states[
        (states["date"] == date) & states["symbol"].isin(members)
    ]
    eligible_states = {
        state
        for state, multiplier in spec["security_selection"]["eligible_states"].items()
        if float(multiplier) > 0
    }
    state_eligible_count = int(state_day["state"].isin(eligible_states).sum())
    return {
        "date": date.date().isoformat(),
        "basket": basket_name,
        "members": members,
        "eligible_constituents": sorted(ready["symbol"].astype(str).tolist()),
        "eligible_constituent_count": eligible_count,
        "constituent_coverage_ratio": float(coverage_ratio),
        "state_eligible_security_count": state_eligible_count,
        "median_relative_momentum_63_vs_qqq": median_relative,
        "median_momentum_20": median_momentum,
        "breadth_above_sma50": breadth,
        "median_drawdown_from_63d_high": median_drawdown,
        "pre_score_eligible": not reasons,
        "composite_percentile": None,
        "score_gate_passed": False,
        "selected": False,
        "reason_codes": reasons,
    }


def _add_component_ranks(
    snapshots: list[dict[str, Any]],
    spec: Mapping[str, Any],
) -> None:
    eligible_indexes = [
        index for index, snapshot in enumerate(snapshots) if snapshot["pre_score_eligible"]
    ]
    if not eligible_indexes:
        return

    components = spec["rotation"]["score"]["components"]
    for field in _SCORE_FIELDS:
        values = pd.Series(
            [float(snapshots[index][field]) for index in eligible_indexes],
            index=eligible_indexes,
            dtype="float64",
        )
        ranks = values.rank(method="average", pct=True, ascending=True)
        for index, value in ranks.items():
            snapshots[int(index)][f"{field}_percentile"] = float(value)

    minimum = float(spec["rotation"]["score"]["minimum_composite_percentile"])
    for index in eligible_indexes:
        composite = sum(
            float(snapshots[index][f"{field}_percentile"])
            * float(components[field]["weight"])
            for field in _SCORE_FIELDS
        )
        snapshots[index]["composite_percentile"] = float(composite)
        snapshots[index]["score_gate_passed"] = composite >= minimum
        if composite < minimum:
            snapshots[index]["reason_codes"].append("BASKET_COMPOSITE_BELOW_GATE")


def _select_securities(
    date: pd.Timestamp,
    members: list[str],
    indicators: pd.DataFrame,
    states: pd.DataFrame,
    spec: Mapping[str, Any],
) -> list[dict[str, Any]]:
    day = indicators[
        (indicators["date"] == date) & indicators["symbol"].isin(members)
    ][["symbol", "rel_mom_63_vs_qqq"]]
    state_day = states[
        (states["date"] == date) & states["symbol"].isin(members)
    ].merge(day, on="symbol", how="left", validate="one_to_one")

    multipliers = {
        str(state): float(value)
        for state, value in spec["security_selection"]["eligible_states"].items()
    }
    priorities = {
        str(state): int(value)
        for state, value in spec["security_selection"]["ranking"]["state_priority"].items()
    }
    state_day["exposure_multiplier"] = state_day["state"].map(multipliers).fillna(0.0)
    state_day["state_priority"] = state_day["state"].map(priorities).fillna(0).astype(int)
    eligible = state_day[
        (state_day["exposure_multiplier"] > 0)
        & state_day["rel_mom_63_vs_qqq"].notna()
    ].copy()
    eligible = eligible.sort_values(
        ["state_priority", "rel_mom_63_vs_qqq", "symbol"],
        ascending=[False, False, True],
    )
    limit = int(spec["rotation"]["maximum_selected_symbols_per_basket"])
    result: list[dict[str, Any]] = []
    for _, row in eligible.head(limit).iterrows():
        result.append(
            {
                "symbol": str(row["symbol"]),
                "state": str(row["state"]),
                "state_priority": int(row["state_priority"]),
                "relative_momentum_63_vs_qqq": float(row["rel_mom_63_vs_qqq"]),
                "exposure_multiplier": float(row["exposure_multiplier"]),
                "state_reason_codes": list(row["reason_codes"]),
                "trailing_stop_3atr": row["trailing_stop_3atr"],
            }
        )
    return result


def build_rotation_history(
    indicators: pd.DataFrame,
    signal_history: list[dict[str, Any]],
    spec: Mapping[str, Any],
    pool: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    states = _state_frame(signal_history)
    qqq = indicators[indicators["symbol"] == "QQQ"].set_index("date")
    next_sessions = _next_session_map(qqq.reset_index()["date"])
    score_history: list[dict[str, Any]] = []
    rotations: list[dict[str, Any]] = []

    for date in _rotation_dates(indicators, spec):
        snapshots = [
            _basket_snapshot(
                date,
                str(name),
                [str(symbol) for symbol in basket["symbols"]],
                indicators,
                states,
                spec,
            )
            for name, basket in pool["baskets"].items()
        ]
        _add_component_ranks(snapshots, spec)

        qqq_row = qqq.loc[date]
        risk_on = bool(qqq_row["risk_on"]) if not pd.isna(qqq_row["risk_on"]) else False
        selected_baskets: list[str] = []
        selected_symbols: dict[str, list[dict[str, Any]]] = {}
        rotation_reasons: list[str] = []
        if not risk_on:
            rotation_reasons.append("ROTATION_MARKET_RISK_OFF")
        else:
            candidates = sorted(
                [snapshot for snapshot in snapshots if snapshot["score_gate_passed"]],
                key=lambda item: (-float(item["composite_percentile"]), item["basket"]),
            )
            for snapshot in candidates:
                securities = _select_securities(
                    date,
                    list(snapshot["members"]),
                    indicators,
                    states,
                    spec,
                )
                if not securities:
                    snapshot["reason_codes"].append(
                        "BASKET_NO_STATE_ELIGIBLE_SECURITY"
                    )
                    continue
                basket_name = str(snapshot["basket"])
                selected_baskets.append(basket_name)
                selected_symbols[basket_name] = securities
                snapshot["selected"] = True
                snapshot["reason_codes"].append("BASKET_SELECTED")
                if len(selected_baskets) >= int(
                    spec["rotation"]["maximum_selected_baskets"]
                ):
                    break
            if not selected_baskets:
                rotation_reasons.append("ROTATION_NO_ELIGIBLE_BASKET")

        selected_set = set(selected_baskets)
        for snapshot in snapshots:
            if (
                snapshot["score_gate_passed"]
                and snapshot["basket"] not in selected_set
                and "BASKET_NO_STATE_ELIGIBLE_SECURITY" not in snapshot["reason_codes"]
            ):
                snapshot["reason_codes"].append("BASKET_NOT_SELECTED_SCORE_ORDER")
            score_history.append(snapshot)

        actionable = next_sessions.get(date)
        rotations.append(
            {
                "date": date.date().isoformat(),
                "actionable_from": (
                    None if actionable is None else actionable.date().isoformat()
                ),
                "risk_on": risk_on,
                "market_regime": str(qqq_row["market_regime"]),
                "selected_baskets": selected_baskets,
                "selected_symbols_by_basket": selected_symbols,
                "reason_codes": rotation_reasons or ["ROTATION_SELECTION_COMPLETED"],
            }
        )
    return score_history, rotations


def build_portfolio_state_history(
    indicators: pd.DataFrame,
    signal_history: list[dict[str, Any]],
    rotations: list[dict[str, Any]],
    spec: Mapping[str, Any],
) -> list[dict[str, Any]]:
    states = _state_frame(signal_history).set_index(["date", "symbol"])
    qqq = indicators[indicators["symbol"] == "QQQ"].sort_values("date")
    next_sessions = _next_session_map(qqq["date"])
    rotations_by_date = {
        pd.Timestamp(row["date"]): row
        for row in rotations
    }
    multipliers = {
        str(state): float(value)
        for state, value in spec["security_selection"]["eligible_states"].items()
    }

    current_rotation: dict[str, Any] | None = None
    history: list[dict[str, Any]] = []
    for _, qqq_row in qqq.iterrows():
        date = pd.Timestamp(qqq_row["date"])
        if date in rotations_by_date:
            current_rotation = rotations_by_date[date]

        risk_on = bool(qqq_row["risk_on"]) if not pd.isna(qqq_row["risk_on"]) else False
        selected_baskets = (
            list(current_rotation["selected_baskets"])
            if current_rotation is not None
            else []
        )
        selected_map = (
            dict(current_rotation["selected_symbols_by_basket"])
            if current_rotation is not None
            else {}
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
                target_weight = symbol_weight * multiplier if risk_on else 0.0
                positions.append(
                    {
                        "basket": basket,
                        "symbol": symbol,
                        "state": state,
                        "target_weight": float(target_weight),
                        "state_multiplier": float(multiplier),
                        "state_reason_codes": state_reasons,
                        "trailing_stop_3atr": trailing_stop,
                    }
                )

        gross = float(sum(position["target_weight"] for position in positions))
        if gross > float(spec["portfolio"]["maximum_gross_exposure"]) + 1e-12:
            raise ValueError("portfolio gross exposure exceeds frozen maximum")
        actionable = next_sessions.get(date)
        history.append(
            {
                "date": date.date().isoformat(),
                "actionable_from": (
                    None if actionable is None else actionable.date().isoformat()
                ),
                "rotation_date": (
                    None if current_rotation is None else current_rotation["date"]
                ),
                "risk_on": risk_on,
                "market_regime": str(qqq_row["market_regime"]),
                "selected_baskets": selected_baskets,
                "positions": positions,
                "gross_exposure": gross,
                "cash_weight": float(1.0 - gross),
                "reason_codes": reasons or ["PORTFOLIO_ROTATION_ACTIVE"],
            }
        )
    return history


def run_small_pool_rotation(
    *,
    spec_path: str | Path,
    prices_csv: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    spec, pool, resolved_spec_path, pool_path = load_rotation_contract(spec_path)
    repository_root = _repository_root(resolved_spec_path)
    timing_spec, formula_path = build_runtime_timing_spec(
        spec,
        pool,
        repository_root=repository_root,
    )
    prices_csv = Path(prices_csv).resolve()
    prices = load_long_ohlcv_csv(prices_csv, timing_spec)
    indicators = compute_rotation_indicators(prices, timing_spec)
    signal_history, _ = generate_signal_history(indicators, timing_spec)
    score_history, rotations = build_rotation_history(
        indicators,
        signal_history,
        spec,
        pool,
    )
    portfolio_history = build_portfolio_state_history(
        indicators,
        signal_history,
        rotations,
        spec,
    )

    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    pool_identity = build_pool_identity(pool, pool_path=pool_path)
    payloads: dict[str, dict[str, Any]] = {
        "pool_identity.json": pool_identity,
        "basket_score_history.json": {
            "schema_version": "1.0",
            "experiment_id": spec["experiment_id"],
            "rows": score_history,
        },
        "rotation_history.json": {
            "schema_version": "1.0",
            "experiment_id": spec["experiment_id"],
            "rows": rotations,
        },
        "portfolio_state_history.json": {
            "schema_version": "1.0",
            "experiment_id": spec["experiment_id"],
            "rows": portfolio_history,
        },
    }
    for filename, payload in payloads.items():
        write_json(output_dir / filename, payload)

    decision = {
        "schema_version": "1.0",
        "experiment_id": spec["experiment_id"],
        "decision": "rotation_implementation_contract_passed",
        "research_only": True,
        "trade_ready": False,
        "performance_evaluated": False,
        "reserved_performance_opened": False,
        "pool_id": pool["pool_id"],
        "candidate_count": pool_identity["candidate_count"],
        "basket_count": pool_identity["basket_count"],
        "rotation_count": len(rotations),
    }
    write_json(output_dir / "decision.json", decision)

    output_hashes = {
        filename: sha256_file(output_dir / filename)
        for filename in [*payloads, "decision.json"]
    }
    manifest = {
        "schema_version": "1.0",
        "experiment_id": spec["experiment_id"],
        "provider_identity_sha256": sha256_file(prices_csv),
        "rotation_spec_identity_sha256": sha256_file(resolved_spec_path),
        "pool_file_identity_sha256": sha256_file(pool_path),
        "pool_membership_identity_sha256": pool_identity[
            "membership_identity_sha256"
        ],
        "timing_formula_identity_sha256": sha256_file(formula_path),
        "input": {"prices_csv": str(prices_csv)},
        "outputs": output_hashes,
        "manifest_identity_sha256": canonical_sha256(
            {
                "provider": sha256_file(prices_csv),
                "rotation_spec": sha256_file(resolved_spec_path),
                "pool_membership": pool_identity["membership_identity_sha256"],
                "timing_formula": sha256_file(formula_path),
                "rotation_rows": len(rotations),
                "portfolio_rows": len(portfolio_history),
            }
        ),
    }
    write_json(output_dir / "evidence_manifest.json", manifest)
    return decision
