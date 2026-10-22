from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import doctor
from src.artifacts.formal_bundle_reader import FormalBundleReadError
from src.artifacts.system_health import SystemHealthError
from src.governance.active_strategy_catalog import load_active_strategy_catalog

ROOT = Path(__file__).resolve().parents[1]
FORMAL = Path("data/research/formal_model_runs")
READINESS = Path("data/research/model_data_bundle_v1/model-data-readiness.json")


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    for relative in (FORMAL, Path("data/research/strategy_signal_ledgers")):
        shutil.copytree(ROOT / relative, root / relative)
    active = load_active_strategy_catalog(ROOT / "configs/strategies/registry.json")
    for relative in [Path("configs/strategies/registry.json"), READINESS,
                     *(Path(row.model_contract) for row in active.strategies)]:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, target)
    return root


def _observed_at(root: Path) -> str:
    return json.loads((root / FORMAL / "freshness.json").read_text(encoding="utf-8"))["declared_at"]


def _digests(root: Path) -> dict[str, str]:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def test_doctor_verifies_current_evidence_without_disposable_indexes(repository: Path) -> None:
    assert not (repository / "artifacts").exists()
    before = _digests(repository)
    health, operations = doctor.diagnose(repository, generated_at=_observed_at(repository))
    assert {row["model_version_id"] for row in health["strategies"]} == set(
        load_active_strategy_catalog(repository / "configs/strategies/registry.json").active_model_version_ids
    )
    assert len(operations["records"]) == len(health["strategies"])
    assert health["research_only"] is True and health["trade_ready"] is False
    assert _digests(repository) == before
    assert not (repository / "artifacts").exists()


@pytest.mark.parametrize("damage", ["tamper", "missing"])
def test_doctor_rejects_damaged_formal_sections(repository: Path, damage: str) -> None:
    catalog = json.loads((repository / FORMAL / "catalog.json").read_text(encoding="utf-8"))
    manifest_path = repository / FORMAL / catalog["records"][0]["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    declaration = next(row for row in manifest["sections"] if row["availability_status"] == "available")
    section = manifest_path.parent / declaration["path"]
    if damage == "tamper":
        section.write_bytes(section.read_bytes() + b" ")
    else:
        section.unlink()
    with pytest.raises(FormalBundleReadError, match="formal section"):
        doctor.diagnose(repository, generated_at=_observed_at(repository))


def test_doctor_keeps_training_blockers_scoped_to_unbound_profiles(repository: Path, monkeypatch, capsys) -> None:
    path = repository / READINESS
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["summary"].update(blocked_component_count=1, partial_component_count=0,
                              blocked_training_profiles=["unentitled-us-history"])
    path.write_text(json.dumps(payload), encoding="utf-8")
    blocked, operations = doctor.diagnose(repository, generated_at=_observed_at(repository))
    payload["summary"].update(blocked_component_count=0, blocked_training_profiles=[])
    path.write_text(json.dumps(payload), encoding="utf-8")
    ready, _ = doctor.diagnose(repository, generated_at=_observed_at(repository))
    assert blocked["model_data"]["state"] == "blocked"
    assert ready["model_data"]["state"] == "current"
    assert blocked["state"] == ready["state"]
    assert blocked["strategies"] == ready["strategies"]
    assert all(row["stages"]["model_data"] == "not_applicable" for row in blocked["strategies"])
    monkeypatch.setattr(doctor, "diagnose", lambda *args, **kwargs: (blocked, operations))
    assert doctor.main(["--root", str(repository)]) == (0 if blocked["state"] == "current" else 1)
    output = capsys.readouterr().out
    assert "Research training profiles: blocked" in output
    assert "blocked_profiles=1" in output
    assert "current_allocations" not in output and "target_allocations" not in output


def test_doctor_reports_real_session_delay_as_failure(repository: Path, monkeypatch, capsys) -> None:
    freshness_path = repository / FORMAL / "freshness.json"
    freshness = json.loads(freshness_path.read_text(encoding="utf-8"))
    freshness["markets"]["cn"] = "2026-01-02"
    freshness_path.write_text(json.dumps(freshness), encoding="utf-8")
    health, operations = doctor.diagnose(repository, generated_at=_observed_at(repository))
    assert health["state"] == "delayed"
    assert next(row for row in health["markets"] if row["market"] == "cn")["state"] == "delayed"
    monkeypatch.setattr(doctor, "diagnose", lambda *args, **kwargs: (health, operations))
    assert doctor.main(["--root", str(repository)]) == 1
    assert "provider=delayed" in capsys.readouterr().out


def test_doctor_does_not_invent_missing_readiness(repository: Path, capsys) -> None:
    (repository / READINESS).unlink()
    with pytest.raises(SystemHealthError, match="invalid health input"):
        doctor.diagnose(repository, generated_at=_observed_at(repository))
    assert doctor.main(["--root", str(repository)]) == 1
    assert "could not be verified" in capsys.readouterr().out
    assert not (repository / READINESS).exists()


def test_doctor_cannot_fetch_train_or_write_repository_evidence(repository: Path) -> None:
    code = r'''
import importlib.abc, json, os, sys
from pathlib import Path
class RejectEngines(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("qlib", "mlflow", "lightgbm", "xgboost", "src.data.adapters",
                                "src.research.formal_model_replay", "src.research.ranker_training")):
            raise AssertionError("doctor loaded research/provider engine: " + fullname)
root = Path(sys.argv[1]).resolve()
def audit(event, args):
    if event in {"socket.connect", "socket.getaddrinfo"}:
        raise AssertionError("doctor attempted network access")
    if event == "open":
        path, mode, flags = args
        if isinstance(path, (str, bytes, os.PathLike)) and (
            any(c in (mode or "") for c in "wax+") or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)
        ):
            if Path(path).resolve().is_relative_to(root):
                raise AssertionError("doctor attempted evidence write")
sys.meta_path.insert(0, RejectEngines())
sys.addaudithook(audit)
from scripts.doctor import diagnose
freshness = json.loads((root / "data/research/formal_model_runs/freshness.json").read_text())
health, operations = diagnose(root, generated_at=freshness["declared_at"])
assert len(health["strategies"]) == len(operations["records"]) > 0
'''
    before = _digests(repository)
    process = subprocess.run([sys.executable, "-c", code, str(repository)], cwd=ROOT,
                             env=os.environ | {"PYTHONDONTWRITEBYTECODE": "1"},
                             capture_output=True, text=True, timeout=30)
    assert process.returncode == 0, process.stderr
    assert _digests(repository) == before


def test_doctor_rejects_truncated_readiness_instead_of_reporting_current(repository: Path, capsys) -> None:
    (repository / READINESS).write_text('{"summary": {}}', encoding="utf-8")
    assert doctor.main(["--root", str(repository)]) == 1
    output = capsys.readouterr().out
    assert "model-data readiness" in output
    assert "Research training profiles: current" not in output
    assert "[SUCCESS]" not in output
