"""Cutoff-bound canonical factor evidence for governed strategy signals.

Strategy logic remains in the model-specific signal producer. This module only
projects already-computed inputs and rule states onto canonical FactorDefinitions,
then validates identity and freshness before the signal enters the common ledger.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from src.common.runtime_settings import PROJECT_ROOT
from src.factors.definition import FactorDefinition
from src.factors.library import FactorLibrary, load_factor_library

SCHEMA_VERSION = "strategy_factor_snapshot_v1"
LIBRARY_PATH = PROJECT_ROOT / "configs" / "factor_libraries" / "strategy_inputs.yaml"
QQQ_FAMILY = "qqq_rotation"
BYD_FAMILY = "byd_allocation"
EFFECT_VALUES = {"support", "veto", "neutral"}
FRESHNESS_VALUES = {"current", "stale", "blocked"}


class StrategyFactorSnapshotError(ValueError):
    """Raised when governed factor evidence is missing, stale, or inconsistent."""


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise StrategyFactorSnapshotError(f"{label} must be an object")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StrategyFactorSnapshotError(f"{label} must be a non-empty string")
    return value.strip()


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StrategyFactorSnapshotError(f"{label} must be numeric")
    result = float(value)
    if result != result or abs(result) == float("inf"):
        raise StrategyFactorSnapshotError(f"{label} must be finite")
    return result


def _definition(library: FactorLibrary, factor_id: str) -> FactorDefinition:
    try:
        return library.factor(factor_id)
    except ValueError as exc:
        raise StrategyFactorSnapshotError(str(exc)) from exc


def _observation(
    library: FactorLibrary,
    factor_id: str,
    *,
    value: object,
    observed_at: str,
    state: str,
    reason_code: str,
    effect: str = "neutral",
    reference: object = None,
) -> dict[str, Any]:
    definition = _definition(library, factor_id)
    if value is None:
        raise StrategyFactorSnapshotError(f"factor {factor_id} has no observation")
    if effect not in EFFECT_VALUES:
        raise StrategyFactorSnapshotError(f"unsupported factor effect: {effect}")

    if definition.output_dtype == "float64":
        normalized: object = _number(value, factor_id)
    elif definition.output_dtype == "bool":
        if not isinstance(value, bool):
            raise StrategyFactorSnapshotError(f"factor {factor_id} must be boolean")
        normalized = value
    elif definition.output_dtype == "string":
        normalized = _text(value, factor_id)
    else:
        raise StrategyFactorSnapshotError(
            f"factor {factor_id} has unsupported output dtype {definition.output_dtype!r}"
        )

    return {
        "factor_id": definition.factor_id,
        "factor_version": definition.factor_version,
        "implementation_hash": definition.implementation_hash,
        "display_name": definition.display_name,
        "information_family": definition.information_family,
        "value": normalized,
        "reference": reference,
        "state": state,
        "effect": effect,
        "reason_code": reason_code,
        "observed_at": observed_at,
    }


def _qqq_snapshot(
    library: FactorLibrary,
    signal: Mapping[str, Any],
    observed_at: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    price = _mapping(signal.get("price_context"), "signal.price_context")
    raw_volatility = signal.get("context")
    volatility = (
        raw_volatility
        if isinstance(raw_volatility, Mapping)
        else _mapping(signal.get("volatility_context"), "signal.volatility_context")
    )

    vix_stress = volatility.get("vix_stress") is True
    vix_release = volatility.get("vix_easing") is True or volatility.get("vix_normalized") is True
    vxn_stress = volatility.get("vxn_stress") is True
    price_failure = price.get("stress_price_failure") is True
    long_break = price.get("long_break") is True

    groups = ["qqq_core"]
    rows = [
        _observation(
            library,
            "strategy.qqq.vix_close",
            value=volatility.get("vix_close"),
            observed_at=observed_at,
            reference={
                "normal": volatility.get("vix_q_normal"),
                "stress": volatility.get("vix_q_stress"),
            },
            state=str(volatility.get("vix_regime") or "unknown"),
            effect="support" if vix_stress else "veto" if vix_release else "neutral",
            reason_code=(
                "vix_stress_supports_defense"
                if vix_stress
                else "vix_easing_supports_release"
                if vix_release
                else "vix_neutral"
            ),
        ),
        _observation(
            library,
            "strategy.qqq.vxn_close",
            value=volatility.get("vxn_close"),
            observed_at=observed_at,
            reference={
                "normal": volatility.get("vxn_q_normal"),
                "stress": volatility.get("vxn_q_stress"),
            },
            state=str(volatility.get("vxn_regime") or "unknown"),
            effect="support" if vxn_stress else "neutral",
            reason_code="vxn_stress_supports_defense" if vxn_stress else "vxn_neutral",
        ),
        _observation(
            library,
            "strategy.qqq.qqq_vs_ma20",
            value=price.get("qqq_vs_ma20"),
            observed_at=observed_at,
            reference=0.0,
            state="below" if price_failure else "at_or_above",
            effect="support" if price_failure else "veto",
            reason_code=(
                "price_below_ma20_supports_defense"
                if price_failure
                else "price_repair_supports_release"
            ),
        ),
        _observation(
            library,
            "strategy.qqq.qqq_vs_ma200",
            value=price.get("qqq_vs_ma200"),
            observed_at=observed_at,
            reference=0.0,
            state="long_break" if long_break else "above_long_trend",
            effect="support" if long_break else "neutral",
            reason_code="long_break_supports_defense" if long_break else "long_trend_intact",
        ),
    ]

    overlay_keys = ("rsi_14", "fear_greed_score", "ma200_falling", "strong_defense")
    if any(key in signal for key in overlay_keys):
        missing = [key for key in overlay_keys if key not in signal]
        if missing:
            raise StrategyFactorSnapshotError(
                f"QQQ overlay factor context is incomplete: {missing}"
            )
        rsi = _number(signal.get("rsi_14"), "signal.rsi_14")
        fear_greed = _number(signal.get("fear_greed_score"), "signal.fear_greed_score")
        ma200_falling = signal.get("ma200_falling")
        strong_defense = signal.get("strong_defense")
        if not isinstance(ma200_falling, bool) or not isinstance(strong_defense, bool):
            raise StrategyFactorSnapshotError("QQQ overlay rule state must be boolean")
        groups.append("qqq_overlay")
        rows.extend(
            [
                _observation(
                    library,
                    "strategy.qqq.rsi14",
                    value=rsi,
                    observed_at=observed_at,
                    reference=30.0,
                    state="panic" if rsi < 30.0 else "normal",
                    effect="support" if rsi < 30.0 else "neutral",
                    reason_code="rsi_panic" if rsi < 30.0 else "rsi_not_panic",
                ),
                _observation(
                    library,
                    "strategy.qqq.fear_greed",
                    value=fear_greed,
                    observed_at=observed_at,
                    reference=10.0,
                    state="extreme_fear" if fear_greed < 10.0 else "normal",
                    effect="support" if fear_greed < 10.0 else "neutral",
                    reason_code=(
                        "fear_greed_extreme_fear" if fear_greed < 10.0 else "fear_greed_not_extreme"
                    ),
                ),
                _observation(
                    library,
                    "strategy.qqq.ma200_falling",
                    value=ma200_falling,
                    observed_at=observed_at,
                    reference=False,
                    state="falling" if ma200_falling else "not_falling",
                    effect="support" if ma200_falling else "neutral",
                    reason_code=(
                        "falling_ma200_supports_slow_bear_defense"
                        if ma200_falling
                        else "ma200_not_falling"
                    ),
                ),
                _observation(
                    library,
                    "strategy.qqq.strong_defense",
                    value=strong_defense,
                    observed_at=observed_at,
                    reference=False,
                    state="active" if strong_defense else "inactive",
                    effect="support" if strong_defense else "neutral",
                    reason_code="strong_defense_active"
                    if strong_defense
                    else "strong_defense_inactive",
                ),
            ]
        )
    return groups, rows


def _byd_snapshot(
    library: FactorLibrary,
    signal: Mapping[str, Any],
    observed_at: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    context = _mapping(signal.get("factor_context"), "signal.factor_context")
    target_mode = str(signal.get("target_mode") or "")
    expansion_active = signal.get("expansion_active")
    if not isinstance(expansion_active, bool):
        raise StrategyFactorSnapshotError("signal.expansion_active must be boolean")

    mom20 = _number(context.get("mom_20"), "signal.factor_context.mom_20")
    mom60 = _number(context.get("mom_60"), "signal.factor_context.mom_60")
    financed = _number(
        context.get("financed_increment"), "signal.factor_context.financed_increment"
    )
    rows = [
        _observation(
            library,
            "strategy.byd.market_state",
            value=context.get("market_state"),
            observed_at=observed_at,
            state=str(context.get("market_state") or "unknown"),
            reason_code="market_regime_context",
        ),
        _observation(
            library,
            "strategy.byd.vol_state",
            value=context.get("vol_state"),
            observed_at=observed_at,
            state=str(context.get("vol_state") or "unknown"),
            reason_code="volatility_regime_context",
        ),
        _observation(
            library,
            "strategy.byd.momentum_20d",
            value=mom20,
            observed_at=observed_at,
            reference=0.0,
            state="positive" if mom20 > 0 else "negative",
            reason_code="momentum_20d_context",
        ),
        _observation(
            library,
            "strategy.byd.momentum_60d",
            value=mom60,
            observed_at=observed_at,
            reference=0.0,
            state="positive" if mom60 > 0 else "negative",
            reason_code="momentum_60d_context",
        ),
        _observation(
            library,
            "strategy.byd.drawdown_252d",
            value=context.get("drawdown_252"),
            observed_at=observed_at,
            reference=0.0,
            state="drawdown",
            reason_code="drawdown_252d_context",
        ),
        _observation(
            library,
            "strategy.byd.momentum_scale",
            value=context.get("momentum_scale"),
            observed_at=observed_at,
            reference=1.0,
            state="scaled",
            reason_code="momentum_scale_context",
        ),
        _observation(
            library,
            "strategy.byd.financed_increment",
            value=financed,
            observed_at=observed_at,
            reference=0.0,
            state="active" if financed > 0 else "inactive",
            effect="support" if financed > 0 else "neutral",
            reason_code="financed_increment_supports_expansion"
            if financed > 0
            else "no_financed_increment",
        ),
        _observation(
            library,
            "strategy.byd.expansion_active",
            value=expansion_active,
            observed_at=observed_at,
            reference=False,
            state="active" if expansion_active else "inactive",
            effect="support"
            if expansion_active and target_mode == "convex_expansion"
            else "neutral",
            reason_code="expansion_rule_active" if expansion_active else "expansion_rule_inactive",
        ),
    ]
    return ["byd_v1_2"], rows


def build_strategy_factor_snapshot(
    *,
    model_family_id: str,
    signal: Mapping[str, Any],
    library_path: str | Path = LIBRARY_PATH,
) -> dict[str, Any]:
    """Bind one signal's current factor inputs to canonical definitions."""

    signal_date = _text(signal.get("signal_date"), "signal.signal_date")
    observed_at = _text(
        signal.get("latest_data_date") or signal_date,
        "signal.latest_data_date",
    )
    library = load_factor_library(library_path)

    if model_family_id == QQQ_FAMILY:
        groups, rows = _qqq_snapshot(library, signal, observed_at)
    elif model_family_id == BYD_FAMILY:
        groups, rows = _byd_snapshot(library, signal, observed_at)
    else:
        raise StrategyFactorSnapshotError(
            f"no strategy factor materializer for family {model_family_id!r}"
        )

    expected_ids = [row.factor_id for row in library.factors_for_groups(groups)]
    actual_ids = [str(row["factor_id"]) for row in rows]
    if actual_ids != expected_ids:
        raise StrategyFactorSnapshotError(
            f"factor snapshot identity mismatch: expected={expected_ids}, actual={actual_ids}"
        )

    snapshot = {
        "schema_version": SCHEMA_VERSION,
        "model_family_id": model_family_id,
        "signal_date": signal_date,
        "observation_cutoff": observed_at,
        "freshness": "current" if signal.get("data_freshness_ok") is True else "stale",
        "catalog_id": library.catalog.catalog_id,
        "catalog_version": library.catalog.catalog_version,
        "catalog_implementation_hash": library.catalog.implementation_hash(),
        "source_sha256": library.source_sha256,
        "groups": groups,
        "factor_count": len(rows),
        "factors": rows,
        "research_only": True,
        "trade_ready": False,
    }
    validate_strategy_factor_snapshot(snapshot)
    return snapshot


def validate_strategy_factor_snapshot(snapshot: object) -> None:
    if not isinstance(snapshot, Mapping):
        raise StrategyFactorSnapshotError("factor snapshot must be an object")
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise StrategyFactorSnapshotError("unsupported factor snapshot schema")
    if snapshot.get("freshness") not in FRESHNESS_VALUES:
        raise StrategyFactorSnapshotError("unsupported factor snapshot freshness")
    if snapshot.get("research_only") is not True or snapshot.get("trade_ready") is not False:
        raise StrategyFactorSnapshotError("factor snapshot research boundary is invalid")

    _text(snapshot.get("signal_date"), "signal_date")
    cutoff = _text(snapshot.get("observation_cutoff"), "observation_cutoff")
    factors = snapshot.get("factors")
    if not isinstance(factors, list) or not factors:
        raise StrategyFactorSnapshotError("factor snapshot factors must be non-empty")
    if snapshot.get("factor_count") != len(factors):
        raise StrategyFactorSnapshotError("factor snapshot factor_count does not match factors")

    ids: set[str] = set()
    for row in factors:
        if not isinstance(row, Mapping):
            raise StrategyFactorSnapshotError("factor observation must be an object")
        factor_id = _text(row.get("factor_id"), "factor_id")
        if factor_id in ids:
            raise StrategyFactorSnapshotError(f"duplicate factor observation: {factor_id}")
        ids.add(factor_id)
        implementation_hash = _text(
            row.get("implementation_hash"), f"{factor_id}.implementation_hash"
        )
        if len(implementation_hash) != 64:
            raise StrategyFactorSnapshotError(f"{factor_id}.implementation_hash must be sha256")
        if row.get("effect") not in EFFECT_VALUES:
            raise StrategyFactorSnapshotError(f"invalid factor effect for {factor_id}")
        if row.get("observed_at") != cutoff:
            raise StrategyFactorSnapshotError(f"factor {factor_id} observation is not cutoff-bound")
