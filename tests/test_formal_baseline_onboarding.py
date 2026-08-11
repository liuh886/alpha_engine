from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from src.research.formal_baseline import load_formal_baseline
from src.research.formal_baseline_onboarding import (
    load_completed_onboarding_record,
    run_formal_baseline_onboarding,
)


CN_SPEC = Path("configs/research_experiments/cn_x1_1_research_loop_onboarding_v1.yaml")
BYD_SPEC = Path("configs/research_experiments/byd_v1_2_research_loop_onboarding_v1.yaml")
QQQ_SPEC = Path(
    "configs/research_experiments/qqq_rotation_v4_3_research_loop_onboarding_v1.yaml"
)
COMPLETED_SPECS = (CN_SPEC, BYD_SPEC, QQQ_SPEC)


def _spec(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


@pytest.mark.parametrize("spec_path", COMPLETED_SPECS)
def test_completed_onboarding_record_keeps_its_historical_identity(spec_path: Path) -> None:
    spec = _spec(spec_path)
    receipt = load_completed_onboarding_record(spec_path)

    assert receipt["status"] == "completed"
    assert receipt["decision"] == "formal_baseline_bound"
    assert receipt["baseline"]["model_version_id"] == spec["baseline"]["model_version_id"]
    assert receipt["baseline"]["bundle_id"] == spec["baseline"]["bundle_id"]
    assert receipt["baseline"]["manifest_sha256"] == spec["baseline"]["manifest_sha256"]
    assert receipt["baseline"]["evidence_cutoff"] == spec["expected_identity"]["evidence_cutoff"]
    assert receipt["research_only"] is True
    assert receipt["trade_ready"] is False
    assert receipt["automatic_promotion"] is False


@pytest.mark.parametrize("spec_path", COMPLETED_SPECS)
def test_completed_onboarding_spec_cannot_be_replayed(spec_path: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="cannot be replayed"):
        run_formal_baseline_onboarding(spec_path, output_dir=tmp_path)


def test_completed_record_validation_does_not_resolve_current_catalog(monkeypatch) -> None:
    def _unexpected_catalog_lookup(*args, **kwargs):
        del args, kwargs
        raise AssertionError("historical onboarding validation touched the current catalog")

    monkeypatch.setattr(
        "src.research.formal_baseline_onboarding.load_formal_baseline",
        _unexpected_catalog_lookup,
    )
    receipt = load_completed_onboarding_record(CN_SPEC)
    assert receipt["baseline"]["model_version_id"] == "cn_x1_1"


@pytest.mark.parametrize(
    ("model_version_id", "model_kind", "model_family_id", "market", "benchmark"),
    (
        ("us_x1_2", "cross_sectional_ranker", "us_ranker", "us", "QQQ"),
        ("cn_x1_1", "cross_sectional_ranker", "cn_ranker", "cn", "000300"),
        (
            "byd_v1_3_recovery_event_low_vol_confirmation_v1",
            "rules_based_allocation",
            "byd_allocation",
            "cn",
            "BYD v1.2",
        ),
        (
            "qqqi_qqq_tqqq_v4_3",
            "rules_based_allocation",
            "qqq_rotation",
            "us",
            "QQQ",
        ),
    ),
)
def test_current_formal_catalog_bundle_is_hash_verified(
    model_version_id: str,
    model_kind: str,
    model_family_id: str,
    market: str,
    benchmark: str,
) -> None:
    baseline = load_formal_baseline(
        model_version_id,
        expected_model_kind=model_kind,
        expected_model_family_id=model_family_id,
    )

    assert baseline.market == market
    assert baseline.benchmark == benchmark
    # The formal catalog is refreshed independently of this contract test.  Pinning
    # a copied cutoff here makes every valid refresh break backend CI even though
    # ``load_formal_baseline`` already verifies catalog/manifest identity.  Keep
    # this assertion structural so the test follows the accepted formal bundle.
    assert date.fromisoformat(baseline.evidence_cutoff).isoformat() == baseline.evidence_cutoff
    assert baseline.bundle_id
    assert baseline.manifest_sha256
    assert baseline.metrics
