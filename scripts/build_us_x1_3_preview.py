"""Build and catalog the governed US x1.3 research-preview bundle.

Historical evidence may be recomputed here, but live forward state is owned by
the append-only strategy signal ledger. A preview may only project a current
target after the exact decision has already been sealed there.
"""

from __future__ import annotations

import argparse
import json
import math
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from src.artifacts.model_run_exporter import (
    RunExportPlan,
    SectionPlan,
    export_model_run,
    update_catalog,
)
from src.artifacts.strategy_signal_ledger import read_latest_evaluation
from src.artifacts.us_x1_3_preview import build_plan
from src.data.market_provider import load_provider_manifest
from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime

MODEL_ID = "us_x1_3"
HOLDING_SESSIONS = 10


class USX13ForwardProjectionError(ValueError):
    """Raised when preview live state diverges from the canonical forward ledger."""


def _mapping(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise USX13ForwardProjectionError("expected mapping payload")
    return deepcopy(dict(value))


def _section_payloads(plan: RunExportPlan) -> dict[str, Any]:
    return {
        section.section_id: deepcopy(section.payload)
        for section in plan.sections
        if section.availability_status == "available"
    }


def _replace_payloads(plan: RunExportPlan, payloads: Mapping[str, Any]) -> RunExportPlan:
    sections: list[SectionPlan] = []
    for section in plan.sections:
        if section.availability_status == "available" and section.section_id in payloads:
            sections.append(replace(section, payload=payloads[section.section_id]))
        else:
            sections.append(section)
    return replace(plan, sections=tuple(sections))


def _is_prospective(row: object) -> bool:
    return isinstance(row, Mapping) and row.get("window_role") == "prospective_unrealized"


def _is_provisional_mtm(row: object) -> bool:
    return isinstance(row, Mapping) and (
        row.get("provisional_mtm") is True
        or row.get("settlement_status") == "provisional_mtm"
    )


def _strip_unsealed_forward_state(plan: RunExportPlan) -> RunExportPlan:
    """Return settled historical evidence only when no newer ledger decision exists."""

    payloads = _section_payloads(plan)

    performance = _mapping(payloads["performance"])
    raw_report = performance.get("report")
    if not isinstance(raw_report, list):
        raise USX13ForwardProjectionError("US x1.3 performance report is missing")
    report = [deepcopy(row) for row in raw_report if not _is_provisional_mtm(row)]
    if not report:
        raise USX13ForwardProjectionError("US x1.3 settled performance report is empty")
    performance["report"] = report
    date_range = _mapping(performance.get("date_range"))
    last = report[-1]
    if not isinstance(last, Mapping):
        raise USX13ForwardProjectionError("US x1.3 final settled performance row is invalid")
    date_range["end"] = str(last.get("holding_end_date") or last.get("date") or "")
    performance["date_range"] = date_range
    payloads["performance"] = performance

    portfolio = _mapping(payloads["portfolio"])
    positions = portfolio.get("positions")
    signals = portfolio.get("signals")
    if not isinstance(positions, list) or not isinstance(signals, list):
        raise USX13ForwardProjectionError("US x1.3 portfolio evidence is incomplete")
    portfolio["positions"] = [deepcopy(row) for row in positions if not _is_prospective(row)]
    portfolio["signals"] = [deepcopy(row) for row in signals if not _is_prospective(row)]
    latest_realized = portfolio.get("latest_realized_signal")
    if not isinstance(latest_realized, Mapping):
        raise USX13ForwardProjectionError("US x1.3 latest realized signal is missing")
    portfolio["latest_signal"] = deepcopy(dict(latest_realized))
    payloads["portfolio"] = portfolio

    trades = _mapping(payloads["trades"])
    records = trades.get("records")
    if not isinstance(records, list):
        raise USX13ForwardProjectionError("US x1.3 trade records are missing")
    settled_records = [deepcopy(row) for row in records if not _is_prospective(row)]
    trades["records"] = settled_records
    analytics = trades.get("analytics")
    if isinstance(analytics, Mapping):
        analytics = deepcopy(dict(analytics))
        analytics["rebalance_event_count"] = len(settled_records)
        analytics["normalized_notional"] = sum(
            abs(float(row.get("weight_delta") or 0.0))
            for row in settled_records
            if isinstance(row, Mapping)
        )
        trades["analytics"] = analytics
    payloads["trades"] = trades

    summary = _mapping(payloads["summary"])
    latest_realized_summary = summary.get("latest_realized_signal")
    if not isinstance(latest_realized_summary, Mapping):
        raise USX13ForwardProjectionError("US x1.3 summary latest realized signal is missing")
    summary["latest_signal"] = deepcopy(dict(latest_realized_summary))
    if isinstance(trades.get("analytics"), Mapping):
        summary["trade_analytics"] = deepcopy(dict(trades["analytics"]))
    payloads["summary"] = summary

    return _replace_payloads(plan, payloads)


def _weights(value: object, *, label: str) -> dict[str, float]:
    if not isinstance(value, Mapping) or not value:
        raise USX13ForwardProjectionError(f"{label} weights are missing")
    result = {str(key): float(weight) for key, weight in value.items()}
    if not math.isclose(sum(result.values()), 1.0, rel_tol=0.0, abs_tol=1e-6):
        raise USX13ForwardProjectionError(f"{label} weights do not sum to one")
    return dict(sorted(result.items()))


def _same_weights(left: Mapping[str, float], right: Mapping[str, float]) -> bool:
    return set(left) == set(right) and all(
        math.isclose(left[key], right[key], rel_tol=0.0, abs_tol=1e-12)
        for key in left
    )


def _assert_ledger_projection(plan: RunExportPlan, signal: Mapping[str, Any]) -> RunExportPlan:
    payloads = _section_payloads(plan)
    portfolio = _mapping(payloads["portfolio"])
    latest = portfolio.get("latest_signal")
    if not isinstance(latest, Mapping) or latest.get("window_role") != "prospective_unrealized":
        raise USX13ForwardProjectionError(
            "sealed US x1.3 forward decision is missing from preview projection"
        )

    ledger_date = str(signal.get("signal_date") or "")
    preview_date = str(latest.get("signal_date") or "")
    if not ledger_date or preview_date != ledger_date:
        raise USX13ForwardProjectionError(
            f"US x1.3 preview/ledger signal date mismatch: preview={preview_date} ledger={ledger_date}"
        )

    preview_weights = _weights(latest.get("target_weights"), label="preview")
    ledger_weights = _weights(signal.get("target_weights"), label="ledger")
    if not _same_weights(preview_weights, ledger_weights):
        raise USX13ForwardProjectionError("US x1.3 preview target differs from sealed ledger target")

    preview_turnover = float(latest.get("turnover") or 0.0)
    ledger_turnover = float(signal.get("turnover_units") or 0.0)
    if not math.isclose(preview_turnover, ledger_turnover, rel_tol=0.0, abs_tol=1e-12):
        raise USX13ForwardProjectionError(
            "US x1.3 preview turnover differs from sealed ledger turnover"
        )

    performance = _mapping(payloads["performance"])
    report = performance.get("report")
    if not isinstance(report, list):
        raise USX13ForwardProjectionError("US x1.3 performance report is missing")
    mtm_rows = [row for row in report if _is_provisional_mtm(row)]
    if len(mtm_rows) != 1 or str(mtm_rows[0].get("signal_date") or "") != ledger_date:
        raise USX13ForwardProjectionError(
            "US x1.3 provisional MTM must bind exactly one sealed ledger signal"
        )
    return plan


def _latest_ledger_signal(root: Path) -> Mapping[str, Any] | None:
    ledger_dir = root / "data" / "research" / "strategy_signal_ledgers" / MODEL_ID
    record = read_latest_evaluation(ledger_dir, model_version_id=MODEL_ID)
    if record is None:
        return None
    signal = record.get("signal")
    if not isinstance(signal, Mapping):
        raise USX13ForwardProjectionError("US x1.3 canonical ledger signal is missing")
    return signal


def _unsettled_forward_signal(
    root: Path,
    provider_dir: Path,
) -> Mapping[str, Any] | None:
    """Return the canonical signal only while its 10-session holding is still open."""

    signal = _latest_ledger_signal(root)
    if signal is None:
        return None
    signal_date = str(signal.get("signal_date") or "")
    if not signal_date:
        raise USX13ForwardProjectionError("US x1.3 canonical ledger signal date is missing")
    provider = load_provider_manifest(
        provider_dir,
        expected_market="us",
        required=True,
        verify_files=True,
    )
    if provider is None:
        raise USX13ForwardProjectionError("US provider manifest is unavailable")
    cutoff = str(provider["calendar"]["last_day"])
    if signal_date > cutoff:
        raise USX13ForwardProjectionError(
            f"US x1.3 ledger signal exceeds provider cutoff: {signal_date} > {cutoff}"
        )
    runtime = QlibUSExecutionRuntime(provider_uri=provider_dir)
    runtime.initialize(root)
    sessions = pd.DatetimeIndex(runtime.calendar(signal_date, cutoff)).normalize().unique()
    signal_ts = pd.Timestamp(signal_date).normalize()
    matches = [index for index, value in enumerate(sessions) if value == signal_ts]
    if len(matches) != 1:
        raise USX13ForwardProjectionError(
            f"US x1.3 ledger signal is absent from provider calendar: {signal_date}"
        )
    return signal if len(sessions) <= HOLDING_SESSIONS else None


def project_forward_state(plan: RunExportPlan, root: Path) -> RunExportPlan:
    """Publish live US x1.3 state only when the signal ledger already owns it."""

    summary = _mapping(_section_payloads(plan)["summary"])
    latest_realized = summary.get("latest_realized_signal")
    if not isinstance(latest_realized, Mapping):
        raise USX13ForwardProjectionError("US x1.3 latest realized signal is missing")
    realized_date = str(latest_realized.get("signal_date") or "")
    if not realized_date:
        raise USX13ForwardProjectionError("US x1.3 latest realized signal date is missing")

    signal = _latest_ledger_signal(root)
    if signal is None:
        return _strip_unsealed_forward_state(plan)
    ledger_date = str(signal.get("signal_date") or "")
    if not ledger_date:
        raise USX13ForwardProjectionError("US x1.3 canonical ledger signal date is missing")
    if ledger_date <= realized_date:
        return _strip_unsealed_forward_state(plan)
    if ledger_date > plan.evidence_cutoff:
        raise USX13ForwardProjectionError(
            f"US x1.3 ledger signal exceeds preview cutoff: {ledger_date} > {plan.evidence_cutoff}"
        )
    return _assert_ledger_projection(plan, signal)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-dir", type=Path, required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/research/model_runs"),
    )
    args = parser.parse_args()
    root = args.root.resolve()
    provider_dir = args.provider_dir.resolve()
    forward_signal = _unsettled_forward_signal(root, provider_dir)
    plan = build_plan(
        root,
        provider_dir=provider_dir,
        generated_at=args.generated_at,
        forward_signal=forward_signal,
    )
    plan = project_forward_state(plan, root)
    manifest = export_model_run(plan, output_root=args.output_root)
    catalog = update_catalog(
        [manifest],
        catalog_path=args.output_root / "catalog.json",
        channel="preview",
    )
    print(json.dumps(catalog, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
