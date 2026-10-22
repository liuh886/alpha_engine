"""Executable release quality gates shared by local runs and CI."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CommandSpec:
    """A quality command with a stable name and working directory."""

    name: str
    argv: tuple[str, ...]
    cwd: Path


@dataclass(frozen=True)
class CommandResult:
    """Captured evidence for one command invocation."""

    name: str
    command: list[str]
    cwd: str
    exit_code: int
    duration_seconds: float
    output_sha256: str
    output_file: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def build_quality_commands(project_root: Path, evidence_dir: Path) -> list[CommandSpec]:
    """Return the complete, ordered local/CI quality command set."""
    root = project_root.resolve()
    frontend = root / "qlib-dashboard"
    return [
        CommandSpec("retired_web_boundary", ("uv", "run", "python", "scripts/check_legacy_web_boundary.py"), root),
        CommandSpec(
            "ci_governance",
            ("uv", "run", "python", "scripts/check_ci_governance.py",
             "--output", str(evidence_dir.resolve() / "ci-workflow-inventory.json"), "--enforce"),
            root,
        ),
        CommandSpec("ruff", ("uv", "run", "ruff", "check", "."), root),
        CommandSpec(
            "mypy_ratchet",
            (
                "uv",
                "run",
                "mypy",
                "src/release",
                "scripts/release_gate.py",
                "src/models/metric_contract.py",
                "src/research/economics.py",
                "src/research/replay_comparison.py",
                "src/research/ranker_execution.py",
                "src/research/ranker_training.py",
                "src/research/us_x1_3_current_target.py",
                "src/data/listing_lifecycle.py",
                "src/data/symbol_identity.py",
                "src/data/snapshot_manifest.py",
                "src/factors/ranker_snapshot.py",
                "src/governance/active_strategy_catalog.py",
                "src/research/formal_baseline.py",
                "src/artifacts/system_health.py",
                "src/data/model_data_bundle.py",
                "src/data/snapshot.py",
                "src/data/market_provider.py",
                "src/artifacts/formal_bundle_reader.py",
                "src/governance/strategy_runtime_capabilities.py",
                "src/research/factor_identity.py",
            ),
            root,
        ),
        CommandSpec(
            "backend_tests",
            (
                "python",
                "-m",
                "pytest",
                "tests",
                "-q",
                "--strict-markers",
                "-p",
                "src.release.pytest_skip_report",
                f"--junitxml={evidence_dir.resolve() / 'pytest.xml'}",
            ),
            root,
        ),
        CommandSpec("frontend_install", ("npm", "ci"), frontend),
        CommandSpec("frontend_typecheck", ("npx", "tsc", "--noEmit"), frontend),
        CommandSpec("frontend_lint", ("npm", "run", "lint"), frontend),
        CommandSpec("frontend_build", ("npm", "run", "build"), frontend),
        CommandSpec("frontend_bundle_budget", ("npm", "run", "check:bundle-budget"), frontend),
        CommandSpec("playwright_install", ("npx", "playwright", "install", "chromium"), frontend),
        CommandSpec("playwright", ("npx", "playwright", "test"), frontend),
        CommandSpec("package_build", ("uv", "build"), root),
    ]


def classify_skips(skips: list[dict[str, str]], approved: set[str] | None = None) -> dict[str, Any]:
    """Classify exact pytest node ids; every non-approved skip fails the gate."""
    approved = approved or set()
    rows = sorted(skips, key=lambda row: (row.get("nodeid", ""), row.get("reason", "")))
    approved_rows = [row for row in rows if row.get("nodeid") in approved]
    unapproved = [row for row in rows if row.get("nodeid") not in approved]
    unused = sorted(approved - {row.get("nodeid", "") for row in rows})
    return {
        "ok": not unapproved,
        "approved_count": len(approved_rows),
        "unapproved_count": len(unapproved),
        "approved": approved_rows,
        "unapproved": unapproved,
        "unused_approvals": unused,
    }


def run_quality_gates(
    project_root: Path,
    evidence_dir: Path,
    *,
    revision: str,
    approved_skips: set[str] | None = None,
) -> dict[str, Any]:
    """Run every release command and persist auditable output evidence."""
    root = project_root.resolve()
    output_dir = evidence_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    skip_path = output_dir / "pytest_skips.json"
    skip_path.unlink(missing_ok=True)
    commands = build_quality_commands(root, output_dir)
    results: list[CommandResult] = []
    build_ok = False
    browser_install_ok = False
    for command in commands:
        environment = os.environ.copy()
        if command.name == "backend_tests":
            environment["ALPHA_SKIP_REPORT"] = str(skip_path)
        if command.name == "playwright_install" and not build_ok:
            result = _blocked_result(command, output_dir, "frontend_build did not pass")
        elif command.name == "playwright" and not browser_install_ok:
            result = _blocked_result(command, output_dir, "playwright_install did not pass")
        else:
            result = _run_command(command, output_dir, environment)
        results.append(result)
        if command.name == "frontend_build":
            build_ok = result.ok
        if command.name == "playwright_install":
            browser_install_ok = result.ok

    skips = _read_skips(skip_path)
    skip_accounting = classify_skips(skips or [], approved=approved_skips)
    skip_accounting["report_present"] = skip_path.is_file()
    skip_accounting["report_valid"] = skips is not None
    if skips is None:
        skip_accounting["ok"] = False
    report = {
        "schema_version": "1",
        "revision": revision,
        "environment": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": platform.platform(),
        },
        "commands": [
            asdict(result) | {"status": "pass" if result.ok else "fail"} for result in results
        ],
        "skip_accounting": skip_accounting,
    }
    report["status"] = (
        "pass" if all(result.ok for result in results) and skip_accounting["ok"] else "fail"
    )
    report_path = output_dir / "quality_gate_report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def _run_command(spec: CommandSpec, output_dir: Path, environment: dict[str, str]) -> CommandResult:
    started = time.perf_counter()
    try:
        process = subprocess.run(
            _executable_argv(spec.argv),
            cwd=spec.cwd,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        output = process.stdout + process.stderr
        exit_code = process.returncode
        if (
            spec.name == "frontend_install" and platform.system() == "Windows" and exit_code == 0
            and not (spec.cwd / "node_modules/@rolldown/binding-win32-x64-msvc/package.json").is_file()
        ):
            # Repair only a skipped optional binary, using the locked version
            # without changing the inputs whose release quality is being checked.
            lock = json.loads((spec.cwd / "package-lock.json").read_text(encoding="utf-8"))
            binding_version = lock["packages"]["node_modules/@rolldown/binding-win32-x64-msvc"]["version"]
            binding_proc = subprocess.run(
                _executable_argv(
                    ("npm", "install", "--no-save", "--package-lock=false",
                     f"@rolldown/binding-win32-x64-msvc@{binding_version}")
                ),
                cwd=spec.cwd,
                env=environment,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            output += "\n" + binding_proc.stdout + binding_proc.stderr
            if binding_proc.returncode != 0:
                exit_code = binding_proc.returncode
    except (OSError, subprocess.SubprocessError, KeyError, json.JSONDecodeError) as exc:
        output = f"{type(exc).__name__}: {exc}\n"
        exit_code = -1
    return _capture_result(spec, output_dir, started, exit_code, output)


def _blocked_result(spec: CommandSpec, output_dir: Path, reason: str) -> CommandResult:
    return _capture_result(spec, output_dir, time.perf_counter(), -1, f"BLOCKED: {reason}\n")


def _capture_result(
    spec: CommandSpec,
    output_dir: Path,
    started: float,
    exit_code: int,
    output: str,
) -> CommandResult:
    output_path = output_dir / f"{spec.name}.log"
    encoded = output.encode("utf-8")
    output_path.write_bytes(encoded)
    digest = hashlib.sha256(encoded).hexdigest()
    return CommandResult(
        name=spec.name,
        command=list(spec.argv),
        cwd=str(spec.cwd),
        exit_code=exit_code,
        duration_seconds=round(time.perf_counter() - started, 3),
        output_sha256=digest,
        output_file=str(output_path),
    )


def _executable_argv(argv: tuple[str, ...]) -> list[str]:
    executable = sys.executable if argv[0] == "python" else shutil.which(argv[0])
    return [executable or argv[0], *argv[1:]]


def _read_skips(path: Path) -> list[dict[str, str]] | None:
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, list) or any(
        not isinstance(row, dict)
        or not isinstance(row.get("nodeid"), str) or not row["nodeid"]
        or not isinstance(row.get("reason"), str)
        for row in value
    ):
        return None
    return value
