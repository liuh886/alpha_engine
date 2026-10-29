from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import pytest

from src.artifacts.strategy_signal_checkpoint import (
    INDEX,
    SignalCheckpointError,
    pack_signal_checkpoint,
    restore_signal_checkpoint,
)
from src.artifacts import strategy_signal_checkpoint as checkpoints
from src.artifacts.strategy_signal_ledger import (
    StrategySignalLedgerError,
    append_signal_evaluation,
    correct_latest_decision,
    read_latest_evaluation,
)
from src.cli.main import main
from test_strategy_signal_ledger import MODEL, _signal

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def source(tmp_path):
    catalog = json.loads((REPO / "configs/strategies/registry.json").read_text())
    catalog["strategies"] = [row for row in catalog["strategies"] if row["model_version_id"] == MODEL]
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text(json.dumps(catalog))
    root = tmp_path / "ledgers"
    ledger = root / MODEL
    signal = _signal()
    common = dict(ledger_root=ledger, model_version_id=MODEL, signal=signal, commit_sha="a" * 40)
    append_signal_evaluation(**common, delivery_status="pending", workflow_run_id="seal", created_at_utc="2026-08-13T00:00:00Z")
    append_signal_evaluation(**common, delivery_status="sent", workflow_run_id="deliver", created_at_utc="2026-08-13T01:00:00Z", telegram_message_id=123)
    return root, catalog_path


def tree(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def pack(source, tmp_path):
    root, catalog = source
    archive = tmp_path / "checkpoint.zip"
    receipt = pack_signal_checkpoint(root, archive, catalog=catalog, code_revision="a" * 40)
    return archive, receipt


def restore(archive, receipt, output, catalog):
    return restore_signal_checkpoint(archive, output, catalog=catalog,
        expected_sha256=receipt["archive_sha256"], expected_byte_size=receipt["archive_byte_size"])


def rewrite(archive, change):
    with zipfile.ZipFile(archive) as handle:
        entries = {info.filename: (info, handle.read(info)) for info in handle.infolist()}
    change(entries)
    with zipfile.ZipFile(archive, "w") as handle:
        for info, data in entries.values():
            handle.writestr(info, data)
    return {"archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "archive_byte_size": archive.stat().st_size}


def test_complete_bytes_and_terminal_delivery_survive_deterministic_roundtrip(source, tmp_path):
    root, catalog = source
    before = tree(root)
    archive, receipt = pack(source, tmp_path)
    second = tmp_path / "same.zip"
    assert pack_signal_checkpoint(root, second, catalog=catalog, code_revision="a" * 40) == receipt
    assert archive.read_bytes() == second.read_bytes()
    output = tmp_path / "restored"
    result = restore(archive, receipt, output, catalog)
    assert result["status"] == "restored"
    assert tree(output) == before == tree(root)
    assert read_latest_evaluation(output / MODEL, model_version_id=MODEL) == read_latest_evaluation(root / MODEL, model_version_id=MODEL)
    assert read_latest_evaluation(output / MODEL, model_version_id=MODEL)["delivery"]["status"] == "sent"
    assert "weights" not in json.dumps(receipt)
    assert "signal_date" not in json.dumps(receipt)


def test_corrections_and_their_original_receipts_remain_byte_identical(source, tmp_path):
    root, catalog = source
    ledger = root / MODEL
    original = ledger / "records/2026-08-12.json"
    correct_latest_decision(ledger_root=ledger, model_version_id=MODEL,
        signal=_signal(fingerprint="corrected", target_state=0),
        expected_record_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
        reason="Synthetic source correction", workflow_run_id="correction", commit_sha="b" * 40,
        created_at_utc="2026-08-14T00:00:00Z")
    archive, receipt = pack(source, tmp_path)
    output = tmp_path / "restored"
    restore(archive, receipt, output, catalog)
    assert tree(root) == tree(output)
    assert read_latest_evaluation(output / MODEL, model_version_id=MODEL)["delivery"]["status"] == "pending"
    assert len(list((output / MODEL / "deliveries").rglob("*.json"))) == 1


@pytest.mark.parametrize("damage", ["pin", "omitted", "traversal", "symlink", "inventory", "canonical"])
def test_untrusted_archives_fail_before_creating_a_target(source, tmp_path, damage):
    _, catalog = source
    archive, receipt = pack(source, tmp_path)
    if damage == "pin":
        receipt["archive_sha256"] = "0" * 64
    else:
        def change(entries):
            name = f"{MODEL}/latest.json"
            if damage == "omitted":
                entries.pop(name)
            elif damage == "traversal":
                info = zipfile.ZipInfo("../spill.json")
                entries[info.filename] = (info, b"{}")
            elif damage == "symlink":
                info, data = entries[name]
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                entries[name] = (info, data)
            else:
                index_info, raw = entries[INDEX]
                index = json.loads(raw)
                if damage == "inventory":
                    index["files"][0]["path"] = ["not", "a", "path"]
                else:
                    info, data = entries[name]
                    data += b" "
                    entries[name] = (info, data)
                    row = next(row for row in index["files"] if row["path"] == name)
                    row.update(sha256=hashlib.sha256(data).hexdigest(), byte_size=len(data))
                entries[INDEX] = (index_info, json.dumps(index).encode())
        receipt = rewrite(archive, change)
    output = tmp_path / "restored"
    with pytest.raises((SignalCheckpointError, StrategySignalLedgerError)):
        restore(archive, receipt, output, catalog)
    assert not output.exists()
    assert not (tmp_path / "spill.json").exists()


def test_wrong_registry_missing_model_and_existing_targets_are_not_silently_accepted(source, tmp_path):
    root, catalog = source
    archive, receipt = pack(source, tmp_path)
    other = tmp_path / "other-catalog.json"
    other.write_bytes(catalog.read_bytes() + b"\n")
    with pytest.raises(SignalCheckpointError, match="registry"):
        restore(archive, receipt, tmp_path / "restored", other)
    with pytest.raises(SignalCheckpointError, match="registry"):
        restore(archive, receipt, tmp_path / "restored", REPO / "configs/strategies/registry.json")
    with pytest.raises(SignalCheckpointError, match="exists"):
        pack_signal_checkpoint(root, archive, catalog=catalog, code_revision="a" * 40)
    with pytest.raises(SignalCheckpointError, match="fresh"):
        restore(archive, receipt, root, catalog)
    with pytest.raises(SignalCheckpointError, match="exact active registry"):
        pack_signal_checkpoint(tmp_path, tmp_path / "bad.zip", catalog=catalog, code_revision="a" * 40)


def test_expansion_limit_and_duplicate_members_fail_before_output(source, tmp_path, monkeypatch):
    _, catalog = source
    archive, receipt = pack(source, tmp_path)
    with monkeypatch.context() as limits:
        limits.setattr(checkpoints, "MAX_BYTES", archive.stat().st_size)
        with pytest.raises(SignalCheckpointError, match="expanded"):
            restore(archive, receipt, tmp_path / "restored", catalog)
    assert not (tmp_path / "restored").exists()
    with zipfile.ZipFile(archive, "a") as handle, pytest.warns(UserWarning):
        handle.writestr(INDEX, b"{}")
    receipt.update(archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), archive_byte_size=archive.stat().st_size)
    with pytest.raises(SignalCheckpointError, match="closure"):
        restore(archive, receipt, tmp_path / "restored", catalog)
    assert not (tmp_path / "restored").exists()


def test_input_drift_and_unexpected_files_cannot_be_silently_dropped(source, tmp_path, monkeypatch):
    root, catalog = source
    collect = checkpoints._collect
    calls = 0

    def changed(*args):
        nonlocal calls
        result = collect(*args)
        calls += 1
        if calls > 1:
            name = next(iter(result))
            result[name] += b" "
        return result

    with monkeypatch.context() as drift:
        drift.setattr(checkpoints, "_collect", changed)
        with pytest.raises(SignalCheckpointError, match="changed during checkpoint"):
            pack_signal_checkpoint(root, tmp_path / "bad.zip", catalog=catalog, code_revision="a" * 40)
    assert not (tmp_path / "bad.zip").exists()
    (root / MODEL / "unreviewed.json").write_text("{}")
    with pytest.raises(SignalCheckpointError, match="unexpected"):
        pack_signal_checkpoint(root, tmp_path / "bad.zip", catalog=catalog, code_revision="a" * 40)


def test_nonactive_history_is_explicitly_excluded_and_untouched(source, tmp_path):
    root, catalog = source
    history = root / "retired_model" / "records" / "2020-01-01.json"
    history.parent.mkdir(parents=True)
    history.write_bytes(b"sealed historical evidence")
    before = tree(root)
    archive, receipt = pack(source, tmp_path)
    assert receipt["scope"] == "active_registry_only"
    assert receipt["excluded_nonactive_models"] == ["retired_model"]
    output = tmp_path / "restored"
    restored = restore(archive, receipt, output, catalog)
    assert restored["excluded_nonactive_models"] == ["retired_model"]
    assert tree(output) == {name: data for name, data in before.items() if name.startswith(MODEL + "/")}
    assert tree(root) == before


@pytest.mark.parametrize("name", ["NUL.json", "CON.json", "com1.json", "LPT9.json"])
def test_windows_device_names_are_rejected_in_both_directions(source, tmp_path, name):
    _, catalog = source
    member = f"{MODEL}/deliveries/2026-08-13/{name}"
    assert not checkpoints._member(member, [MODEL])
    archive, receipt = pack(source, tmp_path)

    def add_device(entries):
        entries[member] = (zipfile.ZipInfo(member), b"{}")

    receipt = rewrite(archive, add_device)
    with pytest.raises(SignalCheckpointError, match="unsafe"):
        restore(archive, receipt, tmp_path / "restored", catalog)
    assert not (tmp_path / "restored").exists()


def test_legacy_sealed_filenames_and_ledger_readme_are_preserved(source, tmp_path):
    root, catalog = source
    legacy = root / MODEL / "records" / "2020-01-01-0123456789abcdef0123.json"
    legacy.write_bytes(b"historical sealed record")
    (root / MODEL / "README.md").write_bytes(b"ledger provenance")
    manifest_path = root / MODEL / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    manifest["record_count"] += 1
    manifest_path.write_text(json.dumps(manifest))
    archive, receipt = pack(source, tmp_path)
    output = tmp_path / "restored"
    restore(archive, receipt, output, catalog)
    assert tree(output) == tree(root)


def test_cli_requires_a_pinned_private_restore_and_emits_metadata_only(source, tmp_path, capsys):
    root, catalog = source
    output = tmp_path / "via-cli.zip"
    args = ["--root", str(REPO), "ops", "checkpoint-ledgers", "--strategy-catalog", str(catalog)]
    assert main([*args, "--ledger-root", str(root), "--output", str(output)]) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert "weights" not in json.dumps(receipt)
    restored = tmp_path / "restored"
    assert main([*args, "--restore", str(output), "--output", str(restored)]) == 2
    assert "requires an exact" in capsys.readouterr().out
    assert not restored.exists()
    assert main([*args, "--restore", str(output), "--output", str(restored),
        "--expected-sha256", receipt["archive_sha256"], "--expected-byte-size", str(receipt["archive_byte_size"])]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "restored"
    assert tree(restored) == tree(root)
    assert main([*args, "--output", "checkpoint-public.zip"]) == 2
    assert "outside the repository" in capsys.readouterr().out
    assert not (REPO / "checkpoint-public.zip").exists()


@pytest.mark.parametrize("target", ["qlib-dashboard/public/data/checkpoint.zip", "qlib-dashboard/dist/checkpoint.zip", "artifacts/private/checkpoint.zip"])
def test_cli_rejects_ignored_build_and_artifact_destinations(source, capsys, target):
    _, catalog = source
    args = ["--root", str(REPO), "ops", "checkpoint-ledgers", "--strategy-catalog", str(catalog)]
    assert main([*args, "--output", target]) == 2
    assert "outside the repository" in capsys.readouterr().out
    assert main([*args, "--restore", "not-opened.zip", "--output", target,
        "--expected-sha256", "a" * 64, "--expected-byte-size", "1"]) == 2
    assert "outside the repository" in capsys.readouterr().out
    assert not (REPO / target).exists()
