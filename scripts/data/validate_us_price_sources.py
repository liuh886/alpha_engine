#!/usr/bin/env python3
"""Run a bounded one-symbol comparison without producing canonical training data."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from src.data.adapters.base import FetchRequest
from src.data.adapters.polygon_adapter import PolygonAdapter
from src.data.adapters.polygon_adapter import _bars, _metadata
from src.data.adapters.tiingo_adapter import TiingoAdapter
from src.data.adapters.yfinance_adapter import YFinanceAdapter
from src.data.etf_reference_bundle import reconcile_adjusted_bars


def probe_polygon_vwap(*, end: str, adapter: PolygonAdapter | None = None, request_interval_seconds: float = 0) -> dict[str, Any]:
    """Bounded diagnostic only; never changes source roles or emits training bars."""
    adapter = adapter or PolygonAdapter()
    client = adapter.client
    if client is not None and request_interval_seconds > 0:
        class PacedClient:
            last_request = 0.0

            def get_json(self, path: str, *, params: dict[str, str] | None = None) -> Any:
                time.sleep(max(0, request_interval_seconds - (time.monotonic() - self.last_request)))
                self.last_request = time.monotonic()
                assert client is not None
                return client.get_json(path, params=params)

        adapter.client = PacedClient()
    rows: list[dict[str, Any]] = []
    for symbol in ("AAPL", "MSFT", "NVDA", "ABBNY", "SBGSY"):
        for start, cutoff in (("2021-01-01", "2021-01-31"), ("2026-01-01", end)):
            row: dict[str, Any] = {"symbol": symbol, "start": start, "cutoff": cutoff}
            try:
                result = adapter.fetch_daily_bars(FetchRequest(symbol=symbol, market="us", start=start, end=cutoff))
                row.update(ok=True, rows=len(result.df), first_date=result.df["date"].min().date().isoformat(), last_date=result.df["date"].max().date().isoformat())
            except Exception as exc:
                row.update(ok=False, error_class=getattr(exc, "error_class", type(exc).__name__), status_code=getattr(exc, "status_code", None), error=str(exc))
                # Distinguish an adjusted-price mismatch from a raw aggregate mismatch.
                # No raw response or bar values are retained in this diagnostic.
                if "OHLC envelope" in str(exc) and adapter.client is not None:
                    try:
                        _metadata(adapter.client.get_json(f"v3/reference/tickers/{symbol}"), symbol)
                        payload = adapter.client.get_json(
                            f"v2/aggs/ticker/{symbol}/range/1/day/{start}/{cutoff}",
                            params={"adjusted": "false", "sort": "asc", "limit": "50000"},
                        )
                        if isinstance(payload, dict) and payload.get("next_url"):
                            raise ValueError("probe response requires pagination")
                        frame = _bars(payload, symbol=symbol)
                        row["raw_aggregate_check"] = {"ok": True, "rows": len(frame)}
                    except Exception as raw_exc:
                        row["raw_aggregate_check"] = {"ok": False, "error_class": type(raw_exc).__name__}
            rows.append(row)
    return {"schema_version": "1.0", "purpose": "bounded_vwap_source_feasibility", "provider": "polygon", "observations": rows, "eligible_for_training": False, "writes_canonical_data": False, "research_only": True, "trade_ready": False}


def _attempt(adapter: Any, request: FetchRequest) -> tuple[Any | None, dict[str, Any]]:
    if getattr(adapter, "client", True) is None:
        return None, {"ok": False, "error_class": "provider_not_configured"}
    try:
        result = adapter.fetch_daily_bars(request)
        return result.df, {
            "ok": True,
            "provider": result.provider,
            "provider_symbol": result.provider_symbol,
            "rows": int(len(result.df)),
        }
    except Exception as exc:
        return None, {
            "ok": False,
            "error_class": str(getattr(exc, "error_class", "data_fetch_error")),
            "status_code": getattr(exc, "status_code", None),
            "error": f"{type(exc).__name__}: {exc}",
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--start", default="2026-07-01")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-validator", choices=["polygon", "tiingo"], default=None)
    parser.add_argument("--probe-vwap", action="store_true", help="Probe five fixed symbols and two fixed history windows using Polygon only")
    args = parser.parse_args()
    if args.probe_vwap:
        payload = probe_polygon_vwap(end=args.end, request_interval_seconds=13)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0  # Successful diagnostic capture is not source qualification.

    request = FetchRequest(
        symbol=args.symbol,
        market="us",
        start=args.start,
        end=args.end,
    )
    canonical, canonical_attempt = _attempt(YFinanceAdapter(), request)
    validators: dict[str, dict[str, Any]] = {}
    reconciliations: dict[str, dict[str, Any]] = {}
    for name, adapter in (
        ("polygon", PolygonAdapter()),
        ("tiingo", TiingoAdapter()),
    ):
        frame, attempt = _attempt(adapter, request)
        validators[name] = attempt
        if canonical is not None and frame is not None:
            reconciliations[name] = reconcile_adjusted_bars(
                canonical,
                frame,
                symbol=args.symbol,
                settings={
                    "minimum_overlap_sessions": 10,
                    "consensus_p99_adjusted_close_return_diff": 0.003,
                    "consensus_max_adjusted_close_return_diff": 0.02,
                    "consensus_p99_adjusted_open_return_diff": 0.005,
                    "consensus_max_adjusted_open_return_diff": 0.02,
                    "consensus_max_annual_compounded_open_return_drift": 0.01,
                    "consensus_max_full_period_compounded_open_return_drift": 0.01,
                    "material_return_difference": 0.02,
                    "corporate_action_window_sessions": 1,
                },
            )
        else:
            reconciliations[name] = {
                "status": "provider_missing",
                "canonical_present": canonical is not None,
                "validator_present": frame is not None,
            }
    payload = {
        "schema_version": "1.0",
        "purpose": "validation_only_smoke_test",
        "symbol": args.symbol,
        "start": args.start,
        "end": args.end,
        "canonical_provider": "yfinance",
        "canonical_attempt": canonical_attempt,
        "validators": validators,
        "reconciliations": reconciliations,
        "eligible_for_training": False,
        "writes_canonical_data": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, indent=2, sort_keys=True))
    if not canonical_attempt.get("ok"):
        return 2
    if args.require_validator and not validators[args.require_validator].get("ok"):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
