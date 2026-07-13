"""Preserve real session evidence for policy-excluded partial windows.

Deleted before merge.
"""

from __future__ import annotations

from pathlib import Path

WINDOW_POLICY = Path("src/research/window_policy.py")
WINDOW_TESTS = Path("tests/test_window_policy.py")
DIAGNOSTIC_TESTS = Path("tests/test_spec_bound_factor_diagnostics.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_policy() -> None:
    text = WINDOW_POLICY.read_text(encoding="utf-8")
    old = '''    for decision in decisions:
        row = decision.to_dict()
        selected = decision.selected_window()
        if selected is None:
            row.update(
                {
                    "status": "excluded",
                    "inclusion_reason": decision.boundary_reason,
                    "available_sessions": 0,
                    "horizon_eligible_sessions": 0,
                    "excluded_tail_sessions": 0,
                    "label_horizon_sessions": horizon_sessions,
                    "sampled_sessions": 0,
                }
            )
            window_rows.append(row)
            continue

        start = pd.Timestamp(selected.test_start)
        end = pd.Timestamp(selected.test_end)
        window_dates = dates_index[(dates_index >= start) & (dates_index <= end)]
        horizon_eligible = (
            window_dates[:-horizon_sessions]
            if len(window_dates) > horizon_sessions
            else window_dates[:0]
        )
        sampled = horizon_eligible[::cadence_sessions]
        include = len(sampled) > 0
        reason = "horizon-contained sessions available"

        if decision.complete:
            if include:
                complete_count += 1
            else:
                reason = "complete window has no horizon-contained sampled sessions"
        else:
            minimum = int(min_partial_window_eligible_sessions or 0)
            include = len(horizon_eligible) >= minimum and len(sampled) > 0
            if include:
                partial_count += 1
                reason = (
                    "partial final window meets declared horizon-eligible "
                    "session minimum"
                )
            else:
                reason = (
                    "partial final window has "
                    f"{len(horizon_eligible)} horizon-eligible sessions; "
                    f"requires at least {minimum}"
                )

        row.update(
            {
                "status": "included" if include else "excluded",
                "inclusion_reason": reason,
                "available_sessions": int(len(window_dates)),
                "horizon_eligible_sessions": int(len(horizon_eligible)),
                "excluded_tail_sessions": int(
                    len(window_dates) - len(horizon_eligible)
                ),
                "label_horizon_sessions": horizon_sessions,
                "sampled_sessions": int(len(sampled)) if include else 0,
            }
        )
        if include:
            selected_windows.append(selected)
            sampled_date_labels.extend(
                (pd.Timestamp(date).strftime("%Y-%m-%d"), decision.label)
                for date in sampled
            )
        window_rows.append(row)
'''
    new = '''    for decision in decisions:
        row = decision.to_dict()
        selected = decision.selected_window()
        evidence_window = selected
        if evidence_window is None and decision.effective_test_end is not None:
            evidence_window = RollingResearchWindow(
                label=decision.label,
                train_start=decision.train_start,
                train_end=decision.train_end,
                test_start=decision.test_start,
                test_end=decision.effective_test_end,
            )
        if evidence_window is None:
            row.update(
                {
                    "status": "excluded",
                    "inclusion_reason": decision.boundary_reason,
                    "available_sessions": 0,
                    "horizon_eligible_sessions": 0,
                    "excluded_tail_sessions": 0,
                    "label_horizon_sessions": horizon_sessions,
                    "sampled_sessions": 0,
                }
            )
            window_rows.append(row)
            continue

        start = pd.Timestamp(evidence_window.test_start)
        end = pd.Timestamp(evidence_window.test_end)
        window_dates = dates_index[(dates_index >= start) & (dates_index <= end)]
        horizon_eligible = (
            window_dates[:-horizon_sessions]
            if len(window_dates) > horizon_sessions
            else window_dates[:0]
        )
        sampled = horizon_eligible[::cadence_sessions]
        include = False
        reason = decision.boundary_reason

        if decision.boundary_status == "candidate_complete":
            include = len(sampled) > 0
            if include:
                complete_count += 1
                reason = "horizon-contained sessions available"
            else:
                reason = "complete window has no horizon-contained sampled sessions"
        elif decision.boundary_status == "candidate_partial_final":
            minimum = int(min_partial_window_eligible_sessions or 0)
            include = len(horizon_eligible) >= minimum and len(sampled) > 0
            if include:
                partial_count += 1
                reason = (
                    "partial final window meets declared horizon-eligible "
                    "session minimum"
                )
            else:
                reason = (
                    "partial final window has "
                    f"{len(horizon_eligible)} horizon-eligible sessions; "
                    f"requires at least {minimum}"
                )

        row.update(
            {
                "status": "included" if include else "excluded",
                "inclusion_reason": reason,
                "available_sessions": int(len(window_dates)),
                "horizon_eligible_sessions": int(len(horizon_eligible)),
                "excluded_tail_sessions": int(
                    len(window_dates) - len(horizon_eligible)
                ),
                "label_horizon_sessions": horizon_sessions,
                "sampled_sessions": int(len(sampled)) if include else 0,
            }
        )
        if include:
            if selected is None:
                raise ValueError(
                    f"included window {decision.label} has no selected boundary"
                )
            selected_windows.append(selected)
            sampled_date_labels.extend(
                (pd.Timestamp(date).strftime("%Y-%m-%d"), decision.label)
                for date in sampled
            )
        window_rows.append(row)
'''
    text = replace_once(text, old, new, "session evidence block")
    WINDOW_POLICY.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    text = WINDOW_TESTS.read_text(encoding="utf-8")
    anchor = '''    assert partial["counts_toward_min_windows"] is False
'''
    addition = '''    assert partial["counts_toward_min_windows"] is False
    assert partial["available_sessions"] > 10
    assert partial["horizon_eligible_sessions"] > 0
    assert partial["excluded_tail_sessions"] == 10
    assert partial["sampled_sessions"] == 0
'''
    if 'assert partial["available_sessions"] > 10' not in text:
        text = replace_once(text, anchor, addition, "partial evidence assertions")
    WINDOW_TESTS.write_text(text, encoding="utf-8")

    diagnostic = DIAGNOSTIC_TESTS.read_text(encoding="utf-8")
    diagnostic = diagnostic.replace(
        'pd.Timestamp(window["test_end"])',
        'pd.Timestamp(window["effective_test_end"])',
    )
    diagnostic = diagnostic.replace(
        'assert all(row["excluded_tail_sessions"] == 10 for row in windows)',
        'assert all(\n'
        '        row["excluded_tail_sessions"] == 10\n'
        '        for row in windows\n'
        '        if row["status"] == "included"\n'
        '    )',
    )
    DIAGNOSTIC_TESTS.write_text(diagnostic, encoding="utf-8")


def main() -> None:
    patch_policy()
    patch_tests()


if __name__ == "__main__":
    main()
