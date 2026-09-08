from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

from src.artifacts.formal_evidence_standard import validate_formal_evidence_bundle
from src.governance.active_strategy_catalog import (
    assert_formal_catalog_matches_active_strategies,
    load_active_strategy_catalog,
)


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/publish_cn_27_v1_3_user_directed.py"
PROMOTION = ROOT / "data/research/experiment_receipts/cn_27_v1_3_user_directed_promotion_v1.json"
PUBLICATION = ROOT / "data/research/experiment_receipts/cn_27_v1_3_formal_publication_v1.json"
FORMAL_ROOT = ROOT / "data/research/formal_model_runs"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("publish_cn_27_v1_3_user_directed", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_promotion_retains_failed_gates_and_pending_prospective_status() -> None:
    module = _load_script()
    receipt = module.build_promotion_receipt()
    failed = receipt["preregistered_gate_result"]
    assert failed["supported"] is False
    assert failed["passed"] == 19
    assert failed["total"] == 21
    assert [row["gate"] for row in failed["failed_gates"]] == [
        "timing_perturbation_sharpe",
        "bootstrap_p05",
    ]
    assert receipt["prospective_validation"]["status"] == "pending"
    assert receipt["prospective_validation"]["gate_passed"] is False
    assert receipt["research_only"] is True
    assert receipt["trade_ready"] is False


def test_committed_cn27_publication_is_native_and_catalog_bound() -> None:
    active = load_active_strategy_catalog(ROOT / "configs/strategies/registry.json")
    catalog = json.loads((FORMAL_ROOT / "catalog.json").read_text(encoding="utf-8"))
    assert_formal_catalog_matches_active_strategies(catalog, active)
    record = next(row for row in catalog["records"] if row["model_version_id"] == "cn_27_v1_3")
    run_dir = FORMAL_ROOT / Path(record["manifest_path"]).parent
    validate_formal_evidence_bundle(run_dir)
    lineage = json.loads((run_dir / "lineage.json").read_text(encoding="utf-8"))
    assert lineage["historical_evidence_recomputed"] is True
    assert lineage["source_evidence"]["exact_historical_reproduction"] is True
    assert lineage["source_evidence"]["preregistered_gates_supported"] is False
    assert lineage["source_evidence"]["prospective_gate_status"] == "pending"
    assert lineage["source_evidence"]["selected_pool_readiness_claimed"] is False


def test_publication_receipts_preserve_research_boundary() -> None:
    promotion = json.loads(PROMOTION.read_text(encoding="utf-8"))
    publication = json.loads(PUBLICATION.read_text(encoding="utf-8"))
    assert promotion["decision"] == "promoted_by_explicit_user_governance_exception"
    assert publication["status"] == "published_formal_research_baseline"
    assert publication["prospective_gate_status"] == "pending"
    assert publication["preregistered_gates_supported"] is False
    assert publication["research_only"] is True
    assert publication["trade_ready"] is False
