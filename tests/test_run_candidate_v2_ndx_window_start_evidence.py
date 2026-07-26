"""Focused contract tests for the NDX window-start evidence runner."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.build_ndx_window_start_provider import (
    _alias_end_date,
    _assert_usable_from_first_membership,
    _clean_bars,
    _required_symbols,
    _validate_isolated_roots,
    build_parser as build_provider_parser,
)
from scripts.run_candidate_v2_ndx_window_start_evidence import (
    MIN_WINDOW_SYMBOLS,
    WINDOW_SNAPSHOT_MAP,
    _aggregate_ndx_windows,
    _build_comparison_vs_static_100,
    _evaluate_ndx_window,
    _filter_training_union_by_membership_coverage,
    _load_provider_lineage,
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


def test_aligned_start_is_50th_earliest_not_latest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One late OOS constituent must not push the fitted history to 2023."""
    import scripts.run_candidate_v2_ndx_window_start_evidence as runner

    early_symbols = [f"E{i:03d}" for i in range(50)]
    late_symbol = "LATE001"
    all_symbols = early_symbols + [late_symbol]
    from src.research.ndx_window_start_universe import (
        NdxWindowStartSnapshot,
        SOURCE_URL_TEMPLATE,
    )

    snapshot_dates: list[NdxSnapshotDate] = []
    for date_str, symbols_for_date in [
        ("2021-01-04", all_symbols),
        ("2021-07-01", all_symbols),
        ("2022-01-03", all_symbols),
        ("2022-07-01", all_symbols),
        ("2023-01-03", all_symbols),
        ("2023-07-03", all_symbols),
    ]:
        symbols_tuple = tuple(sorted(symbols_for_date))
        snapshot_dates.append(
            NdxSnapshotDate(
                date=date_str,
                symbols=symbols_tuple,
                count=len(symbols_tuple),
                sha256_membership_hash=compute_membership_hash(list(symbols_tuple)),
            )
        )

    # Also include the OOS snapshot date 2024-01-02
    snapshot_dates.append(
        NdxSnapshotDate(
            date="2024-01-02",
            symbols=tuple(sorted(all_symbols)),
            count=len(all_symbols),
            sha256_membership_hash=compute_membership_hash(all_symbols),
        )
    )

    snapshot = NdxWindowStartSnapshot(
        source_url_template=SOURCE_URL_TEMPLATE,
        snapshot_dates=tuple(snapshot_dates),
        raw={},
    )

    coverage_calls: list[tuple[str, str]] = []

    def fake_load(symbols, start, end):
        coverage_calls.append((start, end))
        is_test = start == "2024-01-01"
        is_aligned_train = start == "2021-04-05"
        result = {}
        for symbol in symbols:
            late = symbol == late_symbol
            result[symbol] = {
                "first_valid_date": "2023-09-14" if late else "2021-04-05",
                "last_valid_date": end,
                "observations": 500,
                "covers_train_start": is_test or not late or not is_aligned_train,
                "covers_test_end": True,
                "sufficient_coverage": is_test or not late or not is_aligned_train,
            }
        return result

    evaluated: dict[str, object] = {}

    def fake_evaluate(window, test_symbols, *_args, **kwargs):
        evaluated["window"] = window
        evaluated["test_symbols"] = test_symbols
        evaluated["train_symbols"] = kwargs["train_symbols"]
        evaluated["snapshot"] = kwargs["asof_membership_snapshot"]
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
    result = _evaluate_ndx_window(
        window,
        "QQQ",
        {},
        [],
        "$close/Ref($close,10)-1",
        snapshot,
        set(all_symbols),
    )

    assert result is not None
    assert result["coverage_meta"]["aligned_train_start"] == "2021-04-05"
    assert isinstance(evaluated["window"], RollingResearchWindow)
    assert evaluated["window"].train_start == "2021-04-05"
    assert len(evaluated["train_symbols"]) == 50
    assert late_symbol not in evaluated["train_symbols"]
    assert set(evaluated["test_symbols"]) == set(all_symbols)
    assert evaluated["snapshot"] is snapshot
    assert coverage_calls == [
        ("2024-01-01", "2024-06-30"),
        ("2021-01-01", "2023-12-31"),
        ("2021-04-05", "2023-12-31"),
    ]


def test_training_coverage_ends_at_membership_exit() -> None:
    """A former constituent needs bars only while its snapshot is active."""
    from src.research.ndx_window_start_universe import (
        NdxWindowStartSnapshot,
        SOURCE_URL_TEMPLATE,
    )

    entries = []
    for date_str, symbols in [
        ("2021-01-04", ["FORMER", "STAYER"]),
        ("2021-07-01", ["FORMER", "STAYER"]),
        ("2022-01-03", ["STAYER"]),
        ("2022-07-01", ["STAYER"]),
    ]:
        entries.append(
            NdxSnapshotDate(
                date=date_str,
                symbols=tuple(sorted(symbols)),
                count=len(symbols),
                sha256_membership_hash=compute_membership_hash(symbols),
            )
        )
    snapshot = NdxWindowStartSnapshot(
        source_url_template=SOURCE_URL_TEMPLATE,
        snapshot_dates=tuple(entries),
        raw={},
    )
    result = _filter_training_union_by_membership_coverage(
        ["FORMER", "STAYER"],
        snapshot=snapshot,
        aligned_train_start="2021-04-05",
        train_end="2022-12-31",
        date_coverage_data={
            "FORMER": {
                "first_valid_date": "2021-04-05",
                "last_valid_date": "2021-12-31",
                "observations": 190,
            },
            "STAYER": {
                "first_valid_date": "2021-04-05",
                "last_valid_date": "2022-12-30",
                "observations": 440,
            },
        },
        min_symbols=2,
    )
    assert result["skipped"] is False
    assert result["retained_symbols"] == ["FORMER", "STAYER"]
    assert result["required_bounds"]["FORMER"]["required_end"] == "2022-01-02"
    assert result["required_bounds"]["STAYER"]["required_end"] == "2022-12-31"


def test_training_coverage_drops_symbol_missing_during_membership() -> None:
    """Early data loss still fails closed even if a ticker later leaves."""
    from src.research.ndx_window_start_universe import (
        NdxWindowStartSnapshot,
        SOURCE_URL_TEMPLATE,
    )

    symbols = ["FORMER"]
    entry = NdxSnapshotDate(
        date="2021-01-04",
        symbols=tuple(symbols),
        count=1,
        sha256_membership_hash=compute_membership_hash(symbols),
    )
    snapshot = NdxWindowStartSnapshot(
        source_url_template=SOURCE_URL_TEMPLATE,
        snapshot_dates=(entry,),
        raw={},
    )
    result = _filter_training_union_by_membership_coverage(
        symbols,
        snapshot=snapshot,
        aligned_train_start="2021-04-05",
        train_end="2021-12-31",
        date_coverage_data={
            "FORMER": {
                "first_valid_date": "2021-04-05",
                "last_valid_date": "2021-08-01",
                "observations": 80,
            }
        },
        min_symbols=1,
    )
    assert result["skipped"] is True
    assert result["retained_symbols"] == []
    assert "history ends" in result["dropped_reasons"]["FORMER"]


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
            "oos_snapshot_date": "2024-01-02",
            "n_oos_requested": 100,
            "n_oos_test_retained": 100,
            "n_training_snapshots": 6,
            "training_union_requested": 120,
            "training_union_provider_retained": 120,
            "training_date_retained": 100,
            "aligned_train_start": "2021-07-01",
            "training_membership_asof_semiannual": True,
            "training_uses_future_oos_snapshot": False,
            "full_daily_point_in_time": False,
            "provider_coverage_incomplete": False,
            "oos_membership_point_in_time": True,
            "research_only": True,
            "promotion_eligible": False,
            "trade_ready": False,
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
    incomplete["coverage_meta"]["provider_coverage_incomplete"] = True
    incomplete["coverage_meta"]["n_oos_test_retained"] = 95
    incomplete["coverage_meta"]["training_date_retained"] = 95
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


def test_build_parser_accepts_provider_lineage_path() -> None:
    """CLI accepts a lineage file that is bound to the provider identity."""
    parser = build_parser()
    path = "/data/provider_backfill_lineage.json"
    args = parser.parse_args(["--provider-lineage-path", path])
    assert args.provider_lineage_path == Path(path)


def test_provider_lineage_identity_is_verified(tmp_path: Path) -> None:
    """Evidence cannot attach lineage from a different provider."""
    path = tmp_path / "lineage.json"
    path.write_text(
        json.dumps(
            {
                "output_provider_identity_sha256": "provider-a",
                "policies": {
                    "operational_provider_mutated": False,
                    "unavailable_symbols_fail_closed": True,
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="identity mismatch"):
        _load_provider_lineage(path, expected_provider_identity="provider-b")


def test_provider_lineage_requires_fail_closed_policy(tmp_path: Path) -> None:
    """A lineage record cannot hide missing-symbol fallbacks."""
    path = tmp_path / "lineage.json"
    path.write_text(
        json.dumps(
            {
                "output_provider_identity_sha256": "provider-a",
                "policies": {
                    "operational_provider_mutated": False,
                    "unavailable_symbols_fail_closed": False,
                },
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="fail closed"):
        _load_provider_lineage(path, expected_provider_identity="provider-a")


def test_provider_builder_requires_distinct_output_root() -> None:
    """The backfill builder must not target the operational data root."""
    root = Path("/tmp/alpha-engine")
    with pytest.raises(ValueError, match="must differ"):
        _validate_isolated_roots(root, root)


def test_provider_builder_cli_requires_output_root() -> None:
    """No default destination can accidentally overwrite operational data."""
    parser = build_provider_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    args = parser.parse_args(["--output-data-root", "/tmp/ndx-provider"])
    assert args.output_data_root == Path("/tmp/ndx-provider")
    assert args.overwrite is False


def test_provider_builder_required_symbols_are_snapshot_union() -> None:
    """Backfill scope is derived from committed membership, not a watchlist."""
    from src.research.ndx_window_start_universe import load_snapshot

    snapshot = load_snapshot()
    required = _required_symbols(snapshot)
    assert {"AAPL", "FB", "META", "ANSS"}.issubset(required)
    assert "QQQ" not in required


def test_fb_alias_stops_before_first_meta_snapshot() -> None:
    """The recycled FB ticker is represented only through the META rename."""
    from src.research.ndx_window_start_universe import load_snapshot

    snapshot = load_snapshot()
    end = _alias_end_date(
        snapshot,
        target_symbol="FB",
        source_symbol="META",
        requested_end="2026-06-24",
    )
    assert end == "2022-06-30"


def test_clean_bars_drops_batch_union_nan_rows() -> None:
    """Pre-IPO NaN rows from batch-shaped downloads cannot fake coverage."""
    frame = pd.DataFrame(
        {
            "date": ["2021-04-05", "2021-10-28"],
            "open": [None, 47.0],
            "high": [None, 49.0],
            "low": [None, 46.0],
            "close": [None, 48.0],
            "volume": [None, 100.0],
        }
    )
    clean = _clean_bars(frame, start="2021-04-05", end="2021-12-31")
    assert clean["date"].dt.strftime("%Y-%m-%d").tolist() == ["2021-10-28"]
    assert clean["amount"].tolist() == [4800.0]
    assert clean["factor"].tolist() == [1.0]


def test_history_after_first_membership_fails_closed() -> None:
    """A ticker cannot be retained if its bars start after it was required."""
    from src.research.ndx_window_start_universe import load_snapshot

    frame = pd.DataFrame({"date": pd.to_datetime(["2022-01-03"])})
    with pytest.raises(ValueError, match="starts after"):
        _assert_usable_from_first_membership(
            frame,
            snapshot=load_snapshot(),
            symbol="FB",
            requested_start="2021-04-05",
        )


# ══════════════════════════════════════════════════════════════════════════════
# Research-only / trade-ready contract
# ══════════════════════════════════════════════════════════════════════════════


def test_window_payload_has_coverage_meta() -> None:
    """Every window payload includes coverage metadata with as-of flags."""
    payload = _make_valid_window_payload()
    assert "coverage_meta" in payload
    cm = payload["coverage_meta"]
    assert cm["training_membership_asof_semiannual"] is True
    assert cm["training_uses_future_oos_snapshot"] is False
    assert cm["full_daily_point_in_time"] is False
    assert cm["oos_membership_point_in_time"] is True
    assert "oos_snapshot_date" in cm
    assert "aligned_train_start" in cm


def test_aggregate_reports_pit_flags() -> None:
    """Aggregate output includes PIT-related metadata."""
    payloads = [_make_valid_window_payload() for _ in range(4)]
    agg = _aggregate_ndx_windows(payloads)
    cov = agg["coverage_summary"]
    assert "membership_coverage_complete" in cov
    assert "snapshots_loaded" in cov
    assert cov["training_membership_asof_semiannual"] is True
    assert cov["training_uses_future_oos_snapshot"] is False
    assert cov["full_daily_point_in_time"] is False
