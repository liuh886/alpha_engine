from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from src.data.strategy_data_bundle import (
    STRATEGY_MANIFEST_NAME,
    load_strategy_data_bundle,
)
from src.research.etf_rotation_experiment import fetch_adjusted_daily_bars


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
    """Load QQQ strategy inputs from the canonical composite data product.

    Supplying ``bundle_dir`` is the production path and requires the complete
    strategy-data manifest. Direct provider fetching remains available only for
    isolated research callers that deliberately omit a governed bundle.
    """

    requested = [str(value).strip().upper() for value in symbols]
    if bundle_dir is not None:
        root = Path(bundle_dir).resolve()
        strategy_manifest = root / STRATEGY_MANIFEST_NAME
        if not strategy_manifest.is_file():
            raise ValueError(
                "governed QQQ strategy bundle is required; ETF-only compatibility data are not accepted"
            )
        loaded, coverage, manifest = load_strategy_data_bundle(
            root,
            symbols=requested,
        )
        bars = {
            symbol: _clip_frame(
                frame,
                symbol=symbol,
                start=start,
                end=end,
            )
            for symbol, frame in loaded.items()
        }
        selected = coverage.loc[coverage["symbol"].isin(requested)].copy()
        selected["data_mode"] = "governed_strategy_data_bundle"
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
        return bars, selected.sort_values("symbol").reset_index(drop=True), identity

    direct_bars, direct_coverage = fetch_adjusted_daily_bars(
        symbols=requested,
        start=start,
        end=end,
        adapter=adapter,
    )
    coverage = direct_coverage.copy()
    coverage["data_mode"] = "direct_provider_fetch"
    identity = {
        "mode": "direct_provider_fetch",
        "research_only": True,
        "trade_ready": False,
    }
    return direct_bars, coverage.sort_values("symbol").reset_index(drop=True), identity


def _sha256(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()
