import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_build_update_data_commands_incremental_default_rebuilds_db():
    from src.dashboard.data_update_runner import build_update_data_commands

    cmds = build_update_data_commands(python_exe="python")
    assert cmds[0][:2] == ["python", "scripts/update_data.py"]
    assert cmds[1] == ["python", "scripts/build_dashboard_db.py"]


def test_build_update_data_commands_full_rebuild_sets_flags():
    from src.dashboard.data_update_runner import build_update_data_commands

    cmds = build_update_data_commands(python_exe="python", full=True, start="2020-01-01")
    assert cmds[0][:3] == ["python", "scripts/update_data.py", "--full"]
    assert "--start" in cmds[0]


def test_build_update_data_commands_targets_selected_market():
    from src.dashboard.data_update_runner import build_update_data_commands

    cmds = build_update_data_commands(python_exe="python", market="us")

    assert cmds[0][:4] == ["python", "scripts/update_data.py", "--market", "us"]
