from __future__ import annotations

import os
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

import pytest

from src.artifacts import private_signal_ledger as private
from src.artifacts.strategy_signal_checkpoint import pack_signal_checkpoint
from test_strategy_signal_checkpoint import source


def git(root, *args):
    return subprocess.check_output(["git", "-c", "user.name=Test", "-c", "user.email=test@local", *args], cwd=root, stderr=subprocess.PIPE).decode().strip()


@pytest.fixture
def store(tmp_path, monkeypatch):
    root, catalog = source.__wrapped__(tmp_path)
    remote = tmp_path / "private.git"
    git(tmp_path, "init", "--bare", "--initial-branch=main", str(remote))
    writer = tmp_path / "writer"
    writer.mkdir()
    git(writer, "init", "--initial-branch=main")
    archive = writer / private.MEMBER
    archive.parent.mkdir(parents=True)
    pack_signal_checkpoint(root, archive, catalog=catalog, code_revision="a" * 40)
    git(writer, "add", ".")
    git(writer, "commit", "-m", "Seed existing canonical checkpoint")
    git(writer, "push", str(remote), "HEAD:main")
    monkeypatch.setattr(private, "REMOTE", str(remote))

    @contextmanager
    def environment(key):
        assert key == "test-scoped-key"
        with tempfile.TemporaryDirectory(dir=tmp_path) as temporary:
            yield Path(temporary), dict(os.environ)

    monkeypatch.setattr(private, "_private_git_environment", environment)
    return root, catalog, remote


def restore(store, output, revision=None):
    _, catalog, _ = store
    return private.restore_private_ledgers(root=output, catalog=catalog, ssh_key="test-scoped-key", revision=revision)


def persist(store, output, receipt):
    _, catalog, _ = store
    return private.persist_private_ledgers(root=output, catalog=catalog, ssh_key="test-scoped-key", base=receipt, code_revision="b" * 40)


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_restore_noop_append_and_exact_revision_recovery(store, tmp_path):
    original, _, remote = store
    output = tmp_path / "consumer"
    receipt = restore(store, output)
    assert files(output) == files(original)
    noop = persist(store, output, receipt)
    assert noop["changed"] is False and noop["private_commit"] == receipt["private_commit"]
    model = receipt["models"][0]
    (output / model / "README.md").write_bytes(b"canonical provenance")
    saved = persist(store, output, noop)
    assert saved["changed"] is True
    assert git(remote, "rev-parse", "main") == saved["private_commit"]
    recovered = tmp_path / "recovered"
    assert restore(store, recovered)["archive_sha256"] == saved["archive_sha256"]
    assert files(recovered) == files(output)
    older = tmp_path / "older"
    restore(store, older, receipt["private_commit"])
    assert files(older) == files(original)


def test_two_stale_writers_cannot_lose_each_others_updates(store, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    ar, br = restore(store, a), restore(store, b)
    model = ar["models"][0]
    (a / model / "README.md").write_bytes(b"writer a")
    winner = persist(store, a, ar)
    (b / model / "README.md").write_bytes(b"writer b")
    with pytest.raises(private.PrivateLedgerError, match="conflict"):
        persist(store, b, br)
    restored = tmp_path / "winner"
    assert restore(store, restored)["private_commit"] == winner["private_commit"]
    assert (restored / model / "README.md").read_bytes() == b"writer a"


def test_race_at_push_fails_without_force_or_rebase(store, tmp_path, monkeypatch):
    output = tmp_path / "consumer"
    receipt = restore(store, output)
    (output / receipt["models"][0] / "README.md").write_text("candidate")
    _, _, remote = store
    original_git = private._git
    advanced = []

    def raced(worktree, env, *args, **kwargs):
        if args[0] == "push":
            competitor = tmp_path / "competitor"
            git(tmp_path, "clone", str(remote), str(competitor))
            (competitor / "unrelated-archive.txt").write_text("other retention")
            git(competitor, "add", ".")
            git(competitor, "commit", "-m", "Concurrent unrelated retention")
            git(competitor, "push", "origin", "HEAD:main")
            advanced.append(git(remote, "rev-parse", "main"))
        return original_git(worktree, env, *args, **kwargs)

    monkeypatch.setattr(private, "_git", raced)
    with pytest.raises(private.PrivateLedgerError, match="restore authoritative"):
        persist(store, output, receipt)
    assert git(remote, "rev-parse", "main") == advanced[0]


def test_missing_checkpoint_has_no_public_fallback_and_keeps_local_evidence(store, tmp_path):
    _, _, remote = store
    writer = tmp_path / "remove"
    git(tmp_path, "clone", str(remote), str(writer))
    git(writer, "rm", private.MEMBER)
    git(writer, "commit", "-m", "Simulate missing private checkpoint")
    git(writer, "push", "origin", "HEAD:main")
    local = tmp_path / "existing"
    local.mkdir()
    (local / "public-evidence.json").write_bytes(b"must not be used")
    with pytest.raises(private.PrivateLedgerError, match="missing"):
        restore(store, local)
    assert files(local) == {"public-evidence.json": b"must not be used"}


def test_sealed_evidence_removal_is_rejected_and_retired_tree_is_untouched(store, tmp_path):
    output = tmp_path / "consumer"
    output.mkdir()
    (output / "retired").mkdir()
    (output / "retired" / "sealed.json").write_bytes(b"history")
    receipt = restore(store, output)
    assert (output / "retired" / "sealed.json").read_bytes() == b"history"
    next((output / receipt["models"][0] / "deliveries").rglob("*.json")).unlink()
    with pytest.raises(private.PrivateLedgerError, match="sealed evidence"):
        persist(store, output, receipt)


def test_cli_requires_private_restore_receipt_and_no_public_receipt_output(store, tmp_path, monkeypatch, capsys):
    from src.cli.main import main

    _, catalog, _ = store
    monkeypatch.setenv("GOVERNED_SOURCE_ARCHIVE_SSH_KEY", "test-scoped-key")
    monkeypatch.setenv("GOVERNED_SOURCE_ARCHIVE_WRITE_SSH_KEY", "test-scoped-key")
    repo = Path(__file__).resolve().parents[1]
    common = ["--root", str(repo), "ops", "private-ledgers"]
    paths = ["--strategy-catalog", str(catalog), "--ledger-root", str(tmp_path / "cli")]
    receipt = tmp_path / "receipt.json"
    assert main([*common, "restore", *paths, "--receipt", str(receipt)]) == 0
    assert "weights" not in capsys.readouterr().out
    assert main([*common, "persist", *paths, "--receipt", str(receipt)]) == 0
    assert '"changed": false' in capsys.readouterr().out
    assert main([*common, "restore", *paths, "--receipt", "artifacts/private-receipt.json"]) == 2
    assert "outside the repository" in capsys.readouterr().out
    assert main([*common, "persist", *paths, "--receipt", str(tmp_path / "missing.json")]) == 2
    assert '"status": "blocked"' in capsys.readouterr().out


def test_capture_cannot_bypass_immutable_checks_by_changing_source_before_pack(store, tmp_path, monkeypatch):
    output = tmp_path / "consumer"
    receipt = restore(store, output)
    model = receipt["models"][0]
    (output / model / "README.md").write_text("new provenance")
    original = private.pack_signal_checkpoint

    def change_then_pack(*args, **kwargs):
        sealed = next((output / model / "deliveries").rglob("*.json"))
        sealed.write_bytes(sealed.read_bytes() + b" ")
        return original(*args, **kwargs)

    monkeypatch.setattr(private, "pack_signal_checkpoint", change_then_pack)
    with pytest.raises(private.PrivateLedgerError, match="source changed"):
        persist(store, output, receipt)
    _, _, remote = store
    assert git(remote, "rev-parse", "main") == receipt["private_commit"]


def test_private_seed_cannot_discard_public_or_local_sealed_evidence(store, tmp_path):
    output = tmp_path / "consumer"
    receipt = restore(store, output)
    recent = output / receipt["models"][0] / "deliveries" / "2026-08-13" / "later-public-run.json"
    recent.parent.mkdir(parents=True, exist_ok=True)
    recent.write_bytes(b"new public receipt not in the private seed")
    before = files(output)
    with pytest.raises(private.PrivateLedgerError, match="sealed evidence"):
        restore(store, output)
    assert files(output) == before


@pytest.mark.parametrize("rollback_fails", [False, True])
def test_hydration_failure_recovers_or_preserves_original_bytes(tmp_path, monkeypatch, rollback_fails):
    model = "test_model"
    root, stage = tmp_path / "live", tmp_path / "stage"
    for path, data in ((root, b"original"), (stage, b"private snapshot")):
        (path / model).mkdir(parents=True)
        (path / model / "original.json").write_bytes(data)
    replace = os.replace

    def failed(source, target):
        source, target = Path(source), Path(target)
        if target == root / model and (source == stage / model or rollback_fails):
            raise OSError("injected installation failure")
        return replace(source, target)

    monkeypatch.setattr(private.os, "replace", failed)
    with pytest.raises((OSError, private.PrivateLedgerError)):
        private._install(stage, root, [model])
    if rollback_fails:
        retained = list(tmp_path.glob(".ledger-backup-*/test_model/original.json"))
        assert len(retained) == 1 and retained[0].read_bytes() == b"original"
    else:
        assert (root / model / "original.json").read_bytes() == b"original"
        assert not list(tmp_path.glob(".ledger-backup-*"))
