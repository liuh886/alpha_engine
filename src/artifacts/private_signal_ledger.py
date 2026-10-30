"""CAS transport for canonical ledgers in the existing private archive.

The only mutable Git member is a checkpoint of the existing ledger format.
Git commit ancestry supplies publication atomicity; stale writers never rebase.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from src.artifacts.strategy_signal_checkpoint import (
    MAX_BYTES,
    _collect,
    _models,
    pack_signal_checkpoint,
    restore_signal_checkpoint,
)
from src.data.governed_actions_artifact import _private_git_environment

REMOTE = "ssh://git@ssh.github.com:443/liuh886/alpha-engine-data-archive.git"
MEMBER = "archives/strategy-signal-ledgers/latest.zip"


class PrivateLedgerError(ValueError):
    """Missing, stale or unconfirmed protected ledger state; no public fallback."""


def _git(worktree: Path, env: dict[str, str], *args: str, data: bytes | None = None) -> bytes:
    try:
        return subprocess.run(["git", "-c", f"core.hooksPath={worktree / 'no-hooks'}", *args],
            cwd=worktree, env=env, input=data, check=True, capture_output=True, timeout=180).stdout
    except (subprocess.SubprocessError, OSError):
        raise PrivateLedgerError("private ledger Git operation failed; restore authoritative state before retry") from None


def _fetch(worktree: Path, env: dict[str, str], revision: str | None = None) -> str:
    if revision is not None and not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise PrivateLedgerError("private revision must be an exact Git SHA")
    _git(worktree, env, "init", "--quiet")
    _git(worktree, env, "remote", "add", "origin", REMOTE)
    _git(worktree, env, "config", "remote.origin.promisor", "true")
    _git(worktree, env, "config", "remote.origin.partialclonefilter", "blob:none")
    _git(worktree, env, "fetch", "--quiet", "--filter=blob:none", "--depth=1", "origin", revision or "main")
    return _git(worktree, env, "rev-parse", "FETCH_HEAD").decode().strip()


def _download(worktree: Path, env: dict[str, str], commit: str, output: Path) -> tuple[str, int]:
    entry = _git(worktree, env, "ls-tree", commit, "--", MEMBER).decode()
    if not entry.startswith("100644 blob "):
        raise PrivateLedgerError("private canonical checkpoint is missing or not a regular blob")
    size = int(_git(worktree, env, "cat-file", "-s", f"{commit}:{MEMBER}"))
    if not 0 < size <= MAX_BYTES:
        raise PrivateLedgerError("private checkpoint exceeds transport bounds")
    raw = _git(worktree, env, "show", f"{commit}:{MEMBER}")
    if len(raw) != size:
        raise PrivateLedgerError("private checkpoint size changed")
    output.write_bytes(raw)
    output.chmod(0o600)
    return hashlib.sha256(raw).hexdigest(), size


def _receipt(commit: str, digest: str, size: int, catalog: Path) -> dict[str, Any]:
    return {"schema_version": "private_signal_ledger_transport_v1", "private_commit": commit,
        "archive_sha256": digest, "archive_byte_size": size,
        "strategy_catalog_sha256": hashlib.sha256(catalog.read_bytes()).hexdigest(),
        "models": _models(catalog), "research_only": True, "trade_ready": False}


def save_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".ledger-receipt-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _install(staged: Path, root: Path, models: list[str]) -> None:
    """Job-local hydration before any consumers run; roll back partial installs.

    This is not a concurrently readable filesystem publication. Remote Git is
    the atomic authority. Only active subtrees move; retired evidence stays put.
    """
    if root.is_symlink() or any((root / model).is_symlink() for model in models):
        raise PrivateLedgerError("ledger installation cannot traverse symlinks")
    root.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix=".ledger-backup-", dir=root.parent)).resolve()
    cleanup = False
    installed: list[str] = []
    try:
        for model in models:
            target = root / model
            if target.exists():
                os.replace(target, backup / model)
            installed.append(model)
            os.replace(staged / model, target)
        cleanup = True
    except OSError:
        try:
            for model in reversed(installed):
                target = root / model
                if target.exists():
                    os.replace(target, staged / model)
                if (backup / model).exists():
                    os.replace(backup / model, target)
            cleanup = True
        except OSError:
            raise PrivateLedgerError(f"private hydration rollback incomplete; original evidence retained at {backup}") from None
        raise
    finally:
        if cleanup and backup.parent == root.parent.resolve():
            shutil.rmtree(backup)


def _assert_extends(before: dict[str, bytes], after: dict[str, bytes]) -> None:
    for name, raw in before.items():
        if name.endswith("/manifest.json"):
            if name not in after:
                raise PrivateLedgerError("private ledger manifest cannot be removed")
        elif name.endswith("/latest.json"):
            if name not in after:
                raise PrivateLedgerError("private ledger latest cannot be removed")
            old, new = json.loads(raw), json.loads(after[name])
            if new["signal_date"] < old["signal_date"]:
                raise PrivateLedgerError("private ledger latest date cannot regress")
            if new["signal_date"] == old["signal_date"] and raw != after[name] and "correction" not in new:
                raise PrivateLedgerError("private ledger same-date decision conflicts with local evidence")
        elif after.get(name) != raw:
            raise PrivateLedgerError("private ledger sealed evidence cannot be changed or removed")


def restore_private_ledgers(*, root: Path, catalog: Path, ssh_key: str,
                            revision: str | None = None) -> dict[str, Any]:
    with _private_git_environment(ssh_key) as (worktree, env):
        commit = _fetch(worktree, env, revision)
        archive = worktree / "checkpoint.zip"
        digest, size = _download(worktree, env, commit, archive)
        # Stage on the installation filesystem so rename never crosses devices.
        root.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".ledger-stage-", dir=root.parent) as temporary:
            staged = Path(temporary) / "restored"
            restore_signal_checkpoint(archive, staged, catalog=catalog,
                expected_sha256=digest, expected_byte_size=size)
            # During migration, old/public writers may have advanced. Never
            # replace newer local sealed evidence with an obsolete private seed.
            if root.exists() and any((root / model).exists() for model in _models(catalog)):
                _assert_extends(_collect(root, _models(catalog)), _collect(staged, _models(catalog)))
            _install(staged, root, _models(catalog))
        return _receipt(commit, digest, size, catalog)


def persist_private_ledgers(*, root: Path, catalog: Path, ssh_key: str,
                            base: dict[str, Any], code_revision: str) -> dict[str, Any]:
    if (not isinstance(base, dict) or base.get("schema_version") != "private_signal_ledger_transport_v1"
        or base.get("strategy_catalog_sha256") != hashlib.sha256(catalog.read_bytes()).hexdigest()
        or base.get("models") != _models(catalog)
        or base.get("research_only") is not True or base.get("trade_ready") is not False):
        raise PrivateLedgerError("private ledger restore receipt is invalid")
    with _private_git_environment(ssh_key) as (worktree, env):
        parent = _fetch(worktree, env)
        archive = worktree / "base.zip"
        digest, size = _download(worktree, env, parent, archive)
        if digest != base.get("archive_sha256") or size != base.get("archive_byte_size"):
            raise PrivateLedgerError("private ledger conflict: restore latest state and rerun; never rebase a stale decision")
        old = worktree / "old"
        restore_signal_checkpoint(archive, old, catalog=catalog,
            expected_sha256=digest, expected_byte_size=size)
        before = _collect(old, _models(catalog))
        after = _collect(root, _models(catalog))
        _assert_extends(before, after)
        if before == after:
            # Authenticate receive-pack even for a no-op probe. This verifies
            # write-key scope without changing protected strategy evidence.
            _git(worktree, env, "push", "--dry-run", "--quiet", "origin", f"{parent}:refs/heads/main")
            return {**_receipt(parent, digest, size, catalog), "changed": False, "write_access_verified": True}
        updated = worktree / "next.zip"
        packed = pack_signal_checkpoint(root, updated, catalog=catalog, code_revision=code_revision)
        captured = worktree / "captured"
        restore_signal_checkpoint(updated, captured, catalog=catalog,
            expected_sha256=packed["archive_sha256"], expected_byte_size=packed["archive_byte_size"])
        if _collect(captured, _models(catalog)) != after:
            raise PrivateLedgerError("private ledger source changed after immutable-evidence validation")
        publication = updated.read_bytes()
        if hashlib.sha256(publication).hexdigest() != packed["archive_sha256"] or len(publication) != packed["archive_byte_size"]:
            raise PrivateLedgerError("private checkpoint changed before publication")
        blob = _git(worktree, env, "hash-object", "-w", "--stdin", data=publication).decode().strip()
        _git(worktree, env, "read-tree", parent)
        _git(worktree, env, "update-index", "--add", "--cacheinfo", f"100644,{blob},{MEMBER}")
        tree = _git(worktree, env, "write-tree").decode().strip()
        commit = _git(worktree, env, "-c", "user.name=Alpha Engine Research", "-c",
            "user.email=research@alphaengine.local", "commit-tree", tree, "-p", parent,
            "-m", "Persist canonical strategy ledger checkpoint").decode().strip()
        # Fast-forward-only push is the CAS. A concurrent branch update rejects
        # this commit. Never rebase, force-push or replay external side effects.
        _git(worktree, env, "push", "--quiet", "origin", f"{commit}:refs/heads/main")
        return {**_receipt(commit, packed["archive_sha256"], packed["archive_byte_size"], catalog), "changed": True}
