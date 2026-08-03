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
from src.data.adapters.efinance_adapter import EFinanceAdapter
from src.research.selected_pool_guard import resolve_selected_pool

OVERLAP_RATIO_SPREAD_TOLERANCE = 5e-4
PRICE_COLUMNS = ("open", "high", "low", "close")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    output["date"] = pd.to_datetime(output["date"], errors="raise").dt.strftime(
        "%Y-%m-%d"
    )
    for column in ("open", "high", "low", "close", "volume", "amount", "factor"):
        output[column] = pd.to_numeric(output[column], errors="raise")
    return output.sort_values("date").drop_duplicates("date", keep="last").reset_index(
        drop=True
    )


def _append_current_session(
    *,
    symbol: str,
    base: pd.DataFrame,
    overlap_and_append: pd.DataFrame,
    base_cutoff: str,
    cutoff: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    overlap = overlap_and_append.loc[overlap_and_append["date"] == base_cutoff]
    appended = overlap_and_append.loc[overlap_and_append["date"] == cutoff]
    if len(overlap) != 1 or len(appended) != 1:
        raise RuntimeError(
            f"{symbol}: append provider must contain exact overlap/current rows; "
            f"overlap={len(overlap)} current={len(appended)}"
        )
    accepted_overlap = base.loc[base["date"] == base_cutoff]
    if len(accepted_overlap) != 1:
        raise RuntimeError(f"{symbol}: accepted prefix overlap is not unique")

    accepted_row = accepted_overlap.iloc[0]
    source_overlap = overlap.iloc[0]
    ratios: dict[str, float] = {}
    for column in PRICE_COLUMNS:
        source_value = float(source_overlap[column])
        accepted_value = float(accepted_row[column])
        if source_value <= 0 or accepted_value <= 0:
            raise RuntimeError(f"{symbol}: invalid overlap {column}")
        ratios[column] = accepted_value / source_value
    ratio_values = list(ratios.values())
    ratio_anchor = sum(ratio_values) / len(ratio_values)
    ratio_spread = max(ratio_values) / min(ratio_values) - 1.0
    if ratio_spread > OVERLAP_RATIO_SPREAD_TOLERANCE:
        raise RuntimeError(
            f"{symbol}: overlap OHLC ratios are not proportional; spread={ratio_spread}"
        )

    row = appended.iloc[0].copy()
    for column in PRICE_COLUMNS:
        row[column] = float(row[column]) * ratio_anchor
    row["factor"] = 1.0
    extended = pd.concat([base, pd.DataFrame([row])], ignore_index=True)
    extended = extended.sort_values("date").drop_duplicates("date", keep="last")
    if str(extended.iloc[-1]["date"]) != cutoff or len(extended) != len(base) + 1:
        raise RuntimeError(f"{symbol}: appended output is not an exact one-session extension")
    return extended.reset_index(drop=True), {
        "overlap_date": base_cutoff,
        "append_date": cutoff,
        "adjustment_method": "proportional_overlap_anchor_v1",
        "price_ratio_anchor": ratio_anchor,
        "price_ratio_spread": ratio_spread,
        "price_ratio_spread_tolerance": OVERLAP_RATIO_SPREAD_TOLERANCE,
        "accepted_overlap": {column: float(accepted_row[column]) for column in PRICE_COLUMNS},
        "append_provider_overlap": {
            column: float(source_overlap[column]) for column in PRICE_COLUMNS
        },
        "append_provider_raw_current": {
            column: float(appended.iloc[0][column]) for column in PRICE_COLUMNS
        },
        "canonical_current": {column: float(row[column]) for column in PRICE_COLUMNS},
    }


def fetch_shard(
    *,
    output_root: Path,
    shard_index: int,
    shard_count: int,
    start: str,
    cutoff: str,
    base_cutoff: str | None = None,
    append_provider: str | None = None,
) -> dict[str, Any]:
    if shard_count < 1 or not 0 <= shard_index < shard_count:
        raise ValueError("invalid shard index/count")
    if append_provider not in {None, "efinance"}:
        raise ValueError(f"unsupported append provider: {append_provider}")
    if bool(base_cutoff) != bool(append_provider):
        raise ValueError("base_cutoff and append_provider must be declared together")
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
    base_csv_root = output_root / "csv_base"
    csv_root.mkdir(parents=True, exist_ok=True)
    if base_cutoff:
        base_csv_root.mkdir(parents=True, exist_ok=True)
    base_adapter = AkShareSinaAdapter(min_interval_seconds=0.75)
    current_adapter = EFinanceAdapter() if append_provider == "efinance" else None
    records: list[dict[str, Any]] = []
    for symbol in selected:
        requested_base_cutoff = base_cutoff or cutoff
        base_result = base_adapter.fetch_daily_bars(
            FetchRequest(
                symbol=symbol,
                market="cn",
                start=start,
                end=requested_base_cutoff,
            )
        )
        base_frame = _normalize(base_result.df)
        if base_frame.empty or str(base_frame.iloc[-1]["date"]) != requested_base_cutoff:
            raise RuntimeError(
                f"{symbol}: base source does not reach {requested_base_cutoff}; "
                f"last={base_frame.iloc[-1]['date'] if not base_frame.empty else None}"
            )

        reconciliation: dict[str, Any] | None = None
        if current_adapter is not None and base_cutoff is not None:
            current_result = current_adapter.fetch_daily_bars(
                FetchRequest(
                    symbol=symbol,
                    market="cn",
                    start=base_cutoff,
                    end=cutoff,
                )
            )
            current_frame = _normalize(current_result.df)
            frame, reconciliation = _append_current_session(
                symbol=symbol,
                base=base_frame,
                overlap_and_append=current_frame,
                base_cutoff=base_cutoff,
                cutoff=cutoff,
            )
            base_path = base_csv_root / f"{symbol}.csv"
            base_frame.to_csv(base_path, index=False, lineterminator="\n")
        else:
            current_result = None
            frame = base_frame

        if str(frame.iloc[-1]["date"]) != cutoff:
            raise RuntimeError(f"{symbol}: final frame does not reach cutoff {cutoff}")
        path = csv_root / f"{symbol}.csv"
        frame.to_csv(path, index=False, lineterminator="\n")
        record: dict[str, Any] = {
            "symbol": symbol,
            "provider": (
                "akshare_sina_plus_efinance_append"
                if current_result is not None
                else base_result.provider
            ),
            "base_provider": base_result.provider,
            "base_provider_symbol": base_result.provider_symbol,
            "append_provider": current_result.provider if current_result else None,
            "append_provider_symbol": (
                current_result.provider_symbol if current_result else None
            ),
            "row_count": int(len(frame)),
            "base_row_count": int(len(base_frame)),
            "first_date": str(frame.iloc[0]["date"]),
            "base_last_date": str(base_frame.iloc[-1]["date"]),
            "last_date": str(frame.iloc[-1]["date"]),
            "sha256": _sha256(path),
            "base_sha256": (
                _sha256(base_csv_root / f"{symbol}.csv") if base_cutoff else _sha256(path)
            ),
            "reconciliation": reconciliation,
        }
        records.append(record)
    manifest = {
        "schema_version": "1.1.0",
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
        "base_cutoff": base_cutoff,
        "cutoff": cutoff,
        "provider": (
            "akshare_sina_plus_efinance_append"
            if append_provider
            else "akshare_sina"
        ),
        "append_provider": append_provider,
        "append_semantics": (
            "one_session_append_with_proportional_overlap_anchor_v1"
            if append_provider
            else None
        ),
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
    parser.add_argument("--base-cutoff", default=None)
    parser.add_argument("--append-provider", choices=["efinance"], default=None)
    args = parser.parse_args()
    manifest = fetch_shard(
        output_root=args.output_root,
        shard_index=args.shard_index,
        shard_count=args.shard_count,
        start=args.start,
        cutoff=args.cutoff,
        base_cutoff=args.base_cutoff,
        append_provider=args.append_provider,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
