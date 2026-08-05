"""Build complete formal evidence for the frozen CN x1.1 candidate."""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FormalEvidence:
    periods: pd.DataFrame
    holdings: pd.DataFrame
    trades: pd.DataFrame
    attribution: list[dict[str, Any]]
    package: dict[str, Any]
    source_objects: dict[str, Any]


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if pd.isna(value):
        return None
    return value


def compound(values: pd.Series) -> float:
    return float(np.prod(1.0 + values.to_numpy(dtype=float)) - 1.0)


def maximum_drawdown(values: pd.Series) -> float:
    equity = np.cumprod(1.0 + values.to_numpy(dtype=float))
    peak = np.maximum.accumulate(equity)
    return float(np.min(equity / peak - 1.0))


def _load(source_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    periods = pd.read_csv(source_dir / "rebalance_periods.csv", parse_dates=["datetime"])
    holdings = pd.read_csv(
        source_dir / "holdings.csv",
        dtype={"instrument": str},
        parse_dates=["datetime"],
    )
    holdings["instrument"] = holdings["instrument"].str.zfill(6)
    holdings.loc[holdings["entity"].eq("CSI300 fallback"), "instrument"] = "000300"
    periods = periods.sort_values("datetime").reset_index(drop=True)
    holdings = holdings.sort_values(["datetime", "instrument"]).reset_index(drop=True)
    objects: dict[str, Any] = {
        name: pd.read_csv(source_dir / name)
        for name in (
            "half_year_results.csv",
            "neighbor_rule_summary.csv",
            "yearly_state_coverage.csv",
        )
    }
    import json

    for name in (
        "decision.json",
        "evaluation_contract.json",
        "manifest.json",
        "model_spec.json",
    ):
        objects[name] = json.loads((source_dir / name).read_text(encoding="utf-8"))
    return periods, holdings, objects


def build_trades(periods: pd.DataFrame, holdings: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    previous: dict[str, float] = {}
    previous_evaluation: str | None = None
    for period_index, period in periods.iterrows():
        evaluation = str(period["evaluation"])
        if previous_evaluation is not None and evaluation != previous_evaluation:
            previous = {}
        previous_evaluation = evaluation
        date = pd.Timestamp(period["datetime"])
        selected = holdings.loc[holdings["datetime"].eq(date)]
        current = {
            str(row.instrument): float(row.weight)
            for row in selected.itertuples(index=False)
        }
        names = sorted(set(previous) | set(current))
        deltas = {
            name: current.get(name, 0.0) - previous.get(name, 0.0)
            for name in names
        }
        previous_cash = 1.0 - sum(previous.values())
        current_cash = 1.0 - sum(current.values())
        observed_turnover = 0.5 * (
            sum(abs(delta) for delta in deltas.values())
            + abs(current_cash - previous_cash)
        )
        expected_turnover = float(period["turnover"])
        if abs(observed_turnover - expected_turnover) > 1e-9:
            raise ValueError(
                f"turnover mismatch {date:%Y-%m-%d}: "
                f"{observed_turnover} != {expected_turnover}"
            )
        total_security_change = sum(abs(delta) for delta in deltas.values())
        for instrument in names:
            delta = deltas[instrument]
            if abs(delta) < 1e-12:
                continue
            selected_row = selected.loc[selected["instrument"].eq(instrument)]
            current_weight = current.get(instrument, 0.0)
            previous_weight = previous.get(instrument, 0.0)
            if previous_weight == 0.0:
                action = "BUY"
            elif current_weight == 0.0:
                action = "SELL"
            elif delta > 0.0:
                action = "INCREASE"
            else:
                action = "DECREASE"
            rows.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "window": str(period["window"]),
                    "evaluation": evaluation,
                    "period_index": int(period_index),
                    "instrument": instrument,
                    "entity": None if selected_row.empty else selected_row.iloc[0]["entity"],
                    "sector": None if selected_row.empty else selected_row.iloc[0]["sector"],
                    "action": action,
                    "previous_weight": previous_weight,
                    "target_weight": current_weight,
                    "weight_delta": delta,
                    "allocated_transaction_cost": (
                        float(period["cost"]) * abs(delta) / total_security_change
                        if total_security_change
                        else 0.0
                    ),
                    "score": None if selected_row.empty else selected_row.iloc[0]["score"],
                    "risk_on": bool(period["risk_on"]),
                    "rule": str(period["rule"]),
                    "votes": int(period["votes"]),
                }
            )
        previous = current
    return pd.DataFrame(rows)


def build_attribution(periods: pd.DataFrame, holdings: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in holdings.itertuples(index=False):
        rows.append(
            {
                "attribution_type": "position",
                "date": row.datetime.strftime("%Y-%m-%d"),
                "window": row.window,
                "evaluation": row.evaluation,
                "instrument": row.instrument,
                "entity": row.entity,
                "sector": row.sector,
                "state": "risk_off" if row.instrument == "000300" else "risk_on",
                "value": float(row.net_contribution),
                "gross_return": float(row.raw_return),
                "weight": float(row.weight),
            }
        )
    for kind, columns in (
        ("security", ["instrument", "entity", "sector"]),
        ("sector", ["sector"]),
        ("window", ["window", "evaluation"]),
    ):
        for key, frame in holdings.groupby(columns, dropna=False, sort=True):
            values = key if isinstance(key, tuple) else (key,)
            record: dict[str, Any] = {
                "attribution_type": kind,
                "value": float(frame["net_contribution"].sum()),
                "periods": int(len(frame)),
            }
            record.update(
                {
                    column: None if pd.isna(value) else str(value)
                    for column, value in zip(columns, values, strict=True)
                }
            )
            rows.append(record)
    states = periods["risk_on"].map({True: "risk_on", False: "risk_off"})
    for state, frame in periods.groupby(states, sort=True):
        rows.append(
            {
                "attribution_type": "state",
                "state": state,
                "value": float(frame["relative_log_return"].sum()),
                "periods": int(len(frame)),
                "transaction_cost": float(frame["cost"].sum()),
            }
        )
    return rows


def _metrics(periods: pd.DataFrame) -> dict[str, float]:
    strategy = periods["net_return"].astype(float)
    benchmark = periods["benchmark_return"].astype(float)
    total = compound(strategy)
    benchmark_total = compound(benchmark)
    annual_factor = 252.0 / 10.0
    years = len(periods) / annual_factor
    volatility = float(strategy.std(ddof=1) * math.sqrt(annual_factor))
    excess = strategy - benchmark
    return {
        "Total Return": total,
        "Annualized Return": float((1.0 + total) ** (1.0 / years) - 1.0),
        "Benchmark Return": benchmark_total,
        "Compounded Relative Excess Return": float(
            (1.0 + total) / (1.0 + benchmark_total) - 1.0
        ),
        "Annualized Volatility": volatility,
        "Sharpe Ratio": float(
            strategy.mean() / strategy.std(ddof=1) * math.sqrt(annual_factor)
        ),
        "Information Ratio": float(
            excess.mean() / excess.std(ddof=1) * math.sqrt(annual_factor)
        ),
        "Max Drawdown": maximum_drawdown(strategy),
        "Turnover": float(periods["turnover"].sum()),
        "Transaction Cost": float(periods["cost"].sum()),
    }


def _report(periods: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "date": "2022-07-01",
            "account": 1.0,
            "bench_hs300": 1.0,
            "turnover": 0.0,
            "period_return": 0.0,
            "benchmark_return": 0.0,
            "trace_frequency": "non_overlapping_10_session",
        }
    ]
    account = 1.0
    benchmark = 1.0
    for row in periods.itertuples(index=False):
        account *= 1.0 + float(row.net_return)
        benchmark *= 1.0 + float(row.benchmark_return)
        rows.append(
            {
                "date": row.datetime.strftime("%Y-%m-%d"),
                "account": account,
                "bench_hs300": benchmark,
                "turnover": float(row.turnover),
                "period_return": float(row.net_return),
                "gross_return": float(row.gross_return),
                "benchmark_return": float(row.benchmark_return),
                "relative_log_return": float(row.relative_log_return),
                "transaction_cost": float(row.cost),
                "risk_on": bool(row.risk_on),
                "state": "risk_on" if row.risk_on else "risk_off",
                "votes": int(row.votes),
                "long_trend": bool(row.long_trend),
                "medium_momentum": bool(row.medium_momentum),
                "cross_sectional_breadth": bool(row.cross_sectional_breadth),
                "breadth_value": float(row.breadth_value),
                "window": row.window,
                "evaluation": row.evaluation,
                "trace_frequency": "non_overlapping_10_session",
            }
        )
    return rows


def build_formal_evidence(source_dir: Path) -> FormalEvidence:
    periods, holdings, source = _load(source_dir)
    trades = build_trades(periods, holdings)
    attribution = build_attribution(periods, holdings)
    positions = []
    for row in holdings.itertuples(index=False):
        positions.append(
            {
                "date": row.datetime.strftime("%Y-%m-%d"),
                "instrument": row.instrument,
                "entity": row.entity,
                "sector": row.sector,
                "weight": float(row.weight),
                "score": None if pd.isna(row.score) else float(row.score),
                "forward_return": float(row.raw_return),
                "benchmark_return": float(row.benchmark_return),
                "net_contribution": float(row.net_contribution),
                "precision_hit": bool(row.precision_hit),
                "window": row.window,
                "evaluation": row.evaluation,
                "state": "risk_off" if row.instrument == "000300" else "risk_on",
            }
        )
    half_year = source["half_year_results.csv"]
    neighbors = source["neighbor_rule_summary.csv"]
    yearly = source["yearly_state_coverage.csv"]
    window_summary = [
        {"record_type": "half_year", **clean(row)}
        for row in half_year.to_dict("records")
    ] + [
        {"record_type": "neighbor_rule", **clean(row)}
        for row in neighbors.to_dict("records")
    ] + [
        {"record_type": "yearly_state", **clean(row)}
        for row in yearly.to_dict("records")
    ]
    source_manifest = source["manifest.json"]
    decision = source["decision.json"]
    package = {
        "schema_version": "1.0.0",
        "record_type": "formal_model_backtest",
        "backtest_id": "cn_x1_1_through_2026_08_03",
        "model_id": "cn_x1_1",
        "display_name": "CN x1.1",
        "market": "cn",
        "benchmark": "000300",
        "publication_status": "accepted_formal_baseline",
        "generated_at": "2026-08-05T17:20:00Z",
        "evidence_cutoff": "2026-08-03",
        "research_only": True,
        "trade_ready": False,
        "trace_frequency": "non_overlapping_10_session",
        "date_range": {"start": "2022-07-01", "end": "2026-08-03"},
        "metrics": _metrics(periods),
        "portfolio_contract": {
            "universe": "cn_selected_equities_v3",
            "benchmark": "000300",
            "score_source": "r0_cn_x1_0_raw_return_rank/current_cn_ohlcv",
            "horizon_sessions": 10,
            "rebalance_sessions": 10,
            "execution_delay_sessions": 1,
            "cost_bps": 20,
            "weighting": "equal_weight",
            "active_sectors": 4,
            "names_per_sector": 1,
            "sector_score": "mean_top3_daily_score_percentile",
            "risk_on_votes_required": 2,
            "risk_on_votes": [
                "CSI300_close_above_MA200",
                "CSI300_60_session_return_positive",
                "CN130_share_above_own_MA60_at_least_50pct",
            ],
            "risk_off_fallback": "100_percent_CSI300",
        },
        "report": _report(periods),
        "positions": positions,
        "trades": clean(trades.to_dict("records")),
        "attribution": clean(attribution),
        "window_summary": window_summary,
        "state_summary": clean(yearly.to_dict("records")),
        "evidence": {
            "workflow_run_id": 31022910416,
            "workflow_head_sha": "20bb4f52d16e11fe594480226d0a02989cf9b00b",
            "artifact_id": 8937409026,
            "artifact_name": "cn-x1-1-fallback-aware-certified-31022910416",
            "artifact_digest": (
                "sha256:e540e400dbefd5178122444e709182323f1b363a3c41496fd8212e5095ee5a4b"
            ),
            "artifact_expires_at": "2026-09-04T15:59:13Z",
            "provider_artifact_id": 8850463785,
            "provider_identity_sha256": source_manifest["provider_identity_sha256"],
            "candidate_decision": decision["decision"],
            "candidate_source_pr": 576,
            "promotion_issue": 577,
            "frozen_economic_hashes": source["evaluation_contract.json"][
                "frozen_economic_hashes"
            ],
            "row_counts": {
                "rebalance_periods": len(periods),
                "positions": len(holdings),
                "trades": len(trades),
                "attribution": len(attribution),
            },
        },
        "evidence_completeness": {
            "status": "complete",
            "performance_trace": "retained_exact_non_overlapping_10_session_trace",
            "holdings": "retained_exact",
            "trades": "derived_deterministically_from_consecutive_exact_target_weights",
            "attribution": "retained_position_contribution_and_deterministic_aggregates",
            "state_trace": "retained_exact",
            "missing": [],
        },
        "freshness": {
            "status": "current",
            "required_cutoff": "2026-08-03",
            "latest_completed_session": "2026-08-03",
            "model_selection_reopened": False,
            "reporting_only_windows": ["2026H1", "2026H2_PARTIAL"],
        },
        "interpretation_notes": [
            "CN x1.1 supersedes CN x1.0 in the active formal catalog.",
            "Evidence begins 2022-07-01; earlier frozen R0 ledgers are outside the authorized identity.",
            "The 2026 windows remain reporting-only and did not alter model rules.",
            "The full trace combines separately governed historical and reporting segments.",
            "Static CN130 membership carries survivorship bias.",
            "Research evidence only; not authorization for automated trading.",
        ],
    }
    return FormalEvidence(periods, holdings, trades, attribution, package, source)
