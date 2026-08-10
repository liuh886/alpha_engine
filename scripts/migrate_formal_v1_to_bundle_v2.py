"""Project the current accepted formal v1 packages into Model Run Bundle v2.

The projection is deterministic evidence packaging. It does not rerun models,
recompute absent ledgers, reopen model selection, or alter source packages.
Every retained row is copied into a named section and lineage binds the exact
source-package SHA-256. Obsolete accepted-model identities are not supported.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Mapping

from src.artifacts.model_run_bundle_v2 import canonical_json_bytes
from src.artifacts.model_run_exporter import (
    RunExportPlan,
    SectionPlan,
    export_model_run,
    update_catalog,
)


class FormalV1MigrationError(ValueError):
    """A formal v1 package cannot be projected without changing evidence."""


MODEL_MAP: dict[str, tuple[str, str]] = {
    "qqqi_qqq_tqqq_v4_3": ("qqq_rotation", "rules_based_allocation"),
    "us_x1_1": ("us_ranker", "cross_sectional_ranker"),
    "cn_x1_1": ("cn_ranker", "cross_sectional_ranker"),
    "byd_v1_3_recovery_event_low_vol_confirmation_v1": (
        "byd_allocation",
        "rules_based_allocation",
    ),
}

METRIC_ALIASES: dict[str, tuple[str, ...]] = {
    "total_return": ("Total Return", "total_return"),
    "annualized_return": ("Annualized Return", "CAGR", "annual_return"),
    "benchmark_return": (
        "Benchmark Return",
        "Benchmark V1.2 Return",
        "benchmark_return",
    ),
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
    "ic": ("IC",),
    "rank_ic": ("Rank IC", "Mean Rank IC"),
    "icir": ("ICIR", "Mean ICIR"),
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
        raise FormalV1MigrationError(f"invalid formal v1 JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FormalV1MigrationError(f"formal v1 root must be an object: {path}")
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
        raise FormalV1MigrationError(f"formal v1 field {key} must be a list")
    return value


def _metric_source(package: Mapping[str, Any]) -> Mapping[str, Any]:
    metrics = package.get("metrics")
    if not isinstance(metrics, Mapping):
        raise FormalV1MigrationError("formal v1 metrics must be an object")
    return metrics


def _metric(package: Mapping[str, Any], metric_id: str) -> dict[str, Any]:
    source = _metric_source(package)
    unit, direction = METRIC_META[metric_id]
    aliases = METRIC_ALIASES[metric_id]
    for label in aliases:
        value = source.get(label)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        return {
            "metric_id": metric_id,
            "value": float(value),
            "unit": unit,
            "direction": direction,
            "estimator": f"retained_v1_label:{label}",
            "availability_status": "available",
            "unavailable_reason": None,
        }
    model_kind = str(package.get("record_type") or "")
    not_applicable = (
        metric_id in {"ic", "rank_ic", "icir"}
        and model_kind == "formal_model_backtest"
    )
    return {
        "metric_id": metric_id,
        "value": None,
        "unit": unit,
        "direction": direction,
        "estimator": None,
        "availability_status": "not_applicable" if not_applicable else "not_retained",
        "unavailable_reason": (
            "not applicable to rules-based allocation model"
            if not_applicable
            else "metric was not retained in the accepted formal v1 package"
        ),
    }


def _summary(package: Mapping[str, Any], source_sha256: str) -> dict[str, Any]:
    metrics = [_metric(package, metric_id) for metric_id in METRIC_META]
    return {
        "schema_version": "2.0.0",
        "model_version_id": str(package["model_id"]),
        "display_name": str(package.get("display_name") or package["model_id"]),
        "evidence_cutoff": str(package["evidence_cutoff"]),
        "date_range": package.get("date_range"),
        "metrics": metrics,
        "source_package_sha256": source_sha256,
        "research_only": True,
        "trade_ready": False,
    }


def _performance(package: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "source_fields": ["report"],
        "report": _list(package, "report"),
        "research_only": True,
        "trade_ready": False,
    }


def _portfolio(package: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "source_fields": ["positions", "portfolio_contract"],
        "positions": _list(package, "positions"),
        "portfolio_contract": package.get("portfolio_contract"),
        "research_only": True,
        "trade_ready": False,
    }


def _trades(package: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "source_fields": ["trades"],
        "trades": _list(package, "trades"),
        "research_only": True,
        "trade_ready": False,
    }


def _attribution(package: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "source_fields": ["attribution"],
        "attribution": _list(package, "attribution"),
        "research_only": True,
        "trade_ready": False,
    }


def _robustness(package: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "source_fields": ["window_summary"],
        "window_summary": _list(package, "window_summary"),
        "research_only": True,
        "trade_ready": False,
    }


def _lineage(package: Mapping[str, Any], source_sha256: str) -> dict[str, Any]:
    return {
        "schema_version": "2.0.0",
        "source_package_sha256": source_sha256,
        "source_backtest_id": str(package.get("backtest_id") or ""),
        "source_record_type": str(package.get("record_type") or ""),
        "source_evidence": package.get("evidence"),
        "source_freshness": package.get("freshness"),
        "source_evidence_completeness": package.get("evidence_completeness"),
        "historical_evidence_recomputed": False,
        "model_selection_reopened": False,
        "research_only": True,
        "trade_ready": False,
    }


def build_plan(source_path: Path) -> RunExportPlan:
    package = _object(source_path)
    model_id = str(package.get("model_id") or "")
    try:
        family_id, model_kind = MODEL_MAP[model_id]
    except KeyError as exc:
        raise FormalV1MigrationError(f"unsupported formal v1 model: {model_id}") from exc
    source_sha256 = _sha256(source_path)
    run_id = _slug(
        package.get("backtest_id"),
        f"{model_id}-through-{package.get('evidence_cutoff')}",
    )
    sections = (
        SectionPlan("summary", "available", _summary(package, source_sha256)),
        SectionPlan("performance", "available", _performance(package)),
        SectionPlan("portfolio", "available", _portfolio(package)),
        SectionPlan(
            "trades",
            "available" if _list(package, "trades") else "not_retained",
            _trades(package) if _list(package, "trades") else None,
            None if _list(package, "trades") else "trades were not retained in formal v1",
        ),
        SectionPlan(
            "attribution",
            "available" if _list(package, "attribution") else "not_retained",
            _attribution(package) if _list(package, "attribution") else None,
            None
            if _list(package, "attribution")
            else "attribution was not retained in formal v1",
        ),
        SectionPlan("robustness", "available", _robustness(package)),
        SectionPlan("decision", "not_retained", None, "decision ledger was not retained in formal v1"),
        SectionPlan("lineage", "available", _lineage(package, source_sha256)),
    )
    return RunExportPlan(
        channel="formal",
        model_family_id=family_id,
        model_version_id=model_id,
        run_id=run_id,
        model_kind=model_kind,
        publication_status="accepted_formal_baseline",
        evidence_cutoff=str(package["evidence_cutoff"]),
        generated_at=str(package["generated_at"]),
        research_only=True,
        trade_ready=False,
        sections=sections,
    )


def migrate(source_root: Path, output_root: Path) -> dict[str, Any]:
    source_root = source_root.resolve()
    output_root = output_root.resolve()
    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True, exist_ok=False)
    catalog_path = source_root / "catalog.json"
    catalog = _object(catalog_path)
    if (
        catalog.get("schema_version") != "1.0.0"
        or catalog.get("research_only") is not True
        or catalog.get("trade_ready") is not False
    ):
        raise FormalV1MigrationError("formal v1 catalog boundary is invalid")
    records = catalog.get("records")
    if not isinstance(records, list) or not records:
        raise FormalV1MigrationError("formal v1 catalog records are missing")

    projected: list[dict[str, Any]] = []
    for row in records:
        if not isinstance(row, Mapping):
            raise FormalV1MigrationError("formal v1 catalog record is invalid")
        model_id = str(row.get("model_id") or "")
        if model_id not in MODEL_MAP:
            continue
        if row.get("publication_status") != "accepted_formal_baseline":
            raise FormalV1MigrationError(
                f"non-accepted model entered formal projection: {model_id}"
            )
        source_path = source_root / str(row.get("path") or "")
        if not source_path.is_file() or _sha256(source_path) != row.get("sha256"):
            raise FormalV1MigrationError(f"formal v1 digest mismatch: {model_id}")
        plan = build_plan(source_path)
        manifest = export_model_run(output_root, plan)
        update_catalog(output_root, manifest)
        projected.append(
            {
                "model_id": model_id,
                "model_family_id": plan.model_family_id,
                "model_kind": plan.model_kind,
                "source_path": source_path.relative_to(source_root).as_posix(),
                "source_sha256": _sha256(source_path),
                "bundle_id": manifest["bundle_id"],
            }
        )

    receipt = {
        "schema_version": "2.0.0",
        "status": "formal_v1_migrated_byte_preserving",
        "source_catalog_sha256": _sha256(catalog_path),
        "projected": projected,
        "historical_evidence_recomputed": False,
        "model_selection_reopened": False,
        "research_only": True,
        "trade_ready": False,
    }
    (output_root / "migration-receipt.json").write_bytes(canonical_json_bytes(receipt))
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=Path("data/research/formal_backtests"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("data/research/formal_model_runs"),
    )
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = migrate(args.source_root, args.output_root)
    text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
