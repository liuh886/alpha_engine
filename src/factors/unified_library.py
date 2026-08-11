"""Unified Factor Library — single access point for all factor definitions.

Aggregates factor definitions from:
- OHLCV YAML library (24 factors, 10 groups)
- Strategy inputs YAML (16 factors)
- Fundamental factor configs (3 factors)
- FactorRegistry DB (264 factors, 20 Active + 244 Proposed)
- Qlib Alpha158 factor set (158 factors)

Provides a programmatic API that any component can use:
- DataFoundation (offline optimization + online execution)
- Optimization runners (parameter search)
- Signal execution engine (live trading)
- Research agents (factor discovery)
- Model training pipelines
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from src.factors.definition import FactorDefinition


@dataclass
class FactorRecord:
    """Unified factor record across all sources."""
    factor_id: str
    display_name: str
    expression: str
    information_family: str
    namespace: str
    factor_version: str = "1.0"
    markets: tuple[str, ...] = ("us", "cn")
    status: str = "active"
    minimum_lookback: int = 0
    required_fields: tuple[str, ...] = ()
    implementation_hash: str = ""
    source: str = "unknown"  # "ohlcv_yaml", "strategy_yaml", "registry_db", "alpha158"

    @property
    def is_us(self) -> bool: return "us" in self.markets

    @property
    def is_cn(self) -> bool: return "cn" in self.markets

    @property
    def is_active(self) -> bool: return self.status in ("active", "Active", "independent_validation_required")

    @property
    def is_proposed(self) -> bool: return self.status in ("proposed", "Proposed", "unvalidated_formula", "candidate")

    def to_definition(self) -> FactorDefinition:
        return FactorDefinition(
            factor_id=self.factor_id,
            factor_version=self.factor_version,
            namespace=self.namespace,
            display_name=self.display_name,
            expression=self.expression,
            information_family=self.information_family,
            source_name=self.source,
            source_version="1.0",
            required_fields=list(self.required_fields),
            markets=list(self.markets),
            minimum_lookback=self.minimum_lookback,
            availability_lag_sessions=0,
            adjustment_requirement="adjusted",
            output_frequency="day",
            output_dtype="float64",
            missing_value_policy="preserve_nan_after_warmup",
            status=self.status,
        )


@dataclass
class FactorGroup:
    """Named group of factor IDs."""
    name: str
    description: str
    factor_ids: tuple[str, ...]
    market: str = ""  # "us", "cn", or "" for both
    tags: tuple[str, ...] = ()


@dataclass
class FactorLibrary:
    """Unified factor library — aggregated from all sources.

    Usage:
        lib = FactorLibrary()
        lib.load_all()

        # Query
        active_us = lib.query(market="us", status="active")
        momentum = lib.query(family="momentum")
        cn_factors = lib.cn_factors()

        # Groups
        groups = lib.list_groups()
        custom = lib.create_group("my_group", [...], "us")

        # Discovery
        proposed = lib.proposed_factors()  # 244 factors waiting for validation

        # Integration
        exprs = lib.expressions_for_groups(["momentum_volatility_volume"])
    """

    factors: dict[str, FactorRecord] = field(default_factory=dict)
    groups: dict[str, FactorGroup] = field(default_factory=dict)
    _loaded: bool = field(default=False, repr=False)

    # ---- Loading ----

    def load_all(self, project_root: Path | str = ".") -> None:
        """Load factors from all available sources."""
        root = Path(project_root)
        self._load_ohlcv_yaml(root)
        self._load_strategy_yaml(root)
        self._load_fundamental_configs(root)
        self._load_registry_db(root)
        self._load_alpha158()
        self._loaded = True

    def _load_ohlcv_yaml(self, root: Path):
        path = root / "configs/factor_libraries/ohlcv.yaml"
        if not path.is_file():
            return
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        factors_raw = raw.get("factors", {})
        groups_raw = raw.get("groups", {})
        defaults = raw.get("defaults", {})

        for fid, fdef in factors_raw.items():
            self.factors[fid] = FactorRecord(
                factor_id=fid,
                display_name=fdef.get("display_name", fid),
                expression=fdef["expression"],
                information_family=fdef.get("information_family", "unknown"),
                namespace=defaults.get("namespace", "ohlcv"),
                markets=tuple(fdef.get("markets", ["us", "cn"])),
                status=fdef.get("status", "active"),
                minimum_lookback=fdef.get("minimum_lookback", 0),
                required_fields=tuple(fdef.get("required_fields", [])),
                source="ohlcv_yaml",
            )

        for gname, gdef in groups_raw.items():
            self.groups[gname] = FactorGroup(
                name=gname,
                description=gdef.get("description", ""),
                factor_ids=tuple(gdef.get("factor_ids", [])),
                market=_infer_market(gname),
            )

    def _load_strategy_yaml(self, root: Path):
        path = root / "configs/factor_libraries/strategy_inputs.yaml"
        if not path.is_file():
            return
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        defaults = raw.get("defaults", {})
        for fid, fdef in raw.get("factors", {}).items():
            self.factors[fid] = FactorRecord(
                factor_id=fid,
                display_name=fdef.get("display_name", fid),
                expression=fdef["expression"],
                information_family=fdef.get("information_family", "unknown"),
                namespace=defaults.get("namespace", "strategy"),
                markets=tuple(fdef.get("markets", ["us"])),
                status=fdef.get("status", "independent_validation_required"),
                source="strategy_yaml",
            )

    def _load_fundamental_configs(self, root: Path):
        for path in (root / "configs/factors").glob("*.yaml"):
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            fid = raw.get("factor_contract_id", raw.get("stable_factor_key", path.stem))
            components = raw.get("components", {})
            expr_parts = []
            for comp_name, comp_def in components.items():
                expr_parts.append(comp_def.get("definition", comp_name))
            expression = " + ".join(expr_parts) if expr_parts else "see_contract"

            self.factors[f"fundamental.{fid}"] = FactorRecord(
                factor_id=f"fundamental.{fid}",
                display_name=raw.get("factor_contract_id", fid),
                expression=expression,
                information_family="fundamental",
                namespace="fundamental",
                markets=(raw.get("market", "us"),),
                status=raw.get("status", "frozen_pre_evaluation"),
                source="fundamental_config",
            )

    def _load_registry_db(self, root: Path):
        db_path = root / "artifacts/factor_registry.db"
        if not db_path.is_file():
            return
        try:
            conn = sqlite3.connect(str(db_path))
            cur = conn.execute(
                "SELECT name, expression, category, stage FROM factors"
            )
            for row in cur.fetchall():
                name, expr, cat, stage = row
                fid = f"registry.{name}" if name else None
                if fid is None:
                    continue
                if fid in self.factors:
                    continue  # Prefer YAML definition
                self.factors[fid] = FactorRecord(
                    factor_id=fid,
                    display_name=name or fid,
                    expression=expr or "",
                    information_family=cat or "unknown",
                    namespace="registry",
                    markets=("us", "cn"),
                    status=(stage or "Proposed").lower(),
                    source="registry_db",
                )
            conn.close()
        except Exception as e:
            pass  # DB may be locked or corrupted

    def _load_alpha158(self):
        try:
            from src.factors.sets.qlib_alpha158 import ALPHA158
            for item in ALPHA158 if isinstance(ALPHA158, list) else []:
                if isinstance(item, dict):
                    fid = item.get("name", "")
                    self.factors[f"alpha158.{fid}"] = FactorRecord(
                        factor_id=f"alpha158.{fid}",
                        display_name=item.get("name", fid),
                        expression=item.get("expression", ""),
                        information_family=item.get("category", "alpha158"),
                        namespace="alpha158",
                        markets=("us", "cn"),
                        status="proposed",
                        source="alpha158",
                    )
        except ImportError:
            pass

    # ---- Query API ----

    def query(
        self,
        market: str | None = None,
        status: str | None = None,
        family: str | None = None,
        source: str | None = None,
        active_only: bool = False,
    ) -> list[FactorRecord]:
        """Query factors with filters."""
        results = list(self.factors.values())
        if market:
            results = [f for f in results if market in f.markets]
        if status:
            results = [f for f in results if f.status == status or status in f.status]
        if family:
            results = [f for f in results if family in f.information_family]
        if source:
            results = [f for f in results if f.source == source]
        if active_only:
            results = [f for f in results if f.is_active]
        return sorted(results, key=lambda f: (f.information_family, f.factor_id))

    def us_factors(self, active_only: bool = True) -> list[FactorRecord]:
        return self.query(market="us", active_only=active_only)

    def cn_factors(self, active_only: bool = True) -> list[FactorRecord]:
        return self.query(market="cn", active_only=active_only)

    def active_factors(self) -> list[FactorRecord]:
        return [f for f in self.factors.values() if f.is_active]

    def proposed_factors(self) -> list[FactorRecord]:
        return [f for f in self.factors.values() if f.is_proposed]

    def by_family(self) -> dict[str, list[FactorRecord]]:
        result: dict[str, list[FactorRecord]] = {}
        for f in self.factors.values():
            result.setdefault(f.information_family, []).append(f)
        return result

    def by_source(self) -> dict[str, list[FactorRecord]]:
        result: dict[str, list[FactorRecord]] = {}
        for f in self.factors.values():
            result.setdefault(f.source, []).append(f)
        return result

    def by_status(self) -> dict[str, int]:
        from collections import Counter
        return dict(Counter(f.status for f in self.factors.values()))

    # ---- Group API ----

    def list_groups(self, market: str | None = None) -> list[FactorGroup]:
        groups = list(self.groups.values())
        if market:
            groups = [g for g in groups if not g.market or g.market == market]
        return sorted(groups, key=lambda g: g.name)

    def create_group(self, name: str, factor_ids: list[str], market: str = "",
                     description: str = "") -> FactorGroup:
        """Create a dynamic factor group (not persisted to YAML)."""
        for fid in factor_ids:
            if fid not in self.factors:
                raise KeyError(f"unknown factor: {fid}")
        group = FactorGroup(
            name=name, description=description or f"Dynamic group: {name}",
            factor_ids=tuple(factor_ids), market=market,
        )
        self.groups[name] = group
        return group

    def group_by_family(self, market: str = "us") -> dict[str, FactorGroup]:
        """Auto-create groups by information_family."""
        result = {}
        for family, factors in self.by_family().items():
            active = [f for f in factors if market in f.markets and f.is_active]
            if active:
                gname = f"auto_{market}_{family}"
                result[gname] = FactorGroup(
                    name=gname,
                    description=f"Auto-generated: all active {family} factors for {market}",
                    factor_ids=tuple(f.factor_id for f in active),
                    market=market,
                    tags=("auto", family),
                )
        return result

    # ---- Expression API ----

    def expressions_for_groups(self, group_names: list[str]) -> list[str]:
        """Get Qlib expressions for named groups (deduplicated)."""
        exprs, seen_ids = [], set()
        for gname in group_names:
            group = self.groups.get(gname)
            if group is None:
                raise KeyError(f"unknown group: {gname}")
            for fid in group.factor_ids:
                factor = self.factors.get(fid)
                if factor and factor.factor_id not in seen_ids:
                    exprs.append(factor.expression)
                    seen_ids.add(factor.factor_id)
        return exprs

    def expressions_for_ids(self, factor_ids: list[str]) -> list[str]:
        """Get Qlib expressions for specific factor IDs."""
        return [self.factors[fid].expression for fid in factor_ids if fid in self.factors]

    # ---- Discovery API ----

    def scan_ic(
        self, market: str, factor_ids: list[str] | None = None,
        min_abs_ic: float = 0.02, top_n: int = 20,
    ) -> list[dict[str, Any]]:
        """IC-based factor screening placeholder.

        Real implementation would compute IC from provider data.
        Returns factors sorted by estimated information coefficient.
        """
        targets = factor_ids or [f.factor_id for f in self.query(market=market, active_only=False)]
        results = []
        for fid in targets[:top_n * 3]:
            factor = self.factors.get(fid)
            if factor is None:
                continue
            results.append({
                "factor_id": fid,
                "display_name": factor.display_name,
                "information_family": factor.information_family,
                "estimated_ic": 0.0,  # Placeholder
                "status": factor.status,
            })
        return sorted(results, key=lambda r: abs(r["estimated_ic"]), reverse=True)[:top_n]

    def export_catalog(self, market: str = "us", active_only: bool = True) -> list[dict[str, Any]]:
        """Export factor catalog for use by external systems."""
        return [
            {
                "factor_id": f.factor_id,
                "display_name": f.display_name,
                "expression": f.expression,
                "information_family": f.information_family,
                "markets": list(f.markets),
                "status": f.status,
                "implementation_hash": f.implementation_hash,
                "source": f.source,
            }
            for f in self.query(market=market, active_only=active_only)
        ]

    # ---- Stats ----

    def stats(self) -> dict[str, Any]:
        by_source = self.by_source()
        by_status = self.by_status()
        by_family = self.by_family()
        return {
            "total_factors": len(self.factors),
            "total_groups": len(self.groups),
            "by_source": {k: len(v) for k, v in by_source.items()},
            "by_status": by_status,
            "information_families": len(by_family),
            "us_active": len(self.us_factors(active_only=True)),
            "cn_active": len(self.cn_factors(active_only=True)),
            "proposed_unvalidated": len(self.proposed_factors()),
        }


def _infer_market(name: str) -> str:
    """Infer market from group name."""
    nl = name.lower()
    if nl.startswith("cn_") or "cn" in nl[:4]:
        return "cn"
    if nl.startswith("us_"):
        return "us"
    return ""


# ---- Singleton ----

_library: FactorLibrary | None = None


def get_factor_library(project_root: Path | str = ".") -> FactorLibrary:
    """Get or create the global factor library singleton."""
    global _library
    if _library is None or not _library._loaded:
        _library = FactorLibrary()
        _library.load_all(project_root)
    return _library


def reset_factor_library() -> None:
    """Reset the global factor library (for testing or data refresh)."""
    global _library
    _library = None
