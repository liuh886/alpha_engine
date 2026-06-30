from __future__ import annotations

import re
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


def _label_expressions(cfg: dict) -> list[str]:
    value = cfg
    for key in (
        "task",
        "dataset",
        "kwargs",
        "handler",
        "kwargs",
        "data_loader",
        "kwargs",
        "config",
        "label",
    ):
        if not isinstance(value, dict):
            return []
        value = value.get(key)

    def collect(item) -> list[str]:
        if isinstance(item, str):
            return [item]
        if isinstance(item, (list, tuple)):
            return [expression for child in item for expression in collect(child)]
        return []

    return collect(value)


def _ref_offsets(expression: str) -> list[int]:
    """Extract final integer arguments from Ref calls, including nested arguments."""
    offsets: list[int] = []
    for match in re.finditer(r"\bRef\s*\(", expression):
        start = match.end()
        depth = 1
        comma = None
        quote = None
        escaped = False
        for index in range(start, len(expression)):
            char = expression[index]
            if quote:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == quote:
                    quote = None
                continue
            if char in {'"', "'"}:
                quote = char
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    candidate = expression[comma + 1 : index].strip() if comma is not None else ""
                    if re.fullmatch(r"[+-]?\d+", candidate):
                        offsets.append(int(candidate))
                    break
            elif char == "," and depth == 1:
                comma = index
    return offsets


def _max_label_forward_horizon(cfg: dict) -> int:
    return max(
        (abs(offset) for label in _label_expressions(cfg) for offset in _ref_offsets(label) if offset < 0),
        default=0,
    )


def _trading_calendar(calendar):
    import pandas as pd

    if calendar is None:
        raise ValueError("Trading calendar is required for label-horizon purge")
    try:
        values = list(calendar)
        result = pd.DatetimeIndex(pd.to_datetime(values))
    except Exception as exc:
        raise ValueError("Trading calendar is invalid for label-horizon purge") from exc
    if result.empty:
        raise ValueError("Trading calendar is empty for label-horizon purge")
    if result.hasnans or not result.is_monotonic_increasing or not result.is_unique:
        raise ValueError("Trading calendar must contain ordered, unique observed sessions")
    return result


def _segment(segments: dict, name: str):
    import pandas as pd

    value = segments.get(name)
    if not isinstance(value, (list, tuple)) or len(value) < 2 or not value[0] or not value[1]:
        raise ValueError(f"{name} segment is missing or incomplete")
    try:
        start, end = pd.Timestamp(value[0]), pd.Timestamp(value[1])
    except Exception as exc:
        raise ValueError(f"{name} segment has an invalid boundary") from exc
    if start > end:
        raise ValueError(f"{name} segment is invalid or empty")
    return start, end


def _purged_end(calendar, start, end, next_start, horizon: int, name: str):
    boundary_position = calendar.searchsorted(next_start, side="left")
    if boundary_position >= len(calendar):
        raise ValueError(f"Trading calendar does not cover the {name} segment boundary")

    safe_position = boundary_position - horizon - 1
    original_end_position = calendar.searchsorted(end, side="right") - 1
    resolved_position = min(safe_position, original_end_position)
    if resolved_position < 0 or calendar[resolved_position] < start:
        raise ValueError(
            f"{name} segment is empty after purging label horizon {horizon}"
        )
    return calendar[resolved_position]


def apply_label_horizon_purge(cfg: dict, calendar) -> dict:
    """Return a copied workflow config with leakage-safe train/valid ends."""
    result = deepcopy(cfg or {})
    horizon = _max_label_forward_horizon(result)
    if horizon == 0:
        return result

    observed = _trading_calendar(calendar)
    segments = (
        result.get("task", {}).get("dataset", {}).get("kwargs", {}).get("segments")
    )
    if not isinstance(segments, dict):
        raise ValueError("Workflow segments are required for label-horizon purge")

    train_start, train_end = _segment(segments, "train")
    valid_start, valid_end = _segment(segments, "valid")
    test_start, test_end = _segment(segments, "test")

    train_end = _purged_end(
        observed, train_start, train_end, valid_start, horizon, "train"
    )
    valid_end = _purged_end(
        observed, valid_start, valid_end, test_start, horizon, "valid"
    )
    if observed.searchsorted(test_end, side="right") <= observed.searchsorted(
        test_start, side="left"
    ):
        raise ValueError("test segment is invalid or empty on the trading calendar")

    segments["train"] = [str(segments["train"][0]), _as_ymd(train_end)]
    segments["valid"] = [str(segments["valid"][0]), _as_ymd(valid_end)]
    return result
