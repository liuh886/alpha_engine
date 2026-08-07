from __future__ import annotations

from pathlib import Path

from src.research.formal_baseline import load_formal_baseline
from src.research.formal_baseline_onboarding import run_formal_baseline_onboarding


SPEC = Path("configs/research_experiments/cn_x1_1_research_loop_onboarding_v1.yaml")


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
    receipt = run_formal_baseline_onboarding(SPEC, output_dir=tmp_path)

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
