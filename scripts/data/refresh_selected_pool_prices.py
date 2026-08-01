"""Refresh missing or invalid selected-pool price sources into an isolated build.

The command never overwrites the authoritative source directory. It copies valid
source files into a staging tree, fetches only missing/invalid candidates, writes
source-attempt evidence, validates the exact selected pool, builds a manifest-
bound Qlib provider, and atomically publishes the isolated output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from scripts.build_market_providers import DEFAULT_FIELDS, build_market_provider
from src.data.adapters.akshare_adapter import AkShareAdapter
from src.data.adapters.baostock_adapter import BaoStockAdapter
from src.data.adapters.base import MarketDataAdapter
from src.data.adapters.efinance_adapter import EFinanceAdapter
from src.data.adapters.yfinance_adapter import YFinanceAdapter
from src.data.router import MarketDataRouter
from src.data.validation.schema import validate_market_data
from src.research.selected_pool_guard import resolve_selected_pool

REGISTRY = Path("configs/pools/selected_pool_registry_v1.yaml")
BENCHMARKS = {"cn": "000300", "us": "QQQ"}
CANONICAL_COLUMNS = (
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "factor",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _load_pool(path: Path, market: str) -> list[str]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("selected-pool contract must be a mapping")
    if str(payload.get("market", "")).lower() != market:
        raise ValueError("selected-pool market does not match request")
    symbols = [str(item).strip().upper() for item in payload.get("symbols", [])]
    expected = int(payload.get("candidate_count", 0))
    if expected <= 0 or len(symbols) != expected or len(set(symbols)) != expected:
        raise ValueError("selected-pool identity is not exact")
    return symbols


def _normalize_frame(frame: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    missing = sorted(set(CANONICAL_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"{symbol} is missing columns: {missing}")
    result = frame.loc[:, CANONICAL_COLUMNS].copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    for column in CANONICAL_COLUMNS[1:]:
        result[column] = pd.to_numeric(result[column], errors="coerce")
    if result["date"].isna().any():
        raise ValueError(f"{symbol} contains unparseable dates")
    result = result.sort_values("date").reset_index(drop=True)
    if result["date"].duplicated().any():
        raise ValueError(f"{symbol} contains duplicate dates")
    ok, _, errors = validate_market_data(result, symbol)
    if not ok:
        raise ValueError(f"{symbol} schema validation failed: {errors}")
    return result


def _audit_source(path: Path, symbol: str) -> dict[str, Any]:
    if not path.is_file():
        return {"symbol": symbol, "status": "missing", "errors": ["missing"]}
    try:
        frame = _normalize_frame(pd.read_csv(path), symbol=symbol)
    except Exception as exc:
        return {
            "symbol": symbol,
            "status": "invalid",
            "errors": [f"{type(exc).__name__}: {exc}"],
            "sha256": _sha256(path),
        }
    return {
        "symbol": symbol,
        "status": "ready",
        "rows": int(len(frame)),
        "first_date": frame["date"].min().date().isoformat(),
        "last_date": frame["date"].max().date().isoformat(),
        "sha256": _sha256(path),
    }


def _default_router(market: str) -> MarketDataRouter:
    adapters: list[MarketDataAdapter]
    policy: dict[str, list[str]]
    if market == "cn":
        adapters = [EFinanceAdapter(), AkShareAdapter(), BaoStockAdapter()]
        policy = {"cn": ["efinance", "akshare", "baostock"]}
    elif market == "us":
        adapters = [YFinanceAdapter()]
        policy = {"us": ["yfinance"]}
    else:
        raise ValueError(f"unsupported market: {market}")
    return MarketDataRouter(adapters=adapters, policy=policy)


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    output = frame.copy()
    output["date"] = pd.to_datetime(output["date"]).dt.strftime("%Y-%m-%d")
    output.to_csv(path, index=False, lineterminator="\n")


def _attempts(response: Any) -> list[dict[str, Any]]:
    return [attempt.to_dict() for attempt in response.attempts]


def refresh_selected_pool_prices(
    *,
    root: str | Path,
    market: str,
    source_csv_dir: str | Path,
    output_root: str | Path,
    start: str,
    cutoff: str,
    router: MarketDataRouter | None = None,
) -> dict[str, Any]:
    """Build one isolated, exact selected-pool price source and provider."""

    project_root = Path(root).resolve()
    market_key = str(market).lower()
    binding = resolve_selected_pool(
        market_key,
        registry_path=project_root / REGISTRY,
        authoritative=True,
        require_data_ready=False,
    )
    candidates = _load_pool(binding.pool_spec, market_key)
    benchmark = BENCHMARKS[market_key]
    required = [*candidates, benchmark]

    source_dir = Path(source_csv_dir).resolve()
    destination = Path(output_root).resolve()
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(f"output root is not empty: {destination}")

    before = {
        symbol: _audit_source(source_dir / f"{symbol}.csv", symbol)
        for symbol in required
    }
    targets = [
        symbol for symbol in required if before[symbol]["status"] != "ready"
    ]
    data_router = router or _default_router(market_key)

    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.rmdir()

    with tempfile.TemporaryDirectory(
        prefix=f".{destination.name}-staging-",
        dir=destination.parent,
    ) as temporary:
        stage = Path(temporary) / "payload"
        csv_out = stage / "data" / "csv_source"
        csv_out.mkdir(parents=True)
        records: list[dict[str, Any]] = []

        for symbol in required:
            source_path = source_dir / f"{symbol}.csv"
            output_path = csv_out / f"{symbol}.csv"
            if before[symbol]["status"] == "ready":
                shutil.copy2(source_path, output_path)
                records.append(
                    {
                        "symbol": symbol,
                        "action": "copied_verified_source",
                        "source_sha256": before[symbol]["sha256"],
                        "output_sha256": _sha256(output_path),
                        "attempts": [],
                    }
                )
                continue

            response = data_router.fetch_daily_bars(
                symbol=symbol,
                market=market_key,
                start=start,
                end=cutoff,
                validate=True,
            )
            if not response.ok or response.result is None:
                raise RuntimeError(
                    f"all providers failed for {market_key}:{symbol}: "
                    f"{json.dumps(_attempts(response), sort_keys=True)}"
                )
            frame = _normalize_frame(response.result.df, symbol=symbol)
            frame = frame.loc[frame["date"] <= pd.Timestamp(cutoff)].copy()
            if frame.empty:
                raise RuntimeError(f"provider returned no rows through cutoff for {symbol}")
            _write_csv(output_path, frame)
            records.append(
                {
                    "symbol": symbol,
                    "action": "fetched_replacement",
                    "provider": response.result.provider,
                    "provider_symbol": response.result.provider_symbol,
                    "output_sha256": _sha256(output_path),
                    "rows": int(len(frame)),
                    "first_date": frame["date"].min().date().isoformat(),
                    "last_date": frame["date"].max().date().isoformat(),
                    "attempts": _attempts(response),
                }
            )

        after = {
            symbol: _audit_source(csv_out / f"{symbol}.csv", symbol)
            for symbol in required
        }
        blocked = [
            symbol for symbol in required if after[symbol]["status"] != "ready"
        ]
        if blocked:
            raise RuntimeError(f"isolated selected-pool build remains blocked: {blocked}")

        provider_dir = stage / "data" / "providers" / market_key
        provider_manifest = build_market_provider(
            csv_dir=csv_out,
            provider_dir=provider_dir,
            market=market_key,
            include_fields=DEFAULT_FIELDS,
        )
        manifest = {
            "schema_version": "1.0",
            "evidence_type": "selected_pool_price_refresh_v1",
            "market": market_key,
            "pool_id": binding.pool_id,
            "candidate_count": len(candidates),
            "benchmark": benchmark,
            "start": start,
            "cutoff": cutoff,
            "target_count": len(targets),
            "targets": targets,
            "before": before,
            "after": after,
            "records": records,
            "provider_identity_sha256": provider_manifest.get(
                "provider_identity_sha256"
            ),
            "all_sources_ready": True,
            "research_only": True,
            "trade_ready": False,
        }
        _write_json(
            stage / "artifacts" / "selected_pool_price_refresh_manifest.json",
            manifest,
        )
        stage.replace(destination)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--market", choices=("cn", "us"), required=True)
    parser.add_argument(
        "--source-csv-dir",
        type=Path,
        default=Path("data/csv_clean"),
    )
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--cutoff", default="2026-06-18")
    args = parser.parse_args()

    payload = refresh_selected_pool_prices(
        root=args.root,
        market=args.market,
        source_csv_dir=args.source_csv_dir,
        output_root=args.output_root,
        start=args.start,
        cutoff=args.cutoff,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
