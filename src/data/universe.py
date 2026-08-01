from pathlib import Path

import pandas as pd
import yaml
from qlib.data import D

from src.common.market import resolve_start_date


SELECTED_POOL_REGISTRY = Path("configs/pools/selected_pool_registry_v1.yaml")


def _load_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML contract must be a mapping: {path}")
    return payload


def get_selected_tickers(market: str, project_root: Path) -> list[str]:
    """Return the active user-approved selected pool for a market."""

    registry_path = project_root / SELECTED_POOL_REGISTRY
    if not registry_path.exists():
        return []

    registry = _load_yaml(registry_path)
    market_config = (registry.get("markets", {}) or {}).get(market)
    if not isinstance(market_config, dict):
        return []
    if market_config.get("new_authoritative_runs_allowed") is not True:
        raise ValueError(f"authoritative {market} universe is not active")

    pool_value = str(market_config.get("pool_spec", "")).strip()
    if not pool_value:
        raise ValueError(f"selected pool path missing for market: {market}")
    pool_path = project_root / pool_value
    pool = _load_yaml(pool_path)
    if pool.get("pool_id") != market_config.get("active_pool_id"):
        raise ValueError(f"selected pool identity mismatch for market: {market}")
    if pool.get("market") != market or pool.get("status") != "active_selected_pool":
        raise ValueError(f"selected pool is not authoritative for market: {market}")

    raw_symbols = pool.get("symbols")
    if isinstance(raw_symbols, list):
        symbols = [str(symbol).strip() for symbol in raw_symbols if str(symbol).strip()]
    else:
        symbols = [
            str(symbol).strip()
            for basket in (pool.get("baskets", {}) or {}).values()
            for symbol in (basket.get("symbols", []) if isinstance(basket, dict) else [])
            if str(symbol).strip()
        ]
    if not symbols or len(symbols) != len(set(symbols)):
        raise ValueError(f"selected pool symbols must be non-empty and unique: {market}")
    return symbols


def get_base_tickers(market: str, project_root: Path) -> list[str]:
    selected = get_selected_tickers(market, project_root)
    if selected:
        return selected

    market_file = project_root / f"data/watchlist/instruments/{market}.txt"
    all_tickers = []
    if market_file.exists():
        with open(market_file) as f:
            for line in f:
                all_tickers.append(line.strip().split("\t")[0])
    return all_tickers


def clean_universe(
    market: str,
    project_root: Path,
    start_time: str,
    warmup_days: int = 10,
) -> list[str]:
    """Clean the selected universe by removing tickers without start-date data."""

    all_tickers = get_base_tickers(market, project_root)
    if not all_tickers:
        return []

    calendar = D.calendar()
    start_date, _ = resolve_start_date(start_time, calendar)

    warmup_end = pd.Timestamp(start_date) + pd.Timedelta(days=warmup_days)
    valid_tickers = []
    try:
        check_df = D.features(
            all_tickers,
            ["$close"],
            start_time=start_date,
            end_time=warmup_end,
        )
        if not check_df.empty:
            valid_tickers = (
                check_df.index.get_level_values("instrument").unique().tolist()
            )
    except Exception:
        for ticker in all_tickers:
            try:
                if not D.features(
                    [ticker],
                    ["$close"],
                    start_time=start_date,
                    end_time=warmup_end,
                ).empty:
                    valid_tickers.append(ticker)
            except Exception:
                continue

    return valid_tickers


def apply_liquidity_filter(
    tickers: list[str],
    profile_data: dict,
    asof_time: str,
) -> list[str]:
    """Apply min_liquidity filter from profile."""

    from src.common.universe import apply_profile_universe_filters

    min_liquidity = (
        (profile_data.get("universe", {}) or {}).get("filters", {}).get("min_liquidity")
    )
    if min_liquidity is not None:
        return apply_profile_universe_filters(
            tickers,
            profile=profile_data,
            asof_time=asof_time,
            fetch_features=D.features,
        )
    return tickers
