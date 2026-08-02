"""Fail closed when completed fixed-horizon window evidence drops backtest traces."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


class WindowTraceRetentionError(ValueError):
    """Raised when window evidence cannot support a future Repository Run."""


def _read(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WindowTraceRetentionError(f"invalid JSON evidence: {path}") from exc
    if not isinstance(payload, dict):
        raise WindowTraceRetentionError(f"JSON evidence root must be an object: {path}")
    return payload


def check_window_trace_retention(root: Path) -> dict[str, Any]:
    root = root.resolve()
    checked: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.json")):
        payload = _read(path)
        report = payload.get("comparison_report")
        if not isinstance(report, dict):
            continue
        candidates = report.get("candidates")
        if not isinstance(candidates, list):
            continue
        traces = payload.get("backtest_traces")
        if not isinstance(traces, list):
            raise WindowTraceRetentionError(f"backtest_traces missing: {path}")
        contract = payload.get("trace_contract") or {}
        if contract.get("daily_nav_claim") is not False:
            raise WindowTraceRetentionError(f"trace contract must reject daily NAV claim: {path}")

        available = {
            (str(trace.get("candidate_name") or ""), str(trace.get("orientation") or "")): trace
            for trace in traces
            if isinstance(trace, dict)
        }
        expected: set[tuple[str, str]] = set()
        for candidate in candidates:
            if not isinstance(candidate, dict) or int(candidate.get("n_periods") or 0) <= 0:
                continue
            key = (
                str(candidate.get("candidate_name") or ""),
                str(candidate.get("orientation") or ""),
            )
            expected.add(key)
            trace = available.get(key)
            if trace is None:
                raise WindowTraceRetentionError(f"candidate trace missing {key}: {path}")
            if trace.get("trace_frequency") != "non_overlapping_forward_horizon":
                raise WindowTraceRetentionError(f"invalid trace frequency {key}: {path}")
            if not isinstance(trace.get("points"), list) or not trace["points"]:
                raise WindowTraceRetentionError(f"trace points missing {key}: {path}")
            if not isinstance(trace.get("holdings"), list) or not trace["holdings"]:
                raise WindowTraceRetentionError(f"trace holdings missing {key}: {path}")
            if trace.get("research_only") is not True or trace.get("trade_ready") is not False:
                raise WindowTraceRetentionError(f"invalid trace boundary {key}: {path}")
        if expected != set(available):
            extra = sorted(set(available) - expected)
            raise WindowTraceRetentionError(f"unexpected trace candidates {extra}: {path}")
        checked.append(
            {
                "path": str(path.relative_to(root)),
                "candidate_traces": len(expected),
            }
        )
    if not checked:
        raise WindowTraceRetentionError(f"no completed window evidence found under: {root}")
    return {
        "status": "window_trace_retention_valid",
        "root": str(root),
        "window_files": checked,
        "window_count": len(checked),
        "research_only": True,
        "trade_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    print(json.dumps(check_window_trace_retention(args.root), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
