"""Read accepted formal Model Run Bundle v2 evidence with fail-closed identity checks."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from src.artifacts.model_run_bundle_v2 import validate_catalog, validate_manifest


class FormalBundleReadError(ValueError):
    """Raised when accepted formal Bundle v2 evidence is incomplete or inconsistent."""


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalBundleReadError(f"invalid formal JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FormalBundleReadError(f"formal JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(value: Any, *, section_id: str) -> list[dict[str, Any]]:
    rows = value.get("records") if isinstance(value, Mapping) and "records" in value else value
    if not isinstance(rows, list):
        raise FormalBundleReadError(f"formal section rows are unavailable: {section_id}")
    return [copy.deepcopy(dict(row)) for row in rows if isinstance(row, Mapping)]


@dataclass(frozen=True)
class FormalRun:
    root: Path
    record: Mapping[str, Any]
    manifest_path: Path
    manifest: Mapping[str, Any]
    sections: Mapping[str, Any]

    @property
    def model_version_id(self) -> str:
        return str(self.manifest["model_version_id"])

    @property
    def evidence_cutoff(self) -> str:
        return str(self.manifest["evidence_cutoff"])

    @property
    def generated_at(self) -> str:
        return str(self.manifest["generated_at"])

    @property
    def run_id(self) -> str:
        return str(self.manifest["run_id"])

    @property
    def identity(self) -> dict[str, Any]:
        return {
            "model_version_id": self.model_version_id,
            "model_family_id": str(self.manifest["model_family_id"]),
            "model_kind": str(self.manifest["model_kind"]),
            "run_id": self.run_id,
            "bundle_id": str(self.manifest["bundle_id"]),
            "evidence_cutoff": self.evidence_cutoff,
            "manifest_path": self.manifest_path.relative_to(self.root).as_posix(),
            "manifest_sha256": _sha256(self.manifest_path),
        }

    def section(self, section_id: str) -> Any:
        if section_id not in self.sections:
            raise FormalBundleReadError(
                f"formal section is unavailable for {self.model_version_id}: {section_id}"
            )
        return self.sections[section_id]

    def replay_trace(self) -> dict[str, Any]:
        performance = self.section("performance")
        portfolio = self.section("portfolio")
        trades = self.section("trades")
        if not isinstance(performance, Mapping) or not isinstance(portfolio, Mapping):
            raise FormalBundleReadError(
                f"formal performance/portfolio sections are invalid: {self.model_version_id}"
            )
        report = performance.get("report")
        positions = portfolio.get("positions")
        contract = portfolio.get("portfolio_contract")
        if not isinstance(report, list) or not isinstance(positions, list) or not isinstance(contract, Mapping):
            raise FormalBundleReadError(
                f"formal replay trace is incomplete: {self.model_version_id}"
            )
        trade_rows = trades.get("records") if isinstance(trades, Mapping) else trades
        if not isinstance(trade_rows, list):
            raise FormalBundleReadError(
                f"formal trades are unavailable for replay: {self.model_version_id}"
            )
        return {
            "portfolio_contract": copy.deepcopy(dict(contract)),
            "report": copy.deepcopy(list(report)),
            "positions": copy.deepcopy(list(positions)),
            "trades": copy.deepcopy(list(trade_rows)),
        }

    def refresh_state(self) -> dict[str, Any]:
        """Return mutable model-refresh evidence reconstructed only from Bundle v2 sections.

        This is an in-process strategy working state, never a repository authority. A
        refreshed strategy seals it directly into a preview Bundle v2 before fan-in.
        """

        performance = self.section("performance")
        portfolio = self.section("portfolio")
        summary = self.section("summary")
        robustness = self.section("robustness")
        diagnostics = self.section("diagnostics")
        lineage = self.section("lineage")
        if not all(
            isinstance(value, Mapping)
            for value in (performance, portfolio, summary, robustness, diagnostics, lineage)
        ):
            raise FormalBundleReadError(
                f"formal refresh sections are invalid: {self.model_version_id}"
            )
        report = performance.get("report")
        positions = portfolio.get("positions")
        contract = portfolio.get("portfolio_contract")
        date_range = performance.get("date_range")
        metrics_rows = summary.get("metrics")
        windows = robustness.get("window_summary")
        notes = diagnostics.get("interpretation_notes")
        completeness = diagnostics.get("evidence_completeness") or summary.get("evidence_completeness")
        if (
            not isinstance(report, list)
            or not isinstance(positions, list)
            or not isinstance(contract, Mapping)
            or not isinstance(date_range, Mapping)
            or not isinstance(metrics_rows, list)
            or not isinstance(windows, list)
            or not isinstance(notes, list)
            or not isinstance(completeness, Mapping)
        ):
            raise FormalBundleReadError(
                f"formal refresh state is incomplete: {self.model_version_id}"
            )

        metrics: dict[str, float] = {}
        for row in metrics_rows:
            if not isinstance(row, Mapping) or row.get("availability_status") != "available":
                continue
            value = row.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                metrics[str(row.get("metric_id") or "")] = float(value)

        source_evidence = lineage.get("source_evidence")
        source_freshness = lineage.get("source_freshness")
        evidence = copy.deepcopy(dict(source_evidence)) if isinstance(source_evidence, Mapping) else {}
        evidence.update(
            {
                "accepted_formal_bundle_id": str(self.manifest["bundle_id"]),
                "accepted_formal_run_id": self.run_id,
                "accepted_formal_manifest_sha256": _sha256(self.manifest_path),
            }
        )
        freshness = (
            copy.deepcopy(dict(source_freshness))
            if isinstance(source_freshness, Mapping)
            else {
                "status": "current",
                "required_cutoff": self.evidence_cutoff,
                "latest_completed_session": self.evidence_cutoff,
                "model_selection_reopened": False,
                "research_only": True,
                "trade_ready": False,
            }
        )
        trades = _rows(self.section("trades"), section_id="trades")
        attribution = _rows(self.section("attribution"), section_id="attribution")

        return {
            "schema_version": "governed_model_evidence_v1",
            "record_type": "governed_model_evidence",
            "model_id": self.model_version_id,
            "backtest_id": self.run_id,
            "publication_status": "accepted_formal_baseline",
            "generated_at": self.generated_at,
            "evidence_cutoff": self.evidence_cutoff,
            "benchmark": performance.get("benchmark"),
            "trace_frequency": performance.get("trace_frequency"),
            "date_range": copy.deepcopy(dict(date_range)),
            "performance_semantics": copy.deepcopy(performance.get("performance_semantics")),
            "portfolio_contract": copy.deepcopy(dict(contract)),
            "metrics": metrics,
            "report": copy.deepcopy(list(report)),
            "positions": copy.deepcopy(list(positions)),
            "trades": trades,
            "attribution": attribution,
            "window_summary": copy.deepcopy(list(windows)),
            "interpretation_notes": copy.deepcopy(list(notes)),
            "evidence_completeness": copy.deepcopy(dict(completeness)),
            "evidence": evidence,
            "freshness": freshness,
            "research_only": True,
            "trade_ready": False,
        }


def _load_formal_manifest(
    repository: Path,
    formal_root: Path,
    record: Mapping[str, Any],
) -> FormalRun:
    model_version_id = str(record.get("model_version_id") or "")
    manifest_path = (formal_root / str(record.get("manifest_path") or "")).resolve()
    try:
        manifest_path.relative_to(formal_root)
    except ValueError as exc:
        raise FormalBundleReadError("formal manifest escapes formal root") from exc
    if not manifest_path.is_file() or _sha256(manifest_path) != record.get("manifest_sha256"):
        raise FormalBundleReadError(f"formal manifest digest mismatch: {model_version_id}")
    manifest = _object(manifest_path)
    validate_manifest(manifest)
    for field in (
        "model_version_id",
        "model_family_id",
        "model_kind",
        "run_id",
        "bundle_id",
        "evidence_cutoff",
        "publication_status",
    ):
        if manifest.get(field) != record.get(field):
            raise FormalBundleReadError(
                f"formal manifest/catalog mismatch for {model_version_id}: {field}"
            )
    if (
        manifest.get("publication_channel") != "formal"
        or manifest.get("publication_status") != "accepted_formal_baseline"
        or manifest.get("research_only") is not True
        or manifest.get("trade_ready") is not False
    ):
        raise FormalBundleReadError(f"formal manifest boundary is invalid: {model_version_id}")

    run_dir = manifest_path.parent
    sections: dict[str, Any] = {}
    for declaration in manifest.get("sections", []):
        if not isinstance(declaration, Mapping):
            raise FormalBundleReadError("formal section declaration is invalid")
        if declaration.get("availability_status") != "available":
            continue
        section_id = str(declaration.get("section_id") or "")
        path = (run_dir / str(declaration.get("path") or "")).resolve()
        try:
            path.relative_to(run_dir)
        except ValueError as exc:
            raise FormalBundleReadError(f"formal section escapes run: {section_id}") from exc
        if not path.is_file():
            raise FormalBundleReadError(f"formal section is missing: {section_id}")
        data = path.read_bytes()
        if (
            len(data) != declaration.get("byte_size")
            or hashlib.sha256(data).hexdigest() != declaration.get("sha256")
        ):
            raise FormalBundleReadError(f"formal section digest mismatch: {section_id}")
        try:
            value = json.loads(data)
        except json.JSONDecodeError as exc:
            raise FormalBundleReadError(f"formal section JSON is invalid: {section_id}") from exc
        sections[section_id] = value

    return FormalRun(
        root=repository,
        record=record,
        manifest_path=manifest_path,
        manifest=manifest,
        sections=sections,
    )


def load_formal_run(
    repository_root: str | Path,
    model_version_id: str,
    *,
    relative_root: Path = Path("data/research/formal_model_runs"),
) -> FormalRun:
    """Load the one catalog-active accepted formal run for a model."""

    repository = Path(repository_root).resolve()
    formal_root = (repository / relative_root).resolve()
    try:
        formal_root.relative_to(repository)
    except ValueError as exc:
        raise FormalBundleReadError("formal root escapes repository") from exc

    catalog_path = formal_root / "catalog.json"
    catalog = _object(catalog_path)
    validate_catalog(catalog)
    if (
        catalog.get("channel") != "formal"
        or catalog.get("research_only") is not True
        or catalog.get("trade_ready") is not False
    ):
        raise FormalBundleReadError("formal catalog boundary is invalid")
    rows = catalog.get("records")
    if not isinstance(rows, list):
        raise FormalBundleReadError("formal catalog records are missing")
    matches = [
        dict(row)
        for row in rows
        if isinstance(row, Mapping) and row.get("model_version_id") == model_version_id
    ]
    if len(matches) != 1:
        raise FormalBundleReadError(
            f"expected one accepted formal run for {model_version_id}, found {len(matches)}"
        )
    record = matches[0]
    if record.get("publication_status") != "accepted_formal_baseline":
        raise FormalBundleReadError(f"formal run is not accepted: {model_version_id}")
    return _load_formal_manifest(repository, formal_root, record)


def load_retained_formal_run(
    repository_root: str | Path,
    manifest_relative_path: str | Path,
    *,
    relative_root: Path = Path("data/research/formal_model_runs"),
) -> FormalRun:
    """Load one immutable retained formal bundle outside the active catalog.

    Superseded models remain auditable after the active catalog advances.  This
    route keeps the same manifest and section digest checks as the active reader,
    but it intentionally does not claim that the model is currently active.
    """

    repository = Path(repository_root).resolve()
    formal_root = (repository / relative_root).resolve()
    manifest_path = (repository / manifest_relative_path).resolve()
    try:
        formal_root.relative_to(repository)
        relative_manifest = manifest_path.relative_to(formal_root)
    except ValueError as exc:
        raise FormalBundleReadError("retained formal manifest escapes formal root") from exc
    if not manifest_path.is_file():
        raise FormalBundleReadError(f"retained formal manifest is missing: {manifest_path}")
    manifest = _object(manifest_path)
    validate_manifest(manifest)
    record = {
        "model_version_id": manifest.get("model_version_id"),
        "model_family_id": manifest.get("model_family_id"),
        "model_kind": manifest.get("model_kind"),
        "run_id": manifest.get("run_id"),
        "bundle_id": manifest.get("bundle_id"),
        "evidence_cutoff": manifest.get("evidence_cutoff"),
        "publication_status": manifest.get("publication_status"),
        "manifest_path": relative_manifest.as_posix(),
        "manifest_sha256": _sha256(manifest_path),
    }
    return _load_formal_manifest(repository, formal_root, record)
