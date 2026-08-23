"""Independent raw selected-pool refresh fixtures for publication tests."""

from __future__ import annotations

import copy
from typing import Any


def _provider_contract(name: str) -> dict[str, Any]:
    families = {
        "akshare_sina": ("sina_finance", "sina_finance", "qfq_adjusted", "CNY"),
        "akshare": ("eastmoney", "eastmoney", "qfq_adjusted", "CNY"),
        "baostock": ("baostock", "baostock", "raw_unadjusted", "CNY"),
        "efinance": ("eastmoney", "eastmoney", "qfq_adjusted", "CNY"),
        "tencent_qfq_history": (
            "tencent_finance",
            "tencent_finance",
            "qfq_adjusted",
            "synthetic_adjusted_close_times_volume",
        ),
        "yfinance": (
            "yahoo_finance",
            "yahoo_finance",
            "provider_adjusted",
            "synthetic_close_times_volume",
        ),
    }
    source_family, independent_group, price_mode, amount_unit = families[name]
    return {
        "amount_unit": amount_unit,
        "available": True,
        "corporate_actions": name == "yfinance",
        "credential_env": None,
        "credentialed": False,
        "independent_group": independent_group,
        "markets": ["cn", "hk", "us"] if name == "yfinance" else ["cn"],
        "name": name,
        "price_mode": price_mode,
        "research_only": True,
        "source_family": source_family,
        "trade_calendar": False,
        "usage_note": f"fixture contract for {name}",
        "volume_unit": "provider_reported" if name == "tencent_qfq_history" else "shares",
    }


def _attempt(provider: str, *, ok: bool, provider_symbol: str) -> dict[str, Any]:
    return {
        "error": None if ok else f"transient {provider} fixture failure",
        "ok": ok,
        "provider": provider,
        "provider_contract": _provider_contract(provider),
        "provider_symbol": provider_symbol,
        "round": 1,
        "rows": 2 if ok else 0,
        "schema_errors": [],
    }


def _record(symbol: str, provider: str, provider_symbol: str, attempts: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "action": "fetched_incremental_update",
        "attempts": attempts,
        "first_date": "2021-01-04",
        "identity_contract": None,
        "last_date": "2026-08-21",
        "output_sha256": (symbol.lower().encode().hex() + "1" * 64)[:64],
        "promotion_status": "source_semantics_recorded",
        "provider": provider,
        "provider_contract": _provider_contract(provider),
        "provider_symbol": provider_symbol,
        "rows": 1366,
        "symbol": symbol,
    }


def selected_pool_price_source(market: str = "cn") -> dict[str, Any]:
    """Return a fresh raw schema-1.2 manifest independent of repository outputs."""

    if market == "cn":
        provider_order = [
            "akshare_sina", "akshare", "baostock", "efinance",
            "tencent_qfq_history", "yfinance",
        ]
        records = [
            _record("000001", "akshare_sina", "sz000001", [
                _attempt("akshare_sina", ok=True, provider_symbol="sz000001")
            ]),
            _record("515180", "tencent_qfq_history", "sh515180", [
                _attempt("akshare_sina", ok=False, provider_symbol="sh515180"),
                _attempt("akshare", ok=False, provider_symbol="515180"),
                _attempt("baostock", ok=False, provider_symbol="sh.515180"),
                _attempt("efinance", ok=False, provider_symbol="515180"),
                _attempt("tencent_qfq_history", ok=True, provider_symbol="sh515180"),
            ]),
        ]
        candidate_symbols = ["000001"]
        auxiliary_symbols = ["515180"]
        benchmark = "000001"
        selected = {"000001": "akshare_sina", "515180": "tencent_qfq_history"}
        lifecycle: list[str] = []
        terminal_evidence: dict[str, Any] = {}
        terminal_history: list[str] = []
        stale: list[str] = []
    elif market == "us":
        provider_order = ["yfinance"]
        records = [
            _record("AAA", "yfinance", "AAA", [
                _attempt("yfinance", ok=True, provider_symbol="AAA")
            ]),
            {
                "action": "retained_governed_terminal_history",
                "attempts": [],
                "first_date": "2021-01-04",
                "last_date": "2026-08-04",
                "output_sha256": "e" * 64,
                "promotion_status": "governed_terminal_history",
                "rows": 1402,
                "source_path": "data/csv_clean/EA.csv",
                "source_sha256": "d" * 64,
                "symbol": "EA",
                "terminal_lifecycle": {
                    "active_universe_after_terminal_date_allowed": False,
                    "event_type": "acquisition_take_private_delisting",
                    "governed_history_path": "data/csv_clean/EA.csv",
                    "governed_history_sha256": "d" * 64,
                    "historical_rows_retained": True,
                    "market": "us",
                    "public_references": ["https://example.test/sec", "https://example.test/nasdaq"],
                    "reason": "fixture take-private completed",
                    "suspension_effective_date": "2026-08-05",
                    "terminal_date": "2026-08-04",
                },
            },
        ]
        candidate_symbols = ["AAA", "EA"]
        auxiliary_symbols = []
        benchmark = "AAA"
        selected = {"AAA": "yfinance"}
        lifecycle = ["EA"]
        terminal_evidence = {
            "EA": {
                "event_type": "acquisition_take_private_delisting",
                "reason": "fixture take-private completed",
                "terminal_date": "2026-08-04",
            }
        }
        terminal_history = ["EA"]
        stale = ["EA"]
    else:
        raise ValueError(f"unsupported fixture market: {market}")

    providers = {name: _provider_contract(name) for name in provider_order}
    return {
        "after": {},
        "all_sources_current": not stale,
        "all_sources_ready": True,
        "auxiliary_symbols": auxiliary_symbols,
        "before": {},
        "benchmark": benchmark,
        "candidate_count": len(candidate_symbols),
        "candidate_symbols": candidate_symbols,
        "comparison_reference_symbols": [],
        "cutoff": "2026-08-21",
        "evidence_type": "selected_pool_price_refresh_v1",
        "failed_symbols": [],
        "failure_count": 0,
        "formal_auxiliary_fallback_symbols": [],
        "identity_contracts": {},
        "legacy_copied_symbols": [],
        "lifecycle_declared_terminal_symbols": lifecycle,
        "market": market,
        "pool_id": "cn_selected_equities_v3" if market == "cn" else "us_selected_equities_v2",
        "promotion_blocker": None,
        "promotion_eligible": True,
        "provider_architecture": {
            "formal_auxiliary_boundary": "fixture governed fallback",
            "health": {"fixture": "runtime-only"},
            "independent_provider_order": provider_order,
            "provider_order": provider_order,
            "providers": copy.deepcopy(providers),
            "public_source_boundary": "fixture research boundary",
            "same_source_warning": "fixture only",
            "schema_version": "1.2",
            "selection_mode": "credential_aware_fallback",
        },
        "provider_identity_sha256": "b" * 64,
        "quarantined_symbols": [],
        "records": records,
        "refresh_mode": "incremental",
        "research_only": True,
        "schema_version": "1.2",
        "selected_providers": selected,
        "stale_symbols": stale,
        "start": "2021-01-01",
        "status": "selected_pool_price_refresh_ready",
        "target_count": len(records),
        "targets": [record["symbol"] for record in records],
        "terminal_history_symbols": terminal_history,
        "terminal_listing_evidence": terminal_evidence,
        "trade_ready": False,
        "unresolved_stale_symbols": [],
    }
