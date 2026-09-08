"""Dormant CN_27 V1.3 current-target publisher: blocked now, exact later."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from src.artifacts.model_run_bundle_v2 import compute_bundle_id
from src.research.cn_27_current_target import (
    ADAPTER_ID,
    CN27CurrentTargetError,
    FROZEN_EVIDENCE_CUTOFF,
    MODEL_ID,
    prospective_source_status,
    score_cn_27_current_target,
)

ROOT = Path(__file__).resolve().parents[1]
REAL_FORMAL_ROOT = ROOT / "data/research/formal_model_runs"
PROSPECTIVE_CUTOFF = "2026-09-05"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sealed_prospective_root(tmp_path: Path) -> Path:
    """Copy the real formal root and seal one synthetic refreshed CN_27 run."""

    formal = tmp_path / "formal"
    shutil.copytree(REAL_FORMAL_ROOT, formal)
    (tmp_path / "configs/models").mkdir(parents=True)
    shutil.copyfile(
        ROOT / "configs/models/cn_27_v1_3.yaml",
        tmp_path / "configs/models/cn_27_v1_3.yaml",
    )

    catalog_path = formal / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    record = next(
        row
        for row in catalog["records"]
        if row.get("model_version_id") == MODEL_ID
    )
    run_dir = (formal / record["manifest_path"]).parent
    manifest_path = formal / record["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    portfolio_path = run_dir / "portfolio.json"
    portfolio = json.loads(portfolio_path.read_text(encoding="utf-8"))
    seed = [row for row in portfolio["positions"] if row["date"] == FROZEN_EVIDENCE_CUTOFF]
    assert seed, "frozen positions are missing"
    extended = [
        {**row, "date": PROSPECTIVE_CUTOFF} for row in seed
    ]
    portfolio["positions"] = [*portfolio["positions"], *extended]
    portfolio_path.write_text(json.dumps(portfolio, sort_keys=True), encoding="utf-8")

    manifest["evidence_cutoff"] = PROSPECTIVE_CUTOFF
    for section in manifest["sections"]:
        if section.get("section_id") == "portfolio":
            section["sha256"] = _sha256(portfolio_path)
            section["byte_size"] = portfolio_path.stat().st_size
    manifest["bundle_id"] = compute_bundle_id(manifest)
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    record["evidence_cutoff"] = PROSPECTIVE_CUTOFF
    record["manifest_sha256"] = _sha256(manifest_path)
    record["bundle_id"] = manifest["bundle_id"]
    catalog_path.write_text(json.dumps(catalog, sort_keys=True), encoding="utf-8")
    return formal


def test_prospective_source_is_unavailable_on_current_main() -> None:
    status = prospective_source_status(
        formal_root=REAL_FORMAL_ROOT, repository_root=ROOT
    )
    assert status["prospective_source_available"] is False
    assert status["active_evidence_cutoff"] == FROZEN_EVIDENCE_CUTOFF
    assert status["adapter_id"] == ADAPTER_ID


def test_build_fails_closed_as_data_blocked_without_prospective_source(
    tmp_path: Path,
) -> None:
    with pytest.raises(CN27CurrentTargetError) as excinfo:
        score_cn_27_current_target(
            formal_root=REAL_FORMAL_ROOT,
            ledger_dir=tmp_path / "ledger",
            signal_date="2026-09-08",
            market_cutoff="2026-09-08",
            repository_root=ROOT,
        )
    assert excinfo.value.status == "data_blocked"
    assert FROZEN_EVIDENCE_CUTOFF in str(excinfo.value)


def test_sealed_prospective_run_publishes_exact_frozen_recipe_target(
    tmp_path: Path,
) -> None:
    formal = _sealed_prospective_root(tmp_path)
    status = prospective_source_status(
        formal_root=formal, repository_root=tmp_path
    )
    assert status["prospective_source_available"] is True

    first = score_cn_27_current_target(
        formal_root=formal,
        ledger_dir=tmp_path / "ledger",
        signal_date=PROSPECTIVE_CUTOFF,
        market_cutoff=PROSPECTIVE_CUTOFF,
        repository_root=tmp_path,
    )
    second = score_cn_27_current_target(
        formal_root=formal,
        ledger_dir=tmp_path / "ledger",
        signal_date=PROSPECTIVE_CUTOFF,
        market_cutoff=PROSPECTIVE_CUTOFF,
        repository_root=tmp_path,
    )
    assert first == second
    assert first["model_version_id"] == MODEL_ID
    assert first["signal_date"] == PROSPECTIVE_CUTOFF
    assert first["reason_code"] == "cn_27_v1_3_scheduled_monthly_target"
    assert abs(sum(first["target_weights"].values()) - 1.0) <= 1e-9
    assert first["signal_state"] == "no_change"
    assert first["action"] == "HOLD"
    assert first["research_only"] is True
    assert first["trade_ready"] is False
    assert first["diagnostics"]["prospective_evidence_cutoff"] == PROSPECTIVE_CUTOFF
    assert first["diagnostics"]["model_selection_reopened"] is False
    assert len(first["fingerprint"]) == 64


def test_signal_beyond_prospective_cutoff_is_data_blocked(tmp_path: Path) -> None:
    formal = _sealed_prospective_root(tmp_path)
    with pytest.raises(CN27CurrentTargetError) as excinfo:
        score_cn_27_current_target(
            formal_root=formal,
            ledger_dir=tmp_path / "ledger",
            signal_date="2026-09-08",
            market_cutoff="2026-09-08",
            repository_root=tmp_path,
        )
    assert excinfo.value.status == "data_blocked"


def test_stale_signal_before_prospective_cutoff_is_invalid(tmp_path: Path) -> None:
    formal = _sealed_prospective_root(tmp_path)
    with pytest.raises(CN27CurrentTargetError) as excinfo:
        score_cn_27_current_target(
            formal_root=formal,
            ledger_dir=tmp_path / "ledger",
            signal_date=FROZEN_EVIDENCE_CUTOFF,
            market_cutoff=FROZEN_EVIDENCE_CUTOFF,
            repository_root=tmp_path,
        )
    assert excinfo.value.status == "invalid_evidence"


def _run_command(*argv: str) -> tuple[int, Path, Path]:
    import subprocess
    import sys
    import tempfile

    output = Path(tempfile.mkdtemp()) / "out.json"
    completed = subprocess.run(
        [sys.executable, "scripts/run_cn_27_current_target.py", *argv, "--output", str(output)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, output, completed.stdout


def test_runner_status_reports_dormant_source() -> None:
    code, output, _ = _run_command(
        "status", "--formal-root", "data/research/formal_model_runs"
    )
    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["prospective_source_available"] is False


def test_runner_build_writes_data_blocked_receipt() -> None:
    code, output, _ = _run_command(
        "build",
        "--formal-root",
        "data/research/formal_model_runs",
        "--signal-date",
        "2026-09-08",
        "--market-cutoff",
        "2026-09-08",
    )
    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["decision"] == "data_blocked"
    assert "target_weights" not in payload


def test_runner_due_is_not_due_while_dormant() -> None:
    code, output, _ = _run_command(
        "due",
        "--formal-root",
        "data/research/formal_model_runs",
        "--evidence-path",
        "data/research/market_evidence/cn/symbols/000300.json",
        "--as-of",
        "2026-09-08",
    )
    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["due"] is False
    assert payload["status"] == "blocked"
