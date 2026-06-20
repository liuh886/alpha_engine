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


def test_workflow_command_envelope_generates_legacy_training_command():
    from src.dashboard.backtest_runner import WorkflowCommandEnvelope, build_workflow_commands

    envelope = WorkflowCommandEnvelope.from_backtest_request(
        market="US",
        model_type="lgbm",
        profile_path="configs/strategy_profile.json",
        mode="train",
        tag="BT_TEST",
        strategy_template="TopK_10_2W",
        cost_params={"commission": 0.0005},
    )

    assert envelope.to_dict()["action"] == "run"
    assert build_workflow_commands(python_exe="python", envelopes=[envelope]) == [
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
            "--tag",
            "BT_TEST",
            "--strategy_template",
            "TopK_10_2W",
            "--cost_params",
            '{"commission": 0.0005}',
        ]
    ]


def test_workflow_command_envelope_allows_rebacktest_without_model_path_for_runtime_defaults():
    from src.dashboard.backtest_runner import build_backtest_commands

    cmds = build_backtest_commands(
        python_exe="python",
        market="us",
        model_type="lgbm",
        profile_path="configs/strategy_profile.json",
        mode="rebacktest",
        start="2025-01-01",
        end="2025-01-31",
    )

    assert "--model_path" not in cmds[0]
    assert cmds[0][:8] == [
        "python",
        "-m",
        "src.orchestrator",
        "rebacktest",
        "--market",
        "us",
        "--model_type",
        "lgbm",
    ]
