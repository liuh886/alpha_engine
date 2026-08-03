"""Materialize immutable formal-package bases pinned to a Git commit."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


class FormalBaseMaterializationError(ValueError):
    """Raised when a pinned formal base cannot be verified or materialized."""


def _object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalBaseMaterializationError(f"invalid base manifest: {path}") from exc
    if not isinstance(payload, dict):
        raise FormalBaseMaterializationError("base manifest root must be an object")
    return payload


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=check,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError):
            detail = exc.stderr.decode(errors="replace").strip()
        raise FormalBaseMaterializationError(
            f"git {' '.join(args)} failed{': ' + detail if detail else ''}"
        ) from exc


def _ensure_commit(root: Path, commit: str, *, fetch: bool) -> None:
    probe = _git(root, "cat-file", "-e", f"{commit}^{{commit}}", check=False)
    if probe.returncode == 0:
        return
    if not fetch:
        raise FormalBaseMaterializationError(f"pinned base commit is unavailable: {commit}")
    _git(root, "fetch", "--no-tags", "--depth=1", "origin", commit)
    probe = _git(root, "cat-file", "-e", f"{commit}^{{commit}}", check=False)
    if probe.returncode != 0:
        raise FormalBaseMaterializationError(f"cannot fetch pinned base commit: {commit}")


def materialize(
    *,
    repository_root: Path,
    manifest_path: Path,
    output_dir: Path,
    fetch: bool = True,
) -> dict[str, Any]:
    manifest = _object(manifest_path)
    if manifest.get("research_only") is not True or manifest.get("trade_ready") is not False:
        raise FormalBaseMaterializationError("base research boundary is invalid")
    commit = str(manifest.get("base_commit") or "")
    if len(commit) != 40:
        raise FormalBaseMaterializationError("base_commit must be a full Git SHA")
    models = manifest.get("models")
    if not isinstance(models, dict) or set(models) != {"us_x1_1", "cn_x1_0"}:
        raise FormalBaseMaterializationError("base manifest must define US x1.1 and CN x1.0")

    root = repository_root.resolve()
    _ensure_commit(root, commit, fetch=fetch)
    output_dir.mkdir(parents=True, exist_ok=True)
    records: dict[str, dict[str, Any]] = {}
    for model_id in ("us_x1_1", "cn_x1_0"):
        row = models[model_id]
        if not isinstance(row, dict):
            raise FormalBaseMaterializationError(f"invalid base row: {model_id}")
        source_path = str(row.get("path") or "")
        expected = str(row.get("sha256") or "").lower()
        if not source_path or source_path.startswith("/") or ".." in Path(source_path).parts:
            raise FormalBaseMaterializationError(f"unsafe base path: {source_path}")
        if len(expected) != 64 or any(char not in "0123456789abcdef" for char in expected):
            raise FormalBaseMaterializationError(f"invalid base digest: {model_id}")
        payload = _git(root, "show", f"{commit}:{source_path}").stdout
        actual = hashlib.sha256(payload).hexdigest()
        if actual != expected:
            raise FormalBaseMaterializationError(
                f"base digest mismatch for {model_id}: expected {expected}, got {actual}"
            )
        target = output_dir / f"{model_id}.json"
        target.write_bytes(payload)
        records[model_id] = {
            "source_path": source_path,
            "output_path": target.as_posix(),
            "sha256": actual,
            "size_bytes": len(payload),
        }

    receipt = {
        "schema_version": "1.0.0",
        "status": "materialized",
        "base_commit": commit,
        "records": records,
        "research_only": True,
        "trade_ready": False,
    }
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("data/research/formal_backtests/base_manifest.json"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, default=None)
    parser.add_argument("--no-fetch", action="store_true")
    args = parser.parse_args()
    receipt = materialize(
        repository_root=args.repository_root,
        manifest_path=args.manifest,
        output_dir=args.output_dir,
        fetch=not args.no_fetch,
    )
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt is not None:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
