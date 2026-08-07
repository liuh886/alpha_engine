#!/usr/bin/env python3
"""Prepare reviewable source files for missing active-research universe members.

Canonical research sources are never mutated here. Missing US source files are
fetched through the maintained YFinanceAdapter into an artifact directory. The
workflow must stop until those files are reviewed and committed separately.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from src.common.runtime_settings import PROJECT_ROOT
from src.data.adapters.base import DataFetchError, FetchRequest
from src.data.adapters.yfinance_adapter import YFinanceAdapter
from src.research.multi_market_readiness import load_market_watchlist
from src.research.paradigm import ResearchParadigmSpec

EXPERIMENT_ROOT = PROJECT_ROOT / "configs" / "research_experiments"
CANONICAL_SOURCE_ROOT = PROJECT_ROOT / "data" / "csv_source"
ARTIFACT_ROOT = PROJECT_ROOT / "artifacts" / "research_source_repair"


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


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _active_specs() -> list[Path]:
    result: list[Path] = []
    for path in sorted(EXPERIMENT_ROOT.glob("*.yaml")):
        if _load_yaml(path).get("active") is True:
            result.append(path)
    return result


def _mission_context(path: Path) -> dict[str, Any]:
    raw = _load_yaml(path)
    fixed_model = raw.get("fixed_model") or {}
    parent_path = _resolve_repo_file(str(fixed_model.get("frozen_spec", "")))
    parent = ResearchParadigmSpec.from_yaml(parent_path)
    universe_path = _resolve_repo_file(str(parent.universe["source"]))
    symbols = load_market_watchlist(parent.market, watchlist_path=universe_path)
    cutoff = str((raw.get("snapshot") or {}).get("cutoff", "")).strip()
    if not cutoff:
        raise ValueError(f"experiment {path} does not declare snapshot.cutoff")
    return {
        "experiment_id": str(raw["experiment_id"]),
        "market": parent.market,
        "start": str(parent.walk_forward["requested_train_start"]),
        "cutoff": cutoff,
        "symbols": sorted(set(symbols)),
        "benchmark": parent.benchmark,
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _fetch_us_gap(
    *,
    symbol: str,
    start: str,
    cutoff: str,
    output_dir: Path,
) -> dict[str, Any]:
    adapter = YFinanceAdapter()
    request = FetchRequest(symbol=symbol, market="us", start=start, end=cutoff)
    result = adapter.fetch_daily_bars(request)
    destination = output_dir / f"{symbol}.csv"
    result.df.to_csv(destination, index=False, date_format="%Y-%m-%d")
    dates = result.df["date"]
    return {
        "symbol": symbol,
        "status": "fetched_candidate",
        "provider": result.provider,
        "provider_symbol": result.provider_symbol,
        "requested_start": start,
        "requested_end": cutoff,
        "rows": int(len(result.df)),
        "first_date": str(dates.min().date()),
        "last_date": str(dates.max().date()),
        "sha256": _sha256(destination),
        "artifact_path": str(destination.relative_to(PROJECT_ROOT)),
    }


def prepare_source_repairs(spec_paths: list[Path]) -> dict[str, Any]:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    missions: list[dict[str, Any]] = []
    repair_required = False

    for spec_path in spec_paths:
        context = _mission_context(spec_path)
        mission_dir = ARTIFACT_ROOT / context["experiment_id"]
        mission_dir.mkdir(parents=True, exist_ok=True)
        rows: list[dict[str, Any]] = []

        missing = [
            symbol
            for symbol in context["symbols"]
            if not (CANONICAL_SOURCE_ROOT / f"{symbol}.csv").is_file()
        ]
        for symbol in missing:
            repair_required = True
            if context["market"] != "us":
                rows.append(
                    {
                        "symbol": symbol,
                        "status": "missing_no_approved_fetcher",
                        "market": context["market"],
                    }
                )
                continue
            try:
                rows.append(
                    _fetch_us_gap(
                        symbol=symbol,
                        start=context["start"],
                        cutoff=context["cutoff"],
                        output_dir=mission_dir,
                    )
                )
            except DataFetchError as exc:
                rows.append(
                    {
                        "symbol": symbol,
                        "status": "fetch_failed",
                        "provider": "yfinance",
                        "error": str(exc),
                    }
                )

        manifest = {
            "schema_version": "1.0",
            "experiment_id": context["experiment_id"],
            "market": context["market"],
            "canonical_source_root": "data/csv_source",
            "requested_start": context["start"],
            "requested_end": context["cutoff"],
            "universe_count": len(context["symbols"]),
            "missing_count": len(missing),
            "missing_symbols": missing,
            "benchmark": context["benchmark"],
            "candidates": rows,
        }
        _write_json(mission_dir / "manifest.json", manifest)
        missions.append(manifest)

    summary = {
        "schema_version": "1.0",
        "repair_required": repair_required,
        "missions": missions,
    }
    _write_json(ARTIFACT_ROOT / "summary.json", summary)
    marker = ARTIFACT_ROOT / "repair_required"
    if repair_required:
        marker.write_text("canonical research source repair required\n", encoding="utf-8")
    elif marker.exists():
        marker.unlink()
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path)
    args = parser.parse_args()

    specs = [args.spec.resolve()] if args.spec else _active_specs()
    summary = prepare_source_repairs(specs)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
