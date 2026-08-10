"""Fixed-action portfolio runtime for v4.14 multi-factor market events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult, _normalise_bars, _return_metrics
from src.research.v4_14_multifactor_event_discovery import (
    DiscoveryResult,
    EventRule,
    _benjamini_hochberg,
    _date_slice,
    enumerate_rules,
    evaluate_rule_development,
    events_for_rule,
)

BASELINE_KEY = "rotation_vxn_bridge_v4_2_50_50"
BASE_ASSETS = ("QQQI", "QQQ", "TQQQ")
POLICY_ASSETS = ("QQQI", "QQQ", "TQQQ", "VOO", "cash")
FAMILIES = ("defense", "broad_rotation", "repair", "tech_acceleration")


@dataclass(frozen=True)
class PolicyResult:
    """Portfolio evidence derived from nested OOF events and actual feasibility."""

    oof_results: dict[str, StrategyResult]
    actual_results: dict[str, StrategyResult]
    oof_headline: pd.DataFrame
    actual_headline: pd.DataFrame
    oof_action_trace: pd.DataFrame
    actual_action_trace: pd.DataFrame
    oof_attribution: pd.DataFrame
    actual_attribution: pd.DataFrame
    actual_selected_rules: pd.DataFrame
    portfolio_gate: dict[str, Any]
    diagnostics: dict[str, Any]


def select_rules_on_development(
    features: pd.DataFrame,
    contract: Mapping[str, Any],
    *,
    fold: str,
) -> tuple[pd.DataFrame, dict[str, EventRule]]:
    """Select one FDR-passing champion per family on one frozen development set."""

    rules = enumerate_rules(contract)
    rules_by_id = {rule.rule_id: rule for rule in rules}
    minimum_events = int(contract["rule_grammar"]["minimum_development_events"])
    maximum_active = float(contract["rule_grammar"]["maximum_active_session_fraction"])
    selected_count = int(contract["rule_grammar"]["selected_rules_per_family"])
    fdr_alpha = float(contract["rule_grammar"]["fdr_alpha"])
    selected_rows: list[dict[str, Any]] = []
    champions: dict[str, EventRule] = {}
    for family in contract["families"]:
        family_rules = [rule for rule in rules if rule.event_family == family]
        metrics = pd.DataFrame(
            [
                evaluate_rule_development(features, rule, contract, fold=fold)
                for rule in family_rules
            ]
        )
        metrics["qvalue"] = _benjamini_hochberg(metrics["pvalue"])
        metrics["meets_frequency_bounds"] = metrics["events"].ge(minimum_events) & metrics[
            "active_session_fraction"
        ].le(maximum_active)
        metrics["fdr_pass"] = metrics["qvalue"].le(fdr_alpha)
        metrics = metrics.sort_values(
            ["meets_frequency_bounds", "fdr_pass", "score", "rule_id"],
            ascending=[False, False, False, True],
        ).reset_index(drop=True)
        eligible = metrics.loc[metrics["meets_frequency_bounds"]].head(selected_count)
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
                    "development_qvalue": float(row.qvalue),
                    "fdr_pass": bool(row.fdr_pass),
                    "executed": executed,
                }
            )
            if executed:
                champions[family] = rules_by_id[str(row.rule_id)]
    return pd.DataFrame(selected_rows), champions


def selected_rule_events(
    features: pd.DataFrame,
    champions: Mapping[str, EventRule],
    contract: Mapping[str, Any],
    *,
    fold: str,
    sample: str,
) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for family, rule in champions.items():
        events = events_for_rule(
            features,
            rule,
            contract,
            fold=fold,
            sample=sample,
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
                "event_id",
                "signal_close_date",
                "execution_date",
                "event_end_date",
                "holding_sessions",
                "action",
            ]
        )
    return pd.concat(parts, ignore_index=True).sort_values(["execution_date", "event_family"])


def _event_action_trace(
    index: pd.DatetimeIndex,
    events: pd.DataFrame,
    contract: Mapping[str, Any],
    *,
    include_families: Sequence[str] | None = None,
) -> pd.DataFrame:
    priority = [str(value) for value in contract["action_lattice"]["priority"]]
    allowed = set(include_families or priority)
    trace = pd.DataFrame(index=index)
    trace["event_family"] = "baseline"
    trace["action"] = "BASELINE_V4_2"
    trace["event_id"] = ""
    trace["rule_id"] = ""
    if events.empty:
        return trace
    event_rows = events.copy()
    event_rows["execution_date"] = pd.to_datetime(event_rows["execution_date"])
    event_rows["event_end_date"] = pd.to_datetime(event_rows["event_end_date"])
    for family in reversed(priority):
        if family not in allowed:
            continue
        family_events = event_rows.loc[event_rows["event_family"].eq(family)]
        for event in family_events.itertuples(index=False):
            active = (trace.index >= pd.Timestamp(event.execution_date)) & (
                trace.index <= pd.Timestamp(event.event_end_date)
            )
            trace.loc[active, "event_family"] = family
            trace.loc[active, "action"] = str(event.action)
            trace.loc[active, "event_id"] = str(event.event_id)
            trace.loc[active, "rule_id"] = str(event.rule_id)
    return trace


def _action_weights(
    baseline_daily: pd.DataFrame,
    trace: pd.DataFrame,
    *,
    proxy_mode: bool,
) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=baseline_daily.index, columns=list(POLICY_ASSETS))
    for asset in BASE_ASSETS:
        weights[asset] = baseline_daily[f"weight_{asset}"].astype(float)
    for action in trace["action"].unique():
        mask = trace["action"].eq(action)
        if action == "BASELINE_V4_2":
            continue
        weights.loc[mask, :] = 0.0
        if action == "SGOV_DEFENSE":
            weights.loc[mask, "cash"] = 1.0
        elif action == "BROAD_EQUITY":
            weights.loc[mask, "VOO"] = 1.0
        elif action == "NASDAQ_INCOME":
            weights.loc[mask, "QQQ" if proxy_mode else "QQQI"] = 1.0
        elif action == "NASDAQ_CORE":
            weights.loc[mask, "QQQ"] = 1.0
        elif action == "NASDAQ_ACCELERATE":
            weights.loc[mask, "QQQ"] = 0.25
            weights.loc[mask, "TQQQ"] = 0.75
        elif action == "NASDAQ_MAX_ACCELERATE":
            weights.loc[mask, "TQQQ"] = 1.0
        elif action == "BROAD_DEFENSE":
            weights.loc[mask, "cash"] = 0.50
            weights.loc[mask, "VOO"] = 0.50
        else:
            raise ValueError(f"unknown action: {action}")
    if not np.allclose(weights.sum(axis=1), 1.0):
        raise AssertionError("multi-factor policy weights must sum to one")
    if (weights < -1e-12).any().any() or (weights > 1.0 + 1e-12).any().any():
        raise AssertionError("multi-factor policy weights must remain in [0,1]")
    return weights


def _run_policy(
    baseline_daily: pd.DataFrame,
    voo_return: pd.Series,
    cash_return: pd.Series,
    trace: pd.DataFrame,
    contract: Mapping[str, Any],
    *,
    name: str,
    proxy_mode: bool,
) -> StrategyResult:
    daily = baseline_daily.copy()
    daily["VOO_next_open_return"] = voo_return.reindex(daily.index)
    daily["cash_next_open_return"] = cash_return.reindex(daily.index)
    daily = daily.join(trace)
    required = [
        *[f"{asset}_next_open_return" for asset in BASE_ASSETS],
        "VOO_next_open_return",
        "cash_next_open_return",
    ]
    daily = daily.dropna(subset=required).copy()
    weights = _action_weights(daily, daily[["action"]], proxy_mode=proxy_mode)
    daily["weight_QQQI"] = weights["QQQI"]
    daily["weight_QQQ"] = weights["QQQ"]
    daily["weight_TQQQ"] = weights["TQQQ"]
    daily["weight_VOO"] = weights["VOO"]
    daily["weight_cash"] = weights["cash"]
    daily["gross_return"] = (
        daily["weight_QQQI"] * daily["QQQI_next_open_return"]
        + daily["weight_QQQ"] * daily["QQQ_next_open_return"]
        + daily["weight_TQQQ"] * daily["TQQQ_next_open_return"]
        + daily["weight_VOO"] * daily["VOO_next_open_return"]
        + daily["weight_cash"] * daily["cash_next_open_return"]
    )
    turnover = weights.diff().abs().sum(axis=1)
    if len(turnover):
        turnover.iloc[0] = float(weights.iloc[0].abs().sum())
    cost_bps = float(contract["boundaries"]["transaction_cost_bps_per_turnover_unit"])
    daily["turnover_units"] = turnover
    daily["transaction_cost"] = turnover * cost_bps / 10_000.0
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    changed = weights.ne(weights.shift()).any(axis=1)
    metrics = _return_metrics(
        daily["net_return"],
        annual_risk_free_rate=float(contract["boundaries"]["annual_risk_free_rate"]),
    )
    metrics.update(
        {
            "strategy": name,
            "turnover_units": float(daily["turnover_units"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "switch_count": int(max(int(changed.sum()) - 1, 0)),
            "event_sessions": int(daily["event_family"].ne("baseline").sum()),
            "event_session_rate": float(daily["event_family"].ne("baseline").mean()),
        }
    )
    trades = daily.loc[
        changed,
        [
            "event_family",
            "action",
            "event_id",
            "rule_id",
            "weight_QQQI",
            "weight_QQQ",
            "weight_TQQQ",
            "weight_VOO",
            "weight_cash",
            "turnover_units",
            "transaction_cost",
        ],
    ].reset_index(names="date")
    return StrategyResult(name, daily, trades, metrics)


def _run_static(
    baseline_daily: pd.DataFrame,
    voo_return: pd.Series,
    cash_return: pd.Series,
    contract: Mapping[str, Any],
    *,
    name: str,
    weights: Mapping[str, float],
) -> StrategyResult:
    trace = pd.DataFrame(index=baseline_daily.index)
    trace["event_family"] = "static"
    trace["event_id"] = "static"
    trace["rule_id"] = "static"
    if weights == {"QQQ": 1.0}:
        trace["action"] = "NASDAQ_CORE"
    elif weights == {"VOO": 1.0}:
        trace["action"] = "BROAD_EQUITY"
    elif weights == {"QQQ": 0.25, "TQQQ": 0.75}:
        trace["action"] = "NASDAQ_ACCELERATE"
    else:
        daily = baseline_daily.copy()
        daily["VOO_next_open_return"] = voo_return.reindex(daily.index)
        daily["cash_next_open_return"] = cash_return.reindex(daily.index)
        daily = daily.dropna(
            subset=[
                "QQQ_next_open_return",
                "TQQQ_next_open_return",
                "VOO_next_open_return",
                "cash_next_open_return",
            ]
        ).copy()
        matrix = pd.DataFrame(0.0, index=daily.index, columns=list(POLICY_ASSETS))
        for asset, weight in weights.items():
            matrix[asset] = float(weight)
        daily["gross_return"] = (
            matrix["QQQ"] * daily["QQQ_next_open_return"]
            + matrix["TQQQ"] * daily["TQQQ_next_open_return"]
            + matrix["VOO"] * daily["VOO_next_open_return"]
            + matrix["cash"] * daily["cash_next_open_return"]
        )
        turnover = matrix.diff().abs().sum(axis=1)
        turnover.iloc[0] = float(matrix.iloc[0].abs().sum())
        daily["turnover_units"] = turnover
        daily["transaction_cost"] = (
            turnover
            * float(contract["boundaries"]["transaction_cost_bps_per_turnover_unit"])
            / 10_000.0
        )
        daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
        daily["equity"] = (1.0 + daily["net_return"]).cumprod()
        daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
        metrics = _return_metrics(daily["net_return"])
        metrics.update(
            {
                "strategy": name,
                "turnover_units": float(turnover.sum()),
                "transaction_cost_paid": float(daily["transaction_cost"].sum()),
                "switch_count": 0,
                "event_sessions": 0,
                "event_session_rate": 0.0,
            }
        )
        return StrategyResult(name, daily, pd.DataFrame(), metrics)
    return _run_policy(
        baseline_daily,
        voo_return,
        cash_return,
        trace,
        contract,
        name=name,
        proxy_mode=True,
    )


def _baseline_exact(
    baseline_daily: pd.DataFrame,
    index: pd.DatetimeIndex,
    contract: Mapping[str, Any],
) -> StrategyResult:
    daily = baseline_daily.reindex(index).copy()
    weights = daily[[f"weight_{asset}" for asset in BASE_ASSETS]].rename(
        columns={f"weight_{asset}": asset for asset in BASE_ASSETS}
    )
    daily["gross_return"] = sum(
        weights[asset] * daily[f"{asset}_next_open_return"] for asset in BASE_ASSETS
    )
    turnover = weights.diff().abs().sum(axis=1)
    turnover.iloc[0] = float(weights.iloc[0].abs().sum())
    daily["turnover_units"] = turnover
    daily["transaction_cost"] = (
        turnover
        * float(contract["boundaries"]["transaction_cost_bps_per_turnover_unit"])
        / 10_000.0
    )
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    metrics = _return_metrics(daily["net_return"])
    metrics.update(
        {
            "strategy": "frozen_v4_2",
            "turnover_units": float(turnover.sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "switch_count": int(max(int(weights.ne(weights.shift()).any(axis=1).sum()) - 1, 0)),
            "event_sessions": 0,
            "event_session_rate": 0.0,
        }
    )
    return StrategyResult("frozen_v4_2", daily, pd.DataFrame(), metrics)


def _event_attribution(
    candidate: StrategyResult,
    baseline: StrategyResult,
) -> pd.DataFrame:
    daily = candidate.daily.join(
        baseline.daily["net_return"].rename("baseline_net_return"), how="inner"
    )
    active = daily["event_family"].ne("baseline")
    rows: list[dict[str, Any]] = []
    for event_id, window in daily.loc[active].groupby("event_id"):
        if not event_id:
            continue
        candidate_log = float(np.log1p(window["net_return"]).sum())
        baseline_log = float(np.log1p(window["baseline_net_return"]).sum())
        rows.append(
            {
                "event_id": event_id,
                "event_family": str(window["event_family"].iloc[0]),
                "action": str(window["action"].iloc[0]),
                "start_date": window.index.min(),
                "end_date": window.index.max(),
                "sessions": int(len(window)),
                "candidate_return": float(np.exp(candidate_log) - 1.0),
                "baseline_return": float(np.exp(baseline_log) - 1.0),
                "relative_return": float(np.exp(candidate_log - baseline_log) - 1.0),
            }
        )
    return pd.DataFrame(rows)


def _portfolio_gate(
    results: Mapping[str, StrategyResult],
    attribution: pd.DataFrame,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    thresholds = contract["validation"]["portfolio_shadow_gate"]
    baseline = results["frozen_v4_2"]
    policy = results["full_event_policy"]
    cagr_delta_pp = (float(policy.metrics["cagr"]) - float(baseline.metrics["cagr"])) * 100.0
    drawdown_worsening_pp = max(
        0.0,
        (float(baseline.metrics["max_drawdown"]) - float(policy.metrics["max_drawdown"])) * 100.0,
    )
    calmar_delta = float(policy.metrics["calmar"]) - float(baseline.metrics["calmar"])
    aligned = pd.concat(
        [
            policy.daily["net_return"].rename("policy"),
            baseline.daily["net_return"].rename("baseline"),
        ],
        axis=1,
    ).dropna()
    year_relative: dict[str, float] = {}
    for year, group in aligned.groupby(aligned.index.year):
        year_relative[str(int(year))] = float(
            (1.0 + group["policy"]).prod() - (1.0 + group["baseline"]).prod()
        )
    positive_year_rate = (
        float(np.mean([value > 0.0 for value in year_relative.values()])) if year_relative else 0.0
    )
    positive = attribution.loc[attribution["relative_return"].gt(0.0)].copy()
    total_positive = float(positive["relative_return"].sum()) if len(positive) else 0.0
    largest_event_share = (
        float(positive["relative_return"].max() / total_positive) if total_positive > 0.0 else 1.0
    )
    family_positive = positive.groupby("event_family")["relative_return"].sum()
    largest_family_share = (
        float(family_positive.max() / total_positive) if total_positive > 0.0 else 1.0
    )
    turnover_increase = (
        float(policy.metrics["turnover_units"]) / float(baseline.metrics["turnover_units"]) - 1.0
    )
    ablation_wins: dict[str, int] = {}
    for family in FAMILIES:
        key = f"ablation_{family}"
        comparator = results[key]
        comparisons = [
            float(policy.metrics["cagr"]) > float(comparator.metrics["cagr"]),
            float(policy.metrics["max_drawdown"]) > float(comparator.metrics["max_drawdown"]),
            float(policy.metrics["sortino"]) > float(comparator.metrics["sortino"]),
            float(policy.metrics["calmar"]) > float(comparator.metrics["calmar"]),
        ]
        ablation_wins[family] = int(sum(comparisons))
    checks = {
        "cagr": cagr_delta_pp >= float(thresholds["cagr_improvement_vs_v4_2_pp_min"]),
        "max_drawdown": drawdown_worsening_pp <= float(thresholds["max_drawdown_worsening_pp_max"]),
        "calmar": calmar_delta >= float(thresholds["calmar_improvement_vs_v4_2_min"]),
        "sortino": float(policy.metrics["sortino"]) >= float(baseline.metrics["sortino"]),
        "positive_years": positive_year_rate
        >= float(thresholds["positive_calendar_year_rate_min"]),
        "family_concentration": largest_family_share
        <= float(thresholds["largest_family_positive_share_max"]),
        "event_concentration": largest_event_share
        <= float(thresholds["largest_event_positive_share_max"]),
        "turnover": turnover_increase <= float(thresholds["turnover_increase_max"]),
        **{f"beats_{family}_ablation": wins >= 2 for family, wins in ablation_wins.items()},
    }
    return {
        "checks": checks,
        "metrics": {
            "cagr_delta_pp": cagr_delta_pp,
            "max_drawdown_worsening_pp": drawdown_worsening_pp,
            "calmar_delta": calmar_delta,
            "positive_calendar_year_rate": positive_year_rate,
            "calendar_year_relative_returns": year_relative,
            "largest_family_positive_share": largest_family_share,
            "largest_event_positive_share": largest_event_share,
            "turnover_increase": turnover_increase,
            "ablation_win_counts": ablation_wins,
        },
        "passed": bool(all(checks.values())),
    }


def run_multifactor_event_policy(
    bars: Mapping[str, pd.DataFrame],
    proxy_baseline_daily: pd.DataFrame,
    actual_baseline_daily: pd.DataFrame,
    discovery: DiscoveryResult,
    contract: Mapping[str, Any],
) -> PolicyResult:
    """Run nested OOF policy, family ablations and 2024-plus feasibility."""

    oof_start = pd.Timestamp(contract["outer_folds"][0]["test_start"])
    oof_end = pd.Timestamp(contract["outer_folds"][-1]["test_end"])
    proxy_index = proxy_baseline_daily.index[
        (proxy_baseline_daily.index >= oof_start) & (proxy_baseline_daily.index <= oof_end)
    ]
    features = discovery.features
    proxy_index = proxy_index.intersection(features.index).sort_values()
    baseline_proxy = _baseline_exact(proxy_baseline_daily, proxy_index, contract)
    voo_proxy = features["voo_next_open_return"].reindex(proxy_index)
    cash_proxy = features["bil_next_open_return"].reindex(proxy_index)
    oof_trace = _event_action_trace(proxy_index, discovery.outer_events, contract)
    oof_results: dict[str, StrategyResult] = {
        "frozen_v4_2": baseline_proxy,
        "full_event_policy": _run_policy(
            proxy_baseline_daily.reindex(proxy_index),
            voo_proxy,
            cash_proxy,
            oof_trace,
            contract,
            name="full_event_policy",
            proxy_mode=True,
        ),
    }
    for family in FAMILIES:
        trace = _event_action_trace(
            proxy_index,
            discovery.outer_events,
            contract,
            include_families=[family],
        )
        oof_results[f"ablation_{family}"] = _run_policy(
            proxy_baseline_daily.reindex(proxy_index),
            voo_proxy,
            cash_proxy,
            trace,
            contract,
            name=f"ablation_{family}",
            proxy_mode=True,
        )
    oof_results["buy_hold_QQQ"] = _run_static(
        proxy_baseline_daily.reindex(proxy_index),
        voo_proxy,
        cash_proxy,
        contract,
        name="buy_hold_QQQ",
        weights={"QQQ": 1.0},
    )
    oof_results["buy_hold_VOO"] = _run_static(
        proxy_baseline_daily.reindex(proxy_index),
        voo_proxy,
        cash_proxy,
        contract,
        name="buy_hold_VOO",
        weights={"VOO": 1.0},
    )
    oof_results["static_QQQ_VOO_50_50"] = _run_static(
        proxy_baseline_daily.reindex(proxy_index),
        voo_proxy,
        cash_proxy,
        contract,
        name="static_QQQ_VOO_50_50",
        weights={"QQQ": 0.50, "VOO": 0.50},
    )
    oof_results["static_QQQ_TQQQ_25_75"] = _run_static(
        proxy_baseline_daily.reindex(proxy_index),
        voo_proxy,
        cash_proxy,
        contract,
        name="static_QQQ_TQQQ_25_75",
        weights={"QQQ": 0.25, "TQQQ": 0.75},
    )
    oof_attribution = _event_attribution(oof_results["full_event_policy"], baseline_proxy)
    portfolio_gate = _portfolio_gate(oof_results, oof_attribution, contract)

    actual_start = max(
        pd.Timestamp(contract["data"]["actual_product_start"]),
        actual_baseline_daily.index.min(),
    )
    actual_end = actual_baseline_daily.index.max()
    development = _date_slice(features, "2011-01-03", "2023-12-29")
    actual_selected, champions = select_rules_on_development(
        development, contract, fold="actual_2024_plus"
    )
    actual_features = features.loc[actual_start:actual_end].copy()
    actual_events = selected_rule_events(
        actual_features,
        champions,
        contract,
        fold="actual_2024_plus",
        sample="actual_feasibility",
    )
    qqqi = _normalise_bars(bars["QQQI"], "QQQI")
    sgov = _normalise_bars(bars["SGOV"], "SGOV")
    voo = _normalise_bars(bars["VOO"], "VOO")
    actual_index = actual_baseline_daily.index[
        (actual_baseline_daily.index >= actual_start) & (actual_baseline_daily.index <= actual_end)
    ]
    actual_index = (
        actual_index.intersection(qqqi.index)
        .intersection(sgov.index)
        .intersection(voo.index)
        .sort_values()
    )
    voo_return = voo["open"].shift(-1).div(voo["open"]).sub(1.0).reindex(actual_index)
    cash_return = sgov["open"].shift(-1).div(sgov["open"]).sub(1.0).reindex(actual_index)
    baseline_actual = _baseline_exact(actual_baseline_daily, actual_index, contract)
    actual_trace = _event_action_trace(actual_index, actual_events, contract)
    actual_results: dict[str, StrategyResult] = {
        "frozen_v4_2": baseline_actual,
        "full_event_policy": _run_policy(
            actual_baseline_daily.reindex(actual_index),
            voo_return,
            cash_return,
            actual_trace,
            contract,
            name="full_event_policy",
            proxy_mode=False,
        ),
    }
    for family in FAMILIES:
        trace = _event_action_trace(
            actual_index,
            actual_events,
            contract,
            include_families=[family],
        )
        actual_results[f"ablation_{family}"] = _run_policy(
            actual_baseline_daily.reindex(actual_index),
            voo_return,
            cash_return,
            trace,
            contract,
            name=f"ablation_{family}",
            proxy_mode=False,
        )
    actual_attribution = _event_attribution(actual_results["full_event_policy"], baseline_actual)
    oof_headline = pd.DataFrame(
        [dict(result.metrics) for result in oof_results.values()]
    ).set_index("strategy")
    actual_headline = pd.DataFrame(
        [dict(result.metrics) for result in actual_results.values()]
    ).set_index("strategy")
    diagnostics = {
        "research_only": True,
        "trade_ready": False,
        "oof_start": proxy_index.min(),
        "oof_end": proxy_index.max(),
        "oof_observations": int(len(proxy_index)),
        "actual_start": actual_index.min(),
        "actual_end": actual_index.max(),
        "actual_observations": int(len(actual_index)),
        "actual_selected_families": sorted(champions),
        "actual_events": int(len(actual_events)),
        "portfolio_gate": portfolio_gate,
        "shadow_candidate_authorized": bool(
            portfolio_gate["passed"] and bool(discovery.family_gates["passed"].astype(bool).any())
        ),
        "direct_promotion_authorized": False,
        "baseline_and_alerts_unchanged": True,
    }
    return PolicyResult(
        oof_results=oof_results,
        actual_results=actual_results,
        oof_headline=oof_headline,
        actual_headline=actual_headline,
        oof_action_trace=oof_trace,
        actual_action_trace=actual_trace,
        oof_attribution=oof_attribution,
        actual_attribution=actual_attribution,
        actual_selected_rules=actual_selected,
        portfolio_gate=portfolio_gate,
        diagnostics=diagnostics,
    )
