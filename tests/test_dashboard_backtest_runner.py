import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_build_backtest_commands_uses_strategy_profile_and_market():
    from src.dashboard.backtest_runner import build_backtest_commands

    cmds = build_backtest_commands(
        python_exe="python",
        market="us",
        model_type="lgbm",
        profile_path="configs/strategy_profile.json",
    )
    assert cmds == [
        [
            "python",
            "-m",
            "src.orchestrator",
            "run",
            "--market",
            "us",
            "--model_type",
            "lgbm",
            "--profile",
            "configs/strategy_profile.json",
        ]
    ]


def test_build_backtest_commands_rebacktest_uses_existing_model_path():
    from src.dashboard.backtest_runner import build_backtest_commands

    cmds = build_backtest_commands(
        python_exe="python",
        market="us",
        model_type="lgbm",
        profile_path="configs/strategy_profile.json",
        mode="rebacktest",
        model_path="models/us_model_20250102_000000.pkl",
        start="2025-01-01",
        end="latest",
    )
    assert cmds == [
        [
            "python",
            "-m",
            "src.orchestrator",
            "rebacktest",
            "--market",
            "us",
            "--model_type",
            "lgbm",
            "--model_path",
            "models/us_model_20250102_000000.pkl",
            "--start",
            "2025-01-01",
            "--end",
            "latest",
            "--profile",
            "configs/strategy_profile.json",
        ]
    ]
