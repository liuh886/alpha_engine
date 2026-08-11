from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.decision_support.shadow_decision_desk import build_shadow_decision_ticket
from src.research.factor_knowledge_registry import FactorCardInput, FactorKnowledgeRegistry


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _build_rotation_artifacts(
    root: Path,
    *,
    as_of: str = "2026-07-31",
    trade_ready: bool = False,
    include_future: bool = False,
    a_weight: float = 0.50,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    decision = {
        "schema_version": "1.0",
        "experiment_id": "us_shadow_fixture",
        "market": "us",
        "research_only": True,
        "trade_ready": trade_ready,
        "performance_evaluated": False,
        "reserved_performance_opened": False,
    }
    pool = {
        "schema_version": "1.0",
        "pool_id": "us_small_pool_v1",
        "candidate_count": 4,
        "basket_count": 2,
        "membership_identity_sha256": "pool-membership-001",
    }
    baskets = {
        "schema_version": "1.0",
        "rows": [
            {
                "date": as_of,
                "basket": "ai_infrastructure",
                "selected": True,
                "composite_percentile": 0.90,
                "breadth_above_sma50": 0.75,
                "median_relative_momentum_63_vs_benchmark": 0.12,
                "reason_codes": ["BASKET_SELECTED"],
            },
            {
                "date": as_of,
                "basket": "defensive",
                "selected": False,
                "composite_percentile": 0.40,
                "breadth_above_sma50": 0.50,
                "median_relative_momentum_63_vs_benchmark": -0.02,
                "reason_codes": ["BASKET_COMPOSITE_BELOW_GATE"],
            },
        ],
    }
    securities = {
        "schema_version": "1.0",
        "rows": [
            {
                "date": as_of,
                "basket": "ai_infrastructure",
                "symbol": "AAA",
                "state": "ENTER",
                "security_composite_percentile": 0.90,
                "reason_codes": ["SECURITY_SELECTED_WITHIN_BASKET"],
            },
            {
                "date": as_of,
                "basket": "ai_infrastructure",
                "symbol": "BBB",
                "state": "REDUCE",
                "security_composite_percentile": 0.70,
                "reason_codes": ["SECURITY_SELECTED_WITHIN_BASKET"],
            },
            {
                "date": as_of,
                "basket": "defensive",
                "symbol": "CCC",
                "state": "EXIT",
                "security_composite_percentile": 0.20,
                "reason_codes": ["SECURITY_ABSOLUTE_STATE_INELIGIBLE"],
            },
            {
                "date": as_of,
                "basket": "defensive",
                "symbol": "DDD",
                "state": "WATCH",
                "security_composite_percentile": 0.50,
                "reason_codes": ["SECURITY_NOT_SELECTED_SCORE_ORDER"],
            },
        ],
    }
    rotations = {
        "schema_version": "1.0",
        "rows": [
            {
                "date": as_of,
                "actionable_from": "2026-08-03",
                "market": "us",
                "benchmark": "QQQ",
                "risk_on": True,
                "market_regime": "RISK_ON",
                "selected_baskets": ["ai_infrastructure"],
                "selected_symbols_by_basket": {},
                "reason_codes": ["ROTATION_SELECTION_COMPLETED"],
            }
        ],
    }
    portfolios = {
        "schema_version": "1.0",
        "rows": [
            {
                "date": as_of,
                "actionable_from": "2026-08-03",
                "market": "us",
                "benchmark": "QQQ",
                "risk_on": True,
                "market_regime": "RISK_ON",
                "selected_baskets": ["ai_infrastructure"],
                "positions": [
                    {
                        "basket": "ai_infrastructure",
                        "symbol": "AAA",
                        "state": "ENTER",
                        "target_weight": a_weight,
                        "state_reason_codes": ["ENTER_BREAKOUT_CONFIRMED"],
                    },
                    {
                        "basket": "ai_infrastructure",
                        "symbol": "BBB",
                        "state": "REDUCE",
                        "target_weight": 0.25,
                        "state_reason_codes": ["REDUCE_TREND_WEAKENING"],
                    },
                ],
                "gross_exposure": a_weight + 0.25,
                "cash_weight": 1.0 - a_weight - 0.25,
                "reason_codes": ["PORTFOLIO_ROTATION_ACTIVE"],
            }
        ],
    }
    if include_future:
        future = dict(securities["rows"][0])
        future["date"] = "2026-08-01"
        securities["rows"].append(future)

    payloads = {
        "decision.json": decision,
        "pool_identity.json": pool,
        "basket_score_history.json": baskets,
        "security_score_history.json": securities,
        "rotation_history.json": rotations,
        "portfolio_state_history.json": portfolios,
    }
    for filename, payload in payloads.items():
        _write_json(root / filename, payload)
    manifest = {
        "schema_version": "1.0",
        "market": "us",
        "manifest_identity_sha256": "rotation-manifest-001",
        "outputs": {filename: _sha(root / filename) for filename in payloads},
    }
    _write_json(root / "evidence_manifest.json", manifest)
    return root


def _build_registry(db_path: Path) -> None:
    registry = FactorKnowledgeRegistry(db_path)
    registry.register_card(
        FactorCardInput(
            stable_factor_key="revenue_growth_acceleration",
            factor_version="1.0",
            name="Revenue growth acceleration",
            canonical_definition="latest yoy growth minus prior yoy growth",
            information_family="growth",
            update_frequency="quarterly",
            availability_lag_days=1,
            transformation="within_basket_percentile_rank",
            orientation="higher_is_better",
            neutralization="within_primary_basket",
            thesis="Operating acceleration may persist.",
            code_identity="factor:growth-acceleration-v1",
            status="candidate",
            source_kind="shadow-test",
            source_ref="shadow-test:growth-card",
        )
    )
    registry.register_card(
        FactorCardInput(
            stable_factor_key="security_momentum_20",
            factor_version="historical-v1",
            name="Security momentum 20",
            canonical_definition="20-session return",
            information_family="price_trend",
            update_frequency="daily",
            availability_lag_days=0,
            transformation="within_basket_percentile_rank",
            orientation="higher_is_better",
            neutralization="within_primary_basket",
            thesis="Recent leaders may continue.",
            code_identity="factor:security-momentum-20",
            status="rejected",
            source_kind="shadow-test",
            source_ref="shadow-test:rejected-card",
        )
    )


def _factor_scores(path: Path, *, as_of: str = "2026-07-31") -> Path:
    _write_json(
        path,
        {
            "schema_version": "1.0",
            "rows": [
                {
                    "date": as_of,
                    "symbol": "AAA",
                    "stable_factor_key": "revenue_growth_acceleration",
                    "score": 0.8,
                    "percentile": 0.9,
                    "reason_codes": ["GROWTH_ACCELERATION_POSITIVE"],
                },
                {
                    "date": as_of,
                    "symbol": "AAA",
                    "stable_factor_key": "security_momentum_20",
                    "score": 0.7,
                    "percentile": 0.8,
                    "reason_codes": ["LEGACY_PRICE_FACTOR_CONTEXT"],
                },
            ],
        },
    )
    return path


def test_shadow_ticket_is_immutable_explainable_and_non_trading(tmp_path: Path) -> None:
    rotation_dir = _build_rotation_artifacts(tmp_path / "rotation")
    registry_db = tmp_path / "factor_registry.db"
    _build_registry(registry_db)
    scores = _factor_scores(tmp_path / "factor_scores.json")
    ledger = tmp_path / "ledger"

    first = build_shadow_decision_ticket(
        rotation_dir=rotation_dir,
        registry_db=registry_db,
        ledger_dir=ledger,
        market="us",
        as_of_date="2026-07-31",
        factor_scores_path=scores,
        annual_turnover_budget=4.0,
    )
    second = build_shadow_decision_ticket(
        rotation_dir=rotation_dir,
        registry_db=registry_db,
        ledger_dir=ledger,
        market="us",
        as_of_date="2026-07-31",
        factor_scores_path=scores,
        annual_turnover_budget=4.0,
    )

    assert first["ticket_identity_sha256"] == second["ticket_identity_sha256"]
    assert first["mode"] == "diagnostic_only"
    assert first["research_only"] is True
    assert first["trade_ready"] is False
    assert first["automatic_order_routing"] is False
    assert first["performance_evaluated"] is False
    assert first["turnover_budget"]["ticket_turnover"] == pytest.approx(0.75)
    assert first["turnover_budget"]["remaining"] == pytest.approx(3.25)

    by_symbol = {row["symbol"]: row for row in first["securities"]}
    assert by_symbol["AAA"]["action"] == "ENTER_CANDIDATE"
    assert by_symbol["AAA"]["eligible_factor_count"] == 1
    assert by_symbol["AAA"]["excluded_factor_count"] == 1
    assert by_symbol["BBB"]["action"] == "REDUCE_CANDIDATE"
    assert by_symbol["CCC"]["action"] == "EXIT_RISK"
    assert by_symbol["DDD"]["action"] == "WATCH"

    assert (ledger / "us" / "2026-07-31.json").exists()
    assert (ledger / "us" / "2026-07-31.md").exists()
    assert b"\r\n" not in (ledger / "us" / "2026-07-31.md").read_bytes()
    manifest = json.loads((ledger / "us" / "ledger_manifest.json").read_text())
    assert manifest["ticket_count"] == 1
    assert manifest["trade_ready"] is False


def test_same_date_with_changed_inputs_fails_immutable_ledger(tmp_path: Path) -> None:
    rotation_dir = _build_rotation_artifacts(tmp_path / "rotation")
    registry_db = tmp_path / "factor_registry.db"
    _build_registry(registry_db)
    ledger = tmp_path / "ledger"
    build_shadow_decision_ticket(
        rotation_dir=rotation_dir,
        registry_db=registry_db,
        ledger_dir=ledger,
        market="us",
        as_of_date="2026-07-31",
    )

    _build_rotation_artifacts(rotation_dir, a_weight=0.40)
    with pytest.raises(ValueError, match="immutable shadow ledger conflict"):
        build_shadow_decision_ticket(
            rotation_dir=rotation_dir,
            registry_db=registry_db,
            ledger_dir=ledger,
            market="us",
            as_of_date="2026-07-31",
        )


def test_future_rows_fail_closed(tmp_path: Path) -> None:
    rotation_dir = _build_rotation_artifacts(
        tmp_path / "rotation", include_future=True
    )
    registry_db = tmp_path / "factor_registry.db"
    _build_registry(registry_db)

    with pytest.raises(ValueError, match="future row"):
        build_shadow_decision_ticket(
            rotation_dir=rotation_dir,
            registry_db=registry_db,
            ledger_dir=tmp_path / "ledger",
            market="us",
            as_of_date="2026-07-31",
        )


def test_trade_ready_or_tampered_rotation_artifacts_are_rejected(tmp_path: Path) -> None:
    rotation_dir = _build_rotation_artifacts(
        tmp_path / "rotation", trade_ready=True
    )
    registry_db = tmp_path / "factor_registry.db"
    _build_registry(registry_db)
    with pytest.raises(ValueError, match="claiming trade readiness"):
        build_shadow_decision_ticket(
            rotation_dir=rotation_dir,
            registry_db=registry_db,
            ledger_dir=tmp_path / "ledger",
            market="us",
            as_of_date="2026-07-31",
        )

    rotation_dir = _build_rotation_artifacts(tmp_path / "rotation-clean")
    with (rotation_dir / "security_score_history.json").open("a", encoding="utf-8") as handle:
        handle.write(" ")
    with pytest.raises(ValueError, match="hash mismatch"):
        build_shadow_decision_ticket(
            rotation_dir=rotation_dir,
            registry_db=registry_db,
            ledger_dir=tmp_path / "ledger-2",
            market="us",
            as_of_date="2026-07-31",
        )
