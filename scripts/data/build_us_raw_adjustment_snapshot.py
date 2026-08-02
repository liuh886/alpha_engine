"""Fetch and materialize deterministic raw-plus-adjustment US research data.

The command has two stages:

- ``fetch`` stores immutable raw OHLCV plus Adj Close for US87 and QQQ;
- ``materialize`` derives canonical adjusted bars and builds a Qlib provider.

A frozen prefix is append-only by default. Historical revisions fail closed and
must be handled as a separate evidence revision.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from scripts.build_market_providers import DEFAULT_FIELDS, build_market_provider
from src.data.us_raw_adjustment_snapshot import (
    FORMULA_TEXT,
    FORMULA_VERSION,
    HistoricalRevisionError,
    derive_adjusted_bars,
    directory_identity,
    enforce_append_only,
    formula_identity_sha256,
    normalize_yahoo_raw,
    validate_raw_contract,
    write_model_bars,
    write_raw_contract,
)
from src.research.selected_pool_guard import resolve_selected_pool

BENCHMARK = "QQQ"
RAW_MANIFEST = "raw_snapshot_manifest.json"
CONTRACT_MANIFEST = "raw_adjustment_contract_manifest.json"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _load_symbols(root: Path) -> tuple[str, list[str]]:
    binding = resolve_selected_pool(
        "us",
        registry_path=root / "configs/pools/selected_pool_registry_v1.yaml",
        authoritative=True,
        require_data_ready=False,
    )
    payload = yaml.safe_load(binding.pool_spec.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("US selected-pool spec must be a mapping")
    symbols = [str(value).strip().upper() for value in payload.get("symbols", [])]
    expected = int(payload.get("candidate_count", 0))
    if expected != 87 or len(symbols) != expected or len(set(symbols)) != expected:
        raise ValueError("raw-adjustment contract requires the exact 87-symbol US pool")
    if BENCHMARK in symbols:
        raise ValueError("QQQ must remain outside the candidate pool")
    if "TIGO" not in symbols or "TYGO" not in symbols:
        raise ValueError("US87 identity contract requires distinct TIGO and TYGO")
    return binding.pool_id, [*symbols, BENCHMARK]


def _download_symbol(symbol: str, *, start: str, cutoff: str) -> pd.DataFrame:
    import yfinance as yf

    provider_end = (pd.Timestamp(cutoff) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore", message=".*Timestamp.utcnow is deprecated.*"
                )
                frame = yf.download(
                    symbol,
                    start=start,
                    end=provider_end,
                    progress=False,
                    auto_adjust=False,
                    repair=False,
                    threads=False,
                )
            normalized = normalize_yahoo_raw(frame)
            normalized = normalized.loc[
                (normalized["date"] >= pd.Timestamp(start))
                & (normalized["date"] <= pd.Timestamp(cutoff))
            ].reset_index(drop=True)
            if normalized.empty:
                raise ValueError(f"no rows remained after clipping {symbol}")
            return normalized
        except Exception as exc:  # pragma: no cover - live provider path
            last_error = exc
            if attempt < 2:
                time.sleep(2.0)
    raise RuntimeError(f"Yahoo raw download failed for {symbol}: {last_error}")


def fetch_raw_snapshot(
    *,
    root: Path,
    output_dir: Path,
    start: str,
    cutoff: str,
    previous_raw_dir: Path | None = None,
) -> dict[str, Any]:
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"raw output directory is not empty: {output_dir}")
    pool_id, symbols = _load_symbols(root)
    output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    revision_reports: dict[str, Any] = {}

    for symbol in symbols:
        frame = _download_symbol(symbol, start=start, cutoff=cutoff)
        if previous_raw_dir is not None:
            previous_path = previous_raw_dir / f"{symbol}.csv"
            if not previous_path.is_file():
                raise FileNotFoundError(
                    f"previous frozen snapshot is missing {symbol}: {previous_path}"
                )
            previous = validate_raw_contract(pd.read_csv(previous_path))
            revision_reports[symbol] = enforce_append_only(previous, frame)
        file_hash = write_raw_contract(output_dir / f"{symbol}.csv", frame)
        records.append(
            {
                "symbol": symbol,
                "rows": int(len(frame)),
                "first_date": frame["date"].min().date().isoformat(),
                "last_date": frame["date"].max().date().isoformat(),
                "sha256": file_hash,
                "provider_symbol": symbol,
            }
        )

    identity = directory_identity(output_dir)
    manifest = {
        "schema_version": "1.0",
        "evidence_type": "us_raw_adjustment_source_snapshot",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "market": "us",
        "pool_id": pool_id,
        "candidate_count": 87,
        "benchmark": BENCHMARK,
        "instrument_count": len(symbols),
        "start": start,
        "cutoff": cutoff,
        "source": {
            "provider": "yahoo_via_yfinance",
            "auto_adjust": False,
            "repair": False,
            "retained_fields": [
                "raw_open",
                "raw_high",
                "raw_low",
                "raw_close",
                "adj_close",
                "volume",
                "adjustment_ratio",
            ],
        },
        "raw_snapshot": identity,
        "append_only_gate": {
            "previous_snapshot_supplied": previous_raw_dir is not None,
            "status": (
                "historical_prefix_exact"
                if previous_raw_dir is not None
                else "initial_snapshot"
            ),
            "reports": revision_reports,
        },
        "records": records,
        "research_only": True,
        "trade_ready": False,
    }
    _write_json(output_dir.parent / RAW_MANIFEST, manifest)
    return manifest


def materialize_snapshot(
    *,
    root: Path,
    raw_dir: Path,
    output_root: Path,
) -> dict[str, Any]:
    if output_root.exists() and any(output_root.iterdir()):
        raise FileExistsError(f"materialized output root is not empty: {output_root}")
    pool_id, symbols = _load_symbols(root)
    actual = sorted(path.stem for path in raw_dir.glob("*.csv"))
    if actual != sorted(symbols):
        missing = sorted(set(symbols) - set(actual))
        extra = sorted(set(actual) - set(symbols))
        raise ValueError(
            f"raw snapshot instrument mismatch: missing={missing}, extra={extra}"
        )

    model_dir = output_root / "data/csv_source"
    model_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    for symbol in symbols:
        raw = validate_raw_contract(pd.read_csv(raw_dir / f"{symbol}.csv"))
        model = derive_adjusted_bars(raw)
        model_hash = write_model_bars(model_dir / f"{symbol}.csv", model)
        records.append(
            {
                "symbol": symbol,
                "raw_sha256": directory_identity(raw_dir)["files"][
                    actual.index(symbol)
                ]["sha256"],
                "model_input_sha256": model_hash,
                "rows": int(len(model)),
            }
        )

    provider_dir = output_root / "data/providers/us"
    provider_manifest = build_market_provider(
        csv_dir=model_dir,
        provider_dir=provider_dir,
        market="us",
        include_fields=DEFAULT_FIELDS,
    )
    raw_identity = directory_identity(raw_dir)
    model_identity = directory_identity(model_dir)
    manifest = {
        "schema_version": "1.0",
        "evidence_type": "us_raw_adjustment_materialized_provider",
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "market": "us",
        "pool_id": pool_id,
        "candidate_count": 87,
        "benchmark": BENCHMARK,
        "instrument_count": len(symbols),
        "formula": {
            "version": FORMULA_VERSION,
            "text": FORMULA_TEXT,
            "identity_sha256": formula_identity_sha256(),
            "adjusted_close_tie": "exact",
            "economic_tolerance": 1e-8,
        },
        "raw_snapshot": raw_identity,
        "model_input_snapshot": model_identity,
        "provider_identity_sha256": provider_manifest[
            "provider_identity_sha256"
        ],
        "provider_manifest": provider_manifest,
        "records": records,
        "research_only": True,
        "trade_ready": False,
        "decision": "deterministic_raw_adjustment_contract_ready",
    }
    _write_json(output_root / "artifacts" / CONTRACT_MANIFEST, manifest)
    return manifest


def _copy_raw_snapshot(source: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")
    shutil.copytree(source, destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    fetch_parser = subparsers.add_parser("fetch")
    fetch_parser.add_argument("--output-dir", type=Path, required=True)
    fetch_parser.add_argument("--start", default="2021-01-01")
    fetch_parser.add_argument("--cutoff", default="2026-07-31")
    fetch_parser.add_argument("--previous-raw-dir", type=Path, default=None)

    materialize_parser = subparsers.add_parser("materialize")
    materialize_parser.add_argument("--raw-dir", type=Path, required=True)
    materialize_parser.add_argument("--output-root", type=Path, required=True)
    materialize_parser.add_argument(
        "--retain-raw-copy",
        action="store_true",
        help="Copy the frozen raw snapshot into the materialized evidence root.",
    )

    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == "fetch":
        result = fetch_raw_snapshot(
            root=root,
            output_dir=args.output_dir.resolve(),
            start=args.start,
            cutoff=args.cutoff,
            previous_raw_dir=(
                None
                if args.previous_raw_dir is None
                else args.previous_raw_dir.resolve()
            ),
        )
    else:
        output_root = args.output_root.resolve()
        raw_dir = args.raw_dir.resolve()
        result = materialize_snapshot(
            root=root,
            raw_dir=raw_dir,
            output_root=output_root,
        )
        if args.retain_raw_copy:
            _copy_raw_snapshot(raw_dir, output_root / "data/raw_adjustment_source")
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    try:
        main()
    except HistoricalRevisionError as exc:
        raise SystemExit(f"historical revision blocked: {exc}") from exc
