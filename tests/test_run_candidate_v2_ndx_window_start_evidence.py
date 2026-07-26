"""Focused contract tests for the NDX window-start evidence runner."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.run_candidate_v2_ndx_window_start_evidence import (
    MIN_WINDOW_SYMBOLS,
    WINDOW_SNAPSHOT_MAP,
    _aggregate_ndx_windows,
    _build_comparison_vs_static_100,
    _evaluate_ndx_window,
    build_parser,
)
from src.research.ndx_window_start_universe import (
    NdxSnapshotDate,
    compute_membership_hash,
    intersect_with_provider,
)
from src.research.rolling_windows import RollingResearchWindow


# ══════════════════════════════════════════════════════════════════════════════
# Window-to-snapshot mapping
# ══════════════════════════════════════════════════════════════════════════════


def test_window_snapshot_map_has_four_entries() -> None:
    """There are exactly four OOS window labels mapped."""
    assert len(WINDOW_SNAPSHOT_MAP) == 4


def test_window_snapshot_map_covers_2024_2025() -> None:
    """Window labels span 2024H1 through 2025H2."""
    expected = {"2024H1", "2024H2", "2025H1", "2025H2"}
    assert set(WINDOW_SNAPSHOT_MAP.keys()) == expected


def test_window_snapshot_map_dates_are_valid() -> None:
    """Each mapped date is a valid ISO date string."""
    for label, date_str in WINDOW_SNAPSHOT_MAP.items():
        parts = date_str.split("-")
        assert len(parts) == 3
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        assert 2024 <= year <= 2025
        assert month in (1, 7)
        assert day in (1, 2)


def test_window_label_aligns_with_snapshot_date() -> None:
    """H1 maps to Jan snapshot, H2 maps to Jul snapshot."""
    assert WINDOW_SNAPSHOT_MAP["2024H1"] == "2024-01-02"
    assert WINDOW_SNAPSHOT_MAP["2024H2"] == "2024-07-01"
    assert WINDOW_SNAPSHOT_MAP["2025H1"] == "2025-01-02"
    assert WINDOW_SNAPSHOT_MAP["2025H2"] == "2025-07-01"


# ══════════════════════════════════════════════════════════════════════════════
# Intersect helper (re-tested here to ensure shared contract)
# ══════════════════════════════════════════════════════════════════════════════


def test_intersect_returns_expected_fields() -> None:
    """intersect_with_provider returns all required metadata fields."""
    from src.research.ndx_window_start_universe import NdxSnapshotDate

    entry = NdxSnapshotDate(
        date="2024-01-02",
        symbols=("AAPL", "MSFT", "GOOGL"),
        count=3,
        sha256_membership_hash=compute_membership_hash(["AAPL", "MSFT", "GOOGL"]),
    )
    result = intersect_with_provider(entry, {"AAPL", "MSFT", "GOOGL", "NVDA"})
    required = {"date", "requested", "retained", "missing", "n_requested",
                "n_retained", "n_missing", "coverage_ratio", "complete"}
    assert required.issubset(result.keys())


def test_evaluate_window_reloads_coverage_for_aligned_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The derived aligned start must affect both filtering and model fitting."""
    import scripts.run_candidate_v2_ndx_window_start_evidence as runner

    symbols = [f"S{i:03d}" for i in range(MIN_WINDOW_SYMBOLS)]
    initial = {
        symbol: {
            "first_valid_date": "2021-04-05" if i == 0 else "2021-01-04",
            "last_valid_date": "2024-07-05",
            "observations": 800,
            "covers_train_start": i != 0,
            "covers_test_end": True,
            "sufficient_coverage": i != 0,
        }
        for i, symbol in enumerate(symbols)
    }
    aligned = {
        symbol: {
            **record,
            "covers_train_start": True,
            "sufficient_coverage": True,
        }
        for symbol, record in initial.items()
    }
    coverage_calls: list[tuple[str, str]] = []

    def fake_load(
        _symbols: list[str], start: str, end: str
    ) -> dict[str, dict]:
        coverage_calls.append((start, end))
        return initial if len(coverage_calls) == 1 else aligned

    evaluated: dict[str, object] = {}

    def fake_evaluate(window, used_symbols, *_args):
        evaluated["window"] = window
        evaluated["symbols"] = used_symbols
        return {"window": window.to_dict(), "skipped": False}

    monkeypatch.setattr(runner, "load_symbol_date_coverage", fake_load)
    monkeypatch.setattr(runner, "_evaluate_window", fake_evaluate)

    window = RollingResearchWindow(
        label="2024H1",
        train_start="2021-01-01",
        train_end="2023-12-31",
        test_start="2024-01-01",
        test_end="2024-06-30",
    )
    entry = NdxSnapshotDate(
        date="2024-01-02",
        symbols=tuple(symbols),
        count=len(symbols),
        sha256_membership_hash=compute_membership_hash(symbols),
    )
    provider_report = intersect_with_provider(entry, set(symbols))

    result = _evaluate_ndx_window(
        window,
        symbols,
        "QQQ",
        {},
        [],
        "$close/Ref($close,10)-1",
        entry.date,
        entry,
        provider_report,
    )

    assert coverage_calls == [
        ("2021-01-01", "2024-06-30"),
        ("2021-04-05", "2024-06-30"),
    ]
    fitted_window = evaluated["window"]
    assert isinstance(fitted_window, RollingResearchWindow)
    assert fitted_window.train_start == "2021-04-05"
    assert evaluated["symbols"] == symbols
    assert result is not None
    assert result["coverage_meta"]["aligned_train_start"] == "2021-04-05"
    assert result["nominal_window"]["train_start"] == "2021-01-01"


# ══════════════════════════════════════════════════════════════════════════════
# Aggregate
# ══════════════════════════════════════════════════════════════════════════════


def _make_valid_window_payload(
    rel_excess: float = 0.05,
    sharpe: float = 1.2,
    drawdown: float = -0.08,
    n_periods: int = 15,
) -> dict:
    """Build a minimal valid window payload with coverage metadata."""
    return {
        "skipped": False,
        "window": {"label": "2024H1"},
        "candidate": "blend:ranker_momentum:...:ranker0.5_momentum0.5",
        "candidate_v2": {
            "variant_id": "top3_benchmark_trend_filter",
            "relative_excess_return": rel_excess,
            "max_drawdown": drawdown,
            "sharpe_ratio": sharpe,
            "total_return": 0.10,
            "benchmark_return": 0.05,
            "excess_return": 0.05,
            "annual_return": 0.20,
            "volatility": 0.18,
            "turnover": 0.15,
            "costs": 0.0003,
            "cost_bps": 20.0,
            "turnover_model": "cash_inclusive_one_way",
            "information_ratio": 0.60,
            "period_returns": [0.01] * n_periods,
            "benchmark_period_returns": [0.005] * n_periods,
            "portfolio_values": [1.0 + i * 0.01 for i in range(n_periods + 1)],
            "benchmark_values": [1.0 + i * 0.005 for i in range(n_periods + 1)],
            "n_periods": n_periods,
            "test_start": "2024-01-01",
            "test_end": "2024-06-30",
            "mean_gross_exposure": 0.75,
            "min_gross_exposure": 0.5,
            "max_gross_exposure": 1.0,
            "label": "research_only_risk_control_variant",
            "research_only": True,
            "trade_ready": False,
        },
        "score_diagnostics": {
            "ic_mean": 0.06,
            "ic_std": 0.10,
            "ic_ir": 0.35,
            "ic_pos_pct": 0.65,
            "ic_n_days": 60,
            "rank_ic_mean": 0.05,
            "rank_ic_std": 0.10,
            "rank_ic_ir": 0.30,
            "rank_ic_pos_pct": 0.60,
            "rank_ic_n_days": 60,
            "top_bottom_spread_mean": 0.02,
            "top_bottom_spread_std": 0.03,
            "top_bottom_spread_pos_pct": 0.70,
            "top_bottom_spread_n_days": 60,
        },
        "coverage_meta": {
            "ndx_snapshot_date": "2024-01-02",
            "n_official_requested": 100,
            "n_provider_retained": 100,
            "n_provider_missing": 0,
            "n_date_coverage_retained": 100,
            "n_date_coverage_dropped": 0,
            "n_retained": 100,
            "n_missing": 0,
            "coverage_ratio": 1.0,
            "membership_coverage_complete": True,
            "oos_membership_point_in_time": True,
            "full_daily_point_in_time": False,
            "historical_training_membership_selection_bias": True,
        },
    }


def test_aggregate_four_valid_windows_passes_gate() -> None:
    """Four valid positive-excess windows pass the frozen gate."""
    payloads = [_make_valid_window_payload() for _ in range(4)]
    agg = _aggregate_ndx_windows(payloads)
    assert agg["skipped"] is False
    assert agg["n_windows_evaluated"] == 4
    assert agg["candidate_v2"]["positive_excess_windows"] == 4
    assert agg["candidate_v2"]["passes_candidate_v2_gate"] is True
    assert agg["candidate_v2"]["failed_gates"] == []
    assert agg["coverage_summary"]["membership_coverage_complete"] is True


def test_aggregate_skipped_when_all_skipped() -> None:
    """All skipped payloads produce a skipped aggregate."""
    payloads = [
        {"skipped": True, "skip_reason": "empty data", "window": {"label": "2024H1"}},
        {"skipped": True, "skip_reason": "empty data", "window": {"label": "2024H2"}},
    ]
    agg = _aggregate_ndx_windows(payloads)
    assert agg["skipped"] is True


def test_aggregate_empty_payloads_skipped() -> None:
    """Empty payload list produces skipped."""
    agg = _aggregate_ndx_windows([])
    assert agg["skipped"] is True


def test_aggregate_coverage_summary_reflects_all_windows() -> None:
    """coverage_summary reflects snapshots loaded and completeness."""
    payloads = [_make_valid_window_payload() for _ in range(4)]
    agg = _aggregate_ndx_windows(payloads)
    cov = agg["coverage_summary"]
    assert cov["snapshots_loaded"] == 1  # all use the same mock date
    assert cov["membership_coverage_complete"] is True


def test_aggregate_incomplete_coverage_reporting() -> None:
    """When one window has incomplete coverage, summary reflects it."""
    payloads = [_make_valid_window_payload() for _ in range(3)]
    incomplete = _make_valid_window_payload()
    incomplete["coverage_meta"]["membership_coverage_complete"] = False
    incomplete["coverage_meta"]["n_date_coverage_retained"] = 95
    incomplete["coverage_meta"]["n_date_coverage_dropped"] = 5
    incomplete["coverage_meta"]["n_retained"] = 95
    incomplete["coverage_meta"]["n_missing"] = 5
    incomplete["coverage_meta"]["coverage_ratio"] = 0.95
    payloads.append(incomplete)
    agg = _aggregate_ndx_windows(payloads)
    assert agg["coverage_summary"]["membership_coverage_complete"] is False


def test_aggregate_reports_failed_frozen_gates() -> None:
    """Weak windows fail explicitly without lowering the frozen thresholds."""
    payloads = [
        _make_valid_window_payload(rel_excess=-0.05, drawdown=-0.20)
        for _ in range(4)
    ]
    for payload in payloads:
        payload["candidate_v2"]["period_returns"] = [-0.01] * 15
        payload["candidate_v2"]["benchmark_period_returns"] = [0.005] * 15
    agg = _aggregate_ndx_windows(payloads)
    candidate = agg["candidate_v2"]
    assert candidate["passes_candidate_v2_gate"] is False
    assert candidate["gate_thresholds"]["min_compounded_relative_excess"] == 0.30
    assert candidate["gate_thresholds"]["max_drawdown"] == -0.15
    assert {
        "positive_excess_windows",
        "compounded_relative_excess",
        "worst_drawdown",
    }.issubset(candidate["failed_gates"])


# ══════════════════════════════════════════════════════════════════════════════
# Comparison vs static-100
# ══════════════════════════════════════════════════════════════════════════════


def test_comparison_includes_all_metrics() -> None:
    """Comparison dict contains all required metrics."""
    agg = {
        "candidate_v2": {
            "compounded_relative_excess_return": 0.50,
            "mean_sharpe": 0.80,
            "worst_drawdown": -0.12,
        },
        "score_diagnostics": {
            "mean_ic_ir": 0.30,
            "mean_rank_ic_ir": 0.25,
        },
    }
    comp = _build_comparison_vs_static_100(agg)
    assert "static_100_values" in comp
    assert "ndx_window_start_values" in comp
    assert "absolute_deltas" in comp
    assert comp["static_100_values"]["compounded_relative_excess_return"] == 1.7668
    for key in ("compounded_relative_excess_return", "mean_sharpe", "worst_drawdown",
                "mean_ic_ir", "mean_rank_ic_ir"):
        assert key in comp["static_100_values"]
        assert key in comp["ndx_window_start_values"]


# ══════════════════════════════════════════════════════════════════════════════
# CLI contract
# ══════════════════════════════════════════════════════════════════════════════


def test_build_parser_accepts_root_and_data_root() -> None:
    """CLI parser accepts --root and --data-root."""
    parser = build_parser()
    args = parser.parse_args(["--root", "/tmp/project", "--data-root", "/mnt/data"])
    assert str(args.root) == str(Path("/tmp/project"))
    assert str(args.data_root) == str(Path("/mnt/data"))


def test_build_parser_snapshot_path_default() -> None:
    """--snapshot-path defaults to configs/research_universes path."""
    parser = build_parser()
    args = parser.parse_args(["--root", "/tmp"])
    assert "ndx_window_start_membership" in str(args.snapshot_path)


def test_build_parser_accepts_snapshot_path() -> None:
    """CLI accepts custom --snapshot-path."""
    parser = build_parser()
    custom = "/data/custom_snapshot.json"
    args = parser.parse_args(["--root", "/tmp", "--snapshot-path", custom])
    assert args.snapshot_path == Path(custom)


# ══════════════════════════════════════════════════════════════════════════════
# Research-only / trade-ready contract
# ══════════════════════════════════════════════════════════════════════════════


def test_window_payload_has_coverage_meta() -> None:
    """Every window payload includes coverage metadata."""
    payload = _make_valid_window_payload()
    assert "coverage_meta" in payload
    cm = payload["coverage_meta"]
    assert cm["oos_membership_point_in_time"] is True
    assert cm["full_daily_point_in_time"] is False
    assert cm["historical_training_membership_selection_bias"] is True
    assert "ndx_snapshot_date" in cm


def test_aggregate_reports_pit_flags() -> None:
    """Aggregate output includes PIT-related metadata."""
    payloads = [_make_valid_window_payload() for _ in range(4)]
    agg = _aggregate_ndx_windows(payloads)
    cov = agg["coverage_summary"]
    assert "membership_coverage_complete" in cov
    assert "snapshots_loaded" in cov
