from __future__ import annotations


def build_update_data_commands(
    *,
    python_exe: str,
    full: bool = False,
    market: str = "all",
    start: str = "2020-01-01",
    lookback_days: int = 30,
    rebuild_dashboard_db: bool = True,
) -> list[list[str]]:
    """
    Build subprocess command(s) for updating local market data (yfinance -> qlib bin),
    then optionally rebuilding the dashboard DB JSON.
    """
    cmd = [str(python_exe), "scripts/update_data.py"]
    if str(market).lower() != "all":
        cmd += ["--market", str(market).lower()]
    if full:
        cmd += ["--full", "--start", str(start)]
    else:
        cmd += ["--lookback-days", str(int(lookback_days))]

    commands = [cmd]
    if rebuild_dashboard_db:
        commands.append([str(python_exe), "scripts/build_dashboard_db.py"])
    return commands
