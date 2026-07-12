"""One-time patcher for forward-label containment in factor diagnostics.

Deleted before merge.
"""

from pathlib import Path

SOURCE = Path("src/research/spec_bound_factor_diagnostics.py")
TESTS = Path("tests/test_spec_bound_factor_diagnostics.py")


def patch_source() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    text = text.replace(
        'FACTOR_DIAGNOSTICS_SCHEMA_VERSION = "1.0"',
        'FACTOR_DIAGNOSTICS_SCHEMA_VERSION = "1.1"',
        1,
    )
    start = text.index("def _window_date_map(")
    end = text.index("\ndef _daily_factor_rows(", start)
    replacement = '''def _window_date_map(
    available_dates: pd.DatetimeIndex,
    spec: ResearchParadigmSpec,
) -> tuple[dict[pd.Timestamp, str], list[dict[str, Any]]]:
    """Build non-overlapping rebalance dates whose labels stay inside each OOS window.

    A forward ``horizon_days`` return observed near a window boundary must not use
    prices from the next window.  The final horizon-sized tail of every window is
    therefore excluded before applying the declared rebalance cadence.
    """

    walk = spec.walk_forward
    windows = get_aligned_windows(
        str(walk["requested_train_start"]),
        str(walk["test_end"]),
        first_test_year=int(walk["first_test_year"]),
        last_test_year=int(walk["last_test_year"]),
    )
    if len(windows) < int(walk["min_windows"]):
        raise ValueError("declared walk-forward contract has too few diagnostic windows")

    cadence = int(spec.strategy["rebalance_days"])
    horizon = int(spec.strategy["horizon_days"])
    if cadence <= 0 or horizon <= 0:
        raise ValueError("diagnostic cadence and horizon must be positive")

    date_map: dict[pd.Timestamp, str] = {}
    window_rows: list[dict[str, Any]] = []
    for window in windows:
        start = pd.Timestamp(window.test_start)
        end = pd.Timestamp(window.test_end)
        dates = available_dates[(available_dates >= start) & (available_dates <= end)]
        if len(dates) > horizon:
            horizon_eligible = dates[:-horizon]
        else:
            horizon_eligible = dates[:0]
        sampled = horizon_eligible[::cadence]
        for date in sampled:
            date_map[pd.Timestamp(date)] = window.label
        window_rows.append(
            {
                **window.to_dict(),
                "available_sessions": int(len(dates)),
                "horizon_eligible_sessions": int(len(horizon_eligible)),
                "excluded_tail_sessions": int(len(dates) - len(horizon_eligible)),
                "label_horizon_sessions": horizon,
                "sampled_sessions": int(len(sampled)),
            }
        )
    if not date_map:
        raise ValueError("no horizon-contained rebalance dates are available for factor diagnostics")
    return date_map, window_rows

'''
    text = text[:start] + replacement + text[end + 1 :]
    SOURCE.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    text = TESTS.read_text(encoding="utf-8")
    text = text.replace(
        "from src.research.spec_bound_factor_diagnostics import (\n    run_factor_diagnostics,",
        "from src.research.spec_bound_factor_diagnostics import (\n    _window_date_map,\n    run_factor_diagnostics,",
        1,
    )
    text = text.replace(
        '    assert report["sampled_rebalance_dates"] > 50\n',
        '    assert report["sampled_rebalance_dates"] >= 40\n'
        '    assert all(row["excluded_tail_sessions"] == 10 for row in report["windows"])\n'
        '    assert all(row["label_horizon_sessions"] == 10 for row in report["windows"])\n',
        1,
    )
    test_name = "test_window_sampling_contains_forward_labels_within_oos_window"
    if test_name not in text:
        addition = '''\n\ndef test_window_sampling_contains_forward_labels_within_oos_window(
    tmp_path: Path,
) -> None:
    spec_path, _ = _write_spec(tmp_path)
    spec = load_research_paradigm_spec(spec_path)
    available_dates = pd.bdate_range("2024-01-01", "2025-12-31")

    date_map, windows = _window_date_map(available_dates, spec)
    positions = {pd.Timestamp(date): i for i, date in enumerate(available_dates)}
    by_label = {row["label"]: row for row in windows}
    selected = sorted(date_map)

    assert selected
    for date in selected:
        window = by_label[date_map[date]]
        future_date = available_dates[positions[date] + 10]
        assert future_date <= pd.Timestamp(window["test_end"])

    selected_positions = [positions[date] for date in selected]
    assert all(
        right - left >= 10
        for left, right in zip(selected_positions, selected_positions[1:])
    )
    assert all(row["excluded_tail_sessions"] == 10 for row in windows)
    assert all(
        row["horizon_eligible_sessions"]
        == row["available_sessions"] - row["excluded_tail_sessions"]
        for row in windows
    )
'''
        text = text.rstrip() + addition + "\n"
    TESTS.write_text(text, encoding="utf-8")


def main() -> None:
    patch_source()
    patch_tests()


if __name__ == "__main__":
    main()
