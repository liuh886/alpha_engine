from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

from src.data.strategy_data_bundle import (
    STRATEGY_MANIFEST_NAME,
    STRATEGY_SGOV_DATA_SYMBOLS,
    build_strategy_data_bundle,
    load_strategy_data_bundle,
)
from src.research.etf_rotation_experiment import fetch_adjusted_daily_bars

STRATEGY_SUBDIR = "strategy_data"


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


def _strategy_bundle_root(
    etf_root: Path,
    *,
    start: str,
    end: str | None,
    adapter: Any | None,
) -> Path:
    strategy_root = etf_root / STRATEGY_SUBDIR
    manifest = strategy_root / STRATEGY_MANIFEST_NAME
    if not manifest.is_file():
        build_strategy_data_bundle(
            etf_bundle_root=etf_root,
            output_root=strategy_root,
            start=start,
            end=end,
            component_id="strategy.qqqi_qqq_tqqq_sgov_vix_vxn_v1",
            reference_adapter=adapter,
            supplemental_symbols=("SGOV", "^VIX", "^VXN"),
            supplemental_roles={
                "SGOV": "tradable",
                "^VIX": "signal_reference",
                "^VXN": "signal_reference",
            },
            bundle_id="qqqi_qqq_tqqq_sgov_vix_vxn_strategy_data_v1",
        )
    return strategy_root


def fetch_governed_etf_strategy_bars(
    *,
    symbols: Sequence[str],
    start: str,
    end: str | None = None,
    bundle_dir: str | Path | None = None,
    adapter: Any | None = None,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, dict[str, Any]]:
    """Load QQQ strategy inputs from one canonical six-symbol data product.

    Production callers provide the governed professional ETF bundle. This
    function seals the complete QQQ v4.3 strategy product exactly once under
    ``strategy_data/`` and all subsequent model/replay reads consume that same
    manifest-bound product. There is no ETF-only compatibility read path.
    """

    requested = [str(value).strip().upper() for value in symbols]
    if bundle_dir is not None:
        unknown = sorted(set(requested) - set(STRATEGY_SGOV_DATA_SYMBOLS))
        if unknown:
            raise ValueError(f"QQQ v4.3 requests undeclared strategy symbols: {unknown}")
        etf_root = Path(bundle_dir).resolve()
        strategy_root = _strategy_bundle_root(
            etf_root,
            start=start,
            end=end,
            adapter=adapter,
        )
        strategy_manifest = strategy_root / STRATEGY_MANIFEST_NAME
        loaded, coverage, manifest = load_strategy_data_bundle(
            strategy_root,
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
