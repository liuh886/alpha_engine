from src.artifacts.formal_bundle_v2_builder import _canonical_metrics


def test_refresh_state_canonical_signal_metric_ids_remain_available() -> None:
    metrics = _canonical_metrics(
        {
            "metrics": {"rank_ic": 0.0346, "icir": 0.2446},
            "report": [{"date": "2026-06-01"}, {"date": "2026-07-01"}],
            "evidence": {
                "metric_metadata": {
                    "rank_ic": {
                        "sample_count": 1,
                        "scope": "frozen development window: 2024-01-02 through 2026-06-30",
                    },
                    "icir": {
                        "sample_count": 1,
                        "scope": "frozen development window: 2024-01-02 through 2026-06-30",
                    },
                }
            },
        },
        model_kind="cross_sectional_ranker",
    )
    by_id = {row["metric_id"]: row for row in metrics}

    assert by_id["rank_ic"]["availability_status"] == "available"
    assert by_id["rank_ic"]["estimator"] == "retained_formal_source:rank_ic"
    assert by_id["rank_ic"]["sample_count"] == 1
    assert by_id["rank_ic"]["scope"].startswith("frozen development window")
    assert by_id["icir"]["availability_status"] == "available"
    assert by_id["ic"]["availability_status"] == "not_retained"
