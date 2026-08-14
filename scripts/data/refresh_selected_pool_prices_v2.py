"""Run selected-pool refresh with source-aware provider governance.

This wrapper preserves the atomic refresh implementation from v1 while adding
credential-aware providers, upstream-family lineage and promotion gates.
HTTP-level retries stay inside each provider adapter; ``max_rounds`` bounds
symbol-level fallback without leaking failure state across the selected pool.
Provider-normalization rules, including bounded adjusted-OHLC reconciliation,
are part of this same selected-pool evidence contract.
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
FORMAL_MARKET_AUXILIARIES: dict[str, tuple[str, ...]] = {
    # TIGO is the current governed US87 identity. TYGO is a distinct security
    # retained only because accepted US x1.1 history actually traded it; it is
    # published separately rather than being rewritten or substituted as TIGO.
    "us": ("QQQI", "TQQQ", "SGOV", "TYGO"),
    "cn": ("515180",),
}
COMPARISON_REFERENCE_AUXILIARIES: dict[str, tuple[str, ...]] = {
    "us": ("CGDV",),
    "cn": (),
}


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
        # The selected US pool is bulk research evidence. The credentialed
        # Tiingo quota is intentionally reserved for the separate governed
        # QQQ/QQQI/TQQQ executable-ETF reference bundle, where professional
        # dual-source reconciliation is a hard contract.
        adapters.append(YFinanceAdapter())
        providers.append("yfinance")
    else:
        raise ValueError(f"unsupported market: {market}")
    return MarketDataRouter(
        adapters=adapters,
        policy={market_key: providers},
    )


def _decorate_attempt(attempt: dict[str, Any]) -> None:
    provider = str(attempt.get("provider", "")).strip().lower()
    attempt["provider_contract"] = provider_manifest_entry(provider)


def _governed_formal_auxiliary_yahoo_fallback(
    record: dict[str, Any],
    *,
    market: str,
    provider_order: list[str],
) -> bool:
    """Allow Yahoo only as a proven last-resort source for formal auxiliaries.

    CN selected-pool members remain fail-closed on Yahoo-only evidence. A formal
    auxiliary is different: it exists to publish evidence for an already accepted
    traded instrument, not to train or promote the CN ranker. The fallback is
    acceptable only when every configured provider ahead of Yahoo was attempted
    and failed in the same full refresh and Yahoo itself succeeded. Adapter-level
    schema and OHLC reconciliation still run before this manifest is produced.
    """

    symbol = str(record.get("symbol", "")).strip().upper()
    if (
        market != "cn"
        or symbol not in FORMAL_MARKET_AUXILIARIES.get(market, ())
        or str(record.get("provider", "")).strip().lower() != "yfinance"
        or record.get("action") != "fetched_full_refresh"
    ):
        return False

    try:
        yahoo_index = provider_order.index("yfinance")
    except ValueError:
        return False
    preferred = provider_order[:yahoo_index]
    attempts = record.get("attempts", [])
    if not isinstance(attempts, list):
        return False

    normalized = [attempt for attempt in attempts if isinstance(attempt, dict)]
    yahoo_succeeded = any(
        str(attempt.get("provider", "")).strip().lower() == "yfinance"
        and attempt.get("ok") is True
        for attempt in normalized
    )
    if not yahoo_succeeded:
        return False

    for provider in preferred:
        provider_attempts = [
            attempt
            for attempt in normalized
            if str(attempt.get("provider", "")).strip().lower() == provider
        ]
        if not provider_attempts or any(
            attempt.get("ok") is not False for attempt in provider_attempts
        ):
            return False
    return True


def _decorate_manifest(path: Path, router: MarketDataRouter) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    market = str(payload.get("market", "")).strip().lower()
    comparison_references = {
        str(value).strip().upper()
        for value in COMPARISON_REFERENCE_AUXILIARIES.get(market, ())
        if str(value).strip()
    }
    payload["comparison_reference_symbols"] = sorted(comparison_references)
    auxiliaries = payload.get("auxiliary_symbols", [])
    if isinstance(auxiliaries, list):
        payload["auxiliary_symbols"] = [
            value
            for value in auxiliaries
            if str(value).strip().upper() not in comparison_references
        ]
    provider_order = router.providers_for_market(market)
    selected_providers: dict[str, str] = {}
    quarantined: list[str] = []
    governed_auxiliary_fallbacks: list[str] = []
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
                if _governed_formal_auxiliary_yahoo_fallback(
                    record,
                    market=market,
                    provider_order=provider_order,
                ):
                    record["promotion_status"] = (
                        "formal_auxiliary_governed_yahoo_fallback"
                    )
                    governed_auxiliary_fallbacks.append(symbol)
                else:
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
            if market == "cn"
            else (
                "The US selected pool is bulk research evidence from Yahoo; "
                "credentialed Tiingo is reserved for the separately governed "
                "QQQ/QQQI/TQQQ professional reference bundle."
            )
        ),
        "formal_auxiliary_boundary": (
            "CN selected-pool members remain quarantined on Yahoo-only evidence. "
            "An explicitly declared formal auxiliary may use Yahoo only after "
            "every configured preferred provider was attempted and failed in the "
            "same full refresh; adapter validation and normalization remain required."
        ),
        "health": router.provider_health_snapshot(),
    }
    payload["selected_providers"] = selected_providers
    payload["quarantined_symbols"] = sorted(set(quarantined))
    payload["formal_auxiliary_fallback_symbols"] = sorted(
        set(governed_auxiliary_fallbacks)
    )
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
    auxiliary_symbols: list[str] | tuple[str, ...] | None = None,
    router: MarketDataRouter | None = None,
) -> dict[str, Any]:
    destination = Path(output_root).resolve()
    data_router = router or build_hardened_router(market)
    requested_auxiliaries = auxiliary_symbols
    if requested_auxiliaries is None and full_refresh:
        market_key = str(market).lower()
        requested_auxiliaries = (
            *FORMAL_MARKET_AUXILIARIES.get(market_key, ()),
            *COMPARISON_REFERENCE_AUXILIARIES.get(market_key, ()),
        )
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
            auxiliary_symbols=requested_auxiliaries,
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
    parser.add_argument(
        "--auxiliary-symbol",
        action="append",
        default=None,
        help=(
            "Additional formal/reference security. On --full-refresh, the current "
            "governed auxiliary and comparison-reference set is used when omitted."
        ),
    )
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
        auxiliary_symbols=args.auxiliary_symbol,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()