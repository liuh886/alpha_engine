#!/usr/bin/env python3
"""Rebuild Qlib providers required by active research missions from repository sources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from scripts.build_market_providers import build_market_provider
from src.common.runtime_settings import PROJECT_ROOT
from src.data.market_provider import market_provider_path
from src.research.paradigm import ResearchParadigmSpec

EXPERIMENT_ROOT = PROJECT_ROOT / "configs" / "research_experiments"
SOURCE_DIR = PROJECT_ROOT / "data" / "csv_source"


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


def active_markets() -> list[str]:
    markets: set[str] = set()
    for path in sorted(EXPERIMENT_ROOT.glob("*.yaml")):
        payload = _load_yaml(path)
        if payload.get("active") is not True:
            continue
        fixed_model = payload.get("fixed_model") or {}
        frozen_spec = _resolve_repo_file(str(fixed_model.get("frozen_spec", "")))
        parent = ResearchParadigmSpec.from_yaml(frozen_spec)
        if parent.market not in {"us", "cn"}:
            raise ValueError(
                f"active cross-sectional mission has unsupported market {parent.market!r}"
            )
        markets.add(parent.market)
    return sorted(markets)


def main() -> int:
    markets = active_markets()
    if not markets:
        print("{}")
        return 0

    reports: dict[str, dict[str, Any]] = {}
    for market in markets:
        reports[market] = build_market_provider(
            csv_dir=SOURCE_DIR,
            provider_dir=market_provider_path(PROJECT_ROOT, market),
            market=market,
        )
    summary = {
        market: {
            "provider_identity_sha256": report["provider_identity_sha256"],
            "session_count": report["calendar"]["session_count"],
            "instrument_count": report["instruments"]["count"],
        }
        for market, report in reports.items()
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
