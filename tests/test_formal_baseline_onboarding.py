from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pytest
import yaml

from src.governance.active_strategy_catalog import ActiveStrategy, load_active_strategy_catalog
from src.research.formal_baseline import load_formal_baseline
from src.research.formal_baseline_onboarding import RUNNER_ID


EXPERIMENT_ROOT = Path("configs/research_experiments")
FORMAL_CATALOG = Path("data/research/formal_model_runs/catalog.json")
ACTIVE_STRATEGIES = load_active_strategy_catalog()
FORMAL_PAYLOAD = json.loads(FORMAL_CATALOG.read_text(encoding="utf-8"))
FORMAL_MODEL_IDS = {row["model_version_id"] for row in FORMAL_PAYLOAD["records"]}


def test_completed_onboarding_specs_do_not_remain_in_live_config() -> None:
    stale: list[str] = []
    for path in sorted(EXPERIMENT_ROOT.glob("*.yaml")):
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("runner") != RUNNER_ID:
            continue
        if payload.get("active") is not True:
            stale.append(path.as_posix())
    assert stale == []


def test_formal_catalog_matches_active_strategy_catalog() -> None:
    assert FORMAL_MODEL_IDS == set(ACTIVE_STRATEGIES.active_model_version_ids)


@pytest.mark.parametrize(
    "strategy",
    ACTIVE_STRATEGIES.strategies,
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
    assert date.fromisoformat(baseline.evidence_cutoff).isoformat() == baseline.evidence_cutoff
    assert baseline.bundle_id
    assert baseline.manifest_sha256
    assert baseline.metrics
