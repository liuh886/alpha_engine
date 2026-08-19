"""Dispatch isolation for the maintained CN exact-ranker replay CLI."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

import scripts.run_cn_ranker_exact_portfolio_replay as replay_script
from src.research.cn_x1_2_breadth_veto_development import DEVELOPMENT_RUNNER_ID


def _write_spec(tmp_path: Path, payload: dict) -> Path:
    spec = tmp_path / "spec.yaml"
    spec.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return spec


def _runner_stub(key: str, calls: dict):
    def run(spec_path, output_dir):
        calls[key] = (spec_path, output_dir)
        return {"status": "completed"}

    return run


def test_947_route_dispatches_breadth_veto(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict = {}
    monkeypatch.setattr(
        replay_script,
        "run_breadth_veto_development",
        _runner_stub("breadth_veto", calls),
    )
    monkeypatch.setattr(
        replay_script,
        "run_exact_cn_ranker_portfolio_replay",
        _runner_stub("exact", calls),
    )
    spec = _write_spec(tmp_path, {"development_runner": DEVELOPMENT_RUNNER_ID})
    out = tmp_path / "out"
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_cn_ranker_exact_portfolio_replay", "--spec", str(spec), "--output-dir", str(out)],
    )

    assert replay_script.main() == 0
    assert set(calls) == {"breadth_veto"}


def test_exact_route_dispatches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict = {}
    monkeypatch.setattr(
        replay_script,
        "run_breadth_veto_development",
        _runner_stub("breadth_veto", calls),
    )
    monkeypatch.setattr(
        replay_script,
        "run_exact_cn_ranker_portfolio_replay",
        _runner_stub("exact", calls),
    )
    spec = _write_spec(tmp_path, {"experiment_id": "exact_cn_ranker_portfolio_v1"})
    out = tmp_path / "out"
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_cn_ranker_exact_portfolio_replay", "--spec", str(spec), "--output-dir", str(out)],
    )

    assert replay_script.main() == 0
    assert set(calls) == {"exact"}


def test_resume_options_fail_closed_for_non_954_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _write_spec(tmp_path, {"experiment_id": "exact_cn_ranker_portfolio_v1"})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_cn_ranker_exact_portfolio_replay",
            "--spec",
            str(spec),
            "--output-dir",
            str(tmp_path / "out"),
            "--resume",
        ],
    )

    with pytest.raises(ValueError, match="supported only by the #954 route"):
        replay_script.main()
