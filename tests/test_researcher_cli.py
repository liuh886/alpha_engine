from __future__ import annotations

import json
from pathlib import Path

from src.cli import main as cli


def test_data_list_renders_registry_catalog(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        cli,
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

    monkeypatch.setattr(cli, "prepare_data_recipe", fake_prepare)
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

    monkeypatch.setattr(cli, "run_research_recipe", fake_run)
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
