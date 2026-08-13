"""Model-agnostic trace comparison primitives for exact replay gates."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

DEFAULT_TRACE_SECTIONS = ("report", "positions", "trades")
FLOAT_TOLERANCE = 1e-12


def _numeric(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def compare_row_lists(expected: object, observed: object) -> dict[str, Any]:
    if not isinstance(expected, list) or not isinstance(observed, list):
        return {
            "exact": False,
            "expected_rows": len(expected) if isinstance(expected, list) else None,
            "observed_rows": len(observed) if isinstance(observed, list) else None,
            "first_mismatch": {"reason": "section_is_not_a_row_list"},
            "max_absolute_difference": {},
        }

    max_absolute_difference: dict[str, float] = {}
    first_mismatch: dict[str, Any] | None = None
    if len(expected) != len(observed):
        first_mismatch = {
            "reason": "row_count_mismatch",
            "expected": len(expected),
            "observed": len(observed),
        }

    for index, (left, right) in enumerate(zip(expected, observed, strict=False)):
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            if first_mismatch is None:
                first_mismatch = {"reason": "row_is_not_mapping", "index": index}
            continue
        if set(left) != set(right):
            if first_mismatch is None:
                first_mismatch = {
                    "reason": "field_set_mismatch",
                    "index": index,
                    "expected_only": sorted(set(left) - set(right)),
                    "observed_only": sorted(set(right) - set(left)),
                }
            continue
        for field, expected_value in left.items():
            observed_value = right[field]
            if _numeric(expected_value) and _numeric(observed_value):
                left_value = float(expected_value)
                right_value = float(observed_value)
                if math.isnan(left_value) and math.isnan(right_value):
                    difference = 0.0
                    matches = True
                else:
                    difference = abs(left_value - right_value)
                    matches = math.isclose(
                        left_value,
                        right_value,
                        rel_tol=0.0,
                        abs_tol=FLOAT_TOLERANCE,
                    )
                max_absolute_difference[str(field)] = max(
                    max_absolute_difference.get(str(field), 0.0),
                    difference,
                )
            else:
                matches = expected_value == observed_value
            if not matches and first_mismatch is None:
                first_mismatch = {
                    "reason": "value_mismatch",
                    "index": index,
                    "field": str(field),
                    "expected": expected_value,
                    "observed": observed_value,
                }

    exact = first_mismatch is None and len(expected) == len(observed)
    return {
        "exact": exact,
        "expected_rows": len(expected),
        "observed_rows": len(observed),
        "first_mismatch": first_mismatch,
        "max_absolute_difference": dict(sorted(max_absolute_difference.items())),
    }


def compare_package_sections(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
    *,
    sections: Sequence[str] = DEFAULT_TRACE_SECTIONS,
) -> dict[str, Any]:
    comparison = {
        section: compare_row_lists(expected.get(section), observed.get(section))
        for section in sections
    }
    portfolio_contract_exact = expected.get("portfolio_contract") == observed.get(
        "portfolio_contract"
    )
    exact = portfolio_contract_exact and all(
        bool(result["exact"]) for result in comparison.values()
    )
    return {
        "exact": exact,
        "portfolio_contract_exact": portfolio_contract_exact,
        "sections": comparison,
    }
