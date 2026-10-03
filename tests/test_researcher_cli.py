from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.cli import main as cli
from src.data import data_recipe, data_recipe_catalog


@pytest.mark.parametrize("argv", [["--help"], ["data", "list"], ["research", "replay", "--help"], ["ops", "build", "--help"]])
def test_read_only_cli_does_not_load_research_or_provider_engines(argv) -> None:
    code = '''
import importlib.abc
import sys
class RejectHeavyImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("numpy", "pandas", "qlib", "src.data.adapters",
                                "src.research.formal_model_replay", "src.artifacts.model_operations")):
            raise AssertionError("read-only command loaded heavy engine: " + fullname)
sys.meta_path.insert(0, RejectHeavyImports())
from src.cli.main import main
main(ARGV)
'''.replace("ARGV", repr(argv))
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    if argv == ["data", "list"]:
        assert json.loads(result.stdout)["trade_ready"] is False


def test_catalog_error_remains_a_blocked_result(monkeypatch, capsys) -> None:
    def fail(root):
        raise data_recipe_catalog.DataRecipeError("invalid recipe identity")

    monkeypatch.setattr(data_recipe_catalog, "data_recipe_catalog", fail)
    assert cli.main(["data", "list"]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


def test_unexpected_programming_error_is_not_hidden(monkeypatch) -> None:
    def fail(root):
        raise RuntimeError("unexpected bug")

    monkeypatch.setattr(data_recipe_catalog, "data_recipe_catalog", fail)
    with pytest.raises(RuntimeError, match="unexpected bug"):
        cli.main(["data", "list"])


def test_ops_catalog_identity_error_remains_blocked(monkeypatch, capsys) -> None:
    from src.artifacts import strategy_operations
    from src.governance.active_strategy_catalog import ActiveStrategyCatalogError

    def fail(**kwargs):
        raise ActiveStrategyCatalogError("invalid active strategy identity")

    monkeypatch.setattr(strategy_operations, "build_operations_payload", fail)
    assert cli.main(["ops", "build", "--generated-at", "2026-10-03T00:00:00Z"]) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "invalid active strategy identity"


def test_data_list_renders_registry_catalog(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        data_recipe_catalog,
        "data_recipe_catalog",
        lambda root: {
            "recipes": [{"recipe_id": "us87-prices"}],
            "research_only": True,
            "trade_ready": False,
        },
    )
    code = cli.main(["data", "list"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["recipes"][0]["recipe_id"] == "us87-prices"


def test_data_prepare_command_renders_governed_result(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    def fake_prepare(recipe: str, **kwargs):
        captured["recipe"] = recipe
        captured.update(kwargs)
        return {
            "recipe_id": recipe,
            "status": "reused",
            "research_only": True,
            "trade_ready": False,
        }

    monkeypatch.setattr(data_recipe, "prepare_data_recipe", fake_prepare)
    code = cli.main(
        [
            "--root",
            ".",
            "data",
            "prepare",
            "qqq-rotation",
            "--cutoff",
            "2026-08-01",
        ]
    )
    assert code == 0
    assert captured["recipe"] == "qqq-rotation"
    assert captured["cutoff"] == "2026-08-01"
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "reused"
    assert payload["trade_ready"] is False


def test_research_run_forwards_governed_bundle_options(monkeypatch, capsys) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: str, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return {
            "command_id": command,
            "status": "completed",
            "research_only": True,
            "trade_ready": False,
        }

    monkeypatch.setattr(data_recipe, "run_research_recipe", fake_run)
    code = cli.main(
        [
            "research",
            "run",
            "qqqi-vxn-v4.2",
            "--refresh",
            "--source-etf-bundle",
            "artifacts/shared-etf",
        ]
    )
    assert code == 0
    assert captured["command"] == "qqqi-vxn-v4.2"
    assert captured["refresh"] is True
    assert captured["source_etf_bundle"] == Path("artifacts/shared-etf")
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
