from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.factors.panel import build_alpha158_panel


@dataclass
class FakeEvaluator:
    def evaluate(self, *, symbols, expressions, start, end):
        dates = pd.bdate_range(start, periods=90)
        index = pd.MultiIndex.from_product(
            [symbols, dates], names=["instrument", "datetime"]
        )
        values = np.empty((len(index), len(expressions)), dtype=float)
        for column in range(len(expressions)):
            values[:, column] = (
                np.arange(len(index), dtype=float) * (column + 1) / 10000.0
            )
        return pd.DataFrame(values, index=index, columns=list(expressions))


def _fixture(
    tmp_path: Path,
    *,
    include_vwap: bool,
    role: str = "canonical",
    training_eligible: bool = True,
    validation_only: bool = False,
    source_providers: list[str] | None = None,
    vwap_semantics: str = "reported_vwap",
) -> tuple[Path, Path, Path]:
    root = tmp_path / "repo"
    pool = root / "pool.yaml"
    pool.parent.mkdir(parents=True, exist_ok=True)
    pool.write_text(
        yaml.safe_dump(
            {
                "pool_id": "test_pool",
                "candidate_count": 2,
                "symbols": ["AAA", "BBB"],
            }
        ),
        encoding="utf-8",
    )
    contract = root / "contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "catalog": {"expected_factor_count": 158},
                "markets": {
                    "us": {
                        "pool_id": "test_pool",
                        "pool_spec": "pool.yaml",
                        "expected_symbols": 2,
                    }
                },
                "required_provider_fields": [
                    "open",
                    "high",
                    "low",
                    "close",
                    "vwap",
                    "volume",
                ],
                "field_policy": {
                    "allowed_vwap_semantics": [
                        "reported_vwap",
                        "reported_turnover_divided_by_reported_volume",
                    ]
                },
                "provider_role_policy": {
                    "source_role_manifest": "source_role_manifest.json",
                    "canonical_role_required": True,
                    "canonical_training_eligible_required": True,
                    "validation_only_provider_forbidden": True,
                    "validation_only_sources": ["tiingo", "polygon", "tushare"],
                },
                "quality": {
                    "minimum_post_warmup_rows": 20,
                    "near_constant_unique_ratio_threshold": 0.001,
                },
            }
        ),
        encoding="utf-8",
    )
    provider = tmp_path / "provider"
    (provider / "features").mkdir(parents=True, exist_ok=True)
    (provider / "provider_manifest.json").write_text(
        json.dumps({"provider_identity_sha256": "a" * 64}),
        encoding="utf-8",
    )
    (provider / "source_role_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "role": role,
                "canonical_training_eligible": training_eligible,
                "validation_only": validation_only,
                "source_providers": source_providers or ["public_primary"],
                "field_semantics": {"vwap": vwap_semantics},
            }
        ),
        encoding="utf-8",
    )
    fields = ["open", "high", "low", "close", "volume"]
    if include_vwap:
        fields.append("vwap")
    for symbol in ("AAA", "BBB"):
        directory = provider / "features" / symbol.lower()
        directory.mkdir(parents=True, exist_ok=True)
        for field in fields:
            (directory / f"{field}.day.bin").write_bytes(b"fixture")
    return root, contract, provider


def test_alpha158_panel_writes_exact_factor_order_and_quality(tmp_path: Path):
    root, contract, provider = _fixture(tmp_path, include_vwap=True)
    output = tmp_path / "output"
    manifest = build_alpha158_panel(
        root=root,
        contract_path=contract,
        provider_uri=provider,
        market="us",
        start="2024-01-02",
        cutoff="2024-05-31",
        output_root=output,
        evaluator=FakeEvaluator(),
    )
    assert manifest["status"] == "ready"
    assert manifest["factor_count"] == 158
    assert manifest["ready_symbol_count"] == 2
    assert manifest["source_role"]["role"] == "canonical"
    panel = pd.read_csv(output / "panels" / "AAA.csv.gz")
    assert panel.shape[1] == 159
    assert panel.columns[0] == "date"
    quality = pd.read_csv(output / "factor_quality.csv.gz")
    assert len(quality) == 2 * 158
    assert set(quality["status"]) == {"ready"}
    assert manifest["trade_ready"] is False


def test_alpha158_panel_blocks_without_true_vwap(tmp_path: Path):
    root, contract, provider = _fixture(tmp_path, include_vwap=False)
    output = tmp_path / "output"
    manifest = build_alpha158_panel(
        root=root,
        contract_path=contract,
        provider_uri=provider,
        market="us",
        start="2024-01-02",
        cutoff="2024-05-31",
        output_root=output,
        evaluator=FakeEvaluator(),
    )
    assert manifest["status"] == "blocked"
    assert manifest["invalid_symbols"] == ["AAA", "BBB"]
    assert "true vwap" in manifest["blocker"]
    assert not (output / "panels" / "AAA.csv.gz").exists()


def test_alpha158_panel_blocks_validation_only_provider(tmp_path: Path):
    root, contract, provider = _fixture(
        tmp_path,
        include_vwap=True,
        role="validator",
        training_eligible=False,
        validation_only=True,
        source_providers=["polygon"],
    )
    output = tmp_path / "output"
    manifest = build_alpha158_panel(
        root=root,
        contract_path=contract,
        provider_uri=provider,
        market="us",
        start="2024-01-02",
        cutoff="2024-05-31",
        output_root=output,
        evaluator=FakeEvaluator(),
    )
    assert manifest["status"] == "blocked"
    assert "not canonical" in manifest["blocker"]
    assert not (output / "panels" / "AAA.csv.gz").exists()


def test_alpha158_panel_blocks_missing_source_role_manifest(tmp_path: Path):
    root, contract, provider = _fixture(tmp_path, include_vwap=True)
    (provider / "source_role_manifest.json").unlink()
    manifest = build_alpha158_panel(
        root=root,
        contract_path=contract,
        provider_uri=provider,
        market="us",
        start="2024-01-02",
        cutoff="2024-05-31",
        output_root=tmp_path / "output",
        evaluator=FakeEvaluator(),
    )
    assert manifest["status"] == "blocked"
    assert "source-role manifest" in manifest["blocker"]
