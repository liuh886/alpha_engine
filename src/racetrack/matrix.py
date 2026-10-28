"""Racetrack market price matrix loader and calendar alignment.

Loads primary market evidence JSON files, aligns them strictly to official
exchange calendars (XNYS for US), prohibits silent forward-fills, and produces
an immutable PriceMatrix with deterministic SHA-256 fingerprint.
"""

from __future__ import annotations

from collections.abc import Sequence
import hashlib
import io
import json
from pathlib import Path
from typing import Any

import exchange_calendars as xcals
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import yaml

from src.racetrack.contracts import (
    CalendarSessionError,
    DataQualificationError,
    PITViolationError,
    PriceMatrix,
)

MARKET_CALENDAR_MAP: dict[str, str] = {
    "us": "XNYS",
    "cn": "XSHG",
}

DEFAULT_REFERENCE_SYMBOLS: dict[str, str] = {
    "us": "QQQ",
    "cn": "000300",
}


def resolve_reference_symbol(
    market: str,
    ref_config: dict[str, Any] | None = None,
    catalog_symbols: set[str] | Sequence[str] | dict[str, Any] | None = None,
    catalog_path: Path | None = None,
) -> str:
    """Resolve reference benchmark symbol for market, aligning catalog and reference registry.

    Supports both '000300' and '000300.SH' for CN, preferring catalog registration.
    """
    market_lower = market.lower()
    if market_lower == "us":
        return "QQQ"
    elif market_lower == "cn":
        candidates = ("000300", "000300.SH", "SH000300", "sh.000300")
        if catalog_symbols is not None:
            if isinstance(catalog_symbols, dict):
                if "benchmark" in catalog_symbols and catalog_symbols["benchmark"] in candidates:
                    return str(catalog_symbols["benchmark"])
                sym_list = catalog_symbols.get("symbols", [])
                if isinstance(sym_list, list):
                    sym_set = {
                        item.get("symbol")
                        for item in sym_list
                        if isinstance(item, dict) and "symbol" in item
                    }
                else:
                    sym_set = set(sym_list)
            else:
                sym_set = set(catalog_symbols)
            for c in candidates:
                if c in sym_set:
                    return c

        if catalog_path is not None and catalog_path.exists():
            try:
                cat_data = json.loads(catalog_path.read_text(encoding="utf-8"))
                cat_bench = cat_data.get("benchmark")
                if cat_bench in candidates:
                    return str(cat_bench)
                raw_syms = cat_data.get("symbols", [])
                if isinstance(raw_syms, list):
                    registered = {
                        item.get("symbol")
                        for item in raw_syms
                        if isinstance(item, dict) and "symbol" in item
                    }
                elif isinstance(raw_syms, dict):
                    registered = set(raw_syms.keys())
                else:
                    registered = set()
                for c in candidates:
                    if c in registered:
                        return c
            except Exception:
                pass
        return "000300"
    raise ValueError(f"Unsupported market: {market}")


def load_price_matrix(
    market: str,
    pool_id: str,
    start_date: str,
    end_date: str,
    as_of_cutoff: str,
    root_path: Path,
    reference_symbol: str | None = None,
) -> PriceMatrix:
    """Load canonical market price matrix P(t, s) aligned to official exchange calendar.

    Args:
        market: Target market identifier ('us' or 'cn').
        pool_id: Universe candidate pool ID ('us_selected_equities_v2' or 'cn_selected_equities_v3').
        start_date: Start session date string (YYYY-MM-DD).
        end_date: End session date string (YYYY-MM-DD).
        as_of_cutoff: Point-in-time publication cutoff date (YYYY-MM-DD).
        root_path: Repository root directory Path.
        reference_symbol: Optional explicit reference symbol.

    Returns:
        Immutable PriceMatrix containing prices DataFrame and cryptographic manifest sha256.

    Raises:
        CalendarSessionError: If date ranges contain no valid sessions.
        FileNotFoundError: If pool config or evidence files are missing.
    """
    market_lower = market.lower()
    if market_lower not in MARKET_CALENDAR_MAP:
        raise ValueError(
            f"Unsupported market '{market}'. Must be one of {list(MARKET_CALENDAR_MAP.keys())}"
        )

    calendar_name = MARKET_CALENDAR_MAP[market_lower]
    cal = xcals.get_calendar(calendar_name)

    # 1. Resolve trading calendar sessions & PIT cutoff validation
    if end_date > as_of_cutoff:
        raise PITViolationError(
            f"Requested end_date '{end_date}' extends beyond as_of_cutoff '{as_of_cutoff}'. "
            f"Silent truncation is strictly prohibited."
        )
    if start_date > end_date:
        raise CalendarSessionError(f"start_date '{start_date}' exceeds end_date '{end_date}'")

    cal_sessions = cal.sessions_in_range(start_date, end_date)
    sessions = tuple(s.strftime("%Y-%m-%d") for s in cal_sessions)
    if not sessions:
        raise CalendarSessionError(
            f"No valid trading sessions found in range [{start_date}, {end_date}] on {calendar_name}"
        )

    # 2. Read candidate pool configuration
    pool_config_path = root_path / "configs" / "research_universes" / f"{pool_id}.yaml"
    if not pool_config_path.exists():
        raise FileNotFoundError(f"Universe pool config not found: {pool_config_path}")

    with open(pool_config_path, "r", encoding="utf-8") as f:
        pool_data = yaml.safe_load(f)

    candidate_symbols = tuple(str(s) for s in pool_data.get("symbols", []))
    if not candidate_symbols:
        raise ValueError(f"Pool '{pool_id}' contains no candidate symbols in {pool_config_path}")

    # 3. Read reference instrument configuration
    catalog_path = (
        root_path / "data" / "research" / "market_evidence" / market_lower / "catalog.json"
    )
    ref_config_path = root_path / "configs" / "pools" / "reference_instrument_registry_v1.yaml"
    ref_data: dict[str, Any] = {}
    if ref_config_path.exists():
        with open(ref_config_path, "r", encoding="utf-8") as f:
            ref_data = yaml.safe_load(f) or {}

    if reference_symbol is not None:
        if market_lower == "cn" and reference_symbol in ("000300.SH", "SH000300", "sh.000300"):
            ref_symbol = "000300"
        else:
            ref_symbol = reference_symbol
    else:
        ref_symbol = resolve_reference_symbol(
            market_lower,
            ref_config=ref_data,
            catalog_path=catalog_path,
        )

    all_symbols = candidate_symbols + (ref_symbol,)

    # 4. Verify data qualification & catalog.json registration
    catalog_sha256 = ""
    if catalog_path.exists():
        cat_bytes = catalog_path.read_bytes()
        catalog_sha256 = hashlib.sha256(cat_bytes).hexdigest()
        cat_data = json.loads(cat_bytes.decode("utf-8"))
        raw_symbols = cat_data.get("symbols", [])
        if isinstance(raw_symbols, list):
            registered_symbols = {
                item.get("symbol") for item in raw_symbols if isinstance(item, dict)
            }
        elif isinstance(raw_symbols, dict):
            registered_symbols = set(raw_symbols.keys())
        else:
            registered_symbols = set()

        for sym in all_symbols:
            if sym not in registered_symbols:
                if sym in ("000300.SH", "SH000300") and "000300" in registered_symbols:
                    continue
                raise DataQualificationError(
                    f"Symbol '{sym}' is not registered in market evidence catalog '{catalog_path}'"
                )

    # 5. Load evidence JSON files
    evidence_dir = root_path / "data" / "research" / "market_evidence" / market_lower / "symbols"
    source_evidence_hashes: dict[str, str] = {}
    symbol_close_series: dict[str, dict[str, float]] = {}

    for symbol in all_symbols:
        symbol_file = evidence_dir / f"{symbol}.json"
        if not symbol_file.exists():
            if symbol in ("000300.SH", "SH000300") and (evidence_dir / "000300.json").exists():
                symbol_file = evidence_dir / "000300.json"
            else:
                raise FileNotFoundError(
                    f"Market evidence JSON for symbol '{symbol}' not found at {symbol_file}"
                )
            raise FileNotFoundError(
                f"Market evidence JSON for symbol '{symbol}' not found at {symbol_file}"
            )

        file_bytes = symbol_file.read_bytes()
        source_evidence_hashes[symbol] = hashlib.sha256(file_bytes).hexdigest()

        evidence_obj: dict[str, Any] = json.loads(file_bytes.decode("utf-8"))
        bars = evidence_obj.get("bars", [])

        # Index bars by date time string up to cutoff
        bar_dict: dict[str, float] = {}
        for bar in bars:
            bar_time = str(bar.get("time", ""))
            if bar_time <= as_of_cutoff:
                close_val = bar.get("close")
                if close_val is not None:
                    bar_dict[bar_time] = float(close_val)

        symbol_close_series[symbol] = bar_dict

    # 5. Build price matrix DataFrame without forward-filling missing values
    price_data: dict[str, list[float]] = {}
    for symbol in all_symbols:
        s_dict = symbol_close_series[symbol]
        col_values: list[float] = []
        for sess in sessions:
            if sess in s_dict:
                col_values.append(s_dict[sess])
            else:
                col_values.append(np.nan)  # Prohibit silent forward fill
        price_data[symbol] = col_values

    prices_df = pd.DataFrame(data=price_data, index=list(sessions))
    prices_df.index.name = "session"

    # 6. Compute deterministic canonical Parquet bytes and SHA-256
    arrow_arrays = [pa.array(list(sessions), type=pa.string())]
    arrow_names = ["session"]
    for symbol in all_symbols:
        arrow_names.append(symbol)
        arrow_arrays.append(pa.array(price_data[symbol], type=pa.float64()))

    arrow_table = pa.Table.from_arrays(arrow_arrays, names=arrow_names)
    buf = io.BytesIO()
    pq.write_table(arrow_table, buf, compression=None)
    matrix_sha256 = hashlib.sha256(buf.getvalue()).hexdigest()

    return PriceMatrix(
        market=market_lower,
        pool_id=pool_id,
        reference_symbol=ref_symbol,
        calendar=calendar_name,
        start_session=sessions[0],
        end_session=sessions[-1],
        sessions=sessions,
        candidate_symbols=candidate_symbols,
        symbols=all_symbols,
        prices=prices_df,
        matrix_sha256=matrix_sha256,
        source_evidence_hashes=source_evidence_hashes,
        catalog_sha256=catalog_sha256,
        data_qualification="observation_cutoff_verified_not_revision_certified",
    )
