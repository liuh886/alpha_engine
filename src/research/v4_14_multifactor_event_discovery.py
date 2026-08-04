"""Governed multi-factor event discovery for the QQQ strategy family.

The module treats VIX/VXN, RSI20, Bollinger structure and QQQ-versus-VOO
relative strength as close-observable event descriptors.  It does not fit a
daily return model.  Candidate rules are small AND expressions selected only
inside chronological development windows; outer-fold outcomes remain untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from math import erfc, sqrt
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import _normalise_bars
from src.research.v4_2_rsi_vix_sgov_experiment import wilder_rsi


@dataclass(frozen=True)
class EventCondition:
    """One frozen threshold condition in the rule grammar."""

    family: str
    identifier: str
    feature: str
    operator: str
    threshold: float


@dataclass(frozen=True)
class EventRule:
    """One interpretable AND rule containing two or three conditions."""

    event_family: str
    conditions: tuple[EventCondition, ...]

    @property
    def rule_id(self) -> str:
        return self.event_family + "__" + "__".join(
            condition.identifier for condition in self.conditions
        )

    @property
    def condition_count(self) -> int:
        return len(self.conditions)

    def as_dict(self) -> dict[str, Any]:
        return {
            "event_family": self.event_family,
            "rule_id": self.rule_id,
            "condition_count": self.condition_count,
            "conditions": [
                {
                    "family": condition.family,
                    "id": condition.identifier,
                    "feature": condition.feature,
                    "operator": condition.operator,
                    "threshold": condition.threshold,
                }
                for condition in self.conditions
            ],
        }


@dataclass(frozen=True)
class DiscoveryResult:
    """All evidence emitted by the nested event-discovery process."""

    features: pd.DataFrame
    candidate_metrics: pd.DataFrame
    selected_rules: pd.DataFrame
    outer_events: pd.DataFrame
    fold_metrics: pd.DataFrame
    family_gates: pd.DataFrame
    rule_catalog: pd.DataFrame
    diagnostics: dict[str, Any]


def _rolling_percentile(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).apply(
        lambda values: float(np.mean(values <= values[-1])), raw=True
    )


def _bollinger(close: pd.Series, window: int = 20, width: float = 2.0) -> pd.DataFrame:
    mean = close.rolling(window, min_periods=window).mean()
    std = close.rolling(window, min_periods=window).std(ddof=0)
    upper = mean + width * std
    lower = mean - width * std
    scale = upper - lower
    pct_b = (close - lower) / scale.where(scale.abs() > 1e-12)
    bandwidth = scale / mean.where(mean.abs() > 1e-12)
    bandwidth_mean = bandwidth.rolling(63, min_periods=63).mean()
    bandwidth_std = bandwidth.rolling(63, min_periods=63).std(ddof=0)
    bandwidth_z = (bandwidth - bandwidth_mean) / bandwidth_std.where(
        bandwidth_std.abs() > 1e-12
    )
    return pd.DataFrame(
        {
            "mid": mean,
            "upper": upper,
            "lower": lower,
            "pct_b": pct_b,
            "bandwidth": bandwidth,
            "bandwidth_z63": bandwidth_z,
        },
        index=close.index,
    )


def _forward_total_return(values: pd.Series, horizon: int) -> pd.Series:
    """Return from next open through ``horizon`` open-to-open intervals."""

    array = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    output = np.full(len(array), np.nan, dtype=float)
    for location in range(len(array)):
        start = location + 1
        stop = start + horizon
        if stop > len(array):
            continue
        window = array[start:stop]
        if len(window) != horizon or not np.isfinite(window).all():
            continue
        output[location] = float(np.prod(1.0 + window) - 1.0)
    return pd.Series(output, index=values.index, dtype=float)


def _forward_mae(values: pd.Series, horizon: int) -> pd.Series:
    array = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    output = np.full(len(array), np.nan, dtype=float)
    for location in range(len(array)):
        start = location + 1
        stop = start + horizon
        if stop > len(array):
            continue
        window = array[start:stop]
        if len(window) != horizon or not np.isfinite(window).all():
            continue
        path = np.cumprod(1.0 + window) - 1.0
        output[location] = float(path.min())
    return pd.Series(output, index=values.index, dtype=float)


def _common_signal_frame(
    bars: Mapping[str, pd.DataFrame],
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    symbols = ("QQQ", "TQQQ", "VOO", "BIL", "^VIX", "^VXN")
    normalized = {
        symbol: _normalise_bars(bars[symbol], symbol) for symbol in symbols
    }
    index = normalized["QQQ"].index
    for symbol in symbols[1:]:
        index = index.intersection(normalized[symbol].index)
    index = pd.DatetimeIndex(index.sort_values())
    if len(index) < 500:
        raise ValueError("multi-factor common signal history is too short")
    frame = pd.DataFrame(index=index)
    for symbol in symbols:
        safe = symbol.replace("^", "").lower()
        frame[f"{safe}_open"] = normalized[symbol].reindex(index)["open"]
        frame[f"{safe}_close"] = normalized[symbol].reindex(index)["close"]
        frame[f"{safe}_next_open_return"] = (
            normalized[symbol].reindex(index)["open"].shift(-1)
            / normalized[symbol].reindex(index)["open"]
            - 1.0
        )
    return frame, normalized


def build_multifactor_feature_frame(
    bars: Mapping[str, pd.DataFrame],
    proxy_baseline_daily: pd.DataFrame,
) -> pd.DataFrame:
    """Build the frozen VIX/VXN/RSI20/Bollinger/QQQ-VOO feature matrix."""

    frame, _ = _common_signal_frame(bars)
    qqq = frame["qqq_close"]
    voo = frame["voo_close"]
    vix = frame["vix_close"]
    vxn = frame["vxn_close"]

    vix_pct = _rolling_percentile(vix, 252)
    vxn_pct = _rolling_percentile(vxn, 252)
    vix_retreat = 1.0 - vix / vix.rolling(20, min_periods=20).max()
    vxn_retreat = 1.0 - vxn / vxn.rolling(20, min_periods=20).max()
    ratio = vxn / vix.where(vix.abs() > 1e-12)
    ratio_mean = ratio.rolling(63, min_periods=63).mean()
    ratio_std = ratio.rolling(63, min_periods=63).std(ddof=0)

    qqq_boll = _bollinger(qqq)
    voo_boll = _bollinger(voo)
    qqq_ma20 = qqq.rolling(20, min_periods=20).mean()
    qqq_ma50 = qqq.rolling(50, min_periods=50).mean()
    qqq_ma200 = qqq.rolling(200, min_periods=200).mean()
    voo_ma50 = voo.rolling(50, min_periods=50).mean()
    voo_ma200 = voo.rolling(200, min_periods=200).mean()
    qqq_voo_ratio = qqq / voo
    qqq_voo_ratio_ma20 = qqq_voo_ratio.rolling(20, min_periods=20).mean()
    qqq_daily_return = qqq.pct_change(fill_method=None)

    frame["vol_max_percentile_252"] = pd.concat(
        [vix_pct, vxn_pct], axis=1
    ).max(axis=1)
    frame["vol_max_return_5d"] = pd.concat(
        [vix.pct_change(5), vxn.pct_change(5)], axis=1
    ).max(axis=1)
    frame["vol_min_retreat_20d"] = pd.concat(
        [vix_retreat, vxn_retreat], axis=1
    ).min(axis=1)
    frame["vxn_vix_ratio_z63"] = (ratio - ratio_mean) / ratio_std.where(
        ratio_std.abs() > 1e-12
    )
    frame["vxn_minus_vix_percentile"] = vxn_pct - vix_pct
    frame["vxn_minus_vix_return_5d"] = vxn.pct_change(5) - vix.pct_change(5)

    frame["qqq_rsi20"] = wilder_rsi(qqq, period=20)
    frame["qqq_bollinger_pct_b_20_2"] = qqq_boll["pct_b"]
    frame["qqq_bollinger_bandwidth_z63"] = qqq_boll["bandwidth_z63"]
    frame["qqq_distance_ma20"] = qqq / qqq_ma20 - 1.0
    frame["qqq_distance_ma50"] = qqq / qqq_ma50 - 1.0
    frame["qqq_distance_ma200"] = qqq / qqq_ma200 - 1.0
    frame["qqq_ma20_slope_5d"] = qqq_ma20 / qqq_ma20.shift(5) - 1.0
    frame["qqq_drawdown_63d"] = qqq / qqq.rolling(63, min_periods=63).max() - 1.0
    frame["qqq_realized_volatility_20d"] = (
        qqq_daily_return.rolling(20, min_periods=20).std(ddof=0) * np.sqrt(252.0)
    )

    frame["qqq_minus_voo_return_5d"] = qqq.pct_change(5) - voo.pct_change(5)
    frame["qqq_minus_voo_return_20d"] = qqq.pct_change(20) - voo.pct_change(20)
    frame["qqq_voo_rs_distance_ma20"] = (
        qqq_voo_ratio / qqq_voo_ratio_ma20 - 1.0
    )
    frame["qqq_voo_trend_gap"] = qqq.gt(qqq_ma50).astype(float) - voo.gt(
        voo_ma50
    ).astype(float)
    frame["qqq_voo_bollinger_gap"] = qqq_boll["pct_b"] - voo_boll["pct_b"]
    frame["voo_distance_ma200"] = voo / voo_ma200 - 1.0

    stress_now = frame["vol_max_percentile_252"].ge(0.80) | frame[
        "qqq_drawdown_63d"
    ].le(-0.08)
    frame["recent_stress"] = (
        stress_now.astype(float).rolling(20, min_periods=1).max().fillna(0.0).gt(0.0)
    )
    proxy_state = proxy_baseline_daily["position_state"].reindex(frame.index)
    frame["v4_2_execution_state"] = proxy_state.shift(-1)

    horizons = (5, 10, 20)
    for horizon in horizons:
        for symbol in ("qqq", "tqqq", "voo", "bil"):
            frame[f"forward_{symbol}_{horizon}d"] = _forward_total_return(
                frame[f"{symbol}_next_open_return"], horizon
            )
    frame["forward_qqq_mae_20d"] = _forward_mae(
        frame["qqq_next_open_return"], 20
    )
    frame["forward_tqqq_mae_20d"] = _forward_mae(
        frame["tqqq_next_open_return"], 20
    )
    frame["target_defense"] = frame["forward_bil_10d"] - frame[
        "forward_qqq_10d"
    ]
    frame["target_repair"] = frame["forward_qqq_10d"] - frame[
        "forward_bil_10d"
    ]
    frame["target_tech_acceleration"] = frame["forward_tqqq_10d"] - frame[
        "forward_qqq_10d"
    ]
    frame["target_broad_rotation"] = frame["forward_voo_10d"] - frame[
        "forward_qqq_10d"
    ]
    frame.index.name = "signal_close_date"
    return frame


def _condition_from_dict(family: str, raw: Mapping[str, Any]) -> EventCondition:
    operator = str(raw["operator"])
    if operator not in {"ge", "le"}:
        raise ValueError(f"unsupported condition operator: {operator}")
    return EventCondition(
        family=family,
        identifier=str(raw["id"]),
        feature=str(raw["feature"]),
        operator=operator,
        threshold=float(raw["threshold"]),
    )


def enumerate_rules(contract: Mapping[str, Any]) -> list[EventRule]:
    """Enumerate the bounded two- and three-condition AND grammar."""

    rules: list[EventRule] = []
    for event_family, specification in contract["families"].items():
        volatility = [
            _condition_from_dict("volatility", raw)
            for raw in specification["volatility_conditions"]
        ]
        price = [
            _condition_from_dict("price", raw)
            for raw in specification["price_conditions"]
        ]
        cross = [
            _condition_from_dict("cross_index", raw)
            for raw in specification["cross_conditions"]
        ]
        for volatility_condition, price_condition in product(volatility, price):
            rules.append(
                EventRule(event_family, (volatility_condition, price_condition))
            )
            for cross_condition in cross:
                rules.append(
                    EventRule(
                        event_family,
                        (volatility_condition, price_condition, cross_condition),
                    )
                )
    identifiers = [rule.rule_id for rule in rules]
    if len(identifiers) != len(set(identifiers)):
        raise AssertionError("event rule identifiers must be unique")
    return rules


def rule_catalog_frame(rules: Sequence[EventRule]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for rule in rules:
        row = {
            "event_family": rule.event_family,
            "rule_id": rule.rule_id,
            "condition_count": rule.condition_count,
        }
        for position, condition in enumerate(rule.conditions, start=1):
            row[f"condition_{position}_family"] = condition.family
            row[f"condition_{position}_id"] = condition.identifier
            row[f"condition_{position}_feature"] = condition.feature
            row[f"condition_{position}_operator"] = condition.operator
            row[f"condition_{position}_threshold"] = condition.threshold
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["event_family", "rule_id"])


def _apply_condition(frame: pd.DataFrame, condition: EventCondition) -> pd.Series:
    values = pd.to_numeric(frame[condition.feature], errors="coerce")
    if condition.operator == "ge":
        return values.ge(condition.threshold) & values.notna()
    return values.le(condition.threshold) & values.notna()


def _eligibility_mask(frame: pd.DataFrame, eligibility: str) -> pd.Series:
    if eligibility == "always":
        return pd.Series(True, index=frame.index)
    if eligibility == "recent_stress":
        return frame["recent_stress"].fillna(False).astype(bool)
    if eligibility == "v4_2_state_2":
        return frame["v4_2_execution_state"].eq(2)
    if eligibility == "voo_long_trend_positive":
        return frame["voo_distance_ma200"].ge(0.0)
    raise ValueError(f"unknown event eligibility: {eligibility}")


def rule_mask(
    frame: pd.DataFrame,
    rule: EventRule,
    contract: Mapping[str, Any],
) -> pd.Series:
    specification = contract["families"][rule.event_family]
    mask = _eligibility_mask(frame, str(specification["eligibility"]))
    for condition in rule.conditions:
        mask &= _apply_condition(frame, condition)
    return mask.fillna(False).astype(bool)


def _nonoverlap_locations(
    mask: pd.Series,
    *,
    holding_sessions: int,
    cooldown_sessions: int,
) -> list[int]:
    locations: list[int] = []
    next_allowed = 0
    for location, active in enumerate(mask.to_numpy(dtype=bool)):
        if location < next_allowed or not active:
            continue
        if location + 1 + holding_sessions > len(mask):
            continue
        locations.append(location)
        next_allowed = location + 1 + holding_sessions + cooldown_sessions
    return locations


def events_for_rule(
    frame: pd.DataFrame,
    rule: EventRule,
    contract: Mapping[str, Any],
    *,
    fold: str,
    sample: str,
) -> pd.DataFrame:
    grammar = contract["rule_grammar"]
    target_column = f"target_{rule.event_family}"
    raw_mask = rule_mask(frame, rule, contract)
    raw_mask &= frame[target_column].notna()
    locations = _nonoverlap_locations(
        raw_mask,
        holding_sessions=int(grammar["holding_sessions"]),
        cooldown_sessions=int(grammar["cooldown_sessions"]),
    )
    rows: list[dict[str, Any]] = []
    horizon = int(grammar["holding_sessions"])
    for number, location in enumerate(locations, start=1):
        signal_date = frame.index[location]
        execution_date = frame.index[location + 1]
        end_date = frame.index[location + horizon]
        row = {
            "fold": fold,
            "sample": sample,
            "event_family": rule.event_family,
            "rule_id": rule.rule_id,
            "event_id": f"{fold}_{rule.event_family}_{number:03d}",
            "signal_close_date": signal_date,
            "execution_date": execution_date,
            "event_end_date": end_date,
            "holding_sessions": horizon,
            "target_excess_return": float(frame.iloc[location][target_column]),
            "win": bool(frame.iloc[location][target_column] > 0.0),
            "qqq_return_5d": float(frame.iloc[location]["forward_qqq_5d"]),
            "qqq_return_10d": float(frame.iloc[location]["forward_qqq_10d"]),
            "qqq_return_20d": float(frame.iloc[location]["forward_qqq_20d"]),
            "tqqq_return_10d": float(frame.iloc[location]["forward_tqqq_10d"]),
            "voo_return_10d": float(frame.iloc[location]["forward_voo_10d"]),
            "cash_return_10d": float(frame.iloc[location]["forward_bil_10d"]),
            "qqq_mae_20d": float(frame.iloc[location]["forward_qqq_mae_20d"]),
            "tqqq_mae_20d": float(frame.iloc[location]["forward_tqqq_mae_20d"]),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def _one_sided_mean_pvalue(event: pd.Series, baseline: pd.Series) -> float:
    event_values = pd.to_numeric(event, errors="coerce").dropna()
    baseline_values = pd.to_numeric(baseline, errors="coerce").dropna()
    if len(event_values) < 2 or len(baseline_values) < 2:
        return 1.0
    variance = event_values.var(ddof=1) / len(event_values) + baseline_values.var(
        ddof=1
    ) / len(baseline_values)
    if not np.isfinite(variance) or variance <= 1e-18:
        return 0.0 if event_values.mean() > baseline_values.mean() else 1.0
    z_score = float((event_values.mean() - baseline_values.mean()) / sqrt(variance))
    return float(0.5 * erfc(z_score / sqrt(2.0)))


def _benjamini_hochberg(pvalues: pd.Series) -> pd.Series:
    values = pd.to_numeric(pvalues, errors="coerce").fillna(1.0).clip(0.0, 1.0)
    order = np.argsort(values.to_numpy())
    sorted_values = values.to_numpy()[order]
    count = len(sorted_values)
    adjusted = np.empty(count, dtype=float)
    running = 1.0
    for reverse_position in range(count - 1, -1, -1):
        rank = reverse_position + 1
        candidate = sorted_values[reverse_position] * count / rank
        running = min(running, candidate)
        adjusted[reverse_position] = min(running, 1.0)
    output = np.empty(count, dtype=float)
    output[order] = adjusted
    return pd.Series(output, index=values.index, dtype=float)


def evaluate_rule_development(
    frame: pd.DataFrame,
    rule: EventRule,
    contract: Mapping[str, Any],
    *,
    fold: str,
) -> dict[str, Any]:
    specification = contract["families"][rule.event_family]
    target_column = f"target_{rule.event_family}"
    eligibility = _eligibility_mask(frame, str(specification["eligibility"]))
    baseline = frame.loc[eligibility, target_column].dropna()
    events = events_for_rule(frame, rule, contract, fold=fold, sample="development")
    event_values = (
        events["target_excess_return"] if not events.empty else pd.Series(dtype=float)
    )
    raw_mask = rule_mask(frame, rule, contract)
    active_fraction = float(raw_mask.mean()) if len(raw_mask) else 0.0
    base_win_rate = float(baseline.gt(0.0).mean()) if len(baseline) else np.nan
    event_win_rate = float(event_values.gt(0.0).mean()) if len(event_values) else np.nan
    lift = event_win_rate - base_win_rate if np.isfinite(event_win_rate) else np.nan
    mean_excess = float(event_values.mean()) if len(event_values) else np.nan
    median_excess = float(event_values.median()) if len(event_values) else np.nan
    score = (
        mean_excess
        + median_excess
        + 0.02 * lift
        - 0.005 * active_fraction
        if np.isfinite(mean_excess)
        and np.isfinite(median_excess)
        and np.isfinite(lift)
        else -np.inf
    )
    return {
        "fold": fold,
        "sample": "development",
        "event_family": rule.event_family,
        "rule_id": rule.rule_id,
        "condition_count": rule.condition_count,
        "events": int(len(events)),
        "macro_sessions": int(len(frame)),
        "active_session_fraction": active_fraction,
        "base_win_rate": base_win_rate,
        "event_win_rate": event_win_rate,
        "conditional_win_rate_lift": lift,
        "mean_excess_return": mean_excess,
        "median_excess_return": median_excess,
        "score": float(score),
        "pvalue": _one_sided_mean_pvalue(event_values, baseline),
    }


def _date_slice(frame: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    return frame.loc[pd.Timestamp(start) : pd.Timestamp(end)].copy()


def _assign_macro_clusters(events: pd.DataFrame, calendar_days: int) -> pd.DataFrame:
    if events.empty:
        output = events.copy()
        output["macro_cluster_id"] = pd.Series(dtype=str)
        return output
    output = events.sort_values("signal_close_date").copy()
    cluster = 0
    anchor: pd.Timestamp | None = None
    cluster_ids: list[str] = []
    for raw_date in pd.to_datetime(output["signal_close_date"]):
        date = pd.Timestamp(raw_date)
        if anchor is None or (date - anchor).days > calendar_days:
            cluster += 1
            anchor = date
        cluster_ids.append(f"macro_{cluster:03d}")
    output["macro_cluster_id"] = cluster_ids
    return output


def _family_gate(
    events: pd.DataFrame,
    fold_metrics: pd.DataFrame,
    selected_rules: pd.DataFrame,
    family: str,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    thresholds = contract["validation"]["event_quality"]
    family_events = events.loc[events["event_family"].eq(family)].copy()
    family_folds = fold_metrics.loc[fold_metrics["event_family"].eq(family)].copy()
    family_selected = selected_rules.loc[
        selected_rules["event_family"].eq(family)
        & selected_rules["executed_in_outer_fold"].astype(bool)
    ].copy()
    if family_events.empty:
        return {
            "event_family": family,
            "events": 0,
            "macro_clusters": 0,
            "positive_outer_fold_rate": 0.0,
            "conditional_win_rate_lift": np.nan,
            "median_excess_return": np.nan,
            "largest_positive_cluster_share": 1.0,
            "excess_without_best_year": np.nan,
            "rule_recurrence_rate": 0.0,
            "passed": False,
        }
    clustered = _assign_macro_clusters(
        family_events,
        int(contract["rule_grammar"]["macro_cluster_calendar_days"]),
    )
    positive_fold_rate = (
        float(family_folds["mean_excess_return"].gt(0.0).mean())
        if len(family_folds)
        else 0.0
    )
    conditional_lift = float(family_folds["conditional_win_rate_lift"].mean())
    median_excess = float(family_events["target_excess_return"].median())
    cluster_positive = (
        clustered.groupby("macro_cluster_id")["target_excess_return"]
        .sum()
        .clip(lower=0.0)
    )
    largest_cluster_share = (
        float(cluster_positive.max() / cluster_positive.sum())
        if float(cluster_positive.sum()) > 0.0
        else 1.0
    )
    yearly = clustered.groupby(
        pd.to_datetime(clustered["signal_close_date"]).dt.year
    )["target_excess_return"].sum()
    if len(yearly) > 1:
        best_year = yearly.idxmax()
        without_best_year = float(yearly.drop(index=best_year).sum())
    else:
        without_best_year = np.nan
    recurrence = (
        float(family_selected["rule_id"].value_counts().max() / len(contract["outer_folds"]))
        if len(family_selected)
        else 0.0
    )
    checks = {
        "macro_clusters": int(clustered["macro_cluster_id"].nunique())
        >= int(thresholds["minimum_macro_clusters"]),
        "positive_outer_fold_rate": positive_fold_rate
        >= float(thresholds["positive_outer_fold_rate_min"]),
        "conditional_win_rate_lift": conditional_lift
        >= float(thresholds["conditional_win_rate_lift_min"]),
        "median_excess_return": median_excess
        > float(thresholds["median_excess_return_min"]),
        "cluster_concentration": largest_cluster_share
        <= float(thresholds["largest_positive_cluster_share_max"]),
        "without_best_year": np.isfinite(without_best_year)
        and without_best_year >= 0.0,
        "rule_recurrence": recurrence
        >= float(thresholds["recurrence_rate_min"]),
    }
    return {
        "event_family": family,
        "events": int(len(clustered)),
        "macro_clusters": int(clustered["macro_cluster_id"].nunique()),
        "positive_outer_fold_rate": positive_fold_rate,
        "conditional_win_rate_lift": conditional_lift,
        "median_excess_return": median_excess,
        "largest_positive_cluster_share": largest_cluster_share,
        "excess_without_best_year": without_best_year,
        "rule_recurrence_rate": recurrence,
        "checks": checks,
        "passed": bool(all(checks.values())),
    }


def run_nested_event_discovery(
    features: pd.DataFrame,
    contract: Mapping[str, Any],
) -> DiscoveryResult:
    """Run bounded development selection and untouched outer-fold evaluation."""

    rules = enumerate_rules(contract)
    rules_by_id = {rule.rule_id: rule for rule in rules}
    candidate_rows: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []
    outer_events: list[pd.DataFrame] = []
    fold_rows: list[dict[str, Any]] = []
    selected_count = int(contract["rule_grammar"]["selected_rules_per_family"])
    minimum_events = int(contract["rule_grammar"]["minimum_development_events"])
    maximum_active = float(
        contract["rule_grammar"]["maximum_active_session_fraction"]
    )
    fdr_alpha = float(contract["rule_grammar"]["fdr_alpha"])

    for fold_specification in contract["outer_folds"]:
        fold = str(fold_specification["fold"])
        development = _date_slice(
            features,
            str(fold_specification["train_start"]),
            str(fold_specification["train_end"]),
        )
        outer = _date_slice(
            features,
            str(fold_specification["test_start"]),
            str(fold_specification["test_end"]),
        )
        for family in contract["families"]:
            family_rules = [rule for rule in rules if rule.event_family == family]
            metrics = pd.DataFrame(
                [
                    evaluate_rule_development(
                        development, rule, contract, fold=fold
                    )
                    for rule in family_rules
                ]
            )
            metrics["qvalue"] = _benjamini_hochberg(metrics["pvalue"])
            metrics["meets_frequency_bounds"] = (
                metrics["events"].ge(minimum_events)
                & metrics["active_session_fraction"].le(maximum_active)
            )
            metrics["fdr_pass"] = metrics["qvalue"].le(fdr_alpha)
            metrics = metrics.sort_values(
                ["meets_frequency_bounds", "fdr_pass", "score", "rule_id"],
                ascending=[False, False, False, True],
            ).reset_index(drop=True)
            metrics["development_rank"] = np.arange(1, len(metrics) + 1)
            candidate_rows.extend(metrics.to_dict(orient="records"))

            eligible = metrics.loc[metrics["meets_frequency_bounds"]].head(
                selected_count
            )
            champion_rule: EventRule | None = None
            for rank, row in enumerate(eligible.itertuples(index=False), start=1):
                executed = bool(rank == 1 and row.fdr_pass)
                selected_rows.append(
                    {
                        "fold": fold,
                        "event_family": family,
                        "selection_rank": rank,
                        "rule_id": row.rule_id,
                        "development_events": int(row.events),
                        "development_score": float(row.score),
                        "development_pvalue": float(row.pvalue),
                        "development_qvalue": float(row.qvalue),
                        "fdr_pass": bool(row.fdr_pass),
                        "executed_in_outer_fold": executed,
                    }
                )
                if executed:
                    champion_rule = rules_by_id[str(row.rule_id)]
            if champion_rule is None:
                fold_rows.append(
                    {
                        "fold": fold,
                        "event_family": family,
                        "rule_id": "none",
                        "events": 0,
                        "base_win_rate": np.nan,
                        "event_win_rate": np.nan,
                        "conditional_win_rate_lift": np.nan,
                        "mean_excess_return": np.nan,
                        "median_excess_return": np.nan,
                    }
                )
                continue

            events = events_for_rule(
                outer,
                champion_rule,
                contract,
                fold=fold,
                sample="outer",
            )
            specification = contract["families"][family]
            target_column = f"target_{family}"
            eligibility = _eligibility_mask(
                outer, str(specification["eligibility"])
            )
            baseline = outer.loc[eligibility, target_column].dropna()
            base_win_rate = float(baseline.gt(0.0).mean()) if len(baseline) else np.nan
            if events.empty:
                event_win_rate = np.nan
                mean_excess = np.nan
                median_excess = np.nan
            else:
                events["base_win_rate"] = base_win_rate
                events["action"] = str(specification["action"])
                outer_events.append(events)
                event_win_rate = float(events["win"].mean())
                mean_excess = float(events["target_excess_return"].mean())
                median_excess = float(events["target_excess_return"].median())
            fold_rows.append(
                {
                    "fold": fold,
                    "event_family": family,
                    "rule_id": champion_rule.rule_id,
                    "events": int(len(events)),
                    "base_win_rate": base_win_rate,
                    "event_win_rate": event_win_rate,
                    "conditional_win_rate_lift": event_win_rate - base_win_rate
                    if np.isfinite(event_win_rate) and np.isfinite(base_win_rate)
                    else np.nan,
                    "mean_excess_return": mean_excess,
                    "median_excess_return": median_excess,
                }
            )

    candidate_metrics = pd.DataFrame(candidate_rows)
    selected_rules = pd.DataFrame(selected_rows)
    events = (
        pd.concat(outer_events, ignore_index=True)
        if outer_events
        else pd.DataFrame(
            columns=[
                "fold",
                "sample",
                "event_family",
                "rule_id",
                "event_id",
                "signal_close_date",
                "execution_date",
                "event_end_date",
                "holding_sessions",
                "target_excess_return",
                "win",
                "action",
            ]
        )
    )
    events = _assign_macro_clusters(
        events,
        int(contract["rule_grammar"]["macro_cluster_calendar_days"]),
    )
    fold_metrics = pd.DataFrame(fold_rows)
    family_gate_rows = [
        _family_gate(
            events,
            fold_metrics,
            selected_rules,
            family,
            contract,
        )
        for family in contract["families"]
    ]
    family_gates = pd.DataFrame(family_gate_rows)
    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "rules_evaluated": int(len(candidate_metrics)),
        "unique_rule_structures": int(len(rules)),
        "outer_folds": int(len(contract["outer_folds"])),
        "outer_events": int(len(events)),
        "families_with_passing_event_gate": family_gates.loc[
            family_gates["passed"].astype(bool), "event_family"
        ].tolist(),
        "historical_success_authorizes_shadow_only": True,
        "baseline_and_alerts_unchanged": True,
    }
    return DiscoveryResult(
        features=features,
        candidate_metrics=candidate_metrics,
        selected_rules=selected_rules,
        outer_events=events,
        fold_metrics=fold_metrics,
        family_gates=family_gates,
        rule_catalog=rule_catalog_frame(rules),
        diagnostics=diagnostics,
    )
