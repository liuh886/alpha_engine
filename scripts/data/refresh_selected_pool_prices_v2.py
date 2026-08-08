"""Run selected-pool refresh with source-aware provider governance.

This wrapper preserves the atomic refresh implementation from v1 while adding
credential-aware providers, upstream-family lineage and promotion gates.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from scripts.data.refresh_selected_pool_prices import refresh_selected_pool_prices
from src.data.adapters.akshare_adapter import AkShareAdapter
from src.data.adapters.akshare_sina_adapter import AkShareSinaAdapter
from src.data.adapters.baostock_adapter import BaoStockAdapter
from src.data.adapters.base import MarketDataAdapter
from src.data.adapters.efinance_adapter import EFinanceAdapter
from src.data.adapters.tiingo_adapter import TiingoAdapter
from src.data.adapters.tushare_adapter import TushareAdapter
from src.data.adapters.yfinance_adapter import YFinanceAdapter
from src.data.provider_catalog import (
    independent_provider_names,
    provider_manifest_entry,
)
from src.data.router import MarketDataRouter

MANIFEST_RELATIVE_PATH = Path(
    "artifacts/selected_pool_price_refresh_manifest.json"
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def build_hardened_router(market: str) -> MarketDataRouter:
    market_key = str(market or "").strip().lower()
    adapters: list[MarketDataAdapter] = []
    providers: list[str] = []
    if market_key == "cn":
        token = os.getenv("TUSHARE_TOKEN", "").strip()
        if token:
            adapters.append(TushareAdapter(token=token))
            providers.append("tushare")
        adapters.extend(
            [
                AkShareSinaAdapter(),
                AkShareAdapter(),
                BaoStockAdapter(),
                EFinanceAdapter(),
                YFinanceAdapter(),
            ]
        )
        providers.extend(
            [
                "akshare_sina",
                "akshare",
                "baostock",
                "efinance",
                "yfinance",
            ]
        )
    elif market_key == "us":
        token = os.getenv("TIINGO_API_TOKEN", "").strip()
        if token:
            adapters.append(TiingoAdapter(token=token))
            providers.append("tiingo")
        adapters.append(YFinanceAdapter())
        providers.append("yfinance")
    else:
        raise ValueError(f"unsupported market: {market}")
    # Per-symbol retries in refresh_selected_pool_prices are already bounded by
    # max_rounds. A batch-wide circuit breaker lets failures from one symbol
    # suppress independent provider attempts for every later symbol, so the
    # selected-pool refresh deliberately keeps router health request-local.
    return MarketDataRouter(
        adapters=adapters,
        policy={market_key: providers},
    )


def _decorate_attempt(attempt: dict[str, Any]) -> None:
    provider = str(attempt.get("provider", "")).strip().lower()
    attempt["provider_contract"] = provider_manifest_entry(provider)


def _decorate_manifest(path: Path, router: MarketDataRouter) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    market = str(payload.get("market", "")).strip().lower()
    provider_order = router.providers_for_market(market)
    selected_providers: dict[str, str] = {}
    quarantined: list[str] = []
    copied_legacy: list[str] = []

    records = payload.get("records", [])
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            attempts = record.get("attempts", [])
            if isinstance(attempts, list):
                for attempt in attempts:
                    if isinstance(attempt, dict):
                        _decorate_attempt(attempt)
            provider = str(record.get("provider", "")).strip().lower()
            symbol = str(record.get("symbol", "")).strip().upper()
            if provider:
                record["provider_contract"] = provider_manifest_entry(provider)
                selected_providers[symbol] = provider
            if market == "cn" and provider == "yfinance":
                record["promotion_status"] = "quarantined_yahoo_only_cn"
                quarantined.append(symbol)
            elif provider:
                record["promotion_status"] = "source_semantics_recorded"
            if record.get("action") == "copied_verified_source":
                record["promotion_status"] = "legacy_source_not_refetched"
                copied_legacy.append(symbol)

    failures = payload.get("failures", [])
    if isinstance(failures, list):
        for failure in failures:
            if not isinstance(failure, dict):
                continue
            attempts = failure.get("attempts", [])
            if isinstance(attempts, list):
                for attempt in attempts:
                    if (
                        isinstance(attempt, dict)
                        and "provider_contract" not in attempt
                    ):
                        _decorate_attempt(attempt)

    payload["provider_architecture"] = {
        "schema_version": "1.2",
        "selection_mode": "credential_aware_fallback",
        "provider_order": provider_order,
        "independent_provider_order": independent_provider_names(provider_order),
        "providers": {
            provider: provider_manifest_entry(provider) for provider in provider_order
        },
        "same_source_warning": (
            "akshare and efinance share source_family=eastmoney and do not count "
            "as independent corroboration"
        ),
        "public_source_boundary": (
            "akshare_sina is independent from eastmoney but is throttled and may "
            "be temporarily IP-blocked; credentialed tushare remains preferred"
        ),
        "health": router.provider_health_snapshot(),
    }
    payload["selected_providers"] = selected_providers
    payload["quarantined_symbols"] = sorted(set(quarantined))
    payload["legacy_copied_symbols"] = sorted(set(copied_legacy))
    payload["promotion_eligible"] = bool(
        payload.get("status") == "selected_pool_price_refresh_ready"
        and not quarantined
        and not copied_legacy
    )
    if quarantined:
        payload["promotion_blocker"] = "CN symbols rely on Yahoo-only adjusted data"
    elif copied_legacy:
        payload["promotion_blocker"] = (
            "repair-only build contains legacy sources without provider-semantic refresh"
        )
    elif payload.get("status") != "selected_pool_price_refresh_ready":
        payload["promotion_blocker"] = "selected-pool refresh is not complete"
    else:
        payload["promotion_blocker"] = None
    _write_json(path, payload)
    return payload


def refresh_selected_pool_prices_v2(
    *,
    root: str | Path,
    market: str,
    source_csv_dir: str | Path,
    output_root: str | Path,
    start: str,
    cutoff: str,
    max_rounds: int = 2,
    full_refresh: bool = False,
    router: MarketDataRouter | None = None,
) -> dict[str, Any]:
    destination = Path(output_root).resolve()
    data_router = router or build_hardened_router(market)
    try:
        refresh_selected_pool_prices(
            root=root,
            market=market,
            source_csv_dir=source_csv_dir,
            output_root=destination,
            start=start,
            cutoff=cutoff,
            router=data_router,
            max_rounds=max_rounds,
            full_refresh=full_refresh,
        )
    except Exception:
        manifest_path = destination / MANIFEST_RELATIVE_PATH
        if manifest_path.is_file():
            _decorate_manifest(manifest_path, data_router)
        raise
    return _decorate_manifest(destination / MANIFEST_RELATIVE_PATH, data_router)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--market", choices=("cn", "us"), required=True)
    parser.add_argument(
        "--source-csv-dir", type=Path, default=Path("data/csv_clean")
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--cutoff", default="2026-06-18")
    parser.add_argument("--max-rounds", type=int, default=2)
    parser.add_argument("--full-refresh", action="store_true")
    args = parser.parse_args()

    result = refresh_selected_pool_prices_v2(
        root=args.root,
        market=args.market,
        source_csv_dir=args.source_csv_dir,
        output_root=args.output_root,
        start=args.start,
        cutoff=args.cutoff,
        max_rounds=args.max_rounds,
        full_refresh=args.full_refresh,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
