from __future__ import annotations

from pathlib import Path

from src.research.formal_baseline import load_formal_baseline
from src.research.formal_baseline_onboarding import run_formal_baseline_onboarding


CN_SPEC = Path("configs/research_experiments/cn_x1_1_research_loop_onboarding_v1.yaml")
BYD_SPEC = Path("configs/research_experiments/byd_v1_2_research_loop_onboarding_v1.yaml")
QQQ_SPEC = Path(
    "configs/research_experiments/qqq_rotation_v4_2_research_loop_onboarding_v1.yaml"
)


def test_cn_x1_1_formal_bundle_is_hash_verified() -> None:
    baseline = load_formal_baseline(
        "cn_x1_1",
        expected_model_kind="cross_sectional_ranker",
        expected_model_family_id="cn_ranker",
        expected_bundle_id="bbf40fe790c5ec17cf9e408527b636e7368525667ebb7fffe0f2d05cb0c380a3",
        expected_manifest_sha256="76de89c60307767197d50e8c2cea1b1afa25eb5f77bd0b51af2465b922ac796a",
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
        "bbf40fe790c5ec17cf9e408527b636e7368525667ebb7fffe0f2d05cb0c380a3"
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
        expected_bundle_id="833ce53e918da4d7c62dd288e4c33c062637ec75ca8e39600b4d2ac2bf676c7d",
        expected_manifest_sha256="04c41f58f3db245ad6c084f9294b53ce056f37ab976437b43b949cc57dc1876e",
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
        "833ce53e918da4d7c62dd288e4c33c062637ec75ca8e39600b4d2ac2bf676c7d"
    )
    assert receipt["research_only"] is True
    assert receipt["trade_ready"] is False
    assert receipt["automatic_promotion"] is False


def test_qqq_rotation_v4_2_rules_based_bundle_is_hash_verified() -> None:
    baseline = load_formal_baseline(
        "qqqi_qqq_tqqq_v4_2",
        expected_model_kind="rules_based_allocation",
        expected_model_family_id="qqq_rotation",
        expected_bundle_id="2b041025af0a901692a5b0b4d7aae0fd63435431036fd45f3c53e4a4dbbef0ed",
        expected_manifest_sha256="fa815a183e224952cc3971fc8ce464bfa167b709b01ab5e61e6abfa69ab66bb4",
    )

    assert baseline.market == "us"
    assert baseline.benchmark == "QQQ"
    assert baseline.evidence_cutoff == "2026-07-31"
    assert baseline.metrics["total_return"] == 1.0352668079976044
    assert baseline.metrics["annualized_return"] == 0.3305745207818598
    assert baseline.metrics["max_drawdown"] == -0.2421341044679785


def test_qqq_rotation_v4_2_onboarding_emits_research_only_receipt(
    tmp_path: Path,
) -> None:
    receipt = run_formal_baseline_onboarding(QQQ_SPEC, output_dir=tmp_path)

    assert receipt["status"] == "completed"
    assert receipt["decision"] == "formal_baseline_bound"
    assert receipt["baseline"]["model_version_id"] == "qqqi_qqq_tqqq_v4_2"
    assert receipt["baseline"]["model_kind"] == "rules_based_allocation"
    assert receipt["baseline"]["bundle_id"] == (
        "2b041025af0a901692a5b0b4d7aae0fd63435431036fd45f3c53e4a4dbbef0ed"
    )
    assert receipt["research_only"] is True
    assert receipt["trade_ready"] is False
    assert receipt["automatic_promotion"] is False
