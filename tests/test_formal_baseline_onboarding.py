from __future__ import annotations

from pathlib import Path

from src.research.formal_baseline import load_formal_baseline
from src.research.formal_baseline_onboarding import run_formal_baseline_onboarding


CN_SPEC = Path("configs/research_experiments/cn_x1_1_research_loop_onboarding_v1.yaml")
BYD_SPEC = Path("configs/research_experiments/byd_v1_2_research_loop_onboarding_v1.yaml")
QQQ_SPEC = Path(
    "configs/research_experiments/qqq_rotation_v4_3_research_loop_onboarding_v1.yaml"
)

CN_BUNDLE_ID = "f6acc4932bc4eb25c624ef0186e944d094a3adda8c336aa918af9323970268ca"
CN_MANIFEST_SHA = "e7af7ce8b010cf824c51d646df4cc5a02496e8753e0f9a3f094fea7736c3d5bf"
BYD_BUNDLE_ID = "4d0ca5fb15006f532fd8458864664228045011676898b91ad4f48e886601f50e"
BYD_MANIFEST_SHA = "60b56998e992014916e91f6ceadfaeb5f7f1ef9084ba554282905e3da4e17028"
QQQ_BUNDLE_ID = "f70e5d09274b1a97048ca78bec79c1349211c93e2dc22eb02a7cba7a028c31d8"
QQQ_MANIFEST_SHA = "41b2e31ce8fe2f462631bfd8fa5c84732bc739fcbf2fc67ca0b913d08a0266e3"


def test_cn_x1_1_formal_bundle_is_hash_verified() -> None:
    baseline = load_formal_baseline(
        "cn_x1_1",
        expected_model_kind="cross_sectional_ranker",
        expected_model_family_id="cn_ranker",
        expected_bundle_id=CN_BUNDLE_ID,
        expected_manifest_sha256=CN_MANIFEST_SHA,
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
    assert receipt["baseline"]["bundle_id"] == CN_BUNDLE_ID
    assert receipt["research_only"] is True
    assert receipt["trade_ready"] is False
    assert receipt["automatic_promotion"] is False
    assert (tmp_path / "research_receipt.json").is_file()


def test_byd_v1_2_rules_based_bundle_is_hash_verified() -> None:
    baseline = load_formal_baseline(
        "byd_v1_2_convex_momentum_budget_v1",
        expected_model_kind="rules_based_allocation",
        expected_model_family_id="byd_allocation",
        expected_bundle_id=BYD_BUNDLE_ID,
        expected_manifest_sha256=BYD_MANIFEST_SHA,
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
    assert receipt["baseline"]["bundle_id"] == BYD_BUNDLE_ID
    assert receipt["research_only"] is True
    assert receipt["trade_ready"] is False
    assert receipt["automatic_promotion"] is False


def test_qqq_rotation_v4_3_rules_based_bundle_is_hash_verified() -> None:
    baseline = load_formal_baseline(
        "qqqi_qqq_tqqq_v4_3",
        expected_model_kind="rules_based_allocation",
        expected_model_family_id="qqq_rotation",
        expected_bundle_id=QQQ_BUNDLE_ID,
        expected_manifest_sha256=QQQ_MANIFEST_SHA,
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
    assert receipt["baseline"]["bundle_id"] == QQQ_BUNDLE_ID
    assert receipt["research_only"] is True
    assert receipt["trade_ready"] is False
    assert receipt["automatic_promotion"] is False
