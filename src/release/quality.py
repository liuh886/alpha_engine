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
import urllib.error
import urllib.request
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
    evidence_dir.resolve() / "pytest_skips.json"
    return [
        CommandSpec("ruff", ("uv", "run", "ruff", "check", "."), root),
        CommandSpec(
            "mypy_ratchet",
            ("uv", "run", "mypy", "src/release", "scripts/release_gate.py"),
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
                "-p",
                "src.release.pytest_skip_report",
                f"--junitxml={evidence_dir.resolve() / 'pytest.xml'}",
            ),
            root,
        ),
        CommandSpec("frontend_install", ("npm", "ci"), frontend),
        CommandSpec("frontend_typecheck", ("npx", "tsc", "--noEmit"), frontend),
        CommandSpec("frontend_lint", ("npm", "run", "lint"), frontend),
        CommandSpec("frontend_vitest", ("npm", "run", "test"), frontend),
        CommandSpec("frontend_build", ("npm", "run", "build"), frontend),
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
    for command in commands:
        environment = os.environ.copy()
        if command.name == "backend_tests":
            environment["ALPHA_SKIP_REPORT"] = str(skip_path)
        if command.name == "playwright":
            result = (
                _run_playwright(command, output_dir, environment)
                if build_ok
                else _blocked_result(command, output_dir, "frontend_build did not pass")
            )
        else:
            result = _run_command(command, output_dir, environment)
        results.append(result)
        if command.name == "frontend_build":
            build_ok = result.ok

    skips = _read_skips(skip_path)
    skip_accounting = classify_skips(skips, approved=approved_skips)
    skip_accounting["report_present"] = skip_path.is_file()
    if not skip_path.is_file():
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
    except (OSError, subprocess.SubprocessError) as exc:
        output = f"{type(exc).__name__}: {exc}\n"
        exit_code = -1
    return _capture_result(spec, output_dir, started, exit_code, output)


def _run_playwright(
    spec: CommandSpec, output_dir: Path, environment: dict[str, str]
) -> CommandResult:
    started = time.perf_counter()
    preview_argv = _executable_argv(
        ("npm", "run", "preview", "--", "--host", "127.0.0.1", "--port", "8000", "--strictPort")
    )
    preview: subprocess.Popen[str] | None = None
    output = ""
    try:
        preview = subprocess.Popen(
            preview_argv,
            cwd=spec.cwd,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if not _wait_for_http("http://127.0.0.1:8000", preview):
            preview_output = preview.communicate(timeout=5)[0] if preview.poll() is not None else ""
            return _capture_result(
                spec,
                output_dir,
                started,
                -1,
                "Vite preview did not become ready.\n" + preview_output,
            )
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
    except (OSError, subprocess.SubprocessError) as exc:
        output = f"{type(exc).__name__}: {exc}\n"
        exit_code = -1
    finally:
        if preview is not None and preview.poll() is None:
            preview.terminate()
            try:
                preview.wait(timeout=5)
            except subprocess.TimeoutExpired:
                preview.kill()
                preview.wait(timeout=5)
    return _capture_result(spec, output_dir, started, exit_code, output)


def _wait_for_http(url: str, process: subprocess.Popen[str], timeout: float = 20) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status < 500:
                    return True
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.25)
    return False


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
    output_path.write_text(output, encoding="utf-8")
    digest = hashlib.sha256(output.encode("utf-8")).hexdigest()
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


def _read_skips(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    if not isinstance(value, list):
        return []
    return [
        {"nodeid": str(row.get("nodeid", "")), "reason": str(row.get("reason", ""))}
        for row in value
        if isinstance(row, dict)
    ]
