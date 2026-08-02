from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from src.data.adapters.base import FetchRequest, MarketDataAdapter
from src.data.adapters.yfinance_adapter import YFinanceAdapter
from src.data.etf_reference_bundle import (
    ETF_REFERENCE_SYMBOLS,
    load_etf_reference_bundle,
)

STRATEGY_SIGNAL_REFERENCES = ("^VIX", "^VXN")
STRATEGY_DATA_SYMBOLS = (*ETF_REFERENCE_SYMBOLS, *STRATEGY_SIGNAL_REFERENCES)
STRATEGY_MANIFEST_NAME = "strategy_data_manifest.json"


class StrategyDataBundleError(ValueError):
    """Raised when the governed strategy data product is incomplete or altered."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


def _safe_name(symbol: str) -> str:
    return symbol.replace("^", "INDEX_").replace("/", "_")


def _normalise_strategy_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    required = {"date", "open", "close"}
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise StrategyDataBundleError(f"{symbol} bars missing columns: {missing}")
    out = frame[["date", "open", "close"]].copy()
    out["date"] = (
        pd.to_datetime(out["date"], errors="coerce")
        .dt.tz_localize(None)
        .dt.normalize()
    )
    out["open"] = pd.to_numeric(out["open"], errors="coerce")
    out["close"] = pd.to_numeric(out["close"], errors="coerce")
    out = (
        out.dropna(subset=["date", "open", "close"])
        .loc[lambda value: value["open"].gt(0) & value["close"].gt(0)]
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    if out.empty:
        raise StrategyDataBundleError(f"{symbol} has no usable strategy bars")
    return out


def _load_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise StrategyDataBundleError(f"strategy data manifest is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise StrategyDataBundleError("strategy data manifest must be a mapping")
    return payload


def build_strategy_data_bundle(
    *,
    etf_bundle_root: str | Path,
    output_root: str | Path,
    start: str,
    end: str | None = None,
    component_id: str = "strategy.qqqi_qqq_tqqq_vix_vxn_v1",
    pool_id: str = "qqqi_qqq_tqqq_reference_bundle_v1",
    reference_adapter: MarketDataAdapter | None = None,
) -> dict[str, Any]:
    """Build one immutable strategy data identity for tradables and signals."""

    etf_root = Path(etf_bundle_root).resolve()
    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    adapter = reference_adapter or YFinanceAdapter()

    etf_bars, etf_coverage, etf_manifest = load_etf_reference_bundle(
        etf_root,
        symbols=ETF_REFERENCE_SYMBOLS,
        require_strategy_ready=True,
    )
    etf_manifest_path = etf_root / "bundle_manifest.json"
    if not etf_manifest_path.is_file():
        raise StrategyDataBundleError("source ETF bundle manifest is missing")

    frames: dict[str, pd.DataFrame] = {
        symbol: _normalise_strategy_frame(frame, symbol)
        for symbol, frame in etf_bars.items()
    }
    providers: dict[str, str] = {
        symbol: str(etf_manifest.get("selected_providers", {}).get(symbol, "unknown"))
        for symbol in ETF_REFERENCE_SYMBOLS
    }
    roles = {
        **{symbol: "tradable" for symbol in ETF_REFERENCE_SYMBOLS},
        **{symbol: "signal_reference" for symbol in STRATEGY_SIGNAL_REFERENCES},
    }

    missing: list[str] = []
    reference_attempts: dict[str, dict[str, Any]] = {}
    for symbol in STRATEGY_SIGNAL_REFERENCES:
        try:
            result = adapter.fetch_daily_bars(
                FetchRequest(symbol=symbol, market="us", start=start, end=end)
            )
            frame = _normalise_strategy_frame(result.df, symbol)
            frames[symbol] = frame
            providers[symbol] = result.provider
            reference_attempts[symbol] = {
                "ok": True,
                "provider": result.provider,
                "provider_symbol": result.provider_symbol or symbol,
                "rows": int(len(frame)),
                "first_date": frame["date"].min().date().isoformat(),
                "last_date": frame["date"].max().date().isoformat(),
            }
        except Exception as exc:
            missing.append(symbol)
            reference_attempts[symbol] = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }

    file_hashes: dict[str, str] = {}
    coverage_rows: list[dict[str, Any]] = []
    for symbol in STRATEGY_DATA_SYMBOLS:
        frame = frames.get(symbol)
        if frame is None:
            coverage_rows.append(
                {
                    "symbol": symbol,
                    "role": roles[symbol],
                    "status": "missing",
                    "provider": providers.get(symbol),
                    "rows": 0,
                    "first_date": None,
                    "last_date": None,
                }
            )
            continue
        path = output / "canonical" / f"{_safe_name(symbol)}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(path, index=False)
        relative = str(path.relative_to(output))
        file_hashes[relative] = _sha256(path)
        coverage_rows.append(
            {
                "symbol": symbol,
                "role": roles[symbol],
                "status": "ready",
                "provider": providers.get(symbol),
                "rows": int(len(frame)),
                "first_date": frame["date"].min().date().isoformat(),
                "last_date": frame["date"].max().date().isoformat(),
                "path": relative,
                "sha256": file_hashes[relative],
            }
        )

    coverage = pd.DataFrame(coverage_rows).sort_values("symbol").reset_index(drop=True)
    coverage_path = output / "coverage.csv"
    coverage.to_csv(coverage_path, index=False)
    file_hashes[str(coverage_path.relative_to(output))] = _sha256(coverage_path)

    ready_rows = coverage.loc[coverage["status"].eq("ready")]
    expected = len(STRATEGY_DATA_SYMBOLS)
    ready = int(len(ready_rows))
    first_date: str | None = None
    last_date: str | None = None
    if ready == expected:
        starts = pd.to_datetime(ready_rows["first_date"], errors="coerce")
        ends = pd.to_datetime(ready_rows["last_date"], errors="coerce")
        if not starts.isna().any() and not ends.isna().any():
            first = pd.Timestamp(starts.max())
            last = pd.Timestamp(ends.min())
            if first <= last:
                first_date = first.date().isoformat()
                last_date = last.date().isoformat()

    status = "ready" if ready == expected and first_date and last_date else "blocked"
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "bundle_id": "qqqi_qqq_tqqq_vix_vxn_strategy_data_v1",
        "component_id": component_id,
        "component_kind": "strategy_data_bundle",
        "status": status,
        "market": "us",
        "pool_id": pool_id,
        "evidence_cutoff": last_date,
        "first_date": first_date,
        "last_date": last_date,
        "expected_symbol_count": expected,
        "ready_symbol_count": ready,
        "coverage_ratio": float(ready / expected),
        "missing_symbols": sorted(set(missing)),
        "invalid_symbols": [],
        "quarantined_symbols": [],
        "providers": sorted(set(providers.values())),
        "professional_source_ready": bool(
            etf_manifest.get("professional_source_ready", False)
        ),
        "research_only": True,
        "trade_ready": False,
        "symbols": list(STRATEGY_DATA_SYMBOLS),
        "roles": roles,
        "files": dict(sorted(file_hashes.items())),
        "details": {
            "source_etf_bundle_id": etf_manifest.get("bundle_id"),
            "source_etf_manifest_path": str(etf_manifest_path),
            "source_etf_manifest_sha256": _sha256(etf_manifest_path),
            "selected_providers": providers,
            "reference_attempts": reference_attempts,
            "etf_coverage_rows": int(len(etf_coverage)),
            "signal_references_are_non_tradable": True,
        },
    }
    _write_json(output / STRATEGY_MANIFEST_NAME, manifest)
    return manifest


def verify_strategy_data_bundle(bundle_root: str | Path) -> dict[str, Any]:
    root = Path(bundle_root).resolve()
    manifest = _load_manifest(root / STRATEGY_MANIFEST_NAME)
    if manifest.get("status") != "ready":
        raise StrategyDataBundleError(
            f"strategy data bundle is not ready: {manifest.get('missing_symbols', [])}"
        )
    if manifest.get("trade_ready") is not False:
        raise StrategyDataBundleError("strategy data bundle violates trade-ready boundary")
    files = manifest.get("files", {})
    if not isinstance(files, dict):
        raise StrategyDataBundleError("strategy data file inventory must be a mapping")
    for relative, expected in files.items():
        path = root / str(relative)
        if not path.is_file():
            raise StrategyDataBundleError(f"strategy data file is missing: {relative}")
        actual = _sha256(path)
        if actual != str(expected):
            raise StrategyDataBundleError(
                f"strategy data hash mismatch: {relative}: {actual} != {expected}"
            )
    return manifest


def load_strategy_data_bundle(
    bundle_root: str | Path,
    *,
    symbols: Sequence[str] = STRATEGY_DATA_SYMBOLS,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, dict[str, Any]]:
    root = Path(bundle_root).resolve()
    manifest = verify_strategy_data_bundle(root)
    declared = set(str(value) for value in manifest.get("symbols", []))
    requested = [str(value).strip().upper() for value in symbols]
    missing = sorted(set(requested).difference(declared))
    if missing:
        raise StrategyDataBundleError(f"strategy bundle does not declare: {missing}")

    bars: dict[str, pd.DataFrame] = {}
    coverage = pd.read_csv(root / "coverage.csv")
    records = {
        str(row.symbol): row
        for row in coverage.itertuples()
        if str(row.status) == "ready"
    }
    for symbol in requested:
        row = records.get(symbol)
        if row is None:
            raise StrategyDataBundleError(f"strategy data are unavailable: {symbol}")
        path = root / str(row.path)
        bars[symbol] = _normalise_strategy_frame(pd.read_csv(path), symbol)
    return bars, coverage, manifest
