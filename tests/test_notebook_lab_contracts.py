from __future__ import annotations

from src.research.notebook_lab_contracts import ResearchSessionConfig


def test_research_session_config_defaults_to_fixed_10d() -> None:
    cfg = ResearchSessionConfig(
        market="us",
        symbols=["S0"],
        benchmark="SPY",
        train_start="2024-01-01",
        train_end="2024-12-31",
        test_start="2025-01-01",
        test_end="2025-01-05",
    )
    assert cfg.holding_days == 10
    assert cfg.rebalance_days == 10
    assert cfg.topk == 15
