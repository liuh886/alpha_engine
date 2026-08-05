from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/promote_cn_x1_1_formal.py"
EVIDENCE = ROOT / "data/research/cn_x1_1_regime_gated_candidate_v1"
FORMAL_ROOT = ROOT / "data/research/formal_backtests"


def _load() -> ModuleType:
    name = "promote_cn_x1_1_formal"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _seed_formal_root(target: Path) -> None:
    target.mkdir(parents=True)
    shutil.copy2(FORMAL_ROOT / "catalog.json", target / "catalog.json")
    shutil.copy2(FORMAL_ROOT / "freshness.json", target / "freshness.json")


def test_committed_cn_x1_1_package_is_complete_and_reproducible(tmp_path: Path) -> None:
    module = _load()
    first = tmp_path / "first"
    second = tmp_path / "second"
    _seed_formal_root(first)
    _seed_formal_root(second)

    receipt_one = module.promote(first, EVIDENCE)
    receipt_two = module.promote(second, EVIDENCE)

    assert receipt_one["package_sha256"] == receipt_two["package_sha256"]
    assert (first / "cn_x1_1.json").read_bytes() == (second / "cn_x1_1.json").read_bytes()
    assert (first / "catalog.json").read_bytes() == (second / "catalog.json").read_bytes()
    assert (first / "freshness.json").read_bytes() == (second / "freshness.json").read_bytes()
    assert (first / "cn_x1_1.json").read_bytes() == (
        FORMAL_ROOT / "cn_x1_1.json"
    ).read_bytes()

    package = json.loads((first / "cn_x1_1.json").read_text(encoding="utf-8"))
    assert package["model_id"] == "cn_x1_1"
    assert package["display_name"] == "CN x1.1"
    assert package["publication_status"] == "accepted_formal_baseline"
    assert package["evidence_completeness"]["status"] == "complete"
    assert package["evidence_completeness"]["missing"] == []
    assert package["research_only"] is True
    assert package["trade_ready"] is False
    assert package["evidence_cutoff"] == "2026-08-03"
    assert len(package["report"]) == 102
    assert len(package["positions"]) == 252
    assert len(package["trades"]) == 372
    assert package["metrics"]["Historical Relative Excess Return"] == pytest.approx(
        0.5493370449
    )
    assert package["metrics"]["Compounded Relative Excess Return"] == pytest.approx(
        0.5922541247895701
    )
    assert package["metrics"]["Max Drawdown"] == pytest.approx(
        -0.37059032672209047
    )


def test_frozen_evidence_tampering_fails_closed(tmp_path: Path) -> None:
    module = _load()
    evidence = tmp_path / "evidence"
    shutil.copytree(EVIDENCE, evidence)
    holdings = evidence / "holdings.csv"
    holdings.write_text(
        holdings.read_text(encoding="utf-8").replace("三花智控", "tampered", 1),
        encoding="utf-8",
    )
    with pytest.raises(module.PromotionError, match="hash mismatch"):
        module.verify_evidence(evidence)


def test_catalog_replaces_cn_x1_0_with_cn_x1_1(tmp_path: Path) -> None:
    module = _load()
    target = tmp_path / "formal"
    _seed_formal_root(target)
    module.promote(target, EVIDENCE)
    catalog = json.loads((target / "catalog.json").read_text(encoding="utf-8"))
    ids = [row["model_id"] for row in catalog["records"]]
    assert "cn_x1_0" not in ids
    assert ids == [
        "qqqi_qqq_tqqq_v4_2",
        "us_x1_1",
        "cn_x1_1",
        "byd_dividend_sleeve_v1_0",
    ]
    freshness = json.loads((target / "freshness.json").read_text(encoding="utf-8"))
    assert "cn_x1_0" not in freshness["required_models"]
    assert "cn_x1_1" in freshness["required_models"]
