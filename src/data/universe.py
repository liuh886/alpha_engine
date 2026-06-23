import pandas as pd
from pathlib import Path
from qlib.data import D
from src.common.market import resolve_start_date

def get_base_tickers(market: str, project_root: Path) -> list[str]:
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
    warmup_days: int = 10
) -> list[str]:
    """
    Clean the universe by removing tickers that don't have data at the start_time.
    """
    all_tickers = get_base_tickers(market, project_root)
    if not all_tickers:
        return []

    calendar = D.calendar()
    start_date, _ = resolve_start_date(start_time, calendar)
    
    warmup_end = pd.Timestamp(start_date) + pd.Timedelta(days=warmup_days)
    valid_tickers = []
    try:
        # Batch check
        check_df = D.features(all_tickers, ["$close"], start_time=start_date, end_time=warmup_end)
        if not check_df.empty:
            valid_tickers = check_df.index.get_level_values("instrument").unique().tolist()
    except Exception:
        # Iterative fallback
        for t in all_tickers:
            try:
                if not D.features([t], ["$close"], start_time=start_date, end_time=warmup_end).empty:
                    valid_tickers.append(t)
            except Exception:
                continue
        
    return valid_tickers

def apply_liquidity_filter(
    tickers: list[str],
    profile_data: dict,
    asof_time: str
) -> list[str]:
    """
    Apply min_liquidity filter from profile.
    """
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
