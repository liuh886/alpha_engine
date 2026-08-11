#!/usr/bin/env python3
"""Resolve and build the governed formal US x1.2 current target."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from src.data.adapters.base import FetchRequest
from src.data.adapters.yfinance_adapter import YFinanceAdapter
from src.research.ranker_current_target import (
    load_previous_state,
    merge_governed_market_sessions,
    next_due_session,
)
from src.research.us_x1_2_current_target import MODEL_ID, score_us_x1_2_current_target

ROOT = Path(__file__).resolve().parents[1]
FORMAL_FAMILY = "us_ranker"
BENCHMARK = "QQQ"


class USX12CurrentTargetCommandError(ValueError):
    """Raised when the active formal US x1.2 bundle cannot be resolved exactly."""


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise USX12CurrentTargetCommandError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def resolve_formal_bundle(formal_root: Path) -> tuple[Path, Path]:
    """Resolve the single accepted formal US x1.2 manifest and portfolio section."""

    formal_root = formal_root.resolve()
    catalog = _read(formal_root / "catalog.json")
    records = [
        row
        for row in catalog.get("records", [])
        if isinstance(row, dict)
        and row.get("model_family_id") == FORMAL_FAMILY
        and row.get("model_version_id") == MODEL_ID
        and row.get("publication_status") == "accepted_formal_baseline"
    ]
    if len(records) != 1:
        raise USX12CurrentTargetCommandError(
            f"expected one accepted formal {MODEL_ID} record, found {len(records)}"
        )
    record = records[0]
    manifest = formal_root / str(record.get("manifest_path") or "")
    if not manifest.is_file() or _sha256(manifest) != record.get("manifest_sha256"):
        raise USX12CurrentTargetCommandError("US x1.2 formal manifest identity mismatch")
    payload = _read(manifest)
    if (
        payload.get("publication_channel") != "formal"
        or payload.get("publication_status") != "accepted_formal_baseline"
        or payload.get("bundle_id") != record.get("bundle_id")
        or payload.get("research_only") is not True
        or payload.get("trade_ready") is not False
    ):
        raise USX12CurrentTargetCommandError("US x1.2 formal publication boundary changed")
    portfolio_rows = [
        row
        for row in payload.get("sections", [])
        if isinstance(row, dict) and row.get("section_id") == "portfolio"
    ]
    if len(portfolio_rows) != 1 or portfolio_rows[0].get("availability_status") != "available":
        raise USX12CurrentTargetCommandError("US x1.2 formal portfolio section is unavailable")
    section = portfolio_rows[0]
    portfolio = manifest.parent / str(section.get("path") or "")
    if (
        not portfolio.is_file()
        or _sha256(portfolio) != section.get("sha256")
        or portfolio.stat().st_size != section.get("byte_size")
    ):
        raise USX12CurrentTargetCommandError("US x1.2 formal portfolio identity mismatch")
    return manifest, portfolio


def _due(args: argparse.Namespace) -> int:
    _, portfolio = resolve_formal_bundle(args.formal_root)
    anchor, _ = load_previous_state(
        formal_package=portfolio,
        ledger_dir=args.ledger_dir,
    )
    bars = (
        YFinanceAdapter()
        .fetch_daily_bars(
            FetchRequest(
                symbol=BENCHMARK,
                market="us",
                start=anchor,
                end=args.as_of,
            )
        )
        .df
    )
    live_sessions = pd.DatetimeIndex(pd.to_datetime(bars["date"]))
    evidence_path = (
        ROOT
        / "data"
        / "research"
        / "market_evidence"
        / "us"
        / "symbols"
        / f"{BENCHMARK}.json"
    )
    sessions = merge_governed_market_sessions(
        evidence_path=evidence_path,
        live_sessions=live_sessions,
        as_of=args.as_of,
    )
    due = next_due_session(anchor=anchor, sessions=sessions)
    payload = {
        "market": "us",
        "model_version_id": MODEL_ID,
        "anchor": anchor,
        "as_of": args.as_of,
        "due": due is not None,
        "signal_date": due,
        "calendar_provider": "governed_market_evidence_plus_yfinance_increment",
        "research_only": True,
        "trade_ready": False,
    }
    _write(args.output, payload)
    print(json.dumps(payload, sort_keys=True))
    return 0


def _build(args: argparse.Namespace) -> int:
    manifest, portfolio = resolve_formal_bundle(args.formal_root)
    signal = score_us_x1_2_current_target(
        provider_dir=args.provider_dir,
        formal_manifest=manifest,
        formal_portfolio=portfolio,
        ledger_dir=args.ledger_dir,
        signal_date=args.signal_date,
        market_cutoff=args.market_cutoff,
        repository_root=ROOT,
    )
    _write(args.output, signal)
    print(json.dumps(signal, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    due = subparsers.add_parser("due")
    due.add_argument(
        "--formal-root",
        type=Path,
        default=Path("data/research/formal_model_runs"),
    )
    due.add_argument(
        "--ledger-dir",
        type=Path,
        default=Path("data/research/strategy_signal_ledgers/us_x1_2"),
    )
    due.add_argument("--as-of", required=True)
    due.add_argument("--output", type=Path, required=True)
    due.set_defaults(func=_due)

    build = subparsers.add_parser("build")
    build.add_argument(
        "--formal-root",
        type=Path,
        default=Path("data/research/formal_model_runs"),
    )
    build.add_argument(
        "--ledger-dir",
        type=Path,
        default=Path("data/research/strategy_signal_ledgers/us_x1_2"),
    )
    build.add_argument("--provider-dir", type=Path, required=True)
    build.add_argument("--signal-date", required=True)
    build.add_argument("--market-cutoff", required=True)
    build.add_argument("--output", type=Path, required=True)
    build.set_defaults(func=_build)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
