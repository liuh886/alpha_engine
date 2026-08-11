"""Bind US x1.2 native Bundle v2 performance to the provider evidence cutoff."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

import math
import pandas as pd

from src.artifacts.model_run_exporter import RunExportPlan, SectionPlan
from src.research.qlib_execution_common import normalize_qlib_frame_index
from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime


class USX12MtmError(ValueError):
    """Raised when a current US x1.2 MTM observation cannot be proven."""


def _section(plan: RunExportPlan, section_id: str) -> tuple[int, dict[str, Any]]:
    for index, section in enumerate(plan.sections):
        if section.section_id != section_id:
            continue
        if section.availability_status != "available" or not isinstance(section.payload, Mapping):
            raise USX12MtmError(f"US x1.2 {section_id} section is unavailable")
        return index, dict(section.payload)
    raise USX12MtmError(f"US x1.2 {section_id} section is missing")


def _replace_section(
    sections: list[SectionPlan],
    index: int,
    payload: Mapping[str, Any],
) -> None:
    sections[index] = replace(sections[index], payload=dict(payload))


def _close_panel(
    runtime: QlibUSExecutionRuntime,
    instruments: list[str],
    start: str,
    end: str,
) -> pd.DataFrame:
    frame = normalize_qlib_frame_index(runtime.features(instruments, ["$close"], start, end))
    frame.columns = ["close"]
    return frame.sort_index()


def _close(panel: pd.DataFrame, date: str, instrument: str) -> float:
    timestamp = pd.Timestamp(date)
    for candidate in (instrument, instrument.lower(), instrument.upper()):
        try:
            value = float(panel.loc[(timestamp, candidate), "close"])
        except KeyError:
            continue
        if math.isfinite(value) and value > 0.0:
            return value
    raise USX12MtmError(f"missing governed close for {instrument} on {date}")


def _target(signal: Mapping[str, Any]) -> dict[str, float]:
    raw = signal.get("target_weights")
    if not isinstance(raw, Mapping) or not raw:
        raise USX12MtmError("US x1.2 current signal has no target weights")
    target = {str(instrument): float(weight) for instrument, weight in raw.items()}
    if len(target) != 15 or not math.isclose(sum(target.values()), 1.0, abs_tol=1e-9):
        raise USX12MtmError("US x1.2 current target is incomplete")
    return dict(sorted(target.items()))


def _weighted_return(
    panel: pd.DataFrame,
    target: Mapping[str, float],
    start: str,
    end: str,
) -> float:
    return float(
        sum(
            weight * (_close(panel, end, instrument) / _close(panel, start, instrument) - 1.0)
            for instrument, weight in target.items()
        )
    )


def bind_us_x1_2_evidence_cutoff_mtm(
    plan: RunExportPlan,
    *,
    root: Path,
    provider_dir: Path,
    publication_builder: Path,
) -> RunExportPlan:
    """Append one replaceable cutoff MTM observation to native US x1.2 evidence."""

    if plan.model_version_id != "us_x1_2":
        raise USX12MtmError(f"unsupported native MTM model: {plan.model_version_id}")

    sections = list(plan.sections)
    summary_index, summary = _section(plan, "summary")
    performance_index, performance = _section(plan, "performance")
    portfolio_index, portfolio = _section(plan, "portfolio")
    lineage_index, lineage = _section(plan, "lineage")

    report_raw = performance.get("report")
    if not isinstance(report_raw, list) or not report_raw:
        raise USX12MtmError("US x1.2 performance report is empty")
    report = [dict(row) for row in report_raw if isinstance(row, Mapping)]
    if len(report) != len(report_raw):
        raise USX12MtmError("US x1.2 performance report contains an invalid row")

    settled_end = str(report[-1].get("holding_end_date") or "")
    cutoff = str(plan.evidence_cutoff)
    if not settled_end or pd.Timestamp(settled_end) > pd.Timestamp(cutoff):
        raise USX12MtmError(
            f"US x1.2 settled performance exceeds evidence cutoff: {settled_end}/{cutoff}"
        )

    semantics = dict(performance.get("performance_semantics") or {})
    semantics["performance_date_field"] = "holding_end_date"
    semantics["observation_policy"] = "settled_10_session_plus_single_cutoff_mtm"
    performance["performance_semantics"] = semantics

    summary["settled_performance_end"] = settled_end
    summary["performance_observation_end"] = settled_end
    summary["performance_observation_status"] = "settled"

    if pd.Timestamp(settled_end) < pd.Timestamp(cutoff):
        latest_signal = portfolio.get("latest_signal")
        if not isinstance(latest_signal, Mapping):
            raise USX12MtmError("US x1.2 latest signal is missing while performance is stale")
        if latest_signal.get("signal_state") != "prospective_unrealized":
            raise USX12MtmError("US x1.2 has no prospective target for the unsettled interval")
        signal_date = str(latest_signal.get("signal_date") or "")
        if not signal_date or pd.Timestamp(signal_date) > pd.Timestamp(cutoff):
            raise USX12MtmError(f"invalid US x1.2 current signal date: {signal_date}")
        if pd.Timestamp(signal_date) < pd.Timestamp(settled_end):
            raise USX12MtmError(
                f"US x1.2 current signal predates settled performance: {signal_date}/{settled_end}"
            )

        target = _target(latest_signal)
        runtime = QlibUSExecutionRuntime(provider_uri=provider_dir.resolve())
        runtime.initialize(root.resolve())
        panel = _close_panel(runtime, [*target, "QQQ"], signal_date, cutoff)
        gross_return = _weighted_return(panel, target, signal_date, cutoff)
        benchmark_return = _weighted_return(panel, {"QQQ": 1.0}, signal_date, cutoff)
        turnover = float(latest_signal.get("turnover") or 0.0)
        cost_bps = float(latest_signal.get("cost_bps") or 20.0)
        transaction_cost = turnover * cost_bps / 10_000
        net_return = gross_return - transaction_cost

        previous = report[-1]
        account_before = float(previous["account"])
        benchmark_before = float(previous["bench_qqq"])
        account = account_before * (1.0 + net_return)
        benchmark_account = benchmark_before * (1.0 + benchmark_return)
        prior_peak = max(float(row["account"]) for row in report)
        peak = max(prior_peak, account)
        report.append(
            {
                "date": signal_date,
                "holding_end_date": cutoff,
                "window": "current_target",
                "window_role": "prospective_unrealized",
                "period_index": int(previous.get("period_index", len(report) - 1)) + 1,
                "account_before": account_before,
                "account": account,
                "bench_qqq_before": benchmark_before,
                "bench_qqq": benchmark_account,
                "gross_return": gross_return,
                "period_return": net_return,
                "benchmark_return": benchmark_return,
                "excess_return": net_return - benchmark_return,
                "turnover": turnover,
                "transaction_cost": transaction_cost,
                "drawdown": account / peak - 1.0,
                "trace_frequency": "non_overlapping_10_session",
                "partial_window": True,
                "provisional_mtm": True,
                "settlement_status": "provisional_mtm",
                "mtm_as_of": cutoff,
                "mtm_entry_date": signal_date,
                "research_only": True,
                "trade_ready": False,
            }
        )
        summary["performance_observation_end"] = cutoff
        summary["performance_observation_status"] = "provisional_mtm"

    performance["report"] = report
    date_range = dict(performance.get("date_range") or {})
    date_range["end"] = str(report[-1].get("holding_end_date") or report[-1].get("date"))
    performance["date_range"] = date_range

    lineage["publication_builder_source_sha256"] = hashlib.sha256(
        publication_builder.read_bytes()
    ).hexdigest()
    lineage["cutoff_mtm_source_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

    _replace_section(sections, summary_index, summary)
    _replace_section(sections, performance_index, performance)
    _replace_section(sections, portfolio_index, portfolio)
    _replace_section(sections, lineage_index, lineage)

    comparability_key = dict(plan.comparability_key)
    comparability_key["end"] = date_range["end"]
    return replace(plan, sections=tuple(sections), comparability_key=comparability_key)
