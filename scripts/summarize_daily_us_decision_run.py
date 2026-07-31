#!/usr/bin/env python3
"""Summarize a governed daily US decision run from local artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_latest(root: Path, filename: str) -> tuple[Path | None, dict[str, Any] | None]:
    candidates = sorted(root.rglob(filename), key=lambda path: str(path))
    for path in reversed(candidates):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return path, payload
    return None, None


def _blockers(coverage: dict[str, Any] | None) -> list[str]:
    if coverage is None:
        return []
    rows = coverage.get("rows")
    if not isinstance(rows, list):
        return []
    output: list[str] = []
    for row in rows:
        if not isinstance(row, dict) or bool(row.get("factor_ready", True)):
            continue
        symbol = str(row.get("symbol", "UNKNOWN"))
        blockers = row.get("blockers")
        if isinstance(blockers, list) and blockers:
            output.append(f"{symbol}: {', '.join(str(item) for item in blockers)}")
        else:
            blocker = row.get("blocker") or "factor readiness incomplete"
            output.append(f"{symbol}: {blocker}")
    return output


def build_summary(*, artifacts_root: Path, exit_code: int) -> str:
    price_path, price_decision = _load_latest(
        artifacts_root / "market_snapshots", "decision.json"
    )
    sec_paths = sorted(
        (artifacts_root / "forward_shadow_runs").rglob("sec_companyfacts/decision.json"),
        key=lambda path: str(path),
    )
    sec_decision = None
    if sec_paths:
        sec_decision = json.loads(sec_paths[-1].read_text(encoding="utf-8"))
    coverage_paths = sorted(
        (artifacts_root / "forward_shadow_runs").rglob(
            "sec_companyfacts/coverage_report.json"
        ),
        key=lambda path: str(path),
    )
    coverage = None
    if coverage_paths:
        coverage = json.loads(coverage_paths[-1].read_text(encoding="utf-8"))
    multifactor_paths = sorted(
        (artifacts_root / "forward_shadow_runs").rglob(
            "low_turnover_multifactor/decision.json"
        ),
        key=lambda path: str(path),
    )
    multifactor = None
    if multifactor_paths:
        multifactor = json.loads(multifactor_paths[-1].read_text(encoding="utf-8"))
    ticket_paths = sorted(
        (artifacts_root / "decision_ledger" / "us").glob("????-??-??.json"),
        key=lambda path: path.name,
    )
    ticket = None
    if ticket_paths:
        ticket = json.loads(ticket_paths[-1].read_text(encoding="utf-8"))
    log_path = artifacts_root / "operations" / "daily_us_decision.log"
    log_tail: list[str] = []
    if log_path.is_file():
        log_tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]

    status = "COMPLETED" if exit_code == 0 and ticket is not None else "BLOCKED"
    lines = [
        f"# Daily US Decision — {status}",
        "",
        f"- Governed process exit code: `{exit_code}`",
        "- Mode: `diagnostic_only`",
        "- Trade ready: `false`",
        "- Automatic order routing: `false`",
    ]
    if price_decision is not None:
        lines.extend(
            [
                f"- Resolved complete session: `{price_decision.get('resolved_as_of_date')}`",
                f"- Price symbols: `{price_decision.get('symbol_count')}`",
                f"- Price rows: `{price_decision.get('row_count')}`",
            ]
        )
    else:
        lines.append("- Price snapshot: `not produced`")
    if sec_decision is not None:
        lines.extend(
            [
                f"- SEC source decision: `{sec_decision.get('decision')}`",
                f"- Fundamental-ready symbols: `{sec_decision.get('factor_ready_count', 0)}` / `{sec_decision.get('candidate_count', 0)}`",
            ]
        )
    else:
        lines.append("- SEC source decision: `not reached`")
    if multifactor is not None:
        diagnostics = multifactor.get("turnover_diagnostics", {})
        lines.extend(
            [
                f"- Multifactor decision: `{multifactor.get('decision')}`",
                f"- Turnover gate: `{diagnostics.get('turnover_gate_passed')}`",
            ]
        )
    else:
        lines.append("- Multifactor decision: `not reached`")
    if ticket is not None:
        lines.extend(
            [
                f"- Ticket date: `{ticket.get('as_of_date')}`",
                f"- Ticket identity: `{ticket.get('ticket_identity_sha256')}`",
                f"- Security rows: `{len(ticket.get('securities', []))}`",
            ]
        )
    else:
        lines.append("- Decision ticket: `not produced`")

    blockers = _blockers(coverage)
    if blockers:
        lines.extend(["", "## Source blockers", ""])
        lines.extend(f"- {item}" for item in blockers)
    if price_path is not None:
        lines.extend(["", f"Price decision artifact: `{price_path}`"])
    if log_tail:
        lines.extend(["", "## Log tail", "", "```text", *log_tail, "```"])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--exit-code", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = build_summary(
        artifacts_root=args.artifacts_root.resolve(),
        exit_code=args.exit_code,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(summary, encoding="utf-8")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
