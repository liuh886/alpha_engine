"""Fail-closed verification for one explicitly selected release candidate."""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.data.snapshot import compute_aggregate_hash
from src.data.snapshot_manifest import SnapshotManifest

REQUIRED_RELEASE_METRICS: tuple[str, ...] = (
    "ic",
    "rank_ic",
    "icir",
    "consistency",
    "sample_count",
    "coverage",
    "annualized_return",
    "total_return",
    "benchmark_return",
    "excess_return",
    "volatility",
    "sharpe",
    "information_ratio",
    "max_drawdown",
    "turnover",
    "costs",
    "net_return",
)

_MODEL_REQUIRED_FIELDS = (
    "id",
    "model_binary_path",
    "config",
    "features",
    "label_schema",
    "snapshot_id",
    "train_window",
    "valid_window",
    "test_window",
    "benchmark",
    "costs",
    "code_revision",
    "uv_lock_hash",
    "python_version",
    "seeds",
    "predictions_path",
    "labels_path",
    "diagnostics_path",
    "checksums",
)
POLICY: dict[str, Any] = {
    "id": "t48-release-v1",
    "min_icir": 0.3,
    "min_consistency": 0.55,
    "min_samples": 10,
    "max_drawdown": -0.15,
}
_POLICY = POLICY  # backward-compat alias for internal verifier use
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CANDIDATE_ID_RE = re.compile(r"^(?:rc_)?(?:v?\d[\w.-]*|\d{8})$")


@dataclass(frozen=True)
class VerificationCheck:
    """One deterministic verification result."""

    code: str
    passed: bool
    subject: str
    detail: str


@dataclass
class VerificationReport:
    """Machine-readable verdict for exactly one release-candidate manifest."""

    candidate_manifest: str
    candidate_manifest_sha256: str | None = None
    release_candidate_id: str | None = None
    checks: list[VerificationCheck] = field(default_factory=list)
    verified_ids: dict[str, dict[str, str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)

    def add(self, code: str, passed: bool, subject: str, detail: str) -> None:
        self.checks.append(
            VerificationCheck(code=code, passed=passed, subject=subject, detail=detail)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_manifest": self.candidate_manifest,
            "candidate_manifest_sha256": self.candidate_manifest_sha256,
            "release_candidate_id": self.release_candidate_id,
            "status": "pass" if self.ok else "fail",
            "verified_ids": self.verified_ids,
            "checks": [asdict(check) for check in self.checks],
        }


def resolve_candidate_reference(reference: str | Path, project_root: str | Path) -> Path:
    """Resolve an explicit manifest path or an exact ``rc_*`` identifier.

    IDs map to one conventional path. This function never searches directories,
    follows a ``latest`` pointer, or compares historical candidates.
    """
    root = Path(project_root).resolve()
    raw = str(reference)
    if _CANDIDATE_ID_RE.fullmatch(raw):
        candidate_dir = raw.removeprefix("rc_")
        return root / "artifacts" / "release_candidate" / candidate_dir / "release_manifest.json"
    path = Path(reference)
    return path.resolve() if path.is_absolute() else (root / path).resolve()


def get_git_revision(project_root: str | Path) -> str:
    """Return the exact checkout revision, or an empty string on failure."""
    return _git_revision(Path(project_root).resolve())


def verify_release_candidate(
    candidate_manifest: str | Path,
    *,
    project_root: str | Path,
    revision: str | None = None,
) -> VerificationReport:
    """Verify only the candidate named by ``candidate_manifest``."""
    root = Path(project_root).resolve()
    candidate_path = Path(candidate_manifest).resolve()
    report = VerificationReport(candidate_manifest=_display_path(candidate_path, root))
    if not _is_within(candidate_path, root):
        report.add(
            "candidate_path_outside_project",
            False,
            str(candidate_path),
            "candidate manifest must be inside the project root",
        )
        return report
    if not candidate_path.is_file():
        report.add(
            "candidate_manifest_missing", False, report.candidate_manifest, "file does not exist"
        )
        return report

    report.candidate_manifest_sha256 = _sha256(candidate_path)
    candidate = _read_json_object(candidate_path, report, "candidate_manifest_invalid")
    if candidate is None:
        return report

    candidate_id = candidate.get("release_candidate_id")
    report.release_candidate_id = candidate_id if isinstance(candidate_id, str) else None
    report.add(
        "candidate_identity",
        isinstance(candidate_id, str) and bool(candidate_id.strip()),
        report.candidate_manifest,
        f"release_candidate_id={candidate_id!r}",
    )
    report.add(
        "candidate_schema",
        candidate.get("schema_version") == "1",
        report.candidate_manifest,
        f"schema_version={candidate.get('schema_version')!r}; expected '1'",
    )

    current_revision = revision if revision is not None else _git_revision(root)
    code_identity = candidate.get("code_identity")
    if not isinstance(code_identity, dict):
        report.add(
            "code_identity_missing",
            False,
            report.candidate_manifest,
            "code_identity object is required",
        )
        code_identity = {}
    pinned_revision = code_identity.get("revision")
    report.add(
        "code_revision",
        bool(current_revision) and pinned_revision == current_revision,
        report.candidate_manifest,
        f"pinned={pinned_revision!r}; checkout={current_revision!r}",
    )
    lock_hash = _verify_lockfile(code_identity.get("lockfile"), root, report)
    _verify_metric_schema(candidate.get("metric_schema"), report)
    _verify_gate_policy(candidate.get("gate_policy"), report)

    markets = candidate.get("markets")
    if not isinstance(markets, dict):
        report.add(
            "markets_missing", False, report.candidate_manifest, "markets object is required"
        )
        markets = {}
    valid_markets = {"cn", "us"}
    market_names = set(markets)
    if not market_names:
        report.add(
            "market_scope",
            False,
            report.candidate_manifest,
            "at least one market is required",
        )
    elif not market_names.issubset(valid_markets):
        report.add(
            "market_scope",
            False,
            report.candidate_manifest,
            f"markets={sorted(market_names)}; valid={sorted(valid_markets)}",
        )
    else:
        report.add(
            "market_scope",
            True,
            report.candidate_manifest,
            f"markets={sorted(market_names)}",
        )
    for market in sorted(market_names & valid_markets):
        value = markets.get(market)
        if not isinstance(value, dict):
            report.add("market_manifest_missing", False, market, "market object is required")
            continue
        _verify_market(
            market,
            value,
            root=root,
            revision=pinned_revision if isinstance(pinned_revision, str) else "",
            lock_hash=lock_hash,
            report=report,
        )

    _verify_frontend(candidate.get("frontend_build"), root, pinned_revision, report)
    return report


def _verify_lockfile(value: Any, root: Path, report: VerificationReport) -> str:
    if not isinstance(value, dict):
        report.add("lock_identity_missing", False, "code_identity", "lockfile object is required")
        return ""
    path = _project_path(value.get("path"), root)
    expected = value.get("sha256")
    if path is None or not path.is_file():
        report.add(
            "lockfile_missing", False, "code_identity.lockfile", "referenced lockfile missing"
        )
        return ""
    actual = _sha256(path)
    report.add(
        "lockfile_checksum",
        _valid_hash(expected) and expected == actual,
        _display_path(path, root),
        f"expected={expected!r}; actual={actual}",
    )
    return actual


def _verify_metric_schema(value: Any, report: VerificationReport) -> None:
    if not isinstance(value, dict):
        report.add(
            "metric_schema_missing", False, "metric_schema", "metric_schema object is required"
        )
        return
    fields = value.get("required_fields")
    report.add(
        "metric_schema_version",
        value.get("version") == "v1",
        "metric_schema",
        f"version={value.get('version')!r}; expected 'v1'",
    )
    report.add(
        "metric_schema_fields",
        fields == list(REQUIRED_RELEASE_METRICS),
        "metric_schema",
        "required_fields must exactly match the t48 v1 release schema",
    )


def _verify_gate_policy(value: Any, report: VerificationReport) -> None:
    passed = isinstance(value, dict) and value == _POLICY
    report.add(
        "gate_policy",
        passed,
        "gate_policy",
        f"policy must exactly equal {_POLICY!r}",
    )


def _verify_market(
    market: str,
    value: dict[str, Any],
    *,
    root: Path,
    revision: str,
    lock_hash: str,
    report: VerificationReport,
) -> None:
    snapshot = _verify_snapshot(market, value.get("data_snapshot"), root, report)
    snapshot_id = snapshot.get("snapshot_id", "") if snapshot else ""
    model = _verify_model(
        market,
        value.get("model_artifact"),
        root=root,
        snapshot_id=snapshot_id,
        revision=revision,
        lock_hash=lock_hash,
        report=report,
    )
    artifact_id = model.get("id", "") if model else ""
    report.verified_ids.setdefault(market, {})
    if snapshot_id:
        report.verified_ids[market]["data_snapshot"] = snapshot_id
    if artifact_id:
        report.verified_ids[market]["model_artifact"] = artifact_id

    evidence = value.get("evidence")
    if not isinstance(evidence, dict):
        report.add("evidence_missing", False, market, "backtest and signal evidence are required")
        report.add(
            "required_metrics_missing",
            False,
            market,
            "missing=" + ",".join(REQUIRED_RELEASE_METRICS),
        )
        return
    combined_metrics: dict[str, float] = {}
    for kind in ("backtest", "signal"):
        payload = _verify_evidence(
            market,
            kind,
            evidence.get(kind),
            root=root,
            artifact_id=artifact_id,
            snapshot_id=snapshot_id,
            report=report,
        )
        if payload:
            evidence_id = payload.get("id")
            if isinstance(evidence_id, str):
                report.verified_ids[market][f"{kind}_evidence"] = evidence_id
            metrics = payload.get("metrics")
            if isinstance(metrics, dict):
                combined_metrics.update(
                    {
                        key: float(metric)
                        for key, metric in metrics.items()
                        if _finite_number(metric)
                    }
                )

    missing = [name for name in REQUIRED_RELEASE_METRICS if name not in combined_metrics]
    report.add(
        "required_metrics_missing",
        not missing,
        market,
        "missing=" + ",".join(missing) if missing else "all required release metrics present",
    )
    if not missing:
        _verify_metric_thresholds(market, combined_metrics, evidence, root, report)


def _verify_snapshot(
    market: str, value: Any, root: Path, report: VerificationReport
) -> dict[str, Any] | None:
    payload, subject = _load_reference(value, "manifest", root, report, "snapshot")
    if payload is None:
        return None
    expected_id = value.get("id") if isinstance(value, dict) else None
    snapshot_id = payload.get("snapshot_id")
    report.add(
        "snapshot_identity",
        isinstance(expected_id, str) and expected_id == snapshot_id,
        subject,
        f"reference={expected_id!r}; manifest={snapshot_id!r}",
    )
    required = (
        "content_hash",
        "source_adapter",
        "schema_version",
        "universe",
        "date_range",
        "frequency",
        "quality_verdict",
        "storage_uri",
        "file_checksums",
    )
    missing = [name for name in required if _empty(payload.get(name))]
    report.add(
        "snapshot_manifest_complete",
        not missing,
        subject,
        "missing=" + ",".join(missing) if missing else "required snapshot fields present",
    )
    report.add(
        "snapshot_quality",
        payload.get("quality_verdict") == "pass",
        subject,
        "quality_verdict must be pass",
    )
    checksums = payload.get("file_checksums")
    if not isinstance(checksums, dict) or not checksums:
        report.add("snapshot_files_missing", False, subject, "file_checksums must be non-empty")
        return payload
    content_hash = compute_aggregate_hash(checksums)
    files_ok = True
    manifest_path = root / subject
    for relative in sorted(checksums):
        expected = checksums[relative]
        file_path = _child_path(manifest_path.parent, relative)
        if file_path is None or not file_path.is_file() or not _valid_hash(expected):
            files_ok = False
            continue
        if _sha256(file_path) != expected:
            files_ok = False
    identity_ok = (
        payload.get("content_hash") == content_hash
        and SnapshotManifest.from_dict(payload).computed_snapshot_id() == snapshot_id
    )
    report.add(
        "snapshot_file_checksums",
        files_ok,
        subject,
        f"verified_files={len(checksums)}",
    )
    report.add(
        "snapshot_content_identity",
        identity_ok,
        subject,
        f"computed_content_hash={content_hash}",
    )
    return payload


def _verify_model(
    market: str,
    value: Any,
    *,
    root: Path,
    snapshot_id: str,
    revision: str,
    lock_hash: str,
    report: VerificationReport,
) -> dict[str, Any] | None:
    payload, subject = _load_reference(value, "manifest", root, report, "model")
    if payload is None:
        return None
    expected_id = value.get("id") if isinstance(value, dict) else None
    artifact_id = payload.get("id")
    report.add(
        "model_identity",
        isinstance(expected_id, str) and expected_id == artifact_id,
        subject,
        f"reference={expected_id!r}; manifest={artifact_id!r}",
    )
    missing = [name for name in _MODEL_REQUIRED_FIELDS if _empty(payload.get(name))]
    report.add(
        "model_manifest_complete",
        not missing,
        subject,
        "missing=" + ",".join(missing) if missing else "required model fields present",
    )
    bindings_ok = (
        bool(snapshot_id)
        and payload.get("snapshot_id") == snapshot_id
        and bool(revision)
        and payload.get("code_revision") == revision
        and bool(lock_hash)
        and payload.get("uv_lock_hash") == lock_hash
        and payload.get("config", {}).get("market") == market
    )
    report.add(
        "model_provenance_bindings",
        bindings_ok,
        subject,
        "model must match market, snapshot, code revision, and dependency lock",
    )
    checksums = payload.get("checksums")
    required_paths = {
        payload.get("model_binary_path"),
        payload.get("predictions_path"),
        payload.get("labels_path"),
        payload.get("diagnostics_path"),
    }
    files_ok = isinstance(checksums, dict) and bool(checksums) and None not in required_paths
    files_ok = files_ok and required_paths.issubset(set(checksums))  # type: ignore[arg-type]
    manifest_path = root / subject
    if isinstance(checksums, dict):
        for relative, expected in sorted(checksums.items()):
            file_path = _child_path(manifest_path.parent, relative)
            if (
                file_path is None
                or not file_path.is_file()
                or not _valid_hash(expected)
                or _sha256(file_path) != expected
            ):
                files_ok = False
                report.add(
                    "model_file_checksum_mismatch",
                    False,
                    f"{subject}:{relative}",
                    "referenced model file is missing or its checksum differs",
                )
    report.add(
        "model_file_checksums",
        files_ok,
        subject,
        f"verified_files={len(checksums) if isinstance(checksums, dict) else 0}",
    )
    return payload


def _verify_evidence(
    market: str,
    kind: str,
    value: Any,
    *,
    root: Path,
    artifact_id: str,
    snapshot_id: str,
    report: VerificationReport,
) -> dict[str, Any] | None:
    payload, subject = _load_reference(value, "path", root, report, f"{kind}_evidence")
    if payload is None:
        return None
    expected_id = value.get("id") if isinstance(value, dict) else None
    identity_ok = (
        isinstance(expected_id, str)
        and payload.get("id") == expected_id
        and payload.get("evidence_type") == kind
        and payload.get("model_artifact_id") == artifact_id
        and payload.get("snapshot_id") == snapshot_id
        and payload.get("metric_schema_version") == "v1"
        and payload.get("status") == "pass"
    )
    report.add(
        f"{kind}_evidence_identity",
        identity_ok,
        subject,
        f"evidence must bind to {market}/{artifact_id}/{snapshot_id} with pass status",
    )
    metrics = payload.get("metrics")
    metrics_ok = (
        isinstance(metrics, dict)
        and bool(metrics)
        and all(_finite_number(metric) for metric in metrics.values())
    )
    report.add(
        f"{kind}_evidence_metrics",
        metrics_ok,
        subject,
        "metrics must be a non-empty object of finite numbers",
    )
    return payload


def _verify_metric_thresholds(
    market: str,
    metrics: dict[str, float],
    evidence: dict[str, Any],
    root: Path,
    report: VerificationReport,
) -> None:
    signal_ref = evidence.get("signal")
    signal_path = (
        _project_path(signal_ref.get("path"), root) if isinstance(signal_ref, dict) else None
    )
    subject = _display_path(signal_path, root) if signal_path else market
    report.add(
        "icir_threshold",
        metrics["icir"] >= _POLICY["min_icir"],
        subject,
        f"icir={metrics['icir']}; minimum={_POLICY['min_icir']}",
    )
    report.add(
        "consistency_threshold",
        metrics["consistency"] >= _POLICY["min_consistency"],
        subject,
        f"consistency={metrics['consistency']}; minimum={_POLICY['min_consistency']}",
    )
    report.add(
        "sample_threshold",
        metrics["sample_count"] >= _POLICY["min_samples"],
        subject,
        f"sample_count={metrics['sample_count']}; minimum={_POLICY['min_samples']}",
    )
    report.add(
        "drawdown_threshold",
        metrics["max_drawdown"] >= _POLICY["max_drawdown"],
        subject,
        f"max_drawdown={metrics['max_drawdown']}; floor={_POLICY['max_drawdown']}",
    )


def _verify_frontend(value: Any, root: Path, revision: Any, report: VerificationReport) -> None:
    if value is None:
        report.add(
            "frontend_build_missing",
            False,
            "frontend_build",
            "frontend-build evidence is required for this release track",
        )
        return
    payload, subject = _load_reference(value, "path", root, report, "frontend_build")
    if payload is None:
        return
    expected_id = value.get("id") if isinstance(value, dict) else None
    passed = (
        isinstance(expected_id, str)
        and payload.get("id") == expected_id
        and payload.get("status") == "pass"
        and payload.get("code_revision") == revision
    )
    report.add(
        "frontend_build_identity",
        passed,
        subject,
        "frontend build must match the candidate id, revision, and pass status",
    )


def _load_reference(
    value: Any,
    path_key: str,
    root: Path,
    report: VerificationReport,
    kind: str,
) -> tuple[dict[str, Any] | None, str]:
    if not isinstance(value, dict):
        report.add(f"{kind}_reference_missing", False, kind, "reference object is required")
        return None, kind
    path = _project_path(value.get(path_key), root)
    subject = _display_path(path, root) if path else str(value.get(path_key))
    if path is None or not path.is_file():
        report.add(f"{kind}_file_missing", False, subject, "referenced file is missing or unsafe")
        return None, subject
    expected = value.get("sha256")
    actual = _sha256(path)
    if not _valid_hash(expected) or expected != actual:
        report.add(
            f"{kind}_reference_checksum_mismatch",
            False,
            subject,
            f"expected={expected!r}; actual={actual}",
        )
        return None, subject
    report.add(f"{kind}_reference_checksum", True, subject, f"sha256={actual}")
    return _read_json_object(path, report, f"{kind}_json_invalid"), subject


def _read_json_object(path: Path, report: VerificationReport, code: str) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        report.add(code, False, str(path), f"{type(exc).__name__}: {exc}")
        return None
    if not isinstance(value, dict):
        report.add(code, False, str(path), "JSON root must be an object")
        return None
    return value


def _project_path(value: Any, root: Path) -> Path | None:
    if not isinstance(value, str) or not value.strip():
        return None
    raw = Path(value)
    path = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    return path if _is_within(path, root) else None


def _child_path(parent: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        return None
    path = (parent / value).resolve()
    return path if _is_within(path, parent.resolve()) else None


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _display_path(path: Path | None, root: Path) -> str:
    if path is None:
        return ""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _git_revision(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""
