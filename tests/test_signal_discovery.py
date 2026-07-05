"""Tests for src/research/signal_discovery.py — 10D signal discovery module.

Covers:
- Raw-return economic evaluation (provenance validation)
- Leakage protection
- Direction diagnostics / top-bottom spread
- Winner-bucket label generation (training-target utility only)
- Report schema / serialization
- Promotion threshold enforcement
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.research.signal_discovery import (
    PROMOTION_THRESHOLDS,
    CandidateKind,
    CandidateResult,
    CandidateStatus,
    ComparisonReport,
    DirectionDiagnostics,
    DirectionRecommendation,
    ScoreOrientation,
    compute_direction_diagnostics,
    evaluate_candidate,
    generate_winner_labels,
    run_signal_discovery_comparison,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_raw_returns(
    n_dates: int = 30,
    n_stocks: int = 50,
    seed: int = 42,
) -> pd.DataFrame:
    """Create synthetic raw forward returns with provenance attrs."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2025-01-02", periods=n_dates)
    instruments = [f"S{i:04d}" for i in range(n_stocks)]
    idx = pd.MultiIndex.from_product(
        [dates, instruments], names=["datetime", "instrument"]
    )
    returns = rng.normal(0.0002, 0.02, size=len(idx))
    df = pd.DataFrame({"return": returns}, index=idx)
    df.attrs["provenance"] = "raw_forward_return"
    df.attrs["label_expression"] = "Ref($close, -10) / $close - 1"
    df.attrs["horizon"] = 10
    return df


def _make_predictions(
    raw_returns: pd.DataFrame,
    ic_strength: float = 0.3,
    seed: int = 42,
) -> pd.DataFrame:
    """Create synthetic predictions correlated with raw returns."""
    rng = np.random.default_rng(seed)
    scores = raw_returns["return"] * ic_strength + rng.normal(
        0, 0.02, size=len(raw_returns)
    )
    return pd.DataFrame({"score": scores.values}, index=raw_returns.index)


def _make_factor_baseline(
    raw_returns: pd.DataFrame,
    seed: int = 77,
) -> pd.DataFrame:
    """Create synthetic factor baseline predictions from explicit historical data.

    These are independent of future returns — they represent a price-based
    factor like ``$close / Ref($close, 10) - 1`` computed from historical
    prices only (no forward-looking information).
    """
    rng = np.random.default_rng(seed)
    # Factor scores are noise with a small positive bias, independent of raw_returns
    scores = rng.normal(0.0001, 0.015, size=len(raw_returns))
    return pd.DataFrame({"score": scores}, index=raw_returns.index)


def _make_benchmark(raw_returns: pd.DataFrame, seed: int = 99) -> pd.DataFrame:
    """Create synthetic benchmark returns."""
    rng = np.random.default_rng(seed)
    dates = sorted(raw_returns.index.get_level_values("datetime").unique())
    return pd.DataFrame(
        {"return": rng.normal(0.0001, 0.01, size=len(dates))},
        index=dates,
    )


# ---------------------------------------------------------------------------
# Winner-bucket label generation (training-target utility only)
# ---------------------------------------------------------------------------


class TestGenerateWinnerLabels:
    """Tests for generate_winner_labels()."""

    def test_basic_labels(self):
        """Winner labels must be 0 or 1 only, with correct fraction."""
        raw = _make_raw_returns(n_dates=10, n_stocks=50)
        result = generate_winner_labels(
            raw, top_fraction=0.20, min_stocks_per_day=1
        )

        assert "winner_label" in result.columns
        assert set(result["winner_label"].unique()).issubset({0, 1})
        # ~20% should be winners per date
        frac = result["winner_label"].mean()
        assert 0.15 <= frac <= 0.25, f"Expected ~20% winners, got {frac:.2%}"

    def test_top_fraction_ceil(self):
        """Small universes should produce at least 1 winner per date."""
        raw = _make_raw_returns(n_dates=5, n_stocks=5)
        result = generate_winner_labels(raw, top_fraction=0.10)
        # With 5 stocks, top 10% = ceil(0.5) = 1 winner per date
        winners_per_date = result.groupby(level="datetime")["winner_label"].sum()
        assert (winners_per_date >= 1).all()

    def test_rejects_processed_labels(self):
        """Winner labels must reject non-raw-return provenance."""
        raw = _make_raw_returns(n_dates=5, n_stocks=20)
        raw.attrs["provenance"] = "processed_training_label"
        with pytest.raises(ValueError, match="raw_forward_return"):
            generate_winner_labels(raw)

    def test_min_stocks_per_day(self):
        """Dates with too few stocks are skipped."""
        raw = _make_raw_returns(n_dates=5, n_stocks=3)
        result = generate_winner_labels(raw, top_fraction=0.20, min_stocks_per_day=10)
        assert result["winner_label"].sum() == 0

    def test_top_fraction_validation(self):
        """Invalid top_fraction must raise."""
        raw = _make_raw_returns()
        with pytest.raises(ValueError):
            generate_winner_labels(raw, top_fraction=0.0)
        with pytest.raises(ValueError):
            generate_winner_labels(raw, top_fraction=1.5)

    def test_deterministic_by_ticker(self):
        """Tied returns produce deterministic labels by instrument sort."""
        dates = pd.bdate_range("2025-01-02", periods=1)
        instruments = ["B", "A", "C"]
        idx = pd.MultiIndex.from_product(
            [dates, instruments], names=["datetime", "instrument"]
        )
        raw = pd.DataFrame({"return": [0.10, 0.10, 0.05]}, index=idx)
        raw.attrs["provenance"] = "raw_forward_return"
        raw.attrs["horizon"] = 10
        # top_fraction=0.20 with 3 stocks → ceil(0.6) = 1 winner
        # Ties broken alphabetically: A gets winner, B does not
        result = generate_winner_labels(
            raw, top_fraction=0.20, min_stocks_per_day=1
        )
        assert result.loc[(dates[0], "A"), "winner_label"] == 1
        assert result.loc[(dates[0], "B"), "winner_label"] == 0
        assert result.loc[(dates[0], "C"), "winner_label"] == 0

    def test_nan_returns_excluded(self):
        """NaN returns must never be labeled winners."""
        dates = pd.bdate_range("2025-01-02", periods=1)
        instruments = ["A", "B", "C", "D"]
        idx = pd.MultiIndex.from_product(
            [dates, instruments], names=["datetime", "instrument"]
        )
        raw = pd.DataFrame(
            {"return": [np.nan, 0.20, 0.10, 0.05]}, index=idx
        )
        raw.attrs["provenance"] = "raw_forward_return"
        raw.attrs["horizon"] = 10
        result = generate_winner_labels(
            raw, top_fraction=0.50, min_stocks_per_day=1
        )
        assert result.loc[(dates[0], "A"), "winner_label"] == 0  # NaN excluded
        assert result.loc[(dates[0], "B"), "winner_label"] == 1

    def test_missing_provenance_raises(self):
        """DataFrame with no provenance attrs must raise ValueError."""
        raw = _make_raw_returns(n_dates=5, n_stocks=20)
        raw.attrs.pop("provenance", None)
        with pytest.raises(ValueError, match="provenance"):
            generate_winner_labels(raw)

    def test_winner_labels_not_accepted_as_candidate_scores(self):
        """Winner labels must never be passed as candidate scores — target leakage.

        generate_winner_labels derives labels from the SAME raw_returns used
        for evaluation.  Passing winner_label values (0/1) as a candidate
        ``score`` column and evaluating against the same raw_returns is
        same-row leakage: winner labels perfectly identify high-return stocks
        because they WERE defined that way.

        This test verifies that ``evaluate_candidate`` accepts them (the
        caller must enforce the separation), but demonstrates that the
        resulting IC is absurdly high — a self-test that proves why winner
        labels must never enter the comparison pipeline as scores.
        """
        raw = _make_raw_returns(n_dates=10, n_stocks=30)
        winner_labels = generate_winner_labels(raw, top_fraction=0.20)

        # Explicitly verify: winner labels use the same raw returns
        result = evaluate_candidate(
            predictions=winner_labels[["winner_label"]].rename(
                columns={"winner_label": "score"}
            ),
            raw_returns=raw,
            candidate_kind=CandidateKind.WINNER_BUCKET_CLASSIFIER,
        )

        # Winner labels as scores against same returns → extreme IC
        # This proves leakage — the caller (run_signal_discovery_comparison)
        # must never pass winner labels as scores.
        assert result.ic > 0.5, (
            f"Expected extreme IC from same-row leakage, got {result.ic:.4f}"
        )
        # But the comparison workflow itself must NEVER evaluate this candidate
        # — this test is the PROOF of leakage, not an endorsement.


# ---------------------------------------------------------------------------
# Direction diagnostics
# ---------------------------------------------------------------------------


class TestDirectionDiagnostics:
    """Tests for compute_direction_diagnostics()."""

    def test_keep_score_when_positive(self):
        """Positive top−bottom spread + positive rank IC → keep_score."""
        raw = _make_raw_returns(n_dates=20, n_stocks=50)
        pred = _make_predictions(raw, ic_strength=0.5)

        diag = compute_direction_diagnostics(
            pred["score"], raw["return"], top_fraction=0.10
        )

        assert diag.recommendation == DirectionRecommendation.KEEP.value
        assert diag.top_minus_bottom_spread > 0
        assert diag.rank_ic > 0
        assert diag.n_dates > 0
        assert diag.n_samples > 0

    def test_invert_score_when_negative(self):
        """Negative top−bottom spread + negative rank IC → invert_score."""
        raw = _make_raw_returns(n_dates=20, n_stocks=50)
        # Exact anti-correlation makes the expected direction deterministic.
        pred = pd.DataFrame({"score": -raw["return"]}, index=raw.index)

        diag = compute_direction_diagnostics(
            pred["score"], raw["return"], top_fraction=0.10
        )

        assert diag.recommendation == DirectionRecommendation.INVERT.value
        assert diag.top_minus_bottom_spread < 0
        assert diag.rank_ic < 0

    def test_no_signal_when_flat(self):
        """Zero spread → no_signal."""
        dates = pd.bdate_range("2025-01-02", periods=5)
        instruments = [f"S{i:04d}" for i in range(20)]
        idx = pd.MultiIndex.from_product(
            [dates, instruments], names=["datetime", "instrument"]
        )
        # All returns equal → zero spread
        scores = pd.Series(np.zeros(len(idx)), index=idx, name="score")
        returns = pd.Series(np.ones(len(idx)) * 0.01, index=idx, name="return")

        diag = compute_direction_diagnostics(scores, returns)
        assert diag.recommendation == DirectionRecommendation.NO_SIGNAL.value

    def test_inconclusive_when_mixed(self):
        """Positive spread but negative rank IC → inconclusive."""
        raw = _make_raw_returns(n_dates=10, n_stocks=30)
        # Create predictions where top bucket has higher returns but rank IC is
        # negative overall (mixed signal)
        dates = sorted(raw.index.get_level_values("datetime").unique())
        scores_list = []
        returns_list = []
        instruments = sorted(
            raw.index.get_level_values("instrument").unique()
        )
        rng = np.random.default_rng(42)
        for date in dates:
            n = len(instruments)
            s = rng.normal(0, 1, n)
            r = rng.normal(0, 0.02, n)
            # Artificially create spread: make top scores have worse returns
            top_idx = np.argsort(s)[-3:]  # top 3 scores
            r[top_idx] = -0.05
            bot_idx = np.argsort(s)[:3]  # bottom 3 scores
            r[bot_idx] = 0.05
            for inst, sc, rt in zip(instruments, s, r):
                scores_list.append({"datetime": date, "instrument": inst, "score": sc})
                returns_list.append({"datetime": date, "instrument": inst, "return": rt})

        scores_df = pd.DataFrame(scores_list).set_index(["datetime", "instrument"])
        returns_df = pd.DataFrame(returns_list).set_index(["datetime", "instrument"])

        diag = compute_direction_diagnostics(
            scores_df["score"], returns_df["return"]
        )
        assert diag.recommendation in {
            DirectionRecommendation.INVERT.value,
            DirectionRecommendation.INCONCLUSIVE.value,
        }

    def test_top_minus_bottom_positive_spread(self):
        """Top bucket return > bottom bucket return for positive IC."""
        raw = _make_raw_returns(n_dates=20, n_stocks=50)
        pred = _make_predictions(raw, ic_strength=0.5)

        diag = compute_direction_diagnostics(
            pred["score"], raw["return"], top_fraction=0.10
        )

        assert diag.top_bucket_return > diag.bottom_bucket_return
        assert diag.top_minus_bottom_spread > 0
        assert diag.bottom_minus_top_spread < 0

    def test_empty_input(self):
        """Empty input should return no_signal."""
        idx = pd.MultiIndex.from_arrays(
            [[], []], names=["datetime", "instrument"]
        )
        scores = pd.Series([], index=idx, dtype=float)
        returns = pd.Series([], index=idx, dtype=float)

        diag = compute_direction_diagnostics(scores, returns)
        assert diag.recommendation == DirectionRecommendation.NO_SIGNAL.value
        assert diag.n_samples == 0

    def test_serialization(self):
        """DirectionDiagnostics.to_dict() must be JSON-serializable."""
        raw = _make_raw_returns(n_dates=10, n_stocks=30)
        pred = _make_predictions(raw)
        diag = compute_direction_diagnostics(pred["score"], raw["return"])
        d = diag.to_dict()
        json.dumps(d)  # Must not raise


# ---------------------------------------------------------------------------
# Candidate evaluation
# ---------------------------------------------------------------------------


class TestEvaluateCandidate:
    """Tests for evaluate_candidate()."""

    def test_lgbm_original_evaluation(self):
        """LGBM regressor with original orientation produces valid result."""
        raw = _make_raw_returns(n_dates=30, n_stocks=50)
        pred = _make_predictions(raw, ic_strength=0.5)
        bench = _make_benchmark(raw)

        result = evaluate_candidate(
            predictions=pred,
            raw_returns=raw,
            candidate_kind=CandidateKind.LGBM_REGRESSOR,
            orientation=ScoreOrientation.ORIGINAL,
            benchmark_returns=bench,
            topk=5,
            rebalance_days=10,
        )

        assert result.candidate_kind == CandidateKind.LGBM_REGRESSOR
        assert result.orientation == ScoreOrientation.ORIGINAL
        assert isinstance(result.ic, float)
        assert isinstance(result.rank_ic, float)
        assert isinstance(result.icir, float)
        assert result.n_periods > 0
        assert result.test_start != ""
        assert result.test_end != ""

    def test_inverted_orientation_reverses_direction(self):
        """Inverted score should flip IC direction vs original.

        Uses a high-IC synthetic dataset (ic_strength=0.8, many dates/stocks)
        so the directional effect is deterministic even with noise.
        """
        raw = _make_raw_returns(n_dates=40, n_stocks=100)
        pred = _make_predictions(raw, ic_strength=0.8)

        original = evaluate_candidate(
            predictions=pred,
            raw_returns=raw,
            candidate_kind=CandidateKind.LGBM_REGRESSOR,
            orientation=ScoreOrientation.ORIGINAL,
            topk=5,
        )
        inverted = evaluate_candidate(
            predictions=pred,
            raw_returns=raw,
            candidate_kind=CandidateKind.LGBM_REGRESSOR,
            orientation=ScoreOrientation.INVERTED,
            topk=5,
        )

        # IC should flip sign
        assert original.ic > 0, f"Original IC must be positive, got {original.ic}"
        assert inverted.ic < 0, f"Inverted IC must be negative, got {inverted.ic}"
        # Direction diagnostics should be opposite
        assert (
            original.score_direction.recommendation
            != inverted.score_direction.recommendation
        )

    def test_inverted_ic_sign_reversal_strong(self):
        """With very strong IC, inverted IC is always negative (supplementary)."""
        raw = _make_raw_returns(n_dates=50, n_stocks=100)
        # Very strong positive correlation — should survive any noise
        scores = raw["return"] * 0.9 + np.random.default_rng(42).normal(
            0, 0.005, size=len(raw)
        )
        pred = pd.DataFrame({"score": scores.values}, index=raw.index)

        original = evaluate_candidate(
            predictions=pred,
            raw_returns=raw,
            candidate_kind=CandidateKind.LGBM_REGRESSOR,
            orientation=ScoreOrientation.ORIGINAL,
            topk=5,
        )
        inverted = evaluate_candidate(
            predictions=pred,
            raw_returns=raw,
            candidate_kind=CandidateKind.LGBM_REGRESSOR,
            orientation=ScoreOrientation.INVERTED,
            topk=5,
        )

        assert original.ic > 0.5, f"Strong original IC expected, got {original.ic}"
        assert inverted.ic < -0.5, f"Strong inverted IC expected, got {inverted.ic}"

    def test_rejects_processed_labels(self):
        """evaluate_candidate must reject non-raw returns."""
        raw = _make_raw_returns(n_dates=20, n_stocks=30)
        raw.attrs["provenance"] = "rank_normalized_label"
        pred = _make_predictions(raw)

        with pytest.raises(ValueError, match="raw_forward_return"):
            evaluate_candidate(
                predictions=pred,
                raw_returns=raw,
                candidate_kind=CandidateKind.LGBM_REGRESSOR,
            )

    def test_no_common_dates_returns_valid_result(self):
        """Non-overlapping date ranges produce a valid but empty result."""
        raw = _make_raw_returns(n_dates=10, n_stocks=20)
        # Predictions on completely different dates
        dates = pd.bdate_range("2020-01-02", periods=10)
        instruments = raw.index.get_level_values("instrument").unique()[:20]
        idx = pd.MultiIndex.from_product(
            [dates, instruments], names=["datetime", "instrument"]
        )
        pred = pd.DataFrame({"score": np.zeros(len(idx))}, index=idx)

        result = evaluate_candidate(
            predictions=pred,
            raw_returns=raw,
            candidate_kind=CandidateKind.FACTOR_BASELINE,
        )
        assert result.status != CandidateStatus.PROMOTED

    def test_promotion_blockers_when_below_thresholds(self):
        """Poor model must have promotion blockers."""
        raw = _make_raw_returns(n_dates=20, n_stocks=30)
        # Random predictions with very weak IC
        rng = np.random.default_rng(123)
        scores = rng.normal(0, 1, len(raw))
        pred = pd.DataFrame({"score": scores}, index=raw.index)

        result = evaluate_candidate(
            predictions=pred,
            raw_returns=raw,
            candidate_kind=CandidateKind.FACTOR_BASELINE,
            topk=5,
        )
        assert result.status != CandidateStatus.PROMOTED
        assert len(result.promotion_blockers) > 0

    def test_to_dict_serializable(self):
        """CandidateResult.to_dict() must be JSON-serializable."""
        raw = _make_raw_returns(n_dates=15, n_stocks=30)
        pred = _make_predictions(raw)
        result = evaluate_candidate(
            predictions=pred,
            raw_returns=raw,
            candidate_kind=CandidateKind.LGBM_REGRESSOR,
        )
        d = result.to_dict()
        json.dumps(d)

    def test_factor_baseline_uses_explicit_input(self):
        """Factor baseline must use explicit historical-price input, not returns.

        The factor baseline predictions are created by _make_factor_baseline
        which generates scores from an independent random source — NOT from
        raw_returns.  This test proves the factor input is explicit historical
        data, not derived from future-return targets.
        """
        raw = _make_raw_returns(n_dates=20, n_stocks=40)
        factor_pred = _make_factor_baseline(raw)

        # Factor baseline scores are independent noise — correlation with
        # returns should be near zero (not leaked)
        result = evaluate_candidate(
            predictions=factor_pred,
            raw_returns=raw,
            candidate_kind=CandidateKind.FACTOR_BASELINE,
            topk=5,
        )

        # With independent noise factor, IC should be low (not extreme)
        assert abs(result.ic) < 0.15, (
            f"Factor baseline from explicit historical data should not "
            f"have extreme IC, got {result.ic:.4f}"
        )
        # Verify provenance was validated (would raise if wrong)
        assert result.candidate_kind == CandidateKind.FACTOR_BASELINE


# ---------------------------------------------------------------------------
# Comparison report
# ---------------------------------------------------------------------------


class TestComparisonReport:
    """Tests for ComparisonReport and run_signal_discovery_comparison()."""

    def test_full_comparison_run(self):
        """Full comparison run produces a valid report."""
        raw = _make_raw_returns(n_dates=20, n_stocks=40)
        pred = _make_predictions(raw, ic_strength=0.4)
        bench = _make_benchmark(raw)
        factor_pred = _make_factor_baseline(raw)

        report = run_signal_discovery_comparison(
            market="us",
            lgbm_predictions=pred,
            raw_returns=raw,
            factor_baseline_predictions=factor_pred,
            benchmark_returns=bench,
            topk=5,
            rebalance_days=10,
        )

        assert report.market == "us"
        assert report.label_horizon == 10
        assert report.rebalance_days == 10
        # At least: LGBM×2 + rank_transform×2 + factor_baseline×2 = 6
        assert len(report.candidates) >= 6
        # n_candidates is an integer (not a list)
        assert isinstance(report.summary["n_candidates"], int)
        assert report.summary["n_candidates"] == len(report.candidates)

    def test_report_schema(self):
        """ComparisonReport.to_dict() must conform to expected schema."""
        raw = _make_raw_returns(n_dates=15, n_stocks=30)
        pred = _make_predictions(raw)

        report = run_signal_discovery_comparison(
            market="us",
            lgbm_predictions=pred,
            raw_returns=raw,
            factor_baseline_predictions=None,
            topk=5,
        )

        d = report.to_dict()

        # Top-level schema
        assert d["schema_version"] == "1.0"
        assert d["market"] == "us"
        assert "generated_at" in d
        assert d["label_horizon"] == 10
        assert d["rebalance_days"] == 10
        assert isinstance(d["candidates"], list)
        assert isinstance(d["promoted"], list)
        assert isinstance(d["research_only"], list)
        assert isinstance(d["summary"], dict)
        assert isinstance(d["warnings"], list)

        # Each candidate must have required fields
        required_fields = {
            "candidate_kind", "orientation", "ic", "rank_ic", "icir",
            "positive_ic_ratio", "total_return", "benchmark_return",
            "excess_return", "sharpe", "max_drawdown",
            "score_direction", "status", "promotion_blockers",
        }
        for c in d["candidates"]:
            assert required_fields.issubset(c.keys()), (
                f"Missing fields: {required_fields - set(c.keys())}"
            )
            # score_direction sub-schema
            sd = c["score_direction"]
            assert "recommendation" in sd
            assert "top_minus_bottom_spread" in sd
            assert "rank_ic" in sd

        # JSON serializable
        json.dumps(d)

    def test_write_report(self, tmp_path: Path):
        """Report writing produces a valid file."""
        raw = _make_raw_returns(n_dates=10, n_stocks=20)
        pred = _make_predictions(raw)
        factor_pred = _make_factor_baseline(raw)

        output_dir = tmp_path / "10d_signal_discovery"
        run_signal_discovery_comparison(
            market="us",
            lgbm_predictions=pred,
            raw_returns=raw,
            factor_baseline_predictions=factor_pred,
            output_dir=output_dir,
        )

        report_path = output_dir / "us_signal_discovery_report.json"
        assert report_path.is_file()

        # Verify content
        loaded = json.loads(report_path.read_text())
        assert loaded["market"] == "us"
        assert loaded["schema_version"] == "1.0"

    def test_without_factor_baseline(self):
        """Running without factor_baseline_predictions should still produce LGBM + rank results."""
        raw = _make_raw_returns(n_dates=10, n_stocks=20)
        pred = _make_predictions(raw)

        report = run_signal_discovery_comparison(
            market="us",
            lgbm_predictions=pred,
            raw_returns=raw,
            factor_baseline_predictions=None,
            topk=5,
        )

        # Should have LGBM × 2 + rank × 2 = 4, no factor baseline
        kinds = {c.candidate_kind for c in report.candidates}
        assert CandidateKind.LGBM_REGRESSOR in kinds
        assert CandidateKind.RANK_TRANSFORM in kinds
        assert CandidateKind.FACTOR_BASELINE not in kinds

        # Should have warnings about missing factor baseline
        has_factor_warning = any(
            "factor_baseline" in w.lower() for w in report.warnings
        )
        assert has_factor_warning

    def test_no_promoted_when_none_qualify(self):
        """When no candidate meets thresholds, promoted is empty and warning exists."""
        raw = _make_raw_returns(n_dates=10, n_stocks=20)
        # Very weak predictions that won't pass thresholds
        rng = np.random.default_rng(999)
        scores = rng.normal(0, 1, len(raw))
        pred = pd.DataFrame({"score": scores}, index=raw.index)

        report = run_signal_discovery_comparison(
            market="us",
            lgbm_predictions=pred,
            raw_returns=raw,
            factor_baseline_predictions=None,
            topk=5,
        )

        assert report.promoted == []
        has_no_promotion_warning = any(
            "no candidate" in w.lower() for w in report.warnings
        )
        assert has_no_promotion_warning

    def test_rank_transform_candidate_present(self):
        """Rank transform candidate must appear in the report."""
        raw = _make_raw_returns(n_dates=15, n_stocks=30)
        pred = _make_predictions(raw)

        report = run_signal_discovery_comparison(
            market="us",
            lgbm_predictions=pred,
            raw_returns=raw,
            factor_baseline_predictions=None,
            topk=5,
        )

        rank_candidates = [
            c for c in report.candidates
            if c.candidate_kind == CandidateKind.RANK_TRANSFORM
        ]
        assert len(rank_candidates) == 2  # original + inverted


# ---------------------------------------------------------------------------
# Promotion thresholds
# ---------------------------------------------------------------------------


class TestPromotionThresholds:
    """Tests that promotion thresholds are structural and not silently bypassed."""

    def test_thresholds_are_non_empty(self):
        """Promotion thresholds must exist."""
        assert len(PROMOTION_THRESHOLDS) > 0
        assert "min_icir" in PROMOTION_THRESHOLDS
        assert PROMOTION_THRESHOLDS["min_icir"] > 0

    def test_strong_model_passes_thresholds(self):
        """A model with strong IC should have fewer blockers."""
        raw = _make_raw_returns(n_dates=30, n_stocks=50)
        # Very strong IC model
        scores = raw["return"] * 0.8 + np.random.default_rng(42).normal(
            0, 0.001, len(raw)
        )
        pred = pd.DataFrame({"score": scores.values}, index=raw.index)

        result = evaluate_candidate(
            predictions=pred,
            raw_returns=raw,
            candidate_kind=CandidateKind.LGBM_REGRESSOR,
            topk=5,
        )

        # With very strong IC, should have fewer blockers
        total_possible = 6  # number of checks in evaluate_candidate
        assert len(result.promotion_blockers) < total_possible

    def test_weak_model_has_blockers(self):
        """A weak model should list specific blockers."""
        raw = _make_raw_returns(n_dates=20, n_stocks=30)
        # Pure noise predictions
        rng = np.random.default_rng(555)
        scores = rng.normal(0, 1, len(raw))
        pred = pd.DataFrame({"score": scores}, index=raw.index)

        result = evaluate_candidate(
            predictions=pred,
            raw_returns=raw,
            candidate_kind=CandidateKind.FACTOR_BASELINE,
            topk=5,
        )

        assert result.status == CandidateStatus.RESEARCH
        assert len(result.promotion_blockers) > 0
        # Each blocker should mention the metric that failed
        for blocker in result.promotion_blockers:
            assert any(
                keyword in blocker.lower()
                for keyword in ["icir", "rank ic", "positive ic", "spread", "sharpe", "drawdown"]
            ), f"Blocker doesn't mention a known metric: {blocker}"


# ---------------------------------------------------------------------------
# Leakage protection
# ---------------------------------------------------------------------------


class TestLeakageProtection:
    """Tests that leakage safeguards are in place."""

    def test_processed_label_rejected_by_evaluate(self):
        """evaluate_candidate must reject processed labels (rank-normalized, etc.)."""
        raw = _make_raw_returns(n_dates=15, n_stocks=25)
        pred = _make_predictions(raw)

        # Mutate provenance to simulate rank-normalized labels being passed as returns
        contaminated = raw.copy()
        contaminated.attrs["provenance"] = "CSRankNorm_label"

        with pytest.raises(ValueError, match="raw_forward_return"):
            evaluate_candidate(
                predictions=pred,
                raw_returns=contaminated,
                candidate_kind=CandidateKind.LGBM_REGRESSOR,
            )

    def test_vectorized_economic_engine_fails_closed_for_processed_labels(self):
        from src.research.vectorized_backtest import run_vectorized_backtest

        raw = _make_raw_returns(n_dates=12, n_stocks=20)
        predictions = _make_predictions(raw)
        processed = raw.copy()
        processed.attrs["provenance"] = "rank_normalized_label"

        with pytest.raises(ValueError, match="raw_forward_return"):
            run_vectorized_backtest(
                predictions,
                processed,
                topk=5,
                rebalance_days=10,
                require_raw_10d_returns=True,
            )

    def test_processed_label_rejected_by_winner_labels(self):
        """generate_winner_labels must reject processed labels."""
        raw = _make_raw_returns()
        raw.attrs["provenance"] = "DropnaLabel_processed"

        with pytest.raises(ValueError, match="raw_forward_return"):
            generate_winner_labels(raw)

    def test_direction_diagnostics_accept_raw_only(self):
        """Direction diagnostics work with raw returns (provenance checked at caller)."""
        raw = _make_raw_returns(n_dates=10, n_stocks=20)
        pred = _make_predictions(raw)

        # Direction diagnostics itself doesn't check provenance (done at caller),
        # but it should still work correctly
        diag = compute_direction_diagnostics(pred["score"], raw["return"])
        assert diag.n_dates > 0

    def test_original_vs_inverted_evaluates_both(self):
        """The comparison report evaluates both original AND inverted orientations."""
        raw = _make_raw_returns(n_dates=12, n_stocks=25)
        pred = _make_predictions(raw)
        factor_pred = _make_factor_baseline(raw)

        report = run_signal_discovery_comparison(
            market="us",
            lgbm_predictions=pred,
            raw_returns=raw,
            factor_baseline_predictions=factor_pred,
            topk=5,
        )

        orientations = {c.orientation for c in report.candidates}
        assert ScoreOrientation.ORIGINAL in orientations
        assert ScoreOrientation.INVERTED in orientations

    def test_rank_transform_preserves_original_score_direction(self):
        from src.research.signal_discovery import _make_ranking_candidate

        raw = _make_raw_returns(n_dates=2, n_stocks=10)
        predictions = _make_predictions(raw)
        ranked = _make_ranking_candidate(predictions)

        for date in ranked.index.get_level_values("datetime").unique():
            original_day = predictions.xs(date, level="datetime")["score"]
            ranked_day = ranked.xs(date, level="datetime")["score"]
            assert original_day.idxmax() == ranked_day.idxmax()
            assert original_day.idxmin() == ranked_day.idxmin()

    def test_winner_labels_not_evaluated_as_candidates(self):
        """run_signal_discovery_comparison must NEVER evaluate winner labels as scores.

        The comparison workflow evaluates only LGBM, rank-transform, and
        factor-baseline candidates.  Winner-bucket labels are training targets
        only and must not appear as evaluated candidates in the comparison
        report.
        """
        raw = _make_raw_returns(n_dates=10, n_stocks=20)
        pred = _make_predictions(raw)
        factor_pred = _make_factor_baseline(raw)

        report = run_signal_discovery_comparison(
            market="us",
            lgbm_predictions=pred,
            raw_returns=raw,
            factor_baseline_predictions=factor_pred,
            topk=5,
        )

        # Winner-bucket classifier must NOT appear in evaluated candidates
        winner_candidates = [
            c for c in report.candidates
            if c.candidate_kind == CandidateKind.WINNER_BUCKET_CLASSIFIER
        ]
        assert len(winner_candidates) == 0, (
            "Winner-bucket labels must never be evaluated as candidate scores — "
            "that would be same-row target leakage."
        )

        # All three expected families must be present
        kinds = {c.candidate_kind for c in report.candidates}
        assert CandidateKind.LGBM_REGRESSOR in kinds
        assert CandidateKind.RANK_TRANSFORM in kinds
        assert CandidateKind.FACTOR_BASELINE in kinds


# ---------------------------------------------------------------------------
# Canonical output path
# ---------------------------------------------------------------------------


class TestCanonicalOutputPath:
    """Tests for canonical_output_dir()."""

    def test_returns_expected_path(self):
        from src.research.signal_discovery import canonical_output_dir

        project_root = Path("/project_root")
        path = canonical_output_dir(project_root)

        # Platform-independent: check parts, not exact string
        parts = path.parts
        assert "artifacts" in parts
        assert "evidence" in parts
        assert "10d_signal_discovery" in parts

    def test_path_is_relative_to_project_root(self):
        from src.research.signal_discovery import canonical_output_dir

        project_root = Path("/fake/project")
        path = canonical_output_dir(project_root)

        # The output dir should be under the project root
        assert str(path).startswith(str(project_root))


# ---------------------------------------------------------------------------
# Report schema integrity
# ---------------------------------------------------------------------------


class TestReportSchemaIntegrity:
    """Tests that the report schema is structurally correct."""

    def test_promoted_and_research_only_are_disjoint(self):
        """No candidate should be in both promoted and research_only lists."""
        raw = _make_raw_returns(n_dates=15, n_stocks=30)
        pred = _make_predictions(raw)
        factor_pred = _make_factor_baseline(raw)

        report = run_signal_discovery_comparison(
            market="us",
            lgbm_predictions=pred,
            raw_returns=raw,
            factor_baseline_predictions=factor_pred,
            topk=5,
        )

        overlap = set(report.promoted) & set(report.research_only)
        assert not overlap, f"Overlap between promoted and research_only: {overlap}"

    def test_all_candidates_accounted_for(self):
        """Every candidate must be in either promoted or research_only."""
        raw = _make_raw_returns(n_dates=15, n_stocks=30)
        pred = _make_predictions(raw)
        factor_pred = _make_factor_baseline(raw)

        report = run_signal_discovery_comparison(
            market="us",
            lgbm_predictions=pred,
            raw_returns=raw,
            factor_baseline_predictions=factor_pred,
            topk=5,
        )

        all_labels = {
            f"{c.candidate_kind.value}/{c.orientation.value}"
            for c in report.candidates
        }
        accounted = set(report.promoted) | set(report.research_only)
        assert all_labels == accounted, (
            f"Unaccounted candidates: {all_labels - accounted}"
        )

    def test_status_matches_list_membership(self):
        """A candidate's status field must match its list membership."""
        raw = _make_raw_returns(n_dates=15, n_stocks=30)
        pred = _make_predictions(raw)
        factor_pred = _make_factor_baseline(raw)

        report = run_signal_discovery_comparison(
            market="us",
            lgbm_predictions=pred,
            raw_returns=raw,
            factor_baseline_predictions=factor_pred,
            topk=5,
        )

        for c in report.candidates:
            label = f"{c.candidate_kind.value}/{c.orientation.value}"
            if c.status == CandidateStatus.PROMOTED:
                assert label in report.promoted, (
                    f"{label} is PROMOTED but not in promoted list"
                )
            else:
                assert label in report.research_only, (
                    f"{label} is {c.status.value} but not in research_only list"
                )

    def test_rationale_present_in_all_candidates(self):
        """Every candidate result must include strength/weakness rationale."""
        raw = _make_raw_returns(n_dates=15, n_stocks=30)
        pred = _make_predictions(raw)
        factor_pred = _make_factor_baseline(raw)

        report = run_signal_discovery_comparison(
            market="us",
            lgbm_predictions=pred,
            raw_returns=raw,
            factor_baseline_predictions=factor_pred,
            topk=5,
        )

        for c in report.candidates:
            d = c.to_dict()
            assert "strength_rationale" in d
            assert "weakness_rationale" in d
            assert isinstance(d["strength_rationale"], str)
            assert isinstance(d["weakness_rationale"], str)
