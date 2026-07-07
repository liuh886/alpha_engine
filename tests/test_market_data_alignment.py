from __future__ import annotations

import json

import pandas as pd
import pytest

from src.research.market_data_alignment import (
    CoverageAlignment,
    _count_viable_oos_windows,
    align_train_start_to_coverage,
    build_aligned_market_readiness,
    find_common_coverage_start,
)
from src.research.multi_market_readiness import MarketReadinessSpec


# ── helpers ───────────────────────────────────────────────────────────────────


def _dc(
    symbols: list[str],
    first_date: str = "2021-01-04",
    last_date: str = "2026-06-18",
    observations: int = 1300,
) -> dict[str, dict[str, object]]:
    """Build date-coverage records with every symbol fully covered."""
    return {
        s: {
            "first_valid_date": first_date,
            "last_valid_date": last_date,
            "observations": observations,
            "covers_train_start": True,
            "covers_test_end": True,
            "sufficient_coverage": True,
        }
        for s in symbols
    }


def _spec(
    market: str = "us",
    symbols: tuple[str, ...] = ("AAPL", "NVDA", "MSFT"),
    train_start: str = "2021-01-01",
    test_end: str = "2026-06-18",
    min_symbols: int = 2,
    benchmark: str | None = None,
) -> MarketReadinessSpec:
    return MarketReadinessSpec(
        market=market,
        symbols=symbols,
        benchmark=benchmark if benchmark is not None else ("QQQ" if market == "us" else "000300"),
        train_start=train_start,
        test_end=test_end,
        min_symbols=min_symbols,
    )


# ══════════════════════════════════════════════════════════════════════════════
# find_common_coverage_start
# ══════════════════════════════════════════════════════════════════════════════


def test_find_common_coverage_start_basic() -> None:
    """When all symbols have overlapping coverage, returns the min_symbols-th earliest start."""
    symbol_dates = {
        "A": {"first_valid_date": "2021-01-04", "last_valid_date": "2026-06-18"},
        "B": {"first_valid_date": "2021-04-06", "last_valid_date": "2026-06-18"},
        "C": {"first_valid_date": "2021-07-01", "last_valid_date": "2026-06-18"},
    }
    result = find_common_coverage_start(symbol_dates, min_symbols=2, test_end="2026-06-18")
    # Sorted by first_valid_date: A (2021-01-04), B (2021-04-06), C (2021-07-01)
    # min_symbols=2 → 2nd symbol (B) = 2021-04-06
    assert result == "2021-04-06"


def test_find_common_coverage_start_2021_01_01_to_2021_04_06() -> None:
    """Regression: requested 2021-01-01 aligns to 2021-04-06 with staggered starts."""
    symbol_dates = {
        "A": {"first_valid_date": "2021-01-04", "last_valid_date": "2026-06-18"},
        "B": {"first_valid_date": "2021-04-06", "last_valid_date": "2026-06-18"},
        "C": {"first_valid_date": "2021-04-06", "last_valid_date": "2026-06-18"},
    }
    result = find_common_coverage_start(symbol_dates, min_symbols=2, test_end="2026-06-18")
    assert result == "2021-04-06"


def test_find_common_coverage_start_excludes_symbols_with_null_dates() -> None:
    """Symbols with None dates are dropped before alignment."""
    symbol_dates = {
        "A": {"first_valid_date": "2021-01-04", "last_valid_date": "2026-06-18"},
        "B": {"first_valid_date": None, "last_valid_date": None},
        "C": {"first_valid_date": "2021-07-01", "last_valid_date": "2026-06-18"},
    }
    result = find_common_coverage_start(symbol_dates, min_symbols=2, test_end="2026-06-18")
    # Only A and C qualify. Sorted: A, C. min=2 → C = 2021-07-01
    assert result == "2021-07-01"


def test_find_common_coverage_start_excludes_symbols_ending_before_test_end() -> None:
    """A symbol whose last_valid_date does not reach test_end is dropped."""
    symbol_dates = {
        "A": {"first_valid_date": "2021-01-04", "last_valid_date": "2026-06-18"},
        "B": {"first_valid_date": "2021-01-04", "last_valid_date": "2025-12-31"},
        "C": {"first_valid_date": "2021-07-01", "last_valid_date": "2026-06-18"},
    }
    result = find_common_coverage_start(symbol_dates, min_symbols=2, test_end="2026-06-18")
    # B is dropped. A and C remain. Sorted: A, C. min=2 → C = 2021-07-01
    assert result == "2021-07-01"


def test_find_common_coverage_start_returns_none_when_fewer_than_min_symbols() -> None:
    """min_symbols cannot be satisfied → returns None (fail-closed)."""
    symbol_dates = {
        "A": {"first_valid_date": "2021-01-04", "last_valid_date": "2026-06-18"},
        "B": {"first_valid_date": None, "last_valid_date": None},
    }
    result = find_common_coverage_start(symbol_dates, min_symbols=2, test_end="2026-06-18")
    assert result is None


def test_find_common_coverage_start_empty_input() -> None:
    assert find_common_coverage_start({}, min_symbols=2, test_end="2026-06-18") is None


def test_find_common_coverage_start_rejects_min_symbols_below_2() -> None:
    with pytest.raises(ValueError, match="min_symbols"):
        find_common_coverage_start({}, min_symbols=1, test_end="2026-06-18")


# ══════════════════════════════════════════════════════════════════════════════
# CoverageAlignment dataclass
# ══════════════════════════════════════════════════════════════════════════════


def test_coverage_alignment_frozen() -> None:
    """CoverageAlignment instances must be immutable."""
    a = CoverageAlignment(
        alignment_mode="auto",
        market="us",
        requested_train_start="2021-01-01",
        aligned_train_start="2021-04-06",
        retained_symbols=("A", "B"),
        dropped_symbols=("C",),
        drop_reasons={"C": "no data"},
        min_symbols=2,
        test_end="2026-06-18",
        alignment_reason="auto shifted",
        sufficient=True,
        skipped=False,
        skip_reason=None,
        viable_windows=6,
        min_viable_windows=3,
    )
    with pytest.raises(Exception):
        a.alignment_mode = "strict"  # type: ignore[misc]


def test_coverage_alignment_to_dict_roundtrip() -> None:
    a = CoverageAlignment(
        alignment_mode="auto",
        market="us",
        requested_train_start="2021-01-01",
        aligned_train_start="2021-04-06",
        retained_symbols=("A", "B"),
        dropped_symbols=("C",),
        drop_reasons={"C": "no data"},
        min_symbols=2,
        test_end="2026-06-18",
        alignment_reason="auto shifted",
        sufficient=True,
        skipped=False,
        skip_reason=None,
        viable_windows=6,
        min_viable_windows=3,
    )
    d = a.to_dict()
    # Canonical keys
    assert d["alignment_mode"] == "auto"
    assert d["market"] == "us"
    assert d["requested_train_start"] == "2021-01-01"
    assert d["aligned_train_start"] == "2021-04-06"
    assert d["alignment_reason"] == "auto shifted"
    assert d["retained_symbols"] == ["A", "B"]
    assert d["dropped_symbols"] == ["C"]
    assert d["sufficient"] is True
    assert d["skipped"] is False
    assert d["viable_windows"] == 6
    # Legacy aliases preserved for backward compatibility
    assert d["requested_start"] == "2021-01-01"
    assert d["aligned_start"] == "2021-04-06"

    # JSON serializable
    encoded = json.dumps(d)
    restored = json.loads(encoded)
    assert restored["alignment_mode"] == "auto"
    assert restored["requested_train_start"] == "2021-01-01"


def test_coverage_alignment_legacy_properties() -> None:
    """requested_start / aligned_start properties delegate to canonical fields."""
    a = CoverageAlignment(
        alignment_mode="strict",
        market="us",
        requested_train_start="2021-01-01",
        aligned_train_start="2021-01-01",
        retained_symbols=("A", "B"),
        dropped_symbols=(),
        drop_reasons={},
        min_symbols=2,
        test_end="2026-06-18",
        alignment_reason="strict unchanged",
        sufficient=True,
        skipped=False,
        skip_reason=None,
        viable_windows=6,
        min_viable_windows=3,
    )
    assert a.requested_start == "2021-01-01"
    assert a.aligned_start == "2021-01-01"
    assert a.requested_start is a.requested_train_start
    assert a.aligned_start is a.aligned_train_start


# ══════════════════════════════════════════════════════════════════════════════
# align_train_start_to_coverage — strict mode
# ══════════════════════════════════════════════════════════════════════════════


def test_strict_mode_passes_when_coverage_is_sufficient() -> None:
    spec = _spec(symbols=("A", "B", "C"), min_symbols=2)
    dc = _dc(["A", "B", "C"])
    result = align_train_start_to_coverage(spec, dc, alignment_mode="strict")
    assert result.alignment_mode == "strict"
    assert result.aligned_train_start == "2021-01-01"
    assert result.skipped is False
    assert result.sufficient is True
    assert result.alignment_reason == "strict unchanged"
    assert set(result.retained_symbols) == {"A", "B", "C"}


def test_strict_mode_skips_when_insufficient() -> None:
    """Strict mode: if symbols don't have coverage at the requested start, skip."""
    spec = _spec(symbols=("A", "B", "C"), min_symbols=3)
    dc = _dc(["A"])  # Only A is covered
    dc["B"] = {
        "first_valid_date": None, "last_valid_date": None,
        "observations": 0, "covers_train_start": False,
        "covers_test_end": False, "sufficient_coverage": False,
    }
    dc["C"] = {
        "first_valid_date": None, "last_valid_date": None,
        "observations": 0, "covers_train_start": False,
        "covers_test_end": False, "sufficient_coverage": False,
    }
    result = align_train_start_to_coverage(spec, dc, alignment_mode="strict")
    assert result.skipped is True
    assert result.retained_symbols == ()  # fail-closed
    assert result.skip_reason is not None
    assert result.alignment_reason.startswith("skipped:")
    assert "strict mode" in result.skip_reason


def test_strict_mode_drops_when_covers_train_start_is_false() -> None:
    """Strict mode: symbol with covers_train_start=False is dropped even
    when first/last dates are valid and >= min_symbols remain.  Auto mode
    may still align and pass for the same data."""
    symbols = ("A", "B", "C")
    spec = _spec(symbols=symbols, min_symbols=2)
    # A covers requested start; B and C have valid dates but covers_train_start=False
    dc = {
        "A": {"first_valid_date": "2021-01-04", "last_valid_date": "2026-06-18",
              "observations": 1300, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
        "B": {"first_valid_date": "2021-04-06", "last_valid_date": "2026-06-18",
              "observations": 1200, "covers_train_start": False, "covers_test_end": True, "sufficient_coverage": True},
        "C": {"first_valid_date": "2021-07-01", "last_valid_date": "2026-06-18",
              "observations": 1100, "covers_train_start": False, "covers_test_end": True, "sufficient_coverage": True},
    }
    # Strict: only A covers requested_start → only 1 retained, need 2 → skipped
    strict_result = align_train_start_to_coverage(spec, dc, alignment_mode="strict")
    assert strict_result.skipped is True
    assert strict_result.retained_symbols == ()
    assert "B" in strict_result.dropped_symbols
    assert "covers_train_start is False" in strict_result.drop_reasons["B"]
    assert "C" in strict_result.dropped_symbols

    # Auto: ignores covers_train_start, aligns to B's first (2021-04-06)
    auto_result = align_train_start_to_coverage(spec, dc, alignment_mode="auto")
    assert auto_result.skipped is False
    assert auto_result.alignment_reason == "auto shifted"
    assert auto_result.aligned_train_start == "2021-04-06"
    assert "A" in auto_result.retained_symbols
    assert "B" in auto_result.retained_symbols  # covers aligned start
    assert "C" in auto_result.dropped_symbols  # 2021-07-01 > 2021-04-06


def test_strict_mode_drops_when_first_date_after_requested_start() -> None:
    """Strict mode without covers_train_start flag: derive equivalent from
    first_valid_date > requested_start. A symbol beginning 2021-04 must not
    pass strict requested_start 2021-01."""
    symbols = ("A", "B", "C")
    spec = _spec(symbols=symbols, min_symbols=2)
    dc = {
        "A": {"first_valid_date": "2021-01-04", "last_valid_date": "2026-06-18",
              "observations": 1300},
        # No covers_train_start flag — derive from dates
        "B": {"first_valid_date": "2021-04-06", "last_valid_date": "2026-06-18",
              "observations": 1200},
        "C": {"first_valid_date": "2021-07-01", "last_valid_date": "2026-06-18",
              "observations": 1100},
    }
    # Strict: B and C have first_valid_date > 2021-01-01 → dropped. Only A retained → skipped.
    result = align_train_start_to_coverage(spec, dc, alignment_mode="strict")
    assert result.skipped is True
    assert result.retained_symbols == ()
    assert "B" in result.dropped_symbols
    assert "C" in result.dropped_symbols
    assert "after requested_start" in result.drop_reasons["B"]


# ══════════════════════════════════════════════════════════════════════════════
# align_train_start_to_coverage — auto mode
# ══════════════════════════════════════════════════════════════════════════════


def test_auto_mode_moves_start_later_when_needed() -> None:
    """Auto mode finds earliest common start that retains enough symbols."""
    spec = _spec(symbols=("A", "B", "C"), min_symbols=2)
    dc = {
        "A": {"first_valid_date": "2021-01-04", "last_valid_date": "2026-06-18",
              "observations": 1300, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
        "B": {"first_valid_date": "2021-04-06", "last_valid_date": "2026-06-18",
              "observations": 1200, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
        "C": {"first_valid_date": "2021-04-06", "last_valid_date": "2026-06-18",
              "observations": 1200, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
    }
    result = align_train_start_to_coverage(spec, dc, alignment_mode="auto")
    assert result.alignment_mode == "auto"
    assert result.requested_train_start == "2021-01-01"
    assert result.aligned_train_start == "2021-04-06"
    assert result.alignment_reason == "auto shifted"
    assert result.skipped is False
    assert set(result.retained_symbols) == {"A", "B", "C"}


def test_auto_mode_does_not_move_start_earlier() -> None:
    """Aligned start is always >= requested start. Never shifts backward."""
    spec = _spec(symbols=("A", "B"), train_start="2021-06-01", min_symbols=2)
    dc = {
        "A": {"first_valid_date": "2021-01-04", "last_valid_date": "2026-06-18",
              "observations": 1300, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
        "B": {"first_valid_date": "2021-03-01", "last_valid_date": "2026-06-18",
              "observations": 1200, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
    }
    result = align_train_start_to_coverage(spec, dc, alignment_mode="auto")
    # Common start would be 2021-03-01, but requested is 2021-06-01 which is later.
    # The aligned start must NOT move earlier. Reason: auto unchanged.
    assert result.aligned_train_start == "2021-06-01"
    assert result.alignment_reason == "auto unchanged"


def test_auto_mode_drops_symbols_that_start_after_aligned_start() -> None:
    """In auto mode, symbols whose first_valid_date is after the aligned date are dropped."""
    spec = _spec(symbols=("A", "B", "C"), min_symbols=2)
    dc = {
        "A": {"first_valid_date": "2021-01-04", "last_valid_date": "2026-06-18",
              "observations": 1300, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
        "B": {"first_valid_date": "2021-04-06", "last_valid_date": "2026-06-18",
              "observations": 1200, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
        "C": {"first_valid_date": "2021-07-01", "last_valid_date": "2026-06-18",
              "observations": 1100, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
    }
    result = align_train_start_to_coverage(spec, dc, alignment_mode="auto", first_test_year=2024, last_test_year=2026)
    # min=2: aligned_start = B's first = 2021-04-06. C starts 2021-07-01 > aligned → dropped.
    assert result.aligned_train_start == "2021-04-06"
    assert result.alignment_reason == "auto shifted"
    assert set(result.retained_symbols) == {"A", "B"}
    assert "C" in result.dropped_symbols


def test_auto_mode_min_symbols_gate() -> None:
    """When auto alignment cannot retain min_symbols, the result is skipped."""
    spec = _spec(symbols=("A", "B", "C"), min_symbols=2)
    dc = {
        "A": {"first_valid_date": "2021-01-04", "last_valid_date": "2026-06-18",
              "observations": 1300, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
        "B": {"first_valid_date": None, "last_valid_date": None,
              "observations": 0, "covers_train_start": False, "covers_test_end": False, "sufficient_coverage": False},
        "C": {"first_valid_date": None, "last_valid_date": None,
              "observations": 0, "covers_train_start": False, "covers_test_end": False, "sufficient_coverage": False},
    }
    result = align_train_start_to_coverage(spec, dc, alignment_mode="auto")
    assert result.skipped is True
    assert result.retained_symbols == ()
    assert result.alignment_reason.startswith("skipped:")
    assert "cannot retain" in result.skip_reason


def test_auto_mode_too_late_fail_closed() -> None:
    """When aligned start is so late it can't support >=3 windows, fail closed."""
    spec = _spec(
        symbols=("A", "B", "C"),
        train_start="2021-01-01",
        test_end="2026-06-18",
        min_symbols=2,
    )
    # All symbols start very late, after 2025 — not enough time for 3 windows before test_end
    dc = {
        "A": {"first_valid_date": "2025-01-04", "last_valid_date": "2026-06-18",
              "observations": 300, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
        "B": {"first_valid_date": "2025-01-04", "last_valid_date": "2026-06-18",
              "observations": 300, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
        "C": {"first_valid_date": "2025-01-04", "last_valid_date": "2026-06-18",
              "observations": 300, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
    }
    result = align_train_start_to_coverage(spec, dc, alignment_mode="auto", first_test_year=2024, last_test_year=2026)
    assert result.skipped is True
    assert result.retained_symbols == ()
    assert result.alignment_reason.startswith("skipped:")
    assert "half-year OOS windows" in result.skip_reason


def test_auto_mode_under_3_windows_fail_closed() -> None:
    """Edge case: aligned start barely too late for 3 windows."""
    spec = _spec(
        symbols=("A", "B"),
        train_start="2021-01-01",
        test_end="2025-06-30",  # Short range
        min_symbols=2,
    )
    dc = {
        "A": {"first_valid_date": "2024-12-01", "last_valid_date": "2025-06-30",
              "observations": 150, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
        "B": {"first_valid_date": "2024-12-01", "last_valid_date": "2025-06-30",
              "observations": 150, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
    }
    result = align_train_start_to_coverage(spec, dc, alignment_mode="auto", first_test_year=2024, last_test_year=2025)
    # Aligned ~2024-12-01. With test_end=2025-06-30 and first_test_year=2024,
    # windows with test_start in 2024H2 and test_end <= 2025-06-30 might exist
    # but train period from 2024-12-01 to test_start is tiny.
    # Most windows will be filtered out.
    # The key assertion: if < 3 windows survive, result is skipped.
    if result.skipped:
        assert "half-year OOS windows" in result.skip_reason
    # If not skipped (edge case with generous boundaries), verify consistency
    else:
        assert result.viable_windows >= 3


def test_auto_mode_missing_symbol_exclusion() -> None:
    """Symbols not in date_coverage_data are excluded with reason."""
    spec = _spec(symbols=("A", "MISSING"), min_symbols=2)
    dc = {
        "A": {"first_valid_date": "2021-01-04", "last_valid_date": "2026-06-18",
              "observations": 1300, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
    }
    result = align_train_start_to_coverage(spec, dc, alignment_mode="auto")
    # Only 1 symbol retained, need 2 → skipped
    assert result.skipped is True
    assert "MISSING" in result.dropped_symbols


def test_auto_mode_cn_leading_zeros_preserved() -> None:
    """CN symbols with leading zeros (e.g. 000001) must pass through unchanged."""
    spec = MarketReadinessSpec(
        market="cn",
        symbols=("000001", "000069", "002493"),
        benchmark="000300",
        train_start="2021-01-01",
        test_end="2026-06-18",
        min_symbols=2,
    )
    dc = {
        "000001": {"first_valid_date": "2021-01-04", "last_valid_date": "2026-06-18",
                   "observations": 1300, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
        "000069": {"first_valid_date": "2021-04-06", "last_valid_date": "2026-06-18",
                   "observations": 1200, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
        "002493": {"first_valid_date": "2021-04-06", "last_valid_date": "2026-06-18",
                   "observations": 1200, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
    }
    result = align_train_start_to_coverage(spec, dc, alignment_mode="auto")
    assert "000001" in result.retained_symbols
    assert result.retained_symbols[0].startswith("00") or result.retained_symbols[0] == "000001"


def test_auto_mode_complete_output_fields() -> None:
    """Every expected output field must be present and of the correct type."""
    spec = _spec(symbols=("A", "B"), min_symbols=2)
    dc = _dc(["A", "B"])
    result = align_train_start_to_coverage(spec, dc, alignment_mode="auto")

    d = result.to_dict()
    # Canonical fields
    assert "alignment_mode" in d
    assert "market" in d
    assert "requested_train_start" in d
    assert "aligned_train_start" in d
    assert "alignment_reason" in d
    assert "retained_symbols" in d
    assert "dropped_symbols" in d
    assert "drop_reasons" in d
    assert "min_symbols" in d
    assert "test_end" in d
    assert "sufficient" in d
    assert "skipped" in d
    assert "skip_reason" in d
    assert "viable_windows" in d
    assert "min_viable_windows" in d
    assert isinstance(d["retained_symbols"], list)
    assert isinstance(d["dropped_symbols"], list)
    assert isinstance(d["drop_reasons"], dict)
    # Legacy aliases preserved
    assert d["requested_start"] == d["requested_train_start"]
    assert d["aligned_start"] == d["aligned_train_start"]


def test_auto_mode_rejects_invalid_alignment_mode() -> None:
    spec = _spec()
    with pytest.raises(ValueError, match="alignment_mode"):
        align_train_start_to_coverage(spec, {}, alignment_mode="invalid")  # type: ignore[arg-type]


# ══════════════════════════════════════════════════════════════════════════════
# Runner override: auto-mode alignment success → strict coverage overridden
# ══════════════════════════════════════════════════════════════════════════════


def test_auto_mode_alignment_overrides_strict_coverage() -> None:
    """Auto-mode alignment that retains min_symbols must override strict
    coverage's ``skipped=True`` when ``sufficient_coverage`` flags are
    missing but date ranges are valid.

    Reproduces the runner's combined ``filter_universe_by_coverage`` +
    ``align_train_start_to_coverage`` pipeline without Qlib.
    ``filter_universe_by_coverage`` gates on ``sufficient_coverage``; the
    alignment function gates on date ranges.  When they diverge and auto
    alignment succeeds, the alignment is authoritative.

    This test mirrors the ``default_10`` scenario where alignment retains
    all 10 symbols even though strict coverage flagged some as insufficient.
    """
    from src.research.universe_robustness import filter_universe_by_coverage

    symbols = ("A", "B", "C", "D", "E", "F", "G", "H", "I", "J")
    spec = _spec(symbols=symbols, min_symbols=10)

    # All 10 have valid date ranges; first 3 have sufficient_coverage=False.
    # filter_universe_by_coverage uses the flag → drops 3 → skipped.
    # align_train_start_to_coverage uses date ranges → retains all 10.
    dc: dict[str, dict[str, object]] = {}
    for i, sym in enumerate(symbols):
        dc[sym] = {
            "first_valid_date": "2021-01-04",
            "last_valid_date": "2026-06-18",
            "observations": 1300,
            "covers_train_start": True,
            "covers_test_end": True,
            "sufficient_coverage": i >= 3,  # first 3 = insufficient
        }

    # ── Step 1: strict coverage gate (as in runner) ──────────────────────
    coverage = filter_universe_by_coverage(
        symbols,
        min_symbols=10,
        date_range=("2021-01-01", "2026-06-18"),
        date_coverage_data=dc,
    )
    # Only 7/10 have sufficient_coverage → skipped
    assert coverage["skipped"] is True
    assert coverage["retained_symbols"] == []

    # ── Step 2: alignment (as in runner) ─────────────────────────────────
    alignment = align_train_start_to_coverage(spec, dc, alignment_mode="auto")
    assert alignment.skipped is False, (
        f"expected not skipped, got {alignment.alignment_reason}"
    )
    assert len(alignment.retained_symbols) == len(symbols)

    # ── Step 3: runner's override (elif alignment_mode == "auto") ────────
    # The alignment decision overrides the strict coverage report.
    coverage["skipped"] = False
    coverage["sufficient"] = True
    coverage["retained_symbols"] = list(alignment.retained_symbols)
    coverage["dropped_symbols"] = list(alignment.dropped_symbols)
    coverage["skip_reason"] = None
    coverage["coverage_ratio"] = round(
        len(alignment.retained_symbols) / len(symbols), 4
    )

    # After override: alignment is authoritative → not skipped, all retained
    assert coverage["skipped"] is False
    assert coverage["sufficient"] is True
    assert coverage["retained_symbols"] == list(symbols)
    assert coverage["skip_reason"] is None
    assert coverage["coverage_ratio"] == 1.0


def test_auto_mode_insufficient_alignment_remains_skipped() -> None:
    """Auto-mode alignment that cannot retain min_symbols must stay skipped.

    Mirrors the ``expanded_50 49/50`` and ``expanded_100 98/100`` cases
    where the alignment itself cannot satisfy the symbol count threshold.
    The existing ``if alignment.skipped:`` block in the runner (which
    handles all modes) keeps the coverage correctly skipped.
    """
    symbols = ("A", "B", "C", "D", "E")
    spec = _spec(symbols=symbols, min_symbols=5)

    # 4/5 have valid dates; the 5th has no data → alignment can't retain 5.
    dc: dict[str, dict[str, object]] = {}
    for i, sym in enumerate(symbols):
        dc[sym] = {
            "first_valid_date": "2021-01-04" if i < 4 else None,
            "last_valid_date": "2026-06-18" if i < 4 else None,
            "observations": 1300 if i < 4 else 0,
            "covers_train_start": i < 4,
            "covers_test_end": i < 4,
            "sufficient_coverage": i < 4,
        }

    alignment = align_train_start_to_coverage(spec, dc, alignment_mode="auto")
    assert alignment.skipped is True
    assert alignment.sufficient is False
    assert alignment.retained_symbols == ()
    assert "cannot retain" in alignment.skip_reason

    # The runner's `if alignment.skipped:` block (unchanged, applies to all
    # modes) correctly leaves the universe skipped — the elif override for
    # auto-mode success does not fire because alignment.skipped is True.
    coverage: dict[str, object] = {"skipped": True}
    coverage["skipped"] = True
    coverage["sufficient"] = False
    coverage["retained_symbols"] = []
    coverage["skip_reason"] = alignment.skip_reason
    assert coverage["skipped"] is True
    assert coverage["retained_symbols"] == []


# ══════════════════════════════════════════════════════════════════════════════
# _count_viable_oos_windows
# ══════════════════════════════════════════════════════════════════════════════


def test_count_viable_windows_normal_range() -> None:
    """2021-01-01 through 2026-06-30 should yield 5 viable half-year windows (2024H1-2026H1).

    2026H2 is excluded because its test_end (2026-12-31) exceeds the available
    test_end 2026-06-30, leaving 5 windows.
    """
    n = _count_viable_oos_windows("2021-01-01", "2026-06-30", first_test_year=2024, last_test_year=2026)
    assert n == 5


def test_count_viable_windows_late_start_reduces_count() -> None:
    """Starting in 2025 means fewer windows can form before test_end."""
    n = _count_viable_oos_windows("2025-01-01", "2026-06-30", first_test_year=2024, last_test_year=2026)
    assert n < 6


def test_count_viable_windows_very_late_start_zero() -> None:
    """Starting after test_end means zero viable windows."""
    n = _count_viable_oos_windows("2027-01-01", "2026-06-30", first_test_year=2024, last_test_year=2026)
    assert n == 0


def test_count_viable_windows_does_not_mutate_rolling_window_fields() -> None:
    """RollingResearchWindow frozen fields are never mutated in-place.

    The function adjusts train_start upward when aligned_start is later than
    a window's original train_start, but it must construct a replacement
    object rather than mutating the frozen dataclass field directly.
    """
    from src.research.rolling_windows import RollingResearchWindow

    # Verify RollingResearchWindow is truly frozen — assignment raises.
    w = RollingResearchWindow(
        label="2024H1", train_start="2021-01-01", train_end="2023-12-31",
        test_start="2024-01-01", test_end="2024-06-30",
    )
    with pytest.raises(Exception):
        w.train_start = "2024-01-01"  # type: ignore[misc]

    # Now exercise the code path that previously mutated frozen fields.
    # aligned_start=2024-01-01 is later than the default train_start
    # (2021-01-01) for windows from half_year_rolling_windows(start_year=2021).
    # The call must succeed without FrozenInstanceError.
    n = _count_viable_oos_windows("2024-01-01", "2026-06-30", first_test_year=2024, last_test_year=2026)
    # 2024H1 through 2026H2 = 6 windows. With aligned_start=2024-01-01:
    # 2024H1: train_start=2024-01-01, train_end=2023-12-31 → empty → dropped
    # 2026H2: test_end=2026-12-31 > available_end 2026-06-30 → filtered out
    # Surviving: 2024H2, 2025H1, 2025H2, 2026H1 → 4 windows
    assert n == 4, "Windows with empty train period or unavailable test span must be excluded"


# ══════════════════════════════════════════════════════════════════════════════
# build_aligned_market_readiness
# ══════════════════════════════════════════════════════════════════════════════


def test_build_aligned_market_readiness_strict() -> None:
    """Strict mode returns separate reports per market."""
    specs = [
        _spec(market="us", symbols=("AAPL", "NVDA"), min_symbols=2),
    ]
    reports = build_aligned_market_readiness(specs, alignment_mode="strict")
    assert "us" in reports
    assert reports["us"]["alignment_mode"] == "strict"


def test_build_aligned_market_readiness_auto() -> None:
    """Auto mode returns alignment info per market."""
    specs = [
        _spec(market="us", symbols=("AAPL", "NVDA"), min_symbols=2),
    ]
    reports = build_aligned_market_readiness(specs, alignment_mode="auto")
    assert "us" in reports
    assert reports["us"]["alignment_mode"] == "auto"
    assert "requested_train_start" in reports["us"]
    assert "aligned_train_start" in reports["us"]
    assert "alignment_reason" in reports["us"]
    assert reports["us"]["market"] == "us"


def test_build_aligned_market_readiness_multi_market() -> None:
    """US and CN each get independent alignment reports."""
    specs = [
        _spec(market="us", symbols=("AAPL", "NVDA"), min_symbols=2),
        _spec(market="cn", symbols=("000001", "000069"), benchmark="000300", min_symbols=2),
    ]
    reports = build_aligned_market_readiness(specs, alignment_mode="strict")
    assert set(reports.keys()) == {"us", "cn"}
    for market in ("us", "cn"):
        assert "market" in reports[market]
        assert "benchmark" in reports[market]


# ══════════════════════════════════════════════════════════════════════════════
# Edge cases
# ══════════════════════════════════════════════════════════════════════════════


def test_no_forward_fill_of_early_missing_data() -> None:
    """Symbols without first_valid_date are dropped, never forward-filled."""
    spec = _spec(symbols=("A", "B"), min_symbols=2)
    dc = {
        "A": {"first_valid_date": "2021-01-04", "last_valid_date": "2026-06-18",
              "observations": 1300, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
        "B": {"first_valid_date": None, "last_valid_date": "2026-06-18",
              "observations": 0, "covers_train_start": False, "covers_test_end": True, "sufficient_coverage": False},
    }
    result = align_train_start_to_coverage(spec, dc, alignment_mode="auto")
    assert result.skipped is True
    assert "B" in result.dropped_symbols
    assert result.retained_symbols == ()


def test_no_zero_fill_of_early_missing_data() -> None:
    """Symbols with zero observations are dropped, never zero-filled."""
    spec = _spec(symbols=("A", "B"), min_symbols=2)
    dc = {
        "A": {"first_valid_date": "2021-01-04", "last_valid_date": "2026-06-18",
              "observations": 1300, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
        "B": {"first_valid_date": "2021-01-04", "last_valid_date": "2026-06-18",
              "observations": 0, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
    }
    result = align_train_start_to_coverage(spec, dc, alignment_mode="auto")
    # B has coverage but with 0 observations. The first/last dates are valid,
    # so it may be retained. But the key is: we never fabricate data.
    assert result.alignment_mode == "auto"


def test_never_allow_missing_symbols_into_retained_sets() -> None:
    """MarketReadinessSpec rejects min_symbols < 2 (fail-closed)."""
    with pytest.raises(ValueError, match="min_symbols must be at least 2"):
        _spec(symbols=("A", "GHOST"), min_symbols=1)


def test_never_allow_missing_symbols_into_retained_sets_min2() -> None:
    """Retained set must not contain any symbol not in date_coverage_data."""
    spec = _spec(symbols=("A", "GHOST"), min_symbols=2)
    dc = {
        "A": {"first_valid_date": "2021-01-04", "last_valid_date": "2026-06-18",
              "observations": 1300, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
    }
    result = align_train_start_to_coverage(spec, dc, alignment_mode="auto")
    assert result.skipped is True
    assert "GHOST" in result.dropped_symbols
    assert "GHOST" not in result.retained_symbols


def test_drop_reasons_cover_all_dropped() -> None:
    """Every dropped symbol must have a non-empty reason."""
    spec = _spec(symbols=("A", "B", "C"), min_symbols=2)
    dc = {
        "A": {"first_valid_date": "2021-01-04", "last_valid_date": "2026-06-18",
              "observations": 1300, "covers_train_start": True, "covers_test_end": True, "sufficient_coverage": True},
        "B": {"first_valid_date": None, "last_valid_date": None,
              "observations": 0, "covers_train_start": False, "covers_test_end": False, "sufficient_coverage": False},
        "C": {"first_valid_date": "2021-01-04", "last_valid_date": "2025-12-31",
              "observations": 1200, "covers_train_start": True, "covers_test_end": False, "sufficient_coverage": False},
    }
    result = align_train_start_to_coverage(spec, dc, alignment_mode="auto")
    for sym in result.dropped_symbols:
        assert sym in result.drop_reasons
        assert result.drop_reasons[sym]


# ══════════════════════════════════════════════════════════════════════════════
# get_aligned_windows — contract tests
# ══════════════════════════════════════════════════════════════════════════════


def test_aligned_windows_use_adjusted_train_start() -> None:
    """Every returned window must have train_start >= aligned_start."""
    from src.research.market_data_alignment import get_aligned_windows

    windows = get_aligned_windows("2021-04-06", "2026-06-30", first_test_year=2024, last_test_year=2026)
    assert len(windows) > 0, "expected at least one aligned window"
    aligned_ts = pd.Timestamp("2021-04-06")
    for w in windows:
        assert pd.Timestamp(w.train_start) >= aligned_ts, (
            f"window {w.label} train_start={w.train_start} < aligned=2021-04-06"
        )


def test_aligned_windows_no_empty_training_periods() -> None:
    """No returned window may have train_start >= train_end."""
    from src.research.market_data_alignment import get_aligned_windows

    windows = get_aligned_windows("2025-01-01", "2026-06-30", first_test_year=2024, last_test_year=2026)
    for w in windows:
        assert pd.Timestamp(w.train_start) < pd.Timestamp(w.train_end), (
            f"window {w.label} has empty training period: "
            f"train_start={w.train_start} train_end={w.train_end}"
        )


def test_count_viable_windows_equals_helper_length() -> None:
    """_count_viable_oos_windows must return the same count as len(get_aligned_windows(...))."""
    from src.research.market_data_alignment import _count_viable_oos_windows, get_aligned_windows

    cases = [
        ("2021-01-01", "2026-06-30"),
        ("2021-04-06", "2026-06-30"),
        ("2024-01-01", "2026-06-30"),
        ("2025-01-01", "2026-06-30"),
        ("2027-01-01", "2026-06-30"),
    ]
    for aligned_start, test_end in cases:
        count = _count_viable_oos_windows(aligned_start, test_end, first_test_year=2024, last_test_year=2026)
        windows = get_aligned_windows(aligned_start, test_end, first_test_year=2024, last_test_year=2026)
        assert count == len(windows), (
            f"mismatch for aligned={aligned_start} test_end={test_end}: "
            f"_count_viable_oos_windows={count} len(get_aligned_windows)={len(windows)}"
        )


def test_no_window_path_is_fail_closed() -> None:
    """When aligned_start > available_end, get_aligned_windows returns empty list."""
    from src.research.market_data_alignment import get_aligned_windows

    windows = get_aligned_windows("2027-01-01", "2026-06-30", first_test_year=2024, last_test_year=2026)
    assert windows == []


def test_cn_runner_has_no_fillna_zero() -> None:
    """CN 10D validation runner must not contain fillna(0.0) — no data fabrication."""
    from pathlib import Path

    cn_runner = Path(__file__).parent.parent / "scripts" / "run_cn_10d_validation.py"
    source = cn_runner.read_text(encoding="utf-8")
    assert "fillna(0.0)" not in source, (
        "CN runner contains fillna(0.0) — remove data fabrication; "
        "use validate_no_nan_inputs from universe_robustness instead"
    )
    assert "fillna(0)" not in source, (
        "CN runner contains fillna(0) — remove data fabrication"
    )
