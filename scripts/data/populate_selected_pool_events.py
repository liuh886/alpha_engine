"""Populate exact selected-pool PIT fundamentals and explicit corporate actions."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.data.corporate_actions.ashare_public_actions import (
    AsharePublicActionClient,
    eastmoney_dividend_to_events,
)
from src.data.corporate_actions.yfinance_events import (
    fetch_yfinance_actions,
    yfinance_actions_to_corporate_actions,
)
from src.data.fundamentals.ashare_public_financials import (
    AsharePublicFinancialClient,
    cninfo_period_disclosures,
    sina_statement_to_events,
)
from src.data.fundamentals.sec_companyfacts import (
    SecCompanyFactsClient,
    companyfacts_to_events,
)
from src.data.exact_frame_cache import (
    load_exact_frame_snapshot,
    write_exact_frame_snapshot,
)
from src.data.model_data_bundle import ComponentSpec, build_model_data_bundle
from src.data.selected_pool_event_population import (
    SymbolPopulation,
    publish_selected_pool_event_bundle,
    verify_selected_pool_event_bundle,
)

STATEMENTS = ("资产负债表", "利润表", "现金流量表")
STATEMENT_CACHE_NAMES = {
    "资产负债表": "balance_sheet",
    "利润表": "income_statement",
    "现金流量表": "cash_flow_statement",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML must be a mapping: {path}")
    return payload


def _symbols(pool: dict[str, Any]) -> list[str]:
    values = [str(value).strip().upper() for value in pool.get("symbols", [])]
    expected = int(pool.get("candidate_count", 0))
    if len(values) != expected or len(set(values)) != expected:
        raise ValueError("selected-pool identity is not exact")
    return values


def _sec_mapping(symbols: list[str], identity_mapping_path: Path) -> dict[str, dict[str, str]]:
    """Load the reviewed SEC identity contract without runtime ticker discovery."""

    payload = _load_yaml(identity_mapping_path)
    if str(payload.get("pool_id", "")) != "us_selected_equities_v2":
        raise ValueError("SEC identity mapping pool_id mismatch")
    rows = payload.get("symbols")
    if not isinstance(rows, dict):
        raise ValueError("SEC identity mapping symbols must be a mapping")
    mapping: dict[str, dict[str, str]] = {}
    for symbol, row in rows.items():
        normalized_symbol = str(symbol).strip().upper()
        if isinstance(row, dict):
            cik = str(row.get("cik", "")).strip()
            title = str(row.get("title", "")).strip()
        else:
            cik = str(row).strip()
            title = ""
        if len(cik) != 10 or not cik.isdigit():
            raise ValueError(f"invalid reviewed CIK for {normalized_symbol}")
        mapping[normalized_symbol] = {
            "cik": cik,
            "title": title,
            "entity_id": f"CIK{cik}",
        }
    expected = set(symbols)
    if not set(mapping).issubset(expected):
        raise ValueError("SEC identity mapping contains symbols outside selected pool")
    declared_missing = {str(value).strip().upper() for value in payload.get("missing_symbols", [])}
    if expected - set(mapping) != declared_missing:
        raise ValueError("SEC identity mapping missing-symbol declaration is stale")
    exceptions = payload.get("declared_exceptions", {})
    if not isinstance(exceptions, dict):
        raise ValueError("SEC identity mapping exceptions must be a mapping")
    for symbol in declared_missing:
        exception = exceptions.get(symbol)
        if not isinstance(exception, dict):
            raise ValueError(f"missing SEC identity exception for {symbol}")
        entity_id = str(exception.get("entity_id", "")).strip()
        if not entity_id:
            raise ValueError(f"missing non-SEC entity_id for {symbol}")
        mapping[symbol] = {
            "cik": "",
            "title": str(exception.get("entity", "")).strip(),
            "entity_id": entity_id,
        }
    return mapping


def _cn_exchange(symbol: str) -> str:
    if symbol.startswith(("4", "8", "9")):
        return "BSE"
    return "SSE" if symbol.startswith(("5", "6")) else "SZSE"


def _fixture_population(symbols: list[str], *, kind: str) -> dict[str, SymbolPopulation]:
    status = "partial" if kind == "fundamentals" else "no_event_observed"
    return {
        symbol: SymbolPopulation(
            symbol=symbol,
            status=status,
            events=[],
            providers=["fixture"],
        )
        for symbol in symbols
    }


def _populate_us(
    symbols: list[str],
    field_map: dict[str, Any],
    retrieved_at: str,
    *,
    identity_mapping_path: Path,
) -> tuple[dict[str, SymbolPopulation], dict[str, SymbolPopulation]]:
    mapping = _sec_mapping(symbols, identity_mapping_path)
    sec = SecCompanyFactsClient()
    fundamentals: dict[str, SymbolPopulation] = {}
    actions: dict[str, SymbolPopulation] = {}
    for symbol in symbols:
        identity = mapping[symbol]
        cik = identity["cik"]
        if not cik:
            fundamentals[symbol] = SymbolPopulation(
                symbol,
                "identity_missing",
                [],
                ["sec_companyfacts"],
                "SEC registrant CIK is not applicable or unavailable",
            )
        else:
            try:
                payload = sec.fetch_companyfacts(cik)
                events = companyfacts_to_events(
                    payload,
                    symbol=symbol,
                    cik=cik,
                    exchange="US",
                    field_map=field_map,
                    retrieved_at=retrieved_at,
                )
                fundamentals[symbol] = SymbolPopulation(
                    symbol,
                    "ready" if events else "partial",
                    events,
                    ["sec_companyfacts"],
                )
            except Exception as exc:
                fundamentals[symbol] = SymbolPopulation(
                    symbol,
                    "provider_missing",
                    [],
                    ["sec_companyfacts"],
                    f"{type(exc).__name__}: {exc}",
                )
        try:
            frame = fetch_yfinance_actions(symbol)
            events = yfinance_actions_to_corporate_actions(
                frame,
                symbol=symbol,
                exchange="US",
                entity_id=identity["entity_id"],
                retrieved_at=retrieved_at,
            )
            actions[symbol] = SymbolPopulation(
                symbol,
                "ready" if events else "no_event_observed",
                events,
                ["yfinance_actions"],
            )
        except Exception as exc:
            actions[symbol] = SymbolPopulation(
                symbol,
                "provider_missing",
                [],
                ["yfinance_actions"],
                f"{type(exc).__name__}: {exc}",
            )
    return fundamentals, actions


def _populate_cn(
    symbols: list[str],
    field_map: dict[str, Any],
    retrieved_at: str,
    *,
    start_date: str,
    end_date: str,
    source_cache_root: Path | None = None,
    refresh_source_cache: bool = False,
) -> tuple[dict[str, SymbolPopulation], dict[str, SymbolPopulation], dict[str, Any]]:
    financial_client = AsharePublicFinancialClient()
    action_client = AsharePublicActionClient()
    fundamentals: dict[str, SymbolPopulation] = {}
    actions: dict[str, SymbolPopulation] = {}
    start_compact = start_date.replace("-", "")
    end_compact = end_date.replace("-", "")
    fundamental_cache_modes: dict[str, str] = {}
    action_cache_modes: dict[str, str] = {}
    for symbol in symbols:
        exchange = _cn_exchange(symbol)
        try:
            fundamental_identity = {
                "market": "cn",
                "symbol": symbol,
                "exchange": exchange,
                "start": start_date,
                "cutoff": end_date,
                "source_provider": "akshare_sina_financial_report_cninfo_time",
            }
            fundamental_names = ["disclosures", *STATEMENT_CACHE_NAMES.values()]
            fundamental_snapshot = None
            if source_cache_root is not None and not refresh_source_cache:
                fundamental_snapshot = load_exact_frame_snapshot(
                    source_cache_root / "fundamentals" / symbol,
                    identity=fundamental_identity,
                    frame_names=fundamental_names,
                )
            if fundamental_snapshot is None:
                disclosure_frame = financial_client.fetch_disclosures(
                    symbol=symbol,
                    start_date=start_compact,
                    end_date=end_compact,
                )
                statement_frames = {
                    statement: financial_client.fetch_statement(
                        symbol=symbol,
                        exchange=exchange,
                        statement=statement,
                    )
                    for statement in STATEMENTS
                }
                source_retrieved_at = retrieved_at
                fundamental_cache_modes[symbol] = "source_fetch"
                if source_cache_root is not None:
                    write_exact_frame_snapshot(
                        source_cache_root / "fundamentals" / symbol,
                        identity=fundamental_identity,
                        retrieved_at=source_retrieved_at,
                        frames={
                            "disclosures": disclosure_frame,
                            **{
                                STATEMENT_CACHE_NAMES[statement]: frame
                                for statement, frame in statement_frames.items()
                            },
                        },
                    )
            else:
                disclosure_frame = fundamental_snapshot.frames["disclosures"]
                statement_frames = {
                    statement: fundamental_snapshot.frames[cache_name]
                    for statement, cache_name in STATEMENT_CACHE_NAMES.items()
                }
                source_retrieved_at = fundamental_snapshot.retrieved_at
                fundamental_cache_modes[symbol] = "exact_cutoff_reuse"
            disclosures = cninfo_period_disclosures(disclosure_frame)
            events = []
            for statement in STATEMENTS:
                frame = statement_frames[statement]
                events.extend(
                    sina_statement_to_events(
                        frame,
                        disclosures=disclosures,
                        symbol=symbol,
                        exchange=exchange,
                        statement=statement,
                        field_map=field_map,
                        retrieved_at=source_retrieved_at,
                    )
                )
            unique = {event.event_id: event for event in events}
            ordered = sorted(unique.values(), key=lambda event: event.event_id)
            fundamentals[symbol] = SymbolPopulation(
                symbol,
                "ready" if ordered else "partial",
                ordered,
                ["akshare_sina_financial_report_cninfo_time"],
            )
        except Exception as exc:
            fundamental_cache_modes.setdefault(symbol, "source_fetch_failed")
            fundamentals[symbol] = SymbolPopulation(
                symbol,
                "provider_missing",
                [],
                ["akshare_sina_financial_report_cninfo_time"],
                f"{type(exc).__name__}: {exc}",
            )
        try:
            action_identity = {
                "market": "cn",
                "symbol": symbol,
                "exchange": exchange,
                "start": start_date,
                "cutoff": end_date,
                "source_provider": "akshare_eastmoney_dividend",
            }
            action_snapshot = None
            if source_cache_root is not None and not refresh_source_cache:
                action_snapshot = load_exact_frame_snapshot(
                    source_cache_root / "corporate_actions" / symbol,
                    identity=action_identity,
                    frame_names=["dividends"],
                )
            if action_snapshot is None:
                frame = action_client.fetch_dividends(symbol=symbol)
                source_retrieved_at = retrieved_at
                action_cache_modes[symbol] = "source_fetch"
                if source_cache_root is not None:
                    write_exact_frame_snapshot(
                        source_cache_root / "corporate_actions" / symbol,
                        identity=action_identity,
                        retrieved_at=source_retrieved_at,
                        frames={"dividends": frame},
                    )
            else:
                frame = action_snapshot.frames["dividends"]
                source_retrieved_at = action_snapshot.retrieved_at
                action_cache_modes[symbol] = "exact_cutoff_reuse"
            events = eastmoney_dividend_to_events(
                frame,
                symbol=symbol,
                exchange=exchange,
                retrieved_at=source_retrieved_at,
            )
            actions[symbol] = SymbolPopulation(
                symbol,
                "ready" if events else "no_event_observed",
                events,
                ["akshare_eastmoney_dividend"],
            )
        except Exception as exc:
            action_cache_modes.setdefault(symbol, "source_fetch_failed")
            actions[symbol] = SymbolPopulation(
                symbol,
                "provider_missing",
                [],
                ["akshare_eastmoney_dividend"],
                f"{type(exc).__name__}: {exc}",
            )
    source_reuse = {
        "schema_version": "1.0",
        "identity_policy": "market_symbol_exchange_start_exact_cutoff_provider",
        "expected_symbol_count": len(symbols),
        "fundamentals": {
            "exact_cutoff_reuse_count": sum(
                mode == "exact_cutoff_reuse" for mode in fundamental_cache_modes.values()
            ),
            "source_fetch_count": sum(
                mode == "source_fetch" for mode in fundamental_cache_modes.values()
            ),
            "source_fetch_failed_count": sum(
                mode == "source_fetch_failed" for mode in fundamental_cache_modes.values()
            ),
            "modes": fundamental_cache_modes,
        },
        "corporate_actions": {
            "exact_cutoff_reuse_count": sum(
                mode == "exact_cutoff_reuse" for mode in action_cache_modes.values()
            ),
            "source_fetch_count": sum(
                mode == "source_fetch" for mode in action_cache_modes.values()
            ),
            "source_fetch_failed_count": sum(
                mode == "source_fetch_failed" for mode in action_cache_modes.values()
            ),
            "modes": action_cache_modes,
        },
        "cached_retrieved_at_is_preserved": True,
        "research_only": True,
        "trade_ready": False,
    }
    return fundamentals, actions, source_reuse


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", choices=("us", "cn"), required=True)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("configs/data/selected_pool_event_population_v1.yaml"),
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--price-manifest", type=Path, default=None)
    parser.add_argument("--model-data-output", type=Path, default=None)
    parser.add_argument("--frontend-data-dir", type=Path, default=None)
    parser.add_argument("--source-cache-root", type=Path, default=None)
    parser.add_argument("--refresh-source-cache", action="store_true")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="Verify an existing sealed bundle without contacting providers.",
    )
    args = parser.parse_args()

    contract = _load_yaml(args.contract)
    market_contract = contract["markets"][args.market]
    pool_path = Path(str(market_contract["pool_spec"]))
    pool = _load_yaml(pool_path)
    symbols = _symbols(pool)
    governance_paths = {
        "population_contract": args.contract,
        "pool_spec": pool_path,
        "selected_pool_registry": Path("configs/pools/selected_pool_registry_v1.yaml"),
        "reference_instrument_registry": Path(
            "configs/pools/reference_instrument_registry_v1.yaml"
        ),
        "lifecycle_registry": Path(
            "configs/data_quality/symbol_identity_and_lifecycle_v1.yaml"
        ),
    }
    if args.verify_only:
        manifest = verify_selected_pool_event_bundle(
            args.output_root,
            expected_market=args.market,
            expected_pool_id=str(pool["pool_id"]),
            expected_symbols=symbols,
            expected_cutoff=args.cutoff,
            expected_governance_paths=governance_paths,
        )
        print(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
        return 0
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    if args.fixture:
        fundamentals = _fixture_population(symbols, kind="fundamentals")
        actions = _fixture_population(symbols, kind="corporate_actions")
        source_reuse = None
    elif args.market == "us":
        fundamentals, actions = _populate_us(
            symbols,
            contract["fundamental_fields"]["us"],
            retrieved_at,
            identity_mapping_path=Path(str(market_contract["identity_mapping"])),
        )
        source_reuse = None
    else:
        fundamentals, actions, source_reuse = _populate_cn(
            symbols,
            contract["fundamental_fields"]["cn"],
            retrieved_at,
            start_date=args.start,
            end_date=args.cutoff,
            source_cache_root=args.source_cache_root,
            refresh_source_cache=args.refresh_source_cache,
        )

    manifest = publish_selected_pool_event_bundle(
        market=args.market,
        pool_id=str(pool["pool_id"]),
        symbols=symbols,
        fundamentals=fundamentals,
        corporate_actions=actions,
        evidence_cutoff=args.cutoff,
        output_root=args.output_root,
        source_reuse=source_reuse,
        governance_paths=governance_paths,
        evidence_class="contract_fixture" if args.fixture else "source_bound",
    )

    if args.price_manifest and args.model_data_output:
        if manifest.get("publication_eligible") is not True:
            parser.error("contract fixtures cannot satisfy model-data readiness")
        component_paths = {
            str(record["component_kind"]): args.output_root / str(record["manifest_path"])
            for record in manifest["components"]
        }
        component_specs = [
            ComponentSpec(
                component_id=f"prices.{pool['pool_id']}",
                component_kind="selected_pool_prices",
                manifest_path=args.price_manifest,
                market=args.market,
            ),
            ComponentSpec(
                component_id=f"fundamentals.{pool['pool_id']}",
                component_kind="fundamental_coverage",
                manifest_path=component_paths["fundamental_coverage"],
                market=args.market,
            ),
            ComponentSpec(
                component_id=f"corporate_actions.{pool['pool_id']}",
                component_kind="corporate_action_coverage",
                manifest_path=component_paths["corporate_action_coverage"],
                market=args.market,
            ),
        ]
        build_model_data_bundle(
            root=Path.cwd(),
            contract_path=Path("configs/data_contracts/model_data_bundle_v1.yaml"),
            component_specs=component_specs,
            output_root=args.model_data_output,
            evidence_cutoff=args.cutoff,
            frontend_data_dir=args.frontend_data_dir,
        )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
