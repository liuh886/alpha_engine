from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from src.data.etf_reference_bundle import (
    ETF_REFERENCE_SYMBOLS,
    load_etf_reference_bundle,
)
from src.data.strategy_data_bundle import (
    STRATEGY_MANIFEST_NAME,
    load_strategy_data_bundle,
)
from src.research.etf_rotation_experiment import fetch_adjusted_daily_bars


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clip_frame(
    frame: pd.DataFrame,
    *,
    symbol: str,
    start: str,
    end: str | None,
) -> pd.DataFrame:
    local = frame.copy()
    dates = pd.to_datetime(local["date"], errors="coerce").dt.normalize()
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize() if end else None
    mask = dates.ge(start_ts)
    if end_ts is not None:
        mask &= dates.le(end_ts)
    local = local.loc[mask].copy().reset_index(drop=True)
    if local.empty:
        raise ValueError(f"governed strategy data have no rows for {symbol} in requested range")
    return local


def fetch_governed_etf_strategy_bars(
    *,
    symbols: Sequence[str],
    start: str,
    end: str | None = None,
    bundle_dir: str | Path | None = None,
    adapter: Any | None = None,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, dict[str, Any]]:
    """Load strategy data from one governed product when available.

    Preferred mode is the composite QQQ strategy bundle, which binds QQQ, QQQI,
    TQQQ, VIX and VXN into one immutable identity. The older ETF-only bundle is
    retained as a compatibility path; in that mode non-executable references are
    still fetched directly and are clearly labelled as such.
    """

    requested = [str(value).strip().upper() for value in symbols]
    bars: dict[str, pd.DataFrame] = {}
    coverage_frames: list[pd.DataFrame] = []
    identity: dict[str, Any] = {
        "mode": "direct_provider_fetch",
        "research_only": True,
        "trade_ready": False,
    }

    if bundle_dir is not None:
        root = Path(bundle_dir).resolve()
        strategy_manifest = root / STRATEGY_MANIFEST_NAME
        if strategy_manifest.is_file():
            loaded, coverage, manifest = load_strategy_data_bundle(
                root,
                symbols=requested,
            )
            for symbol, frame in loaded.items():
                bars[symbol] = _clip_frame(
                    frame,
                    symbol=symbol,
                    start=start,
                    end=end,
                )
            coverage = coverage.loc[coverage["symbol"].isin(requested)].copy()
            coverage["data_mode"] = "governed_strategy_data_bundle"
            coverage_frames.append(coverage)
            identity = {
                "mode": "governed_strategy_data_bundle",
                "bundle_id": manifest.get("bundle_id"),
                "component_id": manifest.get("component_id"),
                "manifest_path": str(strategy_manifest),
                "manifest_sha256": _sha256(strategy_manifest),
                "strategy_data_ready": manifest.get("status") == "ready",
                "professional_source_ready": manifest.get("professional_source_ready"),
                "selected_providers": manifest.get("details", {}).get("selected_providers", {}),
                "common_history_start": manifest.get("first_date"),
                "common_history_end": manifest.get("last_date"),
                "symbols": manifest.get("symbols", []),
                "roles": manifest.get("roles", {}),
                "research_only": True,
                "trade_ready": False,
            }
            return (
                bars,
                coverage.sort_values("symbol").reset_index(drop=True),
                identity,
            )

    etf_symbols = [value for value in requested if value in ETF_REFERENCE_SYMBOLS]
    other_symbols = [value for value in requested if value not in ETF_REFERENCE_SYMBOLS]

    if bundle_dir is not None and etf_symbols:
        root = Path(bundle_dir).resolve()
        loaded, coverage, manifest = load_etf_reference_bundle(
            root,
            symbols=etf_symbols,
            require_strategy_ready=True,
        )
        for symbol, frame in loaded.items():
            bars[symbol] = _clip_frame(
                frame,
                symbol=symbol,
                start=start,
                end=end,
            )

        selected = coverage.loc[coverage["symbol"].isin(etf_symbols)].copy()
        selected["data_mode"] = "governed_etf_bundle"
        coverage_frames.append(selected)
        manifest_path = root / "bundle_manifest.json"
        identity = {
            "mode": "governed_etf_bundle",
            "bundle_id": manifest.get("bundle_id"),
            "manifest_path": str(manifest_path),
            "manifest_sha256": _sha256(manifest_path),
            "strategy_data_ready": manifest.get("strategy_data_ready"),
            "professional_source_ready": manifest.get("professional_source_ready"),
            "selected_providers": manifest.get("selected_providers", {}),
            "reconciliation_status": manifest.get("reconciliation_status", {}),
            "common_history_start": manifest.get("common_history_start"),
            "common_history_end": manifest.get("common_history_end"),
            "research_only": True,
            "trade_ready": False,
        }
    elif etf_symbols:
        direct_bars, direct_coverage = fetch_adjusted_daily_bars(
            symbols=etf_symbols,
            start=start,
            end=end,
            adapter=adapter,
        )
        bars.update(direct_bars)
        direct_coverage = direct_coverage.copy()
        direct_coverage["data_mode"] = "direct_provider_fetch"
        coverage_frames.append(direct_coverage)

    if other_symbols:
        other_bars, other_coverage = fetch_adjusted_daily_bars(
            symbols=other_symbols,
            start=start,
            end=end,
            adapter=adapter,
        )
        bars.update(other_bars)
        other_coverage = other_coverage.copy()
        other_coverage["data_mode"] = "direct_reference_fetch"
        coverage_frames.append(other_coverage)

    missing = sorted(set(requested).difference(bars))
    if missing:
        raise ValueError(f"strategy data are missing requested symbols: {missing}")
    coverage = (
        pd.concat(coverage_frames, ignore_index=True, sort=False)
        if coverage_frames
        else pd.DataFrame()
    )
    return bars, coverage.sort_values("symbol").reset_index(drop=True), identity
