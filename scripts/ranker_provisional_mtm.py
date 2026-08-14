"""Attach an evidence-cutoff MTM observation to formal ranker packages.

MTM is a valuation view over an already sealed forward decision. It never scores
or creates a target. The strategy signal ledger is the only authority allowed to
advance live ranker state.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.artifacts.formal_refresh import load_object, write_object
from src.artifacts.strategy_signal_ledger import read_latest_evaluation
from src.research.cn130_cross_sectional_ranking import read_qlib_feature
from src.research.ranker_current_target import CN_MODEL_ID, next_due_session
from src.research.us_x1_3_current_target import MODEL_ID as US_MODEL_ID


class RankerProvisionalMtmError(ValueError):
    """Raised when current ranker MTM cannot be proven from governed evidence."""


def _calendar(provider_dir: Path) -> pd.DatetimeIndex:
    path = provider_dir / "calendars" / "day.txt"
    if not path.is_file():
        raise RankerProvisionalMtmError(f"provider calendar is missing: {path}")
    return pd.DatetimeIndex(
        pd.to_datetime(path.read_text(encoding="utf-8").splitlines()),
        name="datetime",
    ).tz_localize(None).normalize()


def _close(provider_dir: Path, instrument: str, calendar: pd.DatetimeIndex) -> pd.Series:
    path = provider_dir / "features" / instrument.lower() / "close.day.bin"
    if not path.is_file():
        raise RankerProvisionalMtmError(f"provider close is missing: {path}")
    values = read_qlib_feature(path, len(calendar))
    return pd.Series(values, index=calendar, dtype=float, name=instrument)


def _formal_signal_date(package: Mapping[str, Any]) -> str:
    positions = package.get("positions")
    if not isinstance(positions, list) or not positions:
        raise RankerProvisionalMtmError("formal ranker package has no positions")
    dates = sorted(
        str(row.get("date") or "")
        for row in positions
        if isinstance(row, Mapping) and row.get("date")
    )
    if not dates:
        raise RankerProvisionalMtmError("formal ranker positions have no signal date")
    return dates[-1]


def _valid_target(signal: Mapping[str, Any]) -> dict[str, float]:
    raw = signal.get("target_weights")
    if not isinstance(raw, Mapping) or not raw:
        raise RankerProvisionalMtmError("current target has no target_weights")
    target = {str(key): float(value) for key, value in raw.items()}
    if not np.isclose(sum(target.values()), 1.0, rtol=0.0, atol=1e-6):
        raise RankerProvisionalMtmError("current target weights do not sum to one")
    return dict(sorted(target.items()))


def _latest_governed_signal(
    *,
    model_id: str,
    formal_signal_date: str,
    cutoff: str,
    ledger_dir: Path,
) -> dict[str, Any] | None:
    """Return the canonical live signal, never a recomputed substitute."""

    record = read_latest_evaluation(ledger_dir, model_version_id=model_id)
    if record is None:
        return None
    signal = record.get("signal")
    if not isinstance(signal, dict):
        raise RankerProvisionalMtmError("latest governed signal payload is missing")
    signal_date = str(signal.get("signal_date") or record.get("signal_date") or "")
    if not signal_date:
        raise RankerProvisionalMtmError("latest governed signal date is missing")

    formal_ts = pd.Timestamp(formal_signal_date)
    signal_ts = pd.Timestamp(signal_date)
    cutoff_ts = pd.Timestamp(cutoff)
    if signal_ts < formal_ts:
        raise RankerProvisionalMtmError(
            "formal ranker state is ahead of the canonical forward ledger: "
            f"formal={formal_signal_date} ledger={signal_date}"
        )
    if signal_ts > cutoff_ts:
        raise RankerProvisionalMtmError(
            "canonical forward signal exceeds the MTM cutoff: "
            f"signal={signal_date} cutoff={cutoff}"
        )
    return signal


def _benchmark_field(model_id: str) -> tuple[str, str]:
    if model_id == US_MODEL_ID:
        return "bench_qqq", "QQQ"
    if model_id == CN_MODEL_ID:
        return "bench_hs300", "000300"
    raise RankerProvisionalMtmError(f"unsupported ranker model: {model_id}")


def _mtm_return(
    *,
    provider_dir: Path,
    calendar: pd.DatetimeIndex,
    target: Mapping[str, float],
    signal_date: str,
    cutoff: str,
    execution_delay_sessions: int,
) -> tuple[str | None, float]:
    signal_ts = pd.Timestamp(signal_date).normalize()
    cutoff_ts = pd.Timestamp(cutoff).normalize()
    signal_matches = np.flatnonzero(calendar == signal_ts)
    cutoff_matches = np.flatnonzero(calendar == cutoff_ts)
    if len(signal_matches) != 1 or len(cutoff_matches) != 1:
        raise RankerProvisionalMtmError(
            f"signal/cutoff is not uniquely present in provider calendar: {signal_date}/{cutoff}"
        )
    entry_index = int(signal_matches[0]) + int(execution_delay_sessions)
    cutoff_index = int(cutoff_matches[0])
    if entry_index > cutoff_index:
        return None, 0.0
    entry_date = pd.Timestamp(calendar[entry_index]).strftime("%Y-%m-%d")

    weighted_return = 0.0
    for instrument, weight in target.items():
        close = _close(provider_dir, instrument, calendar)
        entry = float(close.iloc[entry_index])
        current = float(close.iloc[cutoff_index])
        if not np.isfinite(entry) or entry <= 0.0 or not np.isfinite(current) or current <= 0.0:
            raise RankerProvisionalMtmError(
                f"invalid MTM close for {instrument}: {entry_date}/{cutoff}"
            )
        weighted_return += float(weight) * (current / entry - 1.0)
    return entry_date, float(weighted_return)


def attach_ranker_provisional_mtm(
    *,
    package_path: Path,
    provider_dir: Path,
    ledger_dir: Path,
    cutoff: str,
    repository_root: Path,
) -> dict[str, Any] | None:
    """Replace one ranker's provisional MTM observation with the current cutoff view."""

    package = load_object(package_path)
    package.pop("provisional_mtm", None)
    freshness = package.get("freshness")
    if isinstance(freshness, dict):
        freshness.pop("latest_mtm_date", None)
        freshness.pop("performance_observation_status", None)

    model_id = str(package.get("model_id") or "")
    if model_id not in {US_MODEL_ID, CN_MODEL_ID}:
        raise RankerProvisionalMtmError(f"unsupported formal package: {model_id}")

    evidence_cutoff = str(package.get("evidence_cutoff") or "")
    if not evidence_cutoff:
        raise RankerProvisionalMtmError(f"{model_id} evidence cutoff is missing")
    if pd.Timestamp(evidence_cutoff) > pd.Timestamp(cutoff):
        raise RankerProvisionalMtmError(
            f"{model_id} MTM cutoff regresses evidence: {cutoff} < {evidence_cutoff}"
        )

    report = package.get("report")
    if not isinstance(report, list) or not report:
        raise RankerProvisionalMtmError(f"{model_id} formal report is empty")
    settled_report = [
        row
        for row in report
        if isinstance(row, Mapping)
        and row.get("provisional_mtm") is not True
        and row.get("settlement_status") != "provisional_mtm"
    ]
    if not settled_report:
        raise RankerProvisionalMtmError(f"{model_id} formal report has no settled rows")
    package["report"] = settled_report
    report = settled_report

    formal_signal = _formal_signal_date(package)
    calendar = _calendar(provider_dir)
    signal = _latest_governed_signal(
        model_id=model_id,
        formal_signal_date=formal_signal,
        cutoff=cutoff,
        ledger_dir=ledger_dir,
    )
    if signal is None:
        due = next_due_session(anchor=formal_signal, sessions=calendar)
        if due is not None and pd.Timestamp(due) <= pd.Timestamp(cutoff):
            raise RankerProvisionalMtmError(
                "MTM cannot advance forward state: canonical ledger signal is missing for "
                f"{model_id} due={due} cutoff={cutoff}"
            )
        write_object(package_path, package)
        return None

    package["evidence_cutoff"] = cutoff
    date_range = package.get("date_range")
    if isinstance(date_range, dict):
        date_range["end"] = cutoff
    if isinstance(freshness, dict):
        freshness["status"] = "current"
        freshness["required_cutoff"] = cutoff
        freshness["latest_completed_session"] = cutoff

    signal_date = str(signal.get("signal_date") or "")
    target = _valid_target(signal)
    contract = package.get("portfolio_contract")
    delay = int(contract.get("execution_delay_sessions", 0)) if isinstance(contract, Mapping) else 0
    entry_date, gross_return = _mtm_return(
        provider_dir=provider_dir,
        calendar=calendar,
        target=target,
        signal_date=signal_date,
        cutoff=cutoff,
        execution_delay_sessions=delay,
    )
    rebalance_turnover = float(signal.get("turnover_units") or 0.0)
    transaction_cost = (
        float(signal.get("estimated_transaction_cost") or 0.0)
        if entry_date is not None
        else 0.0
    )
    net_return = gross_return - transaction_cost

    benchmark_field, benchmark_instrument = _benchmark_field(model_id)
    benchmark_target = {benchmark_instrument: 1.0}
    _, benchmark_return = _mtm_return(
        provider_dir=provider_dir,
        calendar=calendar,
        target=benchmark_target,
        signal_date=signal_date,
        cutoff=cutoff,
        execution_delay_sessions=delay,
    )

    previous = report[-1]
    if not isinstance(previous, Mapping):
        raise RankerProvisionalMtmError("latest settled performance row is invalid")
    account_before = float(previous.get("account"))
    benchmark_before = float(previous.get(benchmark_field))
    if not np.isfinite(account_before) or not np.isfinite(benchmark_before):
        raise RankerProvisionalMtmError("latest settled NAV is invalid")
    account = account_before * (1.0 + net_return)
    benchmark_nav = benchmark_before * (1.0 + benchmark_return)
    peak = max(float(row.get("account")) for row in report if isinstance(row, Mapping))
    drawdown = account / max(peak, account) - 1.0

    mtm_row: dict[str, Any] = {
        "date": cutoff,
        "signal_date": signal_date,
        "holding_end_date": cutoff,
        "account_before": account_before,
        "account": account,
        benchmark_field: benchmark_nav,
        f"{benchmark_field}_before": benchmark_before,
        "gross_return": gross_return,
        "period_return": net_return,
        "benchmark_return": benchmark_return,
        "excess_return": net_return - benchmark_return,
        "turnover": 0.0,
        "rebalance_date": signal_date,
        "rebalance_turnover": rebalance_turnover,
        "transaction_cost": transaction_cost,
        "transaction_cost_source_date": signal_date,
        "drawdown": drawdown,
        "window": str(previous.get("window") or ""),
        "evaluation": str(previous.get("evaluation") or "reporting"),
        "trace_frequency": str(package.get("trace_frequency") or "non_overlapping_10_session"),
        "partial_window": True,
        "provisional_mtm": True,
        "settlement_status": "provisional_mtm",
        "mtm_as_of": cutoff,
        "mtm_entry_date": entry_date,
        "research_only": True,
        "trade_ready": False,
    }
    if model_id == CN_MODEL_ID and net_return > -1.0 and benchmark_return > -1.0:
        mtm_row["relative_log_return"] = float(
            np.log1p(net_return) - np.log1p(benchmark_return)
        )
    diagnostics = signal.get("diagnostics")
    if isinstance(diagnostics, Mapping):
        for key in (
            "risk_on",
            "votes",
            "long_trend",
            "medium_momentum",
            "cross_sectional_breadth",
            "breadth_value",
        ):
            if key in diagnostics:
                mtm_row[key] = diagnostics[key]

    package["provisional_mtm"] = {
        "schema_version": "ranker_provisional_mtm_v1",
        "as_of": cutoff,
        "signal_date": signal_date,
        "entry_date": entry_date,
        "target_weights": target,
        "source": "strategy_signal_ledger",
        "performance_row": mtm_row,
        "research_only": True,
        "trade_ready": False,
    }
    if isinstance(freshness, dict):
        freshness["latest_mtm_date"] = cutoff
        freshness["performance_observation_status"] = "provisional_mtm"
    write_object(package_path, package)
    return package["provisional_mtm"]
