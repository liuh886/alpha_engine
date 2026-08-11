"""Production contract for accepted Model Run Bundle v2 formal evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from src.artifacts.model_run_bundle_v2 import (
    validate_catalog,
    validate_manifest,
    validate_metric,
)
from src.artifacts.performance_semantics import validate_performance_semantics

FORMAL_EVIDENCE_CONTRACT_ID = "native_formal_bundle_v2"

CANONICAL_METRIC_IDS = {
    "total_return",
    "annualized_return",
    "benchmark_return",
    "excess_return",
    "annualized_volatility",
    "sharpe_ratio",
    "information_ratio",
    "max_drawdown",
    "turnover",
    "transaction_cost",
    "ic",
    "rank_ic",
    "icir",
}

REQUIRED_AVAILABLE_SECTIONS = {
    "summary",
    "performance",
    "risk",
    "robustness",
    "portfolio",
    "trades",
    "attribution",
    "diagnostics",
    "lineage",
}

REQUIRED_PERFORMANCE_SEMANTICS = {
    "signal_time",
    "execution_time",
    "return_measurement",
    "price_basis",
}


class FormalEvidenceStandardError(ValueError):
    """Raised when an accepted formal bundle violates the production contract."""


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalEvidenceStandardError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FormalEvidenceStandardError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FormalEvidenceStandardError(message)


def _declared_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and value.strip().lower() not in {
        "not declared",
        "not_declared",
    }


def _declared_holding_end(value: object) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and value >= 0
    ) or _declared_text(value)


def _validate_contract_envelope(summary: Mapping[str, Any]) -> Mapping[str, Any]:
    _require(
        summary.get("evidence_contract") == FORMAL_EVIDENCE_CONTRACT_ID,
        "formal evidence contract identity is missing",
    )
    semantics = summary.get("performance_semantics")
    _require(isinstance(semantics, Mapping), "formal performance semantics are missing")
    validate_performance_semantics(semantics)
    for key in REQUIRED_PERFORMANCE_SEMANTICS:
        _require(_declared_text(semantics.get(key)), f"performance semantics missing {key}")
    _require(
        _declared_holding_end(semantics.get("holding_end_offset_sessions")),
        "holding-end semantics are not declared",
    )
    cost = semantics.get("cost")
    _require(isinstance(cost, Mapping), "performance cost semantics are missing")
    _require(
        isinstance(cost.get("rate_bps"), (int, float)) and not isinstance(cost.get("rate_bps"), bool),
        "performance cost rate is not declared",
    )
    _require(_declared_text(cost.get("turnover_formula")), "turnover formula is not declared")
    _require(_declared_text(cost.get("net_return_formula")), "net-return formula is not declared")

    portfolio_contract = summary.get("portfolio_contract")
    _require(isinstance(portfolio_contract, Mapping), "formal portfolio contract is missing")
    for key in ("signal_time", "execution_time", "price_basis", "turnover_formula"):
        _require(_declared_text(portfolio_contract.get(key)), f"portfolio contract missing {key}")
    return semantics


def _validate_performance_endpoint(
    *,
    manifest: Mapping[str, Any],
    summary: Mapping[str, Any],
    performance: Mapping[str, Any],
    semantics: Mapping[str, Any],
) -> None:
    date_range = performance.get("date_range")
    _require(isinstance(date_range, Mapping), "formal performance date range is missing")
    performance_end = str(date_range.get("end") or "")
    _require(bool(performance_end), "formal performance end is missing")

    comparability = manifest.get("comparability_key")
    _require(isinstance(comparability, Mapping), "formal comparability key is missing")
    comparability_end = str(comparability.get("end") or "")
    _require(
        performance_end == comparability_end,
        "formal performance end and comparability end diverge",
    )

    report = performance.get("report")
    _require(isinstance(report, list) and bool(report), "formal performance report is empty")
    latest = report[-1]
    _require(isinstance(latest, Mapping), "latest formal performance row is invalid")
    date_field = str(semantics.get("performance_date_field") or "date")
    _require(
        date_field in {"date", "holding_end_date"},
        "formal performance date field is unsupported",
    )
    latest_observation = str(latest.get(date_field) or "")
    _require(
        latest_observation == performance_end,
        "latest formal performance observation does not reach declared end",
    )

    observation_end = summary.get("performance_observation_end")
    if observation_end is not None:
        _require(
            str(observation_end) == performance_end,
            "formal summary performance observation end diverges",
        )
    if summary.get("performance_observation_status") == "provisional_mtm":
        _require(
            performance_end == str(manifest.get("evidence_cutoff") or ""),
            "provisional MTM does not reach the evidence cutoff",
        )
        _require(latest.get("provisional_mtm") is True, "latest formal row is not marked provisional MTM")
        _require(
            latest.get("settlement_status") == "provisional_mtm",
            "latest formal MTM settlement status is invalid",
        )


def validate_formal_evidence_bundle(run_dir: Path) -> None:
    """Validate the production evidence contract for an accepted formal model."""

    manifest_path = run_dir / "manifest.json"
    manifest = _object(manifest_path)
    validate_manifest(manifest)
    _require(manifest["publication_channel"] == "formal", "formal channel is required")
    _require(
        manifest["publication_status"] == "accepted_formal_baseline",
        "accepted formal status is required",
    )

    sections = {row["section_id"]: row for row in manifest["sections"]}
    _require(
        REQUIRED_AVAILABLE_SECTIONS <= set(sections),
        "formal evidence section set is incomplete",
    )
    for section_id in REQUIRED_AVAILABLE_SECTIONS:
        section = sections[section_id]
        _require(
            section["availability_status"] == "available",
            f"required formal section is unavailable: {section_id}",
        )
        path = run_dir / str(section["path"])
        _require(path.is_file(), f"formal section file is missing: {section_id}")
        data = path.read_bytes()
        _require(len(data) == section["byte_size"], f"formal section size mismatch: {section_id}")
        _require(
            hashlib.sha256(data).hexdigest() == section["sha256"],
            f"formal section digest mismatch: {section_id}",
        )

    summary = _object(run_dir / str(sections["summary"]["path"]))
    semantics = _validate_contract_envelope(summary)
    metrics = summary.get("metrics")
    _require(isinstance(metrics, list), "formal summary canonical metrics are missing")
    metric_ids: set[str] = set()
    for metric in metrics:
        _require(isinstance(metric, Mapping), "invalid canonical metric")
        validate_metric(metric)
        metric_id = str(metric["metric_id"])
        _require(metric_id not in metric_ids, f"duplicate canonical metric: {metric_id}")
        metric_ids.add(metric_id)
    _require(metric_ids == CANONICAL_METRIC_IDS, "canonical metric inventory is incomplete")

    completeness = summary.get("evidence_completeness")
    _require(isinstance(completeness, Mapping), "evidence completeness is missing")
    _require(completeness.get("status") == "complete", "formal evidence must be complete")
    _require(completeness.get("missing") == [], "formal evidence has unresolved missing items")
    not_applicable = completeness.get("not_applicable", [])
    _require(isinstance(not_applicable, list), "not_applicable must be an explicit list")

    performance = _object(run_dir / str(sections["performance"]["path"]))
    _validate_performance_endpoint(
        manifest=manifest,
        summary=summary,
        performance=performance,
        semantics=semantics,
    )

    diagnostics = _object(run_dir / str(sections["diagnostics"]["path"]))
    diagnostics_completeness = diagnostics.get("evidence_completeness")
    _require(isinstance(diagnostics_completeness, Mapping), "diagnostics completeness is missing")
    _require(
        diagnostics_completeness.get("status") == "complete",
        "diagnostics do not confirm complete evidence",
    )

    for section_id in REQUIRED_AVAILABLE_SECTIONS:
        payload = json.loads((run_dir / str(sections[section_id]["path"])).read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            _require(payload.get("research_only") is True, f"{section_id} research boundary changed")
            _require(payload.get("trade_ready") is False, f"{section_id} trade-ready boundary changed")


def validate_formal_catalog_evidence(catalog_path: Path) -> list[str]:
    """Require every active formal catalog record to satisfy the same evidence contract."""

    catalog = _object(catalog_path)
    validate_catalog(catalog)
    _require(catalog.get("channel") == "formal", "formal evidence catalog channel is invalid")
    _require(
        catalog.get("research_only") is True and catalog.get("trade_ready") is False,
        "formal evidence catalog research boundary is invalid",
    )
    records = catalog.get("records")
    _require(isinstance(records, list) and bool(records), "formal evidence catalog is empty")

    model_ids: list[str] = []
    root = catalog_path.parent
    for record in records:
        _require(isinstance(record, Mapping), "formal evidence catalog record is invalid")
        model_id = str(record.get("model_version_id") or "")
        _require(bool(model_id) and model_id not in model_ids, f"duplicate formal model: {model_id!r}")
        manifest_path = root / str(record.get("manifest_path") or "")
        _require(manifest_path.is_file(), f"formal manifest is missing: {model_id}")
        _require(
            _sha256(manifest_path) == record.get("manifest_sha256"),
            f"formal manifest digest mismatch: {model_id}",
        )
        manifest = _object(manifest_path)
        _require(manifest.get("bundle_id") == record.get("bundle_id"), f"formal bundle id mismatch: {model_id}")
        _require(manifest.get("model_version_id") == model_id, f"formal model identity mismatch: {model_id}")
        validate_formal_evidence_bundle(manifest_path.parent)
        model_ids.append(model_id)
    return model_ids
