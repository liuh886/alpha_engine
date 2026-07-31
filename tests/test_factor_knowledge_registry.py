from __future__ import annotations

from pathlib import Path

import pytest

from src.research.factor_knowledge_registry import (
    AUTHORITATIVE_EVALUATION_METRICS,
    FactorCardInput,
    FactorKnowledgeRegistry,
)
from src.research.factor_registry import STAGE_ACTIVE, FactorRegistry


def _registry(tmp_path: Path) -> FactorKnowledgeRegistry:
    return FactorKnowledgeRegistry(tmp_path / "factor_registry.db")


def _card(
    *,
    key: str = "revenue_growth_acceleration",
    version: str = "1.0",
    family: str = "growth",
    source_ref: str = "issue-225:factor-card-v1",
) -> FactorCardInput:
    return FactorCardInput(
        stable_factor_key=key,
        factor_version=version,
        name=key.replace("_", " ").title(),
        canonical_definition="rank(yoy_revenue_growth_t - yoy_revenue_growth_t_minus_1)",
        information_family=family,
        update_frequency="quarterly",
        availability_lag_days=1,
        transformation="within_basket_percentile_rank",
        orientation="higher_is_better",
        neutralization="within_primary_basket",
        thesis="Improving operating growth should be reflected with a publication-date lag.",
        code_identity="spec:issue-225:v1",
        status="candidate",
        spec_path="configs/research_paradigms/us_low_turnover_fundamental_v1.yaml",
        source_report_path="docs/research/factor_knowledge_system_charter_2026-07-31.md",
        source_kind="native_v2",
        source_ref=source_ref,
    )


def _evidence(**overrides):
    payload = {
        "market": "us",
        "universe_version": "us_small_pool_v1",
        "benchmark": "QQQ",
        "horizon_sessions": 20,
        "provider_identity": "provider-sha-001",
        "data_validity_level": "point_in_time_publication_date",
        "development_start": "2021-01-01",
        "development_end": "2025-12-31",
        "falsification_start": "2026-01-01",
        "falsification_end": "2026-06-30",
        "reserved_start": "2026-07-01",
        "reserved_end": "2026-12-31",
        "cost_bps": 10.0,
        "execution_contract": "monthly_close_to_next_open",
        "evidence_manifest_hash": "manifest-001",
        "authoritative": True,
        "decision_status": "candidate",
        "failure_class": "",
        "lessons_learned": "First current-contract factor card.",
        "source_kind": "native_v2",
        "source_ref": "issue-225:evidence-v1",
    }
    payload.update(overrides)
    return payload


def _metrics(**overrides):
    metrics = {
        "ic": 0.03,
        "rank_ic": 0.04,
        "icir": 0.8,
        "t_stat": 2.2,
        "positive_ratio": 0.61,
        "mean_decay_1d": 0.04,
        "mean_decay_5d": 0.02,
        "quintile_spread": 0.004,
        "after_cost_return": 0.28,
        "benchmark_relative_return": 0.06,
        "max_drawdown": -0.24,
        "downside_capture": 0.88,
        "annual_turnover": 2.8,
        "average_holding_sessions": 61.0,
        "max_single_symbol_concentration": 0.27,
        "positive_basket_contribution_ratio": 0.67,
        "coverage_ratio": 0.98,
        "development_falsification_stability": 0.72,
        "cash_utilization": 0.84,
        "failed_gates": [],
        "regime_behavior": {"risk_on": 0.12, "risk_off": 0.03},
        "basket_behavior": {"semiconductor": 0.07},
    }
    metrics.update(overrides)
    return metrics


def test_card_identity_is_versioned_idempotent_and_status_limited(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    card = _card()
    first = registry.register_card(card)
    second = registry.register_card(card)

    assert first == second
    assert registry.get_card(first)["status"] == "candidate"
    assert len(registry.list_cards()) == 1

    with pytest.raises(ValueError, match="invalid factor status"):
        registry.register_card(
            FactorCardInput(**{**card.__dict__, "factor_version": "2.0", "status": "supported"})
        )


def test_authoritative_evidence_requires_complete_identity(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    card_id = registry.register_card(_card())

    with pytest.raises(ValueError, match="provider_identity"):
        registry.record_evidence(card_id, _evidence(provider_identity=""))

    with pytest.raises(ValueError, match="unverified or blocked"):
        registry.record_evidence(
            card_id,
            _evidence(
                decision_status="legacy_unverified",
                evidence_manifest_hash="manifest-legacy-authoritative",
                source_ref="bad-authoritative-status",
            ),
        )


def test_authoritative_evaluation_fails_closed_on_missing_economics(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    card_id = registry.register_card(_card())
    evidence_id = registry.record_evidence(card_id, _evidence())
    incomplete = _metrics()
    incomplete.pop("annual_turnover")

    with pytest.raises(ValueError, match="annual_turnover"):
        registry.record_evaluation(evidence_id, incomplete)

    evaluation_id = registry.record_evaluation(evidence_id, _metrics())
    assert evaluation_id.startswith("evaluation_")
    report = registry.evidence_completeness_report()
    assert report["authoritative_evidence_count"] == 1
    assert report["incomplete_evidence_count"] == 0


def test_non_authoritative_legacy_evaluation_can_be_retained_as_incomplete(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    card_id = registry.register_card(
        _card(
            key="legacy_momentum_5d",
            version="legacy-v1",
            family="price_trend",
            source_ref="legacy-factor:1",
        )
    )
    evidence_id = registry.record_evidence(
        card_id,
        _evidence(
            market="us",
            universe_version="legacy_unknown",
            benchmark="legacy_unknown",
            horizon_sessions=0,
            provider_identity="legacy_unknown",
            data_validity_level="legacy_unknown",
            development_start="",
            development_end="",
            falsification_start="",
            falsification_end="",
            reserved_start="",
            reserved_end="",
            cost_bps=None,
            execution_contract="legacy_unknown",
            evidence_manifest_hash="legacy-manifest-1",
            authoritative=False,
            decision_status="legacy_unverified",
            failure_class="legacy_evidence_incomplete",
            source_ref="legacy-validation:1",
        ),
    )
    registry.record_evaluation(evidence_id, {"ic": 0.05, "icir": 6.2})

    report = registry.evidence_completeness_report()
    assert report["authoritative_evidence_count"] == 0
    assert report["incomplete_evidence_count"] == 1
    missing = report["incomplete"][0]["missing_evaluation_metrics"]
    assert set(AUTHORITATIVE_EVALUATION_METRICS).issubset(set(missing))


def test_manifest_and_evaluation_identities_are_immutable(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    card_a = registry.register_card(_card())
    evidence_a = registry.record_evidence(card_a, _evidence())
    assert registry.record_evidence(card_a, _evidence()) == evidence_a

    card_b = registry.register_card(
        _card(
            key="gross_margin_improvement",
            family="quality",
            source_ref="issue-225:gross-margin-card",
        )
    )
    with pytest.raises(ValueError, match="manifest hash"):
        registry.record_evidence(
            card_b,
            _evidence(source_ref="issue-225:other-evidence"),
        )

    registry.record_evaluation(evidence_a, _metrics())
    with pytest.raises(ValueError, match="immutable"):
        registry.record_evaluation(evidence_a, _metrics(after_cost_return=0.31))


def test_series_relationship_and_combination_usage_interfaces(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    card_a = registry.register_card(_card())
    card_b = registry.register_card(
        _card(
            key="downside_resilience",
            family="risk",
            source_ref="factor-card:downside-resilience",
        )
    )
    evidence = registry.record_evidence(card_a, _evidence())
    artifact = registry.attach_series_artifact(
        evidence,
        series_kind="score",
        artifact_path="artifacts/factors/revenue_growth_score.parquet",
        sha256="a" * 64,
        start_date="2021-01-01",
        end_date="2026-06-30",
        row_count=1200,
    )
    assert artifact.startswith("series_")

    relationship = registry.record_relationship(
        card_b,
        card_a,
        evidence_scope_hash="scope-001",
        source_manifest_hash="relationship-manifest-001",
        score_correlation=0.21,
        return_correlation=0.08,
        selection_overlap=0.19,
        turnover_overlap=0.14,
        redundancy_cluster="distinct-growth-risk",
    )
    assert relationship == registry.record_relationship(
        card_a,
        card_b,
        evidence_scope_hash="scope-001",
        source_manifest_hash="relationship-manifest-001",
        score_correlation=0.21,
        return_correlation=0.08,
        selection_overlap=0.19,
        turnover_overlap=0.14,
        redundancy_cluster="distinct-growth-risk",
    )

    usage = registry.record_combination_usage(
        card_a,
        combination_id="low_turnover_multifactor_v1",
        weight=0.25,
        role="primary",
        evidence_manifest_hash="combination-manifest-001",
    )
    assert usage.startswith("usage_")


def test_legacy_migration_is_additive_idempotent_and_reclassifies_active(tmp_path: Path) -> None:
    db_path = tmp_path / "factor_registry.db"
    legacy = FactorRegistry(db_path=str(db_path))
    factor_id = legacy.register_factor(
        name="mom_5d",
        expression="$close/Ref($close,5)-1",
        category="momentum",
        direction="long",
        lookback_days=5,
        thesis="Legacy static-universe momentum result.",
    )
    legacy.update_stage(factor_id, STAGE_ACTIVE)
    legacy.record_validation(
        factor_id,
        "us",
        {
            "ic": 0.67,
            "rank_ic": 0.66,
            "icir": 6.2,
            "t_stat": 46.9,
            "positive_ratio": 0.92,
            "mean_decay_1d": 0.67,
            "mean_decay_5d": 0.42,
            "quintile_spread": 0.02,
        },
    )
    legacy.record_usage(factor_id, "legacy_lgbm_strategy", weight=1.0)

    registry = FactorKnowledgeRegistry(db_path)
    first = registry.migrate_legacy_registry()
    second = registry.migrate_legacy_registry()

    assert first == {"cards": 1, "evidence": 1, "evaluations": 1, "usage": 1}
    assert second == {"cards": 0, "evidence": 0, "evaluations": 0, "usage": 0}
    cards = registry.list_cards()
    assert len(cards) == 1
    assert cards[0]["name"] == "mom_5d"
    assert cards[0]["status"] == "legacy_unverified"
    assert cards[0]["information_family"] == "price_trend"

    evidence_rows = registry.list_evidence(cards[0]["card_id"])
    assert len(evidence_rows) == 1
    assert evidence_rows[0]["authoritative"] == 0
    assert evidence_rows[0]["decision_status"] == "legacy_unverified"
    assert evidence_rows[0]["failure_class"] == "legacy_evidence_incomplete"

    report = registry.evidence_completeness_report()
    assert report["factor_card_count"] == 1
    assert report["evidence_count"] == 1
    assert report["incomplete_evidence_count"] == 1
