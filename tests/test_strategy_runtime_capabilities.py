from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from src.governance.active_strategy_catalog import load_active_strategy_catalog
from src.governance.strategy_runtime_capabilities import (
    StrategyRuntimeCapabilityError,
    load_active_strategy_runtime_capabilities,
    resolve_strategy_runtime_capabilities,
)

ROOT = Path(__file__).resolve().parents[1]


def test_active_runtime_capabilities_are_exact_and_fail_closed() -> None:
    capabilities = load_active_strategy_runtime_capabilities(repository_root=ROOT)

    assert set(capabilities) == {"qqq_rotation", "us_x", "cn_x", "byd"}
    assert capabilities["us_x"].formal_refresh.as_dict() == {
        "status": "available",
        "adapter_id": "us_x1_3_formal_refresh_v1",
        "reason": None,
    }
    assert capabilities["us_x"].current_target.as_dict() == {
        "status": "available",
        "adapter_id": "us_x1_3_current_target_v1",
        "reason": None,
    }
    assert capabilities["cn_x"].formal_refresh.as_dict() == {
        "status": "blocked",
        "adapter_id": None,
        "reason": "blocked_pending_maintained_cn_x1_2_formal_refresh_adapter",
    }
    assert capabilities["cn_x"].current_target.as_dict() == {
        "status": "blocked",
        "adapter_id": None,
        "reason": "blocked_pending_maintained_cn_x1_2_inference_adapter",
    }
    assert capabilities["qqq_rotation"].current_target.status == "not_applicable"
    assert capabilities["byd"].current_target.status == "not_applicable"


def test_unregistered_successor_does_not_reuse_predecessor_adapter(tmp_path: Path) -> None:
    active = load_active_strategy_catalog(ROOT / "configs/strategies/registry.json")
    incumbent = active.by_strategy_id["us_x"]
    successor = replace(
        incumbent,
        model_version_id="us_x1_4",
        model_contract="configs/models/us_x1_4.yaml",
        signal_ledger="data/research/strategy_signal_ledgers/us_x1_4",
    )
    source = ROOT / "configs/models/us_x1_3.yaml"
    payload = source.read_text(encoding="utf-8").replace(
        "model_id: us_x1_3", "model_id: us_x1_4"
    )
    contract = tmp_path / "configs/models/us_x1_4.yaml"
    contract.parent.mkdir(parents=True)
    contract.write_text(payload, encoding="utf-8")
    capability = resolve_strategy_runtime_capabilities(
        successor, repository_root=tmp_path
    )

    assert capability.formal_refresh.status == "blocked"
    assert capability.current_target.status == "blocked"
    assert capability.formal_refresh.adapter_id is None
    assert capability.current_target.adapter_id is None


def test_ranker_contract_identity_drift_fails_closed(tmp_path: Path) -> None:
    active = load_active_strategy_catalog(ROOT / "configs/strategies/registry.json")
    strategy = active.by_strategy_id["us_x"]
    contract = tmp_path / strategy.model_contract
    contract.parent.mkdir(parents=True)
    payload = {
        "model_id": strategy.model_version_id,
        "market": "cn",
        "research_only": True,
        "trade_ready": False,
    }
    contract.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(StrategyRuntimeCapabilityError, match="market"):
        resolve_strategy_runtime_capabilities(strategy, repository_root=tmp_path)
