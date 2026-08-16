from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.common.runtime_settings import PROJECT_ROOT
from src.research.ranker_execution import candidate_factor_contracts, factor_expressions


@dataclass(frozen=True)
class _Candidate:
    candidate_id: str
    factor_groups: tuple[str, ...]


@dataclass(frozen=True)
class _Parent:
    universe: dict[str, Any]


@dataclass(frozen=True)
class _Spec:
    market: str
    benchmark: str
    factor_library_path: Path
    candidates: tuple[_Candidate, ...]
    parent: _Parent
    raw: dict[str, Any]


def _spec() -> _Spec:
    candidates = (
        _Candidate("baseline", ("momentum_volatility_volume",)),
        _Candidate("mixed", ("momentum_volatility_volume",)),
    )
    return _Spec(
        market="us",
        benchmark="QQQ",
        factor_library_path=PROJECT_ROOT / "configs/factor_libraries/ohlcv.yaml",
        candidates=candidates,
        parent=_Parent(universe={"source": "unused", "min_symbols": 30}),
        raw={
            "factor_library": {"source": "configs/factor_libraries/ohlcv.yaml"},
            "candidates": [
                {
                    "candidate_id": "baseline",
                    "factor_groups": ["momentum_volatility_volume"],
                },
                {
                    "candidate_id": "mixed",
                    "factor_groups": ["momentum_volatility_volume"],
                    "canonical_factor_additions": {
                        "library_sources": [
                            "src/factors/sets/qlib_alpha158.py",
                            "configs/factor_libraries/volume_stat_research.yaml",
                        ],
                        "factor_ids": [
                            "qlib_alpha158.cord10",
                            "qlib_alpha158.rank20",
                            "volume_stat_research.signed_volume_balance_10d",
                        ],
                    },
                },
            ],
        },
    )


def test_candidate_factor_contracts_append_canonical_ids_without_copying_definitions() -> None:
    contracts = candidate_factor_contracts(_spec())

    assert len(contracts["baseline"]["factor_ids"]) == 7
    assert contracts["mixed"]["factor_ids"][-3:] == (
        "qlib_alpha158.cord10",
        "qlib_alpha158.rank20",
        "volume_stat_research.signed_volume_balance_10d",
    )
    assert len(contracts["mixed"]["factor_ids"]) == 10
    assert len(contracts["mixed"]["implementation_hashes"]) == 10
    assert len(set(contracts["mixed"]["expressions"])) == 10


def test_factor_expressions_is_projection_of_canonical_contracts() -> None:
    spec = _spec()
    contracts = candidate_factor_contracts(spec)

    assert factor_expressions(spec) == {
        candidate_id: contract["expressions"]
        for candidate_id, contract in contracts.items()
    }
