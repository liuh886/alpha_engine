"""State-2 tail-event and execution-robustness diagnostics for v4.2.

The module is diagnostic only. It preserves the frozen v4.2 close-decision trace,
portfolio mapping and 10 bps official transaction-cost convention. Alternative
execution scenarios are stress tests, not candidate strategies.
"""

from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.research.etf_rotation_experiment import StrategyResult, _return_metrics
from src.research.vxn_bridge_allocation_experiment import (
    ASSETS,
    bridge_weights_for_states,
)


def _path_statistics(returns: pd.Series) -> dict[str, float | int]:
    clean = pd.to_numeric(returns, errors="coerce").dropna().astype(float)
    if clean.empty:
        return {
            "sessions": 0,
            "cumulative_return": 0.0,
            "max_drawdown": 0.0,
            "maximum_favourable_excursion": 0.0,
            "maximum_adverse_excursion": 0.0,
        }
    equity = (1.0 + clean).cumprod()
    anchored = pd.concat(
        [pd.Series([1.0]), equity.reset_index(drop=True)], ignore_index=True
    )
    drawdown = anchored / anchored.cummax() - 1.0
    return {
        "sessions": int(len(clean)),
        "cumulative_return": float(equity.iloc[-1] - 1.0),
        "max_drawdown": float(drawdown.min()),
        "maximum_favourable_excursion": float(anchored.max() - 1.0),
        "maximum_adverse_excursion": float(anchored.min() - 1.0),
    }


def open_to_open_contribution_decomposition(
    daily: pd.DataFrame,
) -> pd.DataFrame:
    """Split weighted open-to-open gross return into intraday and overnight parts.

    For each asset:
      total = close/open - 1 + (close/open) * (next_open/close - 1)

    Weighting those two additive contributions reproduces the portfolio's
    weighted open-to-open gross return without assuming intraday rebalancing.
    """

    out = pd.DataFrame(index=daily.index)
    intraday_total = pd.Series(0.0, index=daily.index)
    overnight_total = pd.Series(0.0, index=daily.index)
    for asset in ASSETS:
        required = {
            f"weight_{asset}",
            f"{asset}_open",
            f"{asset}_close",
            f"{asset}_next_open_return",
        }
        missing = sorted(required - set(daily.columns))
        if missing:
            raise ValueError(f"daily frame missing {asset} decomposition columns: {missing}")
        weight = pd.to_numeric(daily[f"weight_{asset}"], errors="coerce").fillna(0.0)
        open_price = pd.to_numeric(daily[f"{asset}_open"], errors="coerce")
        close_price = pd.to_numeric(daily[f"{asset}_close"], errors="coerce")
        total_return = pd.to_numeric(
            daily[f"{asset}_next_open_return"], errors="coerce"
        )
        intraday = close_price / open_price - 1.0
        next_open = open_price * (1.0 + total_return)
        overnight = next_open / close_price - 1.0
        intraday_contribution = weight * intraday
        overnight_contribution = weight * (1.0 + intraday) * overnight
        out[f"{asset}_intraday_contribution"] = intraday_contribution
        out[f"{asset}_overnight_contribution"] = overnight_contribution
        intraday_total = intraday_total.add(intraday_contribution, fill_value=0.0)
        overnight_total = overnight_total.add(overnight_contribution, fill_value=0.0)
    out["intraday_contribution"] = intraday_total
    out["overnight_contribution"] = overnight_total
    out["reconstructed_gross_return"] = intraday_total + overnight_total
    if "gross_return" in daily.columns:
        difference = (
            out["reconstructed_gross_return"]
            - pd.to_numeric(daily["gross_return"], errors="coerce")
        ).abs()
        if difference.dropna().gt(1e-8).any():
            raise AssertionError("intraday/overnight decomposition does not tie to gross return")
    return out


def _warning_flags(daily: pd.DataFrame) -> pd.DataFrame:
    flags = pd.DataFrame(index=daily.index)
    qqq_below_ma20 = (
        pd.to_numeric(daily.get("QQQ_close"), errors="coerce")
        < pd.to_numeric(daily.get("ma_short"), errors="coerce")
    ).fillna(False)
    flags["vix_stress"] = daily.get(
        "vix_stress", pd.Series(False, index=daily.index)
    ).fillna(False).astype(bool)
    flags["vxn_stress"] = daily.get(
        "vxn_stress", pd.Series(False, index=daily.index)
    ).fillna(False).astype(bool)
    flags["below_ma_short_n"] = daily.get(
        "below_ma_short_n", pd.Series(False, index=daily.index)
    ).fillna(False).astype(bool)
    flags["qqq_below_ma20"] = qqq_below_ma20
    flags["any_warning"] = flags.any(axis=1)
    return flags


def state_two_episode_attribution(
    result: StrategyResult,
    *,
    top_n: int = 10,
    abrupt_overnight_share: float = 0.60,
    abrupt_worst_day_share: float = 0.50,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Describe every contiguous state-2 holding interval and its tail mechanics."""

    daily = result.daily.copy()
    if "position_state" not in daily.columns:
        raise ValueError("strategy result has no position_state")
    decomposition = open_to_open_contribution_decomposition(daily)
    warnings = _warning_flags(daily)
    frame = daily.join(decomposition).join(
        warnings.add_prefix("warning_"), how="left"
    )
    states = frame["position_state"].astype(int)
    starts = states.eq(2) & states.shift(1).ne(2)
    rows: list[dict[str, Any]] = []

    for episode_id, start_date in enumerate(states.index[starts], start=1):
        start_location = states.index.get_loc(start_date)
        end_location = start_location
        while end_location + 1 < len(states) and int(states.iloc[end_location + 1]) == 2:
            end_location += 1
        end_date = states.index[end_location]
        interval = frame.loc[start_date:end_date].copy()
        gross = _path_statistics(interval["gross_return"])
        net = _path_statistics(interval["net_return"])
        net_equity = (1.0 + interval["net_return"].astype(float)).cumprod()
        trough_date = net_equity.idxmin()
        worst_date = interval["net_return"].astype(float).idxmin()

        intraday_loss = float(
            -interval["intraday_contribution"].clip(upper=0.0).sum()
        )
        overnight_loss = float(
            -interval["overnight_contribution"].clip(upper=0.0).sum()
        )
        decomposed_loss = intraday_loss + overnight_loss
        overnight_loss_share = (
            overnight_loss / decomposed_loss if decomposed_loss > 1e-12 else 0.0
        )
        mae = abs(float(net["maximum_adverse_excursion"]))
        worst_day_share = (
            min(abs(float(interval.loc[worst_date, "net_return"])) / mae, 1.0)
            if mae > 1e-12
            else 0.0
        )
        prior_location = states.index.get_loc(worst_date) - 1
        prior_warning = (
            bool(warnings.iloc[prior_location]["any_warning"])
            if prior_location >= 0
            else False
        )
        same_close_exit = int(interval.loc[worst_date, "decision_state"]) < 2
        mechanism = (
            "abrupt_or_gap_dominated"
            if overnight_loss_share >= abrupt_overnight_share
            or worst_day_share >= abrupt_worst_day_share
            else "gradual_or_distributed"
        )
        rows.append(
            {
                "episode_id": episode_id,
                "start_date": start_date,
                "end_date": end_date,
                "sessions": int(len(interval)),
                "entry_reason": str(interval.iloc[0]["executed_reason"]),
                "exit_decision_date": (
                    end_date
                    if int(interval.iloc[-1]["decision_state"]) < 2
                    else pd.NaT
                ),
                "exit_decision_reason": (
                    str(interval.iloc[-1]["decision_reason"])
                    if int(interval.iloc[-1]["decision_state"]) < 2
                    else None
                ),
                "gross_return": gross["cumulative_return"],
                "net_return": net["cumulative_return"],
                "max_drawdown": net["max_drawdown"],
                "mfe": net["maximum_favourable_excursion"],
                "mae": net["maximum_adverse_excursion"],
                "trough_date": trough_date,
                "sessions_to_trough": int(
                    interval.index.get_loc(trough_date)
                ),
                "worst_date": worst_date,
                "worst_daily_net_return": float(
                    interval.loc[worst_date, "net_return"]
                ),
                "worst_day_intraday_contribution": float(
                    interval.loc[worst_date, "intraday_contribution"]
                ),
                "worst_day_overnight_contribution": float(
                    interval.loc[worst_date, "overnight_contribution"]
                ),
                "intraday_loss_contribution": intraday_loss,
                "overnight_loss_contribution": overnight_loss,
                "overnight_loss_share": overnight_loss_share,
                "worst_day_share_of_mae": worst_day_share,
                "prior_close_warning_before_worst_day": prior_warning,
                "same_close_exit_signal_on_worst_day": same_close_exit,
                "tail_mechanism": mechanism,
                "turnover_units": float(interval["turnover_units"].sum()),
                "transaction_cost": float(interval["transaction_cost"].sum()),
            }
        )

    episodes = pd.DataFrame(rows)
    tail_days = top_state_two_tail_days(frame, top_n=top_n)
    if episodes.empty:
        return episodes, pd.DataFrame(), tail_days
    summary = pd.DataFrame(
        [
            {
                "episodes": int(len(episodes)),
                "sessions": int(episodes["sessions"].sum()),
                "mean_episode_net_return": float(episodes["net_return"].mean()),
                "negative_episode_rate": float(episodes["net_return"].lt(0).mean()),
                "mean_episode_max_drawdown": float(episodes["max_drawdown"].mean()),
                "worst_episode_net_return": float(episodes["net_return"].min()),
                "abrupt_or_gap_dominated_rate": float(
                    episodes["tail_mechanism"].eq("abrupt_or_gap_dominated").mean()
                ),
                "mean_overnight_loss_share": float(
                    episodes["overnight_loss_share"].mean()
                ),
                "prior_warning_rate": float(
                    episodes["prior_close_warning_before_worst_day"].mean()
                ),
                "same_close_exit_signal_rate": float(
                    episodes["same_close_exit_signal_on_worst_day"].mean()
                ),
            }
        ]
    )
    return episodes, summary, tail_days


def top_state_two_tail_days(
    frame: pd.DataFrame,
    *,
    top_n: int = 10,
) -> pd.DataFrame:
    """Rank the worst state-2 economic sessions and show observability."""

    sample = frame.loc[frame["position_state"].eq(2)].copy()
    if sample.empty:
        return pd.DataFrame()
    warnings = _warning_flags(frame)
    rows: list[dict[str, Any]] = []
    for date in sample.nsmallest(top_n, "net_return").index:
        location = frame.index.get_loc(date)
        previous_warning = (
            bool(warnings.iloc[location - 1]["any_warning"]) if location > 0 else False
        )
        row = sample.loc[date]
        rows.append(
            {
                "date": date,
                "net_return": float(row["net_return"]),
                "gross_return": float(row["gross_return"]),
                "intraday_contribution": float(row["intraday_contribution"]),
                "overnight_contribution": float(row["overnight_contribution"]),
                "previous_close_warning": previous_warning,
                "same_close_exit_signal": int(row["decision_state"]) < 2,
                "decision_reason": str(row["decision_reason"]),
                "vix_close": float(row["vix_close"]),
                "vxn_close": float(row["vxn_close"]),
                "vix_stress": bool(row["vix_stress"]),
                "vxn_stress": bool(row["vxn_stress"]),
                "below_ma_short_n": bool(row["below_ma_short_n"]),
                "qqq_below_ma20": bool(
                    float(row["QQQ_close"]) < float(row["ma_short"])
                ),
            }
        )
    return pd.DataFrame(rows)


def _delayed_execution_states(
    decisions: pd.Series,
    *,
    mode: str,
) -> pd.Series:
    """Convert close decisions to executed states under one-session delay stress."""

    valid_modes = {
        "baseline",
        "all_transitions_delay_1",
        "risk_increase_delay_1",
        "risk_reduction_delay_1",
    }
    if mode not in valid_modes:
        raise ValueError(f"unsupported execution mode: {mode}")
    targets = decisions.shift(1).fillna(0).astype(int)
    if mode == "baseline":
        return targets

    current = 0
    pending_target: int | None = None
    executed: list[int] = []
    for target in targets:
        target = int(target)
        if target == current:
            pending_target = None
            executed.append(current)
            continue
        delay = (
            mode == "all_transitions_delay_1"
            or (mode == "risk_increase_delay_1" and target > current)
            or (mode == "risk_reduction_delay_1" and target < current)
        )
        if not delay:
            current = target
            pending_target = None
        elif pending_target == target:
            current = target
            pending_target = None
        else:
            pending_target = target
        executed.append(current)
    return pd.Series(executed, index=decisions.index, dtype=int)


def run_execution_scenario(
    prepared_with_decisions: pd.DataFrame,
    contract: Mapping[str, Any],
    *,
    scenario: str,
    extra_cost_bps_per_turnover_unit: float = 0.0,
) -> StrategyResult:
    """Reprice frozen decisions under one execution stress scenario."""

    if extra_cost_bps_per_turnover_unit < 0.0:
        raise ValueError("extra cost must be non-negative")
    daily = prepared_with_decisions.copy()
    states = _delayed_execution_states(
        daily["decision_state"].astype(int),
        mode=scenario,
    )
    daily["position_state"] = states
    daily["position_label"] = states.map(
        {0: "defensive", 1: "attack", 2: "partial_leverage"}
    )
    weights = bridge_weights_for_states(states, contract)
    for asset in ASSETS:
        daily[f"weight_{asset}"] = weights[asset]
    daily["gross_return"] = sum(
        daily[f"weight_{asset}"] * daily[f"{asset}_next_open_return"]
        for asset in ASSETS
    )
    turnover = weights.diff().abs().sum(axis=1)
    if bool(contract["portfolio"]["charge_initial_entry"]) and not turnover.empty:
        turnover.iloc[0] = weights.iloc[0].abs().sum()
    else:
        turnover.iloc[0] = 0.0
    base_cost_bps = float(
        contract["portfolio"]["transaction_cost_bps_per_turnover_unit"]
    )
    daily["turnover_units"] = turnover
    daily["transaction_cost"] = (
        turnover * (base_cost_bps + extra_cost_bps_per_turnover_unit) / 10_000.0
    )
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily = daily.loc[daily["net_return"].notna()].copy()
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    metrics = _return_metrics(
        daily["net_return"],
        annual_risk_free_rate=float(contract["portfolio"]["annual_risk_free_rate"]),
    )
    metrics.update(
        {
            "strategy": scenario,
            "extra_cost_bps_per_turnover_unit": float(
                extra_cost_bps_per_turnover_unit
            ),
            "total_cost_bps_per_turnover_unit": (
                base_cost_bps + extra_cost_bps_per_turnover_unit
            ),
            "turnover_units": float(turnover.sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "state_2_sessions": int(daily["position_state"].eq(2).sum()),
        }
    )
    return StrategyResult(scenario, daily, pd.DataFrame(), metrics)


def execution_robustness_comparison(
    baseline_result: StrategyResult,
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, dict[str, StrategyResult]]:
    """Compare delay and slippage stresses against the frozen v4.2 baseline."""

    source = baseline_result.daily.copy()
    scenarios: dict[str, StrategyResult] = {}
    for mode in (
        "baseline",
        "all_transitions_delay_1",
        "risk_increase_delay_1",
        "risk_reduction_delay_1",
    ):
        scenarios[mode] = run_execution_scenario(
            source,
            contract,
            scenario=mode,
        )
    for extra in (5.0, 10.0, 20.0):
        key = f"baseline_plus_{int(extra)}bps"
        scenarios[key] = run_execution_scenario(
            source,
            contract,
            scenario="baseline",
            extra_cost_bps_per_turnover_unit=extra,
        )
        scenarios[key].metrics["strategy"] = key

    baseline_scenario = scenarios["baseline"]
    if not baseline_scenario.daily["position_state"].equals(
        baseline_result.daily["position_state"].astype(int)
    ):
        raise AssertionError("baseline execution scenario changed the v4.2 state trace")
    if not np.allclose(
        baseline_scenario.daily["net_return"].to_numpy(dtype=float),
        baseline_result.daily["net_return"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-12,
        equal_nan=True,
    ):
        raise AssertionError("baseline execution scenario does not reproduce v4.2 returns")

    rows = [dict(result.metrics) for result in scenarios.values()]
    table = pd.DataFrame(rows).set_index("strategy")
    baseline = table.loc["baseline"]
    for metric in (
        "total_return",
        "cagr",
        "sharpe",
        "sortino",
        "max_drawdown",
        "calmar",
    ):
        table[f"{metric}_delta_vs_baseline"] = table[metric] - float(baseline[metric])
    return table.sort_index(), scenarios


def state_two_research_gate(
    episode_summary: pd.DataFrame,
    tail_days: pd.DataFrame,
    execution_table: pd.DataFrame,
    gate_contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply predeclared gates to decide the next admissible research direction."""

    if episode_summary.empty or tail_days.empty:
        raise ValueError("state-2 diagnostics are empty")
    thresholds = gate_contract["research_gate"]
    overnight_share = float(
        tail_days["overnight_contribution"].clip(upper=0.0).abs().sum()
        / (
            tail_days["intraday_contribution"].clip(upper=0.0).abs().sum()
            + tail_days["overnight_contribution"].clip(upper=0.0).abs().sum()
        )
    )
    observable_rate = float(tail_days["previous_close_warning"].mean())
    exit_signal_rate = float(tail_days["same_close_exit_signal"].mean())
    risk_reduction_delay_cagr_delta = float(
        execution_table.loc[
            "risk_reduction_delay_1", "cagr_delta_vs_baseline"
        ]
    )
    gradual_rate = 1.0 - float(
        episode_summary.iloc[0]["abrupt_or_gap_dominated_rate"]
    )

    gates = {
        "overnight_loss_share_below_limit": overnight_share
        <= float(thresholds["max_overnight_loss_share"]),
        "observable_warning_rate_above_minimum": observable_rate
        >= float(thresholds["min_previous_close_warning_rate"]),
        "gradual_episode_rate_above_minimum": gradual_rate
        >= float(thresholds["min_gradual_episode_rate"]),
    }
    eligible = all(gates.values())
    if eligible:
        next_direction = "design_one_continuous_state2_volatility_budget_challenger"
    elif overnight_share > float(thresholds["max_overnight_loss_share"]):
        next_direction = (
            "do_not_add_close_based_scaling; prioritize_gap_risk_and_low_risk_variant"
        )
    elif risk_reduction_delay_cagr_delta < float(
        thresholds["max_risk_reduction_delay_cagr_delta"]
    ):
        next_direction = "study_exit_execution_reliability_before_new_risk_budget"
    else:
        next_direction = "retain_v4_2_and_continue_prospective_monitoring"

    return {
        "eligible_for_continuous_state2_volatility_budget": eligible,
        "next_direction": next_direction,
        "measured": {
            "top_tail_overnight_loss_share": overnight_share,
            "top_tail_previous_close_warning_rate": observable_rate,
            "top_tail_same_close_exit_signal_rate": exit_signal_rate,
            "gradual_episode_rate": gradual_rate,
            "risk_reduction_delay_cagr_delta": risk_reduction_delay_cagr_delta,
        },
        "thresholds": dict(thresholds),
        "gates": gates,
    }
