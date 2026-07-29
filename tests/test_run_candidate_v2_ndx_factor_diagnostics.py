"""Contract tests for fixed-hypothesis candidate_v2 factor diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.run_candidate_v2_ndx_factor_diagnostics import (
    FROZEN_FACTOR_DEFINITIONS,
    _aggregate_diagnostics,
    _load_source_evidence,
    _validate_frozen_factor_contract,
)
from scripts.run_candidate_v2_universe_robustness import FROZEN_FEATURE_GROUP


def _factor_diagnostic(
    *,
    original_rank_ic: float,
    original_top3_spread: float,
) -> dict[str, Any]:
    def orientation(multiplier: float) -> dict[str, Any]:
        spread = original_top3_spread * multiplier
        original_icir = 0.2 if original_rank_ic >= 0.0 else -0.2
        return {
            "daily": {
                "mean_rank_ic": original_rank_ic * multiplier,
                "rank_icir": original_icir * multiplier,
                "quintile": {"mean_spread": original_top3_spread * 0.5 * multiplier},
            },
            "rebalance": {
                "fixed_tails": {
                    str(size): {
                        "mean_spread": spread,
                        "positive_spread_ratio": (0.75 if spread > 0.0 else 0.25),
                        "mean_selected_realized_percentile": (0.6 if spread > 0.0 else 0.4),
                    }
                    for size in (3, 10, 20)
                }
            },
        }

    return {
        "orientations": {
            "original": orientation(1.0),
            "inverted": orientation(-1.0),
        }
    }


def _window(label: str) -> dict[str, Any]:
    factors = []
    for index, definition in enumerate(FROZEN_FACTOR_DEFINITIONS):
        factors.append(
            {
                "factor": dict(definition),
                "diagnostic": _factor_diagnostic(
                    original_rank_ic=(-0.03 if index == 0 else 0.01),
                    original_top3_spread=(-0.02 if index == 0 else 0.005),
                ),
            }
        )
    return {
        "window": {"label": label},
        "n_oos_symbols": 100,
        "factors": factors,
    }


def test_frozen_factor_contract_matches_candidate_features() -> None:
    _validate_frozen_factor_contract()
    assert (
        tuple(item["expression"] for item in FROZEN_FACTOR_DEFINITIONS)
        == FROZEN_FEATURE_GROUP.expressions
    )


def test_aggregate_exposes_broad_ic_top3_disconnect_without_promotion() -> None:
    reports = [_window(label) for label in ("2024H1", "2024H2", "2025H1", "2025H2")]
    source = {
        "candidate": "blend:test",
        "score_diagnostics": {
            "mean_rank_ic": 0.02,
            "mean_rank_ic_ir": 0.12,
            "mean_top_bottom_spread": 0.003,
        },
        "selection_tail_diagnostics": {
            "mean_spread": -0.002,
            "mean_positive_spread_ratio": 0.44,
            "mean_selected_realized_percentile": 0.48,
        },
        "candidate_v2": {
            "compounded_relative_excess_return": -0.47,
            "worst_drawdown": -0.24,
        },
    }

    aggregate = _aggregate_diagnostics(reports, source_aggregate=source)

    assert aggregate["diagnosis"]["broad_ic_tail_disconnect"] is True
    assert aggregate["diagnosis"]["top3_economically_consistent"] is False
    assert aggregate["diagnosis"]["conclusion"] == (
        "broad_cross_section_signal_does_not_survive_top3_concentration"
    )
    resolution = aggregate["target_resolution_diagnosis"]
    assert resolution["gain_resolution_mismatch"] is True
    assert resolution["minimum_expected_top_gain_bin_size"] == 20
    assert resolution["minimum_top_gain_bin_to_portfolio_ratio"] == pytest.approx(20 / 3)
    assert resolution["effective_lambdarank_truncation_level"] == 30
    assert resolution["topk_aligned_reference_level"] == 6
    assert resolution["truncation_level_to_portfolio_topk_ratio"] == 10.0
    assert resolution["truncation_level_mismatch"] is True
    assert resolution["objective_topk_alignment_mismatch"] is True
    first = aggregate["factors"][0]
    assert first["descriptive_preferred_orientation"] == "inverted"
    assert first["preferred_orientation_selected_on_same_oos_evidence"] is True
    assert first["passes_diagnostic_consistency_checks"] is True
    assert aggregate["promotion_eligible"] is False
    assert aggregate["trade_ready"] is False


def test_aggregate_requires_four_windows() -> None:
    with pytest.raises(ValueError, match="exactly 4"):
        _aggregate_diagnostics(
            [_window("2024H1")],
            source_aggregate={},
        )


def _write_source_evidence(
    root: Path,
    *,
    provider_identity: str = "provider-1",
    trade_ready: bool = False,
) -> None:
    root.mkdir(parents=True)
    manifest = {
        "candidate": "blend:test",
        "provider_identity_sha256": provider_identity,
        "research_only": True,
        "promotion_eligible": False,
        "trade_ready": trade_ready,
        "training_membership_asof_semiannual": True,
        "training_uses_future_oos_snapshot": False,
    }
    aggregate = {"aggregate": {"n_windows_evaluated": 4}}
    (root / "evidence_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    (root / "aggregate.json").write_text(
        json.dumps(aggregate),
        encoding="utf-8",
    )
    window_dir = root / "per_window"
    window_dir.mkdir()
    for label in ("2024H1", "2024H2", "2025H1", "2025H2"):
        payload = {
            "window": {"label": label},
            "skipped": False,
            "coverage_meta": {
                "oos_membership_point_in_time": True,
                "training_uses_future_oos_snapshot": False,
            },
        }
        (window_dir / f"{label}.json").write_text(
            json.dumps(payload),
            encoding="utf-8",
        )


def test_source_evidence_is_bound_to_provider_and_four_pit_windows(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    _write_source_evidence(source)

    manifest, aggregate, windows, hashes = _load_source_evidence(
        source,
        provider_identity="provider-1",
    )

    assert manifest["candidate"] == "blend:test"
    assert aggregate["n_windows_evaluated"] == 4
    assert len(windows) == 4
    assert set(hashes) == {
        "aggregate.json",
        "evidence_manifest.json",
        "per_window/2024H1.json",
        "per_window/2024H2.json",
        "per_window/2025H1.json",
        "per_window/2025H2.json",
    }


def test_source_evidence_rejects_trade_ready_claim(tmp_path: Path) -> None:
    source = tmp_path / "source"
    _write_source_evidence(source, trade_ready=True)

    with pytest.raises(ValueError, match="must not be trade ready"):
        _load_source_evidence(source, provider_identity="provider-1")
