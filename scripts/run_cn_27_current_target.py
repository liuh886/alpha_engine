#!/usr/bin/env python3
"""Resolve and build the current target for the CN_27 V1.3 allocation model.

Dormant by frozen contract until a governed prospective source exists. Both
subcommands exit 0 with a ``data_blocked`` receipt while the source is absent;
only genuinely invalid evidence exits nonzero.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.artifacts.formal_bundle_reader import FormalBundleReadError, load_formal_run
from src.governance.active_strategy_catalog import load_active_strategy_catalog
from src.governance.strategy_runtime_capabilities import (
    load_active_strategy_runtime_capabilities,
)
from src.research.cn_27_current_target import (
    ADAPTER_ID,
    CN27CurrentTargetError,
    MODEL_ID,
    REBALANCE_SESSIONS,
    prospective_source_status,
    score_cn_27_current_target,
)
from src.research.market_session_clock import completed_market_date
from src.research.ranker_current_target import load_previous_state, next_due_session
from scripts.run_ranker_current_target import _resolve_market_sessions

ROOT = Path(__file__).resolve().parents[1]
STRATEGY_ID = "cn_27"
BENCHMARK = "000300"


class CN27CurrentTargetCommandError(ValueError):
    """Raised when the CN_27 current-target command cannot run exactly."""


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _strategy():
    active = load_active_strategy_catalog()
    strategy = active.by_strategy_id.get(STRATEGY_ID)
    if strategy is None or strategy.model_version_id != MODEL_ID:
        raise CN27CurrentTargetCommandError("active CN_27 strategy identity changed")
    capability = load_active_strategy_runtime_capabilities(active=active)[
        STRATEGY_ID
    ].current_target
    if capability.adapter_id != ADAPTER_ID:
        raise CN27CurrentTargetCommandError(
            capability.reason or "CN_27 current-target adapter is not maintained"
        )
    return strategy, capability


def _blocked_receipt(*, signal_date: str | None, reason: str) -> dict[str, Any]:
    return {
        "model_version_id": MODEL_ID,
        "adapter_id": ADAPTER_ID,
        "decision": "data_blocked",
        "signal_date": signal_date,
        "reason": reason,
        "research_only": True,
        "trade_ready": False,
    }


def _due(args: argparse.Namespace) -> int:
    strategy, capability = _strategy()
    if capability.status != "available":
        payload = {
            "strategy_id": STRATEGY_ID,
            "model_version_id": MODEL_ID,
            "due": False,
            "signal_date": None,
            "status": capability.status,
            "reason": capability.reason,
            "research_only": True,
            "trade_ready": False,
        }
        _write(args.output, payload)
        print(json.dumps(payload, sort_keys=True))
        return 0
    ledger_dir = Path(strategy.signal_ledger)
    formal_dir = Path(args.formal_root).resolve()
    try:
        relative_root = formal_dir.relative_to(ROOT)
    except ValueError as exc:
        raise CN27CurrentTargetCommandError(
            f"CN_27 formal root escapes repository: {formal_dir}"
        ) from exc
    try:
        active = load_formal_run(ROOT, MODEL_ID, relative_root=relative_root)
    except FormalBundleReadError as exc:
        raise CN27CurrentTargetCommandError(
            f"CN_27 active formal run is unreadable: {exc}"
        ) from exc
    portfolio_file = active.manifest_path.parent / "portfolio.json"
    if not portfolio_file.is_file():
        raise CN27CurrentTargetCommandError("CN_27 sealed portfolio file is missing")
    anchor, _ = load_previous_state(
        formal_package=portfolio_file, ledger_dir=ledger_dir
    )
    completed_as_of = completed_market_date("cn", args.as_of)
    sessions, _ = _resolve_market_sessions(
        evidence_path=args.evidence_path,
        market="cn",
        benchmark=BENCHMARK,
        as_of=completed_as_of,
    )
    due = next_due_session(anchor=anchor, sessions=sessions, cadence=REBALANCE_SESSIONS)
    payload = {
        "strategy_id": STRATEGY_ID,
        "model_version_id": MODEL_ID,
        "anchor": anchor,
        "requested_as_of": args.as_of,
        "as_of": completed_as_of,
        "due": due is not None,
        "signal_date": due,
        "cadence_sessions": REBALANCE_SESSIONS,
        "research_only": True,
        "trade_ready": False,
    }
    _write(args.output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


def _build(args: argparse.Namespace) -> int:
    strategy, _ = _strategy()
    try:
        signal = score_cn_27_current_target(
            formal_root=args.formal_root,
            ledger_dir=Path(strategy.signal_ledger),
            signal_date=args.signal_date,
            market_cutoff=args.market_cutoff,
            repository_root=ROOT,
        )
    except CN27CurrentTargetError as exc:
        if exc.status != "data_blocked":
            raise
        receipt = _blocked_receipt(signal_date=args.signal_date, reason=str(exc))
        _write(args.output, receipt)
        print(json.dumps(receipt, sort_keys=True))
        return 0
    if signal.get("model_version_id") != MODEL_ID:
        raise CN27CurrentTargetCommandError("current-target adapter changed model identity")
    _write(args.output, signal)
    print(json.dumps(signal, sort_keys=True))
    return 0


def _status(args: argparse.Namespace) -> int:
    _strategy()
    payload = prospective_source_status(
        formal_root=args.formal_root, repository_root=ROOT
    )
    _write(args.output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    status = subparsers.add_parser("status")
    status.add_argument(
        "--formal-root",
        type=Path,
        default=Path("data/research/formal_model_runs"),
    )
    status.add_argument("--output", type=Path, required=True)
    status.set_defaults(func=_status)

    due = subparsers.add_parser("due")
    due.add_argument(
        "--formal-root",
        type=Path,
        default=Path("data/research/formal_model_runs"),
    )
    due.add_argument("--evidence-path", type=Path, required=True)
    due.add_argument("--as-of", required=True)
    due.add_argument("--output", type=Path, required=True)
    due.set_defaults(func=_due)

    build = subparsers.add_parser("build")
    build.add_argument(
        "--formal-root",
        type=Path,
        default=Path("data/research/formal_model_runs"),
    )
    build.add_argument("--signal-date", required=True)
    build.add_argument("--market-cutoff", required=True)
    build.add_argument("--output", type=Path, required=True)
    build.set_defaults(func=_build)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
