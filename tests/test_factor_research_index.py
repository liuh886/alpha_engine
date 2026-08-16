from __future__ import annotations

from src.common.runtime_settings import PROJECT_ROOT
from src.factors.evidence import records_from_feature_quality_receipt
from src.factors.research_index import build_factor_research_index, query_factor_research_index


def _by_id(index: dict) -> dict[str, dict]:
    return {row["factor_id"]: row for row in index["factors"]}


def test_factor_index_unifies_registered_definitions_models_and_issue966_evidence() -> None:
    index = build_factor_research_index(root=PROJECT_ROOT)
    factors = _by_id(index)

    assert index["factor_count"] >= 180
    assert index["evidence_record_count"] == 9
    assert len(index["index_sha256"]) == 64

    momentum = factors["ohlcv.momentum.ret_10d"]
    assert momentum["market_status"]["us"] == "model_active"
    assert momentum["market_status"]["cn"] == "model_active"
    assert momentum["active_models"] == {"cn": ["cn_x1_2"], "us": ["us_x1_2"]}

    cord5 = factors["qlib_alpha158.cord5"]
    assert cord5["market_status"]["cn"] == "model_active"
    assert cord5["active_models"]["cn"] == ["cn_x1_2"]

    signed = factors["volume_stat_research.signed_volume_balance_10d"]
    assert signed["market_status"] == {"cn": "rejected", "us": "candidate"}
    assert signed["mechanism"] == "signed_volume_balance"

    rank20 = factors["qlib_alpha158.rank20"]
    assert rank20["market_status"]["us"] == "candidate"
    assert rank20["market_status"]["cn"] == "rejected"

    skew = factors["distribution_risk_research.ret_skew_20d"]
    assert skew["market_status"] == {"cn": "diagnostic_only", "us": "validated"}
    assert skew["mechanism"] == "ret_skew"

    kurt = factors["distribution_risk_research.ret_kurt_20d"]
    assert kurt["market_status"] == {"cn": "diagnostic_only", "us": "diagnostic_only"}


def test_factor_index_queries_category_mechanism_market_and_status() -> None:
    index = build_factor_research_index(root=PROJECT_ROOT)

    rows = query_factor_research_index(
        index,
        category="distribution_risk",
        mechanism="ret_skew",
        market="us",
        status="validated",
    )
    assert [row["factor_id"] for row in rows] == [
        "distribution_risk_research.ret_skew_20d"
    ]

    rejected_cn = query_factor_research_index(index, market="cn", status="rejected")
    rejected_ids = {row["factor_id"] for row in rejected_cn}
    assert "volume_stat_research.signed_volume_balance_10d" in rejected_ids
    assert "qlib_alpha158.rank20" in rejected_ids


def test_feature_quality_receipt_normalizes_first_valid_coverage_and_identity() -> None:
    receipt = {
        "gate1_pass": True,
        "market": "us",
        "provider": {"provider_identity_sha256": "a" * 64, "cutoff": "2026-06-30"},
        "universe": {
            "universe_id": "test_us",
            "requested_symbol_count": 2,
        },
        "determinism": {"pass": True},
        "factors": [
            {
                "factor_id": "test.factor",
                "implementation_hash": "b" * 64,
                "finite_count": 198,
                "missing_symbols": [],
                "inf_count": 0,
                "near_constant": False,
                "expression_window": {"past_sessions": 10, "future_sessions": 0},
                "checks": {
                    "finite_and_coverage": True,
                    "no_inf": True,
                    "not_near_constant": True,
                    "no_future_data": True,
                    "symbol_isolation": True,
                },
                "symbol_quality": {
                    "A": {
                        "first_valid_date": "2024-01-15",
                        "last_valid_date": "2025-12-31",
                        "observed_warmup_sessions": 10,
                        "post_warmup_coverage": 1.0,
                    },
                    "B": {
                        "first_valid_date": "2024-01-16",
                        "last_valid_date": "2025-12-31",
                        "observed_warmup_sessions": 11,
                        "post_warmup_coverage": 0.98,
                    },
                },
            }
        ],
    }

    [record] = records_from_feature_quality_receipt(receipt, evidence_path="receipt.json")

    assert record.validation["usable_rows"] == 198
    assert record.validation["minimum_post_warmup_coverage"] == 0.98
    assert record.validation["earliest_first_valid_date"] == "2024-01-15"
    assert record.validation["latest_first_valid_date"] == "2024-01-16"
    assert record.validation["minimum_observed_warmup_sessions"] == 10
    assert record.validation["maximum_observed_warmup_sessions"] == 11
    assert record.validation["deterministic"] is True
