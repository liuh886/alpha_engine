"""Project the current accepted formal v1 packages into Model Run Bundle v2.

The projection is deterministic evidence packaging. It does not rerun models,
recompute absent ledgers, reopen model selection, or alter accepted v1 source
packages. Only the current accepted formal model set is supported.
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


def _mapping(package: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = package.get(key)
    if not isinstance(value, Mapping):
        raise FormalV1MigrationError(f"formal v1 field {key} must be an object")
    return dict(value)


def _canonical_metrics(
    package: Mapping[str, Any], *, model_kind: str
) -> list[dict[str, Any]]:
    raw = _mapping(package, "metrics")
    sample_count = len(_list(package, "report"))
    rows: list[dict[str, Any]] = []
    for metric_id, aliases in METRIC_ALIASES.items():
        source_label = next((label for label in aliases if label in raw), None)
        unit, direction = METRIC_META[metric_id]
        if source_label is not None:
            value = raw[source_label]
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise FormalV1MigrationError(
                    f"metric {source_label} is not a retained number"
                )
            rows.append(
                {
                    "metric_id": metric_id,
                    "value": float(value),
                    "unit": unit,
                    "direction": direction,
                    "estimator": f"retained_v1_label:{source_label}",
                    "annualization": (
                        "retained_v1_semantics"
                        if metric_id
                        in {
                            "annualized_return",
                            "annualized_volatility",
                            "sharpe_ratio",
                            "information_ratio",
                        }
                        else None
                    ),
                    "sample_count": sample_count,
                    "scope": "accepted_formal_v1_observed_window",
                    "availability_status": "available",
                    "unavailable_reason": None,
                }
            )
            continue
        not_applicable = model_kind == "rules_based_allocation" and metric_id in {
            "ic",
            "rank_ic",
            "icir",
        }
        rows.append(
            {
                "metric_id": metric_id,
                "value": None,
                "unit": unit,
                "direction": direction,
                "estimator": None,
                "annualization": None,
                "sample_count": None,
                "scope": "accepted_formal_v1_observed_window",
                "availability_status": (
                    "not_applicable" if not_applicable else "not_retained"
                ),
                "unavailable_reason": (
                    "Cross-sectional prediction metrics do not apply to the "
                    "rules-based allocation model."
                    if not_applicable
                    else "The accepted formal v1 package does not retain this "
                    "canonical metric; migration does not recompute it."
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
                f"The accepted formal v1 source did not retain {key}; declared "
                f"missing evidence includes: {', '.join(str(row) for row in missing)}."
            )
    return (
        f"The accepted formal v1 source did not retain {key}; "
        "migration does not reconstruct it."
    )


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
            reason=reason or f"{section_id} was not retained by the accepted v1 source.",
        )
    return SectionPlan(
        section_id=section_id,
        availability_status="available",
        required_for_model_kind=required,
        payload=payload,
    )


def build_plan(source_path: Path) -> RunExportPlan:
    package = _object(source_path)
    model_id = str(package.get("model_id") or "")
    if model_id not in MODEL_MAP:
        raise FormalV1MigrationError(f"unsupported formal model: {model_id}")
    family, model_kind = MODEL_MAP[model_id]
    if (
        package.get("schema_version") != "1.0.0"
        or package.get("record_type") != "formal_model_backtest"
        or package.get("publication_status") != "accepted_formal_baseline"
        or package.get("research_only") is not True
        or package.get("trade_ready") is not False
    ):
        raise FormalV1MigrationError(f"formal v1 boundary mismatch: {model_id}")

    portfolio_contract = _mapping(package, "portfolio_contract")
    date_range = _mapping(package, "date_range")
    start = str(date_range.get("start") or "")
    end = str(date_range.get("end") or "")
    evidence_cutoff = str(package.get("evidence_cutoff") or "")
    if not start or not end or not evidence_cutoff or end > evidence_cutoff:
        raise FormalV1MigrationError(
            f"formal date range exceeds evidence cutoff: {model_id}: "
            f"{start}/{end}/{evidence_cutoff}"
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
        raise FormalV1MigrationError(f"interpretation notes invalid: {model_id}")

    run_id = _slug(package.get("backtest_id"), f"{model_id}_formal")
    source_sha = _sha256(source_path)
    summary = {
        "schema_version": "2.0.0",
        "model_family_id": family,
        "model_version_id": model_id,
        "run_id": run_id,
        "display_name": str(package.get("display_name") or model_id),
        "market": str(package.get("market") or ""),
        "benchmark": str(package.get("benchmark") or ""),
        "metrics": _canonical_metrics(package, model_kind=model_kind),
        "evidence_completeness": completeness,
        "source_package_sha256": source_sha,
        "research_only": True,
        "trade_ready": False,
    }
    performance = {
        "schema_version": "2.0.0",
        "report": report,
        "date_range": date_range,
        "benchmark": package.get("benchmark"),
        "trace_frequency": package.get("trace_frequency"),
        "source_field": "report",
        "research_only": True,
        "trade_ready": False,
    }
    risk_metric_ids = {
        "annualized_volatility",
        "max_drawdown",
        "turnover",
        "transaction_cost",
    }
    risk = {
        "schema_version": "2.0.0",
        "metrics": [
            row for row in summary["metrics"] if row["metric_id"] in risk_metric_ids
        ],
        "source_fields": ["metrics", "report", "positions"],
        "interpretation_limit": (
            "No tail-risk or volatility evidence is synthesized when absent from v1."
        ),
        "research_only": True,
        "trade_ready": False,
    }
    robustness = {
        "schema_version": "2.0.0",
        "window_summary": windows,
        "source_field": "window_summary",
        "interpretation_limit": (
            "No cost-sensitivity, regime or failure ledger is reconstructed."
        ),
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
        "migration_adapter": "formal_v1_to_bundle_v2_v2",
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
        _section(
            "trades",
            trades if trades else None,
            required=False,
            reason=_unavailable_reason(package, "trades"),
        ),
        _section(
            "attribution",
            attribution if attribution else None,
            required=False,
            reason=_unavailable_reason(package, "attribution"),
        ),
        _section("diagnostics", diagnostics, required=False),
        _section("lineage", lineage, required=True),
        _section(
            "decision",
            None,
            required=False,
            reason=(
                "Decision receipts are governed companion artifacts bound to bundle_id; "
                "no decision is embedded in the evidence manifest."
            ),
        ),
    )

    horizon = portfolio_contract.get("horizon_sessions")
    rebalance = portfolio_contract.get("rebalance_sessions")
    cost = portfolio_contract.get("cost_bps")
    comparability = {
        "market": str(package.get("market") or "unknown"),
        "universe_id": _slug(
            portfolio_contract.get("universe"), f"{model_id}_universe"
        ),
        "benchmark_id": _slug(package.get("benchmark"), "benchmark_unknown"),
        "start": start,
        "end": end,
        "trace_frequency": str(package.get("trace_frequency") or "retained_v1"),
        "horizon": (
            f"{int(horizon)}_sessions"
            if isinstance(horizon, (int, float))
            else "retained_v1_horizon"
        ),
        "rebalance_contract_id": (
            f"rebalance_{int(rebalance)}_sessions"
            if isinstance(rebalance, (int, float))
            else _slug(package.get("trace_frequency"), "rebalance_retained_v1")
        ),
        "cost_contract_id": (
            f"cost_{int(cost)}_bps"
            if isinstance(cost, (int, float))
            else "cost_retained_v1"
        ),
    }
    return RunExportPlan(
        model_family_id=family,
        model_version_id=model_id,
        run_id=run_id,
        model_kind=model_kind,
        publication_channel="formal",
        publication_status="accepted_formal_baseline",
        generated_at=str(package.get("generated_at") or ""),
        evidence_cutoff=evidence_cutoff,
        comparability_key=comparability,
        sections=sections,
        research_only=True,
        trade_ready=False,
    )


def migrate(source_root: Path, output_root: Path) -> dict[str, Any]:
    catalog_path = source_root / "catalog.json"
    catalog_sha = _sha256(catalog_path)
    source_catalog = _object(catalog_path)
    if (
        source_catalog.get("schema_version") != "1.0.0"
        or source_catalog.get("research_only") is not True
        or source_catalog.get("trade_ready") is not False
    ):
        raise FormalV1MigrationError("formal v1 catalog boundary is invalid")
    records = source_catalog.get("records")
    if not isinstance(records, list):
        raise FormalV1MigrationError("formal v1 catalog records are missing")

    source_paths: dict[str, Path] = {}
    for row in records:
        if not isinstance(row, Mapping):
            raise FormalV1MigrationError("formal v1 catalog record is invalid")
        model_id = str(row.get("model_id") or "")
        if row.get("publication_status") != "accepted_formal_baseline":
            raise FormalV1MigrationError(
                f"non-accepted record entered formal catalog: {model_id}"
            )
        if model_id not in MODEL_MAP:
            raise FormalV1MigrationError(
                f"unsupported accepted formal model: {model_id}"
            )
        path = source_root / str(row.get("path") or "")
        if not path.is_file() or _sha256(path) != row.get("sha256"):
            raise FormalV1MigrationError(f"formal v1 catalog digest mismatch: {model_id}")
        source_paths[model_id] = path
    if set(source_paths) != set(MODEL_MAP):
        raise FormalV1MigrationError(
            "formal v1 catalog must contain exactly the current accepted model set"
        )

    if output_root.exists():
        shutil.rmtree(output_root)
    output_root.mkdir(parents=True)
    manifests = [
        export_model_run(build_plan(source_paths[model_id]), output_root=output_root)
        for model_id in MODEL_MAP
    ]
    update_catalog(
        manifests,
        catalog_path=output_root / "catalog.json",
        channel="formal",
    )
    receipt = {
        "schema_version": "2.0.0",
        "status": "formal_v1_migrated_byte_preserving",
        "source_catalog_sha256": catalog_sha,
        "formal_catalog_sha256": _sha256(output_root / "catalog.json"),
        "models": [
            {
                "model_id": model_id,
                "source_sha256": _sha256(source_paths[model_id]),
                "manifest_path": manifests[index].relative_to(output_root).as_posix(),
                "manifest_sha256": _sha256(manifests[index]),
            }
            for index, model_id in enumerate(MODEL_MAP)
        ],
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
