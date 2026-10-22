from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.release import quality


@pytest.mark.parametrize("failure", [None, "backend_tests", "vitest", "build", "playwright_install", "playwright", "skip", "malformed_skip", "missing_skip"])
def test_quality_receipt_records_each_execution_and_blocks_failures(tmp_path: Path, monkeypatch, failure: str | None) -> None:
    worker = tmp_path / "gate.py"
    worker.write_text(r'''
import json, os, sys
from pathlib import Path
name, failure = sys.argv[1:]
with Path("executions.jsonl").open("a") as stream:
    stream.write(json.dumps(name) + "\n")
print("executed " + name)
if name == "backend_tests":
    skip_path = Path(os.environ["ALPHA_SKIP_REPORT"])
    if failure == "malformed_skip":
        skip_path.write_text("{broken")
    elif failure != "missing_skip":
        skip_path.write_text(json.dumps([{"nodeid": "unapproved::skip", "reason": "missing data"}] if failure == "skip" else []))
if name == "frontend_build":
    print("unit stage")
    if failure == "vitest":
        raise SystemExit(7)
    print("build stage")
    if failure == "build":
        raise SystemExit(8)
if name == failure:
    raise SystemExit(9)
''', encoding="utf-8")
    names = ["backend_tests", "frontend_build", "playwright_install", "playwright", "package_build"]
    commands = [quality.CommandSpec(name, ("python", str(worker), name, failure or ""), tmp_path) for name in names]
    monkeypatch.setattr(quality, "build_quality_commands", lambda *args: commands)
    output = tmp_path / "receipt"
    report = quality.run_quality_gates(tmp_path, output, revision="a" * 40)

    assert report["status"] == ("pass" if failure is None else "fail")
    assert report["revision"] == "a" * 40
    rows = {row["name"]: row for row in report["commands"]}
    assert list(rows) == names
    assert "frontend_vitest" not in rows
    assert rows["package_build"]["status"] == "pass"
    executions = [json.loads(line) for line in (tmp_path / "executions.jsonl").read_text().splitlines()]
    assert all(executions.count(name) <= 1 for name in names)
    if failure in {"vitest", "build"}:
        assert rows["frontend_build"]["status"] == "fail"
        assert "playwright_install" not in executions and "playwright" not in executions
    elif failure == "playwright_install":
        assert "playwright" not in executions
    else:
        assert executions == names
    if failure in {"skip", "malformed_skip", "missing_skip"}:
        assert report["skip_accounting"]["ok"] is False
        assert all(row["status"] == "pass" for row in rows.values())
    for row in rows.values():
        log = Path(row["output_file"]).read_bytes()
        assert hashlib.sha256(log).hexdigest() == row["output_sha256"]
        assert row["duration_seconds"] >= 0
        if row["name"] in executions:
            assert ("executed " + row["name"]).encode() in log
    assert json.loads((output / "quality_gate_report.json").read_text()) == report


@pytest.mark.parametrize("present", [False, True])
def test_windows_optional_binding_repair_reuses_lock_and_preserves_inputs(tmp_path: Path, monkeypatch, present: bool) -> None:
    binary = tmp_path / "node_modules/@rolldown/binding-win32-x64-msvc/package.json"
    if present:
        binary.parent.mkdir(parents=True)
        binary.write_text("{}")
    lock = tmp_path / "package-lock.json"
    lock.write_text(json.dumps({"packages": {"node_modules/@rolldown/binding-win32-x64-msvc": {"version": "1.0.0"}}}))
    original = lock.read_bytes()
    calls = []

    def run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="installed\n", stderr="")

    monkeypatch.setattr(quality.platform, "system", lambda: "Windows")
    monkeypatch.setattr(quality.subprocess, "run", run)
    result = quality._run_command(quality.CommandSpec("frontend_install", ("npm", "ci"), tmp_path), tmp_path, {})
    assert result.ok
    assert len(calls) == (1 if present else 2)
    if not present:
        assert "@rolldown/binding-win32-x64-msvc@1.0.0" in calls[1]
        assert "--package-lock=false" in calls[1] and "--no-save" in calls[1]
    assert lock.read_bytes() == original
