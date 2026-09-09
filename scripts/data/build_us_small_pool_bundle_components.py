"""Translate narrow-pool evidence into model-data-bundle components.

The US 23-name pool travels a strategy-specific data path (snapshot bars +
SEC companyfacts), not the selected-pool refresh pipeline, so no
bundle-shaped component manifest exists for it. This script projects the two
governed coverage reports into bundle components without restating them:

- prices.us_small_pool_v2 from the snapshot coverage report (bars present
  through cutoff for every candidate -> ready);
- fundamentals.us_small_pool_v2 from the SEC coverage report (factor-ready
  symbols -> ready, the rest -> missing with the SEC report as the reason
  record; status partial by construction).

Both manifests bind their source shas. Nothing here invents coverage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pool_candidates(pool_path: Path) -> list[str]:
    pool = yaml.safe_load(pool_path.read_text(encoding="utf-8"))
    symbols: list[str] = []
    for basket in (pool.get("baskets") or {}).values():
        symbols.extend(str(value).strip().upper() for value in basket.get("symbols", []))
    return symbols


def build_price_component(
    *, candidates: list[str], coverage_path: Path, cutoff: str
) -> dict[str, Any]:
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    rows = {
        str(row.get("canonical_symbol", "")).strip().upper(): row
        for row in coverage.get("rows", [])
        if isinstance(row, dict)
    }
    ready = [
        symbol
        for symbol in candidates
        if symbol in rows and str(rows[symbol].get("latest_date", "")) >= cutoff
    ]
    missing = [symbol for symbol in candidates if symbol not in ready]
    first_dates = [
        str(rows[symbol].get("first_date", "")) for symbol in ready if rows[symbol].get("first_date")
    ]
    last_dates = [
        str(rows[symbol].get("latest_date", "")) for symbol in ready if rows[symbol].get("latest_date")
    ]
    return {
        "schema_version": "1.0",
        "evidence_type": "us_small_pool_price_coverage_v1",
        "component_id": "prices.us_small_pool_v2",
        "market": "us",
        "pool_id": "us_small_pool_v2",
        "candidate_count": len(candidates),
        "expected_symbol_count": len(candidates),
        "ready_symbol_count": len(ready),
        "ready_symbols": sorted(ready),
        "missing_symbols": sorted(missing),
        "invalid_symbols": [],
        "quarantined_symbols": [],
        "coverage_ratio": (len(ready) / len(candidates)) if candidates else 0.0,
        "evidence_cutoff": min(last_dates) if last_dates else cutoff,
        "first_date": max(first_dates) if first_dates else None,
        "last_date": min(last_dates) if last_dates else None,
        "status": "ready" if not missing and ready else "partial",
        "providers": ["yfinance"],
        "source_coverage_path": coverage_path.as_posix(),
        "source_coverage_sha256": _sha256_file(coverage_path),
        "research_only": True,
        "trade_ready": False,
    }


def build_fundamental_component(
    *, candidates: list[str], coverage_path: Path, cutoff: str
) -> dict[str, Any]:
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    ready_flags = {
        str(row.get("symbol", "")).strip().upper(): bool(row.get("factor_ready"))
        for row in coverage.get("rows", [])
        if isinstance(row, dict)
    }
    ready = [symbol for symbol in candidates if ready_flags.get(symbol, False)]
    missing = [symbol for symbol in candidates if symbol not in ready]
    return {
        "schema_version": "1.0",
        "evidence_type": "us_small_pool_fundamental_coverage_v1",
        "component_id": "fundamentals.us_small_pool_v2",
        "market": "us",
        "pool_id": "us_small_pool_v2",
        "candidate_count": len(candidates),
        "expected_symbol_count": len(candidates),
        "ready_symbol_count": len(ready),
        "ready_symbols": sorted(ready),
        "missing_symbols": sorted(missing),
        "invalid_symbols": [],
        "quarantined_symbols": [],
        "coverage_ratio": (len(ready) / len(candidates)) if candidates else 0.0,
        "evidence_cutoff": cutoff,
        "status": "partial" if ready else "not_provided",
        "providers": ["sec_edgar_companyfacts"],
        "source_coverage_path": coverage_path.as_posix(),
        "source_coverage_sha256": _sha256_file(coverage_path),
        "research_only": True,
        "trade_ready": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pool", type=Path, default=Path("configs/pools/us_small_pool_v2.yaml")
    )
    parser.add_argument(
        "--price-coverage",
        type=Path,
        default=Path(
            "artifacts/market_snapshots/us_small_pool_v2/2026-09-08/coverage_report.json"
        ),
    )
    parser.add_argument(
        "--fundamental-coverage",
        type=Path,
        default=Path(
            "artifacts/evidence/sec_companyfacts_fundamentals_v2/coverage_report.json"
        ),
    )
    parser.add_argument("--evidence-cutoff", default="2026-09-08")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/data/model_data_bundle_v1/components"),
    )
    args = parser.parse_args()
    candidates = _pool_candidates(args.pool.resolve())
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    prices = build_price_component(
        candidates=candidates,
        coverage_path=args.price_coverage.resolve(),
        cutoff=args.evidence_cutoff,
    )
    fundamentals = build_fundamental_component(
        candidates=candidates,
        coverage_path=args.fundamental_coverage.resolve(),
        cutoff=args.evidence_cutoff,
    )
    price_path = output_dir / "us-small-pool-prices.json"
    fundamental_path = output_dir / "us-small-pool-fundamentals.json"
    # LF on all platforms so component hashes match Linux CI.
    for target, payload in ((price_path, prices), (fundamental_path, fundamentals)):
        with target.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "prices": {
                    "path": str(price_path),
                    "status": prices["status"],
                    "coverage_ratio": prices["coverage_ratio"],
                },
                "fundamentals": {
                    "path": str(fundamental_path),
                    "status": fundamentals["status"],
                    "coverage_ratio": fundamentals["coverage_ratio"],
                    "missing_symbols": fundamentals["missing_symbols"],
                },
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
