"""Build formal Model Run Bundle v2 evidence from governed model-source packages."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

from src.artifacts.model_run_bundle_v2 import canonical_json_bytes
from src.artifacts.model_run_exporter import RunExportPlan, SectionPlan, export_model_run, update_catalog
from src.artifacts.performance_semantics import build_performance_semantics, validate_performance_semantics
from src.governance.active_strategy_catalog import ActiveStrategy
from src.governance.model_contract import ModelContractError, load_performance_semantics


class FormalBundleV2BuildError(ValueError):
    """Raised when a governed formal source cannot be packaged without invention."""


METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "total_return": ("Total Return", "total_return"),
    "annualized_return": ("Annualized Return", "CAGR", "annual_return"),
    "benchmark_return": ("Benchmark Return", "Benchmark V1.2 Return", "benchmark_return"),
    "excess_return": (
        "Compounded Relative Excess Return",
        "Relative Terminal Wealth vs V1.2",
        "Excess Return",
        "excess_return",
    ),
    "annualized_volatility": ("Annualized Volatility",),
    "sharpe_ratio": ("Sharpe Ratio", "sharpe"),
    "information_ratio": ("Information Ratio",),
    "max_drawdown": ("Max Drawdown", "mdd"),
    "turnover": ("Turnover",),
    "transaction_cost": ("Transaction Cost",),
    "ic": ("IC", "ic"),
    "rank_ic": ("Rank IC", "Mean Rank IC", "rank_ic"),
    "icir": ("ICIR", "Mean ICIR", "icir"),
}

METRIC_META: dict[str, tuple[str, str]] = {
    "total_return": ("ratio", "higher_is_better"),
    "annualized_return": ("ratio", "higher_is_better"),
    "benchmark_return": ("ratio", "descriptive"),
    "excess_return": ("ratio", "higher_is_better"),
    "annualized_volatility": ("ratio", "lower_is_better"),
    "sharpe_ratio": ("decimal", "higher_is_better"),
    "information_ratio": ("decimal", "higher_is_better"),
    "max_drawdown": ("ratio", "higher_is_better"),
    "turnover": ("ratio", "lower_is_better"),
    "transaction_cost": ("ratio", "lower_is_better"),
    "ic": ("decimal", "higher_is_better"),
    "rank_ic": ("decimal", "higher_is_better"),
    "icir": ("decimal", "higher_is_better"),
}


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalBundleV2BuildError(f"invalid formal source JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FormalBundleV2BuildError(f"formal source root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _slug(value: object, fallback: str) -> str:
    text = re.sub(r"[^a-z0-9._-]+", "_", str(value or "").lower()).strip("_.-")
    if len(text) < 2:
        text = fallback
    return text[:128]


def _list(package: Mapping[str, Any], key: str) -> list[Any]:
    value = package.get(key)
    if not isinstance(value, list):
        raise FormalBundleV2BuildError(f"formal source field {key} must be a list")
    return value


def _mapping(package: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = package.get(key)
    if not isinstance(value, Mapping):
        raise FormalBundleV2BuildError(f"formal source field {key} must be an object")
    return dict(value)


def _canonical_metrics(package: Mapping[str, Any], *, model_kind: str) -> list[dict[str, Any]]:
    raw = _mapping(package, "metrics")
    sample_count = len(_list(package, "report"))
    evidence = package.get("evidence")
    metric_metadata: Mapping[str, Any] = {}
    if isinstance(evidence, Mapping):
        declared = evidence.get("metric_metadata")
        if isinstance(declared, Mapping):
            metric_metadata = declared
    rows: list[dict[str, Any]] = []
    for metric_id, aliases in METRIC_ALIASES.items():
        source_label = next((label for label in aliases if label in raw), None)
        unit, direction = METRIC_META[metric_id]
        if source_label is not None:
            value = raw[source_label]
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise FormalBundleV2BuildError(f"metric {source_label} is not a retained number")
            declared_meta = metric_metadata.get(metric_id)
            retained_count = sample_count
            retained_scope = "accepted_formal_source_observed_window"
            if declared_meta is not None:
                if not isinstance(declared_meta, Mapping):
                    raise FormalBundleV2BuildError(
                        f"metric metadata for {metric_id} must be an object"
                    )
                declared_count = declared_meta.get("sample_count")
                declared_scope = declared_meta.get("scope")
                if (
                    not isinstance(declared_count, int)
                    or isinstance(declared_count, bool)
                    or declared_count <= 0
                    or not isinstance(declared_scope, str)
                    or not declared_scope.strip()
                ):
                    raise FormalBundleV2BuildError(
                        f"metric metadata for {metric_id} is invalid"
                    )
                retained_count = declared_count
                retained_scope = declared_scope.strip()
            rows.append(
                {
                    "metric_id": metric_id,
                    "value": float(value),
                    "unit": unit,
                    "direction": direction,
                    "estimator": f"retained_formal_source:{source_label}",
                    "annualization": (
                        "retained_formal_source_semantics"
                        if metric_id in {"annualized_return", "annualized_volatility", "sharpe_ratio", "information_ratio"}
                        else None
                    ),
                    "sample_count": retained_count,
                    "scope": retained_scope,
                    "availability_status": "available",
                    "unavailable_reason": None,
                }
            )
            continue
        not_applicable = model_kind == "rules_based_allocation" and metric_id in {"ic", "rank_ic", "icir"}
        rows.append(
            {
                "metric_id": metric_id,
                "value": None,
                "unit": unit,
                "direction": direction,
                "estimator": None,
                "annualization": None,
                "sample_count": None,
                "scope": "accepted_formal_source_observed_window",
                "availability_status": "not_applicable" if not_applicable else "not_retained",
                "unavailable_reason": (
                    "Cross-sectional prediction metrics do not apply to the rules-based allocation model."
                    if not_applicable
                    else "The governed formal source does not retain this metric; Bundle v2 does not synthesize it."
                ),
            }
        )
    return rows


def _unavailable_reason(package: Mapping[str, Any], key: str) -> str:
    completeness = package.get("evidence_completeness")
    if isinstance(completeness, Mapping):
        value = completeness.get(key)
        if isinstance(value, str) and value.strip():
            return value
        missing = completeness.get("missing")
        if isinstance(missing, list) and missing:
            return (
                f"The governed formal source did not retain {key}; declared missing evidence includes: "
                f"{', '.join(str(row) for row in missing)}."
            )
    return f"The governed formal source did not retain {key}; Bundle v2 does not reconstruct it."


def _section(
    section_id: str,
    payload: Mapping[str, Any] | list[Any] | None,
    *,
    required: bool,
    reason: str | None = None,
) -> SectionPlan:
    if payload is None:
        return SectionPlan(
            section_id=section_id,
            availability_status="not_retained",
            required_for_model_kind=required,
            reason=reason or f"{section_id} was not retained by the governed formal source.",
        )
    return SectionPlan(
        section_id=section_id,
        availability_status="available",
        required_for_model_kind=required,
        payload=payload,
    )


def build_plan(source_path: Path, strategy: ActiveStrategy) -> RunExportPlan:
    package = _object(source_path)
    model_id = str(package.get("model_id") or "")
    if model_id != strategy.model_version_id:
        raise FormalBundleV2BuildError(
            f"formal source/model identity mismatch: {model_id} != {strategy.model_version_id}"
        )
    if (
        package.get("schema_version") != "1.0.0"
        or package.get("record_type") != "formal_model_backtest"
        or package.get("publication_status") != strategy.formal_status
        or package.get("research_only") is not True
        or package.get("trade_ready") is not False
    ):
        raise FormalBundleV2BuildError(f"formal source boundary mismatch: {model_id}")

    portfolio_contract = _mapping(package, "portfolio_contract")
    date_range = _mapping(package, "date_range")
    start = str(date_range.get("start") or "")
    end = str(date_range.get("end") or "")
    evidence_cutoff = str(package.get("evidence_cutoff") or "")
    if not start or not end or not evidence_cutoff or end > evidence_cutoff:
        raise FormalBundleV2BuildError(
            f"formal date range exceeds evidence cutoff: {model_id}: {start}/{end}/{evidence_cutoff}"
        )

    report = _list(package, "report")
    positions = _list(package, "positions")
    trades = _list(package, "trades")
    attribution = _list(package, "attribution")
    windows = _list(package, "window_summary")
    evidence = _mapping(package, "evidence")
    completeness = _mapping(package, "evidence_completeness")
    notes = package.get("interpretation_notes")
    if not isinstance(notes, list) or not all(isinstance(row, str) for row in notes):
        raise FormalBundleV2BuildError(f"interpretation notes invalid: {model_id}")

    run_id = _slug(package.get("backtest_id"), f"{model_id}_formal")
    source_sha = _sha256(source_path)
    metrics = _canonical_metrics(package, model_kind=strategy.model_kind)
    summary = {
        "schema_version": "2.0.0",
        "model_family_id": strategy.model_family_id,
        "model_version_id": model_id,
        "run_id": run_id,
        "display_name": strategy.display_name,
        "market": strategy.market,
        "benchmark": str(package.get("benchmark") or strategy.benchmark_id),
        "metrics": metrics,
        "evidence_completeness": completeness,
        "source_package_sha256": source_sha,
        "research_only": True,
        "trade_ready": False,
    }
    retained_semantics = package.get("performance_semantics")
    if isinstance(retained_semantics, Mapping) and "schema_version" not in retained_semantics:
        try:
            semantics = load_performance_semantics(strategy)
        except ModelContractError as exc:
            raise FormalBundleV2BuildError(str(exc)) from exc
    else:
        semantics = dict(
            retained_semantics
            if isinstance(retained_semantics, Mapping)
            else build_performance_semantics(
                portfolio_contract,
                trace_frequency=package.get("trace_frequency"),
            )
        )
    validate_performance_semantics(semantics)
    performance = {
        "schema_version": "2.0.0",
        "report": report,
        "date_range": date_range,
        "benchmark": package.get("benchmark"),
        "trace_frequency": package.get("trace_frequency"),
        "performance_semantics": semantics,
        "source_field": "report",
        "research_only": True,
        "trade_ready": False,
    }
    risk_metric_ids = {"annualized_volatility", "max_drawdown", "turnover", "transaction_cost"}
    risk = {
        "schema_version": "2.0.0",
        "metrics": [row for row in metrics if row["metric_id"] in risk_metric_ids],
        "source_fields": ["metrics", "report", "positions"],
        "interpretation_limit": "No tail-risk or volatility evidence is synthesized when absent from the formal source.",
        "research_only": True,
        "trade_ready": False,
    }
    robustness = {
        "schema_version": "2.0.0",
        "window_summary": windows,
        "source_field": "window_summary",
        "interpretation_limit": "No cost-sensitivity, regime or failure ledger is reconstructed.",
        "research_only": True,
        "trade_ready": False,
    }
    portfolio = {
        "schema_version": "2.0.0",
        "portfolio_contract": portfolio_contract,
        "positions": positions,
        "source_fields": ["portfolio_contract", "positions"],
        "research_only": True,
        "trade_ready": False,
    }
    diagnostics = {
        "schema_version": "2.0.0",
        "interpretation_notes": notes,
        "evidence_completeness": completeness,
        "source_field": "interpretation_notes",
        "research_only": True,
        "trade_ready": False,
    }
    lineage = {
        "schema_version": "2.0.0",
        "source_contract": "formal_model_backtest_1_0_0",
        "source_path": source_path.as_posix(),
        "source_sha256": source_sha,
        "source_package_sha256": source_sha,
        "source_backtest_id": package.get("backtest_id"),
        "source_evidence": evidence,
        "source_freshness": package.get("freshness"),
        "source_evidence_completeness": completeness,
        "historical_evidence_recomputed": False,
        "model_selection_reopened": False,
        "research_only": True,
        "trade_ready": False,
    }

    sections = (
        _section("summary", summary, required=True),
        _section("performance", performance, required=True),
        _section("risk", risk, required=False),
        _section("robustness", robustness, required=True),
        _section("portfolio", portfolio, required=True),
        _section("trades", trades if trades else None, required=False, reason=_unavailable_reason(package, "trades")),
        _section("attribution", attribution if attribution else None, required=False, reason=_unavailable_reason(package, "attribution")),
        _section("diagnostics", diagnostics, required=False),
        _section("lineage", lineage, required=True),
        _section(
            "decision",
            None,
            required=False,
            reason="Decision events are governed companion evidence; no circular decision is embedded in the run manifest.",
        ),
    )

    horizon = portfolio_contract.get("horizon_sessions")
    rebalance = portfolio_contract.get("rebalance_sessions")
    cost = portfolio_contract.get("cost_bps")
    comparability = {
        "market": strategy.market,
        "universe_id": _slug(portfolio_contract.get("universe"), f"{model_id}_universe"),
        "benchmark_id": _slug(package.get("benchmark"), "benchmark_unknown"),
        "start": start,
        "end": end,
        "trace_frequency": str(package.get("trace_frequency") or "retained_formal_source"),
        "horizon": f"{int(horizon)}_sessions" if isinstance(horizon, (int, float)) else "retained_formal_source_horizon",
        "rebalance_contract_id": (
            f"rebalance_{int(rebalance)}_sessions"
            if isinstance(rebalance, (int, float))
            else _slug(package.get("trace_frequency"), "rebalance_retained_formal_source")
        ),
        "cost_contract_id": f"cost_{int(cost)}_bps" if isinstance(cost, (int, float)) else "cost_retained_formal_source",
    }
    return RunExportPlan(
        model_family_id=strategy.model_family_id,
        model_version_id=model_id,
        run_id=run_id,
        model_kind=strategy.model_kind,
        publication_channel="formal",
        publication_status=strategy.formal_status,
        generated_at=str(package.get("generated_at") or ""),
        evidence_cutoff=evidence_cutoff,
        comparability_key=comparability,
        sections=sections,
        research_only=True,
        trade_ready=False,
    )


def build_source_bundles(
    source_root: Path,
    output_root: Path,
    strategies: Sequence[ActiveStrategy],
) -> dict[str, Any]:
    catalog_path = source_root / "catalog.json"
    catalog_sha = _sha256(catalog_path)
    source_catalog = _object(catalog_path)
    if (
        source_catalog.get("schema_version") != "1.0.0"
        or source_catalog.get("research_only") is not True
        or source_catalog.get("trade_ready") is not False
    ):
        raise FormalBundleV2BuildError("formal source catalog boundary is invalid")
    records = source_catalog.get("records")
    if not isinstance(records, list):
        raise FormalBundleV2BuildError("formal source catalog records are missing")
    source_rows = {
        str(row.get("model_id") or ""): row
        for row in records
        if isinstance(row, Mapping)
    }
    requested = {strategy.model_version_id for strategy in strategies}
    if set(source_rows) != requested:
        raise FormalBundleV2BuildError(
            f"formal source catalog must match requested source-backed strategies: expected={sorted(requested)}, observed={sorted(source_rows)}"
        )

    source_paths: dict[str, Path] = {}
    for strategy in strategies:
        row = source_rows[strategy.model_version_id]
        if row.get("publication_status") != strategy.formal_status:
            raise FormalBundleV2BuildError(f"formal source status mismatch: {strategy.model_version_id}")
        path = source_root / str(row.get("path") or "")
        if not path.is_file() or _sha256(path) != row.get("sha256"):
            raise FormalBundleV2BuildError(f"formal source digest mismatch: {strategy.model_version_id}")
        source_paths[strategy.model_version_id] = path

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)
    manifests = [
        export_model_run(build_plan(source_paths[strategy.model_version_id], strategy), output_root=output_root)
        for strategy in strategies
    ]
    update_catalog(manifests, catalog_path=output_root / "catalog.json", channel="formal")
    receipt = {
        "schema_version": "2.0.0",
        "status": "formal_sources_built_bundle_v2",
        "source_catalog_sha256": catalog_sha,
        "formal_catalog_sha256": _sha256(output_root / "catalog.json"),
        "model_version_ids": [strategy.model_version_id for strategy in strategies],
        "models": [
            {
                "model_version_id": strategy.model_version_id,
                "source_sha256": _sha256(source_paths[strategy.model_version_id]),
                "manifest_path": manifests[index].relative_to(output_root).as_posix(),
                "manifest_sha256": _sha256(manifests[index]),
            }
            for index, strategy in enumerate(strategies)
        ],
        "historical_evidence_recomputed": False,
        "model_selection_reopened": False,
        "research_only": True,
        "trade_ready": False,
    }
    (output_root / "formal-source-build-receipt.json").write_bytes(canonical_json_bytes(receipt))
    return receipt
