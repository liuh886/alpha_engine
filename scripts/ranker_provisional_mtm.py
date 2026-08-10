"""Attach an evidence-cutoff MTM observation to formal ranker packages.

The accepted v1 report remains settled, append-only evidence. This module writes a
single replaceable ``provisional_mtm`` sidecar on US/CN ranker packages. Bundle v2
may project that row into its performance trace for the dashboard.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.artifacts.strategy_signal_ledger import read_latest_evaluation
from src.research.cn130_cross_sectional_ranking import read_qlib_feature
from src.research.ranker_current_target import (
    CN_MODEL_ID,
    US_MODEL_ID,
    next_due_session,
    score_cn_current_target,
    score_us_current_target,
)
from src.artifacts.formal_refresh import load_object, write_object


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


def _last_settled_signal_date(package: Mapping[str, Any]) -> str:
    report = package.get("report")
    if not isinstance(report, list) or not report:
        raise RankerProvisionalMtmError("formal ranker package has no settled report")
    latest = report[-1]
    if not isinstance(latest, Mapping):
        raise RankerProvisionalMtmError("latest settled performance row is invalid")
    signal_date = str(latest.get("date") or "")
    if not signal_date:
        raise RankerProvisionalMtmError("latest settled performance row has no signal date")
    return signal_date


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
    record = read_latest_evaluation(ledger_dir, model_version_id=model_id)
    if record is None:
        return None
    signal = record.get("signal")
    if not isinstance(signal, dict):
        raise RankerProvisionalMtmError("latest governed signal payload is missing")
    signal_date = str(signal.get("signal_date") or record.get("signal_date") or "")
    if not signal_date:
        raise RankerProvisionalMtmError("latest governed signal date is missing")
    if pd.Timestamp(formal_signal_date) < pd.Timestamp(signal_date) <= pd.Timestamp(cutoff):
        return signal
    return None


def _score_due_target(
    *,
    model_id: str,
    provider_dir: Path,
    formal_package: Path,
    signal_date: str,
    cutoff: str,
    repository_root: Path,
) -> dict[str, Any]:
    empty_ledger = repository_root / "artifacts" / "formal-refresh" / "mtm-empty-ledger" / model_id
    kwargs = {
        "provider_dir": provider_dir,
        "formal_package": formal_package,
        "ledger_dir": empty_ledger,
        "signal_date": signal_date,
        "market_cutoff": f"formal evidence cutoff {cutoff}",
        "repository_root": repository_root,
    }
    if model_id == US_MODEL_ID:
        return score_us_current_target(**kwargs)
    if model_id == CN_MODEL_ID:
        return score_cn_current_target(**kwargs)
    raise RankerProvisionalMtmError(f"unsupported ranker model: {model_id}")


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
    """Replace one ranker's provisional MTM sidecar with the current cutoff view."""

    package = load_object(package_path)
    package.pop("provisional_mtm", None)
    freshness = package.get("freshness")
    if isinstance(freshness, dict):
        freshness.pop("latest_mtm_date", None)
        freshness.pop("performance_observation_status", None)

    model_id = str(package.get("model_id") or "")
    if model_id not in {US_MODEL_ID, CN_MODEL_ID}:
        raise RankerProvisionalMtmError(f"unsupported formal package: {model_id}")
    if str(package.get("evidence_cutoff") or "") != cutoff:
        raise RankerProvisionalMtmError(
            f"{model_id} evidence cutoff does not match MTM cutoff: {package.get('evidence_cutoff')} != {cutoff}"
        )
    report = package.get("report")
    if not isinstance(report, list) or not report:
        raise RankerProvisionalMtmError(f"{model_id} formal report is empty")

    settled_signal = _last_settled_signal_date(package)
    calendar = _calendar(provider_dir)
    signal = _latest_governed_signal(
        model_id=model_id,
        formal_signal_date=settled_signal,
        cutoff=cutoff,
        ledger_dir=ledger_dir,
    )
    if signal is None:
        due = next_due_session(anchor=settled_signal, sessions=calendar)
        if due is None or pd.Timestamp(due) > pd.Timestamp(cutoff):
            write_object(package_path, package)
            return None
        signal = _score_due_target(
            model_id=model_id,
            provider_dir=provider_dir,
            formal_package=package_path,
            signal_date=due,
            cutoff=cutoff,
            repository_root=repository_root,
        )

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
        "date": signal_date,
        "holding_end_date": cutoff,
        "account_before": account_before,
        "account": account,
        benchmark_field: benchmark_nav,
        f"{benchmark_field}_before": benchmark_before,
        "gross_return": gross_return,
        "period_return": net_return,
        "benchmark_return": benchmark_return,
        "excess_return": net_return - benchmark_return,
        "turnover": float(signal.get("turnover_units") or 0.0),
        "transaction_cost": transaction_cost,
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
        "source": "governed_current_target",
        "performance_row": mtm_row,
        "research_only": True,
        "trade_ready": False,
    }
    if isinstance(freshness, dict):
        freshness["latest_mtm_date"] = cutoff
        freshness["performance_observation_status"] = "provisional_mtm"
    write_object(package_path, package)
    return package["provisional_mtm"]