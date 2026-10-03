"""Activated CN_27 V1.3 current-target publisher: prospective source live."""

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


def _sealed_prospective_root(tmp_path: Path, *, cover_positions: bool = True) -> Path:
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
    portfolio["positions"] = [
        row for row in portfolio["positions"] if row["date"] <= FROZEN_EVIDENCE_CUTOFF
    ] + (extended if cover_positions else [])
    portfolio_path.write_text(json.dumps(portfolio, sort_keys=True), encoding="utf-8")

    manifest["evidence_cutoff"] = PROSPECTIVE_CUTOFF
    lineage_path = run_dir / "lineage.json"
    lineage = json.loads(lineage_path.read_text())
    lineage["source_evidence"].pop("operating_state", None)
    lineage_path.write_text(json.dumps(lineage), encoding="utf-8")
    for section in manifest["sections"]:
        if section.get("section_id") in ("portfolio", "lineage"):
            path = run_dir / section["path"]
            section["sha256"] = _sha256(path)
            section["byte_size"] = path.stat().st_size
    manifest["bundle_id"] = compute_bundle_id(manifest)
    manifest_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    record["evidence_cutoff"] = PROSPECTIVE_CUTOFF
    record["manifest_sha256"] = _sha256(manifest_path)
    record["bundle_id"] = manifest["bundle_id"]
    catalog_path.write_text(json.dumps(catalog, sort_keys=True), encoding="utf-8")
    return formal


def test_prospective_source_is_available_on_current_main() -> None:
    status = prospective_source_status(
        formal_root=REAL_FORMAL_ROOT, repository_root=ROOT
    )
    assert status["prospective_source_available"] is True
    if status["current_target_available"]:
        assert status["current_target_blocking_reason"] == ""
    else:
        assert "positions do not cover" in status["current_target_blocking_reason"]
    assert status["active_evidence_cutoff"] > FROZEN_EVIDENCE_CUTOFF
    assert status["adapter_id"] == ADAPTER_ID


def test_build_requires_positions_covering_signal_date_on_current_main(
    tmp_path: Path,
) -> None:
    # Prospective source is available (09-09 refresh), but the refreshed
    # positions still end at the frozen cutoff, so no signal date can be
    # scored yet. This pins the exact remaining data gap: the formal
    # refresh must extend cn27 positions past the frozen cutoff (or the
    # first monthly rebalance must publish them).
    formal = _sealed_prospective_root(tmp_path, cover_positions=False)
    cutoff = PROSPECTIVE_CUTOFF
    with pytest.raises(CN27CurrentTargetError) as excinfo:
        score_cn_27_current_target(
            formal_root=formal,
            ledger_dir=tmp_path / "ledger",
            signal_date=cutoff,
            market_cutoff=cutoff,
            repository_root=tmp_path,
        )
    assert excinfo.value.status == "data_blocked"
    assert "positions do not cover" in str(excinfo.value)


def test_sealed_prospective_run_publishes_exact_frozen_recipe_target(
    tmp_path: Path,
) -> None:
    formal = _sealed_prospective_root(tmp_path)
    status = prospective_source_status(
        formal_root=formal, repository_root=tmp_path
    )
    assert status["prospective_source_available"] is True
    assert status["current_target_available"] is True
    assert status["current_target_blocking_reason"] == ""

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


def test_runner_status_reports_available_source() -> None:
    code, output, _ = _run_command(
        "status", "--formal-root", "data/research/formal_model_runs"
    )
    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["prospective_source_available"] is True


def test_runner_build_reports_missing_positions_on_current_main() -> None:
    status = prospective_source_status(
        formal_root=REAL_FORMAL_ROOT, repository_root=ROOT
    )
    cutoff = str(status["active_evidence_cutoff"])
    code, output, stdout = _run_command(
        "build",
        "--formal-root",
        "data/research/formal_model_runs",
        "--signal-date",
        cutoff,
        "--market-cutoff",
        cutoff,
    )
    # A valid source with missing current positions is a retained data blocker,
    # not corrupt evidence. The CLI succeeds in recording it without weights.
    assert code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    if status["current_target_available"]:
        assert payload["target_weights"]
        assert payload["factor_freshness_ok"] is True
    else:
        assert payload["decision"] == "data_blocked"
        assert "target_weights" not in payload


def test_runner_due_respects_activated_thirty_session_cadence() -> None:
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
    if "anchor" in payload:
        assert payload["anchor"] == "2026-09-04"
    assert payload["cadence_sessions"] == 30


def _seal_operating_state(formal: Path, operating: dict) -> None:
    catalog = json.loads((formal / "catalog.json").read_text())
    record = next(row for row in catalog["records"] if row["model_version_id"] == MODEL_ID)
    manifest_path = formal / record["manifest_path"]
    manifest = json.loads(manifest_path.read_text())
    lineage_path = manifest_path.parent / "lineage.json"
    lineage = json.loads(lineage_path.read_text())
    lineage["source_evidence"]["operating_state"] = operating
    lineage_path.write_text(json.dumps(lineage), encoding="utf-8")
    for section in manifest["sections"]:
        if section["section_id"] == "lineage":
            section["sha256"] = _sha256(lineage_path)
            section["byte_size"] = lineage_path.stat().st_size
    manifest["bundle_id"] = compute_bundle_id(manifest)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    record["manifest_sha256"] = _sha256(manifest_path)
    record["bundle_id"] = manifest["bundle_id"]
    (formal / "catalog.json").write_text(json.dumps(catalog), encoding="utf-8")


def _operating_fixture() -> dict:
    from src.factors.ranker_snapshot import build_ranker_factor_snapshot
    import yaml

    contract = yaml.safe_load((ROOT / "configs/models/cn_27_v1_3.yaml").read_text())
    factors = build_ranker_factor_snapshot(
        model_family_id="cn_27_rotation", signal_date=PROSPECTIVE_CUTOFF,
        latest_data_date=PROSPECTIVE_CUTOFF, data_freshness_ok=True,
        factor_values={f"strategy.cn27.{name}": 0.1 for name in contract["factor_model"]["combination"]},
        library_path=ROOT / "configs/factor_libraries/strategy_inputs.yaml",
    )
    return {
        "as_of": PROSPECTIVE_CUTOFF, "last_rebalance_date": "2026-08-25",
        "target_weights": {"515180": 1.0}, "current_weights": {"515180": 1.0},
        "pending_execution": False, "recipe_id": "k2_projected_22_45_n8",
        "source_bar_sha256": "1" * 64, "contract_sha256": "2" * 64,
        "factor_evidence": factors, "research_only": True, "trade_ready": False,
    }


def test_manifest_bound_operating_target_seals_without_rebalancing_price_drift(tmp_path: Path) -> None:
    from src.artifacts.strategy_signal_ledger import seal_signal_decision

    formal = _sealed_prospective_root(tmp_path)
    _seal_operating_state(formal, _operating_fixture())
    signal = score_cn_27_current_target(
        formal_root=formal, ledger_dir=tmp_path / "ledger",
        signal_date=PROSPECTIVE_CUTOFF, market_cutoff=PROSPECTIVE_CUTOFF,
        repository_root=tmp_path,
    )
    assert signal["target_weights"] == {"515180": 1.0}
    assert signal["action"] == "HOLD"
    assert signal["estimated_transaction_cost"] == 0.0
    assert signal["factor_freshness_ok"] is True
    assert signal["diagnostics"]["last_rebalance_date"] == "2026-08-25"
    path = seal_signal_decision(
        ledger_root=tmp_path / "ledger", model_version_id=MODEL_ID,
        signal=signal, workflow_run_id="test", commit_sha="a" * 40,
        created_at_utc="2026-09-05T10:00:00Z",
    )
    assert path.is_file()
    repeated = score_cn_27_current_target(
        formal_root=formal, ledger_dir=tmp_path / "ledger",
        signal_date=PROSPECTIVE_CUTOFF, market_cutoff=PROSPECTIVE_CUTOFF,
        repository_root=tmp_path,
    )
    assert repeated == signal


@pytest.mark.parametrize("field,value", [
    ("as_of", "2026-09-04"), ("trade_ready", True),
    ("target_weights", {"515180": float("nan")}),
])
def test_operating_state_drift_fails_closed(tmp_path: Path, field: str, value: object) -> None:
    formal = _sealed_prospective_root(tmp_path)
    operating = _operating_fixture()
    operating[field] = value
    _seal_operating_state(formal, operating)
    with pytest.raises(CN27CurrentTargetError) as excinfo:
        prospective_source_status(formal_root=formal, repository_root=tmp_path)
    assert excinfo.value.status == "invalid_evidence"


def test_verified_observation_bootstraps_once_without_fetching_or_resetting_cadence(tmp_path: Path, monkeypatch) -> None:
    import argparse
    from types import SimpleNamespace
    from src.artifacts.strategy_signal_ledger import seal_signal_decision
    import scripts.run_cn_27_current_target as command

    formal = _sealed_prospective_root(tmp_path)
    _seal_operating_state(formal, _operating_fixture())
    ledger = tmp_path / "ledger"
    monkeypatch.setattr(command, "ROOT", tmp_path)
    monkeypatch.setattr(command, "_strategy", lambda: (
        SimpleNamespace(signal_ledger=str(ledger)), SimpleNamespace(status="available")
    ))
    monkeypatch.setattr(command, "_resolve_market_sessions", lambda **kwargs: pytest.fail("observation read fetched data"))
    args = argparse.Namespace(formal_root=formal, as_of="2026-09-08", output=tmp_path / "due.json")
    assert command._due(args) == 0
    assert json.loads(args.output.read_text())["due"] is True
    signal = score_cn_27_current_target(
        formal_root=formal, ledger_dir=ledger, signal_date=PROSPECTIVE_CUTOFF,
        market_cutoff=PROSPECTIVE_CUTOFF, repository_root=tmp_path,
    )
    seal_signal_decision(ledger_root=ledger, model_version_id=MODEL_ID, signal=signal,
        workflow_run_id="test", commit_sha="a" * 40, created_at_utc="2026-09-05T10:00:00Z")
    assert command._due(args) == 0
    assert json.loads(args.output.read_text())["due"] is False
