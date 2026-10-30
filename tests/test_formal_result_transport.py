from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest

import scripts.transport_formal_strategy_result as transport
from scripts.run_formal_refresh_transaction import assemble_strategy_results
from src.artifacts.formal_refresh import FormalRefreshError, load_object, write_object
from src.data import governed_actions_artifact as archives
from test_formal_strategy_refresh import _receipt, _tasks, _write_plan


def git(root, *args):
    return (
        subprocess.check_output(
            ["git", "-c", "user.name=Test", "-c", "user.email=test@local", *args],
            cwd=root,
            stderr=subprocess.PIPE,
        )
        .decode()
        .strip()
    )


@pytest.fixture
def store(tmp_path, monkeypatch):
    remote = tmp_path / "archive.git"
    git(tmp_path, "init", "--bare", "--initial-branch=main", str(remote))
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "--initial-branch=main")
    (seed / "existing-private-ledger").write_bytes(b"synthetic sealed sibling state")
    git(seed, "add", ".")
    git(seed, "commit", "-m", "Seed private fixture")
    git(seed, "push", str(remote), "HEAD:main")

    @contextmanager
    def environment(key):
        assert key == "synthetic-scoped-key"
        with tempfile.TemporaryDirectory(dir=tmp_path) as temporary:
            worktree = Path(temporary) / "git"
            worktree.mkdir()
            yield worktree, dict(os.environ)

    monkeypatch.setattr(archives, "_private_git_environment", environment)
    monkeypatch.setattr(archives, "_private_archive_remote", lambda repository: str(remote))
    return remote


@pytest.fixture
def evidence(tmp_path, store):
    tasks = _tasks()
    for task in tasks:
        task["formal_refresh_required"] = True
    plan = tmp_path / "plan.json"
    _write_plan(plan, tasks)
    results = tmp_path / "results"
    for task in tasks:
        strategy = str(task["strategy_id"])
        write_object(results / strategy / "receipt.json", _receipt(task, "execution_failed"))
        # Synthetic private evidence must survive privately but never enter a locator.
        write_object(
            results / strategy / "input" / "native.json", {"target_weights": {"PRIVATE_CANARY": 1}}
        )
    return dict(
        plan_path=plan,
        results_root=results,
        bindings_root=tmp_path / "bindings",
        run_id="42",
        attempt="1",
        code_revision="a" * 40,
        ssh_key="synthetic-scoped-key",
    )


def retain_all(evidence):
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(
            pool.map(
                lambda strategy: transport.retain_result(**evidence, strategy=strategy),
                transport._tasks(evidence["plan_path"]),
            )
        )


def test_four_concurrent_results_roundtrip_and_failed_evidence_still_blocks_fan_in(
    evidence, store, tmp_path
):
    bindings = retain_all(evidence)
    assert len(bindings) == 4
    assert git(store, "show", "main:existing-private-ledger") == "synthetic sealed sibling state"
    assert b"PRIVATE_CANARY" not in b"".join(
        p.read_bytes() for p in evidence["bindings_root"].rglob("*.json")
    )
    restored = tmp_path / "restored"
    transport.restore_results(**{**evidence, "results_root": restored})
    original = evidence["results_root"]
    assert {
        p.relative_to(original): p.read_bytes() for p in original.rglob("*") if p.is_file()
    } == {p.relative_to(restored): p.read_bytes() for p in restored.rglob("*") if p.is_file()}
    # Existing atomic evaluator still receives the original failure receipts.
    with pytest.raises(FormalRefreshError, match="fatal strategy execution failure"):
        assemble_strategy_results(
            plan_path=evidence["plan_path"],
            strategy_results_root=restored,
            current_preview_root=tmp_path / "unused",
            candidate_preview_root=tmp_path / "candidate",
            receipt_path=tmp_path / "fan-in.json",
        )
    assert not (tmp_path / "candidate").exists()


def test_same_archive_is_idempotent_and_changed_same_member_is_rejected(evidence, store):
    first = transport.retain_result(**evidence, strategy="us_x")
    assert transport.retain_result(**evidence, strategy="us_x")["archive"] == first["archive"]
    (evidence["results_root"] / "us_x" / "input" / "native.json").write_bytes(b"different")
    with pytest.raises(archives.GovernedActionsArtifactError, match="refusing to replace"):
        transport.retain_result(**evidence, strategy="us_x")
    assert git(store, "rev-parse", "main") == first["archive"]["commit"]


def test_restored_data_blocked_receipts_keep_existing_degraded_publication_semantics(
    evidence, tmp_path
):
    for task in transport._tasks(evidence["plan_path"]).values():
        write_object(
            evidence["results_root"] / task["strategy_id"] / "receipt.json",
            _receipt(task, "data_blocked"),
        )
    retain_all(evidence)
    restored = tmp_path / "restored"
    transport.restore_results(**{**evidence, "results_root": restored})
    current = tmp_path / "current"
    shutil.copytree(Path("data/research/model_runs"), current)
    receipt = assemble_strategy_results(
        plan_path=evidence["plan_path"],
        strategy_results_root=restored,
        current_preview_root=current,
        candidate_preview_root=tmp_path / "candidate",
        receipt_path=tmp_path / "fan-in.json",
    )
    assert receipt["status"] == "degraded"
    assert set(receipt["retained_strategy_ids"]) == set(transport._tasks(evidence["plan_path"]))
    assert receipt["changed_strategy_ids"] == []


def test_push_failure_without_remote_advance_stops_without_retry_or_locator(evidence, monkeypatch):
    original = archives._archive_git
    pushes = []

    def denied(worktree, env, *args):
        if args[0] == "push":
            pushes.append(args)
            raise archives.GovernedActionsArtifactError("synthetic denied write")
        return original(worktree, env, *args)

    monkeypatch.setattr(archives, "_archive_git", denied)
    with pytest.raises(archives.GovernedActionsArtifactError, match="append failed"):
        transport.retain_result(**evidence, strategy="us_x")
    assert len(pushes) == 1
    assert not evidence["bindings_root"].exists()


@pytest.mark.parametrize(
    "change",
    [
        "run",
        "code",
        "plan",
        "task",
        "future_attempt",
        "repository",
        "path",
        "digest",
        "size",
        "missing",
        "raw_field",
    ],
)
def test_bad_binding_or_missing_sibling_never_installs_partial_results(evidence, tmp_path, change):
    retain_all(evidence)
    path = evidence["bindings_root"] / "us_x" / "archive-binding.json"
    binding = load_object(path)
    if change == "run":
        binding["workflow_run_id"] = "43"
    elif change == "code":
        binding["code_revision"] = "b" * 40
    elif change == "plan":
        binding["plan_sha256"] = "b" * 64
    elif change == "task":
        binding["task_sha256"] = "b" * 64
    elif change == "future_attempt":
        binding["run_attempt"] = "2"
    elif change == "repository":
        binding["archive"]["repository"] = "owner/other"
    elif change == "path":
        binding["archive"]["path"] = "archives/strategy-signal-ledgers/latest.zip"
    elif change == "digest":
        binding["archive"]["sha256"] = "b" * 64
    elif change == "size":
        binding["archive"]["size_bytes"] = 1
    elif change == "raw_field":
        binding["private_payload"] = "PRIVATE_CANARY"
    write_object(path, binding)
    if change == "missing":
        path.unlink()
    target = tmp_path / "restored"
    with pytest.raises((ValueError, archives.GovernedActionsArtifactError)):
        transport.restore_results(**{**evidence, "results_root": target})
    assert not target.exists()


@pytest.mark.parametrize("status", ["current_no_change", "data_blocked", "execution_failed"])
def test_old_successful_or_blocked_artifact_cannot_mask_retry_before_upload(
    evidence, tmp_path, status
):
    for task in transport._tasks(evidence["plan_path"]).values():
        write_object(
            evidence["results_root"] / task["strategy_id"] / "receipt.json", _receipt(task, status)
        )
    retain_all(evidence)
    with pytest.raises(ValueError):
        transport.restore_results(
            **{**evidence, "attempt": "2", "results_root": tmp_path / "restored"}
        )
    assert not (tmp_path / "restored").exists()


def test_complete_new_attempt_preserves_prior_members_and_restores_exact_current(
    evidence, tmp_path, store
):
    first = retain_all(evidence)
    current = {**evidence, "attempt": "2"}
    retain_all(current)
    transport.restore_results(**{**current, "results_root": tmp_path / "restored"})
    assert (tmp_path / "restored" / "us_x" / "receipt.json").is_file()
    for binding in first:
        assert git(store, "ls-tree", "main", "--", binding["archive"]["path"])


@pytest.mark.parametrize(
    "name",
    [
        "../escape",
        "us_x/../escape",
        "us_x/A",
        "us_x/CON.txt",
        "us_x/a.",
        "us_x/a\\b",
        "us_x/C:stream",
    ],
)
def test_zip_aliases_traversal_and_device_paths_rejected(name):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("us_x/receipt.json", "{}")
        archive.writestr("us_x/a", "first")
        archive.writestr(name.replace("\\", "X"), "synthetic")
    # Windows' ZIP writer normalizes backslashes. Mutate both on-disk headers
    # to exercise hostile archive input rather than the writer's safe output.
    stream = io.BytesIO(stream.getvalue().replace(name.replace("\\", "X").encode(), name.encode()))
    with zipfile.ZipFile(stream) as archive, pytest.raises(ValueError):
        transport._validate_zip(archive, "us_x")


def test_symlink_zip_and_expansion_overflow_are_rejected(monkeypatch):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        info = zipfile.ZipInfo("us_x/receipt.json")
        info.external_attr = 0o120777 << 16
        archive.writestr(info, "outside")
    stream.seek(0)
    with zipfile.ZipFile(stream) as archive, pytest.raises(ValueError):
        transport._validate_zip(archive, "us_x")
    monkeypatch.setattr(transport, "MAX_EXPANDED", 1)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("us_x/receipt.json", "{}")
    stream.seek(0)
    with zipfile.ZipFile(stream) as archive, pytest.raises(ValueError):
        transport._validate_zip(archive, "us_x")


def test_archive_append_preserves_unrelated_ledger_update_at_push(
    evidence, store, tmp_path, monkeypatch
):
    original = archives._archive_git
    once = []

    def racing(worktree, env, *args):
        if args[0] == "push" and not once:
            once.append(True)
            clone = tmp_path / "racing-writer"
            git(tmp_path, "clone", str(store), str(clone))
            (clone / "existing-private-ledger").write_bytes(b"advanced sibling state")
            git(clone, "add", ".")
            git(clone, "commit", "-m", "Concurrent sibling update")
            git(clone, "push", "origin", "HEAD:main")
        return original(worktree, env, *args)

    monkeypatch.setattr(archives, "_archive_git", racing)
    binding = transport.retain_result(**evidence, strategy="us_x")
    assert git(store, "show", "main:existing-private-ledger") == "advanced sibling state"
    assert git(store, "rev-parse", "main") == binding["archive"]["commit"]


def test_workflow_transfers_only_binding_and_restores_before_existing_atomic_fan_in():
    text = Path(".github/workflows/formal-backtest-refresh.yml").read_text(encoding="utf-8")
    strategy = text[text.index("\n  strategy:\n") : text.index("\n  publish:\n")]
    assert "path: artifacts/formal-refresh/strategy-result\n" not in strategy
    assert strategy.index("Retain complete strategy result privately") < strategy.index(
        "Upload private strategy result binding"
    )
    assert "path: artifacts/formal-refresh/strategy-bindings" in strategy
    publish = text[text.index("\n  publish:\n") :]
    assert publish.index("Restore exact private strategy results") < publish.index(
        "Atomically fan in active preview results"
    )
    assert '--attempt "$GITHUB_RUN_ATTEMPT"' in publish
