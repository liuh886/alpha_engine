from __future__ import annotations

from pathlib import Path

from src.research.formal_baseline import load_formal_baseline
from src.research.formal_baseline_onboarding import run_formal_baseline_onboarding


CN_SPEC = Path("configs/research_experiments/cn_x1_1_research_loop_onboarding_v1.yaml")
BYD_SPEC = Path("configs/research_experiments/byd_v1_2_research_loop_onboarding_v1.yaml")
QQQ_SPEC = Path(
    "configs/research_experiments/qqq_rotation_v4_3_research_loop_onboarding_v1.yaml"
)


def test_cn_x1_1_formal_bundle_is_hash_verified() -> None:
    baseline = load_formal_baseline(
        "cn_x1_1",
        expected_model_kind="cross_sectional_ranker",
        expected_model_family_id="cn_ranker",
        expected_bundle_id="4ac43a397cba652ddee49c66acbda90fae0ff1c8cb7c3ac7947657e7d01fa1bb",
        expected_manifest_sha256="f46922d12b2a8f5dbf8cb1251643417f7567a95d8e9fd8d867c65d2060e73a3d",
    )

    assert baseline.market == "cn"
    assert baseline.benchmark == "000300"
    assert baseline.evidence_cutoff == "2026-08-03"
    assert baseline.metrics["excess_return"] == 0.5922541247895701
    assert baseline.metrics["max_drawdown"] == -0.37059032672209047


def test_cn_x1_1_onboarding_emits_research_only_receipt(tmp_path: Path) -> None:
    receipt = run_formal_baseline_onboarding(CN_SPEC, output_dir=tmp_path)

    assert receipt["status"] == "completed"
    assert receipt["decision"] == "formal_baseline_bound"
    assert receipt["baseline"]["model_version_id"] == "cn_x1_1"
    assert receipt["baseline"]["bundle_id"] == (
        "4ac43a397cba652ddee49c66acbda90fae0ff1c8cb7c3ac7947657e7d01fa1bb"
    )
    assert receipt["research_only"] is True
    assert receipt["trade_ready"] is False
    assert receipt["automatic_promotion"] is False
    assert (tmp_path / "research_receipt.json").is_file()


def test_byd_v1_2_rules_based_bundle_is_hash_verified() -> None:
    baseline = load_formal_baseline(
        "byd_v1_2_convex_momentum_budget_v1",
        expected_model_kind="rules_based_allocation",
        expected_model_family_id="byd_allocation",
        expected_bundle_id="65c9d6fc353fcca0f1c9c4a9ce7203058e3a4cb7eeac0a7b97bae19cbbfe8faf",
        expected_manifest_sha256="a813f5cb166f6803d86608084f134e2e22ece431328c4091c5b9261fb7401177",
    )

    assert baseline.market == "cn"
    assert baseline.benchmark == "BYD v1.1"
    assert baseline.evidence_cutoff == "2026-08-03"
    assert baseline.metrics["total_return"] == 6.070391877325108
    assert baseline.metrics["annualized_return"] == 0.35843544390055615
    assert baseline.metrics["max_drawdown"] == -0.4920228932073253


def test_byd_v1_2_onboarding_emits_research_only_receipt(tmp_path: Path) -> None:
    receipt = run_formal_baseline_onboarding(BYD_SPEC, output_dir=tmp_path)

    assert receipt["status"] == "completed"
    assert receipt["decision"] == "formal_baseline_bound"
    assert receipt["baseline"]["model_version_id"] == (
        "byd_v1_2_convex_momentum_budget_v1"
    )
    assert receipt["baseline"]["model_kind"] == "rules_based_allocation"
    assert receipt["baseline"]["bundle_id"] == (
        "65c9d6fc353fcca0f1c9c4a9ce7203058e3a4cb7eeac0a7b97bae19cbbfe8faf"
    )
    assert receipt["research_only"] is True
    assert receipt["trade_ready"] is False
    assert receipt["automatic_promotion"] is False


def test_qqq_rotation_v4_3_rules_based_bundle_is_hash_verified() -> None:
    baseline = load_formal_baseline(
        "qqqi_qqq_tqqq_v4_3",
        expected_model_kind="rules_based_allocation",
        expected_model_family_id="qqq_rotation",
        expected_bundle_id="701fbe8bc6534ff035f6ad2b4c92e32582430c5bd17e5b873817b3fb0eab510d",
        expected_manifest_sha256="3516e73c9a8123ea48be5ed1bd7d1051a207d02bd94824ecef6bf41e925e8ad3",
    )

    assert baseline.market == "us"
    assert baseline.benchmark == "QQQ"
    assert baseline.evidence_cutoff == "2026-08-06"
    assert baseline.metrics["total_return"] == 1.19125278989529
    assert baseline.metrics["annualized_return"] == 0.3679210193759259
    assert baseline.metrics["max_drawdown"] == -0.21658197720414185


def test_qqq_rotation_v4_3_onboarding_emits_research_only_receipt(
    tmp_path: Path,
) -> None:
    receipt = run_formal_baseline_onboarding(QQQ_SPEC, output_dir=tmp_path)

    assert receipt["status"] == "completed"
    assert receipt["decision"] == "formal_baseline_bound"
    assert receipt["baseline"]["model_version_id"] == "qqqi_qqq_tqqq_v4_3"
    assert receipt["baseline"]["model_kind"] == "rules_based_allocation"
    assert receipt["baseline"]["bundle_id"] == (
        "701fbe8bc6534ff035f6ad2b4c92e32582430c5bd17e5b873817b3fb0eab510d"
    )
    assert receipt["research_only"] is True
    assert receipt["trade_ready"] is False
    assert receipt["automatic_promotion"] is False
