from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

from src.research.factor_knowledge_registry import FactorCardInput, FactorKnowledgeRegistry
from src.research.low_turnover_multifactor_pipeline import (
    run_low_turnover_multifactor_pipeline,
)

CONTRACT = Path("configs/factors/us_low_turnover_multifactor_v1.yaml")
POOL = Path("configs/pools/us_small_pool_v1.yaml")
FACTOR_KEYS = [
    "revenue_growth_acceleration",
    "gross_margin_yoy_change",
    "basket_relative_momentum_63",
    "basket_drawdown_from_63d_high",
]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pool() -> dict:
    return yaml.safe_load(POOL.read_text(encoding="utf-8"))


def _membership() -> tuple[dict[str, str], list[str]]:
    pool = _pool()
    basket_by_symbol = {
        str(symbol): str(basket)
        for basket, meta in pool["baskets"].items()
        for symbol in meta["symbols"]
    }
    return basket_by_symbol, list(pool["references"])


def _register_cards(path: Path, *, data_blocked: bool = False) -> None:
    registry = FactorKnowledgeRegistry(path)
    families = {
        "revenue_growth_acceleration": "growth",
        "gross_margin_yoy_change": "quality",
        "basket_relative_momentum_63": "price_trend",
        "basket_drawdown_from_63d_high": "risk",
    }
    for key in FACTOR_KEYS:
        registry.register_card(
            FactorCardInput(
                stable_factor_key=key,
                factor_version="1.0.0",
                name=key,
                canonical_definition=key,
                information_family=families[key],
                update_frequency="monthly",
                availability_lag_days=0,
                transformation="percentile",
                orientation="higher_is_better",
                neutralization="within_scope",
                thesis=f"test {key}",
                code_identity="tests/test_low_turnover_multifactor.py",
                status=(
                    "data_blocked"
                    if data_blocked and key == "revenue_growth_acceleration"
                    else "candidate"
                ),
                source_kind="test_multifactor",
                source_ref=key,
            )
        )


def _write_artifact(folder: Path, name: str, payload: dict) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    manifest = {
        "schema_version": "1.0",
        "manifest_identity_sha256": hashlib.sha256(name.encode()).hexdigest(),
        "outputs": {name: _sha(path)},
    }
    (folder / "evidence_manifest.json").write_text(
        json.dumps(manifest, sort_keys=True), encoding="utf-8"
    )
    return path


def _fixtures(root: Path, *, redundant: bool = False) -> dict[str, Path]:
    basket_by_symbol, references = _membership()
    dates = pd.bdate_range("2025-01-02", periods=140)
    evaluation_dates = list(dates[::20])
    if evaluation_dates[-1] != dates[-1]:
        evaluation_dates.append(dates[-1])

    price_rows = []
    for symbol_index, symbol in enumerate([*basket_by_symbol, *references]):
        for day_index, day in enumerate(dates):
            price_rows.append(
                {
                    "date": day.date().isoformat(),
                    "symbol": symbol,
                    "close": 50.0 + symbol_index + day_index * 0.2,
                }
            )
    prices_path = root / "prices.csv"
    pd.DataFrame(price_rows).to_csv(prices_path, index=False)

    fundamental_rows = []
    symbols_by_basket: dict[str, list[str]] = {}
    for symbol, basket in basket_by_symbol.items():
        symbols_by_basket.setdefault(basket, []).append(symbol)
    for day in evaluation_dates:
        for basket, symbols in symbols_by_basket.items():
            for rank, symbol in enumerate(sorted(symbols)):
                percentile = 1.0 - rank / max(1, len(symbols))
                for factor in FACTOR_KEYS[:2]:
                    fundamental_rows.append(
                        {
                            "date": day.date().isoformat(),
                            "symbol": symbol,
                            "stable_factor_key": factor,
                            "percentile": percentile,
                            "eligible": True,
                            "basket": basket,
                        }
                    )
    fundamental_path = _write_artifact(
        root / "fundamental",
        "factor_scores.json",
        {"schema_version": "1.0", "rows": fundamental_rows},
    )

    basket_rows = []
    for day in evaluation_dates:
        for basket_index, basket in enumerate(sorted(symbols_by_basket)):
            basket_rows.append(
                {
                    "date": day.date().isoformat(),
                    "basket": basket,
                    "median_relative_momentum_63_vs_benchmark_percentile": (
                        0.55 + basket_index * 0.05
                    ),
                    "median_drawdown_from_63d_high_percentile": (
                        0.60 + basket_index * 0.04
                    ),
                }
            )
    basket_path = _write_artifact(
        root / "basket",
        "basket_score_history.json",
        {"schema_version": "1.0", "rows": basket_rows},
    )

    pairs = []
    for left_index, left in enumerate(FACTOR_KEYS):
        for right in FACTOR_KEYS[left_index + 1 :]:
            pairs.append(
                {
                    "left": left,
                    "right": right,
                    "score_correlation": 0.1,
                    "return_correlation": 0.1,
                    "selection_overlap": 0.2,
                    "redundancy_cluster": "",
                }
            )
    factors = []
    for key in FACTOR_KEYS:
        cluster = "redundancy_cluster_01" if redundant and key in FACTOR_KEYS[:2] else ""
        factors.append(
            {
                "stable_factor_key": key,
                "redundancy_cluster": cluster,
            }
        )
    relationship_folder = root / "relationship"
    relationship_folder.mkdir(parents=True, exist_ok=True)
    relationship_path = relationship_folder / "factor_relationships.json"
    relationship_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "relationship_contract_id": "factor_relationship_map_v1",
                "scope": {
                    "market": "us",
                    "universe_version": "us_small_pool_v1",
                },
                "factors": factors,
                "pairs": pairs,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    relationship_manifest = {
        "schema_version": "1.0",
        "manifest_identity_sha256": hashlib.sha256(b"relationship").hexdigest(),
        "outputs": {relationship_path.name: _sha(relationship_path)},
    }
    (relationship_folder / "evidence_manifest.json").write_text(
        json.dumps(relationship_manifest, sort_keys=True), encoding="utf-8"
    )
    return {
        "prices": prices_path,
        "fundamental": fundamental_path,
        "basket": basket_path,
        "relationship": relationship_path,
    }


def _run(tmp_path: Path, *, data_blocked: bool = False, redundant: bool = False):
    registry_path = tmp_path / "factor.db"
    _register_cards(registry_path, data_blocked=data_blocked)
    paths = _fixtures(tmp_path, redundant=redundant)
    decision = run_low_turnover_multifactor_pipeline(
        contract_path=CONTRACT,
        fundamental_scores_path=paths["fundamental"],
        basket_scores_path=paths["basket"],
        relationship_map_path=paths["relationship"],
        prices_csv=paths["prices"],
        registry_db=registry_path,
        output_dir=tmp_path / "output",
    )
    return decision, registry_path, paths


def test_builds_equal_weight_low_turnover_diagnostic_candidate(tmp_path: Path) -> None:
    decision, registry_path, _ = _run(tmp_path)

    assert decision["decision"] == "multifactor_diagnostic_candidate_ready"
    assert decision["relationship_gate_passed"] is True
    assert decision["information_family_count"] == 4
    assert decision["turnover_diagnostics"]["turnover_gate_passed"] is True
    assert len(decision["combination_usage_ids"]) == 4
    assert decision["trade_ready"] is False
    assert decision["composite_card_id"]
    registry = FactorKnowledgeRegistry(registry_path)
    assert registry.get_card_by_key("us_low_turnover_multifactor_v1") is not None
    portfolio = json.loads(
        (tmp_path / "output" / "portfolio_history.json").read_text(encoding="utf-8")
    )
    assert portfolio["rows"]
    assert max(len(row["selected_symbols"]) for row in portfolio["rows"]) > 0
    scores = json.loads(
        (tmp_path / "output" / "multifactor_scores.json").read_text(encoding="utf-8")
    )
    assert all("score" in row and "percentile" in row for row in scores["rows"])


def test_data_blocked_card_keeps_candidate_diagnostic_and_incomplete(tmp_path: Path) -> None:
    decision, _, _ = _run(tmp_path, data_blocked=True)

    assert decision["decision"] == (
        "multifactor_diagnostic_scores_ready_registry_evidence_incomplete"
    )
    assert decision["registry_incomplete_statuses"] == {
        "revenue_growth_acceleration": "data_blocked"
    }


def test_shared_redundancy_cluster_fails_closed(tmp_path: Path) -> None:
    registry_path = tmp_path / "factor.db"
    _register_cards(registry_path)
    paths = _fixtures(tmp_path, redundant=True)

    with pytest.raises(ValueError, match="share redundancy clusters"):
        run_low_turnover_multifactor_pipeline(
            contract_path=CONTRACT,
            fundamental_scores_path=paths["fundamental"],
            basket_scores_path=paths["basket"],
            relationship_map_path=paths["relationship"],
            prices_csv=paths["prices"],
            registry_db=registry_path,
            output_dir=tmp_path / "output",
        )


def test_tampered_factor_artifact_fails_closed(tmp_path: Path) -> None:
    registry_path = tmp_path / "factor.db"
    _register_cards(registry_path)
    paths = _fixtures(tmp_path)
    with paths["fundamental"].open("a", encoding="utf-8") as handle:
        handle.write("\n")

    with pytest.raises(ValueError, match="artifact hash mismatch"):
        run_low_turnover_multifactor_pipeline(
            contract_path=CONTRACT,
            fundamental_scores_path=paths["fundamental"],
            basket_scores_path=paths["basket"],
            relationship_map_path=paths["relationship"],
            prices_csv=paths["prices"],
            registry_db=registry_path,
            output_dir=tmp_path / "output",
        )


def test_tampered_relationship_map_fails_closed(tmp_path: Path) -> None:
    registry_path = tmp_path / "factor.db"
    _register_cards(registry_path)
    paths = _fixtures(tmp_path)
    with paths["relationship"].open("a", encoding="utf-8") as handle:
        handle.write("\n")

    with pytest.raises(ValueError, match="relationship map hash"):
        run_low_turnover_multifactor_pipeline(
            contract_path=CONTRACT,
            fundamental_scores_path=paths["fundamental"],
            basket_scores_path=paths["basket"],
            relationship_map_path=paths["relationship"],
            prices_csv=paths["prices"],
            registry_db=registry_path,
            output_dir=tmp_path / "output",
        )
