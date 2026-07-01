from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from src.data.snapshot import compute_aggregate_hash
from src.release.candidate import (
    REQUIRED_RELEASE_METRICS,
    resolve_candidate_reference,
    verify_release_candidate,
)
from src.release.quality import build_quality_commands, classify_skips

REVISION = "a" * 40


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _make_snapshot(root: Path, market: str) -> tuple[str, Path]:
    from src.data.snapshot_manifest import SnapshotManifest

    files = {"calendar.txt": f"{market}:2026-06-20\n".encode()}
    checksums = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
    content_hash = compute_aggregate_hash(checksums)
    manifest_dict: dict[str, Any] = {
        "content_hash": content_hash,
        "file_checksums": checksums,
        "source_adapter": "fixture",
        "schema_version": "1",
        "universe": f"{market}-fixture",
        "date_range": {"start": "2026-01-01", "end": "2026-06-20"},
        "frequency": "day",
        "quality_verdict": "pass",
    }
    snapshot_id = SnapshotManifest.from_dict(manifest_dict).computed_snapshot_id()
    manifest_dict["snapshot_id"] = snapshot_id
    snapshot_dir = root / "data" / "snapshots" / market / snapshot_id
    for name, content in files.items():
        (snapshot_dir / name).parent.mkdir(parents=True, exist_ok=True)
        (snapshot_dir / name).write_bytes(content)
    manifest_path = snapshot_dir / "manifest.json"
    manifest_dict.update(
        {
            "storage_uri": _relative(root, snapshot_dir),
            "created_at": "2026-06-20T00:00:00Z",
        }
    )
    _write_json(manifest_path, manifest_dict)
    return snapshot_id, manifest_path


def _make_model(root: Path, market: str, snapshot_id: str, lock_hash: str) -> tuple[str, Path]:
    artifact_id = f"{market}-model-v1"
    artifact_dir = root / "artifacts" / "model_artifacts" / artifact_id
    artifact_dir.mkdir(parents=True)
    files = {
        "model.pkl": b"model-bytes",
        "predictions.csv": b"date,instrument,score\n2026-06-20,TEST,0.2\n",
        "labels.csv": b"date,instrument,label\n2026-06-20,TEST,0.1\n",
        "diagnostics.json": b'{"status":"pass"}\n',
    }
    for name, content in files.items():
        (artifact_dir / name).write_bytes(content)
    manifest_path = artifact_dir / "manifest.json"
    _write_json(
        manifest_path,
        {
            "id": artifact_id,
            "model_binary_path": "model.pkl",
            "config": {"market": market, "model": "LGBModel"},
            "features": ["feature_1"],
            "label_schema": {"name": "return_5d", "horizon": 5},
            "snapshot_id": snapshot_id,
            "train_window": ["2024-01-01", "2025-01-01"],
            "valid_window": ["2025-01-02", "2025-06-30"],
            "test_window": ["2025-07-01", "2026-06-20"],
            "benchmark": "fixture-benchmark",
            "costs": {"open_cost": 0.0005, "close_cost": 0.0015},
            "code_revision": REVISION,
            "uv_lock_hash": lock_hash,
            "python_version": "3.12.0",
            "seeds": {"numpy": 42},
            "predictions_path": "predictions.csv",
            "labels_path": "labels.csv",
            "diagnostics_path": "diagnostics.json",
            "checksums": {name: _sha256(artifact_dir / name) for name in files},
        },
    )
    return artifact_id, manifest_path


def _metrics() -> dict[str, float]:
    return {
        "ic": 0.08,
        "rank_ic": 0.07,
        "icir": 0.9,
        "consistency": 0.7,
        "sample_count": 20,
        "coverage": 0.98,
        "annualized_return": 0.18,
        "total_return": 0.16,
        "benchmark_return": 0.08,
        "excess_return": 0.1,
        "volatility": 0.12,
        "sharpe": 1.5,
        "information_ratio": 1.1,
        "max_drawdown": -0.08,
        "turnover": 0.25,
        "costs": 0.01,
        "net_return": 0.15,
    }


def _make_evidence(
    root: Path,
    market: str,
    kind: str,
    artifact_id: str,
    snapshot_id: str,
    metrics: dict[str, float],
) -> tuple[str, Path]:
    evidence_id = f"{market}-{kind}-v1"
    path = root / "artifacts" / "evidence" / f"{evidence_id}.json"
    _write_json(
        path,
        {
            "id": evidence_id,
            "evidence_type": kind,
            "status": "pass",
            "model_artifact_id": artifact_id,
            "snapshot_id": snapshot_id,
            "metric_schema_version": "v1",
            "metrics": metrics,
        },
    )
    return evidence_id, path


def _make_candidate(root: Path) -> tuple[Path, dict[str, Any]]:
    lock_path = root / "uv.lock"
    lock_path.write_text("fixture-lock\n", encoding="utf-8")
    lock_hash = _sha256(lock_path)
    markets: dict[str, Any] = {}
    for market in ("cn", "us"):
        snapshot_id, snapshot_manifest = _make_snapshot(root, market)
        artifact_id, artifact_manifest = _make_model(root, market, snapshot_id, lock_hash)
        metrics = _metrics()
        backtest_metrics = {key: metrics[key] for key in REQUIRED_RELEASE_METRICS[6:]}
        signal_metrics = {key: metrics[key] for key in REQUIRED_RELEASE_METRICS[:6]}
        backtest_id, backtest_path = _make_evidence(
            root, market, "backtest", artifact_id, snapshot_id, backtest_metrics
        )
        signal_id, signal_path = _make_evidence(
            root, market, "signal", artifact_id, snapshot_id, signal_metrics
        )
        markets[market] = {
            "data_snapshot": {
                "id": snapshot_id,
                "manifest": _relative(root, snapshot_manifest),
                "sha256": _sha256(snapshot_manifest),
            },
            "model_artifact": {
                "id": artifact_id,
                "manifest": _relative(root, artifact_manifest),
                "sha256": _sha256(artifact_manifest),
            },
            "evidence": {
                "backtest": {
                    "id": backtest_id,
                    "path": _relative(root, backtest_path),
                    "sha256": _sha256(backtest_path),
                },
                "signal": {
                    "id": signal_id,
                    "path": _relative(root, signal_path),
                    "sha256": _sha256(signal_path),
                },
            },
        }

    frontend_path = root / "artifacts" / "evidence" / "frontend-build-v1.json"
    _write_json(
        frontend_path,
        {"id": "frontend-build-v1", "status": "pass", "code_revision": REVISION},
    )
    candidate = {
        "schema_version": "1",
        "release_candidate_id": "rc_fixture",
        "code_identity": {
            "revision": REVISION,
            "lockfile": {"path": "uv.lock", "sha256": lock_hash},
        },
        "metric_schema": {
            "version": "v1",
            "required_fields": list(REQUIRED_RELEASE_METRICS),
        },
        "gate_policy": {
            "id": "t48-release-v1",
            "min_icir": 0.3,
            "min_consistency": 0.55,
            "min_samples": 10,
            "max_drawdown": -0.15,
        },
        "markets": markets,
        "frontend_build": {
            "id": "frontend-build-v1",
            "path": _relative(root, frontend_path),
            "sha256": _sha256(frontend_path),
        },
    }
    candidate_path = root / "artifacts" / "release_candidate" / "fixture" / "manifest.json"
    _write_json(candidate_path, candidate)
    return candidate_path, candidate


def test_verifies_only_the_exact_release_candidate(tmp_path: Path) -> None:
    candidate_path, _ = _make_candidate(tmp_path)

    report = verify_release_candidate(candidate_path, project_root=tmp_path, revision=REVISION)

    assert report.ok
    assert report.release_candidate_id == "rc_fixture"
    assert report.verified_ids["cn"]["model_artifact"] == "cn-model-v1"
    assert report.verified_ids["us"]["model_artifact"] == "us-model-v1"


def test_rejects_checksum_mismatch(tmp_path: Path) -> None:
    candidate_path, candidate = _make_candidate(tmp_path)
    manifest_path = tmp_path / candidate["markets"]["cn"]["model_artifact"]["manifest"]
    model_path = manifest_path.parent / "model.pkl"
    model_path.write_bytes(b"tampered")

    report = verify_release_candidate(candidate_path, project_root=tmp_path, revision=REVISION)

    assert not report.ok
    assert any(check.code == "model_file_checksum_mismatch" for check in report.checks)


def test_rejects_missing_required_metrics(tmp_path: Path) -> None:
    candidate_path, candidate = _make_candidate(tmp_path)
    ref = candidate["markets"]["us"]["evidence"]["backtest"]
    evidence_path = tmp_path / ref["path"]
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    evidence["metrics"].pop("annualized_return")
    _write_json(evidence_path, evidence)
    ref["sha256"] = _sha256(evidence_path)
    _write_json(candidate_path, candidate)

    report = verify_release_candidate(candidate_path, project_root=tmp_path, revision=REVISION)

    assert not report.ok
    missing = next(
        check
        for check in report.checks
        if check.code == "required_metrics_missing" and check.subject == "us"
    )
    assert "annualized_return" in missing.detail


def test_missing_evidence_reports_all_required_metrics(tmp_path: Path) -> None:
    candidate_path, candidate = _make_candidate(tmp_path)
    candidate["markets"]["cn"].pop("evidence")
    _write_json(candidate_path, candidate)

    report = verify_release_candidate(candidate_path, project_root=tmp_path, revision=REVISION)

    missing = next(
        check
        for check in report.checks
        if check.code == "required_metrics_missing" and check.subject == "cn"
    )
    assert not missing.passed
    assert "annualized_return" in missing.detail
    assert "max_drawdown" in missing.detail


def test_does_not_fall_back_to_best_historical_evidence(tmp_path: Path) -> None:
    candidate_path, candidate = _make_candidate(tmp_path)
    ref = candidate["markets"]["cn"]["evidence"]["signal"]
    selected_path = tmp_path / ref["path"]
    selected = json.loads(selected_path.read_text(encoding="utf-8"))
    selected["metrics"]["icir"] = -0.2
    _write_json(selected_path, selected)
    ref["sha256"] = _sha256(selected_path)
    _write_json(candidate_path, candidate)

    historical_path = tmp_path / "artifacts" / "walk_forward" / "cn_best_ever.json"
    _write_json(historical_path, {"ic_ir": 999.0, "consistency_score": 1.0, "n_success": 999})

    report = verify_release_candidate(candidate_path, project_root=tmp_path, revision=REVISION)

    assert not report.ok
    threshold = next(check for check in report.checks if check.code == "icir_threshold")
    assert selected_path.relative_to(tmp_path).as_posix() in threshold.subject
    assert "cn_best_ever.json" not in json.dumps(report.to_dict())


def test_quality_command_set_covers_the_release_pipeline(tmp_path: Path) -> None:
    commands = build_quality_commands(tmp_path, tmp_path / "evidence")

    assert [command.name for command in commands] == [
        "ruff",
        "mypy_ratchet",
        "backend_tests",
        "frontend_install",
        "frontend_typecheck",
        "frontend_lint",
        "frontend_vitest",
        "frontend_build",
        "playwright",
        "package_build",
    ]
    rendered = [" ".join(command.argv) for command in commands]
    assert "ruff check ." in rendered[0]
    assert "src/release" in rendered[1]
    assert "pytest tests" in rendered[2]
    assert "npm run lint" in rendered[5]
    assert "npm run test" in rendered[6]
    assert "playwright test" in rendered[8]


def test_unapproved_backend_skip_fails_accounting() -> None:
    accounting = classify_skips(
        [
            {"nodeid": "tests/test_release.py::test_live_path", "reason": "service missing"},
            {"nodeid": "tests/test_optional.py::test_adapter", "reason": "optional dependency"},
        ],
        approved={"tests/test_optional.py::test_adapter"},
    )

    assert not accounting["ok"]
    assert accounting["approved_count"] == 1
    assert accounting["unapproved"] == [
        {"nodeid": "tests/test_release.py::test_live_path", "reason": "service missing"}
    ]


def test_snapshot_tampered_snapshot_id_fails_content_identity(tmp_path: Path) -> None:
    """A snapshot manifest with wrong snapshot_id fails snapshot_content_identity."""
    candidate_path, candidate = _make_candidate(tmp_path)
    ref = candidate["markets"]["us"]["data_snapshot"]
    manifest_path = tmp_path / ref["manifest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["snapshot_id"] = "0" * 64  # tamper identity so computed_snapshot_id() won't match
    _write_json(manifest_path, manifest)
    ref["sha256"] = _sha256(manifest_path)
    _write_json(candidate_path, candidate)

    report = verify_release_candidate(candidate_path, project_root=tmp_path, revision=REVISION)
    assert not report.ok
    us_subject = candidate["markets"]["us"]["data_snapshot"]["manifest"]
    ic = next(
        (c for c in report.checks if c.code == "snapshot_content_identity" and c.subject == us_subject),
        None,
    )
    assert ic is not None, "snapshot_content_identity check must exist for us"
    assert not ic.passed, "content identity must fail with wrong snapshot_id"


def test_rc_20260620_fails_verification(tmp_path: Path) -> None:
    """The original rc_20260620 must fail because it has no formal snapshots and lacks required metrics."""
    # Build a manifest that mirrors the known-deficient rc_20260620 state:
    # no data snapshots, no model artifacts, no evidence for either market.
    candidate = {
        "schema_version": "1",
        "release_candidate_id": "rc_20260620",
        "code_identity": {
            "revision": "",
            "lockfile": {"path": "uv.lock", "sha256": ""},
        },
        "metric_schema": {
            "version": "v1",
            "required_fields": list(REQUIRED_RELEASE_METRICS),
        },
        "gate_policy": {
            "id": "t48-release-v1",
            "min_icir": 0.3,
            "min_consistency": 0.55,
            "min_samples": 10,
            "max_drawdown": -0.15,
        },
        "markets": {
            "cn": {
                "data_snapshot": None,
                "model_artifact": None,
                "evidence": None,
            },
            "us": {
                "data_snapshot": None,
                "model_artifact": None,
                "evidence": None,
            },
        },
        "frontend_build": None,
        "status": "rejected",
        "rejection_reason": "T48 audit: no formal DataSnapshot, missing required metrics",
    }
    candidate_path = (
        tmp_path / "artifacts" / "release_candidate" / "20260620" / "release_manifest.json"
    )
    _write_json(candidate_path, candidate)

    report = verify_release_candidate(candidate_path, project_root=tmp_path, revision=REVISION)

    assert not report.ok
    codes = {check.code for check in report.checks if not check.passed}
    # Must fail on snapshot-related checks (no formal DataSnapshot)
    snapshot_failures = {c for c in codes if "snapshot" in c or "reference_missing" in c}
    assert snapshot_failures, f"Expected snapshot failures, got: {codes}"
    # Must fail on missing required metrics (no evidence)
    metrics_failures = {c for c in codes if "metrics" in c or "evidence" in c}
    assert metrics_failures, f"Expected metrics/evidence failures, got: {codes}"
    # Must also fail on code revision (empty string)
    assert "code_revision" in codes


# ---------------------------------------------------------------------------
# US-only release candidate tests
# ---------------------------------------------------------------------------


def test_us_only_candidate_passes_verification(tmp_path: Path) -> None:
    """A valid US-only release candidate (no CN market) passes verification
    and includes a frontend build reference."""
    candidate_path, _ = _make_us_only_candidate(tmp_path)

    report = verify_release_candidate(candidate_path, project_root=tmp_path, revision=REVISION)

    assert report.ok
    assert report.release_candidate_id == "rc_fixture_us"
    assert "us" in report.verified_ids
    assert "cn" not in report.verified_ids


def test_us_only_candidate_rejects_checksum_mismatch(tmp_path: Path) -> None:
    """A US-only candidate fails when a model file checksum is tampered."""
    candidate_path, candidate = _make_us_only_candidate(tmp_path)
    manifest_path = tmp_path / candidate["markets"]["us"]["model_artifact"]["manifest"]
    model_path = manifest_path.parent / "model.pkl"
    model_path.write_bytes(b"tampered")

    report = verify_release_candidate(candidate_path, project_root=tmp_path, revision=REVISION)

    assert not report.ok
    assert any(check.code == "model_file_checksum_mismatch" for check in report.checks)


def test_us_only_candidate_missing_evidence_fails(tmp_path: Path) -> None:
    """A US-only candidate with missing evidence still fails closed."""
    candidate_path, candidate = _make_us_only_candidate(tmp_path)
    candidate["markets"]["us"].pop("evidence")
    _write_json(candidate_path, candidate)

    report = verify_release_candidate(candidate_path, project_root=tmp_path, revision=REVISION)

    assert not report.ok
    missing = next(
        check
        for check in report.checks
        if check.code == "evidence_missing" and check.subject == "us"
    )
    assert not missing.passed


# ---------------------------------------------------------------------------
# Identifier resolution tests
# ---------------------------------------------------------------------------


def test_v_style_identifier_resolves_to_correct_path(tmp_path: Path) -> None:
    """The identifier v0.1.0-rc1 resolves to the expected manifest path."""
    path = resolve_candidate_reference("v0.1.0-rc1", tmp_path)
    expected = tmp_path / "artifacts" / "release_candidate" / "v0.1.0-rc1" / "release_manifest.json"
    assert path == expected


def test_rc_v_style_identifier_resolves_correctly(tmp_path: Path) -> None:
    """The identifier rc_v0.1.0-rc1 resolves to the expected manifest path
    (same directory as v0.1.0-rc1 after stripping rc_ prefix)."""
    path = resolve_candidate_reference("rc_v0.1.0-rc1", tmp_path)
    expected = tmp_path / "artifacts" / "release_candidate" / "v0.1.0-rc1" / "release_manifest.json"
    assert path == expected


def test_rc_style_identifier_still_resolves(tmp_path: Path) -> None:
    """The traditional rc_20260620 identifier still resolves correctly."""
    path = resolve_candidate_reference("rc_20260620", tmp_path)
    expected = tmp_path / "artifacts" / "release_candidate" / "20260620" / "release_manifest.json"
    assert path == expected


# ---------------------------------------------------------------------------
# Helpers for US-only candidates
# ---------------------------------------------------------------------------


def _make_us_only_candidate(root: Path) -> tuple[Path, dict[str, Any]]:
    """Build a minimal passing US-only release candidate (no CN market)."""
    lock_path = root / "uv.lock"
    lock_path.write_text("fixture-lock-us\n", encoding="utf-8")
    lock_hash = _sha256(lock_path)

    market = "us"
    snapshot_id, snapshot_manifest = _make_snapshot(root, market)
    artifact_id, artifact_manifest = _make_model(root, market, snapshot_id, lock_hash)
    metrics = _metrics()
    backtest_metrics = {key: metrics[key] for key in REQUIRED_RELEASE_METRICS[6:]}
    signal_metrics = {key: metrics[key] for key in REQUIRED_RELEASE_METRICS[:6]}
    backtest_id, backtest_path = _make_evidence(
        root, market, "backtest", artifact_id, snapshot_id, backtest_metrics
    )
    signal_id, signal_path = _make_evidence(
        root, market, "signal", artifact_id, snapshot_id, signal_metrics
    )

    markets: dict[str, Any] = {
        market: {
            "data_snapshot": {
                "id": snapshot_id,
                "manifest": _relative(root, snapshot_manifest),
                "sha256": _sha256(snapshot_manifest),
            },
            "model_artifact": {
                "id": artifact_id,
                "manifest": _relative(root, artifact_manifest),
                "sha256": _sha256(artifact_manifest),
            },
            "evidence": {
                "backtest": {
                    "id": backtest_id,
                    "path": _relative(root, backtest_path),
                    "sha256": _sha256(backtest_path),
                },
                "signal": {
                    "id": signal_id,
                    "path": _relative(root, signal_path),
                    "sha256": _sha256(signal_path),
                },
            },
        }
    }

    # Frontend build evidence (required by gate)
    frontend_path = root / "artifacts" / "evidence" / "frontend-build-us.json"
    _write_json(
        frontend_path,
        {"id": "frontend-build-us", "status": "pass", "code_revision": REVISION},
    )

    candidate: dict[str, Any] = {
        "schema_version": "1",
        "release_candidate_id": "rc_fixture_us",
        "code_identity": {
            "revision": REVISION,
            "lockfile": {"path": "uv.lock", "sha256": lock_hash},
        },
        "metric_schema": {
            "version": "v1",
            "required_fields": list(REQUIRED_RELEASE_METRICS),
        },
        "gate_policy": {
            "id": "t48-release-v1",
            "min_icir": 0.3,
            "min_consistency": 0.55,
            "min_samples": 10,
            "max_drawdown": -0.15,
        },
        "markets": markets,
        "frontend_build": {
            "id": "frontend-build-us",
            "path": _relative(root, frontend_path),
            "sha256": _sha256(frontend_path),
        },
    }
    candidate_path = root / "artifacts" / "release_candidate" / "fixture_us" / "manifest.json"
    _write_json(candidate_path, candidate)
    return candidate_path, candidate


def test_snapshot_missing_date_range_fails_manifest_complete(tmp_path: Path) -> None:
    """A snapshot manifest with empty date_range fails snapshot_manifest_complete."""
    lock_path = tmp_path / "uv.lock"
    lock_path.write_text("fixture-lock\n", encoding="utf-8")
    lock_hash = _sha256(lock_path)

    files = {"data.bin": b"test-data"}
    checksums = {n: hashlib.sha256(c).hexdigest() for n, c in files.items()}
    content_hash = compute_aggregate_hash(checksums)
    snapshot_id = content_hash[:16]
    snap_dir = tmp_path / "data" / "snapshots" / "us" / snapshot_id
    snap_dir.mkdir(parents=True, exist_ok=True)
    for n, c in files.items():
        (snap_dir / n).write_bytes(c)
    manifest_path = snap_dir / "manifest.json"
    _write_json(
        manifest_path,
        {
            "snapshot_id": snapshot_id,
            "content_hash": content_hash,
            "file_checksums": checksums,
            "source_adapter": "test",
            "schema_version": "1",
            "universe": "us-test",
            "date_range": {},  # empty — gate treats as missing
            "frequency": "day",
            "quality_verdict": "pass",
            "storage_uri": str(snap_dir),
            "created_at": "2026-06-20T00:00:00Z",
        },
    )
    iid = "us-model-v1"
    adir = tmp_path / "artifacts" / "model_artifacts" / iid
    adir.mkdir(parents=True)
    for f in ("model.pkl", "predictions.csv", "labels.csv", "diagnostics.json"):
        (adir / f).write_bytes(b"x")
    _write_json(
        adir / "manifest.json",
        {
            "id": iid,
            "model_binary_path": "model.pkl",
            "config": {"market": "us", "model": "LGB"},
            "features": [],
            "label_schema": {"name": "r", "horizon": 1},
            "snapshot_id": snapshot_id,
            "train_window": [], "valid_window": [], "test_window": [],
            "benchmark": "QQQ",
            "costs": {},
            "code_revision": REVISION,
            "uv_lock_hash": lock_hash,
            "python_version": "3.12",
            "seeds": {},
            "predictions_path": "predictions.csv",
            "labels_path": "labels.csv",
            "diagnostics_path": "diagnostics.json",
            "checksums": {f: _sha256(adir / f) for f in ("model.pkl", "predictions.csv", "labels.csv", "diagnostics.json")},
        },
    )
    fep = tmp_path / "artifacts" / "evidence" / "fe.json"
    _write_json(fep, {"id": "fe", "status": "pass", "code_revision": REVISION})
    candidate = {
        "schema_version": "1",
        "release_candidate_id": "rc_test",
        "code_identity": {"revision": REVISION, "lockfile": {"path": "uv.lock", "sha256": lock_hash}},
        "metric_schema": {"version": "v1", "required_fields": list(REQUIRED_RELEASE_METRICS)},
        "gate_policy": {"id": "t48-release-v1", "min_icir": 0.3, "min_consistency": 0.55, "min_samples": 10, "max_drawdown": -0.15},
        "markets": {
            "us": {
                "data_snapshot": {"id": snapshot_id, "manifest": _relative(tmp_path, manifest_path), "sha256": _sha256(manifest_path)},
                "model_artifact": {"id": iid, "manifest": _relative(tmp_path, adir / "manifest.json"), "sha256": _sha256(adir / "manifest.json")},
            },
        },
        "frontend_build": {"id": "fe", "path": _relative(tmp_path, fep), "sha256": _sha256(fep)},
    }
    cp = tmp_path / "artifacts" / "release_candidate" / "test" / "manifest.json"
    _write_json(cp, candidate)

    report = verify_release_candidate(cp, project_root=tmp_path, revision=REVISION)
    assert not report.ok
    sc = next((c for c in report.checks if c.code == "snapshot_manifest_complete"), None)
    assert sc is not None, "snapshot_manifest_complete check must exist"
    assert not sc.passed, "snapshot incomplete when date_range is empty"
    assert "date_range" in sc.detail


def test_snapshot_tampered_content_hash_fails_content_identity(tmp_path: Path) -> None:
    """A snapshot manifest with wrong content_hash fails snapshot_content_identity."""
    lock_path = tmp_path / "uv.lock"
    lock_path.write_text("fixture-lock\n", encoding="utf-8")
    lock_hash = _sha256(lock_path)

    files = {"data.bin": b"test-data"}
    checksums = {n: hashlib.sha256(c).hexdigest() for n, c in files.items()}
    wrong_ch = "0" * 64
    snapshot_id = wrong_ch[:16]
    snap_dir = tmp_path / "data" / "snapshots" / "us" / snapshot_id
    snap_dir.mkdir(parents=True, exist_ok=True)
    (snap_dir / "data.bin").write_bytes(b"test-data")
    manifest_path = snap_dir / "manifest.json"
    _write_json(
        manifest_path,
        {
            "snapshot_id": snapshot_id,
            "content_hash": wrong_ch,
            "file_checksums": checksums,
            "source_adapter": "test",
            "schema_version": "1",
            "universe": "us-test",
            "date_range": {"start": "2026-01-01", "end": "2026-06-20"},
            "frequency": "day",
            "quality_verdict": "pass",
            "storage_uri": str(snap_dir),
            "created_at": "2026-06-20T00:00:00Z",
        },
    )
    iid = "us-model-v1"
    adir = tmp_path / "artifacts" / "model_artifacts" / iid
    adir.mkdir(parents=True)
    for f in ("model.pkl", "predictions.csv", "labels.csv", "diagnostics.json"):
        (adir / f).write_bytes(b"x")
    _write_json(
        adir / "manifest.json",
        {
            "id": iid,
            "model_binary_path": "model.pkl",
            "config": {"market": "us", "model": "LGB"},
            "features": [],
            "label_schema": {"name": "r", "horizon": 1},
            "snapshot_id": snapshot_id,
            "train_window": [], "valid_window": [], "test_window": [],
            "benchmark": "QQQ",
            "costs": {},
            "code_revision": REVISION,
            "uv_lock_hash": lock_hash,
            "python_version": "3.12",
            "seeds": {},
            "predictions_path": "predictions.csv",
            "labels_path": "labels.csv",
            "diagnostics_path": "diagnostics.json",
            "checksums": {f: _sha256(adir / f) for f in ("model.pkl", "predictions.csv", "labels.csv", "diagnostics.json")},
        },
    )
    fep = tmp_path / "artifacts" / "evidence" / "fe.json"
    _write_json(fep, {"id": "fe", "status": "pass", "code_revision": REVISION})
    candidate = {
        "schema_version": "1",
        "release_candidate_id": "rc_test",
        "code_identity": {"revision": REVISION, "lockfile": {"path": "uv.lock", "sha256": lock_hash}},
        "metric_schema": {"version": "v1", "required_fields": list(REQUIRED_RELEASE_METRICS)},
        "gate_policy": {"id": "t48-release-v1", "min_icir": 0.3, "min_consistency": 0.55, "min_samples": 10, "max_drawdown": -0.15},
        "markets": {
            "us": {
                "data_snapshot": {"id": snapshot_id, "manifest": _relative(tmp_path, manifest_path), "sha256": _sha256(manifest_path)},
                "model_artifact": {"id": iid, "manifest": _relative(tmp_path, adir / "manifest.json"), "sha256": _sha256(adir / "manifest.json")},
            },
        },
        "frontend_build": {"id": "fe", "path": _relative(tmp_path, fep), "sha256": _sha256(fep)},
    }
    cp = tmp_path / "artifacts" / "release_candidate" / "test" / "manifest.json"
    _write_json(cp, candidate)

    real_ch = compute_aggregate_hash(checksums)
    report = verify_release_candidate(cp, project_root=tmp_path, revision=REVISION)
    assert not report.ok
    ic = next((c for c in report.checks if c.code == "snapshot_content_identity"), None)
    assert ic is not None, "snapshot_content_identity check must exist"
    assert not ic.passed, "content identity must fail with wrong content_hash"
    assert "computed_content_hash=" in ic.detail
    assert real_ch in ic.detail
