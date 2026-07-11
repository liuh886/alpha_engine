from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import yaml

from src.research.multi_market_readiness import normalize_market_symbol
from src.research.paradigm import load_research_paradigm_spec
from src.research.spec_bound_execution import (
    build_declared_execution_contract,
    contract_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
CASES = (
    (
        ROOT / "configs/research_paradigms/cn_10d_csi300_baseline.yaml",
        "cn",
        {"000300", "000905", "399006", "159757", "159997", "510050", "510300", "512000", "513130", "515000"},
    ),
    (
        ROOT / "configs/research_paradigms/us_10d_qqq_baseline.yaml",
        "us",
        {"QQQ", "SPY", "XOP", "SPCX"},
    ),
)


def _universe_payload(source: str) -> dict:
    payload = yaml.safe_load((ROOT / source).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_canonical_paradigms_use_versioned_equity_universes() -> None:
    for spec_path, market, excluded in CASES:
        spec = load_research_paradigm_spec(spec_path)
        source = str(spec.universe["source"])
        assert source.startswith("configs/research_universes/")
        assert source != "configs/watchlist.yaml"
        assert spec.universe["universe_id"]
        assert spec.universe["membership_mode"] == "static_curated"
        assert spec.universe["membership_as_of"] == "2026-07-11"
        assert spec.universe["asset_type"] == "equity"
        assert spec.universe["survivorship_bias"] is True

        payload = _universe_payload(source)
        metadata = payload["metadata"]
        assert metadata["universe_id"] == spec.universe["universe_id"]
        assert metadata["membership_mode"] == spec.universe["membership_mode"]
        assert metadata["membership_as_of"] == spec.universe["membership_as_of"]
        assert metadata["asset_type"] == spec.universe["asset_type"]
        assert metadata["survivorship_bias"] is spec.universe["survivorship_bias"]

        raw = payload[market]
        assert isinstance(raw, list) and raw
        assert all(isinstance(symbol, str) for symbol in raw)
        normalized = [
            normalize_market_symbol(market, symbol).normalized_symbol
            for symbol in raw
        ]
        assert len(normalized) == len(set(normalized))
        assert normalize_market_symbol(market, spec.benchmark).normalized_symbol not in normalized
        assert excluded.isdisjoint(normalized)
        assert len(normalized) >= int(spec.universe["min_symbols"])

        if market == "cn":
            assert all(symbol.isdigit() and len(symbol) == 6 for symbol in normalized)


def test_versioned_universe_source_hash_binds_membership_metadata(tmp_path: Path) -> None:
    spec = load_research_paradigm_spec(CASES[0][0])
    source = ROOT / str(spec.universe["source"])
    payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)

    copied_source = tmp_path / "cn_universe.yaml"
    copied_source.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    copied_universe = dict(spec.universe)
    copied_universe["source"] = str(copied_source)
    copied_spec = replace(spec, universe=copied_universe)
    first = build_declared_execution_contract(copied_spec)

    payload["metadata"]["membership_as_of"] = "2026-07-10"
    copied_source.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    second = build_declared_execution_contract(copied_spec)

    assert first["universe"]["source"] == second["universe"]["source"]
    assert first["universe"]["source_sha256"] != second["universe"]["source_sha256"]
    assert contract_sha256(first) != contract_sha256(second)
