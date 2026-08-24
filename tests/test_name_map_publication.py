"""The console bundle must publish the governed CN instrument-name registry."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.artifacts.repository_research_store import (
    DEFAULT_CATALOG,
    NAME_MAP_SOURCE,
    export_repository_research_data,
)


def test_export_publishes_governed_name_map_for_console(tmp_path: Path) -> None:
    output = tmp_path / "site" / "data"

    export_repository_research_data(output, catalog_path=DEFAULT_CATALOG)

    payload = json.loads((output / "name_map.json").read_text(encoding="utf-8"))
    assert payload["research_only"] is True
    assert payload["trade_ready"] is False
    assert payload["source"] == "configs/name_map.yaml"
    name_map = payload["name_map"]
    assert isinstance(name_map, dict) and name_map


def test_name_map_covers_every_cn_selected_pool_symbol() -> None:
    registry = yaml.safe_load(NAME_MAP_SOURCE.read_text(encoding="utf-8"))
    assert isinstance(registry, dict) and registry

    pool = yaml.safe_load(
        (
            NAME_MAP_SOURCE.parents[1]
            / "configs/research_universes/cn_selected_equities_v3.yaml"
        ).read_text(encoding="utf-8")
    )
    symbols = [str(symbol) for symbol in pool["symbols"]]
    assert len(symbols) == 130

    missing = [symbol for symbol in symbols if str(registry.get(symbol, "")).strip() == ""]
    assert missing == []
