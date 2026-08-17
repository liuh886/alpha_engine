from __future__ import annotations

from pathlib import Path

import yaml

from src.governance.active_strategy_catalog import load_active_strategy_catalog
from src.governance.strategy_runtime_capabilities import load_active_strategy_runtime_capabilities
from src.research.cn_x1_2_current_target import MODEL_ID as CN_MODEL_ID
from src.research.cn_x1_2_prospective import FROZEN_TRAIN_END

ROOT = Path(__file__).resolve().parents[1]


def test_both_active_rankers_have_exact_current_target_adapters() -> None:
    active = load_active_strategy_catalog(ROOT / "configs/strategies/registry.json")
    capabilities = load_active_strategy_runtime_capabilities(
        repository_root=ROOT,
        active=active,
    )
    assert capabilities["us_x"].current_target.adapter_id == "us_x1_3_current_target_v1"
    assert capabilities["cn_x"].current_target.adapter_id == "cn_x1_2_current_target_v1"


def test_cn_x1_2_current_target_keeps_frozen_training_boundary() -> None:
    config = yaml.safe_load((ROOT / "configs/models/cn_x1_2.yaml").read_text(encoding="utf-8"))
    assert CN_MODEL_ID == "cn_x1_2"
    assert FROZEN_TRAIN_END == "2026-06-30"
    assert config["formal_publication"]["current_target_activation"] == "maintained_cn_x1_2_current_target_v1"
    assert "blocked_pending" not in (ROOT / "configs/models/cn_x1_2.yaml").read_text(encoding="utf-8")


def test_ranker_workflow_has_no_delivery_transport() -> None:
    workflow = (ROOT / ".github/workflows/ranker-10d-current-target.yml").read_text(encoding="utf-8")
    assert "scripts/run_ranker_current_target.py" in workflow
    assert "TELEGRAM_BOT_TOKEN" not in workflow
    assert "api.telegram.org" not in workflow
    assert "gh issue create" not in workflow
    assert "run_us_x1_3_current_target.py" not in workflow
