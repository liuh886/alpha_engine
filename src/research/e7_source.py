"""As-observed rolling daily source, reusing the canonical Yahoo adapter."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

import numpy as np
import pandas as pd
from exchange_calendars import get_calendar

from src.data.adapters.base import FetchRequest
from src.data.adapters.yfinance_adapter import YFinanceAdapter
from src.research.e5_score_reconstruction import sha
from src.research.study_workspace import save_receipt_exclusive


def sessions(day: str, count: int) -> list[str]:
    cal = get_calendar("XNYS")
    start = cal.session_offset(day, -count + 1)
    return cal.sessions_in_range(start, day).strftime("%Y-%m-%d").tolist()


def validate_panel(frame: pd.DataFrame, cfg: dict, day: str) -> None:
    symbols = set(cfg["symbols"]) | {cfg["benchmark"]}
    if set(frame["symbol"]) != symbols:
        raise ValueError("E7 source pool incomplete: no candidate dropping")
    expected = sessions(day, cfg["source"]["history_sessions"])
    if frame.duplicated(["symbol", "date"]).any():
        raise ValueError("duplicate E7 market observation")
    for symbol, part in frame.groupby("symbol"):
        if part["date"].sort_values().tolist() != expected:
            raise ValueError(f"E7 source calendar gap: {symbol}")
    for field in ("close", "raw_close"):
        if not np.isfinite(frame[field]).all() or (frame[field] <= 0).any():
            raise ValueError("E7 requires positive finite adjusted and raw closes")
    if not np.isfinite(frame["volume"]).all() or (frame["volume"] < 0).any():
        raise ValueError("invalid E7 reported volume")


def collect(root: Path, cfg: dict, day: str) -> dict:
    expected = sessions(day, cfg["source"]["history_sessions"])
    attempt = root / "sources" / ("attempt-" + uuid.uuid4().hex)
    raw_root = attempt / "raw"
    adapter = YFinanceAdapter(evidence_root=raw_root)
    rows = []
    proof = []
    for symbol in [*cfg["symbols"], cfg["benchmark"]]:
        before = set(raw_root.glob("request-*"))
        result = adapter.fetch_daily_bars(FetchRequest(symbol, "us", expected[0], day))
        created = set(raw_root.glob("request-*")) - before
        if len(created) != 1:
            raise ValueError("canonical adapter did not retain exactly one raw response")
        folder = created.pop()
        record = json.loads((folder / "request.json").read_bytes())
        if (
            record["symbol"] != symbol
            or record["provider_symbol"] != symbol
            or sha(folder / "raw.parquet") != record["raw_sha256"]
        ):
            raise ValueError("provider raw symbol/hash identity mismatch")
        raw = pd.read_parquet(folder / "raw.parquet")
        if isinstance(raw.columns, pd.MultiIndex):
            if set(raw.columns.get_level_values(1)) != {symbol}:
                raise ValueError("provider returned another security")
            raw.columns = raw.columns.get_level_values(0)
        required = {"Close", "Adj Close", "Dividends", "Stock Splits", "Volume"}
        if not required <= set(raw.columns):
            raise ValueError("raw action/adjustment fields unavailable")
        raw.index = raw.index.strftime("%Y-%m-%d")
        panel = result.df.copy()
        panel["date"] = panel["date"].dt.strftime("%Y-%m-%d")
        for key, column in (
            ("raw_close", "Close"),
            ("dividend", "Dividends"),
            ("split", "Stock Splits"),
        ):
            panel[key] = [float(raw.loc[d, column]) for d in panel["date"]]
        panel["symbol"] = symbol
        rows.append(panel)
        proof.append(
            {
                "symbol": symbol,
                "observed_at_utc": record["retrieved_at_utc"],
                "request_path": (folder / "request.json").relative_to(root).as_posix(),
                "request_sha256": sha(folder / "request.json"),
                "raw_path": (folder / "raw.parquet").relative_to(root).as_posix(),
                "raw_sha256": record["raw_sha256"],
                "normalization_sha256": sha(folder / "normalization.json"),
            }
        )
        print("E7_SOURCE", len(rows), symbol, day, flush=True)
    frame = pd.concat(rows, ignore_index=True).sort_values(["symbol", "date"])
    validate_panel(frame, cfg, day)
    path = attempt / "market.parquet"
    frame.to_parquet(path, index=False)
    available = max(p["observed_at_utc"] for p in proof)
    if pd.Timestamp(available) < get_calendar("XNYS").session_close(day):
        raise ValueError("market snapshot observed before its session closed")
    record = {
        "schema_version": "e7_as_seen_market_v1",
        "session": day,
        "first_seen_at_utc": datetime.now(timezone.utc).isoformat(),
        "available_at_utc": available,
        "frame_path": path.relative_to(root).as_posix(),
        "frame_sha256": sha(path),
        "source_receipts": proof,
        "rows": len(frame),
        "source_symbols": len(proof),
        "volume_units_certified": False,
        "action_available_at_certified": False,
        "price_policy": "same_snapshot_adj_close_ratios; observed_raw_current_close_fill_reference",
        "research_only": True,
        "trade_ready": False,
        "pit_certified": False,
    }
    save_receipt_exclusive(root / "market" / f"{day}.json", record)
    return record


def read(root: Path, day: str, cfg: dict) -> tuple[dict, pd.DataFrame]:
    record = json.loads((root / "market" / f"{day}.json").read_bytes())
    path = (root / record["frame_path"]).resolve()
    if not path.is_relative_to(root.resolve()) or sha(path) != record["frame_sha256"]:
        raise ValueError("retained source snapshot path/hash mismatch")
    frame = pd.read_parquet(path)
    validate_panel(frame, cfg, day)
    return record, frame
