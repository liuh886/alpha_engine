from __future__ import annotations

from copy import deepcopy

from src.data.provider_snapshot_comparison import (
    compare_candidate_evidence,
    compare_refresh_manifests,
    decide_snapshot_drift,
)


def _manifest(*, cutoff: str, rows: int, output_hash: str) -> dict:
    return {
        "market": "cn",
        "pool_id": "cn_selected_equities_v3",
        "cutoff": cutoff,
        "provider_identity_sha256": output_hash,
        "before": {"000001": {"sha256": "before"}},
        "selected_providers": {"000001": "akshare_sina"},
        "records": [
            {
                "symbol": "000001",
                "provider": "akshare_sina",
                "provider_symbol": "sz000001",
                "first_date": "2021-01-04",
                "last_date": cutoff,
                "rows": rows,
                "output_sha256": output_hash,
            }
        ],
        "research_only": True,
        "trade_ready": False,
    }


def test_missing_prefix_evidence_blocks_append_only_claim() -> None:
    old = _manifest(cutoff="2026-06-18", rows=1321, output_hash="a" * 64)
    new = _manifest(cutoff="2026-07-31", rows=1351, output_hash="b" * 64)
    rows, summary = compare_refresh_manifests(old, new)
    assert rows[0].classification == "prefix_evidence_missing"
    assert rows[0].row_delta == 30
    assert summary["before_snapshots_equal"] is True
    decision = decide_snapshot_drift(rows, summary)
    assert decision["decision"] == "unexplained_provider_drift_blocking"
    assert decision["further_cn_model_search_authorized"] is False


def test_identical_prefix_hashes_prove_append_only_reproducibility() -> None:
    old = _manifest(cutoff="2026-06-18", rows=1321, output_hash="a" * 64)
    new = _manifest(cutoff="2026-07-31", rows=1351, output_hash="b" * 64)
    old["historical_prefix_sha256"] = {"000001": "c" * 64}
    new["historical_prefix_sha256"] = {"000001": "c" * 64}
    rows, summary = compare_refresh_manifests(old, new)
    assert rows[0].classification == "appended_only"
    assert summary["historical_prefix_evidence_complete"] is True
    assert decide_snapshot_drift(rows, summary)["decision"] == (
        "append_only_reproducible"
    )


def test_changed_prefix_is_visible_and_never_silently_accepted() -> None:
    old = _manifest(cutoff="2026-06-18", rows=1321, output_hash="a" * 64)
    new = _manifest(cutoff="2026-07-31", rows=1351, output_hash="b" * 64)
    old["historical_prefix_sha256"] = {"000001": "c" * 64}
    new["historical_prefix_sha256"] = {"000001": "d" * 64}
    rows, summary = compare_refresh_manifests(old, new)
    assert rows[0].classification == "historical_prefix_changed"
    decision = decide_snapshot_drift(rows, summary)
    assert decision["decision"] == "legitimate_historical_revision_explained"
    assert decision["automatic_restatement_authorized"] is False


def test_candidate_metric_deltas_bind_exact_candidate_identity() -> None:
    candidate = "xgb:daily_ranker:cn_balanced_ohlcv:baseline"
    old = {
        "candidates": [
            {
                "candidate": candidate,
                "n_windows": 4,
                "compounded_total_return": 0.68,
                "compounded_benchmark_return": 0.40,
                "compounded_relative_excess_return": 0.20,
                "mean_icir": 0.10,
                "mean_rank_ic": 0.01,
                "mean_spread": 0.02,
                "worst_drawdown": -0.16,
                "positive_excess_ratio": 0.75,
            }
        ]
    }
    new = deepcopy(old)
    new["candidates"][0]["compounded_total_return"] = 0.58
    new["candidates"][0]["compounded_relative_excess_return"] = 0.13
    result = compare_candidate_evidence(old, new, candidate_id=candidate)
    assert result["old_windows"] == result["new_windows"] == 4
    assert result["metrics"]["compounded_total_return"]["delta"] == -0.1
    assert result["metrics"]["compounded_relative_excess_return"]["delta"] == -0.07
