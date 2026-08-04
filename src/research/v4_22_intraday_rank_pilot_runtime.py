from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

import pandas as pd

import src.research.v4_22_intraday_rank_pilot as core


_ECONOMIC_COLUMNS = (
    "QQQ_open",
    "QQQ_opening_close",
    "QQQ_next_open",
    "TQQQ_open",
    "TQQQ_opening_close",
    "TQQQ_next_open",
    "SPY_open",
    "SPY_opening_close",
    "SPY_next_open",
    "baseline_exact_gross_return",
    "overlay_exact_gross_return",
    "baseline_exact_net_return",
    "overlay_exact_net_return",
    "switch_turnover_units",
    "baseline_next_reconcile_turnover_units",
    "overlay_next_reconcile_turnover_units",
    "incremental_turnover_units",
)


def _audit_frame(
    frame: pd.DataFrame,
    contract: Mapping[str, Any],
) -> pd.DataFrame:
    out = frame.copy()
    rate = (
        float(
            contract["boundaries"][
                "transaction_cost_bps_per_turnover_unit"
            ]
        )
        / 10_000.0
    )
    out["switch_cost"] = out["switch_turnover_units"] * rate
    out["baseline_next_reconcile_cost"] = (
        out["baseline_next_reconcile_turnover_units"] * rate
    )
    out["overlay_next_reconcile_cost"] = (
        out["overlay_next_reconcile_turnover_units"] * rate
    )
    out["incremental_cost"] = (
        out["switch_cost"]
        + out["overlay_next_reconcile_cost"]
        - out["baseline_next_reconcile_cost"]
    )
    return out


def _enrich_ledger(
    ledger: pd.DataFrame,
    frame: pd.DataFrame,
) -> pd.DataFrame:
    if ledger.empty:
        columns = list(ledger.columns)
        for column in (*_ECONOMIC_COLUMNS, "switch_cost", "baseline_next_reconcile_cost", "overlay_next_reconcile_cost", "incremental_cost"):
            if column not in columns:
                columns.append(column)
        return pd.DataFrame(columns=columns)
    additions = [
        column
        for column in (
            *_ECONOMIC_COLUMNS,
            "switch_cost",
            "baseline_next_reconcile_cost",
            "overlay_next_reconcile_cost",
            "incremental_cost",
        )
        if column in frame.columns and column not in ledger.columns
    ]
    return ledger.join(frame[additions], how="left")


def _full_path_frame(
    baseline_daily: pd.DataFrame,
    state2_frame: pd.DataFrame,
    contract: Mapping[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    start = pd.Timestamp(contract["intraday_data"]["start_date"])
    end = pd.Timestamp(contract["intraday_data"]["end_date"])
    index = baseline_daily.index[
        (baseline_daily.index >= start) & (baseline_daily.index <= end)
    ]
    baseline = baseline_daily.reindex(index).copy()
    path_frame = pd.DataFrame(index=index)
    path_frame["delever_to_qqq_net_advantage"] = state2_frame[
        "delever_to_qqq_net_advantage"
    ].reindex(index)
    return baseline, path_frame


def run_intraday_rank_pilot_runtime(
    intraday_bars: Mapping[str, pd.DataFrame],
    daily_bars: Mapping[str, pd.DataFrame],
    baseline_daily: pd.DataFrame,
    contract: Mapping[str, Any],
) -> core.IntradayPilotResult:
    """Run the frozen pilot and complete path/ledger audit surfaces.

    The model, features, scores, thresholds, triggers and event labels are produced
    by the frozen core. This wrapper only extends the strategy path to the complete
    declared intraday interval and attaches already-computed prices and costs to
    prediction/event ledgers.
    """

    result = core.run_intraday_rank_pilot(
        intraday_bars,
        daily_bars,
        baseline_daily,
        contract,
    )
    audited_frame = _audit_frame(result.frame, contract)
    predictions = _enrich_ledger(result.predictions, audited_frame)
    events = _enrich_ledger(result.triggered_events, audited_frame)

    baseline_slice, path_frame = _full_path_frame(
        baseline_daily, audited_frame, contract
    )
    event_dates = pd.DatetimeIndex(events.index) if not events.empty else pd.DatetimeIndex([])
    all_state2_dates = pd.DatetimeIndex(
        audited_frame.dropna(
            subset=["delever_to_qqq_net_advantage"]
        ).index
    )
    strategies = {
        "frozen_v4_2": core._strategy_daily(
            baseline_slice,
            path_frame,
            pd.DatetimeIndex([]),
            name="frozen_v4_2",
        ),
        "rank_triggered_intraday_meta_label": core._strategy_daily(
            baseline_slice,
            path_frame,
            event_dates,
            name="rank_triggered_intraday_meta_label",
        ),
        "always_delever_state2_at_1000": core._strategy_daily(
            baseline_slice,
            path_frame,
            all_state2_dates,
            name="always_delever_state2_at_1000",
        ),
    }
    strategy_metrics = core._metrics_table(strategies)
    tail_metrics, tail_gate = core._tail_and_path(
        baseline_slice,
        audited_frame,
        events,
        strategies,
        contract,
    )
    trainable = bool(
        len(result.fold_coverage) == len(contract["outer_folds"])
        and result.fold_coverage["trainable"].all()
    )
    if not trainable:
        decision = (
            "intraday_rank_pilot_inconclusive_due_to_sample_or_class_coverage"
        )
    elif result.feasibility_gate["passed"] and tail_gate["passed"]:
        decision = "intraday_rank_mechanism_worth_prospective_collection"
    else:
        decision = "intraday_rank_mechanism_not_supported_in_recent_history"
    return replace(
        result,
        frame=audited_frame,
        predictions=predictions,
        triggered_events=events,
        strategy_daily=strategies,
        strategy_metrics=strategy_metrics,
        tail_metrics=tail_metrics,
        tail_and_path_gate=tail_gate,
        decision=decision,
    )
