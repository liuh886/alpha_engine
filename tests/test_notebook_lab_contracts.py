from __future__ import annotations

from src.research.notebook_lab_contracts import ResearchSessionConfig
from src.research.notebook_research_api import sanitize_factor_name


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


def test_sanitize_factor_name_matches_training_notebook_convention() -> None:
    assert sanitize_factor_name("close/Ref(close,10)-1") == "close_d_Ref_close_10-1"
