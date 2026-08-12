from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from src.governance.active_strategy_catalog import ActiveStrategy, load_active_strategy_catalog
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
ACTIVE_FORMAL_STRATEGIES = load_active_strategy_catalog().strategies


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
    "strategy",
    ACTIVE_FORMAL_STRATEGIES,
    ids=lambda strategy: strategy.strategy_id,
)
def test_current_formal_catalog_bundle_is_hash_verified(strategy: ActiveStrategy) -> None:
    baseline = load_formal_baseline(
        strategy.model_version_id,
        expected_model_kind=strategy.model_kind,
        expected_model_family_id=strategy.model_family_id,
    )

    assert baseline.model_version_id == strategy.model_version_id
    assert baseline.model_family_id == strategy.model_family_id
    assert baseline.model_kind == strategy.model_kind
    assert baseline.market == strategy.market
    assert baseline.benchmark
    # The formal catalog is refreshed independently of this contract test. Pinning
    # a copied cutoff or model version here makes every valid promotion/refresh break
    # backend CI even though load_formal_baseline already verifies catalog/manifest
    # identity. Keep these assertions structural so the test follows the active
    # strategy catalog and accepted formal bundle automatically.
    assert date.fromisoformat(baseline.evidence_cutoff).isoformat() == baseline.evidence_cutoff
    assert baseline.bundle_id
    assert baseline.manifest_sha256
    assert baseline.metrics
