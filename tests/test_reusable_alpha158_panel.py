from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src.factors.reusable_panel import (
    ReusableFactorPanelError,
    build_reusable_alpha158_panel,
)


@dataclass
class CountingEvaluator:
    calls: int = 0

    def evaluate(self, *, symbols, expressions, start, end):
        self.calls += 1
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


class FailingEvaluator:
    def evaluate(self, *, symbols, expressions, start, end):
        raise AssertionError("exact reusable panel should not rematerialize factors")


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    pool = root / "pool.yaml"
    pool.write_text(
        yaml.safe_dump(
            {
                "pool_id": "test_pool",
                "market": "us",
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
                "field_policy": {"allowed_vwap_semantics": ["reported_vwap"]},
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
    (provider / "features").mkdir(parents=True)
    (provider / "provider_manifest.json").write_text(
        json.dumps({"provider_identity_sha256": "a" * 64}),
        encoding="utf-8",
    )
    (provider / "source_role_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "role": "canonical",
                "canonical_training_eligible": True,
                "validation_only": False,
                "source_providers": ["public_primary"],
                "field_semantics": {"vwap": "reported_vwap"},
            }
        ),
        encoding="utf-8",
    )
    for symbol in ("aaa", "bbb"):
        directory = provider / "features" / symbol
        directory.mkdir(parents=True)
        for field in ("open", "high", "low", "close", "vwap", "volume"):
            (directory / f"{field}.day.bin").write_bytes(b"fixture")
    return root, contract, provider


def _build(
    *,
    root: Path,
    contract: Path,
    provider: Path,
    output: Path,
    evaluator,
):
    return build_reusable_alpha158_panel(
        root=root,
        contract_path=contract,
        provider_uri=provider,
        market="us",
        start="2024-01-02",
        cutoff="2024-05-31",
        output_root=output,
        evaluator=evaluator,
    )


def test_exact_panel_is_reused_without_factor_evaluation(tmp_path: Path) -> None:
    root, contract, provider = _fixture(tmp_path)
    output = tmp_path / "panel"
    evaluator = CountingEvaluator()
    first = _build(
        root=root,
        contract=contract,
        provider=provider,
        output=output,
        evaluator=evaluator,
    )
    assert evaluator.calls == 2
    assert len(first["input_identity_sha256"]) == 64

    second = _build(
        root=root,
        contract=contract,
        provider=provider,
        output=output,
        evaluator=FailingEvaluator(),
    )
    assert second == first


def test_identical_rebuilds_have_identical_compressed_file_hashes(tmp_path: Path) -> None:
    root, contract, provider = _fixture(tmp_path)
    first = _build(
        root=root,
        contract=contract,
        provider=provider,
        output=tmp_path / "panel-a",
        evaluator=CountingEvaluator(),
    )
    second = _build(
        root=root,
        contract=contract,
        provider=provider,
        output=tmp_path / "panel-b",
        evaluator=CountingEvaluator(),
    )
    assert first["input_identity_sha256"] == second["input_identity_sha256"]
    assert first["files"] == second["files"]


def test_tampered_exact_panel_fails_closed_instead_of_rebuilding(tmp_path: Path) -> None:
    root, contract, provider = _fixture(tmp_path)
    output = tmp_path / "panel"
    manifest = _build(
        root=root,
        contract=contract,
        provider=provider,
        output=output,
        evaluator=CountingEvaluator(),
    )
    relative = next(name for name in manifest["files"] if name.startswith("panels/"))
    with (output / relative).open("ab") as handle:
        handle.write(b"tamper")

    with pytest.raises(ReusableFactorPanelError, match="hash mismatch"):
        _build(
            root=root,
            contract=contract,
            provider=provider,
            output=output,
            evaluator=FailingEvaluator(),
        )
