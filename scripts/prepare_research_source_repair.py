#!/usr/bin/env python3
"""Prepare authoritative selected-pool repair artifacts for active missions.

This wrapper owns no provider logic. It detects missing committed source files and
routes repair through the repository's maintained
``refresh_selected_pool_prices_v2`` contract. Canonical sources are never
mutated; the isolated repair output must be reviewed and committed separately.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml

from scripts.data.refresh_selected_pool_prices_v2 import (
    MANIFEST_RELATIVE_PATH,
    refresh_selected_pool_prices_v2,
)
from src.common.runtime_settings import PROJECT_ROOT
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


def _active_specs() -> list[Path]:
    return [
        path
        for path in sorted(EXPERIMENT_ROOT.glob("*.yaml"))
        if _load_yaml(path).get("active") is True
    ]


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
    missing = [
        symbol
        for symbol in sorted(set(symbols))
        if not (CANONICAL_SOURCE_ROOT / f"{symbol}.csv").is_file()
    ]
    benchmark = str(parent.benchmark)
    if not (CANONICAL_SOURCE_ROOT / f"{benchmark}.csv").is_file():
        missing.append(benchmark)
    return {
        "experiment_id": str(raw["experiment_id"]),
        "market": parent.market,
        "start": str(parent.walk_forward["requested_train_start"]),
        "cutoff": cutoff,
        "missing_symbols": sorted(set(missing)),
    }


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def prepare_repairs(spec_paths: list[Path]) -> dict[str, Any]:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    missions: list[dict[str, Any]] = []
    repair_required = False

    for spec_path in spec_paths:
        context = _mission_context(spec_path)
        missing = context["missing_symbols"]
        mission: dict[str, Any] = {
            "experiment_id": context["experiment_id"],
            "market": context["market"],
            "missing_symbols": missing,
        }
        if not missing:
            mission["status"] = "canonical_sources_complete"
            missions.append(mission)
            continue

        repair_required = True
        output_root = ARTIFACT_ROOT / context["experiment_id"]
        try:
            manifest = refresh_selected_pool_prices_v2(
                root=PROJECT_ROOT,
                market=context["market"],
                source_csv_dir=CANONICAL_SOURCE_ROOT,
                output_root=output_root,
                start=context["start"],
                cutoff=context["cutoff"],
                max_rounds=2,
                full_refresh=False,
            )
            mission.update(
                {
                    "status": "repair_candidate_ready",
                    "refresh_status": manifest.get("status"),
                    "promotion_eligible": bool(manifest.get("promotion_eligible")),
                    "provider_identity_sha256": manifest.get(
                        "provider_identity_sha256"
                    ),
                    "refresh_targets": manifest.get("targets", []),
                    "manifest_path": str(
                        (output_root / MANIFEST_RELATIVE_PATH).relative_to(PROJECT_ROOT)
                    ),
                }
            )
        except Exception as exc:
            manifest_path = output_root / MANIFEST_RELATIVE_PATH
            manifest = _read_manifest(manifest_path)
            mission.update(
                {
                    "status": "repair_candidate_blocked",
                    "error": f"{type(exc).__name__}: {exc}",
                    "refresh_status": manifest.get("status"),
                    "failed_symbols": manifest.get("failed_symbols", []),
                    "manifest_path": (
                        str(manifest_path.relative_to(PROJECT_ROOT))
                        if manifest_path.is_file()
                        else None
                    ),
                }
            )
        missions.append(mission)

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
    summary = prepare_repairs(specs)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
