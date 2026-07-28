"""Runner contracts for cross-market technical-factor evidence."""

from __future__ import annotations

import hashlib
import json

import pandas as pd

from scripts.run_technical_indicator_factor_evidence import (
    _audit_provider_sources,
    _cross_market_decisions,
    _persist_window_contract,
    _raw_forward_returns,
)
from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR
from src.research.technical_indicator_factors import (
    TECHNICAL_INDICATOR_SPECS,
)


def test_raw_forward_returns_use_canonical_ten_session_economics() -> None:
    dates = pd.bdate_range("2025-01-02", periods=15)
    index = pd.MultiIndex.from_product(
        [dates, ("A", "B")],
        names=["datetime", "instrument"],
    )
    close = pd.DataFrame(
        {
            "close": [
                value
                for offset in range(15)
                for value in (10.0 + offset, 20.0 + 2.0 * offset)
            ]
        },
        index=index,
    )

    returns = _raw_forward_returns(close)

    assert returns.loc[(dates[0], "A"), "return"] == 1.0
    assert returns.loc[(dates[0], "B"), "return"] == 1.0
    assert pd.isna(returns.loc[(dates[-1], "A"), "return"])
    assert returns.attrs == {
        "provenance": "raw_forward_return",
        "horizon": 10,
        "expression": CANONICAL_10D_RETURN_EXPR,
    }


def _stability(*, stable: bool) -> dict:
    return {
        "candidates": [
            {
                "candidate": (
                    f"{spec.name}/factor_baseline/original"
                ),
                "stable_research_candidate": stable,
                "mean_icir": 0.2,
                "mean_rank_ic": 0.03,
                "positive_spread_ratio": 1.0,
                "worst_drawdown": -0.1,
            }
            for spec in TECHNICAL_INDICATOR_SPECS
        ]
    }


def _reports(*, positive_excess: bool) -> list[dict]:
    rows = []
    for _ in range(4):
        candidates = []
        for spec in TECHNICAL_INDICATOR_SPECS:
            candidates.append(
                {
                    "candidate_name": spec.name,
                    "orientation": "original",
                    "total_return": 0.03 if positive_excess else -0.03,
                    "benchmark_return": 0.01,
                    "excess_return": 0.02 if positive_excess else -0.04,
                }
            )
        rows.append({"comparison_report": {"candidates": candidates}})
    return rows


def test_cross_market_decision_requires_both_markets_and_economics() -> None:
    supported = _cross_market_decisions(
        us_reports=_reports(positive_excess=True),
        cn_reports=_reports(positive_excess=True),
        us_stability=_stability(stable=True),
        cn_stability=_stability(stable=True),
    )
    rejected = _cross_market_decisions(
        us_reports=_reports(positive_excess=True),
        cn_reports=_reports(positive_excess=False),
        us_stability=_stability(stable=True),
        cn_stability=_stability(stable=True),
    )

    assert all(row["cross_market_supported"] for row in supported)
    assert all(row["trade_ready"] is False for row in supported)
    assert not any(row["cross_market_supported"] for row in rejected)


def test_window_contract_is_persisted_without_local_artifact_path(tmp_path) -> None:
    artifact_path = tmp_path / "window.json"
    artifact_path.write_text('{"schema_version": "1.0"}', encoding="utf-8")
    report = {
        "schema_version": "1.0",
        "artifact_path": str(artifact_path),
    }
    window = {
        "label": "2024H1",
        "membership_mode": "window_start_point_in_time",
        "snapshot_date": "2024-01-02",
    }

    _persist_window_contract(report, window=window)

    persisted = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert persisted["window_contract"] == {
        "label": "2024H1",
        "membership_mode": "window_start_point_in_time",
        "snapshot_date": "2024-01-02",
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": False,
    }
    assert "artifact_path" not in persisted
    assert report["artifact_path"] == str(artifact_path)


def test_source_audit_separates_close_and_high_low_eligibility(
    tmp_path,
) -> None:
    source = tmp_path / "A.csv"
    source.write_text(
        "\n".join(
            (
                "date,open,high,low,close,volume,amount,factor",
                "2025-01-02,10,11,9,10,100,1000,1",
                "2025-01-03,10,9,9,10,0,0,1",
            )
        ),
        encoding="utf-8",
    )
    manifest = {
        "provider_identity_sha256": "a" * 64,
        "source_csvs": [
            {
                "name": source.name,
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        ],
    }

    result = _audit_provider_sources(
        market="test",
        csv_dirs=(tmp_path,),
        provider_manifest=manifest,
        survivorship_bias=True,
    )

    assert result["close_only_factor_evidence_eligible"] is True
    assert result["high_low_factor_evidence_eligible"] is False
    assert result["invalid_ohlc_rows"] == 1
    assert result["nonpositive_volume_rows"] == 1
    assert result["survivorship_bias"] is True
