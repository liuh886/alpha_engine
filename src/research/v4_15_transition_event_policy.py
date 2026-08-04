"""Fixed-action portfolio runtime for v4.15 fresh transition events."""

from __future__ import annotations

from typing import Any, Mapping

import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult, _normalise_bars
from src.research.v4_14_multifactor_event_policy import (
    FAMILIES,
    PolicyResult,
    _baseline_exact,
    _event_action_trace,
    _event_attribution,
    _portfolio_gate,
    _run_policy,
    _run_static,
)
from src.research.v4_15_transition_event_discovery import (
    TransitionDiscoveryResult,
    build_transition_flags,
    select_transition_rules,
    selected_transition_events,
)


def run_transition_event_policy(
    bars: Mapping[str, pd.DataFrame],
    proxy_baseline_daily: pd.DataFrame,
    actual_baseline_daily: pd.DataFrame,
    discovery: TransitionDiscoveryResult,
    contract: Mapping[str, Any],
) -> PolicyResult:
    """Run nested OOF transition policy, family ablations and actual feasibility."""

    oof_start = pd.Timestamp(contract["outer_folds"][0]["test_start"])
    oof_end = pd.Timestamp(contract["outer_folds"][-1]["test_end"])
    features = discovery.features
    proxy_index = proxy_baseline_daily.index[
        (proxy_baseline_daily.index >= oof_start)
        & (proxy_baseline_daily.index <= oof_end)
    ]
    proxy_index = proxy_index.intersection(features.index).sort_values()
    baseline_proxy = _baseline_exact(proxy_baseline_daily, proxy_index, contract)
    voo_proxy = features["voo_next_open_return"].reindex(proxy_index)
    cash_proxy = features["bil_next_open_return"].reindex(proxy_index)
    oof_trace = _event_action_trace(
        proxy_index, discovery.outer_events, contract
    )
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
    oof_attribution = _event_attribution(
        oof_results["full_event_policy"], baseline_proxy
    )
    portfolio_gate = _portfolio_gate(oof_results, oof_attribution, contract)

    actual_start = max(
        pd.Timestamp(contract["data"]["actual_product_start"]),
        actual_baseline_daily.index.min(),
    )
    actual_end = actual_baseline_daily.index.max()
    development = features.loc[pd.Timestamp("2011-01-03") : pd.Timestamp("2023-12-29")]
    all_flags = discovery.transition_flags
    development_flags = all_flags.reindex(development.index)
    actual_selected, champions, _ = select_transition_rules(
        development,
        development_flags,
        contract,
        fold="actual_2024_plus",
    )
    actual_features = features.loc[actual_start:actual_end].copy()
    actual_flags = all_flags.reindex(actual_features.index)
    actual_events = selected_transition_events(
        actual_features,
        actual_flags,
        champions,
        contract,
        fold="actual_2024_plus",
        sample="actual_feasibility",
    )

    qqqi = _normalise_bars(bars["QQQI"], "QQQI")
    sgov = _normalise_bars(bars["SGOV"], "SGOV")
    voo = _normalise_bars(bars["VOO"], "VOO")
    actual_index = actual_baseline_daily.index[
        (actual_baseline_daily.index >= actual_start)
        & (actual_baseline_daily.index <= actual_end)
    ]
    actual_index = (
        actual_index.intersection(qqqi.index)
        .intersection(sgov.index)
        .intersection(voo.index)
        .sort_values()
    )
    voo_return = voo["open"].shift(-1).div(voo["open"]).sub(1.0).reindex(actual_index)
    cash_return = (
        sgov["open"].shift(-1).div(sgov["open"]).sub(1.0).reindex(actual_index)
    )
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
    actual_attribution = _event_attribution(
        actual_results["full_event_policy"], baseline_actual
    )
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
            portfolio_gate["passed"]
            and bool(discovery.family_gates["passed"].astype(bool).any())
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
