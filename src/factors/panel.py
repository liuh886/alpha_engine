from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

import numpy as np
import pandas as pd
import yaml  # type: ignore[import-untyped]

from src.factors.definition import FactorDefinition
from src.factors.sets.qlib_alpha158 import load_alpha158_definitions


class FactorPanelError(ValueError):
    pass


class FactorEvaluator(Protocol):
    def evaluate(
        self,
        *,
        symbols: Sequence[str],
        expressions: Sequence[str],
        start: str,
        end: str,
    ) -> pd.DataFrame: ...


@dataclass
class QlibFactorEvaluator:
    provider_uri: Path
    market: str
    _initialized: bool = False

    def _init(self) -> None:
        if self._initialized:
            return
        import qlib
        from qlib.constant import REG_CN, REG_US

        region = REG_US if self.market == "us" else REG_CN
        qlib.init(provider_uri=str(self.provider_uri), region=region)
        self._initialized = True

    def evaluate(
        self,
        *,
        symbols: Sequence[str],
        expressions: Sequence[str],
        start: str,
        end: str,
    ) -> pd.DataFrame:
        self._init()
        from qlib.data import D

        frame = D.features(
            instruments=list(symbols),
            fields=list(expressions),
            start_time=start,
            end_time=end,
            freq="day",
        )
        if not isinstance(frame, pd.DataFrame):
            raise FactorPanelError("Qlib feature evaluation did not return a DataFrame")
        return frame


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FactorPanelError(f"YAML must be a mapping: {path}")
    return payload


def _pool_symbols(root: Path, contract: Mapping[str, Any], market: str) -> tuple[str, list[str]]:
    market_contract = contract.get("markets", {}).get(market)
    if not isinstance(market_contract, dict):
        raise FactorPanelError(f"market is not declared: {market}")
    pool_path = root / str(market_contract.get("pool_spec", ""))
    pool = _load_yaml(pool_path)
    symbols = [str(value).strip().upper() for value in pool.get("symbols", [])]
    expected = int(market_contract.get("expected_symbols", 0))
    if len(symbols) != expected or len(set(symbols)) != expected:
        raise FactorPanelError("factor panel selected-pool identity is not exact")
    return str(market_contract.get("pool_id", "")), symbols


def _provider_manifest(provider_uri: Path) -> tuple[Path, str, dict[str, Any]]:
    path = provider_uri / "provider_manifest.json"
    if not path.is_file():
        raise FactorPanelError(f"provider manifest is missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FactorPanelError("provider manifest must be a JSON object")
    return path, _sha256(path), payload


def _source_role_manifest(
    provider_uri: Path,
    policy: Mapping[str, Any],
) -> tuple[Path, str | None, dict[str, Any] | None]:
    name = str(policy.get("source_role_manifest", "source_role_manifest.json"))
    path = provider_uri / name
    if not path.is_file():
        return path, None, None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise FactorPanelError("source-role manifest must be a JSON object")
    return path, _sha256(path), payload


def _provider_role_blocker(
    payload: Mapping[str, Any] | None,
    *,
    policy: Mapping[str, Any],
    field_policy: Mapping[str, Any],
) -> str | None:
    if payload is None:
        return "canonical source-role manifest is unavailable"

    role = str(payload.get("role", "")).strip().lower()
    if bool(policy.get("canonical_role_required", True)) and role != "canonical":
        return f"provider role is not canonical: {role or 'missing'}"
    if bool(policy.get("canonical_training_eligible_required", True)) and (
        payload.get("canonical_training_eligible") is not True
    ):
        return "provider is not canonical-training-eligible"
    if bool(policy.get("validation_only_provider_forbidden", True)) and (
        payload.get("validation_only") is True
    ):
        return "validation-only provider cannot satisfy Alpha158 fields"

    forbidden = {
        str(value).strip().lower()
        for value in policy.get("validation_only_sources", [])
        if str(value).strip()
    }
    declared_sources = {
        str(value).strip().lower()
        for value in payload.get("source_providers", [])
        if str(value).strip()
    }
    if forbidden.intersection(declared_sources):
        names = sorted(forbidden.intersection(declared_sources))
        return f"validation-only source declared in canonical provider: {names}"

    semantics = payload.get("field_semantics", {})
    if not isinstance(semantics, dict):
        return "provider field semantics are missing"
    vwap_semantics = str(semantics.get("vwap", "")).strip()
    allowed = {
        str(value).strip()
        for value in field_policy.get("allowed_vwap_semantics", [])
        if str(value).strip()
    }
    if not vwap_semantics:
        return "provider does not declare vwap semantics"
    if allowed and vwap_semantics not in allowed:
        return f"provider vwap semantics are not eligible: {vwap_semantics}"
    return None


def provider_field_coverage(provider_uri: Path, field: str) -> set[str]:
    feature_root = provider_uri / "features"
    if not feature_root.is_dir():
        return set()
    covered: set[str] = set()
    for path in feature_root.glob(f"*/{field}.day.bin"):
        covered.add(path.parent.name.upper())
    return covered


def _catalog_payload(definitions: Sequence[FactorDefinition]) -> dict[str, Any]:
    rows = [definition.to_dict() for definition in definitions]
    seed = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {
        "schema_version": "1.0",
        "component_id": "factors.qlib_alpha158.catalog_v1",
        "component_kind": "factor_catalog",
        "status": "ready" if len(rows) == 158 else "blocked",
        "factor_count": len(rows),
        "catalog_sha256": hashlib.sha256(seed).hexdigest(),
        "factors": rows,
        "research_only": True,
        "trade_ready": False,
    }


def _symbol_frame(
    evaluated: pd.DataFrame,
    symbol: str,
    factor_ids: Sequence[str],
) -> pd.DataFrame:
    if isinstance(evaluated.index, pd.MultiIndex):
        names = list(evaluated.index.names)
        instrument_level = names.index("instrument") if "instrument" in names else 0
        try:
            frame = evaluated.xs(symbol, level=instrument_level).copy()
        except KeyError:
            return pd.DataFrame(columns=factor_ids)
    else:
        frame = evaluated.copy()
    frame.columns = list(factor_ids)
    frame.index = pd.to_datetime(frame.index, errors="coerce")
    frame = frame.loc[~frame.index.isna()].sort_index()
    frame = frame.loc[~frame.index.duplicated(keep="last")]
    return frame


def _quality_rows(
    frame: pd.DataFrame,
    *,
    symbol: str,
    definitions: Sequence[FactorDefinition],
    source_availability: pd.Series,
    minimum_rows: int,
    near_constant_threshold: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    available = pd.to_numeric(source_availability.reindex(frame.index), errors="coerce").notna()
    for definition in definitions:
        values = pd.to_numeric(frame.get(definition.factor_id), errors="coerce")
        lookback = int(definition.minimum_lookback)
        if lookback:
            required_observations = lookback + 1
            eligible = (
                available.astype(int)
                .rolling(required_observations, min_periods=required_observations)
                .sum()
                .eq(required_observations)
            )
        else:
            eligible = available
        post = values.loc[eligible]
        finite = post.replace([np.inf, -np.inf], np.nan)
        nan_count = int(finite.isna().sum())
        inf_count = int(np.isinf(post.to_numpy(dtype=float, na_value=np.nan)).sum())
        finite_values = finite.dropna()
        unique = int(finite_values.nunique(dropna=True))
        unique_ratio = float(unique / len(finite_values)) if len(finite_values) else 0.0
        status = "ready_with_formula_nan" if nan_count else "ready"
        reasons: list[str] = []
        if len(finite_values) < minimum_rows:
            status = "blocked"
            reasons.append("insufficient_post_warmup_rows")
        if nan_count:
            reasons.append("formula_undefined_nan_preserved")
        if inf_count:
            status = "blocked"
            reasons.append("infinite_values")
        if unique <= 1 and len(finite_values):
            reasons.append("constant_factor")
        elif unique_ratio < near_constant_threshold and len(finite_values):
            reasons.append("near_constant_factor")
        rows.append(
            {
                "symbol": symbol,
                "factor_id": definition.factor_id,
                "implementation_hash": definition.implementation_hash,
                "minimum_lookback": definition.minimum_lookback,
                "warmup_rows": lookback,
                "source_available_rows": int(available.sum()),
                "source_unavailable_rows": int((~available).sum()),
                "eligible_rows": int(eligible.sum()),
                "post_warmup_rows": int(len(post)),
                "finite_rows": int(len(finite_values)),
                "nan_rows": nan_count,
                "inf_rows": inf_count,
                "unique_values": unique,
                "unique_ratio": unique_ratio,
                "first_valid_date": (
                    pd.Timestamp(finite_values.index.min()).date().isoformat()
                    if len(finite_values)
                    else None
                ),
                "last_valid_date": (
                    pd.Timestamp(finite_values.index.max()).date().isoformat()
                    if len(finite_values)
                    else None
                ),
                "status": status,
                "reasons": "|".join(reasons),
            }
        )
    return rows


def _blocked_manifest(
    *,
    output: Path,
    market: str,
    pool_id: str,
    cutoff: str,
    symbols: Sequence[str],
    catalog_path: Path,
    provider_manifest_path: Path,
    provider_hash: str,
    source_role_path: Path,
    source_role_hash: str | None,
    blocker: str,
    field_coverage: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    manifest = {
        "schema_version": "1.1",
        "component_id": f"factors.qlib_alpha158.panel.{market}.v1",
        "component_kind": "factor_panel",
        "status": "blocked",
        "market": market,
        "pool_id": pool_id,
        "evidence_cutoff": cutoff,
        "expected_symbol_count": len(symbols),
        "ready_symbol_count": 0,
        "coverage_ratio": 0.0,
        "missing_symbols": [],
        "invalid_symbols": list(symbols),
        "quarantined_symbols": [],
        "providers": ["qlib_provider"],
        "professional_source_ready": None,
        "catalog_path": str(catalog_path),
        "catalog_sha256": _sha256(catalog_path),
        "provider_manifest_path": str(provider_manifest_path),
        "provider_manifest_sha256": provider_hash,
        "source_role_manifest_path": str(source_role_path),
        "source_role_manifest_sha256": source_role_hash,
        "field_coverage": dict(field_coverage or {}),
        "blocker": blocker,
        "research_only": True,
        "trade_ready": False,
    }
    _write_json(output / "factor_panel_manifest.json", manifest)
    return manifest


def build_alpha158_panel(
    *,
    root: str | Path,
    contract_path: str | Path,
    provider_uri: str | Path,
    market: str,
    start: str,
    cutoff: str,
    output_root: str | Path,
    evaluator: FactorEvaluator | None = None,
) -> dict[str, Any]:
    repo = Path(root).resolve()
    contract_file = Path(contract_path)
    if not contract_file.is_absolute():
        contract_file = repo / contract_file
    contract = _load_yaml(contract_file)
    market_key = str(market).lower()
    pool_id, symbols = _pool_symbols(repo, contract, market_key)
    definitions = load_alpha158_definitions()
    expected_factors = int(contract.get("catalog", {}).get("expected_factor_count", 0))
    if len(definitions) != expected_factors:
        raise FactorPanelError("Alpha158 catalog count drift")

    output = Path(output_root).resolve()
    output.mkdir(parents=True, exist_ok=True)
    catalog = _catalog_payload(definitions)
    catalog_path = output / "factor_catalog.json"
    _write_json(catalog_path, catalog)
    provider = Path(provider_uri).resolve()
    provider_manifest_path, provider_hash, _ = _provider_manifest(provider)

    role_policy = contract.get("provider_role_policy", {})
    if not isinstance(role_policy, dict):
        raise FactorPanelError("provider_role_policy must be a mapping")
    field_policy = contract.get("field_policy", {})
    if not isinstance(field_policy, dict):
        raise FactorPanelError("field_policy must be a mapping")
    source_role_path, source_role_hash, source_role = _source_role_manifest(provider, role_policy)
    role_blocker = _provider_role_blocker(
        source_role,
        policy=role_policy,
        field_policy=field_policy,
    )
    if role_blocker:
        return _blocked_manifest(
            output=output,
            market=market_key,
            pool_id=pool_id,
            cutoff=cutoff,
            symbols=symbols,
            catalog_path=catalog_path,
            provider_manifest_path=provider_manifest_path,
            provider_hash=provider_hash,
            source_role_path=source_role_path,
            source_role_hash=source_role_hash,
            blocker=role_blocker,
        )

    required_fields = [str(value) for value in contract.get("required_provider_fields", [])]
    field_coverage = {
        field: sorted(provider_field_coverage(provider, field)) for field in required_fields
    }
    missing_vwap = sorted(set(symbols).difference(field_coverage.get("vwap", [])))
    if missing_vwap:
        return _blocked_manifest(
            output=output,
            market=market_key,
            pool_id=pool_id,
            cutoff=cutoff,
            symbols=missing_vwap,
            catalog_path=catalog_path,
            provider_manifest_path=provider_manifest_path,
            provider_hash=provider_hash,
            source_role_path=source_role_path,
            source_role_hash=source_role_hash,
            blocker="true vwap field is unavailable for exact selected pool",
            field_coverage=field_coverage,
        )

    engine = evaluator or QlibFactorEvaluator(provider_uri=provider, market=market_key)
    expressions = [definition.expression for definition in definitions]
    factor_ids = [definition.factor_id for definition in definitions]
    evaluated = engine.evaluate(
        symbols=symbols,
        expressions=expressions,
        start=start,
        end=cutoff,
    )
    if len(evaluated.columns) != len(definitions):
        raise FactorPanelError("evaluated Alpha158 column count mismatch")
    source_evaluated = engine.evaluate(
        symbols=symbols,
        expressions=["$close"],
        start=start,
        end=cutoff,
    )
    if len(source_evaluated.columns) != 1:
        raise FactorPanelError("canonical close availability evaluation failed")

    quality_settings = contract.get("quality", {})
    minimum_rows = int(quality_settings.get("minimum_post_warmup_rows", 20))
    near_constant = float(quality_settings.get("near_constant_unique_ratio_threshold", 0.001))
    files: dict[str, str] = {}
    quality_rows: list[dict[str, Any]] = []
    ready_symbols: list[str] = []
    invalid_symbols: list[str] = []
    not_yet_applicable_symbols: list[str] = []
    for symbol in symbols:
        frame = _symbol_frame(evaluated, symbol, factor_ids)
        source_frame = _symbol_frame(source_evaluated, symbol, ["source_close"])
        if frame.empty or source_frame.empty:
            invalid_symbols.append(symbol)
            continue
        frame.index.name = "date"
        path = output / "panels" / f"{symbol}.csv.gz"
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.reset_index().to_csv(path, index=False, compression="gzip")
        files[path.relative_to(output).as_posix()] = _sha256(path)
        symbol_quality = _quality_rows(
            frame,
            symbol=symbol,
            definitions=definitions,
            source_availability=source_frame["source_close"],
            minimum_rows=minimum_rows,
            near_constant_threshold=near_constant,
        )
        quality_rows.extend(symbol_quality)
        if all(row["status"] in {"ready", "ready_with_formula_nan"} for row in symbol_quality):
            ready_symbols.append(symbol)
        else:
            blocked_rows = [row for row in symbol_quality if row["status"] == "blocked"]
            if blocked_rows and all(
                str(row["reasons"]).split("|") == ["insufficient_post_warmup_rows"]
                for row in blocked_rows
            ):
                not_yet_applicable_symbols.append(symbol)
            else:
                invalid_symbols.append(symbol)

    quality = pd.DataFrame(quality_rows)
    quality_path = output / "factor_quality.csv.gz"
    quality.to_csv(quality_path, index=False, compression="gzip")
    files[quality_path.relative_to(output).as_posix()] = _sha256(quality_path)
    status = "ready" if len(ready_symbols) == len(symbols) else "partial"
    manifest = {
        "schema_version": "1.1",
        "component_id": f"factors.qlib_alpha158.panel.{market_key}.v1",
        "component_kind": "factor_panel",
        "status": status,
        "market": market_key,
        "pool_id": pool_id,
        "evidence_cutoff": cutoff,
        "first_date": start,
        "last_date": cutoff,
        "expected_symbol_count": len(symbols),
        "ready_symbol_count": len(ready_symbols),
        "coverage_ratio": float(len(ready_symbols) / len(symbols)),
        "missing_symbols": [],
        "invalid_symbols": sorted(set(invalid_symbols)),
        "not_yet_applicable_symbols": sorted(set(not_yet_applicable_symbols)),
        "quarantined_symbols": [],
        "providers": ["qlib_provider"],
        "professional_source_ready": None,
        "factor_count": len(definitions),
        "catalog_path": str(catalog_path),
        "catalog_sha256": _sha256(catalog_path),
        "provider_manifest_path": str(provider_manifest_path),
        "provider_manifest_sha256": provider_hash,
        "source_role_manifest_path": str(source_role_path),
        "source_role_manifest_sha256": source_role_hash,
        "source_role": source_role,
        "field_coverage": field_coverage,
        "quality_policy": {
            "availability_field": "canonical_close",
            "lookback_requires_consecutive_available_sessions": True,
            "source_unavailable_sessions_excluded_from_factor_eligibility": True,
            "formula_undefined_nan_policy": "preserve_and_report",
            "infinite_value_policy": "block",
            "minimum_finite_rows": minimum_rows,
        },
        "files": dict(sorted(files.items())),
        "research_only": True,
        "trade_ready": False,
    }
    _write_json(output / "factor_panel_manifest.json", manifest)
    return manifest
