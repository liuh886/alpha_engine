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
_PROVIDER_WIDE_ERRORS = {"rate_limited", "credential_or_entitlement"}
_VALIDATION_PASS = {"consensus", "explainable_corporate_action_difference"}


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


def _validator_status(
    canonical: pd.DataFrame,
    validator: pd.DataFrame | None,
    *,
    symbol: str,
    settings: Mapping[str, Any],
) -> dict[str, Any]:
    if validator is None:
        return {
            "symbol": symbol,
            "status": "provider_missing",
            "canonical_present": True,
            "validator_present": False,
            "overlap_sessions": 0,
            "reason": "validation provider unavailable",
        }
    return reconcile_adjusted_bars(
        canonical,
        validator,
        symbol=symbol,
        settings=dict(settings),
    )


def build_professional_price_shard(
    *,
    root: str | Path,
    contract_path: str | Path,
    output_root: str | Path,
    cutoff: str,
    shard_index: int,
    canonical_adapter: MarketDataAdapter,
    validation_adapters: Mapping[str, MarketDataAdapter | None],
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
    circuits: dict[str, dict[str, Any]] = {}
    for name, adapter in validation_adapters.items():
        circuits[name] = {
            "open": adapter is None,
            "reason": "provider_not_configured" if adapter is None else "",
            "opened_on_symbol": "",
        }

    for symbol in selected:
        canonical, canonical_attempt = _fetch(
            canonical_adapter, symbol=symbol, start=start, cutoff=cutoff
        )
        validator_attempts: dict[str, dict[str, Any]] = {}
        reconciliations: dict[str, dict[str, Any]] = {}
        validator_frames: dict[str, pd.DataFrame] = {}

        if canonical is not None:
            canonical_path = output / "canonical" / f"{symbol}.csv"
            canonical_path.parent.mkdir(parents=True, exist_ok=True)
            canonical.to_csv(canonical_path, index=False)
            hashes[str(canonical_path.relative_to(output))] = _sha256(canonical_path)
        else:
            canonical_path = None

        for name, adapter in validation_adapters.items():
            circuit = circuits[name]
            if circuit["open"]:
                validator_attempts[name] = {
                    "ok": False,
                    "error_class": "provider_circuit_open",
                    "reason": circuit["reason"],
                    "opened_on_symbol": circuit["opened_on_symbol"],
                }
                validator = None
            else:
                validator, attempt = _fetch(
                    adapter, symbol=symbol, start=start, cutoff=cutoff
                )
                validator_attempts[name] = attempt
                if not attempt.get("ok") and attempt.get("error_class") in _PROVIDER_WIDE_ERRORS:
                    circuit.update(
                        {
                            "open": True,
                            "reason": str(attempt.get("error_class")),
                            "opened_on_symbol": symbol,
                        }
                    )
            if validator is not None:
                validator_frames[name] = validator
                path = output / "validators" / name / f"{symbol}.csv"
                path.parent.mkdir(parents=True, exist_ok=True)
                validator.to_csv(path, index=False)
                hashes[str(path.relative_to(output))] = _sha256(path)
            if canonical is not None:
                reconciliations[name] = _validator_status(
                    canonical,
                    validator,
                    symbol=symbol,
                    settings=settings,
                )
            else:
                reconciliations[name] = {
                    "symbol": symbol,
                    "status": "canonical_missing",
                    "canonical_present": False,
                    "validator_present": validator is not None,
                    "overlap_sessions": 0,
                    "reason": "canonical source unavailable",
                }

        if canonical is None:
            status = "canonical_missing"
        elif any(row.get("status") == "quarantine" for row in reconciliations.values()):
            status = "validation_conflict"
        else:
            present = sum(1 for row in reconciliations.values() if row.get("status") in _VALIDATION_PASS)
            configured = len(validation_adapters)
            if configured and present == configured:
                status = "canonical_ready_validated"
            elif present:
                status = "canonical_ready_partially_validated"
            else:
                status = "canonical_ready_unvalidated"

        records.append(
            {
                "symbol": symbol,
                "status": status,
                "canonical_path": (
                    str(canonical_path.relative_to(output)) if canonical_path else None
                ),
                "canonical_attempt": canonical_attempt,
                "validator_attempts": validator_attempts,
                "reconciliations": reconciliations,
            }
        )

    complete = all(
        row["status"]
        in {
            "canonical_ready_unvalidated",
            "canonical_ready_validated",
            "canonical_ready_partially_validated",
        }
        for row in records
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
        "provider_circuits": circuits,
        "complete": complete,
        "canonical_provider": canonical_adapter.name,
        "validation_providers": list(validation_adapters),
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
    validated = sum(
        value in {"canonical_ready_validated", "canonical_ready_partially_validated"}
        for value in statuses.values()
    )
    fully_validated = sum(
        value == "canonical_ready_validated" for value in statuses.values()
    )
    manifest = {
        "schema_version": "1.1",
        "component_id": "prices.us_selected_equities_v2.governed",
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
        "canonical_provider": "yfinance",
        "validation_providers": ["tiingo", "polygon"],
        "validated_symbol_count": validated,
        "fully_validated_symbol_count": fully_validated,
        "validation_coverage_ratio": validated / len(expected_symbols),
        "research_price_ready": True,
        "professional_sources_validation_only": True,
        "professional_source_ready": False,
        "symbol_statuses": statuses,
        "shard_manifests": shard_hashes,
        "provider_contracts": {
            "yfinance": provider_manifest_entry("yfinance"),
            "tiingo": provider_manifest_entry("tiingo"),
            "polygon": provider_manifest_entry("polygon"),
        },
        "research_only": True,
        "trade_ready": False,
    }
    _write_json(output / BUNDLE_MANIFEST, manifest)
    return manifest
