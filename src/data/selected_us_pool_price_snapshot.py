"""Build manifest-bound OHLCV snapshots for the active selected US pool."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.data.adapters.base import FetchRequest
from src.data.adapters.yfinance_adapter import YFinanceAdapter
from src.data.us_pool_price_snapshot import (
    DailyBarsAdapter,
    MAX_STALE_CALENDAR_DAYS,
    NEW_YORK,
    POST_CLOSE_TIME,
    PoolSymbol,
    _canonical_hash,
    _normalise_result,
    _sha256_file,
    _write_immutable,
    resolve_safe_request_through,
)

DEFAULT_POOL = Path("configs/pools/us_small_pool_v2.yaml")
DEFAULT_START = "2024-01-01"


def load_selected_pool_symbols(
    pool_path: str | Path = DEFAULT_POOL,
) -> tuple[list[PoolSymbol], Path, str]:
    resolved = Path(pool_path).resolve()
    payload = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("selected US pool must be a YAML mapping")
    pool_id = str(payload.get("pool_id", ""))
    if payload.get("market") != "us" or payload.get("status") != "active_selected_pool":
        raise ValueError("price snapshot requires an active selected US pool")
    if pool_id != "us_small_pool_v2":
        raise ValueError(f"unexpected active selected US pool: {pool_id}")

    symbols: list[PoolSymbol] = []
    for basket, meta in payload.get("baskets", {}).items():
        for raw_symbol in meta.get("symbols", []):
            symbol = str(raw_symbol).strip().upper()
            symbols.append(
                PoolSymbol(
                    canonical_symbol=symbol,
                    provider_symbol=symbol,
                    role="candidate",
                    basket=str(basket),
                )
            )
    for canonical, meta in payload.get("references", {}).items():
        symbols.append(
            PoolSymbol(
                canonical_symbol=str(canonical).strip().upper(),
                provider_symbol=str(meta.get("provider_symbol", canonical)).strip(),
                role=str(meta.get("role", "reference")),
                basket="reference",
            )
        )
    canonical = [row.canonical_symbol for row in symbols]
    if not symbols or len(canonical) != len(set(canonical)):
        raise ValueError("selected US pool symbols must be non-empty and unique")
    if {"TIGO", "SNDK"} & set(canonical):
        raise ValueError("selected US historical pool contains a prohibited identity")
    return symbols, resolved, pool_id


def build_selected_us_pool_price_snapshot(
    *,
    output_root: str | Path,
    requested_through: str | None = None,
    start_date: str = DEFAULT_START,
    pool_path: str | Path = DEFAULT_POOL,
    adapter: DailyBarsAdapter | None = None,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    target = resolve_safe_request_through(
        requested_through=requested_through,
        now_utc=now_utc,
    )
    start = date.fromisoformat(start_date)
    if start >= target:
        raise ValueError("snapshot start_date must precede requested-through date")

    symbols, resolved_pool, pool_id = load_selected_pool_symbols(pool_path)
    provider = adapter or YFinanceAdapter()
    frames: list[pd.DataFrame] = []
    coverage: list[dict[str, Any]] = []
    for symbol in symbols:
        result = provider.fetch_daily_bars(
            FetchRequest(
                symbol=symbol.provider_symbol,
                market="us",
                start=start.isoformat(),
                end=target.isoformat(),
            )
        )
        frame = _normalise_result(result, symbol)
        observed_provider_symbol = str(result.provider_symbol or symbol.provider_symbol)
        latest = frame["date"].max().date()
        first = frame["date"].min().date()
        source_identity = _canonical_hash(
            {
                "provider": result.provider,
                "canonical_symbol": symbol.canonical_symbol,
                "provider_symbol": observed_provider_symbol,
                "rows": frame.assign(date=frame["date"].dt.strftime("%Y-%m-%d")).to_dict(
                    orient="records"
                ),
            }
        )
        coverage.append(
            {
                "canonical_symbol": symbol.canonical_symbol,
                "provider_symbol": observed_provider_symbol,
                "role": symbol.role,
                "basket": symbol.basket,
                "provider": result.provider,
                "first_date": first.isoformat(),
                "latest_date": latest.isoformat(),
                "row_count": len(frame),
                "source_identity_sha256": source_identity,
            }
        )
        frames.append(frame)

    latest_dates = {row["latest_date"] for row in coverage}
    if len(latest_dates) != 1:
        details = ", ".join(f"{row['canonical_symbol']}={row['latest_date']}" for row in coverage)
        raise ValueError("selected US pool latest-session coverage is inconsistent: " + details)
    resolved_as_of = date.fromisoformat(next(iter(latest_dates)))
    if resolved_as_of > target:
        raise ValueError("provider returned rows beyond requested-through cutoff")
    if (target - resolved_as_of).days > MAX_STALE_CALENDAR_DAYS:
        raise ValueError(
            f"selected US pool snapshot is stale: target={target}, latest={resolved_as_of}"
        )
    local_now = (now_utc or datetime.now(timezone.utc)).astimezone(NEW_YORK)
    if (
        requested_through is None
        and resolved_as_of == local_now.date()
        and local_now.time() < POST_CLOSE_TIME
    ):
        raise ValueError("intraday US daily bar cannot be accepted as a complete session")

    combined = pd.concat(frames, ignore_index=True)
    combined = combined[combined["date"].dt.date <= resolved_as_of]
    combined = combined.sort_values(["date", "symbol"]).reset_index(drop=True)
    expected = {row.canonical_symbol for row in symbols}
    latest_rows = combined[combined["date"].dt.date == resolved_as_of]
    observed_latest = set(latest_rows["symbol"])
    if observed_latest != expected:
        missing = sorted(expected - observed_latest)
        raise ValueError("latest session is missing selected symbols: " + ", ".join(missing))

    output = Path(output_root).resolve() / resolved_as_of.isoformat()
    output.mkdir(parents=True, exist_ok=True)
    prices_path = output / "prices.csv"
    csv_frame = combined.copy()
    csv_frame["date"] = csv_frame["date"].dt.strftime("%Y-%m-%d")
    _write_immutable(prices_path, csv_frame.to_csv(index=False).encode("utf-8"))

    snapshot_id = f"{pool_id}_yfinance_snapshot_v1"
    coverage_payload = {
        "schema_version": "1.0",
        "snapshot_id": snapshot_id,
        "pool_id": pool_id,
        "requested_through": target.isoformat(),
        "resolved_as_of_date": resolved_as_of.isoformat(),
        "provider": provider.name,
        "candidate_and_reference_count": len(symbols),
        "all_latest_session_complete": True,
        "rows": coverage,
    }
    coverage_path = output / "coverage_report.json"
    _write_immutable(
        coverage_path,
        json.dumps(coverage_payload, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
    )

    decision = {
        "schema_version": "1.0",
        "decision": "selected_us_pool_price_snapshot_ready",
        "research_only": True,
        "trade_ready": False,
        "performance_evaluated": False,
        "provider": provider.name,
        "pool_id": pool_id,
        "requested_through": target.isoformat(),
        "resolved_as_of_date": resolved_as_of.isoformat(),
        "symbol_count": len(symbols),
        "row_count": len(combined),
        "prices_csv": str(prices_path),
    }
    decision_path = output / "decision.json"
    _write_immutable(
        decision_path,
        json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
    )

    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "snapshot_id": snapshot_id,
        "research_only": True,
        "trade_ready": False,
        "inputs": {
            "pool_id": pool_id,
            "pool_sha256": _sha256_file(resolved_pool),
            "provider": provider.name,
            "start_date": start.isoformat(),
            "requested_through": target.isoformat(),
            "source_identities": {
                row["canonical_symbol"]: row["source_identity_sha256"] for row in coverage
            },
        },
        "outputs": {
            "prices.csv": _sha256_file(prices_path),
            "coverage_report.json": _sha256_file(coverage_path),
            "decision.json": _sha256_file(decision_path),
        },
    }
    manifest["manifest_identity_sha256"] = _canonical_hash(manifest)
    manifest_path = output / "evidence_manifest.json"
    _write_immutable(
        manifest_path,
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8"),
    )
    return decision
