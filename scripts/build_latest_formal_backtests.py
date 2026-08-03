"""Append current reporting windows to accepted US x1.1 and CN x1.0 packages.

Historical accepted evidence is immutable. The builder consumes only the frozen
2026 reporting windows, appends their realized economics, and never reruns model
selection or rewrites previously accepted rows.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any


class LatestFormalBacktestError(ValueError):
    """Raised when a latest-session extension is incomplete or inconsistent."""


def _object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LatestFormalBacktestError(f"invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise LatestFormalBacktestError(f"JSON root must be an object: {path}")
    return payload


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _calendar(path: Path) -> list[str]:
    rows = [
        row.strip()
        for row in path.read_text(encoding="utf-8").splitlines()
        if row.strip()
    ]
    if not rows or rows != sorted(set(rows)):
        raise LatestFormalBacktestError(f"invalid calendar: {path}")
    return rows


def _holding_end(calendar: list[str], signal_date: str, horizon: int) -> str:
    try:
        index = calendar.index(signal_date)
    except ValueError as exc:
        raise LatestFormalBacktestError(
            f"signal date missing from calendar: {signal_date}"
        ) from exc
    target = index + horizon
    if target >= len(calendar):
        raise LatestFormalBacktestError(
            f"horizon is not realized by provider cutoff: {signal_date}+{horizon}"
        )
    return calendar[target]


def _relative(strategy: float, benchmark: float) -> float:
    return (1.0 + strategy) / (1.0 + benchmark) - 1.0


def _trace(run_dir: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = _object(run_dir / "walk_forward_windows.json")
    rows = {
        str(row.get("label")): row
        for row in plan.get("windows", [])
        if isinstance(row, dict)
    }
    window = rows.get(label)
    if window is None or window.get("status") != "included":
        raise LatestFormalBacktestError(
            f"{run_dir.name}/{label}: window not included"
        )
    payload = _object(
        run_dir / "windows" / f"{plan['experiment_id']}_{label}.json"
    )
    traces = [
        row
        for row in payload.get("backtest_traces", [])
        if isinstance(row, dict)
        and row.get("orientation") == "original"
        and str(row.get("candidate_name", "")).startswith("xgb:daily_ranker")
    ]
    if len(traces) != 1:
        raise LatestFormalBacktestError(
            f"{run_dir.name}/{label}: expected one frozen original trace"
        )
    trace = traces[0]
    if trace.get("research_only") is not True or trace.get("trade_ready") is not False:
        raise LatestFormalBacktestError(
            f"{run_dir.name}/{label}: research boundary weakened"
        )
    if label == "2026H2":
        if window.get("complete") is not False:
            raise LatestFormalBacktestError(
                f"{run_dir.name}/{label}: must be partial"
            )
        if window.get("counts_toward_min_windows") is not False:
            raise LatestFormalBacktestError(
                f"{run_dir.name}/{label}: partial window affects selection"
            )
        if window.get("effective_test_end") != "2026-07-31":
            raise LatestFormalBacktestError(
                f"{run_dir.name}/{label}: cutoff mismatch"
            )
    return window, trace


def _validate_trace(trace: dict[str, Any]) -> None:
    points = trace.get("points")
    holdings = trace.get("holdings")
    contributions = trace.get("name_contributions")
    metrics = trace.get("metrics")
    if not all(
        isinstance(value, list) for value in (points, holdings, contributions)
    ):
        raise LatestFormalBacktestError("trace rows missing")
    if not isinstance(metrics, dict):
        raise LatestFormalBacktestError("trace metrics missing")
    if not (len(points) == len(holdings) == len(contributions)):
        raise LatestFormalBacktestError("trace row counts differ")
    benchmark = metrics.get("benchmark_period_returns")
    if not isinstance(benchmark, list) or len(benchmark) != len(points):
        raise LatestFormalBacktestError("benchmark period trace missing")
    if int(metrics.get("n_periods", -1)) != len(points):
        raise LatestFormalBacktestError("period count mismatch")
    if trace.get("forward_horizon_sessions") != 10:
        raise LatestFormalBacktestError("formal horizon must remain ten sessions")


def _trace_hash(trace: dict[str, Any]) -> str:
    payload = {
        key: trace[key]
        for key in (
            "candidate_name",
            "orientation",
            "forward_horizon_sessions",
            "top_n",
            "rebalance_days",
            "cost_bps",
            "points",
            "holdings",
            "name_contributions",
            "metrics",
            "research_only",
            "trade_ready",
        )
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def verify_duplicate_extensions(
    run_a: Path, run_b: Path, labels: tuple[str, ...]
) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for label in labels:
        _, a = _trace(run_a, label)
        _, b = _trace(run_b, label)
        _validate_trace(a)
        _validate_trace(b)
        digest_a = _trace_hash(a)
        digest_b = _trace_hash(b)
        if digest_a != digest_b:
            raise LatestFormalBacktestError(
                f"{run_a.name}/{label}: independent executions differ"
            )
        hashes[label] = digest_a
    return hashes


def _trade_rows(
    *,
    trace: dict[str, Any],
    calendar: list[str],
    window: str,
    period_offset: int,
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, float],
    dict[str, float],
    dict[str, int],
    dict[str, int],
    str,
]:
    _validate_trace(trace)
    positions: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    gross_by_name: dict[str, float] = defaultdict(float)
    cost_by_name: dict[str, float] = defaultdict(float)
    held_by_name: dict[str, int] = defaultdict(int)
    wins_by_name: dict[str, int] = defaultdict(int)
    previous: dict[str, float] = {}
    latest_end = ""

    for index, (point, holding, contribution) in enumerate(
        zip(
            trace["points"],
            trace["holdings"],
            trace["name_contributions"],
            strict=True,
        ),
        start=1,
    ):
        signal_date = str(point["signal_date"])
        if signal_date != holding.get("signal_date") or signal_date != contribution.get(
            "signal_date"
        ):
            raise LatestFormalBacktestError(f"{window}: signal-date mismatch")
        holding_end = _holding_end(calendar, signal_date, 10)
        latest_end = max(latest_end, holding_end)
        weights = {
            str(key): float(value)
            for key, value in dict(holding["weights"]).items()
        }
        contributions = {
            str(key): float(value)
            for key, value in dict(contribution["name_contributions"]).items()
        }
        if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
            raise LatestFormalBacktestError(f"{window}: weights do not sum to one")
        union = sorted(set(previous) | set(weights))
        absolute_change = sum(
            abs(weights.get(key, 0.0) - previous.get(key, 0.0)) for key in union
        )
        turnover = 0.5 * absolute_change
        period_cost = turnover * float(trace["cost_bps"]) / 10000.0
        gross = float(contribution["gross_portfolio_return"])
        net = float(point["net_period_return"])
        if not math.isclose(gross - period_cost, net, abs_tol=1e-10):
            raise LatestFormalBacktestError(f"{window}: cost/economics mismatch")

        for rank, instrument in enumerate(sorted(weights), start=1):
            value = contributions.get(instrument, 0.0)
            positions.append(
                {
                    "date": signal_date,
                    "holding_end_date": holding_end,
                    "instrument": instrument,
                    "weight": weights[instrument],
                    "rank": rank,
                    "forward_contribution": value,
                    "action": (
                        "BUY"
                        if previous.get(instrument, 0.0) == 0.0
                        else "HOLD"
                        if math.isclose(
                            previous.get(instrument, 0.0), weights[instrument]
                        )
                        else "REBALANCE"
                    ),
                    "window": window,
                }
            )
            gross_by_name[instrument] += value
            held_by_name[instrument] += 1
            if value > 0:
                wins_by_name[instrument] += 1

        for instrument in union:
            old = previous.get(instrument, 0.0)
            new = weights.get(instrument, 0.0)
            delta = new - old
            allocated = (
                period_cost * abs(delta) / absolute_change if absolute_change else 0.0
            )
            if old == 0.0 and new > 0.0:
                action = "BUY"
            elif old > 0.0 and new == 0.0:
                action = "SELL"
            elif math.isclose(delta, 0.0, abs_tol=1e-15):
                action = "HOLD"
            elif delta > 0.0:
                action = "INCREASE"
            else:
                action = "DECREASE"
            trades.append(
                {
                    "date": signal_date,
                    "holding_end_date": holding_end,
                    "instrument": instrument,
                    "action": action,
                    "previous_weight": old,
                    "target_weight": new,
                    "weight_delta": delta,
                    "transaction_cost": allocated,
                    "period_index": period_offset + index,
                    "window": window,
                }
            )
            cost_by_name[instrument] += allocated
        previous = weights
    return (
        positions,
        trades,
        dict(gross_by_name),
        dict(cost_by_name),
        dict(held_by_name),
        dict(wins_by_name),
        latest_end,
    )


def _append_us(
    package: dict[str, Any],
    *,
    run_dir: Path,
    calendar: list[str],
    cutoff: str,
    generated_at: str,
    workflow_run_id: str,
    workflow_head_sha: str,
    duplicate_hashes: dict[str, str],
) -> dict[str, Any]:
    output = copy.deepcopy(package)
    if (
        output.get("model_id") != "us_x1_1"
        or output.get("evidence_cutoff") != "2025-12-31"
    ):
        raise LatestFormalBacktestError(
            "US source package is not the accepted 2025 baseline"
        )
    if [row.get("window") for row in output["window_summary"]] != [
        "2024H1",
        "2024H2",
        "2025H1",
        "2025H2",
    ]:
        raise LatestFormalBacktestError("US historical windows were already modified")

    account = float(output["report"][-1]["account"])
    bench = float(output["report"][-1]["bench_qqq"])
    peak = max(float(row["account"]) for row in output["report"])
    period_offset = len(output["report"]) - 1
    new_turnover = 0.0
    new_cost = 0.0
    latest_realized = ""
    gross_new: dict[str, float] = defaultdict(float)
    cost_new: dict[str, float] = defaultdict(float)
    held_new: dict[str, int] = defaultdict(int)
    wins_new: dict[str, int] = defaultdict(int)
    windows_new: dict[str, set[str]] = defaultdict(set)

    for label in ("2026H1", "2026H2"):
        window_row, trace = _trace(run_dir, label)
        _validate_trace(trace)
        window = f"{label}_partial" if label == "2026H2" else label
        metrics = trace["metrics"]
        benchmark_returns = [
            float(value) for value in metrics["benchmark_period_returns"]
        ]
        (
            positions,
            trades,
            gross,
            costs,
            held,
            wins,
            latest_end,
        ) = _trade_rows(
            trace=trace,
            calendar=calendar,
            window=window,
            period_offset=period_offset,
        )
        latest_realized = max(latest_realized, latest_end)
        output["positions"].extend(positions)
        output["trades"].extend(trades)
        for name, value in gross.items():
            gross_new[name] += value
            windows_new[name].add(window)
        for name, value in costs.items():
            cost_new[name] += value
        for name, value in held.items():
            held_new[name] += value
        for name, value in wins.items():
            wins_new[name] += value

        for point, benchmark_return in zip(
            trace["points"], benchmark_returns, strict=True
        ):
            signal_date = str(point["signal_date"])
            holding_end = _holding_end(calendar, signal_date, 10)
            net = float(point["net_period_return"])
            account *= 1.0 + net
            bench *= 1.0 + benchmark_return
            peak = max(peak, account)
            period_offset += 1
            output["report"].append(
                {
                    "date": signal_date,
                    "holding_end_date": holding_end,
                    "account": account,
                    "bench_qqq": bench,
                    "period_return": net,
                    "benchmark_return": benchmark_return,
                    "excess_return": net - benchmark_return,
                    "drawdown": account / peak - 1.0,
                    "window": window,
                    "partial_window": label == "2026H2",
                    "trace_frequency": "non_overlapping_10_session",
                }
            )
        window_turnover = float(metrics["turnover"])
        window_cost = float(metrics["costs"])
        new_turnover += window_turnover
        new_cost += window_cost
        output["window_summary"].append(
            {
                "window": window,
                "source_window": label,
                "complete": bool(window_row["complete"]),
                "counts_toward_model_selection": bool(
                    window_row["counts_toward_min_windows"]
                ),
                "periods": int(metrics["n_periods"]),
                "net_strategy_return": float(metrics["total_return"]),
                "qqq_return": float(metrics["benchmark_return"]),
                "compounded_relative_excess_return": _relative(
                    float(metrics["total_return"]),
                    float(metrics["benchmark_return"]),
                ),
                "turnover": window_turnover,
                "transaction_cost": window_cost,
                "max_drawdown": float(metrics["max_drawdown"]),
                "start": str(metrics["test_start"]),
                "last_signal_date": str(metrics["test_end"]),
                "provider_cutoff": cutoff,
                "horizon_eligible_sessions": int(
                    window_row["horizon_eligible_sessions"]
                ),
                "trace_sha256": duplicate_hashes[label],
            }
        )

    old_attribution = {
        str(row["instrument"]): copy.deepcopy(row) for row in output["attribution"]
    }
    for instrument in sorted(set(old_attribution) | set(gross_new) | set(cost_new)):
        row = old_attribution.setdefault(
            instrument,
            {
                "instrument": instrument,
                "name": instrument,
                "gross_contribution": 0.0,
                "transaction_cost": 0.0,
                "value": 0.0,
                "periods_held": 0,
                "windows_held": 0,
                "win_rate": 0.0,
            },
        )
        old_periods = int(row.get("periods_held", 0))
        old_wins = float(row.get("win_rate", 0.0)) * old_periods
        row["gross_contribution"] = float(
            row.get("gross_contribution", 0.0)
        ) + gross_new.get(instrument, 0.0)
        row["transaction_cost"] = float(
            row.get("transaction_cost", 0.0)
        ) + cost_new.get(instrument, 0.0)
        row["value"] = row["gross_contribution"] - row["transaction_cost"]
        row["periods_held"] = old_periods + held_new.get(instrument, 0)
        row["windows_held"] = int(row.get("windows_held", 0)) + len(
            windows_new.get(instrument, set())
        )
        row["win_rate"] = (
            (old_wins + wins_new.get(instrument, 0)) / row["periods_held"]
            if row["periods_held"]
            else 0.0
        )
    output["attribution"] = sorted(
        old_attribution.values(),
        key=lambda row: (-float(row["value"]), row["instrument"]),
    )

    output["backtest_id"] = "us_x1_1_through_2026_07_31"
    output["generated_at"] = generated_at
    output["evidence_cutoff"] = cutoff
    output["date_range"]["end"] = cutoff
    output["metrics"] = {
        **output["metrics"],
        "Total Return": account - 1.0,
        "Benchmark Return": bench - 1.0,
        "Compounded Relative Excess Return": account / bench - 1.0,
        "Max Drawdown": min(
            float(row.get("drawdown", 0.0)) for row in output["report"]
        ),
        "Turnover": float(output["metrics"]["Turnover"]) + new_turnover,
        "Transaction Cost": float(output["metrics"]["Transaction Cost"])
        + new_cost,
    }
    evidence = dict(output["evidence"])
    evidence["freshness_evidence"] = {
        "schema_version": "1.0.0",
        "workflow_run_id": workflow_run_id,
        "workflow_head_sha": workflow_head_sha,
        "provider_identity_sha256": (
            "5c09d0fbc8348e182ce8829c44d43d96aaae4ed8a2c2ba8901e69034a7c6aa95"
        ),
        "provider_cutoff": cutoff,
        "independent_execution_count": 2,
        "trace_sha256": duplicate_hashes,
        "model_selection_reopened": False,
        "automatic_promotion": False,
    }
    output["evidence"] = evidence
    output["freshness"] = {
        "schema_version": "1.0.0",
        "status": "current",
        "required_cutoff": cutoff,
        "latest_completed_session": cutoff,
        "latest_realized_holding_end": latest_realized,
        "partial_final_window": "2026H2_partial",
        "model_selection_reopened": False,
    }
    output["interpretation_notes"] = [
        "Formal accepted US x1.1 history through 2025-12-31 is retained unchanged.",
        "2026H1 and 2026H2_partial are deterministic reporting extensions of the frozen model.",
        "2026H2_partial is excluded from model selection and automatic promotion.",
        f"Provider evidence is current through {cutoff}; the latest realized ten-session holding ends {latest_realized}.",
        "Research evidence only; not authorization for live or automated trading.",
    ]
    return output


def _append_cn(
    package: dict[str, Any],
    *,
    run_dir: Path,
    calendar: list[str],
    cutoff: str,
    generated_at: str,
    workflow_run_id: str,
    workflow_head_sha: str,
    duplicate_hash: str,
) -> dict[str, Any]:
    output = copy.deepcopy(package)
    if (
        output.get("model_id") != "cn_x1_0"
        or output.get("evidence_cutoff") != "2026-06-15"
    ):
        raise LatestFormalBacktestError(
            "CN source package is not the accepted 2026H1 baseline"
        )
    if output["window_summary"][-1].get("window") != "2026H1":
        raise LatestFormalBacktestError("CN historical window list was already modified")
    window_row, trace = _trace(run_dir, "2026H2")
    _validate_trace(trace)
    metrics = trace["metrics"]
    points = trace["points"]
    holdings = trace["holdings"]
    benchmark_returns = [
        float(value) for value in metrics["benchmark_period_returns"]
    ]
    latest_holding_end = max(
        _holding_end(calendar, str(row["signal_date"]), 10) for row in points
    )
    account = float(output["report"][-1]["account"]) * (
        1.0 + float(metrics["total_return"])
    )
    bench = float(output["report"][-1]["bench_hs300"]) * (
        1.0 + float(metrics["benchmark_return"])
    )
    output["report"].append(
        {
            "date": str(metrics["test_end"]),
            "holding_end_date": latest_holding_end,
            "account": account,
            "bench_hs300": bench,
            "period_return": float(metrics["total_return"]),
            "benchmark_return": float(metrics["benchmark_return"]),
            "excess_return": float(metrics["excess_return"]),
            "max_drawdown": float(metrics["max_drawdown"]),
            "turnover": float(metrics["turnover"]),
            "window": "2026H2_partial",
            "partial_window": True,
            "trace_frequency": "partial_half_year_window",
        }
    )
    final_holding = dict(holdings[-1])
    final_date = str(final_holding["signal_date"])
    final_end = _holding_end(calendar, final_date, 10)
    weights = {
        str(key): float(value)
        for key, value in dict(final_holding["weights"]).items()
    }
    for rank, instrument in enumerate(sorted(weights), start=1):
        output["positions"].append(
            {
                "date": final_date,
                "holding_end_date": final_end,
                "instrument": instrument,
                "rank": rank,
                "weight": weights[instrument],
                "window": "2026H2_partial",
                "snapshot_semantics": "final_top15_for_partial_window",
            }
        )
    output["window_summary"].append(
        {
            "window": "2026H2_partial",
            "source_window": "2026H2",
            "complete": False,
            "counts_toward_model_selection": False,
            "start": str(metrics["test_start"]),
            "end": str(metrics["test_end"]),
            "latest_realized_holding_end": latest_holding_end,
            "provider_cutoff": cutoff,
            "n_periods": int(metrics["n_periods"]),
            "total_return": float(metrics["total_return"]),
            "benchmark_return": float(metrics["benchmark_return"]),
            "compounded_relative_excess_return": _relative(
                float(metrics["total_return"]),
                float(metrics["benchmark_return"]),
            ),
            "max_drawdown": float(metrics["max_drawdown"]),
            "turnover": float(metrics["turnover"]),
            "horizon_eligible_sessions": int(
                window_row["horizon_eligible_sessions"]
            ),
            "trace_sha256": duplicate_hash,
            "benchmark_period_returns": benchmark_returns,
        }
    )
    output["backtest_id"] = "cn_x1_0_through_2026_07_31"
    output["generated_at"] = generated_at
    output["evidence_cutoff"] = cutoff
    output["date_range"]["end"] = cutoff
    output["metrics"] = {
        **output["metrics"],
        "Total Return": account - 1.0,
        "Benchmark Return": bench - 1.0,
        "Compounded Relative Excess Return": account / bench - 1.0,
        "Max Drawdown": min(
            float(output["metrics"]["Max Drawdown"]),
            float(metrics["max_drawdown"]),
        ),
    }
    evidence = dict(output["evidence"])
    evidence["freshness_evidence"] = {
        "schema_version": "1.0.0",
        "workflow_run_id": workflow_run_id,
        "workflow_head_sha": workflow_head_sha,
        "provider_identity_sha256": (
            "bf5fa1373a0b5ebfedcd90c2cf3c4748300efd2b25da0adfbfb1daab8c6405d8"
        ),
        "provider_cutoff": cutoff,
        "independent_execution_count": 2,
        "trace_sha256": {"2026H2": duplicate_hash},
        "model_selection_reopened": False,
        "automatic_promotion": False,
    }
    output["evidence"] = evidence
    output["freshness"] = {
        "schema_version": "1.0.0",
        "status": "current",
        "required_cutoff": cutoff,
        "latest_completed_session": cutoff,
        "latest_realized_holding_end": latest_holding_end,
        "partial_final_window": "2026H2_partial",
        "model_selection_reopened": False,
    }
    completeness = dict(output["evidence_completeness"])
    missing = set(str(value) for value in completeness.get("missing", []))
    missing.update(
        {
            "historical_transaction_ledger",
            "historical_security_attribution",
        }
    )
    completeness.update(
        {
            "status": "partial",
            "latest_partial_window_trace": "retained_exact",
            "missing": sorted(missing),
        }
    )
    output["evidence_completeness"] = completeness
    output["interpretation_notes"] = [
        "Formal accepted CN x1.0 history through 2026H1 is retained unchanged.",
        "2026H2_partial is a deterministic reporting extension of the frozen model.",
        "The partial window is excluded from model selection and automatic promotion.",
        "Historical transaction-ledger and security-attribution evidence remain unavailable; the frontend must continue to show that limitation.",
        f"Provider evidence is current through {cutoff}; the latest realized ten-session holding ends {latest_holding_end}.",
        "Research evidence only; not authorization for live or automated trading.",
    ]
    return output


def build(
    *,
    us_run_a: Path,
    us_run_b: Path,
    cn_run_a: Path,
    cn_run_b: Path,
    us_calendar_path: Path,
    cn_calendar_path: Path,
    existing_dir: Path,
    output_dir: Path,
    cutoff: str,
    generated_at: str,
    workflow_run_id: str,
    workflow_head_sha: str,
) -> dict[str, Any]:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    us_hashes = verify_duplicate_extensions(
        us_run_a, us_run_b, ("2026H1", "2026H2")
    )
    cn_hashes = verify_duplicate_extensions(cn_run_a, cn_run_b, ("2026H2",))
    us = _append_us(
        _object(existing_dir / "us_x1_1.json"),
        run_dir=us_run_a,
        calendar=_calendar(us_calendar_path),
        cutoff=cutoff,
        generated_at=generated_at,
        workflow_run_id=workflow_run_id,
        workflow_head_sha=workflow_head_sha,
        duplicate_hashes=us_hashes,
    )
    cn = _append_cn(
        _object(existing_dir / "cn_x1_0.json"),
        run_dir=cn_run_a,
        calendar=_calendar(cn_calendar_path),
        cutoff=cutoff,
        generated_at=generated_at,
        workflow_run_id=workflow_run_id,
        workflow_head_sha=workflow_head_sha,
        duplicate_hash=cn_hashes["2026H2"],
    )
    v42 = _object(existing_dir / "qqqi_qqq_tqqq_v4_2.json")
    if v42.get("evidence_cutoff") != cutoff:
        raise LatestFormalBacktestError("QQQ Rotation v4.2 is stale")
    for model_id, payload in (
        ("qqqi_qqq_tqqq_v4_2", v42),
        ("us_x1_1", us),
        ("cn_x1_0", cn),
    ):
        _write(output_dir / f"{model_id}.json", payload)

    old_catalog = _object(existing_dir / "catalog.json")
    records = []
    for row in old_catalog["records"]:
        updated = dict(row)
        updated["sha256"] = _sha256(output_dir / str(updated["path"]))
        records.append(updated)
    catalog = {
        **old_catalog,
        "published_at": generated_at,
        "records": records,
        "research_only": True,
        "trade_ready": False,
    }
    _write(output_dir / "catalog.json", catalog)
    return {
        "schema_version": "1.0.0",
        "cutoff": cutoff,
        "generated_at": generated_at,
        "models": [
            {
                "model_id": model_id,
                "sha256": _sha256(output_dir / f"{model_id}.json"),
            }
            for model_id in (
                "qqqi_qqq_tqqq_v4_2",
                "us_x1_1",
                "cn_x1_0",
            )
        ],
        "catalog_sha256": _sha256(output_dir / "catalog.json"),
        "trace_sha256": {"us": us_hashes, "cn": cn_hashes},
        "research_only": True,
        "trade_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--us-run-a", type=Path, required=True)
    parser.add_argument("--us-run-b", type=Path, required=True)
    parser.add_argument("--cn-run-a", type=Path, required=True)
    parser.add_argument("--cn-run-b", type=Path, required=True)
    parser.add_argument("--us-calendar", type=Path, required=True)
    parser.add_argument("--cn-calendar", type=Path, required=True)
    parser.add_argument(
        "--existing-dir",
        type=Path,
        default=Path("data/research/formal_backtests"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--cutoff", default="2026-07-31")
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--workflow-run-id", default="")
    parser.add_argument("--workflow-head-sha", default="")
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = build(
        us_run_a=args.us_run_a,
        us_run_b=args.us_run_b,
        cn_run_a=args.cn_run_a,
        cn_run_b=args.cn_run_b,
        us_calendar_path=args.us_calendar,
        cn_calendar_path=args.cn_calendar,
        existing_dir=args.existing_dir,
        output_dir=args.output_dir,
        cutoff=args.cutoff,
        generated_at=args.generated_at,
        workflow_run_id=args.workflow_run_id,
        workflow_head_sha=args.workflow_head_sha,
    )
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
