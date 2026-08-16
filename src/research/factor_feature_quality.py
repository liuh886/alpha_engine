"""Gate-1 structural quality checks for canonical research factors.

This module deliberately evaluates feature mechanics only. It never loads a
forward-return label, computes IC, or trains a model, so feature-quality checks
cannot consume reporting/holdout evidence intended for later selection.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import pandas as pd

from src.common.qlib_init import build_qlib_init_cfg, safe_qlib_init
from src.data.market_provider import load_provider_manifest, market_provider_path
from src.factors.definition import FactorDefinition
from src.factors.library import load_factor_library
from src.research.multi_market_readiness import normalize_market_symbols
from src.research.paradigm import ResearchParadigmSpec, load_research_paradigm_spec
from src.research.qlib_execution_common import normalize_qlib_frame_index
from src.research.spec_bound_execution import build_declared_execution_contract, contract_sha256

FEATURE_QUALITY_SCHEMA_VERSION = "1.0"
MIN_POST_WARMUP_COVERAGE = 0.90
MAX_END_GAP_DAYS = 14


class FactorFeatureQualityRuntime(Protocol):
    def initialize(self, repository_root: Path) -> None: ...

    def features(
        self,
        symbols: Sequence[str],
        expressions: Sequence[str],
        start: str,
        end: str,
    ) -> pd.DataFrame: ...

    def expression_window(self, expression: str) -> tuple[int, int]: ...

    def metadata(self) -> dict[str, Any]: ...


class QlibFactorFeatureQualityRuntime:
    """Thin adapter over the repository's existing Qlib provider path."""

    def __init__(self, *, market: str, provider_uri: str | Path) -> None:
        self.market = market
        self.provider_uri = Path(provider_uri)
        self._resolved_provider_uri = ""

    def initialize(self, repository_root: Path) -> None:
        provider = self.provider_uri
        if not provider.is_absolute():
            provider = repository_root / provider
        self._resolved_provider_uri = str(provider.resolve())
        safe_qlib_init(
            build_qlib_init_cfg(
                None,
                market=self.market,
                provider_uri_default=self._resolved_provider_uri,
            )
        )

    def features(
        self,
        symbols: Sequence[str],
        expressions: Sequence[str],
        start: str,
        end: str,
    ) -> pd.DataFrame:
        from qlib.data import D

        return D.features(
            list(symbols),
            list(expressions),
            start_time=start,
            end_time=end,
        )

    def expression_window(self, expression: str) -> tuple[int, int]:
        from qlib.data.data import ExpressionD

        parsed = ExpressionD.get_expression_instance(expression)
        left, right = parsed.get_extended_window_size()
        return int(left), int(right)

    def metadata(self) -> dict[str, Any]:
        return {
            "provider": "qlib",
            "provider_uri": self._resolved_provider_uri,
            "market": self.market,
        }


def _resolve_source(spec: ResearchParadigmSpec, source: str) -> Path:
    spec_dir = Path(spec.spec_path).parent if spec.spec_path else Path.cwd()
    for candidate in (spec_dir / source, Path.cwd() / source):
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"research source not found: {source}")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _selected_factors(spec: ResearchParadigmSpec) -> tuple[Path, list[FactorDefinition]]:
    source = _resolve_source(spec, str(spec.factor_library["source"]))
    library = load_factor_library(source)
    definitions = library.factors_for_groups(spec.factor_library["groups"])
    if not definitions:
        raise ValueError("factor quality contract resolved no canonical factors")
    if len({row.factor_id for row in definitions}) != len(definitions):
        raise ValueError("factor quality contract resolved duplicate factor IDs")
    if len({row.expression for row in definitions}) != len(definitions):
        raise ValueError("factor quality contract resolved duplicate expressions")
    return source, definitions


def _normalize_feature_frame(
    raw: pd.DataFrame,
    definitions: Sequence[FactorDefinition],
) -> pd.DataFrame:
    frame = normalize_qlib_frame_index(raw.copy())
    if frame.index.names != ["datetime", "instrument"]:
        raise ValueError("factor provider must return a datetime/instrument MultiIndex")
    if len(frame.columns) != len(definitions):
        raise ValueError(
            "provider returned unexpected factor column count: "
            f"expected={len(definitions)}, actual={len(frame.columns)}"
        )
    frame.columns = [row.factor_id for row in definitions]
    return frame.sort_index()


def _frame_digest(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    digest.update("|".join(map(str, frame.columns)).encode("utf-8"))
    for index, row in frame.iterrows():
        date, instrument = index
        digest.update(pd.Timestamp(date).isoformat().encode("utf-8"))
        digest.update(b"|")
        digest.update(str(instrument).encode("utf-8"))
        for value in row:
            number = float(value)
            if math.isnan(number):
                token = "nan"
            elif math.isinf(number):
                token = "inf" if number > 0 else "-inf"
            else:
                token = number.hex()
            digest.update(b"|")
            digest.update(token.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _frames_identical(left: pd.DataFrame, right: pd.DataFrame) -> bool:
    if not left.index.equals(right.index) or list(left.columns) != list(right.columns):
        return False
    return bool(
        np.array_equal(
            left.to_numpy(dtype=float),
            right.to_numpy(dtype=float),
            equal_nan=True,
        )
    )


def _symbol_quality(
    series: pd.Series,
    minimum_lookback: int,
    *,
    expected_end: str,
) -> dict[str, Any]:
    numeric = pd.to_numeric(series, errors="coerce")
    values = numeric.to_numpy(dtype=float)
    finite_mask = np.isfinite(values)
    inf_count = int(np.isinf(values).sum())
    finite_positions = np.flatnonzero(finite_mask)
    if finite_positions.size == 0:
        return {
            "finite_count": 0,
            "inf_count": inf_count,
            "first_valid_date": None,
            "last_valid_date": None,
            "observed_warmup_sessions": None,
            "post_warmup_coverage": 0.0,
            "end_gap_days": None,
            "minimum_lookback": minimum_lookback,
        }

    first_position = int(finite_positions[0])
    last_position = int(finite_positions[-1])
    eligible = values[first_position : last_position + 1]
    post_warmup_coverage = float(np.isfinite(eligible).mean())
    index = pd.DatetimeIndex(series.index)
    first_valid = pd.Timestamp(index[first_position])
    last_valid = pd.Timestamp(index[last_position])
    end_gap_days = max(0, int((pd.Timestamp(expected_end) - last_valid).days))
    return {
        "finite_count": int(finite_mask.sum()),
        "inf_count": inf_count,
        "first_valid_date": first_valid.strftime("%Y-%m-%d"),
        "last_valid_date": last_valid.strftime("%Y-%m-%d"),
        "observed_warmup_sessions": first_position,
        "post_warmup_coverage": post_warmup_coverage,
        "end_gap_days": end_gap_days,
        "minimum_lookback": minimum_lookback,
    }


def _factor_quality(
    frame: pd.DataFrame,
    definition: FactorDefinition,
    *,
    requested_symbols: Sequence[str],
    runtime: FactorFeatureQualityRuntime,
    start: str,
    end: str,
) -> dict[str, Any]:
    factor_id = definition.factor_id
    column = frame[factor_id]
    symbol_rows: dict[str, dict[str, Any]] = {}
    missing_symbols: list[str] = []

    available_symbols = set(column.index.get_level_values("instrument"))
    for symbol in requested_symbols:
        if symbol not in available_symbols:
            missing_symbols.append(symbol)
            continue
        values = column.xs(symbol, level="instrument")
        symbol_rows[symbol] = _symbol_quality(
            values,
            definition.minimum_lookback,
            expected_end=end,
        )

    finite = pd.to_numeric(column, errors="coerce").to_numpy(dtype=float)
    finite_values = finite[np.isfinite(finite)]
    inf_count = int(np.isinf(finite).sum())
    near_constant = bool(
        finite_values.size < 2
        or np.nanstd(finite_values) <= np.finfo(float).eps
        or np.unique(finite_values).size < 2
    )
    coverage_pass = bool(
        not missing_symbols
        and symbol_rows
        and all(
            row["finite_count"] > 0
            and row["inf_count"] == 0
            and row["post_warmup_coverage"] >= MIN_POST_WARMUP_COVERAGE
            and row["end_gap_days"] is not None
            and row["end_gap_days"] <= MAX_END_GAP_DAYS
            for row in symbol_rows.values()
        )
    )

    left_window, right_window = runtime.expression_window(definition.expression)
    no_future_pass = right_window == 0

    probe_symbols = []
    if requested_symbols:
        positions = sorted({0, len(requested_symbols) // 2, len(requested_symbols) - 1})
        probe_symbols = [requested_symbols[position] for position in positions]
    isolation_results: dict[str, bool] = {}
    for symbol in probe_symbols:
        isolated = _normalize_feature_frame(
            runtime.features([symbol], [definition.expression], start, end),
            [definition],
        )
        batch = frame.loc[
            frame.index.get_level_values("instrument") == symbol,
            [factor_id],
        ]
        isolation_results[symbol] = _frames_identical(batch, isolated)
    symbol_isolation_pass = bool(isolation_results) and all(isolation_results.values())

    return {
        "factor_id": factor_id,
        "factor_version": definition.factor_version,
        "implementation_hash": definition.implementation_hash,
        "expression": definition.expression,
        "required_fields": list(definition.required_fields),
        "minimum_lookback": definition.minimum_lookback,
        "finite_count": int(finite_values.size),
        "inf_count": inf_count,
        "near_constant": near_constant,
        "missing_symbols": missing_symbols,
        "minimum_post_warmup_coverage_required": MIN_POST_WARMUP_COVERAGE,
        "maximum_end_gap_days_allowed": MAX_END_GAP_DAYS,
        "symbol_quality": symbol_rows,
        "expression_window": {
            "past_sessions": left_window,
            "future_sessions": right_window,
        },
        "symbol_isolation": isolation_results,
        "checks": {
            "finite_and_coverage": coverage_pass,
            "no_inf": inf_count == 0,
            "not_near_constant": not near_constant,
            "no_future_data": no_future_pass,
            "symbol_isolation": symbol_isolation_pass,
        },
    }


def evaluate_factor_feature_quality(
    spec: ResearchParadigmSpec,
    *,
    repository_root: str | Path,
    runtime: FactorFeatureQualityRuntime,
    provider_identity: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate deterministic feature mechanics without using any forward label."""

    root = Path(repository_root).resolve()
    declared_contract = build_declared_execution_contract(spec)
    expected_count = spec.universe.get("exact_pool_candidate_count")
    requested_symbols = [
        row.normalized_symbol
        for row in normalize_market_symbols(
            spec.market,
            list(declared_contract["universe"]["requested_symbols"]),
        )
    ]
    if expected_count is not None and len(requested_symbols) != int(expected_count):
        raise ValueError(
            "exact universe count drifted: "
            f"declared={expected_count}, resolved={len(requested_symbols)}"
        )

    factor_source, definitions = _selected_factors(spec)
    expressions = [row.expression for row in definitions]
    start = str(spec.walk_forward["requested_train_start"])
    end = str(spec.walk_forward["test_end"])

    runtime.initialize(root)
    first = _normalize_feature_frame(
        runtime.features(requested_symbols, expressions, start, end),
        definitions,
    )
    second = _normalize_feature_frame(
        runtime.features(requested_symbols, expressions, start, end),
        definitions,
    )
    first_digest = _frame_digest(first)
    second_digest = _frame_digest(second)
    deterministic = first_digest == second_digest and _frames_identical(first, second)

    factors = [
        _factor_quality(
            first,
            definition,
            requested_symbols=requested_symbols,
            runtime=runtime,
            start=start,
            end=end,
        )
        for definition in definitions
    ]
    factor_checks_pass = all(all(row["checks"].values()) for row in factors)
    gate1_pass = bool(deterministic and factor_checks_pass)

    return {
        "schema_version": FEATURE_QUALITY_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "experiment_id": spec.experiment_id,
        "market": spec.market,
        "quality_scope": "feature_mechanics_only_no_forward_label",
        "gate": "issue_966_gate_1",
        "gate1_pass": gate1_pass,
        "research_only": True,
        "trade_ready": False,
        "provider": dict(provider_identity),
        "runtime": runtime.metadata(),
        "declared_contract_sha256": contract_sha256(declared_contract),
        "universe": {
            "universe_id": spec.universe.get("universe_id"),
            "source": declared_contract["universe"]["source"],
            "source_sha256": declared_contract["universe"]["source_sha256"],
            "requested_symbol_count": len(requested_symbols),
            "requested_symbols": requested_symbols,
        },
        "factor_library": {
            "source": str(spec.factor_library["source"]),
            "source_sha256": _sha256_file(factor_source),
            "selected_groups": list(spec.factor_library["groups"]),
        },
        "evaluation_range": {"start": start, "end": end},
        "determinism": {
            "pass": deterministic,
            "first_sha256": first_digest,
            "second_sha256": second_digest,
        },
        "factor_count": len(factors),
        "factors": factors,
    }


def run_factor_feature_quality_from_files(
    spec_path: str | Path,
    *,
    repository_root: str | Path = ".",
    provider_dir: str | Path | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Verify provider identity, run Gate-1 checks, and optionally persist a receipt."""

    root = Path(repository_root).resolve()
    spec = load_research_paradigm_spec(spec_path)
    provider = (
        Path(provider_dir).resolve()
        if provider_dir is not None
        else market_provider_path(root, spec.market)
    )
    if any(provider.rglob("fixture_manifest.json")):
        raise ValueError("synthetic/test provider cannot support Gate-1 feature quality")

    manifest = load_provider_manifest(
        provider,
        expected_market=spec.market,
        required=True,
        verify_files=True,
    )
    provider_cutoff = manifest.get("cutoff")
    expected_cutoff = str(spec.walk_forward["test_end"])
    if provider_cutoff != expected_cutoff:
        raise ValueError(
            "Gate-1 provider cutoff must equal the feature-quality contract end: "
            f"provider={provider_cutoff!r}, expected={expected_cutoff!r}"
        )
    manifest_path = provider / "provider_manifest.json"
    calendar = dict(manifest.get("calendar") or {})
    instruments = dict(manifest.get("instruments") or {})
    provider_identity = {
        "provider_dir": str(provider),
        "provider_identity_sha256": manifest.get("provider_identity_sha256"),
        "provider_manifest_sha256": _sha256_file(manifest_path),
        "cutoff": provider_cutoff,
        "calendar_first_day": calendar.get("first_day"),
        "calendar_last_day": calendar.get("last_day"),
        "session_count": calendar.get("session_count"),
        "instrument_count": instruments.get("count"),
    }
    report = evaluate_factor_feature_quality(
        spec,
        repository_root=root,
        runtime=QlibFactorFeatureQualityRuntime(market=spec.market, provider_uri=provider),
        provider_identity=provider_identity,
    )
    if output_path is not None:
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report
