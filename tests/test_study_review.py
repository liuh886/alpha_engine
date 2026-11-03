"""Tests for continuous hypothesis review loop (E1)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.research.study_review import (
    CounterEvidenceItem,
    CounterEvidenceSeverity,
    FrozenConditions,
    HypothesisSpec,
    ObservationMetrics,
    ReviewConclusion,
    ReviewLifecycleState,
    ScheduledReview,
    StudyReviewRecord,
    add_counter_evidence,
    create_study_review,
    format_study_review_markdown,
    list_study_reviews,
    load_study_review,
    save_study_review,
)


@pytest.fixture
def sample_hypothesis() -> HypothesisSpec:
    return HypothesisSpec(
        statement="Low volatility equities provide downside protection in tech pullbacks.",
        economic_rationale="High-beta growth stocks suffer severe variance drag during corrections.",
        expected_edge="Lower maximum drawdown by at least 5% vs equal-weight benchmark.",
        falsification_criteria=[
            "Max drawdown exceeds equal-weight benchmark.",
            "1-year excess return drops below -25%.",
        ],
    )


@pytest.fixture
def sample_frozen_conditions() -> FrozenConditions:
    return FrozenConditions(
        frozen_at_cutoff="2024-01-01",
        market="us",
        pool_id="us_selected_equities_v2",
        runner_id="us87_low_vol_challenger_v1",
        benchmarks=["us87_ew_pool_runner_v1", "QQQ"],
        cost_bps=8.0,
        rebalance_cadence="monthly_first_session",
    )


@pytest.fixture
def sample_scheduled_review() -> ScheduledReview:
    return ScheduledReview(
        next_review_session="2026-12-01",
        cadence="monthly",
        review_triggers=["max_drawdown_below_-0.25"],
    )


def test_study_review_creation_and_fingerprint(
    sample_hypothesis: HypothesisSpec,
    sample_frozen_conditions: FrozenConditions,
    sample_scheduled_review: ScheduledReview,
):
    record = create_study_review(
        review_id="rev_test_001",
        title="Test Review",
        hypothesis=sample_hypothesis,
        frozen_conditions=sample_frozen_conditions,
        scheduled_review=sample_scheduled_review,
    )
    assert record.review_id == "rev_test_001"
    assert record.lifecycle_state == ReviewLifecycleState.OBSERVING
    assert record.research_only is True
    assert record.trade_ready is False
    assert len(record.lineage_fingerprint) == 64
    assert record.compute_fingerprint() == record.lineage_fingerprint


def test_study_review_serialization_roundtrip(
    tmp_path: Path,
    sample_hypothesis: HypothesisSpec,
    sample_frozen_conditions: FrozenConditions,
    sample_scheduled_review: ScheduledReview,
):
    obs = {
        "full_sample": ObservationMetrics(
            as_of_session="2026-11-02",
            sample_kind="full_sample",
            cumulative_return=0.15,
            annualized_return=0.07,
            sharpe_ratio=0.85,
            max_drawdown=-0.12,
            persistence_score=0.45,
            vs_benchmark_returns={"QQQ": -0.02},
            rebalances_count=20,
            cash_drag_ratio=0.02,
        )
    }
    concl = ReviewConclusion(
        verdict="Observing steady low-beta characteristics",
        verdict_session="2026-11-02",
        summary="Consistent with thesis",
        supported_points=["Max drawdown within limit"],
        unresolved_risks=["Potential beta drag in bull rallies"],
        recommendation="continue_observing",
    )
    record = create_study_review(
        review_id="rev_test_roundtrip",
        title="Roundtrip Test",
        hypothesis=sample_hypothesis,
        frozen_conditions=sample_frozen_conditions,
        scheduled_review=sample_scheduled_review,
        initial_observations=obs,
        initial_conclusion=concl,
    )

    out_file = tmp_path / "test_review.json"
    save_study_review(record, out_file)
    assert out_file.is_file()

    loaded = load_study_review(out_file)
    assert loaded.review_id == record.review_id
    assert loaded.title == record.title
    assert loaded.hypothesis.statement == sample_hypothesis.statement
    assert loaded.observations["full_sample"].cumulative_return == 0.15
    assert loaded.conclusion.verdict == "Observing steady low-beta characteristics"
    assert loaded.lineage_fingerprint == record.lineage_fingerprint


def test_tampered_review_fingerprint_raises_value_error(
    tmp_path: Path,
    sample_hypothesis: HypothesisSpec,
    sample_frozen_conditions: FrozenConditions,
    sample_scheduled_review: ScheduledReview,
):
    record = create_study_review(
        review_id="rev_test_tamper",
        title="Tamper Test",
        hypothesis=sample_hypothesis,
        frozen_conditions=sample_frozen_conditions,
        scheduled_review=sample_scheduled_review,
    )
    out_file = tmp_path / "tampered.json"
    save_study_review(record, out_file)

    # Tamper with hypothesis without updating fingerprint
    raw = json.loads(out_file.read_text(encoding="utf-8"))
    raw["hypothesis"]["statement"] = "Tampered statement claiming 1000% returns"
    out_file.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="Review record fingerprint mismatch"):
        load_study_review(out_file)


def test_add_counter_evidence_and_lifecycle_transitions(
    sample_hypothesis: HypothesisSpec,
    sample_frozen_conditions: FrozenConditions,
    sample_scheduled_review: ScheduledReview,
):
    record = create_study_review(
        review_id="rev_test_transitions",
        title="Transition Test",
        hypothesis=sample_hypothesis,
        frozen_conditions=sample_frozen_conditions,
        scheduled_review=sample_scheduled_review,
        lifecycle_state=ReviewLifecycleState.SUPPORTED,
    )
    assert record.lifecycle_state == ReviewLifecycleState.SUPPORTED

    # Adding INFO does not degrade state
    record = add_counter_evidence(
        record,
        category="beta_drag",
        observation="Expected minor lag in momentum rally",
        session="2025-01-02",
        severity=CounterEvidenceSeverity.INFO,
    )
    assert len(record.counter_evidence) == 1
    assert record.counter_evidence[0].evidence_id == "CE-001"
    assert record.lifecycle_state == ReviewLifecycleState.SUPPORTED

    # Adding WARNING degrades SUPPORTED to CHALLENGED
    record = add_counter_evidence(
        record,
        category="turnover_drag",
        observation="Turnover surged to 45%",
        session="2025-06-02",
        severity=CounterEvidenceSeverity.WARNING,
    )
    assert len(record.counter_evidence) == 2
    assert record.counter_evidence[1].evidence_id == "CE-002"
    assert record.lifecycle_state == ReviewLifecycleState.CHALLENGED

    # Adding FALSIFYING maintains CHALLENGED (ready for REFUTED verdict)
    record = add_counter_evidence(
        record,
        category="drawdown_breach",
        observation="Drawdown exceeded 30%",
        session="2025-09-02",
        severity=CounterEvidenceSeverity.FALSIFYING,
    )
    assert len(record.counter_evidence) == 3
    assert record.lifecycle_state == ReviewLifecycleState.CHALLENGED


def test_markdown_formatter_renders_all_six_lifecycle_stages(
    sample_hypothesis: HypothesisSpec,
    sample_frozen_conditions: FrozenConditions,
    sample_scheduled_review: ScheduledReview,
):
    record = create_study_review(
        review_id="rev_test_md",
        title="Markdown Test",
        hypothesis=sample_hypothesis,
        frozen_conditions=sample_frozen_conditions,
        scheduled_review=sample_scheduled_review,
        initial_observations={
            "oos": ObservationMetrics(
                as_of_session="2026-11-02",
                sample_kind="out_of_sample",
                cumulative_return=0.05,
                annualized_return=0.03,
                sharpe_ratio=0.6,
                max_drawdown=-0.10,
                persistence_score=0.4,
                vs_benchmark_returns={"us87_ew_pool_runner_v1": -0.15},
                rebalances_count=10,
            )
        },
    )
    md = format_study_review_markdown(record)
    assert "1. Hypothesis Formulation (提出假设)" in md
    assert "2. Frozen Conditions (冻结条件)" in md
    assert "3. Performance Observations (表现观察)" in md
    assert "4. Counter-Evidence Collection (反证收集与证伪检验)" in md
    assert "5. Review Conclusion (当前结论)" in md
    assert "6. Scheduled Review & Watchpoints (后续复核与触发预警)" in md
    assert "us87_low_vol_challenger_v1" in md
    assert "2026-12-01" in md


def test_list_study_reviews_in_directory(tmp_path: Path, sample_hypothesis, sample_frozen_conditions, sample_scheduled_review):
    record = create_study_review(
        review_id="rev_list_001",
        title="List Test",
        hypothesis=sample_hypothesis,
        frozen_conditions=sample_frozen_conditions,
        scheduled_review=sample_scheduled_review,
    )
    save_study_review(record, tmp_path / "rev_list_001.json")
    # Write invalid json
    (tmp_path / "invalid.json").write_text("not json", encoding="utf-8")

    reviews = list_study_reviews(tmp_path)
    assert len(reviews) == 1
    assert reviews[0]["review_id"] == "rev_list_001"
    assert reviews[0]["runner_id"] == "us87_low_vol_challenger_v1"


def test_cli_study_review_integration(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]

    # 1. Test CLI list on actual study_reviews directory
    out = subprocess.check_output(
        [sys.executable, "-m", "src.cli.main", "research", "study", "review", "list"],
        cwd=root,
        text=True,
    )
    data = json.loads(out)
    assert "reviews" in data
    assert any(r["review_id"] == "rev_us87_low_vol_v1" for r in data["reviews"])

    # 2. Test CLI show markdown
    out_md = subprocess.check_output(
        [
            sys.executable,
            "-m",
            "src.cli.main",
            "research",
            "study",
            "review",
            "show",
            "data/research/study_reviews/us87_low_vol_review_v1.json",
        ],
        cwd=root,
        text=True,
    )
    assert "Investment Hypothesis Continuous Review" in out_md
    assert "US87 Low-Volatility Defense Hypothesis" in out_md
    assert "CE-001" in out_md

    # 3. Test CLI init
    init_out_file = tmp_path / "cli_init_review.json"
    out_init = subprocess.check_output(
        [
            sys.executable,
            "-m",
            "src.cli.main",
            "research",
            "study",
            "review",
            "init",
            "--review-id",
            "rev_cli_test",
            "--title",
            "CLI Scaffold Review",
            "--runner-id",
            "us87_low_vol_challenger_v1",
            "--statement",
            "Testing CLI init command",
            "--output",
            str(init_out_file),
        ],
        cwd=root,
        text=True,
    )
    init_data = json.loads(out_init)
    assert init_data["status"] == "created"
    assert init_out_file.is_file()

    # 4. Test CLI add-counter-evidence
    out_ce = subprocess.check_output(
        [
            sys.executable,
            "-m",
            "src.cli.main",
            "research",
            "study",
            "review",
            "add-counter-evidence",
            str(init_out_file),
            "--category",
            "beta_drag",
            "--observation",
            "Observed severe lag during AI boom",
            "--session",
            "2026-05-01",
            "--severity",
            "warning",
        ],
        cwd=root,
        text=True,
    )
    ce_data = json.loads(out_ce)
    assert ce_data["status"] == "counter_evidence_added"
    assert ce_data["evidence_count"] == 1
    assert ce_data["lifecycle_state"] == "challenged"
