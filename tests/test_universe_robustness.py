from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.research.universe_robustness import (
    FROZEN_BASELINE_NAME,
    FROZEN_BLEND_WEIGHT,
    FROZEN_RANKER_NAME,
    UniverseSpec,
    _identify_index_levels,
    _parse_qlib_features_frame,
    build_required_candidate_names,
    check_universe_coverage,
    default_universe_specs,
    filter_universe_by_coverage,
    load_symbol_date_coverage,
    summarize_universe_robustness,
    validate_no_nan_inputs,
)


# ── UniverseSpec ────────────────────────────────────────────────────────────

def test_universe_spec_construction_and_to_dict() -> None:
    spec = UniverseSpec(name="test_universe", symbols=("AAPL", "NVDA", "MSFT"), min_symbols=2)
    d = spec.to_dict()
    assert d["name"] == "test_universe"
    assert d["symbols"] == ["AAPL", "NVDA", "MSFT"]
    assert d["min_symbols"] == 2


def test_universe_spec_from_dict_roundtrip() -> None:
    original = UniverseSpec(name="us_large", symbols=("A", "B", "C"), min_symbols=5)
    data = original.to_dict()
    restored = UniverseSpec.from_dict(data)
    assert restored.name == original.name
    assert restored.symbols == original.symbols
    assert restored.min_symbols == original.min_symbols


def test_universe_spec_from_dict_default_min_symbols() -> None:
    spec = UniverseSpec.from_dict({"name": "us_large", "symbols": ["A", "B", "C"]})
    assert spec.min_symbols == 2


def test_universe_spec_json_serialization() -> None:
    spec = UniverseSpec(name="us", symbols=("AAPL", "NVDA"), min_symbols=2)
    encoded = json.dumps(spec.to_dict())
    data = json.loads(encoded)
    restored = UniverseSpec.from_dict(data)
    assert restored == spec


def test_universe_spec_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="name"):
        UniverseSpec(name="", symbols=("A", "B"), min_symbols=2)


def test_universe_spec_empty_symbols_allows_and_marks_skipped() -> None:
    """Empty symbols are accepted (for expanded specs with no local candidates)."""
    spec = UniverseSpec(name="expanded_50_symbols", symbols=(), min_symbols=50)
    d = spec.to_dict()
    assert d["name"] == "expanded_50_symbols"
    assert d["symbols"] == []
    assert d["min_symbols"] == 50
    # Roundtrip
    restored = UniverseSpec.from_dict(d)
    assert restored == spec
    assert restored.symbols == ()
    # filter_universe_by_coverage marks it skipped with no retained symbols
    report = filter_universe_by_coverage(
        (),
        {"AAPL", "NVDA"},
        min_symbols=50,
    )
    assert report["requested_symbols"] == []
    assert report["coverage_ratio"] == 0.0
    assert report["skipped"] is True
    assert report["retained_symbols"] == []


def test_universe_spec_rejects_non_string_symbols() -> None:
    with pytest.raises(ValueError, match="strings"):
        UniverseSpec(name="us", symbols=(1, 2, 3), min_symbols=2)  # type: ignore[arg-type]


def test_universe_spec_rejects_min_symbols_below_2() -> None:
    with pytest.raises(ValueError, match="min_symbols"):
        UniverseSpec(name="us", symbols=("A", "B"), min_symbols=1)


def test_universe_spec_rejects_duplicate_symbols() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        UniverseSpec(name="us", symbols=("A", "B", "A"), min_symbols=2)


# ── default_universe_specs ──────────────────────────────────────────────────

TEN_SESSION = ["AAPL", "NVDA", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "COST", "NFLX"]


def test_default_universe_specs_returns_exactly_three() -> None:
    specs = default_universe_specs(TEN_SESSION, market="us")
    assert len(specs) == 3


def test_default_universe_specs_names_in_order() -> None:
    specs = default_universe_specs(TEN_SESSION, market="us")
    names = [s.name for s in specs]
    assert names == ["default_10_symbols", "expanded_50_symbols", "expanded_100_symbols"]


def test_default_universe_specs_default_10_contains_session() -> None:
    specs = default_universe_specs(TEN_SESSION, market="us")
    d10 = next(s for s in specs if s.name == "default_10_symbols")
    assert set(d10.symbols) == set(TEN_SESSION)
    assert d10.min_symbols == 8


def test_default_universe_specs_tiny_session_still_returns_all_three() -> None:
    specs = default_universe_specs(["AAPL"], market="us")
    assert len(specs) == 3
    d10 = next(s for s in specs if s.name == "default_10_symbols")
    assert d10.symbols == ("AAPL",)
    assert d10.min_symbols == 8  # coverage will mark skipped


def test_default_universe_specs_with_extra_symbols_populates_expanded() -> None:
    """expanded_50 contains session + extra locals (nested, not disjoint)."""
    extra = ["XOM", "CVX", "JPM", "BAC", "WMT", "PG", "JNJ", "UNH", "HD", "DIS"]
    specs = default_universe_specs(
        TEN_SESSION,
        market="us",
        watchlist_symbols=TEN_SESSION + extra,
        qlib_symbols=[],
    )
    e50 = next(s for s in specs if s.name == "expanded_50_symbols")
    # Nested: session (10) + extra locals (10) = 20 total
    assert len(e50.symbols) == 20
    for sym in extra:
        assert sym in e50.symbols
    for sym in TEN_SESSION:
        assert sym in e50.symbols  # session symbols are part of expanded_50
    assert e50.min_symbols == 50


def test_default_universe_specs_expanded_100_contains_expanded_50() -> None:
    """expanded_100_symbols is a strict superset of expanded_50_symbols (nested construction)."""
    extra_50 = [f"SYM{i:04d}" for i in range(50)]
    extra_100 = [f"BIG{i:04d}" for i in range(100)]
    all_local = TEN_SESSION + extra_50 + extra_100
    specs = default_universe_specs(
        TEN_SESSION,
        market="us",
        watchlist_symbols=all_local,
        qlib_symbols=[],
    )
    e50_spec = next(s for s in specs if s.name == "expanded_50_symbols")
    e100_spec = next(s for s in specs if s.name == "expanded_100_symbols")
    e50 = set(e50_spec.symbols)
    e100 = set(e100_spec.symbols)
    assert len(e50) == 50
    assert len(e100) == 100
    assert e50.issubset(e100)  # nested: e100 contains all of e50
    assert e50_spec.min_symbols == 50
    assert e100_spec.min_symbols == 100


def test_default_universe_specs_produces_unique_names() -> None:
    specs = default_universe_specs(TEN_SESSION, market="us")
    names = [s.name for s in specs]
    assert len(names) == len(set(names))


# ── filter_universe_by_coverage ─────────────────────────────────────────────

def test_filter_all_available() -> None:
    report = filter_universe_by_coverage(
        ("AAPL", "NVDA", "MSFT"),
        {"AAPL", "NVDA", "MSFT", "GOOGL"},
        min_symbols=2,
    )
    assert report["requested_symbols"] == ["AAPL", "MSFT", "NVDA"]
    assert report["retained_symbols"] == ["AAPL", "MSFT", "NVDA"]
    assert report["dropped_symbols"] == []
    assert report["coverage_ratio"] == 1.0
    assert report["sufficient"] is True
    assert report["skipped"] is False


def test_filter_partial_drop() -> None:
    report = filter_universe_by_coverage(
        ("AAPL", "NVDA", "BOGUS"),
        {"AAPL", "NVDA"},
        min_symbols=2,
    )
    assert report["requested_symbols"] == ["AAPL", "BOGUS", "NVDA"]
    assert report["retained_symbols"] == ["AAPL", "NVDA"]
    assert report["dropped_symbols"] == ["BOGUS"]
    assert report["coverage_ratio"] == pytest.approx(2 / 3, abs=0.01)
    assert report["sufficient"] is True
    assert report["skipped"] is False


def test_filter_insufficient_marks_skipped() -> None:
    report = filter_universe_by_coverage(
        ("AAPL", "NVDA", "MSFT"),
        {"AAPL"},
        min_symbols=2,
    )
    assert report["retained_symbols"] == []  # emptied
    assert report["coverage_ratio"] == pytest.approx(1 / 3, abs=0.01)
    assert report["sufficient"] is False
    assert report["skipped"] is True


def test_filter_insufficient_cannot_provide_evidence() -> None:
    """Fail-closed: insufficient universes return empty retained_symbols."""
    report = filter_universe_by_coverage(
        ("A", "B", "C"),
        {"A"},
        min_symbols=3,
    )
    assert report["skipped"] is True
    assert report["sufficient"] is False
    assert report["retained_symbols"] == []  # must not leak symbols


def test_filter_with_date_range() -> None:
    report = filter_universe_by_coverage(
        ("AAPL", "NVDA"),
        {"AAPL", "NVDA", "GOOGL"},
        min_symbols=2,
        date_range=("2021-01-01", "2026-06-30"),
    )
    assert report["date_range"] == {"start": "2021-01-01", "end": "2026-06-30"}


def test_filter_empty_requested() -> None:
    report = filter_universe_by_coverage(
        (),
        {"AAPL", "NVDA"},
        min_symbols=2,
    )
    assert report["requested_symbols"] == []
    assert report["coverage_ratio"] == 0.0
    assert report["skipped"] is True
    assert report["retained_symbols"] == []


def test_filter_preserves_date_range_in_output() -> None:
    report = filter_universe_by_coverage(
        ("AAPL",),
        {"AAPL", "NVDA"},
        min_symbols=2,
        date_range=("2020-01-01", "2025-12-31"),
    )
    assert "date_range" in report
    assert report["date_range"]["start"] == "2020-01-01"


# ── nested universe construction (defect 1) ──────────────────────────────────


def test_default_universe_specs_nested_containment() -> None:
    """expanded_50 contains default_10; expanded_100 contains expanded_50."""
    extra = [f"LOCAL{i:03d}" for i in range(200)]
    specs = default_universe_specs(
        TEN_SESSION,
        market="us",
        watchlist_symbols=TEN_SESSION + extra,
        qlib_symbols=[],
    )
    d10 = set(next(s for s in specs if s.name == "default_10_symbols").symbols)
    e50 = set(next(s for s in specs if s.name == "expanded_50_symbols").symbols)
    e100 = set(next(s for s in specs if s.name == "expanded_100_symbols").symbols)

    assert d10.issubset(e50), "default_10 must be subset of expanded_50"
    assert e50.issubset(e100), "expanded_50 must be subset of expanded_100"
    assert d10.issubset(e100), "default_10 must be subset of expanded_100"
    assert len(e50) == 50
    assert len(e100) == 100


def test_default_universe_specs_expanded_50_contains_session_plus_locals() -> None:
    """expanded_50 has session symbols first, then locals, up to 50 total."""
    locals_ = [f"L{i:03d}" for i in range(100)]
    specs = default_universe_specs(
        TEN_SESSION,
        market="us",
        watchlist_symbols=TEN_SESSION + locals_,
        qlib_symbols=[],
    )
    e50 = next(s for s in specs if s.name == "expanded_50_symbols").symbols
    assert len(e50) == 50
    # Session symbols come first (stable order)
    for sym in TEN_SESSION:
        assert sym in e50


# ── date coverage validation (defect 2) ──────────────────────────────────────


def _make_date_coverage(
    symbols: list[str],
    first_date: str = "2021-01-04",
    last_date: str = "2026-06-30",
    observations: int = 1300,
    sufficient: bool = True,
) -> dict[str, dict[str, object]]:
    return {
        s: {
            "first_valid_date": first_date,
            "last_valid_date": last_date,
            "observations": observations,
            "covers_train_start": sufficient,
            "covers_test_end": sufficient,
            "sufficient_coverage": sufficient,
        }
        for s in symbols
    }


def test_filter_with_date_coverage_data_retains_covered_symbols() -> None:
    dc = _make_date_coverage(["AAPL", "NVDA", "MSFT"])
    report = filter_universe_by_coverage(
        ("AAPL", "NVDA", "MSFT"),
        min_symbols=2,
        date_range=("2021-01-01", "2026-06-30"),
        date_coverage_data=dc,
    )
    assert report["requested_symbols"] == ["AAPL", "MSFT", "NVDA"]
    assert report["retained_symbols"] == ["AAPL", "MSFT", "NVDA"]
    assert report["dropped_symbols"] == []
    assert report["coverage_ratio"] == 1.0
    assert report["sufficient"] is True
    assert report["skipped"] is False
    assert "date_coverage" in report
    # Per-symbol fields
    for sym in ["AAPL", "NVDA", "MSFT"]:
        assert sym in report["date_coverage"]
        assert report["date_coverage"][sym]["first_valid_date"] == "2021-01-04"
        assert report["date_coverage"][sym]["last_valid_date"] == "2026-06-30"
        assert report["date_coverage"][sym]["observations"] == 1300
        assert report["date_coverage"][sym]["sufficient_coverage"] is True


def test_filter_date_coverage_drops_uncovered_symbols() -> None:
    dc = _make_date_coverage(["AAPL", "NVDA"], sufficient=True)
    dc["BOGUS"] = {
        "first_valid_date": None,
        "last_valid_date": None,
        "observations": 0,
        "covers_train_start": False,
        "covers_test_end": False,
        "sufficient_coverage": False,
    }
    report = filter_universe_by_coverage(
        ("AAPL", "NVDA", "BOGUS"),
        min_symbols=2,
        date_range=("2021-01-01", "2026-06-30"),
        date_coverage_data=dc,
    )
    assert report["retained_symbols"] == ["AAPL", "NVDA"]
    assert report["dropped_symbols"] == ["BOGUS"]
    assert report["sufficient"] is True


def test_filter_date_coverage_fail_closed_insufficient() -> None:
    """Only 1 of 3 symbols has coverage — universe is skipped with empty retained."""
    dc = _make_date_coverage(["AAPL"], sufficient=True)
    dc["NVDA"] = {
        "first_valid_date": None,
        "last_valid_date": None,
        "observations": 0,
        "covers_train_start": False,
        "covers_test_end": False,
        "sufficient_coverage": False,
    }
    dc["MSFT"] = {
        "first_valid_date": None,
        "last_valid_date": None,
        "observations": 0,
        "covers_train_start": False,
        "covers_test_end": False,
        "sufficient_coverage": False,
    }
    report = filter_universe_by_coverage(
        ("AAPL", "NVDA", "MSFT"),
        min_symbols=3,
        date_range=("2021-01-01", "2026-06-30"),
        date_coverage_data=dc,
    )
    assert report["skipped"] is True
    assert report["sufficient"] is False
    assert report["retained_symbols"] == []  # fail-closed
    assert report["skip_reason"] is not None
    assert "insufficient date coverage" in report["skip_reason"]


def test_filter_date_coverage_includes_per_symbol_nulls_for_missing() -> None:
    """Symbols not in date_coverage_data get null entries in report."""
    dc = _make_date_coverage(["AAPL"])
    report = filter_universe_by_coverage(
        ("AAPL", "MISSING"),
        min_symbols=1,
        date_range=("2021-01-01", "2026-06-30"),
        date_coverage_data=dc,
    )
    assert "MISSING" in report["date_coverage"]
    assert report["date_coverage"]["MISSING"]["first_valid_date"] is None
    assert report["date_coverage"]["MISSING"]["sufficient_coverage"] is False


def test_filter_date_coverage_no_data_falls_back_to_name_based() -> None:
    """When date_coverage_data is None, falls back to available_symbols set."""
    report = filter_universe_by_coverage(
        ("AAPL", "NVDA"),
        {"AAPL", "NVDA", "GOOGL"},
        min_symbols=2,
    )
    assert report["retained_symbols"] == ["AAPL", "NVDA"]
    assert report["sufficient"] is True
    assert "date_coverage" not in report


# ── candidate naming contract (defect 3) ─────────────────────────────────────


def test_frozen_ranker_name_includes_feature_group_and_calibration() -> None:
    assert "momentum_volatility_volume" in FROZEN_RANKER_NAME
    assert "gain5_round100_leaves31_leaf10_lr0.05" in FROZEN_RANKER_NAME
    assert FROZEN_RANKER_NAME.startswith("lgbm:daily_ranker:")


def test_frozen_baseline_name_is_canonical() -> None:
    assert FROZEN_BASELINE_NAME == "factor:historical_momentum_10d"


def test_build_required_candidate_names_returns_three_keys() -> None:
    names = build_required_candidate_names()
    assert set(names.keys()) == {"ranker", "blend", "baseline"}


def test_build_required_candidate_names_blend_uses_build_blend_candidates() -> None:
    """The blend name is produced by build_blend_candidates, not manually composed."""
    names = build_required_candidate_names()
    assert names["ranker"] == FROZEN_RANKER_NAME
    assert names["baseline"] == FROZEN_BASELINE_NAME
    # The blend name must use the exact pattern from build_blend_candidates
    assert names["blend"].startswith("blend:ranker_momentum:")
    short_ranker = FROZEN_RANKER_NAME.replace("lgbm:daily_ranker:", "")
    assert short_ranker in names["blend"]
    assert "ranker0.5_momentum0.5" in names["blend"]


def test_build_required_candidate_names_respects_custom_parameters() -> None:
    names = build_required_candidate_names(
        ranker_name="lgbm:daily_ranker:custom:cal",
        blend_weight=0.75,
    )
    assert names["ranker"] == "lgbm:daily_ranker:custom:cal"
    assert "ranker0.75_momentum0.25" in names["blend"]


# ── NaN / zero-fill validation (defect 4) ────────────────────────────────────


def test_validate_no_nan_inputs_passes_valid_data() -> None:
    import pandas as pd
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]})
    ok, reason = validate_no_nan_inputs(df, context="features")
    assert ok is True
    assert reason is None


def test_validate_no_nan_inputs_rejects_all_nan() -> None:
    import numpy as np
    import pandas as pd
    df = pd.DataFrame({"a": [np.nan, np.nan], "b": [np.nan, np.nan]})
    ok, reason = validate_no_nan_inputs(df, context="returns")
    assert ok is False
    assert reason is not None
    assert "NaN" in reason


def test_validate_no_nan_inputs_rejects_zero_filled() -> None:
    """Data that was NaN→0 filled should be rejected with an explicit reason."""
    import numpy as np
    import pandas as pd
    df = pd.DataFrame({"a": [0.0, 0.0, 0.0], "b": [0.0, 0.0, np.nan]})
    ok, reason = validate_no_nan_inputs(df, context="features")
    assert ok is False
    assert reason is not None
    assert "zero" in reason.lower()


def test_validate_no_nan_inputs_rejects_empty() -> None:
    import pandas as pd
    df = pd.DataFrame()
    ok, reason = validate_no_nan_inputs(df, context="scores")
    assert ok is False
    assert "empty" in reason


# ── check_universe_coverage (compatibility alias) ───────────────────────────

def test_check_compat_alias_maps_fields() -> None:
    report = check_universe_coverage(
        ("AAPL", "NVDA", "MSFT"),
        {"AAPL", "NVDA", "MSFT", "GOOGL"},
        min_symbols=2,
    )
    # Legacy field names
    assert report["requested_count"] == 3
    assert report["retained_count"] == 3
    assert report["dropped_count"] == 0
    assert report["coverage_ratio"] == 1.0
    assert report["retained"] == ["AAPL", "MSFT", "NVDA"]
    assert report["sufficient"] is True
    assert report["skipped"] is False


def test_check_compat_insufficient_closes_gate() -> None:
    report = check_universe_coverage(
        ("A", "B", "C"),
        {"A"},
        min_symbols=3,
    )
    assert report["skipped"] is True
    assert report["sufficient"] is False
    assert report["retained"] == []  # fail-closed


def test_check_compat_with_date_range() -> None:
    report = check_universe_coverage(
        ("AAPL", "NVDA"),
        {"AAPL", "NVDA", "GOOGL"},
        min_symbols=2,
        date_range=("2021-01-01", "2026-06-30"),
    )
    # Compat alias includes date_coverage from the underlying report
    assert "date_coverage" in report
    assert report["date_coverage"] is None  # None when no date_coverage_data supplied


# ── summarize_universe_robustness ────────────────────────────────────────────


def _make_summary(
    blend_label: str,
    mean_icir: float,
    worst_drawdown: float,
    ready_ratio: float,
    n_reports: int = 4,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "min_windows": 3,
        "n_reports": n_reports,
        "n_candidates": 2,
        "candidates": [
            {
                "candidate": blend_label,
                "n_windows": n_reports,
                "mean_icir": mean_icir,
                "mean_rank_ic": 0.07,
                "mean_spread": 0.015,
                "positive_icir_ratio": 1.0,
                "positive_spread_ratio": 0.75,
                "worst_drawdown": worst_drawdown,
                "ready_ratio": ready_ratio,
                "stable_research_candidate": True,
            },
            {
                "candidate": "factor:historical_momentum_10d/factor_baseline/original",
                "n_windows": n_reports,
                "mean_icir": 0.05,
                "mean_rank_ic": 0.02,
                "mean_spread": 0.005,
                "positive_icir_ratio": 0.50,
                "positive_spread_ratio": 0.50,
                "worst_drawdown": -0.25,
                "ready_ratio": 0.0,
                "stable_research_candidate": False,
            },
        ],
        "best_candidate": blend_label,
    }


def test_summarize_compares_fixed_blend_row() -> None:
    """Uses blend: candidate, not arbitrary best."""
    results = {
        "default_10_symbols": _make_summary(
            "blend:ranker_momentum:...:ranker0.5_momentum0.5/signal_blend/original",
            0.25, -0.12, 0.25,
        ),
        "expanded_50_symbols": _make_summary(
            "blend:ranker_momentum:...:ranker0.5_momentum0.5/signal_blend/original",
            0.18, -0.18, 0.10,
        ),
    }
    summary = summarize_universe_robustness(results)

    assert summary["n_universes"] == 2
    assert summary["n_evaluated"] == 2
    assert summary["n_skipped"] == 0
    assert summary["decision_status"] == "universe_stronger_research_candidate"
    assert summary["best_universe"] is not None
    assert summary["best_universe"]["universe"] == "default_10_symbols"
    assert summary["best_universe"]["mean_icir"] == 0.25
    assert summary["best_universe"]["blend_candidate"] is not None
    assert "blend:" in str(summary["best_universe"]["blend_candidate"])


def test_summarize_handles_skipped_universes() -> None:
    results = {
        "default_10_symbols": _make_summary(
            "blend:.../signal_blend/original", 0.25, -0.12, 0.25,
        ),
        "expanded_50_symbols": None,
    }
    summary = summarize_universe_robustness(results)

    assert summary["n_evaluated"] == 1
    assert summary["n_skipped"] == 1
    assert "expanded_50_symbols" in summary["skipped_universes"]
    assert summary["best_universe"]["universe"] == "default_10_symbols"


def test_summarize_reports_expanded_universe_skipped() -> None:
    results = {
        "default_10_symbols": _make_summary(
            "blend:.../signal_blend/original", 0.25, -0.12, 0.25,
        ),
        "expanded_100_symbols": None,
    }
    summary = summarize_universe_robustness(results)

    skipped_row = next(
        r for r in summary["universe_rows"] if r["universe"] == "expanded_100_symbols"
    )
    assert skipped_row["status"] == "skipped"
    assert skipped_row["blend_candidate"] is None
    assert skipped_row["mean_icir"] is None


def test_summarize_all_skipped() -> None:
    results = {
        "default_10_symbols": None,
        "expanded_50_symbols": None,
    }
    summary = summarize_universe_robustness(results)

    assert summary["n_evaluated"] == 0
    assert summary["n_skipped"] == 2
    assert summary["decision_status"] == "no_universe_evaluated"
    assert summary["best_universe"] is None
    assert summary["trade_ready"] is False


def test_summarize_trade_ready_requires_all_three_gates() -> None:
    """ICIR >= 0.30, drawdown >= -0.15, ready_ratio >= 0.75."""
    results = {
        "default_10_symbols": _make_summary(
            "blend:.../signal_blend/original", 0.35, -0.10, 0.80,
        ),
    }
    summary = summarize_universe_robustness(results)
    assert summary["decision_status"] == "universe_robust_research_candidate"
    assert summary["trade_ready"] is True
    assert summary["best_universe"]["failed_gates"] == []


def test_summarize_not_trade_ready_when_drawdown_too_deep() -> None:
    """High ICIR and ready ratio alone are insufficient."""
    results = {
        "default_10_symbols": _make_summary(
            "blend:.../signal_blend/original", 0.35, -0.20, 0.80,
        ),
    }
    summary = summarize_universe_robustness(results)
    assert summary["trade_ready"] is False
    assert "worst_drawdown" in (summary["best_universe"]["failed_gates"] or [])
    # Might still be stronger research if ICIR >= 0.20
    assert summary["decision_status"] != "universe_robust_research_candidate"


def test_summarize_not_trade_ready_when_icir_too_low() -> None:
    results = {
        "default_10_symbols": _make_summary(
            "blend:.../signal_blend/original", 0.25, -0.10, 0.80,
        ),
    }
    summary = summarize_universe_robustness(results)
    assert summary["trade_ready"] is False
    assert "mean_icir" in summary["best_universe"]["failed_gates"]


def test_summarize_not_trade_ready_when_ready_ratio_too_low() -> None:
    results = {
        "default_10_symbols": _make_summary(
            "blend:.../signal_blend/original", 0.35, -0.10, 0.50,
        ),
    }
    summary = summarize_universe_robustness(results)
    assert summary["trade_ready"] is False
    assert "ready_ratio" in summary["best_universe"]["failed_gates"]


def test_summarize_research_candidate_status() -> None:
    results = {
        "default_10_symbols": _make_summary(
            "blend:.../signal_blend/original", 0.15, -0.20, 0.10,
        ),
    }
    summary = summarize_universe_robustness(results)
    assert summary["decision_status"] == "universe_research_candidate"


def test_summarize_stronger_requires_controlled_drawdown() -> None:
    """ICIR >= 0.20 with drawdown >= -0.15."""
    results = {
        "default_10_symbols": _make_summary(
            "blend:.../signal_blend/original", 0.25, -0.12, 0.25,
        ),
    }
    summary = summarize_universe_robustness(results)
    assert summary["decision_status"] == "universe_stronger_research_candidate"


def test_summarize_stronger_fails_on_bad_drawdown() -> None:
    """ICIR >= 0.20 but drawdown < -0.15 does not reach stronger research."""
    results = {
        "default_10_symbols": _make_summary(
            "blend:.../signal_blend/original", 0.25, -0.18, 0.25,
        ),
    }
    summary = summarize_universe_robustness(results)
    # strong ICIR alone does not reach stronger_research which requires
    # ICIR >= 0.20 AND drawdown >= -0.15
    assert summary["decision_status"] == "universe_research_candidate"


def test_summarize_includes_failed_gates_per_universe() -> None:
    results = {
        "default_10_symbols": _make_summary(
            "blend:.../signal_blend/original", 0.25, -0.12, 0.25,
        ),
    }
    summary = summarize_universe_robustness(results)
    row = summary["universe_rows"][0]
    assert "failed_gates" in row
    assert isinstance(row["failed_gates"], list)


def test_summarize_includes_trade_ready_in_output() -> None:
    results = {
        "default_10_symbols": _make_summary(
            "blend:.../signal_blend/original", 0.15, -0.20, 0.10,
        ),
    }
    summary = summarize_universe_robustness(results)
    assert "trade_ready" in summary
    assert summary["trade_ready"] is False


def test_summarize_includes_recommended_next_steps() -> None:
    results = {
        "default_10_symbols": _make_summary(
            "blend:.../signal_blend/original", 0.25, -0.12, 0.25,
        ),
    }
    summary = summarize_universe_robustness(results)
    assert "non_trade_ready_warning" in summary
    assert "recommended_next_step" in summary
    assert "data coverage" in summary["recommended_next_step"]
    assert "feature/factor" in summary["recommended_next_step"]


# ── Qlib frame parser: _parse_qlib_features_frame ────────────────────────


def test_parse_instrument_datetime_order() -> None:
    """MultiIndex (instrument, datetime) — the most common Qlib layout."""
    idx = pd.MultiIndex.from_tuples(
        [
            ("AAPL", pd.Timestamp("2021-01-04")),
            ("AAPL", pd.Timestamp("2021-01-05")),
            ("AAPL", pd.Timestamp("2021-01-06")),
            ("AAPL", pd.Timestamp("2021-01-07")),
            ("MSFT", pd.Timestamp("2021-01-04")),
            ("MSFT", pd.Timestamp("2021-01-05")),
            ("MSFT", pd.Timestamp("2021-01-06")),
            ("MSFT", pd.Timestamp("2021-01-07")),
        ],
        names=["instrument", "datetime"],
    )
    df = pd.DataFrame(
        {"$close": [150.0, 151.0, np.nan, 153.0, 300.0, 301.0, 302.0, np.nan]},
        index=idx,
    )
    result = _parse_qlib_features_frame(
        df, ["AAPL", "MSFT"],
        field="$close",
        req_start=pd.Timestamp("2021-01-01"),
        req_end=pd.Timestamp("2021-01-15"),
        pad=pd.Timedelta(days=14),
    )

    # AAPL: 3 valid obs, missing 2021-01-06
    assert result["AAPL"]["first_valid_date"] == "2021-01-04"
    assert result["AAPL"]["last_valid_date"] == "2021-01-07"
    assert result["AAPL"]["observations"] == 3
    assert result["AAPL"]["sufficient_coverage"] is True

    # MSFT: 3 valid obs, missing 2021-01-07
    assert result["MSFT"]["first_valid_date"] == "2021-01-04"
    assert result["MSFT"]["last_valid_date"] == "2021-01-06"
    assert result["MSFT"]["observations"] == 3
    assert result["MSFT"]["sufficient_coverage"] is True


def test_parse_datetime_instrument_order() -> None:
    """MultiIndex (datetime, instrument) — alternate Qlib layout."""
    idx = pd.MultiIndex.from_tuples(
        [
            (pd.Timestamp("2021-01-04"), "AAPL"),
            (pd.Timestamp("2021-01-04"), "MSFT"),
            (pd.Timestamp("2021-01-05"), "AAPL"),
            (pd.Timestamp("2021-01-05"), "MSFT"),
            (pd.Timestamp("2021-01-06"), "AAPL"),
            (pd.Timestamp("2021-01-06"), "MSFT"),
            (pd.Timestamp("2021-01-07"), "AAPL"),
            (pd.Timestamp("2021-01-07"), "MSFT"),
        ],
        names=["datetime", "instrument"],
    )
    df = pd.DataFrame(
        {"$close": [150.0, 300.0, 151.0, 301.0, np.nan, 302.0, 153.0, np.nan]},
        index=idx,
    )
    result = _parse_qlib_features_frame(
        df, ["AAPL", "MSFT"],
        field="$close",
        req_start=pd.Timestamp("2021-01-01"),
        req_end=pd.Timestamp("2021-01-15"),
        pad=pd.Timedelta(days=14),
    )

    assert result["AAPL"]["first_valid_date"] == "2021-01-04"
    assert result["AAPL"]["last_valid_date"] == "2021-01-07"
    assert result["AAPL"]["observations"] == 3
    assert result["AAPL"]["sufficient_coverage"] is True

    assert result["MSFT"]["first_valid_date"] == "2021-01-04"
    assert result["MSFT"]["last_valid_date"] == "2021-01-06"
    assert result["MSFT"]["observations"] == 3
    assert result["MSFT"]["sufficient_coverage"] is True


def test_parse_symbol_not_in_frame_is_zero() -> None:
    """A requested symbol with no rows in the frame gets zero coverage."""
    idx = pd.MultiIndex.from_tuples(
        [("AAPL", pd.Timestamp("2021-01-04"))],
        names=["instrument", "datetime"],
    )
    df = pd.DataFrame({"$close": [150.0]}, index=idx)
    result = _parse_qlib_features_frame(
        df, ["AAPL", "MISSING"],
        field="$close",
        req_start=pd.Timestamp("2021-01-01"),
        req_end=pd.Timestamp("2021-01-31"),
        pad=pd.Timedelta(days=14),
    )
    assert result["AAPL"]["observations"] == 1
    assert result["MISSING"]["observations"] == 0
    assert result["MISSING"]["first_valid_date"] is None
    assert result["MISSING"]["sufficient_coverage"] is False


def test_parse_all_nan_frame_returns_zero() -> None:
    """Every symbol having only NaN values → zero-observation coverage."""
    idx = pd.MultiIndex.from_tuples(
        [
            ("AAPL", pd.Timestamp("2021-01-04")),
            ("MSFT", pd.Timestamp("2021-01-04")),
        ],
        names=["instrument", "datetime"],
    )
    df = pd.DataFrame({"$close": [np.nan, np.nan]}, index=idx)
    result = _parse_qlib_features_frame(
        df, ["AAPL", "MSFT"],
        field="$close",
        req_start=pd.Timestamp("2021-01-01"),
        req_end=pd.Timestamp("2021-01-31"),
        pad=pd.Timedelta(days=14),
    )
    assert result["AAPL"]["observations"] == 0
    assert result["MSFT"]["observations"] == 0


def test_parse_empty_frame_returns_empty() -> None:
    result = _parse_qlib_features_frame(
        pd.DataFrame(),
        ["AAPL"],
        field="$close",
        req_start=pd.Timestamp("2021-01-01"),
        req_end=pd.Timestamp("2021-01-31"),
        pad=pd.Timedelta(days=14),
    )
    assert result == {}


def test_parse_missing_field_column_returns_empty() -> None:
    """When the requested field is not a column, fail closed."""
    idx = pd.MultiIndex.from_tuples(
        [("AAPL", pd.Timestamp("2021-01-04"))],
        names=["instrument", "datetime"],
    )
    df = pd.DataFrame({"$open": [150.0]}, index=idx)
    result = _parse_qlib_features_frame(
        df, ["AAPL"],
        field="$close",
        req_start=pd.Timestamp("2021-01-01"),
        req_end=pd.Timestamp("2021-01-31"),
        pad=pd.Timedelta(days=14),
    )
    assert result == {}


def test_parse_non_multiindex_returns_empty() -> None:
    """A flat DatetimeIndex cannot be parsed — fail closed."""
    dates = [pd.Timestamp("2021-01-04"), pd.Timestamp("2021-01-05")]
    df = pd.DataFrame({"$close": [150.0, 151.0]}, index=dates)
    result = _parse_qlib_features_frame(
        df, ["AAPL"],
        field="$close",
        req_start=pd.Timestamp("2021-01-01"),
        req_end=pd.Timestamp("2021-01-31"),
        pad=pd.Timedelta(days=14),
    )
    assert result == {}


# ── _identify_index_levels ───────────────────────────────────────────────


def test_identify_levels_by_name() -> None:
    idx = pd.MultiIndex.from_tuples(
        [("AAPL", pd.Timestamp("2021-01-04")), ("MSFT", pd.Timestamp("2021-01-04"))],
        names=["instrument", "datetime"],
    )
    instr_lvl, dt_lvl = _identify_index_levels(pd.DataFrame(index=idx))
    assert instr_lvl == 0
    assert dt_lvl == 1


def test_identify_levels_reversed_names() -> None:
    idx = pd.MultiIndex.from_tuples(
        [(pd.Timestamp("2021-01-04"), "AAPL"), (pd.Timestamp("2021-01-04"), "MSFT")],
        names=["datetime", "instrument"],
    )
    instr_lvl, dt_lvl = _identify_index_levels(pd.DataFrame(index=idx))
    assert instr_lvl == 1
    assert dt_lvl == 0


def test_identify_levels_fallback_by_type() -> None:
    """When level names are None, infer by value types."""
    tuples = [("AAPL", pd.Timestamp("2021-01-04")), ("MSFT", pd.Timestamp("2021-01-05"))]
    idx = pd.MultiIndex.from_tuples(tuples)
    # Qlib's MultiIndex.from_tuples without explicit names uses names=[0, 1]
    instr_lvl, dt_lvl = _identify_index_levels(pd.DataFrame(index=idx))
    assert instr_lvl == 0  # "AAPL"/"MSFT" are non-date strings
    assert dt_lvl == 1  # Timestamps


def test_identify_levels_flat_index_returns_none() -> None:
    df = pd.DataFrame({"a": [1]}, index=[pd.Timestamp("2021-01-04")])
    assert _identify_index_levels(df) == (None, None)
