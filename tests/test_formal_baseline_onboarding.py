from __future__ import annotations

from pathlib import Path

import yaml

from src.research.formal_baseline import load_formal_baseline
from src.research.formal_baseline_onboarding import run_formal_baseline_onboarding


CN_SPEC = Path("configs/research_experiments/cn_x1_1_research_loop_onboarding_v1.yaml")
BYD_SPEC = Path("configs/research_experiments/byd_v1_2_research_loop_onboarding_v1.yaml")
QQQ_SPEC = Path(
    "configs/research_experiments/qqq_rotation_v4_3_research_loop_onboarding_v1.yaml"
)


def _spec(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_from_spec(
    path: Path,
    *,
    model_version_id: str,
    model_kind: str,
    model_family_id: str,
):
    spec = _spec(path)
    baseline = spec["baseline"]
    return load_formal_baseline(
        model_version_id,
        expected_model_kind=model_kind,
        expected_model_family_id=model_family_id,
        expected_bundle_id=baseline["bundle_id"],
        expected_manifest_sha256=baseline["manifest_sha256"],
    )


def test_cn_x1_1_formal_bundle_is_hash_verified() -> None:
    baseline = _load_from_spec(
        CN_SPEC,
        model_version_id="cn_x1_1",
        model_kind="cross_sectional_ranker",
        model_family_id="cn_ranker",
    )
    assert baseline.market == "cn"
    assert baseline.benchmark == "000300"
    assert baseline.evidence_cutoff == "2026-08-03"
    assert baseline.metrics["excess_return"] == 0.5922541247895701
    assert baseline.metrics["max_drawdown"] == -0.37059032672209047


def test_cn_x1_1_onboarding_emits_research_only_receipt(tmp_path: Path) -> None:
    spec = _spec(CN_SPEC)
    receipt = run_formal_baseline_onboarding(CN_SPEC, output_dir=tmp_path)
    assert receipt["status"] == "completed"
    assert receipt["decision"] == "formal_baseline_bound"
    assert receipt["baseline"]["model_version_id"] == "cn_x1_1"
    assert receipt["baseline"]["bundle_id"] == spec["baseline"]["bundle_id"]
    assert receipt["research_only"] is True
    assert receipt["trade_ready"] is False
    assert receipt["automatic_promotion"] is False
    assert (tmp_path / "research_receipt.json").is_file()


def test_byd_v1_2_rules_based_bundle_is_hash_verified() -> None:
    baseline = _load_from_spec(
        BYD_SPEC,
        model_version_id="byd_v1_2_convex_momentum_budget_v1",
        model_kind="rules_based_allocation",
        model_family_id="byd_allocation",
    )
    assert baseline.market == "cn"
    assert baseline.benchmark == "BYD v1.1"
    assert baseline.evidence_cutoff == "2026-08-03"
    assert baseline.metrics["total_return"] == 6.070391877325108
    assert baseline.metrics["annualized_return"] == 0.35843544390055615
    assert baseline.metrics["max_drawdown"] == -0.4920228932073253


def test_byd_v1_2_onboarding_emits_research_only_receipt(tmp_path: Path) -> None:
    spec = _spec(BYD_SPEC)
    receipt = run_formal_baseline_onboarding(BYD_SPEC, output_dir=tmp_path)
    assert receipt["status"] == "completed"
    assert receipt["decision"] == "formal_baseline_bound"
    assert receipt["baseline"]["model_version_id"] == (
        "byd_v1_2_convex_momentum_budget_v1"
    )
    assert receipt["baseline"]["model_kind"] == "rules_based_allocation"
    assert receipt["baseline"]["bundle_id"] == spec["baseline"]["bundle_id"]
    assert receipt["research_only"] is True
    assert receipt["trade_ready"] is False
    assert receipt["automatic_promotion"] is False


def test_qqq_rotation_v4_3_rules_based_bundle_is_hash_verified() -> None:
    baseline = _load_from_spec(
        QQQ_SPEC,
        model_version_id="qqqi_qqq_tqqq_v4_3",
        model_kind="rules_based_allocation",
        model_family_id="qqq_rotation",
    )
    assert baseline.market == "us"
    assert baseline.benchmark == "QQQ"
    assert baseline.evidence_cutoff == "2026-08-07"
    assert baseline.metrics["max_drawdown"] < 0
    assert baseline.metrics["annualized_return"] > 0


def test_qqq_rotation_v4_3_onboarding_emits_research_only_receipt(
    tmp_path: Path,
) -> None:
    spec = _spec(QQQ_SPEC)
    receipt = run_formal_baseline_onboarding(QQQ_SPEC, output_dir=tmp_path)
    assert receipt["status"] == "completed"
    assert receipt["decision"] == "formal_baseline_bound"
    assert receipt["baseline"]["model_version_id"] == "qqqi_qqq_tqqq_v4_3"
    assert receipt["baseline"]["model_kind"] == "rules_based_allocation"
    assert receipt["baseline"]["bundle_id"] == spec["baseline"]["bundle_id"]
    assert receipt["research_only"] is True
    assert receipt["trade_ready"] is False
    assert receipt["automatic_promotion"] is False
