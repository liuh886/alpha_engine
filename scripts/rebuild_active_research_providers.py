#!/usr/bin/env python3
"""Rebuild exact Qlib providers required by data-backed research missions."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from scripts.build_market_providers import build_market_provider
from scripts.data.refresh_selected_pool_prices import BENCHMARKS
from src.common.runtime_settings import PROJECT_ROOT
from src.data.market_provider import market_provider_path
from src.research.cross_sectional_experiment_runner import RUNNER_ID as DATA_BACKED_RUNNER
from src.research.multi_market_readiness import load_market_watchlist
from src.research.paradigm import ResearchParadigmSpec

EXPERIMENT_ROOT = PROJECT_ROOT / "configs" / "research_experiments"
SOURCE_DIR = PROJECT_ROOT / "data" / "csv_source"


@dataclass(frozen=True)
class MissionDataPlane:
    experiment_id: str
    market: str
    source_symbols: tuple[str, ...]


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected YAML mapping: {path}")
    return payload


def _resolve_repo_file(raw: str) -> Path:
    path = (PROJECT_ROOT / raw).resolve()
    path.relative_to(PROJECT_ROOT.resolve())
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _data_plane_for_spec(path: Path) -> MissionDataPlane | None:
    payload = _load_yaml(path)
    if payload.get("runner") != DATA_BACKED_RUNNER:
        return None
    fixed_model = payload.get("fixed_model") or {}
    frozen_spec = _resolve_repo_file(str(fixed_model.get("frozen_spec", "")))
    parent = ResearchParadigmSpec.from_yaml(frozen_spec)
    if parent.market not in {"us", "cn"}:
        raise ValueError(
            f"cross-sectional mission has unsupported market {parent.market!r}"
        )
    universe_path = _resolve_repo_file(str(parent.universe["source"]))
    candidates = load_market_watchlist(parent.market, watchlist_path=universe_path)
    benchmark_source = BENCHMARKS[parent.market]
    symbols = tuple(sorted({*candidates, benchmark_source}))
    missing = [
        symbol for symbol in symbols if not (SOURCE_DIR / f"{symbol}.csv").is_file()
    ]
    if missing:
        raise ValueError(
            f"mission {payload['experiment_id']} is missing canonical sources: {missing}"
        )
    return MissionDataPlane(
        experiment_id=str(payload["experiment_id"]),
        market=parent.market,
        source_symbols=symbols,
    )


def active_specs() -> list[Path]:
    return [
        path
        for path in sorted(EXPERIMENT_ROOT.glob("*.yaml"))
        if _load_yaml(path).get("active") is True
    ]


def _group_data_planes(specs: list[Path]) -> dict[str, MissionDataPlane]:
    by_market: dict[str, MissionDataPlane] = {}
    for path in specs:
        plane = _data_plane_for_spec(path)
        if plane is None:
            continue
        existing = by_market.get(plane.market)
        if existing is not None and existing.source_symbols != plane.source_symbols:
            raise ValueError(
                "simultaneous active missions in one market must share one exact "
                f"data plane: {existing.experiment_id} != {plane.experiment_id}"
            )
        by_market[plane.market] = plane
    return by_market


def _build_exact_provider(plane: MissionDataPlane) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(
        prefix=f"alpha-research-{plane.market}-sources-"
    ) as temporary:
        source_stage = Path(temporary) / "csv_source"
        source_stage.mkdir(parents=True)
        for symbol in plane.source_symbols:
            shutil.copy2(SOURCE_DIR / f"{symbol}.csv", source_stage / f"{symbol}.csv")
        return build_market_provider(
            csv_dir=source_stage,
            provider_dir=market_provider_path(PROJECT_ROOT, plane.market),
            market=plane.market,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path)
    args = parser.parse_args()

    specs = [args.spec.resolve()] if args.spec else active_specs()
    planes = _group_data_planes(specs)
    if not planes:
        print("{}")
        return 0

    reports = {market: _build_exact_provider(plane) for market, plane in planes.items()}
    summary = {
        market: {
            "experiment_id": planes[market].experiment_id,
            "provider_identity_sha256": report["provider_identity_sha256"],
            "session_count": report["calendar"]["session_count"],
            "instrument_count": report["instruments"]["count"],
            "source_symbol_count": len(planes[market].source_symbols),
        }
        for market, report in reports.items()
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
