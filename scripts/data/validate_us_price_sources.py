#!/usr/bin/env python3
"""Run a bounded one-symbol comparison without producing canonical training data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.data.adapters.base import FetchRequest
from src.data.adapters.polygon_adapter import PolygonAdapter
from src.data.adapters.tiingo_adapter import TiingoAdapter
from src.data.adapters.yfinance_adapter import YFinanceAdapter
from src.data.etf_reference_bundle import reconcile_adjusted_bars


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
    args = parser.parse_args()

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
