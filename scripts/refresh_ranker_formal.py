"""Refresh accepted US x1.1 and CN x1.1 formal packages append-only.

The adapters consume freshly rebuilt providers and frozen-model evidence. They
never rerun model selection. Existing report, position and trade rows remain an
exact prefix; only newly realized 10-session periods may be appended.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from scripts.run_cn_x1_1_sector_breadth import load_ledgers
from src.artifacts.formal_refresh import FormalRefreshError, load_object, sha256, write_object
from src.artifacts.performance_semantics import build_performance_semantics
from src.research.cn130_cross_sectional_ranking import forward_returns, load_provider_panel
from src.research.cn_x1_1_regime_gated import (
    RegimeGateSpec,
    build_regime_state,
    run_regime_portfolio,
)


class RankerRefreshError(FormalRefreshError):
    """Raised when a frozen ranker extension cannot be reproduced."""


def _date_identity(value: Any) -> str:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise RankerRefreshError(f"invalid date identity: {value!r}") from exc
    if pd.isna(timestamp):
        raise RankerRefreshError(f"invalid date identity: {value!r}")
    return timestamp.strftime("%Y-%m-%d")


def _calendar(path: Path) -> list[str]:
    rows = [row.strip() for row in path.read_text(encoding="utf-8").splitlines() if row.strip()]
    if not rows or rows != sorted(set(rows)):
        raise RankerRefreshError(f"invalid provider calendar: {path}")
    return rows


def _holding_end(
    calendar: Sequence[str],
    signal_date: str,
    *,
    holding_sessions: int = 10,
    execution_delay_sessions: int = 0,
) -> str:
    try:
        index = calendar.index(signal_date)
    except ValueError as exc:
        raise RankerRefreshError(f"signal date is absent from provider calendar: {signal_date}") from exc
    target = index + execution_delay_sessions + holding_sessions
    if target >= len(calendar):
        raise RankerRefreshError(
            "unrealized horizon: "
            f"{signal_date}+{execution_delay_sessions}+{holding_sessions}"
        )
    return str(calendar[target])


def _trace(run_dir: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = load_object(run_dir / "walk_forward_windows.json")
    rows = {
        str(row.get("label")): row
        for row in plan.get("windows", [])
        if isinstance(row, dict)
    }
    window = rows.get(label)
    if window is None or window.get("status") != "included":
        raise RankerRefreshError(f"{run_dir.name}/{label}: window is not included")
    payload = load_object(run_dir / "windows" / f"{plan['experiment_id']}_{label}.json")
    traces = [
        row
        for row in payload.get("backtest_traces", [])
        if isinstance(row, dict)
        and row.get("orientation") == "original"
        and str(row.get("candidate_name", "")).startswith("xgb:daily_ranker")
    ]
    if len(traces) != 1:
        raise RankerRefreshError(f"{run_dir.name}/{label}: frozen XGBoost trace is ambiguous")
    trace = traces[0]
    points = trace.get("points")
    holdings = trace.get("holdings")
    contributions = trace.get("name_contributions")
    metrics = trace.get("metrics")
    if not all(isinstance(value, list) for value in (points, holdings, contributions)):
        raise RankerRefreshError(f"{run_dir.name}/{label}: trace rows are missing")
    if not isinstance(metrics, dict) or not (
        len(points) == len(holdings) == len(contributions)
    ):
        raise RankerRefreshError(f"{run_dir.name}/{label}: trace row counts differ")
    if trace.get("forward_horizon_sessions") != 10 or trace.get("rebalance_days") != 10:
        raise RankerRefreshError(f"{run_dir.name}/{label}: frozen 10-session contract changed")
    if trace.get("research_only") is not True or trace.get("trade_ready") is not False:
        raise RankerRefreshError(f"{run_dir.name}/{label}: research boundary changed")
    return window, trace


def _trace_digest(trace: Mapping[str, Any]) -> str:
    retained = {
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
        json.dumps(retained, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _latest_weights(package: Mapping[str, Any]) -> dict[str, float]:
    positions = package.get("positions")
    if not isinstance(positions, list) or not positions:
        return {}
    latest = max(str(row.get("date") or "") for row in positions if isinstance(row, dict))
    return {
        str(row["instrument"]): float(row["weight"])
        for row in positions
        if isinstance(row, dict) and str(row.get("date")) == latest
    }


def _attribution_index(package: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = package.get("attribution")
    if not isinstance(rows, list):
        raise RankerRefreshError("formal attribution is missing")
    return {
        str(row.get("instrument")): row
        for row in rows
        if isinstance(row, dict) and row.get("instrument")
    }


def _latest_realized_holding_end(package: Mapping[str, Any]) -> str:
    candidates: list[str] = []
    freshness = package.get("freshness")
    if isinstance(freshness, Mapping):
        accepted = freshness.get("latest_realized_holding_end")
        if accepted:
            candidates.append(_date_identity(accepted))
    for field in ("report", "positions", "trades"):
        rows = package.get(field)
        if not isinstance(rows, list):
            continue
        candidates.extend(
            _date_identity(row["holding_end_date"])
            for row in rows
            if isinstance(row, Mapping) and row.get("holding_end_date")
        )
    if not candidates:
        raise RankerRefreshError("formal package has no realized holding end evidence")
    return max(candidates)


def _update_common_metadata(
    package: dict[str, Any],
    *,
    cutoff: str,
    generated_at: str,
    provider_manifest: Path,
    evidence: Mapping[str, Any],
) -> None:
    package["performance_semantics"] = build_performance_semantics(
        dict(package["portfolio_contract"]),
        trace_frequency=package.get("trace_frequency"),
    )
    package["generated_at"] = generated_at
    package["evidence_cutoff"] = cutoff
    package["date_range"] = {
        **dict(package["date_range"]),
        "end": cutoff,
    }
    package["freshness"] = {
        "status": "current",
        "required_cutoff": cutoff,
        "latest_completed_session": cutoff,
        "latest_realized_holding_end": _latest_realized_holding_end(package),
        "model_selection_reopened": False,
        "provider_manifest_sha256": sha256(provider_manifest),
        "research_only": True,
        "trade_ready": False,
    }
    package["evidence"] = {
        **dict(package.get("evidence") or {}),
        **dict(evidence),
        "refresh_provider_manifest": provider_manifest.as_posix(),
        "refresh_provider_manifest_sha256": sha256(provider_manifest),
        "model_selection_reopened": False,
    }
    package["research_only"] = True
    package["trade_ready"] = False


def refresh_us(
    *,
    current_package: Path,
    run_a: Path,
    run_b: Path,
    calendar_path: Path,
    provider_manifest: Path,
    cutoff: str,
    generated_at: str,
    output: Path,
) -> dict[str, Any]:
    package = copy.deepcopy(load_object(current_package))
    if package.get("model_id") != "us_x1_1":
        raise RankerRefreshError("US refresh requires the accepted us_x1_1 package")
    calendar = _calendar(calendar_path)
    existing_dates = {
        str(row.get("date"))
        for row in package.get("report", [])
        if isinstance(row, dict)
    }
    previous = _latest_weights(package)
    account = float(package["report"][-1]["account"])
    benchmark = float(package["report"][-1]["bench_qqq"])
    peak = max(float(row["account"]) for row in package["report"])
    period_index = max(
        [int(row.get("period_index", 0)) for row in package.get("trades", []) if isinstance(row, dict)]
        or [len(package["report"]) - 1]
    )
    attribution = _attribution_index(package)
    window_updates: dict[str, dict[str, Any]] = {}
    duplicate_hashes: dict[str, str] = {}
    appended = 0

    for label in ("2026H1", "2026H2"):
        window_a, trace_a = _trace(run_a, label)
        window_b, trace_b = _trace(run_b, label)
        digest_a = _trace_digest(trace_a)
        digest_b = _trace_digest(trace_b)
        if digest_a != digest_b or window_a != window_b:
            raise RankerRefreshError(f"US duplicate executions differ for {label}")
        duplicate_hashes[label] = digest_a
        benchmark_returns = [float(value) for value in trace_a["metrics"]["benchmark_period_returns"]]
        if len(benchmark_returns) != len(trace_a["points"]):
            raise RankerRefreshError(f"US benchmark trace is incomplete for {label}")
        window_name = "2026H2_partial" if label == "2026H2" else label

        for point, holding, contribution, benchmark_return in zip(
            trace_a["points"],
            trace_a["holdings"],
            trace_a["name_contributions"],
            benchmark_returns,
            strict=True,
        ):
            signal_date = str(point["signal_date"])
            if signal_date != str(holding.get("signal_date")) or signal_date != str(
                contribution.get("signal_date")
            ):
                raise RankerRefreshError(f"US signal identity mismatch: {signal_date}")
            if signal_date in existing_dates:
                continue
            holding_end = _holding_end(calendar, signal_date)
            if holding_end > cutoff:
                continue
            weights = {str(key): float(value) for key, value in dict(holding["weights"]).items()}
            contributions = {
                str(key): float(value)
                for key, value in dict(contribution["name_contributions"]).items()
            }
            if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
                raise RankerRefreshError(f"US weights do not sum to one: {signal_date}")
            union = sorted(set(previous) | set(weights))
            absolute_change = sum(
                abs(weights.get(name, 0.0) - previous.get(name, 0.0)) for name in union
            )
            turnover = 0.5 * absolute_change
            cost = turnover * float(trace_a["cost_bps"]) / 10000.0
            gross = float(contribution["gross_portfolio_return"])
            net = float(point["net_period_return"])
            if not math.isclose(gross - cost, net, abs_tol=1e-10):
                raise RankerRefreshError(f"US cost reconciliation failed: {signal_date}")

            account *= 1.0 + net
            benchmark *= 1.0 + benchmark_return
            peak = max(peak, account)
            package["report"].append(
                {
                    "date": signal_date,
                    "holding_end_date": holding_end,
                    "account": account,
                    "bench_qqq": benchmark,
                    "period_return": net,
                    "gross_return": gross,
                    "benchmark_return": benchmark_return,
                    "excess_return": net - benchmark_return,
                    "turnover": turnover,
                    "transaction_cost": cost,
                    "drawdown": account / peak - 1.0,
                    "window": window_name,
                    "partial_window": label == "2026H2",
                    "trace_frequency": "non_overlapping_10_session",
                }
            )
            period_index += 1
            for rank, instrument in enumerate(sorted(weights), start=1):
                value = contributions.get(instrument, 0.0)
                package["positions"].append(
                    {
                        "date": signal_date,
                        "holding_end_date": holding_end,
                        "instrument": instrument,
                        "weight": weights[instrument],
                        "rank": rank,
                        "forward_contribution": value,
                        "action": "BUY" if previous.get(instrument, 0.0) == 0.0 else "HOLD",
                        "window": window_name,
                    }
                )
                item = attribution.setdefault(
                    instrument,
                    {
                        "instrument": instrument,
                        "name": instrument,
                        "value": 0.0,
                        "gross_contribution": 0.0,
                        "transaction_cost": 0.0,
                        "periods_held": 0,
                        "windows_held": 0,
                        "win_rate": 0.0,
                    },
                )
                wins = float(item.get("win_rate", 0.0)) * int(item.get("periods_held", 0))
                item["gross_contribution"] = float(item.get("gross_contribution", 0.0)) + value
                item["periods_held"] = int(item.get("periods_held", 0)) + 1
                item["win_rate"] = (wins + float(value > 0.0)) / item["periods_held"]
            for instrument in union:
                old = previous.get(instrument, 0.0)
                target = weights.get(instrument, 0.0)
                delta = target - old
                if math.isclose(delta, 0.0, abs_tol=1e-15):
                    continue
                allocated = cost * abs(delta) / absolute_change if absolute_change else 0.0
                action = (
                    "BUY"
                    if old == 0.0 and target > 0.0
                    else "SELL"
                    if old > 0.0 and target == 0.0
                    else "INCREASE"
                    if delta > 0.0
                    else "DECREASE"
                )
                package["trades"].append(
                    {
                        "date": signal_date,
                        "holding_end_date": holding_end,
                        "instrument": instrument,
                        "action": action,
                        "previous_weight": old,
                        "target_weight": target,
                        "weight_delta": delta,
                        "transaction_cost": allocated,
                        "period_index": period_index,
                        "window": window_name,
                    }
                )
                if instrument in attribution:
                    attribution[instrument]["transaction_cost"] = float(
                        attribution[instrument].get("transaction_cost", 0.0)
                    ) + allocated
            previous = weights
            existing_dates.add(signal_date)
            appended += 1

        metrics = trace_a["metrics"]
        window_updates[window_name] = {
            "window": window_name,
            "start": window_a.get("effective_test_start"),
            "end": window_a.get("effective_test_end"),
            "partial_window": label == "2026H2",
            "n_periods": int(metrics["n_periods"]),
            "total_return": float(metrics["total_return"]),
            "benchmark_return": float(metrics["benchmark_return"]),
            "simple_excess_return": float(metrics["total_return"])
            - float(metrics["benchmark_return"]),
            "turnover": float(metrics["turnover"]),
            "transaction_cost": float(metrics["costs"]),
            "trace_sha256": digest_a,
        }

    package["attribution"] = sorted(
        attribution.values(), key=lambda row: abs(float(row.get("value", 0.0))), reverse=True
    )
    existing_windows = {
        str(row.get("window")): row
        for row in package.get("window_summary", [])
        if isinstance(row, dict)
    }
    existing_windows.update(window_updates)
    package["window_summary"] = list(existing_windows.values())
    last = package["report"][-1]
    package["metrics"] = {
        **dict(package["metrics"]),
        "Total Return": float(last["account"]) - 1.0,
        "Benchmark Return": float(last["bench_qqq"]) - 1.0,
        "Compounded Relative Excess Return": float(last["account"])
        / float(last["bench_qqq"])
        - 1.0,
        "Max Drawdown": min(float(row.get("drawdown", 0.0)) for row in package["report"]),
        "Turnover": sum(float(row.get("turnover", 0.0)) for row in package["report"]),
        "Transaction Cost": sum(
            float(row.get("transaction_cost", 0.0)) for row in package["report"]
        ),
    }
    package["backtest_id"] = f"us_x1_1-through-{cutoff.replace('-', '_')}"
    _update_common_metadata(
        package,
        cutoff=cutoff,
        generated_at=generated_at,
        provider_manifest=provider_manifest,
        evidence={
            "refresh_adapter": "refresh_ranker_formal.us_x1_1",
            "duplicate_trace_sha256": duplicate_hashes,
            "run_a_identity_sha256": sha256(run_a / "candidate_manifest.json"),
            "run_b_identity_sha256": sha256(run_b / "candidate_manifest.json"),
        },
    )
    write_object(output, package)
    return {"model_id": "us_x1_1", "appended_periods": appended, "output_sha256": sha256(output)}


def _classification_map(root: Path) -> dict[str, Mapping[str, Any]]:
    import yaml

    payload = yaml.safe_load(
        (root / "configs/research_classifications/cn130_sector_industry_v1.yaml").read_text(
            encoding="utf-8"
        )
    )
    values = payload.get("symbols")
    if not isinstance(values, dict):
        raise RankerRefreshError("CN classification map is invalid")
    return {str(key).zfill(6): value for key, value in values.items()}


def refresh_cn(
    *,
    repository_root: Path,
    current_package: Path,
    provider_dir: Path,
    provider_manifest: Path,
    ledger_a: Path,
    ledger_b: Path,
    cutoff: str,
    generated_at: str,
    output: Path,
) -> dict[str, Any]:
    package = copy.deepcopy(load_object(current_package))
    if package.get("model_id") != "cn_x1_1":
        raise RankerRefreshError("CN refresh requires the accepted cn_x1_1 package")
    if sha256(ledger_a) != sha256(ledger_b):
        raise RankerRefreshError("CN duplicate score-ledger executions differ")

    spec = RegimeGateSpec()
    import yaml

    universe = yaml.safe_load(
        (repository_root / "configs/research_universes/cn_selected_equities_v3.yaml").read_text(
            encoding="utf-8"
        )
    )
    symbols = [str(value).zfill(6) for value in universe["symbols"]]
    if len(symbols) != 130 or len(set(symbols)) != 130:
        raise RankerRefreshError("CN130 universe identity is not exact")
    ledger_root = ledger_a.parent
    ledger, _ = load_ledgers([ledger_root], ("2026H2_PARTIAL",))
    panel = load_provider_panel(provider_dir, [*symbols, spec.benchmark], fields=("close",))
    close = panel.fields["close"]
    calendar = [_date_identity(value) for value in close.index]
    if calendar != sorted(set(calendar)):
        raise RankerRefreshError("CN provider calendar is invalid")
    state = build_regime_state(
        close,
        symbols=symbols,
        benchmark=spec.benchmark,
        long_ma_sessions=spec.long_ma_sessions,
        momentum_sessions=spec.momentum_sessions,
        breadth_ma_sessions=spec.breadth_ma_sessions,
        breadth_threshold=spec.breadth_threshold,
    )
    benchmark_returns = forward_returns(
        close[[spec.benchmark]],
        horizon=spec.horizon_sessions,
        delay=spec.execution_delay_sessions,
    )[spec.benchmark]
    summary, periods, holdings, windows = run_regime_portfolio(
        ledger,
        benchmark_returns,
        state,
        windows=("2026H2_PARTIAL",),
        variant=spec.variant(),
        rule="two_of_three",
        rebalance_sessions=spec.rebalance_sessions,
        cost_bps=spec.cost_bps,
    )

    existing_dates = {
        _date_identity(row.get("date"))
        for row in package.get("report", [])
        if isinstance(row, dict) and row.get("date")
    }
    previous = _latest_weights(package)
    account = float(package["report"][-1]["account"])
    benchmark = float(package["report"][-1]["bench_hs300"])
    peak = max(float(row["account"]) for row in package["report"])
    period_index = max(
        [int(row.get("period_index", 0)) for row in package.get("trades", []) if isinstance(row, dict)]
        or [len(package["report"]) - 1]
    )
    attribution = _attribution_index(package)
    classifications = _classification_map(repository_root)
    appended = 0

    holdings_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in holdings.to_dict("records"):
        holdings_by_date[_date_identity(row["datetime"])].append(row)

    for period in periods.to_dict("records"):
        signal_date = _date_identity(period["datetime"])
        if signal_date in existing_dates:
            continue
        holding_end = _holding_end(
            calendar,
            signal_date,
            holding_sessions=spec.horizon_sessions,
            execution_delay_sessions=spec.execution_delay_sessions,
        )
        if holding_end > cutoff:
            continue
        rows = holdings_by_date.get(signal_date, [])
        if not rows:
            raise RankerRefreshError(f"CN holdings are missing: {signal_date}")
        weights = {str(row["instrument"]): float(row["weight"]) for row in rows}
        if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
            raise RankerRefreshError(f"CN weights do not sum to one: {signal_date}")
        net = float(period["net_return"])
        benchmark_return = float(period["benchmark_return"])
        gross = float(period["gross_return"])
        turnover = float(period["turnover"])
        cost = float(period["cost"])
        account *= 1.0 + net
        benchmark *= 1.0 + benchmark_return
        peak = max(peak, account)
        risk_on = bool(period["risk_on"])
        package["report"].append(
            {
                "date": signal_date,
                "holding_end_date": holding_end,
                "account": account,
                "bench_hs300": benchmark,
                "period_return": net,
                "gross_return": gross,
                "benchmark_return": benchmark_return,
                "excess_return": net - benchmark_return,
                "relative_log_return": float(period["relative_log_return"]),
                "turnover": turnover,
                "transaction_cost": cost,
                "drawdown": account / peak - 1.0,
                "window": "2026H2_PARTIAL",
                "evaluation": "reporting",
                "risk_on": risk_on,
                "risk_state": "risk_on" if risk_on else "risk_off_csi300_fallback",
                "votes": int(period["votes"]),
                "long_trend": bool(period["long_trend"]),
                "medium_momentum": bool(period["medium_momentum"]),
                "cross_sectional_breadth": bool(period["cross_sectional_breadth"]),
                "breadth_value": float(period["breadth_value"]),
                "benchmark_hit": bool(period["benchmark_hit"]),
                "trace_frequency": "non_overlapping_10_session",
            }
        )
        for row in rows:
            instrument = str(row["instrument"])
            entity = str(row.get("entity") or instrument)
            sector = str(row.get("sector") or classifications.get(instrument, {}).get("sector") or "Unknown")
            contribution = float(row["net_contribution"])
            package["positions"].append(
                {
                    "date": signal_date,
                    "holding_end_date": holding_end,
                    "instrument": instrument,
                    "name": entity,
                    "sector": sector,
                    "weight": float(row["weight"]),
                    "score": None if pd.isna(row.get("score")) else float(row["score"]),
                    "raw_return": float(row["raw_return"]),
                    "benchmark_return": float(row["benchmark_return"]),
                    "net_contribution": contribution,
                    "precision_hit": bool(row["precision_hit"]),
                    "window": "2026H2_PARTIAL",
                    "evaluation": "reporting",
                    "risk_state": "risk_on" if risk_on else "risk_off_csi300_fallback",
                }
            )
            item = attribution.setdefault(
                instrument,
                {
                    "instrument": instrument,
                    "name": entity,
                    "sector": sector,
                    "value": 0.0,
                    "periods_held": 0,
                    "risk_on_periods": 0,
                    "risk_off_periods": 0,
                },
            )
            item["value"] = float(item.get("value", 0.0)) + contribution
            item["periods_held"] = int(item.get("periods_held", 0)) + 1
            item["risk_on_periods"] = int(item.get("risk_on_periods", 0)) + int(risk_on)
            item["risk_off_periods"] = int(item.get("risk_off_periods", 0)) + int(not risk_on)
        union = sorted(set(previous) | set(weights))
        absolute_change = sum(
            abs(weights.get(name, 0.0) - previous.get(name, 0.0)) for name in union
        )
        period_index += 1
        for instrument in union:
            old = previous.get(instrument, 0.0)
            target = weights.get(instrument, 0.0)
            delta = target - old
            if math.isclose(delta, 0.0, abs_tol=1e-15):
                continue
            allocated = cost * abs(delta) / absolute_change if absolute_change else 0.0
            action = (
                "BUY"
                if old == 0.0 and target > 0.0
                else "SELL"
                if old > 0.0 and target == 0.0
                else "INCREASE"
                if delta > 0.0
                else "DECREASE"
            )
            source = next((row for row in rows if str(row["instrument"]) == instrument), None)
            package["trades"].append(
                {
                    "date": signal_date,
                    "holding_end_date": holding_end,
                    "instrument": instrument,
                    "action": action,
                    "previous_weight": old,
                    "target_weight": target,
                    "weight_delta": delta,
                    "transaction_cost": allocated,
                    "reason": "regime_gated_sector_breadth_rebalance",
                    "risk_state": "risk_on" if risk_on else "risk_off_csi300_fallback",
                    "window": "2026H2_PARTIAL",
                    "entity": None if source is None else source.get("entity"),
                    "sector": None if source is None else source.get("sector"),
                    "period_index": period_index,
                }
            )
        previous = weights
        existing_dates.add(signal_date)
        appended += 1

    package["attribution"] = sorted(
        attribution.values(), key=lambda row: abs(float(row.get("value", 0.0))), reverse=True
    )
    window_rows = {
        str(row.get("window")): row
        for row in package.get("window_summary", [])
        if isinstance(row, dict) and row.get("window")
    }
    for row in windows.to_dict("records"):
        window_rows[str(row["window"])] = row
    package["window_summary"] = list(window_rows.values())
    last = package["report"][-1]
    package["metrics"] = {
        **dict(package["metrics"]),
        "Total Return": float(last["account"]) - 1.0,
        "Benchmark Return": float(last["bench_hs300"]) - 1.0,
        "Compounded Relative Excess Return": float(last["account"])
        / float(last["bench_hs300"])
        - 1.0,
        "Max Drawdown": min(float(row.get("drawdown", 0.0)) for row in package["report"]),
        "Turnover": sum(float(row.get("turnover", 0.0)) for row in package["report"]),
        "Transaction Cost": sum(
            float(row.get("transaction_cost", 0.0)) for row in package["report"]
        ),
        "2026 Reporting Relative Excess Return": float(summary["relative_excess"]),
    }
    package["backtest_id"] = f"cn_x1_1-through-{cutoff.replace('-', '_')}"
    _update_common_metadata(
        package,
        cutoff=cutoff,
        generated_at=generated_at,
        provider_manifest=provider_manifest,
        evidence={
            "refresh_adapter": "refresh_ranker_formal.cn_x1_1",
            "score_ledger_sha256": sha256(ledger_a),
            "duplicate_score_ledger_sha256": sha256(ledger_b),
            "reporting_summary": summary,
        },
    )
    write_object(output, package)
    return {"model_id": "cn_x1_1", "appended_periods": appended, "output_sha256": sha256(output)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    us = subparsers.add_parser("us")
    us.add_argument("--current-package", type=Path, required=True)
    us.add_argument("--run-a", type=Path, required=True)
    us.add_argument("--run-b", type=Path, required=True)
    us.add_argument("--calendar", type=Path, required=True)
    us.add_argument("--provider-manifest", type=Path, required=True)
    us.add_argument("--cutoff", required=True)
    us.add_argument("--generated-at", required=True)
    us.add_argument("--output", type=Path, required=True)

    cn = subparsers.add_parser("cn")
    cn.add_argument("--repository-root", type=Path, default=Path.cwd())
    cn.add_argument("--current-package", type=Path, required=True)
    cn.add_argument("--provider-dir", type=Path, required=True)
    cn.add_argument("--provider-manifest", type=Path, required=True)
    cn.add_argument("--ledger-a", type=Path, required=True)
    cn.add_argument("--ledger-b", type=Path, required=True)
    cn.add_argument("--cutoff", required=True)
    cn.add_argument("--generated-at", required=True)
    cn.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "us":
        result = refresh_us(
            current_package=args.current_package,
            run_a=args.run_a,
            run_b=args.run_b,
            calendar_path=args.calendar,
            provider_manifest=args.provider_manifest,
            cutoff=args.cutoff,
            generated_at=args.generated_at,
            output=args.output,
        )
    else:
        result = refresh_cn(
            repository_root=args.repository_root.resolve(),
            current_package=args.current_package,
            provider_dir=args.provider_dir,
            provider_manifest=args.provider_manifest,
            ledger_a=args.ledger_a,
            ledger_b=args.ledger_b,
            cutoff=args.cutoff,
            generated_at=args.generated_at,
            output=args.output,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
