from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import yaml

from src.data.adapters.base import FetchRequest, MarketDataAdapter
from src.data.etf_reference_bundle import reconcile_adjusted_bars
from src.data.provider_catalog import provider_manifest_entry

SHARD_MANIFEST = "shard_manifest.json"
BUNDLE_MANIFEST = "professional_price_manifest.json"
_PROVIDER_BREAKER_ERRORS = {"rate_limited", "credential_or_entitlement"}


class ProfessionalPriceBundleError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ProfessionalPriceBundleError(f"contract must be a mapping: {path}")
    return payload


def _symbols(root: Path, contract: Mapping[str, Any]) -> list[str]:
    pool = contract.get("pool", {})
    if not isinstance(pool, dict):
        raise ProfessionalPriceBundleError("pool contract is missing")
    spec = root / str(pool.get("spec", ""))
    payload = _load_yaml(spec)
    symbols = [str(value).strip().upper() for value in payload.get("symbols", [])]
    expected = int(pool.get("candidate_count", 0))
    if len(symbols) != expected or len(set(symbols)) != expected:
        raise ProfessionalPriceBundleError("US selected-pool identity is not exact")
    references = [str(value).strip().upper() for value in pool.get("references", [])]
    if set(symbols).intersection(references):
        raise ProfessionalPriceBundleError("candidate/reference overlap is forbidden")
    return [*symbols, *references]


def shard_symbols(symbols: Sequence[str], *, shard_size: int, shard_index: int) -> list[str]:
    if shard_size < 1 or shard_index < 0:
        raise ProfessionalPriceBundleError("invalid shard arguments")
    start = shard_index * shard_size
    return list(symbols[start : start + shard_size])


def shard_count(symbols: Sequence[str], *, shard_size: int) -> int:
    return (len(symbols) + shard_size - 1) // shard_size


def _fetch(
    adapter: MarketDataAdapter | None,
    *,
    symbol: str,
    start: str,
    cutoff: str,
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    if adapter is None:
        return None, {"ok": False, "error_class": "provider_not_configured"}
    try:
        result = adapter.fetch_daily_bars(
            FetchRequest(symbol=symbol, market="us", start=start, end=cutoff)
        )
        frame = result.df.copy()
        return frame, {
            "ok": True,
            "provider": result.provider,
            "provider_symbol": result.provider_symbol or symbol,
            "rows": int(len(frame)),
            "first_date": pd.to_datetime(frame["date"]).min().date().isoformat(),
            "last_date": pd.to_datetime(frame["date"]).max().date().isoformat(),
            "metadata": dict(frame.attrs.get("provider_metadata", {})),
        }
    except Exception as exc:
        return None, {
            "ok": False,
            "error_class": str(getattr(exc, "error_class", "data_fetch_error")),
            "error": f"{type(exc).__name__}: {exc}",
            "status_code": getattr(exc, "status_code", None),
            "retry_after_seconds": getattr(exc, "retry_after_seconds", None),
        }


def _circuit_attempt(reason: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error_class": "provider_circuit_open",
        "error": f"provider skipped after shard-wide failure: {reason}",
    }


def build_professional_price_shard(
    *,
    root: str | Path,
    contract_path: str | Path,
    output_root: str | Path,
    cutoff: str,
    shard_index: int,
    primary_adapter: MarketDataAdapter | None,
    secondary_adapter: MarketDataAdapter | None,
) -> dict[str, Any]:
    repo = Path(root).resolve()
    contract_file = Path(contract_path)
    if not contract_file.is_absolute():
        contract_file = repo / contract_file
    contract = _load_yaml(contract_file)
    all_symbols = _symbols(repo, contract)
    shard_size = int(contract.get("sharding", {}).get("shard_size", 10))
    total_shards = shard_count(all_symbols, shard_size=shard_size)
    selected = shard_symbols(
        all_symbols, shard_size=shard_size, shard_index=shard_index
    )
    if not selected:
        raise ProfessionalPriceBundleError(
            f"shard index outside range: {shard_index}/{total_shards}"
        )
    start = str(contract.get("history", {}).get("requested_start", "2021-01-01"))
    settings = dict(contract.get("reconciliation", {}))
    output = Path(output_root).resolve() / "shards" / f"{shard_index:03d}"
    output.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    primary_open = primary_adapter is None
    secondary_open = secondary_adapter is None
    primary_reason = "provider_not_configured" if primary_open else ""
    secondary_reason = "provider_not_configured" if secondary_open else ""
    primary_calls = 0
    secondary_calls = 0

    for symbol in selected:
        if primary_open:
            primary, primary_attempt = None, _circuit_attempt(primary_reason)
        else:
            primary_calls += 1
            primary, primary_attempt = _fetch(
                primary_adapter, symbol=symbol, start=start, cutoff=cutoff
            )
            if primary_attempt.get("error_class") in _PROVIDER_BREAKER_ERRORS:
                primary_open = True
                primary_reason = str(primary_attempt.get("error_class"))

        if secondary_open:
            secondary, secondary_attempt = None, _circuit_attempt(secondary_reason)
        else:
            secondary_calls += 1
            secondary, secondary_attempt = _fetch(
                secondary_adapter, symbol=symbol, start=start, cutoff=cutoff
            )
            if secondary_attempt.get("error_class") in _PROVIDER_BREAKER_ERRORS:
                secondary_open = True
                secondary_reason = str(secondary_attempt.get("error_class"))

        reconciliation = reconcile_adjusted_bars(
            primary, secondary, symbol=symbol, settings=settings
        )
        if primary is not None and secondary is not None:
            status = str(reconciliation["status"])
            canonical = primary if status != "quarantine" else None
        elif primary is not None:
            status = "single_professional_source"
            canonical = primary
        elif secondary is not None:
            status = "single_professional_source"
            canonical = secondary
        else:
            status = "provider_missing"
            canonical = None

        for provider, frame in (("tiingo", primary), ("polygon", secondary)):
            if frame is None:
                continue
            path = output / "sources" / provider / f"{symbol}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(path, index=False)
            hashes[str(path.relative_to(output))] = _sha256(path)
        canonical_path: str | None = None
        if canonical is not None:
            path = output / "canonical" / f"{symbol}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            canonical.to_csv(path, index=False)
            canonical_path = str(path.relative_to(output))
            hashes[canonical_path] = _sha256(path)
        records.append(
            {
                "symbol": symbol,
                "status": status,
                "canonical_path": canonical_path,
                "primary_attempt": primary_attempt,
                "secondary_attempt": secondary_attempt,
                "reconciliation": reconciliation,
            }
        )

    manifest = {
        "schema_version": "1.1",
        "contract_id": contract.get("contract_id"),
        "pool_id": contract.get("pool", {}).get("pool_id"),
        "shard_index": shard_index,
        "shard_size": shard_size,
        "total_shards": total_shards,
        "symbols": selected,
        "cutoff": cutoff,
        "records": records,
        "files": dict(sorted(hashes.items())),
        "provider_health": {
            "tiingo": {
                "attempted_symbols": primary_calls,
                "circuit_open": primary_open,
                "circuit_reason": primary_reason or None,
            },
            "polygon": {
                "attempted_symbols": secondary_calls,
                "circuit_open": secondary_open,
                "circuit_reason": secondary_reason or None,
            },
        },
        "complete": all(
            row["status"]
            in {
                "consensus",
                "explainable_corporate_action_difference",
                "single_professional_source",
            }
            for row in records
        ),
        "research_only": True,
        "trade_ready": False,
    }
    _write_json(output / SHARD_MANIFEST, manifest)
    return manifest


def finalize_professional_price_bundle(
    *,
    root: str | Path,
    contract_path: str | Path,
    output_root: str | Path,
    cutoff: str,
) -> dict[str, Any]:
    repo = Path(root).resolve()
    contract_file = Path(contract_path)
    if not contract_file.is_absolute():
        contract_file = repo / contract_file
    contract = _load_yaml(contract_file)
    expected_symbols = _symbols(repo, contract)
    output = Path(output_root).resolve()
    manifests = sorted(output.glob(f"shards/*/{SHARD_MANIFEST}"))
    records: dict[str, dict[str, Any]] = {}
    shard_hashes: dict[str, str] = {}
    for path in manifests:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("cutoff") != cutoff:
            continue
        if payload.get("complete") is not True:
            raise ProfessionalPriceBundleError(f"incomplete shard: {path}")
        shard_hashes[str(path.relative_to(output))] = _sha256(path)
        for row in payload.get("records", []):
            symbol = str(row.get("symbol", "")).upper()
            if symbol in records:
                raise ProfessionalPriceBundleError(f"duplicate shard symbol: {symbol}")
            records[symbol] = row
    missing = sorted(set(expected_symbols).difference(records))
    extra = sorted(set(records).difference(expected_symbols))
    if missing or extra:
        raise ProfessionalPriceBundleError(
            f"shard set is incomplete: missing={missing}, extra={extra}"
        )
    statuses = {symbol: str(records[symbol]["status"]) for symbol in expected_symbols}
    dual = all(
        value in {"consensus", "explainable_corporate_action_difference"}
        for value in statuses.values()
    )
    manifest = {
        "schema_version": "1.0",
        "component_id": "prices.us_selected_equities_v2.professional",
        "component_kind": "selected_pool_prices",
        "status": "ready",
        "market": "us",
        "pool_id": contract.get("pool", {}).get("pool_id"),
        "evidence_cutoff": cutoff,
        "expected_symbol_count": len(expected_symbols),
        "ready_symbol_count": len(expected_symbols),
        "coverage_ratio": 1.0,
        "missing_symbols": [],
        "invalid_symbols": [],
        "quarantined_symbols": [],
        "providers": ["tiingo", "polygon"] if dual else ["tiingo"],
        "professional_source_ready": True,
        "professional_corroborated": dual,
        "symbol_statuses": statuses,
        "shard_manifests": shard_hashes,
        "provider_contracts": {
            "tiingo": provider_manifest_entry("tiingo"),
            "polygon": provider_manifest_entry("polygon"),
        },
        "research_only": True,
        "trade_ready": False,
    }
    _write_json(output / BUNDLE_MANIFEST, manifest)
    return manifest
