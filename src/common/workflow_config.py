from __future__ import annotations

from copy import deepcopy


def _as_ymd(value) -> str:
    try:
        import pandas as pd

        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except Exception:
        return str(value)


def _latest_calendar_ymd(calendar) -> str | None:
    if calendar is None:
        return None
    try:
        if len(calendar) <= 0:
            return None
        return _as_ymd(calendar[-1])
    except Exception:
        try:
            cal_list = list(calendar)
            if not cal_list:
                return None
            return _as_ymd(cal_list[-1])
        except Exception:
            return None


def apply_backtest_and_test_window(
    cfg: dict,
    calendar,
    *,
    default_start: str = "2025-01-01",
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict:
    """
    Apply a consistent [start, end] window to both:
    - `port_analysis_config.backtest`
    - `task.dataset.kwargs.segments.test`
    while also ensuring `task.dataset.kwargs.handler.kwargs.end_time` covers the end date.

    Parameters
    ----------
    cfg:
        Workflow config dict (as loaded from YAML).
    calendar:
        Qlib trading calendar (list-like).
    default_start:
        Used when backtest start_time is missing and no override is provided.
    start_time:
        Optional override for start date (YYYY-MM-DD).
    end_time:
        Optional override for end date (YYYY-MM-DD). If None/"latest"/"", uses the latest trading day in `calendar`.

    Returns
    -------
    dict
        A deep-copied config with updated windows.
    """
    cfg = deepcopy(cfg or {})

    backtest = cfg.setdefault("port_analysis_config", {}).setdefault("backtest", {})
    existing_start = backtest.get("start_time")
    resolved_start = str(start_time or existing_start or default_start)

    resolved_end: str | None
    end_key = str(end_time or "").strip().lower()
    if end_time is None or end_key in {"latest", ""}:
        resolved_end = _latest_calendar_ymd(calendar)
    else:
        resolved_end = str(end_time)

    if not resolved_end:
        resolved_end = str(backtest.get("end_time") or resolved_start)

    backtest["start_time"] = resolved_start
    backtest["end_time"] = str(resolved_end)

    dataset_kwargs = cfg.setdefault("task", {}).setdefault("dataset", {}).setdefault("kwargs", {})
    handler_kwargs = dataset_kwargs.setdefault("handler", {}).setdefault("kwargs", {})
    handler_kwargs["end_time"] = str(resolved_end)

    segments = dataset_kwargs.setdefault("segments", {})
    test_seg = segments.get("test")
    seg_start = None
    if isinstance(test_seg, (list, tuple)) and len(test_seg) >= 1 and test_seg[0]:
        seg_start = str(test_seg[0])
    else:
        seg_start = resolved_start
    if start_time is not None:
        seg_start = str(resolved_start)

    segments["test"] = [str(seg_start), str(resolved_end)]

    return cfg

