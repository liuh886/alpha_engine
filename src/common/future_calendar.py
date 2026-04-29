from __future__ import annotations

from pathlib import Path


def _read_nonempty_lines(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def ensure_calendar_future_file(
    provider_uri: str | Path, *, freq: str = "day", extra_days: int = 1
) -> Path:
    """
    Ensure Qlib's `calendars/<freq>_future.txt` exists.

    Qlib's TradeCalendarManager uses `future=True` and requires at least one extra
    calendar timestamp beyond the last trading day to compute interval right endpoints.

    This helper copies `calendars/<freq>.txt` and appends `extra_days` extra days
    (calendar days) as a safe boundary.
    """
    provider_uri = Path(provider_uri)
    calendars_dir = provider_uri / "calendars"
    base_path = calendars_dir / f"{freq}.txt"
    future_path = calendars_dir / f"{freq}_future.txt"

    if extra_days <= 0:
        return future_path

    base_lines = _read_nonempty_lines(base_path)
    if not base_lines:
        return future_path

    try:
        import pandas as pd

        last = pd.Timestamp(base_lines[-1])
        appended = []
        for _ in range(int(extra_days)):
            last = last + pd.Timedelta(days=1)
            appended.append(last.strftime("%Y-%m-%d"))
    except Exception:
        # Best effort: if we can't parse, don't create a potentially wrong future file.
        return future_path

    out_lines = base_lines + appended
    out_text = "\n".join(out_lines) + "\n"

    try:
        if (
            future_path.exists()
            and future_path.read_text(encoding="utf-8", errors="replace") == out_text
        ):
            return future_path
    except Exception:
        pass

    calendars_dir.mkdir(parents=True, exist_ok=True)
    future_path.write_text(out_text, encoding="utf-8")
    return future_path
