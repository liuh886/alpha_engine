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


def _raw_symbols(source: str, market: str) -> list[object]:
    payload = yaml.safe_load((ROOT / source).read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    symbols = payload[market]
    assert isinstance(symbols, list)
    return symbols


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

        raw = _raw_symbols(source, market)
        assert raw
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


def test_universe_identity_metadata_is_bound_into_execution_contract() -> None:
    spec = load_research_paradigm_spec(CASES[0][0])
    contract = build_declared_execution_contract(spec)

    assert contract["universe"]["universe_id"] == spec.universe["universe_id"]
    assert contract["universe"]["membership_mode"] == "static_curated"
    assert contract["universe"]["membership_as_of"] == "2026-07-11"
    assert contract["universe"]["asset_type"] == "equity"
    assert contract["universe"]["survivorship_bias"] is True

    changed_universe = dict(spec.universe)
    changed_universe["membership_as_of"] = "2026-07-10"
    changed = replace(spec, universe=changed_universe)
    changed_contract = build_declared_execution_contract(changed)

    assert contract_sha256(contract) != contract_sha256(changed_contract)
