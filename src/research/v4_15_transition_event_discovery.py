"""Fresh transition-event discovery for the QQQ strategy family.

This module reuses the v4.14 close-observable feature set but transforms it into
first crossings and first confirmations.  A rule fires only when its final
required transition becomes confirmed inside a fixed three-session window; a
persistent state cannot retrigger the same rule on subsequent closes.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.v4_14_multifactor_event_discovery import (
    _assign_macro_clusters,
    _benjamini_hochberg,
    _date_slice,
    _one_sided_mean_pvalue,
    build_multifactor_feature_frame,
)


@dataclass(frozen=True)
class TransitionRule:
    event_family: str
    volatility_transition: str
    price_transition: str
    cross_transition: str | None

    @property
    def rule_id(self) -> str:
        components = [
            self.event_family,
            self.volatility_transition,
            self.price_transition,
        ]
        if self.cross_transition is not None:
            components.append(self.cross_transition)
        return "__".join(components)

    @property
    def condition_count(self) -> int:
        return 2 + int(self.cross_transition is not None)

    @property
    def motif_id(self) -> str:
        return "__".join(
            [
                self.event_family,
                _transition_motif(self.volatility_transition),
                _transition_motif(self.price_transition),
                _transition_motif(self.cross_transition)
                if self.cross_transition is not None
                else "no_cross",
            ]
        )


@dataclass(frozen=True)
class TransitionDiscoveryResult:
    features: pd.DataFrame
    transition_flags: pd.DataFrame
    rule_catalog: pd.DataFrame
    candidate_metrics: pd.DataFrame
    selected_rules: pd.DataFrame
    outer_events: pd.DataFrame
    fold_metrics: pd.DataFrame
    family_gates: pd.DataFrame
    diagnostics: dict[str, Any]


def _cross_up(values: pd.Series, threshold: float) -> pd.Series:
    return values.ge(threshold) & values.shift(1).lt(threshold)


def _cross_down(values: pd.Series, threshold: float) -> pd.Series:
    return values.le(threshold) & values.shift(1).gt(threshold)


def _transition_motif(identifier: str | None) -> str:
    if identifier is None:
        return "none"
    if "retreat" in identifier or "repaired" in identifier or "normalization" in identifier:
        return "vol_repair"
    if "stress_onset" in identifier or "spike_onset" in identifier or "premium_onset" in identifier:
        return "vol_onset"
    if identifier.startswith("rsi20"):
        return "rsi_cross"
    if "bollinger_pct_b" in identifier:
        return "bollinger_cross"
    if "ma20" in identifier:
        return "ma20_cross"
    if "bandwidth" in identifier:
        return "bandwidth_transition"
    if "rs_cross" in identifier:
        return "relative_strength_cross"
    if "bollinger_gap" in identifier:
        return "cross_bollinger_gap"
    if "return20" in identifier:
        return "cross_return20"
    return identifier


def build_transition_flags(
    features: pd.DataFrame,
    contract: Mapping[str, Any],
) -> pd.DataFrame:
    """Build one-session transition impulses from frozen v4.14 features."""

    flags = pd.DataFrame(False, index=features.index, columns=[])
    definitions = contract["transition_definitions"]
    for identifier, specification in definitions.items():
        kind = str(specification["kind"])
        if kind in {"cross_up", "cross_down"}:
            values = pd.to_numeric(
                features[str(specification["feature"])], errors="coerce"
            )
            threshold = float(specification["threshold"])
            signal = (
                _cross_up(values, threshold)
                if kind == "cross_up"
                else _cross_down(values, threshold)
            )
        elif kind == "vol_retreat_confirmed":
            prior_stress = (
                features["vol_max_percentile_252"]
                .shift(1)
                .rolling(10, min_periods=1)
                .max()
                .ge(0.80)
            )
            state = (
                prior_stress
                & features["vol_min_retreat_20d"].ge(0.15)
                & features["vol_max_return_5d"].le(0.0)
            )
            signal = state & ~state.shift(1, fill_value=False)
        elif kind == "tech_premium_repaired":
            prior_premium = (
                features["vxn_vix_ratio_z63"]
                .shift(1)
                .rolling(10, min_periods=1)
                .max()
                .ge(1.00)
            )
            state = prior_premium & features["vxn_vix_ratio_z63"].le(0.50)
            signal = state & ~state.shift(1, fill_value=False)
        elif kind == "vol_normalization_cross":
            prior_stress = (
                features["vol_max_percentile_252"]
                .shift(1)
                .rolling(20, min_periods=1)
                .max()
                .ge(0.80)
            )
            signal = prior_stress & _cross_down(
                features["vol_max_percentile_252"], 0.60
            )
        elif kind == "compression_release":
            prior_compression = (
                features["qqq_bollinger_bandwidth_z63"]
                .shift(1)
                .rolling(10, min_periods=1)
                .min()
                .le(-0.50)
            )
            signal = prior_compression & _cross_up(
                features["qqq_bollinger_bandwidth_z63"], 0.0
            )
        else:
            raise ValueError(f"unsupported transition kind: {kind}")
        flags[str(identifier)] = signal.fillna(False).astype(bool)
    flags.index.name = features.index.name
    return flags


def enumerate_transition_rules(contract: Mapping[str, Any]) -> list[TransitionRule]:
    rules: list[TransitionRule] = []
    for family, specification in contract["families"].items():
        vol = [str(value) for value in specification["volatility_transitions"]]
        price = [str(value) for value in specification["price_transitions"]]
        cross = [str(value) for value in specification["cross_transitions"]]
        required = bool(specification["cross_required"])
        for volatility_transition, price_transition in product(vol, price):
            if not required:
                rules.append(
                    TransitionRule(
                        str(family),
                        volatility_transition,
                        price_transition,
                        None,
                    )
                )
            for cross_transition in cross:
                rules.append(
                    TransitionRule(
                        str(family),
                        volatility_transition,
                        price_transition,
                        cross_transition,
                    )
                )
    identifiers = [rule.rule_id for rule in rules]
    if len(identifiers) != len(set(identifiers)):
        raise AssertionError("transition rule identifiers must be unique")
    return rules


def transition_rule_catalog(rules: Sequence[TransitionRule]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_family": rule.event_family,
                "rule_id": rule.rule_id,
                "motif_id": rule.motif_id,
                "condition_count": rule.condition_count,
                "volatility_transition": rule.volatility_transition,
                "price_transition": rule.price_transition,
                "cross_transition": rule.cross_transition or "",
            }
            for rule in rules
        ]
    ).sort_values(["event_family", "rule_id"])


def _recent_confirmation(flags: pd.Series, window: int) -> pd.Series:
    return (
        flags.astype(int).rolling(window, min_periods=1).max().gt(0).astype(bool)
    )


def transition_rule_mask(
    features: pd.DataFrame,
    flags: pd.DataFrame,
    rule: TransitionRule,
    contract: Mapping[str, Any],
) -> pd.Series:
    """Return only the first close on which all transitions are confirmed."""

    window = int(contract["transition_rules"]["confirmation_window_sessions"])
    components = [
        _recent_confirmation(flags[rule.volatility_transition], window),
        _recent_confirmation(flags[rule.price_transition], window),
    ]
    if rule.cross_transition is not None:
        components.append(
            _recent_confirmation(flags[rule.cross_transition], window)
        )
    confirmed = components[0].copy()
    for component in components[1:]:
        confirmed &= component
    latest_impulse = flags[rule.volatility_transition] | flags[rule.price_transition]
    if rule.cross_transition is not None:
        latest_impulse |= flags[rule.cross_transition]
    mask = confirmed & latest_impulse

    specification = contract["families"][rule.event_family]
    eligibility = str(specification["eligibility"])
    if eligibility == "extension_capped":
        mask &= features["qqq_distance_ma20"].le(
            float(
                contract["transition_rules"][
                    "repair_and_acceleration_extension_cap"
                ]
            )
        )
    elif eligibility == "voo_long_trend_positive":
        mask &= features["voo_distance_ma200"].ge(0.0)
    elif eligibility != "always":
        raise ValueError(f"unsupported transition eligibility: {eligibility}")
    return mask.fillna(False).astype(bool)


def _nonoverlap_locations(
    mask: pd.Series,
    *,
    holding_sessions: int,
    cooldown_sessions: int,
) -> list[int]:
    output: list[int] = []
    next_allowed = 0
    for location, active in enumerate(mask.to_numpy(dtype=bool)):
        if location < next_allowed or not active:
            continue
        if location + 1 + holding_sessions > len(mask):
            continue
        output.append(location)
        next_allowed = location + 1 + holding_sessions + cooldown_sessions
    return output


def _target_column(family: str, horizon: int) -> tuple[str, str]:
    if family == "defense":
        return f"forward_bil_{horizon}d", f"forward_qqq_{horizon}d"
    if family == "repair":
        return f"forward_qqq_{horizon}d", f"forward_bil_{horizon}d"
    if family == "tech_acceleration":
        return f"forward_tqqq_{horizon}d", f"forward_qqq_{horizon}d"
    if family == "broad_rotation":
        return f"forward_voo_{horizon}d", f"forward_qqq_{horizon}d"
    raise ValueError(f"unsupported transition family: {family}")


def events_for_transition_rule(
    features: pd.DataFrame,
    flags: pd.DataFrame,
    rule: TransitionRule,
    contract: Mapping[str, Any],
    *,
    fold: str,
    sample: str,
) -> pd.DataFrame:
    specification = contract["families"][rule.event_family]
    horizon = int(specification["holding_sessions"])
    candidate_column, reference_column = _target_column(
        rule.event_family, horizon
    )
    mask = transition_rule_mask(features, flags, rule, contract)
    mask &= features[candidate_column].notna() & features[reference_column].notna()
    locations = _nonoverlap_locations(
        mask,
        holding_sessions=horizon,
        cooldown_sessions=int(contract["transition_rules"]["cooldown_sessions"]),
    )
    rows: list[dict[str, Any]] = []
    for number, location in enumerate(locations, start=1):
        candidate_return = float(features.iloc[location][candidate_column])
        reference_return = float(features.iloc[location][reference_column])
        rows.append(
            {
                "fold": fold,
                "sample": sample,
                "event_family": rule.event_family,
                "rule_id": rule.rule_id,
                "motif_id": rule.motif_id,
                "event_id": f"{fold}_{rule.event_family}_{number:03d}",
                "signal_close_date": features.index[location],
                "execution_date": features.index[location + 1],
                "event_end_date": features.index[location + horizon],
                "holding_sessions": horizon,
                "candidate_return": candidate_return,
                "reference_return": reference_return,
                "target_excess_return": candidate_return - reference_return,
                "win": bool(candidate_return > reference_return),
                "signal_qqq_distance_ma20": float(
                    features.iloc[location]["qqq_distance_ma20"]
                ),
                "signal_rsi20": float(features.iloc[location]["qqq_rsi20"]),
                "signal_vol_percentile": float(
                    features.iloc[location]["vol_max_percentile_252"]
                ),
                "signal_vol_retreat": float(
                    features.iloc[location]["vol_min_retreat_20d"]
                ),
            }
        )
    return pd.DataFrame(rows)


def evaluate_transition_rule(
    features: pd.DataFrame,
    flags: pd.DataFrame,
    rule: TransitionRule,
    contract: Mapping[str, Any],
    *,
    fold: str,
) -> dict[str, Any]:
    specification = contract["families"][rule.event_family]
    horizon = int(specification["holding_sessions"])
    candidate_column, reference_column = _target_column(
        rule.event_family, horizon
    )
    baseline = (
        features[candidate_column] - features[reference_column]
    ).dropna()
    events = events_for_transition_rule(
        features, flags, rule, contract, fold=fold, sample="development"
    )
    event_values = (
        events["target_excess_return"] if not events.empty else pd.Series(dtype=float)
    )
    mask = transition_rule_mask(features, flags, rule, contract)
    base_win_rate = float(baseline.gt(0.0).mean()) if len(baseline) else np.nan
    event_win_rate = float(event_values.gt(0.0).mean()) if len(event_values) else np.nan
    lift = event_win_rate - base_win_rate if np.isfinite(event_win_rate) else np.nan
    mean_excess = float(event_values.mean()) if len(event_values) else np.nan
    median_excess = float(event_values.median()) if len(event_values) else np.nan
    score = (
        mean_excess + median_excess + 0.02 * lift
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
        "motif_id": rule.motif_id,
        "condition_count": rule.condition_count,
        "events": int(len(events)),
        "active_session_fraction": float(mask.mean()),
        "base_win_rate": base_win_rate,
        "event_win_rate": event_win_rate,
        "conditional_win_rate_lift": lift,
        "mean_excess_return": mean_excess,
        "median_excess_return": median_excess,
        "score": float(score),
        "pvalue": _one_sided_mean_pvalue(event_values, baseline),
    }


def select_transition_rules(
    features: pd.DataFrame,
    flags: pd.DataFrame,
    contract: Mapping[str, Any],
    *,
    fold: str,
) -> tuple[pd.DataFrame, dict[str, TransitionRule], pd.DataFrame]:
    rules = enumerate_transition_rules(contract)
    by_id = {rule.rule_id: rule for rule in rules}
    minimum_events = int(
        contract["transition_rules"]["minimum_development_events"]
    )
    maximum_active = float(
        contract["transition_rules"]["maximum_active_session_fraction"]
    )
    selected_count = int(
        contract["transition_rules"]["selected_rules_per_family"]
    )
    fdr_alpha = float(contract["transition_rules"]["fdr_alpha"])
    candidate_parts: list[pd.DataFrame] = []
    selected_rows: list[dict[str, Any]] = []
    champions: dict[str, TransitionRule] = {}
    for family in contract["families"]:
        family_rules = [rule for rule in rules if rule.event_family == family]
        metrics = pd.DataFrame(
            [
                evaluate_transition_rule(
                    features, flags, rule, contract, fold=fold
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
        candidate_parts.append(metrics)
        eligible = metrics.loc[metrics["meets_frequency_bounds"]].head(
            selected_count
        )
        for rank, row in enumerate(eligible.itertuples(index=False), start=1):
            executed = bool(rank == 1 and row.fdr_pass)
            selected_rows.append(
                {
                    "fold": fold,
                    "event_family": family,
                    "selection_rank": rank,
                    "rule_id": row.rule_id,
                    "motif_id": row.motif_id,
                    "development_events": int(row.events),
                    "development_score": float(row.score),
                    "development_pvalue": float(row.pvalue),
                    "development_qvalue": float(row.qvalue),
                    "fdr_pass": bool(row.fdr_pass),
                    "executed_in_outer_fold": executed,
                }
            )
            if executed:
                champions[family] = by_id[str(row.rule_id)]
    candidates = pd.concat(candidate_parts, ignore_index=True)
    return pd.DataFrame(selected_rows), champions, candidates


def selected_transition_events(
    features: pd.DataFrame,
    flags: pd.DataFrame,
    champions: Mapping[str, TransitionRule],
    contract: Mapping[str, Any],
    *,
    fold: str,
    sample: str,
) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for family, rule in champions.items():
        events = events_for_transition_rule(
            features, flags, rule, contract, fold=fold, sample=sample
        )
        if events.empty:
            continue
        events["action"] = str(contract["families"][family]["action"])
        parts.append(events)
    if not parts:
        return pd.DataFrame(
            columns=[
                "fold",
                "sample",
                "event_family",
                "rule_id",
                "motif_id",
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
    return pd.concat(parts, ignore_index=True).sort_values(
        ["execution_date", "event_family"]
    )


def _family_gate(
    events: pd.DataFrame,
    fold_metrics: pd.DataFrame,
    selected: pd.DataFrame,
    family: str,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    thresholds = contract["validation"]["event_quality"]
    family_events = events.loc[events["event_family"].eq(family)].copy()
    family_folds = fold_metrics.loc[
        fold_metrics["event_family"].eq(family)
        & fold_metrics["events"].gt(0)
    ].copy()
    executed = selected.loc[
        selected["event_family"].eq(family)
        & selected["executed_in_outer_fold"].astype(bool)
    ]
    if family_events.empty:
        return {
            "event_family": family,
            "events": 0,
            "macro_clusters": 0,
            "positive_outer_fold_rate": 0.0,
            "conditional_win_rate_lift": np.nan,
            "median_excess_return": np.nan,
            "largest_positive_cluster_share": 1.0,
            "largest_positive_event_share": 1.0,
            "excess_without_best_year": np.nan,
            "motif_recurrence_rate": 0.0,
            "passed": False,
        }
    clustered = _assign_macro_clusters(
        family_events,
        int(contract["transition_rules"]["macro_cluster_calendar_days"]),
    )
    positive_fold_rate = (
        float(family_folds["mean_excess_return"].gt(0.0).mean())
        if len(family_folds)
        else 0.0
    )
    lift = float(family_folds["conditional_win_rate_lift"].mean())
    median = float(family_events["target_excess_return"].median())
    positive_clusters = (
        clustered.groupby("macro_cluster_id")["target_excess_return"]
        .sum()
        .clip(lower=0.0)
    )
    total_cluster_positive = float(positive_clusters.sum())
    cluster_share = (
        float(positive_clusters.max() / total_cluster_positive)
        if total_cluster_positive > 0.0
        else 1.0
    )
    positive_events = family_events["target_excess_return"].clip(lower=0.0)
    total_event_positive = float(positive_events.sum())
    event_share = (
        float(positive_events.max() / total_event_positive)
        if total_event_positive > 0.0
        else 1.0
    )
    yearly = family_events.groupby(
        pd.to_datetime(family_events["signal_close_date"]).dt.year
    )["target_excess_return"].sum()
    without_best = (
        float(yearly.drop(index=yearly.idxmax()).sum()) if len(yearly) > 1 else np.nan
    )
    recurrence = (
        float(executed["motif_id"].value_counts().max() / len(contract["outer_folds"]))
        if len(executed)
        else 0.0
    )
    checks = {
        "macro_clusters": int(clustered["macro_cluster_id"].nunique())
        >= int(thresholds["minimum_macro_clusters"]),
        "positive_outer_fold_rate": positive_fold_rate
        >= float(thresholds["positive_outer_fold_rate_min"]),
        "conditional_win_rate_lift": lift
        >= float(thresholds["conditional_win_rate_lift_min"]),
        "median_excess_return": median
        > float(thresholds["median_excess_return_min"]),
        "cluster_concentration": cluster_share
        <= float(thresholds["largest_positive_cluster_share_max"]),
        "event_concentration": event_share
        <= float(thresholds["largest_positive_event_share_max"]),
        "without_best_year": np.isfinite(without_best) and without_best >= 0.0,
        "motif_recurrence": recurrence
        >= float(thresholds["recurrence_rate_min"]),
    }
    return {
        "event_family": family,
        "events": int(len(family_events)),
        "macro_clusters": int(clustered["macro_cluster_id"].nunique()),
        "positive_outer_fold_rate": positive_fold_rate,
        "conditional_win_rate_lift": lift,
        "median_excess_return": median,
        "largest_positive_cluster_share": cluster_share,
        "largest_positive_event_share": event_share,
        "excess_without_best_year": without_best,
        "motif_recurrence_rate": recurrence,
        "checks": checks,
        "passed": bool(all(checks.values())),
    }


def run_nested_transition_discovery(
    features: pd.DataFrame,
    contract: Mapping[str, Any],
) -> TransitionDiscoveryResult:
    flags = build_transition_flags(features, contract)
    candidate_parts: list[pd.DataFrame] = []
    selected_parts: list[pd.DataFrame] = []
    outer_parts: list[pd.DataFrame] = []
    fold_rows: list[dict[str, Any]] = []
    for fold_specification in contract["outer_folds"]:
        fold = str(fold_specification["fold"])
        development = _date_slice(
            features,
            str(fold_specification["train_start"]),
            str(fold_specification["train_end"]),
        )
        development_flags = flags.reindex(development.index)
        outer = _date_slice(
            features,
            str(fold_specification["test_start"]),
            str(fold_specification["test_end"]),
        )
        outer_flags = flags.reindex(outer.index)
        selected, champions, candidates = select_transition_rules(
            development,
            development_flags,
            contract,
            fold=fold,
        )
        candidate_parts.append(candidates)
        selected_parts.append(selected)
        events = selected_transition_events(
            outer,
            outer_flags,
            champions,
            contract,
            fold=fold,
            sample="outer",
        )
        if not events.empty:
            outer_parts.append(events)
        for family in contract["families"]:
            family_events = events.loc[events["event_family"].eq(family)]
            if family_events.empty:
                fold_rows.append(
                    {
                        "fold": fold,
                        "event_family": family,
                        "rule_id": champions[family].rule_id
                        if family in champions
                        else "none",
                        "motif_id": champions[family].motif_id
                        if family in champions
                        else "none",
                        "events": 0,
                        "base_win_rate": np.nan,
                        "event_win_rate": np.nan,
                        "conditional_win_rate_lift": np.nan,
                        "mean_excess_return": np.nan,
                        "median_excess_return": np.nan,
                    }
                )
                continue
            specification = contract["families"][family]
            horizon = int(specification["holding_sessions"])
            candidate_column, reference_column = _target_column(family, horizon)
            baseline = (outer[candidate_column] - outer[reference_column]).dropna()
            base_win_rate = float(baseline.gt(0.0).mean())
            event_win_rate = float(family_events["win"].mean())
            fold_rows.append(
                {
                    "fold": fold,
                    "event_family": family,
                    "rule_id": str(family_events["rule_id"].iloc[0]),
                    "motif_id": str(family_events["motif_id"].iloc[0]),
                    "events": int(len(family_events)),
                    "base_win_rate": base_win_rate,
                    "event_win_rate": event_win_rate,
                    "conditional_win_rate_lift": event_win_rate - base_win_rate,
                    "mean_excess_return": float(
                        family_events["target_excess_return"].mean()
                    ),
                    "median_excess_return": float(
                        family_events["target_excess_return"].median()
                    ),
                }
            )
    candidates = pd.concat(candidate_parts, ignore_index=True)
    selected = pd.concat(selected_parts, ignore_index=True)
    events = (
        pd.concat(outer_parts, ignore_index=True)
        if outer_parts
        else pd.DataFrame(
            columns=[
                "fold",
                "sample",
                "event_family",
                "rule_id",
                "motif_id",
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
        int(contract["transition_rules"]["macro_cluster_calendar_days"]),
    )
    folds = pd.DataFrame(fold_rows)
    gates = pd.DataFrame(
        [
            _family_gate(events, folds, selected, family, contract)
            for family in contract["families"]
        ]
    )
    rules = enumerate_transition_rules(contract)
    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "unique_rule_structures": int(len(rules)),
        "development_evaluations": int(len(candidates)),
        "outer_folds": int(len(contract["outer_folds"])),
        "outer_events": int(len(events)),
        "families_with_passing_event_gate": gates.loc[
            gates["passed"].astype(bool), "event_family"
        ].tolist(),
        "persistent_state_rules_used": False,
        "historical_success_authorizes_shadow_only": True,
        "baseline_and_alerts_unchanged": True,
    }
    return TransitionDiscoveryResult(
        features=features,
        transition_flags=flags,
        rule_catalog=transition_rule_catalog(rules),
        candidate_metrics=candidates,
        selected_rules=selected,
        outer_events=events,
        fold_metrics=folds,
        family_gates=gates,
        diagnostics=diagnostics,
    )
