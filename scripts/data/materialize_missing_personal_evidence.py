"""Script to supplement missing market evidence for personal portfolio holdings.

Fetches authoritative historical OHLCV data up to cutoff 2026-10-26 using YFinanceAdapter,
computes standard bars and chart studies (boll20, macd_12_26_9, rsi14),
and writes canonical JSON evidence files to data/research/market_evidence/us/symbols/
while updating data/research/market_evidence/us/catalog.json.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.dashboard.market_evidence import (
    _bars,
    _canonical_json,
    _chart_studies,
    _write_json,
)
from src.data.adapters.base import FetchRequest
from src.data.adapters.yfinance_adapter import YFinanceAdapter

SYMBOLS_TO_SUPPLEMENT: dict[str, str] = {
    "PL": "Planet Labs PBC",
    "SOXL": "Direxion Daily Semiconductor Bull 3X Shares",
    "SPCX": "Space Exploration Technologies Corp.",
    "IQQ": "iShares Nasdaq 100 ETF",
}


def materialize_supplemented_evidence(root: Path | None = None) -> dict[str, Any]:
    repo_root = (root or Path.cwd()).resolve()
    us_evidence_dir = repo_root / "data/research/market_evidence/us"
    symbols_dir = us_evidence_dir / "symbols"
    catalog_path = us_evidence_dir / "catalog.json"

    if not catalog_path.is_file():
        raise RuntimeError(f"Catalog not found: {catalog_path}")

    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    provider_manifest_sha = catalog.get("provider_manifest_sha256", "")

    existing_catalog_symbols = {
        s["symbol"]: s for s in catalog.get("symbols", []) if isinstance(s, dict)
    }

    adapter = YFinanceAdapter()
    materialized: list[dict[str, Any]] = []

    for sym, name in SYMBOLS_TO_SUPPLEMENT.items():
        print(f"Fetching {sym} ({name})...")
        req = FetchRequest(
            symbol=sym,
            market="us",
            start="2021-01-01",
            end="2026-10-26",
        )
        res = adapter.fetch_daily_bars(req)
        df = res.df

        bars = _bars(df)
        chart_studies = _chart_studies(df)

        csv_bytes = df.to_csv(index=False).encode("utf-8")
        source_csv_sha = hashlib.sha256(csv_bytes).hexdigest()

        start_date = bars[0]["time"]
        cutoff_date = bars[-1]["time"]

        payload = {
            "schema_version": "1.1",
            "evidence_type": "security_market_evidence",
            "market": "us",
            "instrument_id": f"us:{sym}",
            "provider_symbol": sym,
            "symbol": sym,
            "source_instruments": [],
            "roles": ["comparison_reference"],
            "name": name,
            "start": start_date,
            "cutoff": cutoff_date,
            "source_csv_sha256": source_csv_sha,
            "provider_manifest_sha256": provider_manifest_sha,
            "bars": bars,
            "chart_studies": chart_studies,
            "formal_model_events": [],
            "factor_series": {},
            "factor_series_scope": {
                "factor_ids": [],
                "group": "momentum_volatility_volume",
                "materialization_rule": "published_for_every_market_evidence_security",
            },
            "research_only": True,
            "trade_ready": False,
        }

        target_path = symbols_dir / f"{sym}.json"
        payload_sha = _write_json(target_path, payload)

        cat_entry = {
            "cutoff": cutoff_date,
            "factor_series_available": False,
            "formal_event_count": 0,
            "instrument_id": f"us:{sym}",
            "name": name,
            "path": f"symbols/{sym}.json",
            "provider_symbol": sym,
            "roles": ["comparison_reference"],
            "sha256": payload_sha,
            "source_instruments": [],
            "start": start_date,
            "symbol": sym,
        }

        existing_catalog_symbols[sym] = cat_entry
        materialized.append({
            "symbol": sym,
            "name": name,
            "bars_count": len(bars),
            "start": start_date,
            "cutoff": cutoff_date,
            "sha256": payload_sha,
        })
        print(f"  -> Wrote {sym}.json: {len(bars)} bars ({start_date} ~ {cutoff_date})")

    # Update catalog
    updated_symbols = sorted(existing_catalog_symbols.values(), key=lambda x: str(x["symbol"]))
    catalog["symbols"] = updated_symbols
    catalog["symbol_count"] = len(updated_symbols)

    catalog_encoded = _canonical_json(catalog)
    catalog_path.write_bytes(catalog_encoded)
    print(f"Updated {catalog_path}: total symbols = {len(updated_symbols)}")

    return {
        "status": "success",
        "supplemented_count": len(materialized),
        "total_catalog_symbols": len(updated_symbols),
        "details": materialized,
    }


if __name__ == "__main__":
    result = materialize_supplemented_evidence()
    print(json.dumps(result, indent=2, ensure_ascii=False))
