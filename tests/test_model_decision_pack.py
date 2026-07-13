from __future__ import annotations

import pytest

from src.research.model_decision_pack import build_model_decision_pack, render_model_decision_markdown


def _summary(mean_icir: float, worst_drawdown: float, ready_ratio: float) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "min_windows": 3,
        "partial_window_policy": "complete_windows_only",
        "n_reports": 4,
        "n_candidates": 10,
        "candidates": [
            {
                "candidate": "blend:ranker_momentum:best/signal_blend/original",
                "n_windows": 4,
                "mean_icir": mean_icir,
                "mean_rank_ic": 0.0738,
                "mean_spread": 0.0145,
                "positive_icir_ratio": 1.0,
                "positive_spread_ratio": 0.75,
                "worst_drawdown": worst_drawdown,
                "ready_ratio": ready_ratio,
                "stable_research_candidate": True,
            },
            {
                "candidate": "lgbm:daily_ranker:old/lgbm_lambdarank/original",
                "n_windows": 4,
                "mean_icir": 0.0833,
                "mean_rank_ic": 0.0339,
                "mean_spread": 0.0100,
                "positive_icir_ratio": 1.0,
                "positive_spread_ratio": 1.0,
                "worst_drawdown": -0.142,
                "ready_ratio": 0.0,
                "stable_research_candidate": True,
            },
        ],
    }


def test_model_decision_pack_marks_blend_as_stronger_research_not_trade_ready() -> None:
    pack = build_model_decision_pack(_summary(mean_icir=0.2551, worst_drawdown=-0.112, ready_ratio=0.25))

    assert pack["current_best_candidate"]["candidate"] == "blend:ranker_momentum:best/signal_blend/original"
    assert pack["decision"]["status"] == "stronger_research_candidate"
    assert pack["decision"]["trade_ready"] is False
    assert pack["decision"]["failed_trade_gates"] == ["mean_icir", "ready_ratio"]
    assert pack["stable_candidate_count"] == 2
    assert "not authorization" in pack["non_trade_ready_warning"]


def test_model_decision_pack_requires_ready_ratio_for_trade_guidance() -> None:
    pack = build_model_decision_pack(_summary(mean_icir=0.35, worst_drawdown=-0.10, ready_ratio=0.25))

    assert pack["decision"]["status"] == "stronger_research_candidate"
    assert pack["decision"]["trade_ready"] is False
    assert pack["decision"]["failed_trade_gates"] == ["ready_ratio"]


def test_model_decision_pack_marks_trade_guidance_only_when_all_decision_gates_pass() -> None:
    pack = build_model_decision_pack(_summary(mean_icir=0.35, worst_drawdown=-0.10, ready_ratio=0.75))

    assert pack["decision"]["status"] == "trade_guidance_candidate"
    assert pack["decision"]["trade_ready"] is True
    assert pack["decision"]["failed_trade_gates"] == []


def test_model_decision_pack_handles_no_stable_candidate() -> None:
    pack = build_model_decision_pack(
        {"schema_version": "1.0", "min_windows": 3, "n_reports": 4, "n_candidates": 1, "candidates": []}
    )

    assert pack["current_best_candidate"] is None
    assert pack["decision"]["status"] == "no_stable_candidate"
    assert pack["decision"]["trade_ready"] is False


def test_render_model_decision_markdown_includes_status_and_warning() -> None:
    pack = build_model_decision_pack(_summary(mean_icir=0.2551, worst_drawdown=-0.112, ready_ratio=0.25))
    text = render_model_decision_markdown(pack)

    assert "AlphaEngine 10D Model Decision Pack" in text
    assert "stronger_research_candidate" in text
    assert "Trade ready: **False**" in text
    assert "Research evidence is not authorization" in text


def test_model_decision_pack_rejects_single_window_stability_sources() -> None:
    summary = _summary(mean_icir=0.2551, worst_drawdown=-0.112, ready_ratio=0.25)
    summary["min_windows"] = 1
    summary["n_reports"] = 1

    with pytest.raises(ValueError, match="min_windows"):
        build_model_decision_pack(summary)


def test_model_decision_pack_recommends_universe_expansion_not_more_weight_tuning() -> None:
    pack = build_model_decision_pack(_summary(mean_icir=0.2551, worst_drawdown=-0.112, ready_ratio=0.25))

    assert "Expand the universe" in pack["recommended_next_step"]
    assert "robustness validation" in pack["recommended_next_step"]
    assert "do not continue small blend-weight tuning" in pack["recommended_next_step"]
