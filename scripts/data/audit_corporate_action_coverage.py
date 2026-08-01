"""Audit normalized corporate-action events against an exact selected pool."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from src.data.corporate_actions import normalize_corporate_action
from src.research.selected_pool_guard import resolve_selected_pool

REGISTRY = Path("configs/pools/selected_pool_registry_v1.yaml")


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML contract must be a mapping: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(
    root: Path,
    *,
    market: str,
    events_path: Path,
) -> dict[str, Any]:
    normalized_root = root.resolve()
    binding = resolve_selected_pool(
        market,
        registry_path=normalized_root / REGISTRY,
        authoritative=True,
        require_data_ready=False,
    )
    pool = _load_yaml(binding.pool_spec)
    symbols = [str(value).upper() for value in pool.get("symbols", [])]
    expected_count = int(pool.get("candidate_count", 0))
    if len(symbols) != expected_count or len(symbols) != len(set(symbols)):
        raise ValueError("selected-pool identity is not exact")

    absolute_events = events_path
    if not absolute_events.is_absolute():
        absolute_events = normalized_root / absolute_events
    if not absolute_events.is_file():
        raise FileNotFoundError(f"corporate-action event file not found: {absolute_events}")

    coverage: dict[str, dict[str, Any]] = {
        symbol: {
            "status": "no_event_observed",
            "event_count": 0,
            "event_types": {},
            "conflict_count": 0,
            "first_effective_date": None,
            "latest_effective_date": None,
        }
        for symbol in symbols
    }
    seen: set[str] = set()
    event_count = 0
    with absolute_events.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on line {line_number}") from exc
            if not isinstance(raw, dict):
                raise ValueError(f"event on line {line_number} must be an object")
            event = normalize_corporate_action(raw)
            if event.market != market:
                raise ValueError(f"event market mismatch on line {line_number}")
            if event.symbol not in coverage:
                raise ValueError(
                    f"event symbol is outside selected pool on line {line_number}: "
                    f"{event.symbol}"
                )
            if event.event_id in seen:
                raise ValueError(f"duplicate event_id on line {line_number}")
            seen.add(event.event_id)

            row = coverage[event.symbol]
            row["status"] = "events_present"
            row["event_count"] += 1
            row["event_types"][event.event_type] = (
                row["event_types"].get(event.event_type, 0) + 1
            )
            if event.reconciliation_status == "conflict":
                row["conflict_count"] += 1
            first = row["first_effective_date"]
            latest = row["latest_effective_date"]
            if first is None or event.effective_date < first:
                row["first_effective_date"] = event.effective_date
            if latest is None or event.effective_date > latest:
                row["latest_effective_date"] = event.effective_date
            event_count += 1

    for row in coverage.values():
        row["event_types"] = dict(sorted(row["event_types"].items()))
        if row["conflict_count"]:
            row["status"] = "conflict"

    symbols_with_events = sum(
        1 for row in coverage.values() if row["event_count"] > 0
    )
    conflict_symbols = sorted(
        symbol for symbol, row in coverage.items() if row["conflict_count"] > 0
    )
    return {
        "schema_version": "1.0",
        "contract_id": "corporate_action_store_v1",
        "market": market,
        "pool_id": binding.pool_id,
        "candidate_count": expected_count,
        "reported_candidate_count": len(coverage),
        "complete_candidate_enumeration": len(coverage) == expected_count,
        "symbols_with_events": symbols_with_events,
        "symbols_without_events": expected_count - symbols_with_events,
        "conflict_symbols": conflict_symbols,
        "event_count": event_count,
        "events_path": str(absolute_events),
        "events_sha256": _sha256(absolute_events),
        "research_only": True,
        "trade_ready": False,
        "coverage": coverage,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--market", choices=("us", "cn"), required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = audit(args.root, market=args.market, events_path=args.events)
    output = args.output
    if not output.is_absolute():
        output = args.root.resolve() / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(output)


if __name__ == "__main__":
    main()
