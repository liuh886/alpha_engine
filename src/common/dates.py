"""Dynamic date helpers for default parameters.

Usage:
    from src.common.dates import default_end_date, default_start_date

    def my_func(end_date: str = None):
        end_date = end_date or default_end_date()
"""

from datetime import datetime, timedelta


def default_end_date() -> str:
    """Return today's date as YYYY-MM-DD."""
    return datetime.now().strftime("%Y-%m-%d")


def default_start_date(years_back: int = 1) -> str:
    """Return date N years ago as YYYY-MM-DD."""
    return (datetime.now() - timedelta(days=365 * years_back)).strftime("%Y-%m-%d")


def default_train_end() -> str:
    """Return yesterday's date for walk-forward training end."""
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
