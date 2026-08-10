#!/usr/bin/env python3
"""Screen BYD successor state information without candidate optimization.

Issue #732 research only. The screen keeps three evidence lines separate:
1. controlled trend-expansion volatility-gate relaxation;
2. controlled SMA120/90/60 core sensitivity;
3. development-anchored continuous trend-quality / recovery-state features.

No branch is promotable from this script. All history through the frozen cutoff is
consumed evidence and every comparison is retrospective.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.common.runtime_settings import PROJECT_ROOT
from src.research.byd_515180_allocation import WINDOWS, metrics, prepare_common_dataset
from src.research.byd_v1_2_convex_momentum import (
    CANDIDATE as V12_MODEL_ID,
    MAX_FINANCED_INCREMENT,
    momentum_scale,
    run_candidates as run_v12_candidates,
)
from src.research.byd_v1_2_recovery_state import (
    build_research_dataset,
    load_canonical_snapshot,
)
from src.research.byd_v1_2_trend_expansion import (
    PRIMARY_FINANCING_RATE,
    RULES as EXPANSION_RULES,
    STRESS_FINANCING_RATE,
    run_financed_allocation,
)
from src.research.rules_based_allocation_experiment_runner import (
    _extract_inputs,
    _formal_daily,
    _formal_section,
    _load_formal,
    _load_spec,
    _trace_reproduction,
)

SPEC = PROJECT_ROOT / "configs/research_experiments/byd_v1_3_min_hold_bear_defense_certification_v1.yaml"
PRIMARY_COST_BPS = 20.0
STRESS_COST_BPS = 40.0
VOL_RELAX_RATIOS = (1.00, 1.15, 1.30)
SMA_WINDOWS = (120, 90, 60)
EPS = 1e-12

FEATURES: dict[str, dict[str, Any]] = {
    "norm_mom_20": {"family": "offense", "orientation": 1.0},
    "norm_mom_60": {"family": "offense", "orientation": 1.0},
    "directional_efficiency_20": {"family": "offense", "orientation": 1.0},
    "directional_efficiency_60": {"family": "offense", "orientation": 1.0},
    "drawdown_252": {"family": "recovery", "orientation": -1.0},
    "distance_from_low_20": {"family": "recovery", "orientation": 1.0},
    "momentum_accel_20_60": {"family": "recovery", "orientation": 1.0},
    "drawdown120_x_rebound20": {"family": "recovery", "orientation": 1.0},
    "drawdown252_x_rebound60": {"family": "recovery", "orientation": 1.0},
}


def _stateful_binary(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    active = False
    values: list[bool] = []
    for enter_now, exit_now in zip(
        entry.fillna(False), exit_.fillna(False), strict=True
    ):
        if active and bool(exit_now):
            active = False
        elif not active and bool(enter_now):
            active = True
        values.append(active)
    return pd.Series(values, index=entry.index, dtype=bool)


def _episodes(mask: pd.Series) -> pd.DataFrame:
    active = mask.fillna(False).astype(bool)
    starts = active & ~active.shift(1, fill_value=False)
    ids = starts.cumsum().where(active)
    rows: list[dict[str, Any]] = []
    for raw_id, block in active.groupby(ids):
        if pd.isna(raw_id):
            continue
        rows.append(
            {
                "episode_id": int(raw_id),
                "start": block.index.min(),
                "end": block.index.max(),
                "sessions": int(len(block)),
            }
        )
    return pd.DataFrame(rows)


def _window_slice(frame: pd.DataFrame | pd.Series, window: str) -> Any:
    start, end = WINDOWS[window]
    return frame.loc[pd.Timestamp(start) : pd.Timestamp(end)]


def _wealth(returns: pd.Series) -> float:
    clean = returns.dropna().astype(float)
    return float((1.0 + clean).prod()) if not clean.empty else 1.0


def _window_metrics(daily: pd.DataFrame, window: str) -> dict[str, float]:
    block = _window_slice(daily, window)
    output = metrics(block)
    returns = block["net_return"].dropna()
    output["financed_sessions"] = float(
        block.loc[returns.index, "borrowed_weight"].gt(EPS).sum()
    )
    output["transaction_cost_paid"] = float(block.loc[returns.index, "cost"].sum())
    output["financing_cost_paid"] = float(
        block.loc[returns.index, "financing_cost"].sum()
    )
    return output


def _relative_terminal_wealth(candidate: pd.DataFrame, baseline: pd.DataFrame, window: str) -> float:
    candidate_return = _wealth(_window_slice(candidate["net_return"], window))
    baseline_return = _wealth(_window_slice(baseline["net_return"], window))
    return candidate_return / baseline_return - 1.0


def _add_screen_features(full: pd.DataFrame) -> pd.DataFrame:
    frame = full.copy()
    close = frame["close"].astype(float)
    daily_path = close.diff().abs()
    sigma = frame["realized_vol_60"].replace(0.0, np.nan)
    frame["sma_90"] = close.rolling(90).mean()
    frame["vol_ratio_60"] = sigma / frame["historical_vol_median"].replace(0.0, np.nan)
    frame["norm_mom_20"] = frame["mom_20"] / (sigma * np.sqrt(20.0))
    frame["norm_mom_60"] = frame["mom_60"] / (sigma * np.sqrt(60.0))
    frame["directional_efficiency_20"] = (
        close.diff(20) / daily_path.rolling(20).sum().replace(0.0, np.nan)
    )
    frame["directional_efficiency_60"] = (
        close.diff(60) / daily_path.rolling(60).sum().replace(0.0, np.nan)
    )
    return frame


def _core_position(full: pd.DataFrame, sma_window: int) -> pd.Series:
    sma_name = f"sma_{sma_window}"
    if sma_name not in full:
        raise ValueError(f"missing {sma_name}")
    entry = full["close"].gt(full[sma_name]) & full["mom_20"].gt(0.0)
    exit_ = full["close"].lt(full[sma_name]) & full["mom_60"].lt(0.0)
    active = _stateful_binary(entry, exit_)
    return (0.75 + 0.25 * active.astype(float)).rename(f"sma_{sma_window}_base")


def _core_decision(position: pd.Series, index: pd.DatetimeIndex) -> pd.DataFrame:
    base = position.reindex(index).astype(float)
    return pd.DataFrame(
        {
            "byd_weight": base,
            "etf_weight": 1.0 - base,
            "cash_weight": 0.0,
        },
        index=index,
    )


def _expansion_active(common: pd.DataFrame, base: pd.Series, vol_ratio_limit: float) -> pd.Series:
    vol_ratio = common["realized_vol_60"] / common["historical_vol_median"].replace(0.0, np.nan)
    entry = (
        base.eq(EXPANSION_RULES["entry_base_byd_weight"])
        & common["market_state"].eq(EXPANSION_RULES["entry_market_state"])
        & vol_ratio.le(vol_ratio_limit)
        & common["mom_20"].gt(EXPANSION_RULES["entry_mom_20_floor"])
        & common["mom_60"].gt(EXPANSION_RULES["entry_mom_60_floor"])
        & common["drawdown_252"].gt(EXPANSION_RULES["entry_drawdown_252_floor"])
    )
    exit_ = (
        base.eq(EXPANSION_RULES["exit_base_byd_weight"])
        | common["market_state"].ne(EXPANSION_RULES["exit_market_state_not"])
        | vol_ratio.gt(vol_ratio_limit)
        | common["mom_20"].le(EXPANSION_RULES["exit_mom_20_ceiling"])
    )
    return _stateful_binary(entry, exit_)


def _expansion_decision(
    common: pd.DataFrame,
    base: pd.Series,
    *,
    vol_ratio_limit: float,
) -> tuple[pd.DataFrame, pd.Series]:
    active = _expansion_active(common, base, vol_ratio_limit)
    scale = momentum_scale(common["mom_20"])
    increment = active.astype(float) * MAX_FINANCED_INCREMENT * scale
    byd = base + increment
    etf = (1.0 - base).where(increment.eq(0.0), 0.0)
    decision = pd.DataFrame(
        {
            "byd_weight": byd,
            "etf_weight": etf,
            "cash_weight": 1.0 - byd - etf,
        },
        index=common.index,
    )
    if not np.allclose(decision.sum(axis=1), 1.0, atol=1e-12):
        raise AssertionError("relaxed expansion decision weights do not sum to one")
    if decision["byd_weight"].gt(1.125 + EPS).any():
        raise AssertionError("relaxed expansion exceeds frozen 112.5% cap")
    return decision, active


def _performance_rows(
    variants: dict[str, Any],
    baseline_name: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scenario, cost_bps, financing_rate in (
        ("primary", PRIMARY_COST_BPS, PRIMARY_FINANCING_RATE),
        ("stress", STRESS_COST_BPS, STRESS_FINANCING_RATE),
    ):
        results = {
            name: run_financed_allocation(
                name,
                item["common"],
                item["decision"],
                cost_bps=cost_bps,
                annual_financing_rate=financing_rate,
            )
            for name, item in variants.items()
        }
        baseline = results[baseline_name].daily
        for name, result in results.items():
            for window in WINDOWS:
                metrics_row = _window_metrics(result.daily, window)
                rows.append(
                    {
                        "scenario": scenario,
                        "model": name,
                        "window": window,
                        **metrics_row,
                        "relative_terminal_wealth_vs_control": _relative_terminal_wealth(
                            result.daily, baseline, window
                        ),
                    }
                )
    return rows


def _transition_rows(positions: dict[str, pd.Series], common: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name, position in positions.items():
        aligned = position.reindex(common.index).astype(float)
        transitions = aligned.ne(aligned.shift(1)).fillna(False)
        risk_on = aligned.eq(1.0)
        risk_on_start = risk_on & ~risk_on.shift(1, fill_value=False)
        for year, index in pd.Series(common.index, index=common.index).groupby(common.index.year):
            period_index = pd.DatetimeIndex(index.values)
            starts = risk_on_start.reindex(period_index).fillna(False)
            forward10 = common["byd_open"].shift(-11) / common["byd_open"].shift(-1) - 1.0
            forward20 = common["byd_open"].shift(-21) / common["byd_open"].shift(-1) - 1.0
            rows.append(
                {
                    "model": name,
                    "year": int(year),
                    "sessions": int(len(period_index)),
                    "risk_on_share": float(risk_on.reindex(period_index).mean()),
                    "transitions": int(transitions.reindex(period_index).sum()),
                    "risk_on_starts": int(starts.sum()),
                    "mean_forward_10_after_risk_on_start": float(
                        forward10.reindex(period_index)[starts].mean()
                    ) if starts.any() else None,
                    "mean_forward_20_after_risk_on_start": float(
                        forward20.reindex(period_index)[starts].mean()
                    ) if starts.any() else None,
                }
            )
    return rows


def _feature_threshold(
    series: pd.Series,
    mask: pd.Series,
    orientation: float,
) -> float:
    sample = series.loc[mask].dropna()
    if len(sample) < 100:
        raise RuntimeError("insufficient development sample for feature threshold")
    quantile = 0.70 if orientation > 0 else 0.30
    return float(sample.quantile(quantile))


def _feature_state(series: pd.Series, threshold: float, orientation: float) -> pd.Series:
    return series.ge(threshold) if orientation > 0 else series.le(threshold)


def _screen_feature_rows(
    full: pd.DataFrame,
    common: pd.DataFrame,
    base: pd.Series,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    common_base = base.reindex(common.index).astype(float)
    development = common.index.to_series().between(
        pd.Timestamp(WINDOWS["development"][0]),
        pd.Timestamp(WINDOWS["development"][1]),
    )
    non_vol_expansion = (
        common_base.eq(1.0)
        & common["market_state"].eq(EXPANSION_RULES["entry_market_state"])
        & common["mom_20"].gt(0.0)
        & common["mom_60"].gt(0.0)
        & common["drawdown_252"].gt(EXPANSION_RULES["entry_drawdown_252_floor"])
    )
    current_vol_low = common["vol_state"].eq("low")
    low_vol_only_near_miss = non_vol_expansion & ~current_vol_low
    near_miss_2025_h1 = low_vol_only_near_miss & common.index.to_series().between(
        pd.Timestamp("2025-01-01"), pd.Timestamp("2025-06-30")
    )

    for feature, spec in FEATURES.items():
        orientation = float(spec["orientation"])
        family = str(spec["family"])
        series = full[feature].reindex(common.index).astype(float)
        eligible = common_base.eq(1.0) if family == "offense" else common_base.eq(0.75)
        threshold_mask = development & eligible
        threshold = _feature_threshold(series, threshold_mask, orientation)
        state = _feature_state(series, threshold, orientation) & eligible
        candidate_state = non_vol_expansion & state if family == "offense" else state
        episode_table = _episodes(candidate_state)

        for window in ("development", "fixed_validation", "retrospective_2025_plus"):
            start, end = WINDOWS[window]
            mask = common.index.to_series().between(pd.Timestamp(start), pd.Timestamp(end))
            selected = candidate_state & mask
            forward10 = full["forward_open_return_10"].reindex(common.index)[selected].dropna()
            forward20 = full["forward_open_return_20"].reindex(common.index)[selected].dropna()
            window_episodes = episode_table.loc[
                episode_table["start"].between(pd.Timestamp(start), pd.Timestamp(end))
            ] if not episode_table.empty else episode_table
            rows.append(
                {
                    "family": family,
                    "feature": feature,
                    "orientation": orientation,
                    "development_threshold": threshold,
                    "window": window,
                    "state_sessions": int(selected.sum()),
                    "state_hit_rate": float(selected.sum() / max(int(mask.sum()), 1)),
                    "episodes": int(len(window_episodes)),
                    "median_episode_sessions": float(window_episodes["sessions"].median())
                    if not window_episodes.empty else 0.0,
                    "max_episode_sessions": int(window_episodes["sessions"].max())
                    if not window_episodes.empty else 0,
                    "forward_10_samples": int(len(forward10)),
                    "mean_forward_10": float(forward10.mean()) if len(forward10) else None,
                    "median_forward_10": float(forward10.median()) if len(forward10) else None,
                    "forward_20_samples": int(len(forward20)),
                    "mean_forward_20": float(forward20.mean()) if len(forward20) else None,
                    "median_forward_20": float(forward20.median()) if len(forward20) else None,
                    "2025_h1_low_vol_near_miss_capture": int(
                        (candidate_state & near_miss_2025_h1).sum()
                    ) if family == "offense" else None,
                    "2026_state_sessions": int(
                        (
                            candidate_state
                            & common.index.to_series().between(
                                pd.Timestamp("2026-01-01"), common.index.max()
                            )
                        ).sum()
                    ),
                }
            )
    return rows


def _vol_gate_diagnostics(
    common: pd.DataFrame,
    base: pd.Series,
    active_by_ratio: dict[float, pd.Series],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    base = base.reindex(common.index).astype(float)
    vol_ratio = common["realized_vol_60"] / common["historical_vol_median"].replace(0.0, np.nan)
    other_entry = (
        base.eq(1.0)
        & common["market_state"].eq(EXPANSION_RULES["entry_market_state"])
        & common["mom_20"].gt(0.0)
        & common["mom_60"].gt(0.0)
        & common["drawdown_252"].gt(EXPANSION_RULES["entry_drawdown_252_floor"])
    )
    for ratio, active in active_by_ratio.items():
        entry = other_entry & vol_ratio.le(ratio)
        for year in sorted(set(common.index.year)):
            year_mask = common.index.year == year
            episodes = _episodes(active & year_mask)
            rows.append(
                {
                    "vol_ratio_limit": ratio,
                    "year": int(year),
                    "raw_entry_hits": int((entry & year_mask).sum()),
                    "active_sessions": int((active & year_mask).sum()),
                    "episodes": int(len(episodes)),
                    "median_episode_sessions": float(episodes["sessions"].median())
                    if not episodes.empty else 0.0,
                    "max_episode_sessions": int(episodes["sessions"].max())
                    if not episodes.empty else 0,
                }
            )
    return rows


def run() -> dict[str, Any]:
    spec = _load_spec(SPEC)
    with tempfile.TemporaryDirectory(prefix="byd-successor-screen-") as raw_root:
        root = Path(raw_root)
        byd_dir, etf_dir, data_identity = _extract_inputs(spec, root)
        common, signals, _ = prepare_common_dataset(byd_dir, etf_dir)
        cutoff = pd.Timestamp(str(spec["data"]["historical_cutoff"]))
        common = common.loc[:cutoff].copy()
        signals = signals.reindex(common.index)

        canonical = load_canonical_snapshot(byd_dir)
        full = build_research_dataset(canonical.adjusted, canonical.sessions)
        full.index = pd.to_datetime(full.index).normalize()
        full = _add_screen_features(full)

        formal = _load_formal(spec)
        performance_path, performance_sha = _formal_section(
            formal,
            "performance",
            str(spec["baseline"]["performance_sha256"]),
        )
        formal_daily = _formal_daily(performance_path, str(cutoff.date()))
        standard_results, _ = run_v12_candidates(
            common,
            signals,
            cost_bps=PRIMARY_COST_BPS,
            annual_financing_rate=PRIMARY_FINANCING_RATE,
        )
        trace = _trace_reproduction(formal_daily, standard_results[V12_MODEL_ID].daily)
        if not trace["exact"]:
            raise RuntimeError("successor screen refuses non-exact V1.2 champion reproduction")

        base = signals["base_byd_weight"].astype(float)

        vol_variants: dict[str, dict[str, Any]] = {}
        active_by_ratio: dict[float, pd.Series] = {}
        for ratio in VOL_RELAX_RATIOS:
            decision, active = _expansion_decision(
                common, base, vol_ratio_limit=ratio
            )
            name = f"vol_ratio_{ratio:.2f}"
            vol_variants[name] = {"common": common, "decision": decision}
            active_by_ratio[ratio] = active
        vol_performance = _performance_rows(vol_variants, "vol_ratio_1.00")

        ratio_control = run_financed_allocation(
            "vol_ratio_1.00",
            common,
            vol_variants["vol_ratio_1.00"]["decision"],
            cost_bps=PRIMARY_COST_BPS,
            annual_financing_rate=PRIMARY_FINANCING_RATE,
        )
        control_trace = _trace_reproduction(formal_daily, ratio_control.daily)
        if not control_trace["exact"]:
            raise RuntimeError("vol_ratio=1.00 does not reproduce formal V1.2")

        core_positions = {
            f"sma_{window}": _core_position(full, window)
            for window in SMA_WINDOWS
        }
        sma_variants = {
            name: {"common": common, "decision": _core_decision(position, common.index)}
            for name, position in core_positions.items()
        }
        sma_performance = _performance_rows(sma_variants, "sma_120")
        sma120_position = core_positions["sma_120"].reindex(common.index)
        if not np.allclose(sma120_position, base, atol=0.0, rtol=0.0):
            raise RuntimeError("SMA120 control does not reproduce maintained core state")

        feature_rows = _screen_feature_rows(full, common, base)

    return {
        "schema_version": "1.0",
        "issue": 732,
        "research_only": True,
        "historical_evidence_consumed": True,
        "automatic_promotion": False,
        "combination_grid_allowed": False,
        "baseline": {
            "model_id": V12_MODEL_ID,
            "bundle_id": formal.bundle_id,
            "performance_sha256": performance_sha,
            "formal_trace_reproduction": trace,
            "vol_ratio_1_00_trace_reproduction": control_trace,
        },
        "data_identity": data_identity,
        "pre_registered_controls": {
            "vol_ratio_limits": list(VOL_RELAX_RATIOS),
            "sma_windows": list(SMA_WINDOWS),
            "feature_state_threshold": "development q70 for positive orientation / q30 for negative orientation",
        },
        "vol_relaxation": {
            "performance": vol_performance,
            "annual_state_diagnostics": _vol_gate_diagnostics(
                common, base, active_by_ratio
            ),
        },
        "sma_sensitivity": {
            "performance": sma_performance,
            "annual_transitions": _transition_rows(core_positions, common),
        },
        "state_feature_screen": feature_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "artifacts/research/byd_successor_state_screen.json",
    )
    args = parser.parse_args()
    payload = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "baseline": payload["baseline"],
        "vol_relaxation": payload["vol_relaxation"],
        "sma_sensitivity": payload["sma_sensitivity"],
        "state_feature_screen": payload["state_feature_screen"],
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
