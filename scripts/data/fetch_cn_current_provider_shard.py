"""Append one completed CN session to the immutable accepted provider prefix."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from scripts.data.fetch_cn_provider_shard import (
    _append_current_session,
    _normalize,
    _sha256,
)
from scripts.data.refresh_selected_pool_prices import BENCHMARKS, _load_pool
from src.data.adapters.akshare_sina_adapter import AkShareSinaAdapter
from src.data.adapters.base import FetchRequest
from src.data.adapters.sina_close_snapshot_adapter import SinaCloseSnapshotAdapter
from src.research.selected_pool_guard import resolve_selected_pool


def fetch_shard(
    *,
    output_root: Path,
    shard_index: int,
    shard_count: int,
    start: str,
    base_cutoff: str,
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
    pool_hash = hashlib.sha256(binding.pool_spec.read_bytes()).hexdigest()
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
    base_csv_root = output_root / "csv_base"
    csv_root.mkdir(parents=True, exist_ok=True)
    base_csv_root.mkdir(parents=True, exist_ok=True)
    base_adapter = AkShareSinaAdapter(min_interval_seconds=0.75)
    close_adapter = SinaCloseSnapshotAdapter()
    records: list[dict[str, Any]] = []

    for position, symbol in enumerate(selected):
        base_result = base_adapter.fetch_daily_bars(
            FetchRequest(
                symbol=symbol,
                market="cn",
                start=start,
                end=base_cutoff,
            )
        )
        base_frame = _normalize(base_result.df)
        if base_frame.empty or str(base_frame.iloc[-1]["date"]) != base_cutoff:
            raise RuntimeError(
                f"{symbol}: accepted-prefix source does not reach {base_cutoff}"
            )
        if position:
            time.sleep(0.5)
        close_result = close_adapter.fetch_daily_bars(
            FetchRequest(
                symbol=symbol,
                market="cn",
                start=base_cutoff,
                end=cutoff,
            )
        )
        close_frame = _normalize(close_result.df)
        extended, reconciliation = _append_current_session(
            symbol=symbol,
            base=base_frame,
            overlap_and_append=close_frame,
            base_cutoff=base_cutoff,
            cutoff=cutoff,
        )
        base_path = base_csv_root / f"{symbol}.csv"
        path = csv_root / f"{symbol}.csv"
        base_frame.to_csv(base_path, index=False, lineterminator="\n")
        extended.to_csv(path, index=False, lineterminator="\n")
        records.append(
            {
                "symbol": symbol,
                "provider": "akshare_sina_plus_sina_close_snapshot",
                "base_provider": base_result.provider,
                "base_provider_symbol": base_result.provider_symbol,
                "append_provider": close_result.provider,
                "append_provider_symbol": close_result.provider_symbol,
                "row_count": int(len(extended)),
                "base_row_count": int(len(base_frame)),
                "first_date": str(extended.iloc[0]["date"]),
                "base_last_date": str(base_frame.iloc[-1]["date"]),
                "last_date": str(extended.iloc[-1]["date"]),
                "sha256": _sha256(path),
                "base_sha256": _sha256(base_path),
                "reconciliation": reconciliation,
            }
        )

    manifest = {
        "schema_version": "1.2.0",
        "status": "complete",
        "market": "cn",
        "pool_id": binding.pool_id,
        "pool_hash": pool_hash,
        "candidate_count": len(candidates),
        "total_symbol_count": len(all_symbols),
        "shard_index": shard_index,
        "shard_count": shard_count,
        "selected_symbol_count": len(selected),
        "start": start,
        "base_cutoff": base_cutoff,
        "cutoff": cutoff,
        "provider": "akshare_sina_plus_sina_close_snapshot",
        "append_provider": "sina_close_snapshot",
        "append_semantics": "one_completed_session_with_raw_overlap_anchor_v1",
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
    parser.add_argument("--base-cutoff", required=True)
    parser.add_argument("--cutoff", required=True)
    args = parser.parse_args()
    result = fetch_shard(
        output_root=args.output_root,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
        start=args.start,
        base_cutoff=args.base_cutoff,
        cutoff=args.cutoff,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
