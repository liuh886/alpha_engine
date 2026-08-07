from __future__ import annotations

from pathlib import Path

from src.research.formal_baseline import load_formal_baseline
from src.research.formal_baseline_onboarding import run_formal_baseline_onboarding


CN_SPEC = Path("configs/research_experiments/cn_x1_1_research_loop_onboarding_v1.yaml")
BYD_SPEC = Path("configs/research_experiments/byd_v1_2_research_loop_onboarding_v1.yaml")
QQQ_SPEC = Path(
    "configs/research_experiments/qqq_rotation_v4_3_research_loop_onboarding_v1.yaml"
)

CN_BUNDLE_ID = "12ccb53404a198e184f89bf2bdcd724a17238be931a51df4fb781b8bdef3ba9e"
CN_MANIFEST_SHA = "08ed64d75e101b4079212f3130798c54647b4f2071c6f7ea5f70abe047e8fc15"
BYD_BUNDLE_ID = "e6b64d2d75e21e3701ec610c397ea16efcc5e9483cb30ad6475d1bd1d1fd990c"
BYD_MANIFEST_SHA = "2fb50136a4a7f37d39a403392a6dde1217a7c3f58e920ac5f6ffa7101274f9d6"
QQQ_BUNDLE_ID = "df2f6675d68169fcb1e8c7cf58febc7722638b881584451f48127a0196453e0e"
QQQ_MANIFEST_SHA = "41999fd55f6386a291883b29f65f831bda077f708e6ef4deed1302632c81fa3e"


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
