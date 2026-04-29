def get_region_for_market(market: str) -> str:
    market = (market or "").lower()
    if market in {"cn", "hk"}:
        return "cn"
    if market == "us":
        return "us"
    return "us"


def resolve_start_date(start_date, calendar):
    if calendar is None or len(calendar) == 0:
        return str(start_date), False
    import bisect

    import pandas as pd

    start = pd.Timestamp(str(start_date)).strftime("%Y-%m-%d")
    cal = [pd.Timestamp(str(x)).strftime("%Y-%m-%d") for x in calendar]

    idx = bisect.bisect_left(cal, start)
    if idx >= len(cal):
        return start, False
    resolved = cal[idx]
    return resolved, resolved != start


def resolve_backtest_window(
    backtest_cfg: dict, calendar, *, default_start: str = "2025-01-01"
) -> dict:
    """
    Ensure backtest window is aligned with available trading calendar.

    - start_time: keep existing if provided; otherwise default_start
    - end_time: always set to the latest available trading day (calendar[-1])

    Notes
    -----
    Qlib calendars are trading-day timestamps; "latest" means latest date in the data.
    """
    backtest_cfg = dict(backtest_cfg or {})
    start_time = str(backtest_cfg.get("start_time") or default_start)

    end_time = backtest_cfg.get("end_time")
    if calendar is not None and len(calendar) > 0:
        try:
            import pandas as pd

            last = pd.Timestamp(calendar[-1]).strftime("%Y-%m-%d")
        except Exception:
            last = str(calendar[-1])
        end_time = last
    else:
        end_time = str(end_time) if end_time is not None else start_time

    backtest_cfg["start_time"] = start_time
    backtest_cfg["end_time"] = str(end_time)
    return backtest_cfg
