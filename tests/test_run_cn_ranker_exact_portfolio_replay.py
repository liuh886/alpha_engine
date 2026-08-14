"""Import and dispatch isolation for the CN exact ranker replay CLI.

Issue #947 route and the maintained exact replay route must not pull in the
stale legacy diagnostic modules (``cn_cal_deeper_portfolio_mapping_replay`` and
``cn_rank_blend_portfolio_replay``), which still import the removed private
``_fit_scores`` helper. Those modules are loaded lazily inside their matching
dispatch branch only.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

import pytest
import yaml

import scripts.run_cn_ranker_exact_portfolio_replay as replay_script
from src.research.cn_x1_2_breadth_veto_development import DEVELOPMENT_RUNNER_ID

_LEGACY_MODULES = (
    "src.research.cn_cal_deeper_portfolio_mapping_replay",
    "src.research.cn_rank_blend_portfolio_replay",
)


def _drop_modules(monkeypatch: pytest.MonkeyPatch, *names: str) -> None:
    for name in names:
        monkeypatch.delitem(sys.modules, name, raising=False)


def _write_spec(tmp_path: Path, payload: dict) -> Path:
    spec = tmp_path / "spec.yaml"
    spec.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return spec


def _runner_stub(key: str, calls: dict):
    def run(spec_path, output_dir):
        calls[key] = (spec_path, output_dir)
        return {"status": "completed"}

    return run


def test_import_does_not_pull_in_stale_legacy_modules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _drop_modules(monkeypatch, *_LEGACY_MODULES, replay_script.__name__)
    importlib.import_module(replay_script.__name__)
    for name in _LEGACY_MODULES:
        assert name not in sys.modules


def test_947_route_dispatches_breadth_veto_without_legacy_imports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _drop_modules(monkeypatch, *_LEGACY_MODULES)
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
    for name in _LEGACY_MODULES:
        assert name not in sys.modules


def test_exact_route_dispatches_without_legacy_imports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _drop_modules(monkeypatch, *_LEGACY_MODULES)
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
    for name in _LEGACY_MODULES:
        assert name not in sys.modules


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


def _install_fake_legacy(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    attr: str,
    key: str,
    calls: dict,
) -> None:
    module = types.ModuleType(name)
    setattr(module, attr, _runner_stub(key, calls))
    monkeypatch.setitem(sys.modules, name, module)


def test_legacy_rank_blend_route_still_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict = {}
    _install_fake_legacy(
        monkeypatch,
        "src.research.cn_rank_blend_portfolio_replay",
        "run_cn_rank_blend_portfolio_replay",
        "rank_blend",
        calls,
    )
    spec = _write_spec(tmp_path, {"rank_blend_diagnostic": {"experiment_id": "blend"}})
    out = tmp_path / "out"
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_cn_ranker_exact_portfolio_replay", "--spec", str(spec), "--output-dir", str(out)],
    )

    assert replay_script.main() == 0
    assert set(calls) == {"rank_blend"}


def test_legacy_portfolio_mapping_route_still_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: dict = {}
    _install_fake_legacy(
        monkeypatch,
        "src.research.cn_cal_deeper_portfolio_mapping_replay",
        "run_cal_deeper_portfolio_mapping_replay",
        "portfolio_mapping",
        calls,
    )
    spec = _write_spec(tmp_path, {"portfolio_mapping_diagnostic": {"experiment_id": "mapping"}})
    out = tmp_path / "out"
    monkeypatch.setattr(
        sys,
        "argv",
        ["run_cn_ranker_exact_portfolio_replay", "--spec", str(spec), "--output-dir", str(out)],
    )

    assert replay_script.main() == 0
    assert set(calls) == {"portfolio_mapping"}
