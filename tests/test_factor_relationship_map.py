from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from src.research.factor_knowledge_registry import FactorCardInput, FactorKnowledgeRegistry
from src.research.factor_relationship_map import build_factor_relationship_map

CONTRACT = Path("configs/factor_knowledge/relationship_map_v1.yaml")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _register(registry_path: Path, factors: list[str]) -> None:
    registry = FactorKnowledgeRegistry(registry_path)
    for factor in factors:
        registry.register_card(
            FactorCardInput(
                stable_factor_key=factor,
                factor_version="1.0.0",
                name=factor,
                canonical_definition=factor,
                information_family="price_trend" if factor != "quality" else "quality",
                update_frequency="daily",
                availability_lag_days=0,
                transformation="rank",
                orientation="higher_is_better",
                neutralization="within_universe",
                thesis=f"test {factor}",
                code_identity="tests/test_factor_relationship_map.py",
                status="candidate",
                source_kind="test_relationship_map",
                source_ref=factor,
            )
        )


def _input_files(root: Path) -> Path:
    factors = ["momentum_a", "momentum_b", "quality"]
    symbols = ["AAA", "BBB", "CCC"]
    score_rows = []
    dates = pd.bdate_range("2025-01-02", periods=40)
    for day_index, day in enumerate(dates):
        for symbol_index, symbol in enumerate(symbols):
            base = float(day_index + symbol_index)
            score_rows.extend(
                [
                    {
                        "date": day.date().isoformat(),
                        "symbol": symbol,
                        "stable_factor_key": "momentum_a",
                        "score": base,
                    },
                    {
                        "date": day.date().isoformat(),
                        "symbol": symbol,
                        "stable_factor_key": "momentum_b",
                        "score": base * 2.0 + 1.0,
                    },
                    {
                        "date": day.date().isoformat(),
                        "symbol": symbol,
                        "stable_factor_key": "quality",
                        "score": float(((day_index * 3 + symbol_index * 7) % 11) - 5),
                    },
                ]
            )
    returns_rows = []
    for index, day in enumerate(dates[:25]):
        momentum_return = (index % 5 - 2) / 100.0
        returns_rows.extend(
            [
                {"date": day.date().isoformat(), "stable_factor_key": "momentum_a", "return": momentum_return},
                {"date": day.date().isoformat(), "stable_factor_key": "momentum_b", "return": momentum_return},
                {"date": day.date().isoformat(), "stable_factor_key": "quality", "return": ((index * 3) % 7 - 3) / 100.0},
            ]
        )
    selection_rows = []
    for index, day in enumerate(dates[:10]):
        momentum_set = {"AAA", "BBB"} if index % 2 == 0 else {"BBB", "CCC"}
        quality_set = {"CCC"} if index % 2 == 0 else {"AAA"}
        for factor, selected_set in {
            "momentum_a": momentum_set,
            "momentum_b": momentum_set,
            "quality": quality_set,
        }.items():
            for symbol in symbols:
                selection_rows.append(
                    {
                        "date": day.date().isoformat(),
                        "stable_factor_key": factor,
                        "symbol": symbol,
                        "selected": symbol in selected_set,
                    }
                )

    paths = {
        "scores": root / "scores.csv",
        "returns": root / "returns.csv",
        "selections": root / "selections.csv",
    }
    pd.DataFrame(score_rows).to_csv(paths["scores"], index=False)
    pd.DataFrame(returns_rows).to_csv(paths["returns"], index=False)
    pd.DataFrame(selection_rows).to_csv(paths["selections"], index=False)
    manifest = {
        "schema_version": "1.0",
        "scope": {
            "market": "us",
            "universe_version": "us_small_pool_v1",
            "benchmark": "QQQ",
            "start_date": dates[0].date().isoformat(),
            "end_date": dates[-1].date().isoformat(),
            "provider_identity": "provider-test-identity",
            "evidence_manifest_hash": "evidence-test-identity",
        },
        "artifacts": {
            kind: {"path": path.name, "sha256": _sha(path)}
            for kind, path in paths.items()
        },
    }
    manifest_path = root / "input_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest_path


def test_builds_redundancy_clusters_and_records_relationships(tmp_path: Path) -> None:
    registry_path = tmp_path / "factor.db"
    _register(registry_path, ["momentum_a", "momentum_b", "quality"])
    manifest_path = _input_files(tmp_path)

    decision = build_factor_relationship_map(
        contract_path=CONTRACT,
        input_manifest_path=manifest_path,
        registry_db=registry_path,
        output_dir=tmp_path / "output",
    )
    payload = json.loads(
        (tmp_path / "output" / "factor_relationships.json").read_text(encoding="utf-8")
    )
    factors = {row["stable_factor_key"]: row for row in payload["factors"]}
    pairs = {(row["left"], row["right"]): row for row in payload["pairs"]}

    assert decision["pair_count"] == 3
    assert decision["redundancy_cluster_count"] == 1
    assert factors["momentum_a"]["redundancy_cluster"] == factors["momentum_b"]["redundancy_cluster"]
    assert factors["quality"]["redundancy_cluster"] == ""
    assert pairs[("momentum_a", "momentum_b")]["score_correlation"] == pytest.approx(1.0)
    assert pairs[("momentum_a", "momentum_b")]["selection_overlap"] == pytest.approx(1.0)


def test_artifact_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    registry_path = tmp_path / "factor.db"
    _register(registry_path, ["momentum_a", "momentum_b", "quality"])
    manifest_path = _input_files(tmp_path)
    with (tmp_path / "scores.csv").open("a", encoding="utf-8") as handle:
        handle.write("\n")

    with pytest.raises(ValueError, match="hash mismatch"):
        build_factor_relationship_map(
            contract_path=CONTRACT,
            input_manifest_path=manifest_path,
            registry_db=registry_path,
            output_dir=tmp_path / "output",
        )


def test_unknown_factor_card_fails_closed(tmp_path: Path) -> None:
    registry_path = tmp_path / "factor.db"
    _register(registry_path, ["momentum_a", "momentum_b"])
    manifest_path = _input_files(tmp_path)

    with pytest.raises(ValueError, match="missing from registry"):
        build_factor_relationship_map(
            contract_path=CONTRACT,
            input_manifest_path=manifest_path,
            registry_db=registry_path,
            output_dir=tmp_path / "output",
        )
