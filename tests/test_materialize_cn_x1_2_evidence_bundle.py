from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from src.artifacts.model_run_bundle_v2 import (
    canonical_json_bytes,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/materialize_cn_x1_2_evidence_bundle.py"
PORTFOLIO = Path(
    "data/research/cn_x1_2_alpha158_breadth_scaled_v1/"
    "challenger_portfolio_evidence.json"
)
EXPERIMENT = Path(
    "data/research/experiment_receipts/cn_x1_2_alpha158_breadth_scaled_v1.json"
)
PROMOTION = Path(
    "data/research/experiment_receipts/cn_x1_2_user_directed_promotion_v1.json"
)
SOURCE = ROOT / (
    "data/research/historical_model_evidence/"
    "cn_x1_2_alpha158_breadth_scaled_v1.json"
)


def _load() -> ModuleType:
    name = "materialize_cn_x1_2_evidence_bundle"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_retired_cn_x1_2_historical_package_remains_exact() -> None:
    promotion = json.loads((ROOT / PROMOTION).read_text(encoding="utf-8"))
    recorded = str(promotion["portfolio_evidence"]["sha256"])
    actual = hashlib.sha256((ROOT / PORTFOLIO).read_bytes()).hexdigest()
    # The receipt must stay bound to the exact committed portfolio bytes;
    # drift here is what issue #1046 recorded and the governed re-publish
    # via promote_cn_x1_2_governance_exception.py fixed.
    assert recorded == actual

    module = _load()
    package = module.build_package(PORTFOLIO, EXPERIMENT, PROMOTION)
    assert canonical_json_bytes(package) == SOURCE.read_bytes()
    assert package["evidence_completeness"]["status"] == "complete"
    assert package["evidence_completeness"]["missing"] == []
    assert package["evidence"]["preregistered_gates_supported"] is False
    assert package["evidence"]["failed_gate"] == module.FAILED_GATE
    assert package["evidence"]["no_2026h2_evidence_consumed"] is True
    assert len(package["report"]) == 57
    assert len(package["positions"]) == 170
    assert package["trades"]
    assert package["attribution"]


@pytest.mark.parametrize("update_catalogs", [False, True])
def test_retired_cn_x1_2_cannot_publish_active_bundles(tmp_path: Path, update_catalogs: bool) -> None:
    module = _load()
    canonical_paths = [ROOT / "configs/strategies/registry.json", SOURCE,
                       ROOT / "data/research/model_runs/catalog.json",
                       ROOT / "data/research/formal_model_runs/catalog.json"]
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in canonical_paths}
    with pytest.raises(module.CnX12EvidenceError, match="not the active CN strategy"):
        module.materialize(
            PORTFOLIO, EXPERIMENT, PROMOTION, tmp_path / "source.json",
            tmp_path / "preview", tmp_path / "formal",
            Path("configs/strategies/registry.json"), update_catalogs=update_catalogs,
        )
    # The exact derived source can remain as failed-attempt evidence; no active
    # preview/formal publication or canonical mutation is permitted.
    assert (tmp_path / "source.json").read_bytes() == SOURCE.read_bytes()
    assert not (tmp_path / "preview").exists()
    assert not (tmp_path / "formal").exists()
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in canonical_paths} == before


def test_cn_x1_2_row_evidence_tampering_fails_closed(tmp_path: Path) -> None:
    module = _load()
    payload = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    payload["cost_paths"]["20"]["periods"][0]["net_return"] += 0.01
    tampered = tmp_path / "portfolio.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(module.CnX12EvidenceError, match="summary|hash|drifted"):
        module.build_package(tampered, EXPERIMENT, PROMOTION)


def test_active_bundle_catalogs_match_registry_and_exclude_retired_cn_models() -> None:
    registry = json.loads((ROOT / "configs/strategies/registry.json").read_text(encoding="utf-8"))
    expected = {row["model_version_id"] for row in registry["strategies"]}
    assert len(expected) == 4
    for path in (
        ROOT / "data/research/model_runs/catalog.json",
        ROOT / "data/research/formal_model_runs/catalog.json",
    ):
        catalog = json.loads(path.read_text(encoding="utf-8"))
        ids = [row["model_version_id"] for row in catalog["records"]]
        assert len(ids) == len(set(ids))
        assert set(ids) == expected
        assert "cn_x1_2" not in ids
        assert "cn_x1_1" not in ids
