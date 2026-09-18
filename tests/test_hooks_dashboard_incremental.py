"""Tests for post-training dashboard updates and data-repair timeout."""

from __future__ import annotations

import subprocess

from src.workflows import hooks


def test_update_dashboard_db_uses_incremental_model_ids(tmp_path, monkeypatch):
    import scripts.build_dashboard_db as dashboard

    db_path = tmp_path / "dashboard.json"
    db_path.write_text("{}", encoding="utf-8")
    calls: list[str] = []

    monkeypatch.setattr(dashboard, "DASHBOARD_DB_PATH", db_path)
    monkeypatch.setattr(
        dashboard, "main", lambda *, model_id="", sync_yaml=False: calls.append(model_id)
    )

    hooks._update_dashboard_db(["m1", "m2", "m1"])

    assert calls == ["m1", "m2"]


def test_update_dashboard_db_full_rebuild_when_missing(tmp_path, monkeypatch):
    import scripts.build_dashboard_db as dashboard

    calls: list[str] = []

    monkeypatch.setattr(dashboard, "DASHBOARD_DB_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(
        dashboard, "main", lambda *, model_id="", sync_yaml=False: calls.append(model_id)
    )

    hooks._update_dashboard_db(["m1"])

    assert calls == [""]


def test_repair_data_times_out(monkeypatch):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="update_data", timeout=kwargs.get("timeout", 1))

    monkeypatch.setattr(hooks.subprocess, "run", fake_run)

    assert hooks._repair_data("us") is False
