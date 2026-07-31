"""Governed orchestration for BaoStock–Tushare A-share evidence sources."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.research.cn_live_evidence_sources import (
    BaoStockClient,
    BaoStockClientProtocol,
    SourceRunConfig,
    TushareClientProtocol,
    TushareHttpClient,
    _bars,
    _blocked,
    _build_status,
    _calendar,
    _limits,
    _listing_metadata,
    _promote_live_contract,
    _query_baostock_symbol,
)
from src.research.cn_pool_provider import build_cn_pool_provider, load_cn_provider_contract
from src.research.focus_watchlist_signal import canonical_sha256, sha256_file
from src.research.research_artifacts import write_json


def build_cn_live_evidence_sources(
    *,
    contract_path: str | Path,
    output_dir: str | Path,
    start_date: str,
    end_date: str = "2026-06-30",
    tushare_client: TushareClientProtocol | None = None,
    baostock_client: BaoStockClientProtocol | None = None,
    fixture_mode: bool = False,
) -> dict[str, Any]:
    """Build source staging and pass it through the frozen CN provider contract."""

    config = SourceRunConfig(start_date, end_date, fixture_mode)
    config.validate()
    output = Path(output_dir).resolve()
    staging = output / "staging"
    capabilities: dict[str, Any] = {
        "baostock": "not_attempted",
        "tushare_trade_cal": "not_attempted",
        "tushare_stock_basic": "not_attempted",
        "tushare_stk_limit": "not_attempted",
        "tushare_token_present": False,
        "fixture_mode": fixture_mode,
    }
    token = os.environ.get("TUSHARE_TOKEN", "")
    if tushare_client is None:
        capabilities["tushare_token_present"] = bool(token.strip())
        if not token.strip():
            return _blocked(
                output,
                reason="TUSHARE_TOKEN is missing",
                config=config,
                capabilities=capabilities,
            )
        tushare_client = TushareHttpClient(token)
    bao = baostock_client or BaoStockClient()

    try:
        _, pool, _, _, _, _ = load_cn_provider_contract(contract_path)
        candidates = [
            str(symbol)
            for basket in pool["baskets"].values()
            for symbol in basket["symbols"]
        ]
        references = [str(symbol) for symbol in pool["references"]]
        bao.login()
        capabilities["baostock"] = "available"
        calendar = _calendar(bao, tushare_client, config)
        capabilities["tushare_trade_cal"] = "available"
        listing = _listing_metadata(bao, tushare_client, candidates)
        capabilities["tushare_stock_basic"] = "available"
        limits = _limits(tushare_client, candidates, config)
        capabilities["tushare_stk_limit"] = "available"

        raw_by_symbol = {}
        qfq_by_symbol = {}
        reference_by_symbol = {}
        for symbol in candidates:
            raw, qfq = _query_baostock_symbol(bao, symbol, config, index=False)
            if qfq is None:
                raise RuntimeError(f"adjusted history is missing: {symbol}")
            raw_by_symbol[symbol] = raw
            qfq_by_symbol[symbol] = qfq
        for symbol in references:
            raw, _ = _query_baostock_symbol(bao, symbol, config, index=True)
            reference_by_symbol[symbol] = raw

        bars, raw_execution = _bars(raw_by_symbol, qfq_by_symbol, reference_by_symbol)
        status = _build_status(
            raw_by_symbol, reference_by_symbol, calendar, listing, limits
        )
        # The contract requires a single status-provider identity. Candidate and
        # reference semantics differ, but both are produced by this reconciled
        # source pipeline and share one field-level provenance contract.
        status["source_status_provider"] = "baostock+tushare_reconciled_status"

        staging.mkdir(parents=True, exist_ok=True)
        paths = {
            "contract_bars": staging / "contract_bars.csv",
            "execution_bars_raw": staging / "execution_bars_raw.csv",
            "status": staging / "contract_status.csv",
            "calendar": staging / "contract_calendar.csv",
            "limits": staging / "daily_price_limits.csv",
            "listing": staging / "listing_metadata.csv",
        }
        bars.to_csv(paths["contract_bars"], index=False)
        raw_execution.to_csv(paths["execution_bars_raw"], index=False)
        status.to_csv(paths["status"], index=False)
        calendar.to_csv(paths["calendar"], index=False)
        limits.to_csv(paths["limits"], index=False)
        listing.to_csv(paths["listing"], index=False)
        source_manifest: dict[str, Any] = {
            "schema_version": "1.0",
            "market": "cn",
            "source_roles": {
                "bars": "BaoStock raw and qfq; relative factor anchored to 2026-06-30",
                "status": "BaoStock tradestatus/isST plus Tushare stk_limit",
                "calendar": "BaoStock and Tushare trade_cal reconciled",
                "listing": "BaoStock and Tushare stock_basic reconciled",
            },
            "request_range": {"start": start_date, "end": end_date},
            "row_counts": {
                "bars": len(bars),
                "raw_execution_bars": len(raw_execution),
                "status": len(status),
                "calendar": len(calendar),
                "limits": len(limits),
                "listing": len(listing),
            },
            "files": {
                name: {"path": str(path), "sha256": sha256_file(path)}
                for name, path in paths.items()
            },
            "fixture_mode": fixture_mode,
            "token_persisted": False,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        source_manifest["source_manifest_identity_sha256"] = canonical_sha256(
            source_manifest
        )
        write_json(staging / "source_manifest.json", source_manifest)
        write_json(
            staging / "source_capability_report.json",
            {
                "schema_version": "1.0",
                "decision": (
                    "fixture_sources_complete_not_authoritative"
                    if fixture_mode
                    else "live_sources_complete"
                ),
                "capabilities": capabilities,
                "live_provider_run_completed": not fixture_mode,
                "source_attestation_verified": not fixture_mode,
                "authoritative_provider_artifact": False,
                "token_persisted": False,
            },
        )
        build_cn_pool_provider(
            contract_path=contract_path,
            bars_csv=paths["contract_bars"],
            status_csv=paths["status"],
            calendar_csv=paths["calendar"],
            output_dir=output,
        )
        if fixture_mode:
            return json.loads((output / "decision.json").read_text(encoding="utf-8"))
        return _promote_live_contract(output, source_manifest)
    except Exception as exc:
        capabilities["failure_type"] = type(exc).__name__
        return _blocked(
            output,
            reason=str(exc),
            config=config,
            capabilities=capabilities,
        )
    finally:
        try:
            bao.logout()
        except Exception:
            pass
