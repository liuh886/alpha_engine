from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

from src.artifacts.model_run_bundle_v2 import canonical_json_bytes


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
PREVIEW = ROOT / (
    "data/research/model_runs/cn_ranker/cn_x1_2/"
    "cn_x1_2-through-2026_06_30"
)
FORMAL = ROOT / (
    "data/research/formal_model_runs/cn_ranker/cn_x1_2/"
    "cn_x1_2-through-2026_06_30"
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


def _assert_same_tree(left: Path, right: Path) -> None:
    left_files = sorted(path.relative_to(left) for path in left.rglob("*") if path.is_file())
    right_files = sorted(path.relative_to(right) for path in right.rglob("*") if path.is_file())
    assert left_files == right_files
    for path in left_files:
        assert (left / path).read_bytes() == (right / path).read_bytes(), path


@pytest.mark.approved_skip(
    reason="known evidence-chain defect: the committed CN x1.2 user-directed "
    "promotion receipt (4cbdd288) records sha256 dcdf929e… for "
    "challenger_portfolio_evidence.json while the committed file hashes to "
    "1b6ef673…; promotion-bound evidence must not be rewritten locally and "
    "the bundle requires governed re-publication"
)
def test_cn_x1_2_complete_bundle_is_exactly_reproducible(tmp_path: Path) -> None:
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

    result = module.materialize(
        PORTFOLIO,
        EXPERIMENT,
        PROMOTION,
        tmp_path / "source.json",
        tmp_path / "preview",
        tmp_path / "formal",
        Path("configs/strategies/registry.json"),
        update_catalogs=False,
    )
    assert result["preregistered_gates_supported"] is False
    generated_preview = (
        tmp_path
        / "preview/cn_ranker/cn_x1_2/cn_x1_2-through-2026_06_30"
    )
    generated_formal = (
        tmp_path
        / "formal/cn_ranker/cn_x1_2/cn_x1_2-through-2026_06_30"
    )
    _assert_same_tree(generated_preview, PREVIEW)
    _assert_same_tree(generated_formal, FORMAL)


def test_cn_x1_2_row_evidence_tampering_fails_closed(tmp_path: Path) -> None:
    module = _load()
    payload = json.loads(PORTFOLIO.read_text(encoding="utf-8"))
    payload["cost_paths"]["20"]["periods"][0]["net_return"] += 0.01
    tampered = tmp_path / "portfolio.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(module.CnX12EvidenceError, match="summary|hash|drifted"):
        module.build_package(tampered, EXPERIMENT, PROMOTION)


def test_active_bundle_catalogs_publish_cn_x1_2_not_cn_x1_1() -> None:
    for path in (
        ROOT / "data/research/model_runs/catalog.json",
        ROOT / "data/research/formal_model_runs/catalog.json",
    ):
        catalog = json.loads(path.read_text(encoding="utf-8"))
        ids = [row["model_version_id"] for row in catalog["records"]]
        assert "cn_x1_2" in ids
        assert "cn_x1_1" not in ids
