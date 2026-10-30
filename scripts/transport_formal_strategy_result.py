"""Move Formal result bytes through the existing private archive, never public artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from src.artifacts.formal_refresh import load_object, sha256, write_object
from src.data.governed_actions_artifact import (
    DurableGitArchive,
    GovernedActionsArtifactError,
    _download_durable_git,
    retain_private_archive,
)
from src.governance.active_strategy_catalog import load_active_strategy_catalog

REPOSITORY = "liuh886/alpha-engine-data-archive"
SCHEMA = "formal_private_result_binding_v1"
MAX_FILES = 20000
MAX_EXPANDED = 1024 * 1024 * 1024


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("invalid or mismatched private Formal result evidence")


def _task_hash(task: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(task, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _tasks(plan_path: Path) -> dict[str, dict[str, Any]]:
    plan = load_object(plan_path)
    _require(plan.get("schema_version") == "formal_refresh_plan_v5")
    _require(plan.get("research_only") is True and plan.get("trade_ready") is False)
    tasks = plan.get("tasks")
    _require(isinstance(tasks, list) and bool(tasks))
    active = load_active_strategy_catalog().by_strategy_id
    _require(all(isinstance(task, dict) for task in tasks))
    _require(
        len(tasks) == len(active) and {task.get("strategy_id") for task in tasks} == set(active)
    )
    for task in tasks:
        strategy = active[task["strategy_id"]]
        _require(task.get("model_version_id") == strategy.model_version_id)
        _require(
            type(task.get("formal_refresh_required")) is bool
            and type(task.get("mtm_refresh_required")) is bool
        )
    execution = [
        task for task in tasks if task["formal_refresh_required"] or task["mtm_refresh_required"]
    ]
    _require(plan.get("execution_task_matrix") == execution)
    return {task["strategy_id"]: task for task in execution}


def _identity(run_id: str, attempt: str, code_revision: str) -> None:
    _require(bool(re.fullmatch(r"[1-9][0-9]*", run_id)))
    _require(bool(re.fullmatch(r"[1-9][0-9]*", attempt)))
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", code_revision)))


def _member(run_id: str, attempt: str, strategy: str) -> str:
    return f"archives/formal-strategy-results/{run_id}/attempt-{attempt}/{strategy}.zip"


def _base(plan_path: Path, task: dict[str, Any], run_id: str, code_revision: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA,
        "workflow_run_id": run_id,
        "code_revision": code_revision,
        "plan_sha256": sha256(plan_path),
        "task_sha256": _task_hash(task),
        "strategy_id": task["strategy_id"],
        "model_version_id": task["model_version_id"],
        "research_only": True,
        "trade_ready": False,
    }


def _safe_name(name: str, strategy: str) -> bool:
    # Portable across both runner OSes; no aliases, drive paths or device names.
    parts = name.rstrip("/").split("/")
    return (
        len(parts) > 1
        and parts[0] == strategy
        and all(
            bool(re.fullmatch(r"[A-Za-z0-9_.-]+", part))
            and part not in {".", ".."}
            and not part.endswith(".")
            and not re.fullmatch(r"(?i:con|prn|aux|nul|com[0-9]|lpt[0-9])(?:\..*)?", part)
            for part in parts
        )
    )


def _validate_zip(archive: zipfile.ZipFile, strategy: str) -> None:
    members = archive.infolist()
    _require(0 < len(members) <= MAX_FILES)
    seen: set[str] = set()
    total = 0
    for info in members:
        _require(info.orig_filename == info.filename and _safe_name(info.filename, strategy))
        name = info.filename.rstrip("/").casefold()
        _require(name not in seen)
        seen.add(name)
        _require((info.external_attr >> 16) & 0o170000 != 0o120000)
        _require(not info.flag_bits & 1)
        _require(info.compress_type in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
        total += info.file_size
        _require(total <= MAX_EXPANDED)
    _require(f"{strategy}/receipt.json" in {info.filename for info in members})


def retain_result(
    *,
    plan_path: Path,
    results_root: Path,
    bindings_root: Path,
    strategy: str,
    run_id: str,
    attempt: str,
    code_revision: str,
    ssh_key: str,
) -> dict[str, Any]:
    _identity(run_id, attempt, code_revision)
    tasks = _tasks(plan_path)
    _require(strategy in tasks)
    result = results_root / strategy
    _require(result.is_dir() and not result.is_symlink() and not results_root.is_symlink())
    with tempfile.TemporaryDirectory(prefix="formal-result-pack-") as temporary:
        archive_path = Path(temporary) / "result.zip"
        with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            count = total = 0
            for path in sorted(result.rglob("*")):
                _require(not path.is_symlink())
                if path.is_dir():
                    continue
                _require(path.is_file())
                name = path.relative_to(results_root).as_posix()
                _require(_safe_name(name, strategy))
                count += 1
                total += path.stat().st_size
                _require(count <= MAX_FILES and total <= MAX_EXPANDED)
                archive.write(path, name)
        with zipfile.ZipFile(archive_path) as archive:
            _validate_zip(archive, strategy)
        binding = {
            **_base(plan_path, tasks[strategy], run_id, code_revision),
            "run_attempt": attempt,
            "archive": retain_private_archive(
                repository=REPOSITORY,
                member=_member(run_id, attempt, strategy),
                archive_path=archive_path,
                ssh_key=ssh_key,
            ),
        }
    write_object(bindings_root / strategy / "archive-binding.json", binding)
    return binding


def restore_results(
    *,
    plan_path: Path,
    results_root: Path,
    bindings_root: Path,
    run_id: str,
    attempt: str,
    code_revision: str,
    ssh_key: str,
) -> None:
    _identity(run_id, attempt, code_revision)
    tasks = _tasks(plan_path)
    _require(not results_root.exists() and not results_root.is_symlink())
    observed = {path.parent.name for path in bindings_root.glob("*/archive-binding.json")}
    _require(observed == set(tasks))
    results_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".formal-results-", dir=results_root.parent
    ) as temporary:
        staging = Path(temporary) / "results"
        staging.mkdir()
        for strategy, task in tasks.items():
            locator = bindings_root / strategy / "archive-binding.json"
            _require(not locator.is_symlink() and not locator.parent.is_symlink())
            binding = load_object(locator)
            expected = _base(plan_path, task, run_id, code_revision)
            _require(binding.get("research_only") is True and binding.get("trade_ready") is False)
            _require(set(binding) == set(expected) | {"run_attempt", "archive"})
            _require(all(binding.get(key) == value for key, value in expected.items()))
            original_attempt = binding.get("run_attempt")
            _require(
                isinstance(original_attempt, str)
                and bool(re.fullmatch(r"[1-9][0-9]*", original_attempt))
            )
            # Never let an older successful/blocked artifact conceal a failed
            # retry before upload. Partial reruns fail closed; rerun all jobs.
            _require(original_attempt == attempt)
            archive = binding.get("archive")
            _require(
                isinstance(archive, dict)
                and set(archive) == {"repository", "commit", "path", "sha256", "size_bytes"}
            )
            _require(
                archive["repository"] == REPOSITORY
                and archive["path"] == _member(run_id, original_attempt, strategy)
            )
            _require(
                isinstance(archive["commit"], str)
                and bool(re.fullmatch(r"[0-9a-f]{40}", archive["commit"]))
            )
            _require(
                isinstance(archive["sha256"], str)
                and bool(re.fullmatch(r"[0-9a-f]{64}", archive["sha256"]))
            )
            _require(
                type(archive["size_bytes"]) is int and 0 < archive["size_bytes"] <= 90 * 1024 * 1024
            )
            downloaded = Path(temporary) / "result.zip"
            _download_durable_git(
                archive=DurableGitArchive(**archive), destination=downloaded, ssh_key=ssh_key
            )
            with zipfile.ZipFile(downloaded) as handle:
                _validate_zip(handle, strategy)
                handle.extractall(staging)
        # A failed download/validation never exposes a partial fan-in directory.
        os.replace(staging, results_root)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("retain", "restore"))
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--results-root", type=Path, required=True)
    parser.add_argument("--bindings-root", type=Path, required=True)
    parser.add_argument("--strategy-id")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--code-revision", required=True)
    args = parser.parse_args()
    common = dict(
        plan_path=args.plan,
        results_root=args.results_root,
        bindings_root=args.bindings_root,
        run_id=args.run_id,
        attempt=args.attempt,
        code_revision=args.code_revision,
    )
    try:
        if args.operation == "retain":
            _require(bool(args.strategy_id))
            retain_result(
                **common,
                strategy=args.strategy_id,
                ssh_key=os.environ.get("GOVERNED_SOURCE_ARCHIVE_WRITE_SSH_KEY", ""),
            )
        else:
            restore_results(**common, ssh_key=os.environ.get("GOVERNED_SOURCE_ARCHIVE_SSH_KEY", ""))
    except (
        ValueError,
        OSError,
        KeyError,
        TypeError,
        zipfile.BadZipFile,
        GovernedActionsArtifactError,
    ):
        # No raw receipt reason, file content, command stderr or private path in Actions logs.
        print("private Formal result transport failed; publication blocked")
        return 1
    print(
        json.dumps(
            {
                "status": "complete",
                "operation": args.operation,
                "research_only": True,
                "trade_ready": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
