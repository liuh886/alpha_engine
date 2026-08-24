"""Gate: the governed CN instrument-name registry covers the selected pool.

Export wiring itself is exercised by the repository research store tests;
this module guards registry completeness against pool membership drift.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from src.artifacts.repository_research_store import NAME_MAP_SOURCE


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
