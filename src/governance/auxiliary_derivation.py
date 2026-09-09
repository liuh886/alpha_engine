"""Derive shared-provider auxiliaries from strategy YAMLs instead of memory.

Seven list sources describe overlapping universes; provider auxiliaries were
hand-written in two code locations. This module mechanically derives the
strategy-driven required auxiliary set per market:

  required[market] =
      (strategy pool members outside the selected pool)
      + (strategy-referenced executable instruments outside pool/benchmark)

References whose role declares a benchmark, or whose reference-registry entry
is non-executable/an index, are excluded with a recorded reason. Anything
hardcoded beyond the derived set must appear in DECLARED_EXTRAS with a citing
source; anything derived but missing from the hardcoded tuples fails the
consistency gate (that is exactly the CN_27 outage class).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]

SELECTED_UNIVERSE_PATHS = {
    "us": "configs/research_universes/us_selected_equities_v2.yaml",
    "cn": "configs/research_universes/cn_selected_equities_v3.yaml",
}
REFERENCE_REGISTRY_PATH = "configs/pools/reference_instrument_registry_v1.yaml"

# Sealed frozen-vendor provenance per strategy market. The accepted baseline
# mixes vendors per symbol (tencent QFQ for most, akshare_sina for 301291,
# akshare for the 000300 index); reproducing the blessed vendor per symbol is
# the only way a live refresh can pass the restatement gate. Pins live in a
# sparse-checkout-safe config (not beside the evidence) and are verified
# against the sealed coverage by test.
STRATEGY_VENDOR_PINS = {
    "cn": "configs/data/cn_strategy_vendor_pins_v1.yaml",
}
STRATEGY_VENDOR_PROVENANCE = {
    "cn": "artifacts/evidence/cn_all_weather_alpha_rotation_v1/coverage.csv",
}

# Strategy files whose members/references must resolve inside the shared
# formal provider. A pool whose bars travel a strategy-specific data path
# (e.g. narrow-contract-owned bars) is deliberately absent here.
STRATEGY_SOURCES: dict[str, tuple[dict[str, Any], ...]] = {
    "cn": (
        {
            "kind": "strategy_pool",
            "path": "configs/pools/cn_all_weather_alpha_rotation_v1.yaml",
            # extend_bars reads every frozen member from the shared provider.
            "shared_provider_members": True,
        },
    ),
    "us": (
        {
            "kind": "strategy_pool",
            "path": "configs/pools/us_small_pool_v2.yaml",
            # Narrow-pool members travel the strategy-specific bars path
            # (SEC fundamentals + owned fetch); only declared references
            # may require shared-provider coverage.
            "shared_provider_members": False,
        },
        {
            "kind": "strategy_bundle",
            "path": "configs/data_contracts/qqq_rotation_sgov_model_data_v1.yaml",
            "profile": "qqqi_qqq_tqqq_sgov_vix_vxn_rotation_v1",
        },
    ),
}

# Hardcoded auxiliaries beyond the derived set. Each needs a citing source;
# the gate rejects undeclared extras so legacy entries cannot hide drift.
DECLARED_EXTRAS: dict[str, dict[str, str]] = {
    "us": {
        "CGDV": "comparison reference for qqq rotation evaluation "
        "(COMPARISON_REFERENCE_AUXILIARIES; qqq v4.12-v4.20 research family)",
        "TYGO": "legacy TIGO-substitution guard; TYGO is a selected-pool "
        "candidate so the build filters it out of auxiliaries "
        "(reference registry comment; test_formal_auxiliary_universe_"
        "preserves_legacy_tygo_without_substitution)",
    },
    "cn": {},
}


def normalize_symbol(raw: object) -> str:
    """Canonicalize pool/reference/provider spellings to auxiliary identity."""
    text = str(raw or "").strip().upper().lstrip("^")
    if "." in text:
        text = text.split(".", 1)[0]
    return text


def _load_yaml(root: Path, relative: str) -> Any:
    path = root / relative
    if not path.is_file():
        raise ValueError(f"auxiliary derivation source is missing: {relative}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _pool_members(pool: Mapping[str, Any]) -> list[str]:
    members: list[str] = []
    symbols = pool.get("symbols")
    if isinstance(symbols, list):
        for entry in symbols:
            symbol = entry.get("symbol") if isinstance(entry, Mapping) else entry
            if str(symbol or "").strip():
                members.append(normalize_symbol(symbol))
    baskets = pool.get("baskets")
    if isinstance(baskets, Mapping):
        for basket in baskets.values():
            if not isinstance(basket, Mapping):
                continue
            for symbol in basket.get("symbols") or []:
                if str(symbol or "").strip():
                    members.append(normalize_symbol(symbol))
    return members


def _pool_references(pool: Mapping[str, Any], source: str) -> list[tuple[str, str, str]]:
    """Return (symbol, role, provenance) for declared reference instruments."""
    found: list[tuple[str, str, str]] = []
    references = pool.get("references")
    if isinstance(references, Mapping):
        for key, entry in references.items():
            if not isinstance(entry, Mapping):
                continue
            symbol = entry.get("symbol") or entry.get("provider_symbol") or key
            role = str(entry.get("role") or "")
            if str(symbol or "").strip():
                found.append((normalize_symbol(symbol), role, f"{source}:references"))
    return found


@dataclass
class DerivedAuxiliaries:
    market: str
    required: list[str] = field(default_factory=list)
    provenance: dict[str, str] = field(default_factory=dict)
    excluded: dict[str, str] = field(default_factory=dict)


def _executable_lookup(registry: Mapping[str, Any]) -> dict[str, bool]:
    lookup: dict[str, bool] = {}
    markets = registry.get("markets")
    if not isinstance(markets, Mapping):
        return lookup
    for instruments in markets.values():
        if not isinstance(instruments, Mapping):
            continue
        entries = instruments.get("instruments")
        if not isinstance(entries, Mapping):
            continue
        for entry in entries.values():
            if not isinstance(entry, Mapping):
                continue
            canonical = normalize_symbol(entry.get("canonical_symbol"))
            if not canonical:
                continue
            instrument_type = str(entry.get("instrument_type") or "").lower()
            executable = (
                bool(entry.get("executable", False))
                and "index" not in instrument_type
            )
            lookup[canonical] = executable
            aliases = entry.get("provider_aliases") or []
            for alias in aliases:
                lookup.setdefault(normalize_symbol(alias), executable)
    return lookup


def derive_required_auxiliaries(
    repository_root: Path | str = REPOSITORY_ROOT,
) -> dict[str, DerivedAuxiliaries]:
    """Derive the strategy-driven required auxiliary set per market."""
    root = Path(repository_root).resolve()
    registry = _load_yaml(root, REFERENCE_REGISTRY_PATH)
    executable = _executable_lookup(registry if isinstance(registry, Mapping) else {})
    derived: dict[str, DerivedAuxiliaries] = {}
    for market, sources in STRATEGY_SOURCES.items():
        universe = _load_yaml(root, SELECTED_UNIVERSE_PATHS[market])
        selected = {normalize_symbol(value) for value in universe.get("symbols", [])}
        result = DerivedAuxiliaries(market=market)
        documents = [
            (source, _load_yaml(root, str(source["path"]))) for source in sources
        ]
        benchmarks = set()
        for source, document in documents:
            if source["kind"] == "strategy_pool":
                for symbol, role, _ in _pool_references(
                    document, str(source["path"])
                ):
                    if "benchmark" in role.lower():
                        benchmarks.add(symbol)
        for source, document in documents:
            relative = str(source["path"])
            if source["kind"] == "strategy_pool":
                if source.get("shared_provider_members", True):
                    members = _pool_members(document)
                    for symbol in members:
                        if symbol in selected:
                            continue
                        if symbol not in result.provenance:
                            result.required.append(symbol)
                            result.provenance[symbol] = f"{relative}:pool_members"
                else:
                    for symbol in _pool_members(document):
                        if symbol in selected or symbol in result.excluded:
                            continue
                        result.excluded.setdefault(
                            symbol,
                            f"pool members travel strategy-specific data path "
                            f"({relative})",
                        )
                for symbol, role, provenance in _pool_references(document, relative):
                    _classify_reference(
                        result, selected, executable, symbol, role, provenance
                    )
            elif source["kind"] == "strategy_bundle":
                profiles = document.get("profiles") or {}
                profile = profiles.get(source["profile"], {})
                for symbol in profile.get("candidate_symbols") or []:
                    normalized = normalize_symbol(symbol)
                    if normalized in selected or normalized in result.provenance:
                        continue
                    if normalized in benchmarks:
                        result.excluded.setdefault(
                            normalized,
                            f"market benchmark ({relative}:profiles/"
                            f"{source['profile']}/candidate_symbols)",
                        )
                        continue
                    result.required.append(normalized)
                    result.provenance[normalized] = (
                        f"{relative}:profiles/{source['profile']}/candidate_symbols"
                    )
                for reference in profile.get("references") or []:
                    normalized = normalize_symbol(reference)
                    _classify_reference(
                        result,
                        selected,
                        executable,
                        normalized,
                        role="strategy_reference",
                        provenance=(
                            f"{relative}:profiles/{source['profile']}/references"
                        ),
                    )
        result.required.sort()
        derived[market] = result
    return derived


def _classify_reference(
    result: DerivedAuxiliaries,
    selected: set[str],
    executable: Mapping[str, bool],
    symbol: str,
    role: str,
    provenance: str,
) -> None:
    if not symbol or symbol in selected or symbol in result.provenance:
        if symbol and symbol in selected:
            result.excluded.setdefault(symbol, f"selected-pool candidate ({provenance})")
        return
    if "benchmark" in role.lower():
        result.excluded[symbol] = f"benchmark role '{role}' ({provenance})"
        return
    if symbol in executable and not executable[symbol]:
        result.excluded[symbol] = (
            f"non-executable/index reference ({provenance})"
        )
        return
    result.required.append(symbol)
    result.provenance[symbol] = provenance


def verify_against_hardcoded(
    hardcoded: Mapping[str, tuple[str, ...] | list[str]],
    repository_root: Path | str = REPOSITORY_ROOT,
) -> dict[str, dict[str, list[str]]]:
    """Compare derived requirements with hardcoded auxiliary tuples.

    Returns per market {"missing": [...], "undeclared_extras": [...]}.
    Missing entries are fail-closed gate violations; undeclared extras are
    hardcoded symbols no strategy source justifies.
    """
    derived = derive_required_auxiliaries(repository_root)
    report: dict[str, dict[str, list[str]]] = {}
    for market, result in derived.items():
        required = {normalize_symbol(value) for value in result.required}
        coded = {normalize_symbol(value) for value in hardcoded.get(market, ())}
        declared = {normalize_symbol(value) for value in DECLARED_EXTRAS.get(market, {})}
        report[market] = {
            "missing": sorted(required - coded),
            "undeclared_extras": sorted(coded - required - declared),
        }
    return report


def strategy_symbol_vendor_overrides(
    repository_root: Path | str = REPOSITORY_ROOT,
) -> dict[str, dict[str, str]]:
    """Map strategy symbols to their blessed frozen vendor per market.

    Reads the versioned vendor-pins config (sparse-checkout safe, hash-bound
    into the provider contract). Pins reorder the vendor chain per symbol;
    fallbacks stay intact. Use :func:`strategy_vendor_provenance` to verify
    the pins against the sealed frozen coverage.
    """
    import yaml as _yaml

    root = Path(repository_root).resolve()
    overrides: dict[str, dict[str, str]] = {}
    for market, relative in STRATEGY_VENDOR_PINS.items():
        path = root / relative
        if not path.is_file():
            raise ValueError(f"strategy vendor pins are missing: {relative}")
        document = _yaml.safe_load(path.read_text(encoding="utf-8"))
        markets = (document or {}).get("markets", {})
        pins = markets.get(market, {})
        if not isinstance(pins, dict) or not pins:
            raise ValueError(f"strategy vendor pins are empty: {relative}")
        market_overrides: dict[str, str] = {}
        for raw_symbol, vendor in pins.items():
            symbol = normalize_symbol(raw_symbol)
            vendor_name = str(vendor or "").strip().lower()
            if symbol and vendor_name:
                market_overrides[symbol] = vendor_name
                # Alias without leading zeros: router callers pass both
                # bare ("2156") and zero-padded ("002156") spellings, and
                # a pin that silently misses reverts to the default chain.
                stripped = symbol.lstrip("0")
                if stripped and stripped != symbol:
                    market_overrides.setdefault(stripped, vendor_name)
        overrides[market] = market_overrides
    return overrides


def strategy_vendor_provenance(
    repository_root: Path | str = REPOSITORY_ROOT,
) -> dict[str, dict[str, str]]:
    """Derive symbol->vendor directly from sealed frozen coverage (audit)."""
    import csv

    root = Path(repository_root).resolve()
    provenance: dict[str, dict[str, str]] = {}
    for market, relative in STRATEGY_VENDOR_PROVENANCE.items():
        path = root / relative
        if not path.is_file():
            raise ValueError(f"strategy vendor provenance is missing: {relative}")
        market_provenance: dict[str, str] = {}
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                symbol = normalize_symbol(row.get("symbol"))
                vendor = str(row.get("provider") or "").strip().lower()
                if symbol and vendor:
                    market_provenance[symbol] = vendor
        provenance[market] = market_provenance
    return provenance
