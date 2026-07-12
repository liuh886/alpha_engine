"""One-time patcher for Issue #124 OHLC round-off tolerance.

This file is deleted before merge.
"""

from pathlib import Path


SOURCE = Path("src/research/real_market_acceptance.py")
TESTS = Path("tests/test_real_market_acceptance.py")


def patch_source() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    text = text.replace(
        'ACCEPTANCE_SCHEMA_VERSION = "1.2"',
        'ACCEPTANCE_SCHEMA_VERSION = "1.3"',
        1,
    )

    constants_anchor = "_MAX_VIOLATION_EXAMPLES = 20\n"
    constants = (
        "_MAX_VIOLATION_EXAMPLES = 20\n"
        "_OHLC_ORDER_ABS_TOLERANCE = 1e-12\n"
        "_OHLC_ORDER_REL_TOLERANCE = 1e-12\n"
    )
    if "_OHLC_ORDER_ABS_TOLERANCE" not in text:
        if constants_anchor not in text:
            raise RuntimeError("OHLC constants anchor not found")
        text = text.replace(constants_anchor, constants, 1)

    start = text.index("def _ohlc_order_evidence(")
    end = text.index("\ndef _inspect_csv(", start)
    replacement = '''def _ohlc_order_evidence(
    dates: pd.Series,
    numeric: pd.DataFrame,
) -> dict[str, Any]:
    """Return material OHLC-order evidence without repairing source values.

    Adjusted market data can differ by a few floating-point ULPs after provider
    normalization and CSV serialization. Comparisons therefore ignore only
    deltas within a strict absolute/relative tolerance and continue to reject
    any material ordering violation.
    """

    violations: list[dict[str, Any]] = []
    invalid_rows: set[int] = set()
    ignored_roundoff_count = 0
    max_ignored_roundoff: dict[str, Any] | None = None
    comparisons = (
        ("high_below_open", "high", "open"),
        ("high_below_low", "high", "low"),
        ("high_below_close", "high", "close"),
        ("low_above_open", "open", "low"),
        ("low_above_close", "close", "low"),
    )

    for position, (_, row) in enumerate(numeric.iterrows()):
        if not all(math.isfinite(float(row[column])) for column in _OHLC_COLUMNS):
            continue
        for violation_type, upper_column, lower_column in comparisons:
            upper = float(row[upper_column])
            lower = float(row[lower_column])
            absolute_magnitude = lower - upper
            if absolute_magnitude <= 0.0:
                continue

            scale = max(abs(upper), abs(lower), 1.0)
            tolerance = max(
                _OHLC_ORDER_ABS_TOLERANCE,
                _OHLC_ORDER_REL_TOLERANCE * scale,
            )
            record = _violation_record(
                row_index=position,
                date=dates.iloc[position] if position < len(dates) else None,
                violation_type=violation_type,
                numeric_row=row,
                absolute_magnitude=absolute_magnitude,
            )
            record["comparison_tolerance"] = float(tolerance)

            if absolute_magnitude <= tolerance:
                ignored_roundoff_count += 1
                if max_ignored_roundoff is None or (
                    float(record["absolute_magnitude"]),
                    float(record["relative_magnitude"]),
                ) > (
                    float(max_ignored_roundoff["absolute_magnitude"]),
                    float(max_ignored_roundoff["relative_magnitude"]),
                ):
                    max_ignored_roundoff = record
                continue

            invalid_rows.add(position)
            violations.append(record)

    violations.sort(key=lambda item: (int(item["row_index"]), str(item["type"])))
    max_violation = (
        max(
            violations,
            key=lambda item: (
                float(item["absolute_magnitude"]),
                float(item["relative_magnitude"]),
            ),
        )
        if violations
        else None
    )
    return {
        "invalid_row_count": len(invalid_rows),
        "violation_count": len(violations),
        "examples": violations[:_MAX_VIOLATION_EXAMPLES],
        "examples_truncated": len(violations) > _MAX_VIOLATION_EXAMPLES,
        "max_violation": max_violation,
        "comparison_tolerance": {
            "absolute": _OHLC_ORDER_ABS_TOLERANCE,
            "relative": _OHLC_ORDER_REL_TOLERANCE,
        },
        "ignored_roundoff_count": ignored_roundoff_count,
        "max_ignored_roundoff": max_ignored_roundoff,
    }

'''
    text = text[:start] + replacement + text[end + 1 :]
    SOURCE.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    text = TESTS.read_text(encoding="utf-8")
    test_name = "test_ohlc_order_tolerates_machine_precision_roundoff"
    if test_name in text:
        return

    addition = '''\n\ndef test_ohlc_order_tolerates_machine_precision_roundoff(tmp_path: Path) -> None:
    path = tmp_path / "roundoff-bars.csv"
    exact = 100.0
    frame = pd.DataFrame(
        {
            "date": ["2026-01-05", "2026-01-06"],
            "open": [exact, exact],
            "high": [np.nextafter(exact, 0.0), exact + 1.0],
            "low": [exact - 1.0, np.nextafter(exact, np.inf)],
            "close": [exact, exact],
            "volume": [1000.0, 1000.0],
        }
    )
    frame.to_csv(path, index=False)

    result = _inspect_csv(path)

    assert result["ok"] is True
    assert result["invalid_ohlc_order_rows"] == 0
    evidence = result["ohlc_order_evidence"]
    assert evidence["violation_count"] == 0
    assert evidence["ignored_roundoff_count"] == 2
    assert evidence["max_ignored_roundoff"] is not None
    assert evidence["comparison_tolerance"] == {
        "absolute": 1e-12,
        "relative": 1e-12,
    }
    json.dumps(result, allow_nan=False)
'''
    TESTS.write_text(text.rstrip() + addition + "\n", encoding="utf-8")


def main() -> None:
    patch_source()
    patch_tests()


if __name__ == "__main__":
    main()
