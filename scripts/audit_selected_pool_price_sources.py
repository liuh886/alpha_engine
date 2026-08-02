"""Audit committed price CSVs for an exact selected model pool."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.data.validation.schema import validate_market_data
from src.research.selected_pool_guard import resolve_selected_pool

REGISTRY = Path("configs/pools/selected_pool_registry_v1.yaml")
BENCHMARKS = {"us": "QQQ", "cn": "000300"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pool_symbols(path: Path) -> list[str]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("selected-pool contract must be a mapping")
    symbols = [str(item).strip().upper() for item in payload.get("symbols", [])]
    expected = int(payload.get("candidate_count", 0))
    if expected <= 0 or len(symbols) != expected or len(set(symbols)) != expected:
        raise ValueError("selected-pool identity is not exact")
    return symbols


def _audit_file(path: Path, symbol: str) -> dict[str, Any]:
    if not path.is_file():
        return {
            "symbol": symbol,
            "status": "missing",
            "path": str(path),
            "errors": ["source CSV is missing"],
        }
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        return {
            "symbol": symbol,
            "status": "invalid",
            "path": str(path),
            "errors": [f"read failed: {type(exc).__name__}: {exc}"],
        }
    if "date" not in frame.columns:
        return {
            "symbol": symbol,
            "status": "invalid",
            "path": str(path),
            "errors": ["required date column is missing"],
        }
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    errors: list[str] = []
    if frame["date"].isna().any():
        errors.append("unparseable dates")
    if frame["date"].duplicated().any():
        errors.append("duplicate dates")
    ok, _, schema_errors = validate_market_data(frame, symbol)
    if not ok:
        errors.extend(str(error) for error in schema_errors)
    valid_dates = frame["date"].dropna()
    return {
        "symbol": symbol,
        "status": "ready" if not errors else "invalid",
        "path": str(path),
        "sha256": _sha256(path),
        "row_count": int(len(frame)),
        "first_date": (
            valid_dates.min().date().isoformat() if not valid_dates.empty else None
        ),
        "last_date": (
            valid_dates.max().date().isoformat() if not valid_dates.empty else None
        ),
        "errors": errors,
    }


def audit(
    root: Path,
    *,
    market: str,
    csv_dir: Path = Path("data/csv_clean"),
) -> dict[str, Any]:
    normalized_root = root.resolve()
    market_key = market.lower()
    binding = resolve_selected_pool(
        market_key,
        registry_path=normalized_root / REGISTRY,
        authoritative=True,
        require_data_ready=False,
    )
    candidates = _pool_symbols(binding.pool_spec)
    benchmark = BENCHMARKS[market_key]
    source_dir = csv_dir if csv_dir.is_absolute() else normalized_root / csv_dir

    candidate_rows = [
        _audit_file(source_dir / f"{symbol}.csv", symbol)
        for symbol in candidates
    ]
    benchmark_row = _audit_file(source_dir / f"{benchmark}.csv", benchmark)
    missing = [row["symbol"] for row in candidate_rows if row["status"] == "missing"]
    invalid = [row["symbol"] for row in candidate_rows if row["status"] == "invalid"]
    ready = [row["symbol"] for row in candidate_rows if row["status"] == "ready"]
    all_ready = not missing and not invalid and benchmark_row["status"] == "ready"
    return {
        "schema_version": "1.0",
        "market": market_key,
        "pool_id": binding.pool_id,
        "candidate_count": len(candidates),
        "ready_candidate_count": len(ready),
        "missing_candidate_count": len(missing),
        "invalid_candidate_count": len(invalid),
        "missing_candidates": missing,
        "invalid_candidates": invalid,
        "benchmark": benchmark_row,
        "all_sources_ready": all_ready,
        "decision": (
            "selected_pool_price_sources_ready"
            if all_ready
            else "selected_pool_price_sources_blocked"
        ),
        "research_only": True,
        "trade_ready": False,
        "candidates": candidate_rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--market", choices=("us", "cn"), required=True)
    parser.add_argument("--csv-dir", type=Path, default=Path("data/csv_clean"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = audit(
        args.root,
        market=args.market,
        csv_dir=args.csv_dir,
    )
    output = args.output
    if not output.is_absolute():
        output = args.root.resolve() / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
