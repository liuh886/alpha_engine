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
from src.data.model_data_bundle import ComponentSpec, build_model_data_bundle
from src.data.selected_pool_event_population import (
    SymbolPopulation,
    build_selected_pool_event_artifacts,
)

STATEMENTS = ("资产负债表", "利润表", "现金流量表")


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


def _sec_mapping(
    symbols: list[str], identity_mapping_path: Path
) -> dict[str, dict[str, str]]:
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
    declared_missing = {
        str(value).strip().upper() for value in payload.get("missing_symbols", [])
    }
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
) -> tuple[dict[str, SymbolPopulation], dict[str, SymbolPopulation]]:
    financial_client = AsharePublicFinancialClient()
    action_client = AsharePublicActionClient()
    fundamentals: dict[str, SymbolPopulation] = {}
    actions: dict[str, SymbolPopulation] = {}
    start_compact = start_date.replace("-", "")
    end_compact = end_date.replace("-", "")
    for symbol in symbols:
        exchange = _cn_exchange(symbol)
        try:
            disclosure_frame = financial_client.fetch_disclosures(
                symbol=symbol,
                start_date=start_compact,
                end_date=end_compact,
            )
            disclosures = cninfo_period_disclosures(disclosure_frame)
            events = []
            for statement in STATEMENTS:
                frame = financial_client.fetch_statement(
                    symbol=symbol,
                    exchange=exchange,
                    statement=statement,
                )
                events.extend(
                    sina_statement_to_events(
                        frame,
                        disclosures=disclosures,
                        symbol=symbol,
                        exchange=exchange,
                        statement=statement,
                        field_map=field_map,
                        retrieved_at=retrieved_at,
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
            fundamentals[symbol] = SymbolPopulation(
                symbol,
                "provider_missing",
                [],
                ["akshare_sina_financial_report_cninfo_time"],
                f"{type(exc).__name__}: {exc}",
            )
        try:
            frame = action_client.fetch_dividends(symbol=symbol)
            events = eastmoney_dividend_to_events(
                frame,
                symbol=symbol,
                exchange=exchange,
                retrieved_at=retrieved_at,
            )
            actions[symbol] = SymbolPopulation(
                symbol,
                "ready" if events else "no_event_observed",
                events,
                ["akshare_eastmoney_dividend"],
            )
        except Exception as exc:
            actions[symbol] = SymbolPopulation(
                symbol,
                "provider_missing",
                [],
                ["akshare_eastmoney_dividend"],
                f"{type(exc).__name__}: {exc}",
            )
    return fundamentals, actions


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
    args = parser.parse_args()

    contract = _load_yaml(args.contract)
    market_contract = contract["markets"][args.market]
    pool_path = Path(str(market_contract["pool_spec"]))
    pool = _load_yaml(pool_path)
    symbols = _symbols(pool)
    retrieved_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    if args.fixture:
        fundamentals = _fixture_population(symbols, kind="fundamentals")
        actions = _fixture_population(symbols, kind="corporate_actions")
    elif args.market == "us":
        fundamentals, actions = _populate_us(
            symbols,
            contract["fundamental_fields"]["us"],
            retrieved_at,
            identity_mapping_path=Path(str(market_contract["identity_mapping"])),
        )
    else:
        fundamentals, actions = _populate_cn(
            symbols,
            contract["fundamental_fields"]["cn"],
            retrieved_at,
            start_date=args.start,
            end_date=args.cutoff,
        )

    manifest = build_selected_pool_event_artifacts(
        market=args.market,
        pool_id=str(pool["pool_id"]),
        symbols=symbols,
        fundamentals=fundamentals,
        corporate_actions=actions,
        evidence_cutoff=args.cutoff,
        output_root=args.output_root,
    )

    if args.price_manifest and args.model_data_output:
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
                manifest_path=args.output_root / "fundamentals/component_manifest.json",
                market=args.market,
            ),
            ComponentSpec(
                component_id=f"corporate_actions.{pool['pool_id']}",
                component_kind="corporate_action_coverage",
                manifest_path=args.output_root
                / "corporate_actions/component_manifest.json",
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
