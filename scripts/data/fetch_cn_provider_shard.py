"""Fetch one deterministic shard of the CN130 plus CSI 300 provider snapshot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.data.refresh_selected_pool_prices import BENCHMARKS, _load_pool
from src.data.adapters.akshare_sina_adapter import AkShareSinaAdapter
from src.data.adapters.base import FetchRequest
from src.research.selected_pool_guard import resolve_selected_pool


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_shard(
    *,
    output_root: Path,
    shard_index: int,
    shard_count: int,
    start: str,
    cutoff: str,
) -> dict[str, Any]:
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("invalid shard index/count")
    binding = resolve_selected_pool(
        "cn",
        registry_path=Path("configs/pools/selected_pool_registry_v1.yaml"),
        authoritative=True,
        require_data_ready=False,
    )
    candidates = _load_pool(binding.pool_spec, "cn")
    all_symbols = sorted({*candidates, BENCHMARKS["cn"]})
    if len(candidates) != 130 or len(all_symbols) != 131:
        raise RuntimeError(
            f"unexpected CN pool: candidates={len(candidates)}, total={len(all_symbols)}"
        )
    selected = [
        symbol
        for position, symbol in enumerate(all_symbols)
        if position % shard_count == shard_index
    ]
    csv_root = output_root / "csv"
    csv_root.mkdir(parents=True, exist_ok=True)
    adapter = AkShareSinaAdapter(min_interval_seconds=0.75)
    records: list[dict[str, Any]] = []
    for symbol in selected:
        result = adapter.fetch_daily_bars(
            FetchRequest(symbol=symbol, market="cn", start=start, end=cutoff)
        )
        frame = result.df.copy()
        frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.strftime(
            "%Y-%m-%d"
        )
        if frame.empty or str(frame.iloc[-1]["date"]) != cutoff:
            raise RuntimeError(
                f"{symbol}: source does not reach cutoff {cutoff}; "
                f"last={frame.iloc[-1]['date'] if not frame.empty else None}"
            )
        path = csv_root / f"{symbol}.csv"
        frame.to_csv(path, index=False)
        records.append(
            {
                "symbol": symbol,
                "provider": result.provider,
                "provider_symbol": result.provider_symbol,
                "row_count": int(len(frame)),
                "first_date": str(frame.iloc[0]["date"]),
                "last_date": str(frame.iloc[-1]["date"]),
                "sha256": _sha256(path),
            }
        )
    manifest = {
        "schema_version": "1.0.0",
        "status": "complete",
        "market": "cn",
        "pool_id": binding.pool_id,
        "pool_hash": binding.pool_hash,
        "candidate_count": len(candidates),
        "total_symbol_count": len(all_symbols),
        "shard_index": shard_index,
        "shard_count": shard_count,
        "selected_symbol_count": len(selected),
        "start": start,
        "cutoff": cutoff,
        "provider": "akshare_sina",
        "records": records,
        "research_only": True,
        "trade_ready": False,
    }
    manifest_path = output_root / f"shard-{shard_index}.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--start", default="2021-01-01")
    parser.add_argument("--cutoff", default="2026-07-31")
    args = parser.parse_args()
    manifest = fetch_shard(
        output_root=args.output_root,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
        start=args.start,
        cutoff=args.cutoff,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
