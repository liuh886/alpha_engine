from src.api.routers.factors import _format_failed_experiment


def test_walk_forward_failure_matches_frontend_contract():
    formatted = _format_failed_experiment(
        {
            "_source": "walk_forward",
            "file": "us_20260620_003612_hash.json",
            "_timestamp": "20260620_003612",
            "market": "us",
            "model_type": "lgbm",
            "reason": "Low IC_IR=0.0000 (< 0.3)",
            "mean_ic": 0.0,
            "ic_ir": 0.0,
        },
        0,
    )

    assert formatted == {
        "id": "wf:us_20260620_003612_hash.json",
        "timestamp": "20260620_003612",
        "type": "wf",
        "name": "us_20260620_003612_hash.json",
        "failure_reason": "Low IC_IR=0.0000 (< 0.3)",
        "details": {"market": "us", "model_type": "lgbm", "mean_ic": 0.0, "ic_ir": 0.0},
    }
