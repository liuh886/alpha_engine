"""Focused tests for snapshot-cutoff data planes in the research provider rebuild."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import scripts.rebuild_active_research_providers as rebuild
from scripts.rebuild_active_research_providers import (
    MissionDataPlane,
    _data_plane_for_spec,
    _group_data_planes,
)
from src.research.cross_sectional_experiment_runner import RUNNER_ID as DATA_BACKED_RUNNER


class _FakeParadigm:
    market = "cn"
    universe = {"source": "universe.yaml"}


def test_data_plane_reads_snapshot_cutoff(tmp_path: Path, monkeypatch) -> None:
    spec = tmp_path / "mission.yaml"
    spec.write_text(
        yaml.safe_dump(
            {
                "experiment_id": "cn_test_mission",
                "runner": DATA_BACKED_RUNNER,
                "snapshot": {"cutoff": "2026-06-30"},
                "fixed_model": {"frozen_spec": "paradigm.yaml"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "paradigm.yaml").write_text(
        "market: cn\nuniverse:\n  source: universe.yaml\n", encoding="utf-8"
    )
    (tmp_path / "universe.yaml").write_text(
        yaml.safe_dump({"market": "cn", "symbols": ["000001"], "candidate_count": 1}),
        encoding="utf-8",
    )
    source_dir = tmp_path / "csv_source"
    source_dir.mkdir()
    (source_dir / "000001.csv").write_text("date\n2026-06-30\n", encoding="utf-8")
    (source_dir / "000300.csv").write_text("date\n2026-06-30\n", encoding="utf-8")

    monkeypatch.setattr(rebuild, "_resolve_repo_file", lambda raw: (tmp_path / raw).resolve())
    monkeypatch.setattr(
        rebuild.ResearchParadigmSpec,
        "from_yaml",
        lambda _path: _FakeParadigm(),
    )
    monkeypatch.setattr(rebuild, "load_market_watchlist", lambda market, watchlist_path: ["000001"])
    monkeypatch.setattr(rebuild, "SOURCE_DIR", source_dir)

    plane = _data_plane_for_spec(spec)
    assert plane is not None
    assert plane.cutoff == "2026-06-30"
    assert plane.market == "cn"
    assert plane.source_symbols == ("000001", "000300")  # benchmark is appended


def test_data_plane_missing_cutoff_is_rejected(tmp_path: Path, monkeypatch) -> None:
    spec = tmp_path / "mission.yaml"
    spec.write_text(
        yaml.safe_dump(
            {
                "experiment_id": "cn_test_mission",
                "runner": DATA_BACKED_RUNNER,
                "fixed_model": {"frozen_spec": "paradigm.yaml"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rebuild, "_resolve_repo_file", lambda raw: (tmp_path / raw).resolve())
    monkeypatch.setattr(
        rebuild.ResearchParadigmSpec,
        "from_yaml",
        lambda _path: _FakeParadigm(),
    )
    monkeypatch.setattr(rebuild, "load_market_watchlist", lambda market, watchlist_path: ["000001"])
    source_dir = tmp_path / "csv_source"
    source_dir.mkdir()
    (source_dir / "000001.csv").write_text("date\n2026-06-30\n", encoding="utf-8")
    (source_dir / "000300.csv").write_text("date\n2026-06-30\n", encoding="utf-8")
    monkeypatch.setattr(rebuild, "SOURCE_DIR", source_dir)

    with pytest.raises(ValueError, match="missing snapshot.cutoff"):
        _data_plane_for_spec(spec)


def test_data_plane_invalid_cutoff_is_rejected(tmp_path: Path, monkeypatch) -> None:
    spec = tmp_path / "mission.yaml"
    spec.write_text(
        yaml.safe_dump(
            {
                "experiment_id": "cn_test_mission",
                "runner": DATA_BACKED_RUNNER,
                "snapshot": {"cutoff": "2026/06/30"},
                "fixed_model": {"frozen_spec": "paradigm.yaml"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(rebuild, "_resolve_repo_file", lambda raw: (tmp_path / raw).resolve())
    monkeypatch.setattr(
        rebuild.ResearchParadigmSpec,
        "from_yaml",
        lambda _path: _FakeParadigm(),
    )
    monkeypatch.setattr(rebuild, "load_market_watchlist", lambda market, watchlist_path: ["000001"])
    source_dir = tmp_path / "csv_source"
    source_dir.mkdir()
    (source_dir / "000001.csv").write_text("date\n2026-06-30\n", encoding="utf-8")
    (source_dir / "000300.csv").write_text("date\n2026-06-30\n", encoding="utf-8")
    monkeypatch.setattr(rebuild, "SOURCE_DIR", source_dir)

    with pytest.raises(ValueError, match="must be a YYYY-MM-DD ISO date"):
        _data_plane_for_spec(spec)


def _plane(experiment_id: str, market: str, cutoff: str) -> MissionDataPlane:
    return MissionDataPlane(
        experiment_id=experiment_id,
        market=market,
        cutoff=cutoff,
        source_symbols=("000001", "000300"),
    )


def _group(monkeypatch, specs: list[Path], by_path: dict[str, MissionDataPlane]):
    monkeypatch.setattr(rebuild, "_data_plane_for_spec", lambda path: by_path[str(path)])
    return _group_data_planes(specs)


def test_group_data_planes_merges_same_cutoff_and_symbols(monkeypatch) -> None:
    specs = [Path(f"{experiment_id}.yaml") for experiment_id in ("a", "b")]
    by_path = {
        str(specs[0]): _plane("a", "cn", "2026-06-30"),
        str(specs[1]): _plane("b", "cn", "2026-06-30"),
    }
    grouped = _group(monkeypatch, specs, by_path)
    assert grouped["cn"].cutoff == "2026-06-30"
    assert grouped["cn"].source_symbols == ("000001", "000300")


def test_group_data_planes_rejects_cutoff_conflict(monkeypatch) -> None:
    specs = [Path(f"{experiment_id}.yaml") for experiment_id in ("a", "b")]
    by_path = {
        str(specs[0]): _plane("a", "cn", "2026-06-30"),
        str(specs[1]): _plane("b", "cn", "2026-08-11"),
    }
    with pytest.raises(ValueError, match="one exact data plane"):
        _group(monkeypatch, specs, by_path)


def test_group_data_planes_rejects_symbol_conflict(monkeypatch) -> None:
    specs = [Path(f"{experiment_id}.yaml") for experiment_id in ("a", "b")]
    conflicting = MissionDataPlane(
        experiment_id="b",
        market="cn",
        cutoff="2026-06-30",
        source_symbols=("000002", "000300"),
    )
    by_path = {
        str(specs[0]): _plane("a", "cn", "2026-06-30"),
        str(specs[1]): conflicting,
    }
    with pytest.raises(ValueError, match="one exact data plane"):
        _group(monkeypatch, specs, by_path)


def test_group_data_planes_separates_markets_by_cutoff(monkeypatch) -> None:
    specs = [Path(f"{experiment_id}.yaml") for experiment_id in ("cn", "us")]
    by_path = {
        str(specs[0]): _plane("cn", "cn", "2026-06-30"),
        str(specs[1]): MissionDataPlane(
            experiment_id="us",
            market="us",
            cutoff="2026-06-24",
            source_symbols=("AAPL", "QQQ"),
        ),
    }
    grouped = _group(monkeypatch, specs, by_path)
    assert grouped["cn"].cutoff == "2026-06-30"
    assert grouped["us"].cutoff == "2026-06-24"
