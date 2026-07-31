from __future__ import annotations

from pathlib import Path

import yaml

from src.research.factor_history_backfill import (
    backfill_history_batch,
    load_history_cards,
)
from src.research.factor_knowledge_registry import FactorKnowledgeRegistry

INVENTORY = Path("configs/factor_knowledge/historical_factor_cards_v1.yaml")


def test_inventory_is_unique_and_truth_bounded() -> None:
    payload = load_history_cards(INVENTORY)
    cards = payload["cards"]
    keys = [row["stable_factor_key"] for row in cards]

    assert payload["truth_boundary"] == {
        "research_only": True,
        "trade_ready": False,
        "reserved_performance_opened": False,
        "standalone_support_implied": False,
    }
    assert len(cards) == 25
    assert len(keys) == len(set(keys))
    assert {row["status"] for row in cards} == {
        "legacy_unverified",
        "rejected",
        "market_specific_clue",
        "retired",
        "data_blocked",
    }


def test_backfill_is_deterministic_idempotent_and_non_authoritative(tmp_path: Path) -> None:
    registry = FactorKnowledgeRegistry(tmp_path / "factor_registry.db")
    first = backfill_history_batch(registry, INVENTORY)
    second = backfill_history_batch(registry, INVENTORY)

    assert first["card_count"] == 25
    assert second["card_count"] == 25
    assert first["inventory_sha256"] == second["inventory_sha256"]
    assert first["status_counts"] == {
        "data_blocked": 2,
        "legacy_unverified": 5,
        "market_specific_clue": 6,
        "rejected": 10,
        "retired": 2,
    }
    assert first["authoritative_evidence_created"] == 0
    assert first["reserved_performance_opened"] is False
    assert first["trade_ready"] is False

    cards = registry.list_cards()
    evidence = registry.list_evidence()
    report = registry.evidence_completeness_report()
    assert len(cards) == 25
    assert len(evidence) == 25
    assert report["factor_card_count"] == 25
    assert report["evidence_count"] == 25
    assert report["authoritative_evidence_count"] == 0
    assert report["incomplete_evidence_count"] == 25


def test_high_value_historical_lessons_are_preserved(tmp_path: Path) -> None:
    registry = FactorKnowledgeRegistry(tmp_path / "factor_registry.db")
    backfill_history_batch(registry, INVENTORY)
    cards = {row["stable_factor_key"]: row for row in registry.list_cards()}

    assert cards["mom_5d"]["status"] == "legacy_unverified"
    assert cards["lightgbm_lambdarank_ohlcv"]["status"] == "retired"
    assert cards["xgboost_rank_ndcg_ohlcv"]["status"] == "retired"
    assert cards["rsi_strength_10"]["status"] == "market_specific_clue"
    assert cards["basket_relative_momentum_63"]["status"] == "market_specific_clue"
    assert cards["security_relative_momentum_63"]["status"] == "rejected"
    assert cards["qqq_market_regime_gate"]["status"] == "rejected"
    assert cards["revenue_growth_acceleration"]["status"] == "data_blocked"

    tree_evidence = registry.list_evidence(cards["lightgbm_lambdarank_ohlcv"]["card_id"])
    assert len(tree_evidence) == 1
    assert tree_evidence[0]["failure_class"] == "family_level_stop"
    assert "PIT" in tree_evidence[0]["lessons_learned"]


def test_inventory_yaml_has_no_hidden_supported_or_trade_ready_claim() -> None:
    payload = yaml.safe_load(INVENTORY.read_text(encoding="utf-8"))
    rendered = INVENTORY.read_text(encoding="utf-8").lower()

    assert payload["truth_boundary"]["trade_ready"] is False
    assert "status: supported" not in rendered
    assert "trade_ready: true" not in rendered
    assert "reserved_performance_opened: true" not in rendered
