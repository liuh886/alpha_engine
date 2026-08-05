from __future__ import annotations

# Final trusted zero-drift verification after catalog and freshness synchronization.
import json
from pathlib import Path

import pandas as pd


def test_formal_cn_x1_1_package_is_complete() -> None:
    root = Path(__file__).resolve().parents[1]
    package = json.loads(
        (root / "data/research/formal_backtests/cn_x1_1.json").read_text(
            encoding="utf-8"
        )
    )
    assert package["model_id"] == "cn_x1_1"
    assert package["publication_status"] == "accepted_formal_baseline"
    assert package["research_only"] is True
    assert package["trade_ready"] is False
    assert package["date_range"] == {
        "start": "2022-07-01",
        "end": "2026-08-03",
    }
    assert package["evidence_completeness"]["status"] == "complete"
    assert package["evidence_completeness"]["missing"] == []
    assert package["evidence"]["row_counts"] == {
        "rebalance_periods": 102,
        "positions": 252,
        "trades": 370,
        "attribution": 363,
    }
    assert package["metrics"]["Compounded Relative Excess Return"] > 0.59
    assert package["evidence"]["candidate_decision"] == (
        "cn_x1_1_regime_gated_candidate_authorized"
    )


def test_formal_catalog_supersedes_cn_x1_0() -> None:
    root = Path(__file__).resolve().parents[1]
    v1 = json.loads(
        (root / "data/research/formal_backtests/catalog.json").read_text(
            encoding="utf-8"
        )
    )
    v1_ids = {row["model_id"] for row in v1["records"]}
    assert "cn_x1_1" in v1_ids
    assert "cn_x1_0" not in v1_ids

    v2 = json.loads(
        (root / "data/research/formal_model_runs/catalog.json").read_text(
            encoding="utf-8"
        )
    )
    v2_ids = {row["model_version_id"] for row in v2["records"]}
    assert v2_ids == {"qqqi_qqq_tqqq_v4_2", "us_x1_1", "cn_x1_1"}


def test_formal_freshness_supersedes_cn_x1_0() -> None:
    root = Path(__file__).resolve().parents[1]
    freshness = json.loads(
        (root / "data/research/formal_backtests/freshness.json").read_text(
            encoding="utf-8"
        )
    )
    for key in (
        "required_models",
        "date_range_end_required_models",
        "freshness_receipt_required_models",
    ):
        assert "cn_x1_1" in freshness[key]
        assert "cn_x1_0" not in freshness[key]
    assert freshness["promoted_model"] == "cn_x1_1"
    assert freshness["superseded_model"] == "cn_x1_0"
    assert freshness["promotion_issue"] == 577


def test_cash_aware_turnover_and_cost_identity() -> None:
    root = Path(__file__).resolve().parents[1]
    ledger = root / "data/research/formal_backtests/cn_x1_1_ledgers"
    periods = pd.read_csv(ledger / "rebalance_periods.csv")
    holdings = pd.read_csv(
        ledger / "holdings.csv",
        dtype={"instrument": str},
    )
    trades = pd.read_csv(
        ledger / "trades.csv",
        dtype={"instrument": str},
    )

    assert len(periods) == 102
    assert len(holdings) == 252
    assert len(trades) == 370
    assert periods.iloc[0]["turnover"] == 1.0
    segment_starts = periods.loc[
        periods["evaluation"].ne(periods["evaluation"].shift()),
        "turnover",
    ].tolist()
    assert segment_starts == [1.0, 1.0]

    allocated = trades.groupby("period_index", sort=True)[
        "allocated_transaction_cost"
    ].sum()
    expected = periods["cost"]
    assert (
        allocated.reindex(expected.index, fill_value=0.0) - expected
    ).abs().max() < 1e-10


def test_v2_bundle_has_complete_sections() -> None:
    root = Path(__file__).resolve().parents[1]
    bundle = (
        root
        / "data/research/formal_model_runs/cn_ranker/cn_x1_1"
        / "cn_x1_1_through_2026_08_03"
    )
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    available = {
        row["section_id"]
        for row in manifest["sections"]
        if row["availability_status"] == "available"
    }
    assert manifest["model_version_id"] == "cn_x1_1"
    assert manifest["publication_status"] == "accepted_formal_baseline"
    assert {
        "summary",
        "performance",
        "risk",
        "robustness",
        "portfolio",
        "trades",
        "attribution",
        "diagnostics",
        "lineage",
    } <= available


def test_release_manifest_binds_certified_artifact() -> None:
    root = Path(__file__).resolve().parents[1]
    release = json.loads(
        (
            root
            / "data/research/formal_promotions/releases/cn_x1_1.json"
        ).read_text(encoding="utf-8")
    )
    assert release["model_id"] == "cn_x1_1"
    assert release["source"]["artifact_id"] == 8937409026
    assert release["source"]["artifact_digest"] == (
        "sha256:e540e400dbefd5178122444e709182323f1b363a3c41496fd8212e5095ee5a4b"
    )
    assert release["durability"]["status"] == "durable_repository_evidence"
    assert len(release["durability"]["approved_durable_locations"]) == 5
