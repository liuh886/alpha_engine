"""Contract tests for static-to-PIT decomposition."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.run_static_to_pit_alpha_decomposition import build_parser
from src.research.paradigm import ResearchParadigmSpec, load_research_paradigm_spec
from src.research.static_to_pit_decomposition import (
    build_four_cell_matrix,
    final_stop_decision,
    validate_endpoint_reproduction,
    validate_frozen_spec_pair,
)

STATIC_SPEC = Path("configs/research_paradigms/us_10d_lgbm_xgb_ranker_comparison.yaml")
PIT_SPEC = Path("configs/research_paradigms/us_10d_lgbm_xgb_ranker_pit_robustness.yaml")


def test_four_cell_matrix_is_frozen_and_ordered() -> None:
    cells = build_four_cell_matrix()
    assert [cell.cell_id for cell in cells] == ["S/S", "S/P", "P/S", "P/P"]
    assert cells[0].training_membership == "static_curated"
    assert cells[-1].oos_membership == "window_start_point_in_time"


def test_repository_specs_share_frozen_contract() -> None:
    payload = validate_frozen_spec_pair(
        load_research_paradigm_spec(STATIC_SPEC),
        load_research_paradigm_spec(PIT_SPEC),
    )
    assert payload["research_only"] is True
    assert payload["promotion_eligible"] is False
    assert payload["trade_ready"] is False
    assert payload["observed_windows"] == ["2024H1", "2024H2", "2025H1", "2025H2"]
    assert len(payload["contract_sha256"]) == 64


def test_frozen_spec_pair_rejects_model_change() -> None:
    static = load_research_paradigm_spec(STATIC_SPEC)
    pit = load_research_paradigm_spec(PIT_SPEC)
    altered = ResearchParadigmSpec.from_dict(
        {
            **pit.to_dict(),
            "candidate_grid": {
                **pit.candidate_grid,
                "ranker": {
                    **pit.candidate_grid["ranker"],
                    "calibrations": [{
                        **pit.candidate_grid["ranker"]["calibrations"][0],
                        "num_boost_round": 101,
                    }],
                },
            },
        },
        spec_path=pit.spec_path,
    )
    with pytest.raises(ValueError, match="candidate_grid"):
        validate_frozen_spec_pair(static, altered)


def _row(prefix: str, icir: float, excess: float, drawdown: float) -> dict:
    return {
        "candidate": f"{prefix}model/kind/original",
        "mean_icir": icir,
        "compounded_relative_excess_return": excess,
        "worst_drawdown": drawdown,
    }


def test_endpoint_reproduction_accepts_published_metrics() -> None:
    stability = {
        "S/S": {"candidates": [
            _row("lgbm:", 0.3587, 0.6504, -0.2734),
            _row("xgb:", 0.3497, 0.7035, -0.2563),
        ]},
        "P/P": {"candidates": [
            _row("lgbm:", 0.0966, -0.2049, -0.2611),
            _row("xgb:", 0.1149, -0.3408, -0.2559),
        ]},
    }
    result = validate_endpoint_reproduction(stability)
    assert result["passed"] is True


def test_endpoint_reproduction_fails_on_drift() -> None:
    assert validate_endpoint_reproduction({
        "S/S": {"candidates": []},
        "P/P": {"candidates": []},
    })["passed"] is False


def test_decision_cannot_promote_observed_cells() -> None:
    decision = final_stop_decision()
    assert decision["decision"] == "stop_existing_ohlcv_ranker_family"
    assert decision["promotion_eligible"] is False
    assert decision["trade_ready"] is False


def test_cli_requires_both_manifest_bound_providers() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    args = parser.parse_args([
        "--static-reference-provider-uri", "data/providers/us_static",
        "--decomposition-provider-uri", "data/providers/us_pit",
    ])
    assert args.static_reference_provider_uri == Path("data/providers/us_static")
    assert args.decomposition_provider_uri == Path("data/providers/us_pit")


def test_runner_exposes_no_parameter_search_surface() -> None:
    combined = (
        Path("scripts/run_static_to_pit_alpha_decomposition.py").read_text(encoding="utf-8")
        + Path("src/research/static_to_pit_execution.py").read_text(encoding="utf-8")
    )
    for forbidden in ("--learning-rate", "--top-n", "--factor", "--orientation"):
        assert forbidden not in combined
    assert "final_stop_decision()" in combined
