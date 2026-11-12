"""P2-E2 trial-matrix contract tests, without model fitting or private data."""
from __future__ import annotations

import json
import hashlib
import shutil
import tempfile
import unittest
import zipfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from src.research.cloud_exchange import ExchangeError
from src.research.colab_experiment_batch import (
    SCHEMA, plan, execute, checkpoint, restore, checkpoint_archive, restore_archive,
)
from src.research.study_workspace import DEFAULT_XGB_CONFIG


def spec() -> dict:
    base = DEFAULT_XGB_CONFIG.to_dict()
    base["symbols"] = "$US87"
    base["train_start"] = "2025-06-05"
    base["train_end"] = "2025-12-31"
    base["test_start"] = "2026-01-02"
    base["test_end"] = "2026-03-31"
    base["as_of_cutoff"] = "2026-11-03"
    return {
        "schema_version": SCHEMA,
        "batch_id": "us87_xgb_validation_v1",
        "runner_git_sha": "1" * 40,
        "v5_bundle_manifest_sha256": "a" * 64,
        "history_archive_sha256": "b" * 64,
        "purpose": "validation_search_only",
        "study": base,
        "validation_folds": [
            {"fold_id": "fold_a", "train_start": "2025-06-05", "train_end": "2025-12-31",
             "test_start": "2026-01-02", "test_end": "2026-03-31"},
            {"fold_id": "fold_b", "train_start": "2025-06-05", "train_end": "2026-04-30",
             "test_start": "2026-05-04", "test_end": "2026-08-31"},
        ],
        "search_space": {"max_depth": [2, 3], "learning_rate": [0.03]},
        "seeds": [42, 43],
        "max_trials": 8,
    }


def fake_study(spec_path: Path, source_root: Path, output: Path, status="ready") -> dict:
    raw = {"status": status, "research_only": True, "trade_ready": False,
           "pit_certified": False, "git_commit": "1" * 40,
           "experiment_receipt": json.loads(spec_path.read_text())}
    raw["study_hash"] = hashlib.sha256(json.dumps(
        raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    output.write_text(json.dumps(raw), encoding="utf-8")
    return {"status": status}


@pytest.fixture
def retained_trial(tmp_path):
    data = tmp_path / "data"
    pool = data / "configs/research_universes/us_selected_equities_v2.yaml"
    pool.parent.mkdir(parents=True)
    pool.write_text("symbols:\n" + "".join(f"  - S{i:03}\n" for i in range(87)))
    batch_file = tmp_path / "batch.json"
    batch_file.write_text(json.dumps(spec()))
    outputs = tmp_path / "outputs"
    with patch("src.research.colab_experiment_batch.verify_stage", return_value={
        "bundle_manifest_sha256": "a" * 64, "history_archive_sha256": "b" * 64}), patch(
        "src.research.colab_experiment_batch._git_head", return_value="1" * 40), patch(
        "src.research.study_workspace.run_study", side_effect=fake_study):
        execute(batch_spec=batch_file, data_root=data, output_root=outputs, max_new_trials=1)
        yield batch_file, data, outputs


@pytest.mark.parametrize("field,value", [
    ("batch_spec_sha256", "f" * 64), ("runner_git_sha", "2" * 40),
    ("study_status", "blocked"), ("trade_ready", True),
])
def test_resume_rejects_foreign_or_changed_trial_identity(retained_trial, field, value):
    batch_file, data, outputs = retained_trial
    receipt = next(outputs.rglob("trial-result.json"))
    raw = json.loads(receipt.read_text())
    raw[field] = value
    receipt.write_text(json.dumps(raw))
    with pytest.raises(ExchangeError, match="identity|status differs"):
        execute(batch_spec=batch_file, data_root=data, output_root=outputs,
                max_new_trials=1, resume=True)


def test_resume_rejects_altered_study_even_if_outer_hash_is_replaced(retained_trial):
    batch_file, data, outputs = retained_trial
    receipt = next(outputs.rglob("trial-result.json"))
    study = receipt.parent / "study-receipt.json"
    raw = json.loads(study.read_text())
    raw["fabricated_performance"] = 99
    study.write_text(json.dumps(raw))
    wrapper = json.loads(receipt.read_text())
    wrapper["receipt_sha256"] = hashlib.sha256(study.read_bytes()).hexdigest()
    receipt.write_text(json.dumps(wrapper))
    with pytest.raises(ExchangeError, match="study identity/hash"):
        execute(batch_spec=batch_file, data_root=data, output_root=outputs,
                max_new_trials=1, resume=True)


def test_resumed_blocked_trials_remain_in_aggregate_counts(retained_trial):
    batch_file, data, outputs = retained_trial
    with patch("src.research.study_workspace.run_study", side_effect=lambda *a, **kw: fake_study(*a, **kw, status="blocked")):
        first = execute(batch_spec=batch_file, data_root=data, output_root=outputs,
                        max_new_trials=1, resume=True)
    assert first["blocked_trials"] == 1
    second = execute(batch_spec=batch_file, data_root=data, output_root=outputs,
                     max_new_trials=1, resume=True)
    assert second["resumed_trials"] == 2 and second["blocked_trials"] == 1


def test_completed_study_recovers_after_interruption_before_wrapper(retained_trial):
    batch_file, data, outputs = retained_trial
    result = next(outputs.rglob("trial-result.json"))
    study = result.parent / "study-receipt.json"
    original = study.read_bytes()
    result.unlink()  # Simulate VM termination after atomic study retention.
    with patch("src.research.study_workspace.run_study", side_effect=fake_study) as fitter:
        recovered = execute(batch_spec=batch_file, data_root=data, output_root=outputs,
                            resume=True, max_new_trials=1)
    assert fitter.call_count == 1  # Only the next trial is fitted.
    assert study.read_bytes() == original
    assert recovered["recovered_completed_trials"] == 1
    assert recovered["resumed_trials"] == 1 and recovered["new_trials"] == 1


def test_private_checkpoint_restores_to_fresh_session_and_resumes(retained_trial, tmp_path):
    batch_file, data, outputs = retained_trial
    saved = tmp_path / "checkpoint"
    pin = checkpoint(batch_spec=batch_file, data_root=data, output_root=outputs, destination=saved)
    fresh = tmp_path / "fresh-session"
    got = restore(batch_spec=batch_file, data_root=data, checkpoint_root=saved,
                  expected_index_sha256=pin["index_sha256"], output_root=fresh)
    assert got["files"] == 4
    resumed = execute(batch_spec=batch_file, data_root=data, output_root=fresh,
                      resume=True, max_new_trials=1)
    assert resumed["resumed_trials"] == 1 and resumed["new_trials"] == 1
    original = next(outputs.rglob("study-receipt.json"))
    assert original.read_bytes() == (fresh / original.relative_to(outputs)).read_bytes()


@pytest.mark.parametrize("field,value", [
    ("runner_git_sha", "2" * 40), ("history_archive_sha256", "f" * 64),
    ("review_status", "accepted"),
])
def test_checkpoint_rejects_changed_identity_before_copy(retained_trial, tmp_path, field, value):
    batch_file, data, outputs = retained_trial
    saved = tmp_path / "checkpoint"
    checkpoint(batch_spec=batch_file, data_root=data, output_root=outputs, destination=saved)
    index = saved / "checkpoint-index.json"
    changed = json.loads(index.read_text())
    changed[field] = value
    index.write_text(json.dumps(changed))
    with pytest.raises(ExchangeError, match="source/batch/runner"):
        restore(batch_spec=batch_file, data_root=data, checkpoint_root=saved,
                expected_index_sha256=hashlib.sha256(index.read_bytes()).hexdigest(),
                output_root=tmp_path / "fresh")
    assert not (tmp_path / "fresh").exists()


def test_checkpoint_refuses_raw_data_and_unlisted_files(retained_trial, tmp_path):
    batch_file, data, outputs = retained_trial
    (outputs / "raw-prices.csv").write_text("unexpected market data")
    with pytest.raises(ExchangeError, match="unexpected file"):
        checkpoint(batch_spec=batch_file, data_root=data, output_root=outputs,
                   destination=tmp_path / "checkpoint")
    assert not (tmp_path / "checkpoint").exists()


def test_checkpoint_requires_independent_pin_and_refuses_overwrite(retained_trial, tmp_path):
    batch_file, data, outputs = retained_trial
    saved = tmp_path / "checkpoint"
    pin = checkpoint(batch_spec=batch_file, data_root=data, output_root=outputs, destination=saved)
    with pytest.raises(ExchangeError, match="fresh"):
        checkpoint(batch_spec=batch_file, data_root=data, output_root=outputs, destination=saved)
    with pytest.raises(ExchangeError, match="independently pinned"):
        restore(batch_spec=batch_file, data_root=data, checkpoint_root=saved,
                expected_index_sha256="f" * 64, output_root=tmp_path / "fresh")
    assert not (tmp_path / "fresh").exists()
    assert hashlib.sha256((saved / "checkpoint-index.json").read_bytes()).hexdigest() == pin["index_sha256"]


def test_checkpoint_refuses_tampered_inner_file_before_copy(retained_trial, tmp_path):
    batch_file, data, outputs = retained_trial
    saved = tmp_path / "checkpoint"
    pin = checkpoint(batch_spec=batch_file, data_root=data, output_root=outputs, destination=saved)
    next(saved.rglob("study-receipt.json")).write_text('{"status":"ready"}')
    with pytest.raises(ExchangeError):
        restore(batch_spec=batch_file, data_root=data, checkpoint_root=saved,
                expected_index_sha256=pin["index_sha256"], output_root=tmp_path / "fresh")
    assert not (tmp_path / "fresh").exists()


def test_failed_model_attempts_are_retained_and_stop_after_failure_budget(retained_trial):
    batch_file, data, outputs = retained_trial
    with patch("src.research.study_workspace.run_study", side_effect=ValueError("declared candidate fit failed")):
        result = execute(batch_spec=batch_file, data_root=data, output_root=outputs,
                         resume=True, max_new_trials=7)
    assert result["resumed_trials"] == 1 and result["blocked_trials"] == 3
    assert result["stop_reason"] == "consecutive_model_failure_budget"
    assert len(list(outputs.rglob("trial-result.json"))) == 4
    failed = [json.loads(p.read_text()) for p in outputs.rglob("study-receipt.json")
              if json.loads(p.read_text())["status"] == "blocked"]
    assert all(r["blocked_reasons"][0]["code"] == "model_execution_failed" for r in failed)


def test_wall_time_budget_stops_starting_new_trials_and_preserves_prior_results(retained_trial):
    batch_file, data, outputs = retained_trial
    with patch("src.research.colab_experiment_batch.time.perf_counter", side_effect=[0, 2, 2, 2, 2, 2, 2, 2, 2]):
        result = execute(batch_spec=batch_file, data_root=data, output_root=outputs,
                         resume=True, max_new_trials=7, max_wall_seconds=1)
    assert result["new_trials"] == 0 and result["resumed_trials"] == 1
    assert result["stop_reason"] == "wall_time_start_budget"


def test_archive_checkpoint_roundtrip_skips_retained_fit(retained_trial, tmp_path):
    batch_file, data, outputs = retained_trial
    archive = tmp_path / "transport.zip"
    pin = checkpoint_archive(batch_spec=batch_file, data_root=data, output_root=outputs, archive=archive)
    fresh = tmp_path / "fresh"
    restored = restore_archive(batch_spec=batch_file, data_root=data, archive=archive,
        expected_archive_sha256=pin["archive_sha256"], expected_index_sha256=pin["index_sha256"], output_root=fresh)
    assert restored["files"] == pin["files"]
    for path in outputs.rglob("*"):
        if path.is_file():
            assert path.read_bytes() == (fresh / path.relative_to(outputs)).read_bytes()
    with patch("src.research.study_workspace.run_study", side_effect=fake_study) as fitter:
        result = execute(batch_spec=batch_file, data_root=data, output_root=fresh, resume=True, max_new_trials=1)
    assert result["resumed_trials"] == 1 and fitter.call_count == 1


@pytest.mark.parametrize("mutation", ["archive_pin", "index_pin", "traversal", "inner_receipt", "extra_file"])
def test_archive_checkpoint_rejects_tampering_before_restore(retained_trial, tmp_path, mutation):
    batch_file, data, outputs = retained_trial
    archive = tmp_path / "transport.zip"
    pin = checkpoint_archive(batch_spec=batch_file, data_root=data, output_root=outputs, archive=archive)
    if mutation in ("traversal", "extra_file"):
        with zipfile.ZipFile(archive, "a") as pack:
            pack.writestr("../escape.json" if mutation == "traversal" else "extra.json", "{}")
    if mutation == "inner_receipt":
        with zipfile.ZipFile(archive) as pack:
            members = {i.filename: pack.read(i.filename) for i in pack.infolist()}
        key = next(k for k in members if k.endswith("study-receipt.json"))
        members[key] = b'{}'
        with zipfile.ZipFile(archive, "w") as pack:
            for name, data_bytes in members.items():
                pack.writestr(name, data_bytes)
    archive_pin = "f" * 64 if mutation == "archive_pin" else hashlib.sha256(archive.read_bytes()).hexdigest()
    index_pin = "f" * 64 if mutation == "index_pin" else pin["index_sha256"]
    fresh = tmp_path / "fresh"
    with pytest.raises(ExchangeError):
        restore_archive(batch_spec=batch_file, data_root=data, archive=archive,
            expected_archive_sha256=archive_pin, expected_index_sha256=index_pin, output_root=fresh)
    assert not fresh.exists() and not (tmp_path / "escape.json").exists()


class BatchPlanningTests(unittest.TestCase):
    def test_stable_full_scope_plan(self) -> None:
        first = plan(spec())
        self.assertEqual(first, plan(spec()))
        self.assertEqual(first["trial_count"], 8)
        self.assertEqual(len({t["trial_id"] for t in first["trials"]}), 8)
        self.assertEqual(first["role"], "validation_search_only")
        self.assertTrue(all(t["study"]["symbols"] == "$US87" for t in first["trials"]))
        self.assertTrue(all(not first[key] for key in ("trade_ready", "pit_certified")))

    def test_reject_hidden_pool_narrowing(self) -> None:
        s = spec()
        s["study"]["symbols"] = ["AAPL", "MSFT"]
        with self.assertRaisesRegex(ExchangeError, "full US87"):
            plan(s)

    def test_reject_stale_or_unfrozen_revision(self) -> None:
        s = spec()
        s["runner_git_sha"] = "main"
        with self.assertRaisesRegex(ExchangeError, "exact experiment runner SHA"):
            plan(s)

    def test_reject_trial_budget_overrun(self) -> None:
        s = spec()
        s["max_trials"] = 7
        with self.assertRaisesRegex(ExchangeError, "exceeds max_trials"):
            plan(s)

    def test_reject_validation_overlap(self) -> None:
        s = spec()
        s["validation_folds"][1]["train_end"] = "2026-02-28"
        s["validation_folds"][1]["test_start"] = "2026-03-01"
        with self.assertRaisesRegex(ExchangeError, "validation windows overlap"):
            plan(s)

    def test_reject_lookahead_cutoff(self) -> None:
        s = spec()
        s["validation_folds"][1]["test_end"] = "2026-11-04"
        with self.assertRaisesRegex(ExchangeError, "out-of-range"):
            plan(s)

    def test_reject_final_holdout_optimization(self) -> None:
        s = spec()
        s["purpose"] = "tune_final_test"
        with self.assertRaisesRegex(ExchangeError, "validation search"):
            plan(s)

    def test_reject_unsupported_estimator_param(self) -> None:
        s = spec()
        s["search_space"]["n_estimators"] = [100]
        with self.assertRaisesRegex(ExchangeError, "unsupported search"):
            plan(s)

    def test_reject_unfrozen_dataset_root(self) -> None:
        with patch("src.research.colab_experiment_batch.verify_stage",
                   return_value={"bundle_manifest_sha256": "f" * 64,
                                 "history_archive_sha256": "b" * 64}):
            with self.assertRaisesRegex(ExchangeError, "differs"):
                plan(spec(), Path("/private/data-root"))

    def test_no_model_exec_on_plan(self) -> None:
        with patch("src.research.study_workspace.run_study", side_effect=AssertionError):
            self.assertEqual(plan(spec())["trial_count"], 8)

    def test_checkpoint_chunk_resume_avoids_rerunning_previous_trials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "isolated"
            pool = data / "configs/research_universes/us_selected_equities_v2.yaml"
            pool.parent.mkdir(parents=True)
            pool.write_text(
                "symbols:\n" + "".join(f"  - S{i:03}\n" for i in range(87)),
                encoding="utf-8")
            batch_file = root / "batch.json"
            batch_file.write_text(json.dumps(spec()), encoding="utf-8")
            calls: list[str] = []

            def fake_run(spec_path: Path, source_root: Path, output: Path) -> dict:
                calls.append(spec_path.parent.name)
                return fake_study(spec_path, source_root, output)

            with patch("src.research.colab_experiment_batch.verify_stage",
                       return_value={"bundle_manifest_sha256": "a" * 64,
                                     "history_archive_sha256": "b" * 64}), patch(
                       "src.research.colab_experiment_batch._git_head", return_value="1" * 40
                       ), patch("src.research.study_workspace.run_study", side_effect=fake_run):
                first = execute(batch_spec=batch_file, data_root=data,
                                output_root=root / "outputs", max_new_trials=2)
                self.assertEqual(first["status"], "BATCH_PARTIAL_CHECKPOINT_READY")
                self.assertEqual(first["new_trials"], 2)
                self.assertEqual(first["pending_trials"], 6)
                second = execute(batch_spec=batch_file, data_root=data,
                                 output_root=root / "outputs",
                                 max_new_trials=6, resume=True)
                self.assertEqual(second["status"], "BATCH_EXECUTED_RESEARCH_ONLY")
                self.assertEqual(second["resumed_trials"], 2)
                self.assertEqual(second["new_trials"], 6)
                self.assertEqual(len(calls), 8)

    def test_study_run_refuses_wrong_checkout_before_fitting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            batch_path = root / "batch.json"
            batch_path.write_text(json.dumps(spec()), encoding="utf-8")
            with patch("src.research.colab_experiment_batch.verify_stage",
                       return_value={"bundle_manifest_sha256": "a" * 64,
                                     "history_archive_sha256": "b" * 64}), patch(
                       "src.research.colab_experiment_batch._git_head", return_value="2" * 40):
                with self.assertRaisesRegex(ExchangeError, "revision mismatch"):
                    execute(batch_spec=batch_path, data_root=root / "data",
                            output_root=root / "results")


if __name__ == "__main__":
    unittest.main()


# Campaign Sharding: independent Colab windows, not intra-VM multiprocessing.

def test_shard_manifest_is_total_disjoint_and_deterministic():
    from src.research.colab_campaign_shards import compile_shards, assigned_trial_ids

    batch = plan(spec())
    manifest = compile_shards(batch, 3)
    assert manifest == compile_shards(batch, 3)
    actual = [tid for s in manifest["shards"] for tid in s["trial_ids"]]
    assert len(actual) == batch["trial_count"] == len(set(actual))
    assert set(actual) == {t["trial_id"] for t in batch["trials"]}
    for shard in manifest["shards"]:
        got = assigned_trial_ids(manifest, batch, shard["shard_id"])
        assert got == set(shard["trial_ids"])
        assert shard["trial_count"] == len(got)
    assert [s["trial_count"] for s in manifest["shards"]] == [3, 3, 2]


def test_shard_rejects_changed_identity_duplicate_and_unknown_id():
    from src.research.colab_campaign_shards import compile_shards, assigned_trial_ids

    batch = plan(spec())
    manifest = compile_shards(batch, 2)
    with pytest.raises(ExchangeError, match="unknown shard"):
        assigned_trial_ids(manifest, batch, "s03")
    tampered = json.loads(json.dumps(manifest))
    tampered["shards"][1]["trial_ids"][0] = tampered["shards"][0]["trial_ids"][0]
    with pytest.raises(ExchangeError, match="frozen shard"):
        assigned_trial_ids(tampered, batch, "s02")
    modified_batch = json.loads(json.dumps(batch))
    modified_batch["runner_git_sha"] = "2" * 40
    with pytest.raises(ExchangeError, match="frozen shard"):
        assigned_trial_ids(manifest, modified_batch, "s01")
    with pytest.raises(ExchangeError, match="shard count"):
        compile_shards(batch, batch["trial_count"] + 1)


def test_shard_trial_runner_preserves_disjoint_outputs_and_resume(retained_trial, tmp_path):
    from src.research.colab_campaign_shards import compile_shards

    batch_file, data, _ = retained_trial
    batch = plan(json.loads(batch_file.read_text()))
    manifest = compile_shards(batch, 2)
    path = tmp_path / "shards.json"
    path.write_text(json.dumps(manifest))
    written = []
    for shard_id in ("s01", "s02"):
        outputs = tmp_path / shard_id / "runs"
        with patch("src.research.colab_experiment_batch.verify_stage", return_value={
            "bundle_manifest_sha256": "a" * 64, "history_archive_sha256": "b" * 64
        }), patch("src.research.colab_experiment_batch._git_head", return_value="1" * 40), patch(
            "src.research.study_workspace.run_study", side_effect=fake_study
        ) as fit:
            first = execute(
                batch_spec=batch_file, data_root=data, output_root=outputs,
                shard_manifest=path, shard_id=shard_id, max_new_trials=1
            )
            assert first["new_trials"] == 1 and first["campaign_trials"] == 8
            second = execute(
                batch_spec=batch_file, data_root=data, output_root=outputs,
                shard_manifest=path, shard_id=shard_id, max_new_trials=100,
                resume=True
            )
            assert second["pending_trials"] == 0 and fit.call_count == 4
            assert second["shard_id"] == shard_id and second["trials"] == 4
        ids = {p.parent.name for p in outputs.rglob("trial-result.json")}
        assert ids == set(manifest["shards"][int(shard_id[-2:])-1]["trial_ids"])
        written.append(ids)
    assert written[0].isdisjoint(written[1])


def test_shard_runner_fails_closed_on_shared_output_and_foreign_receipts(
    retained_trial, tmp_path
):
    from src.research.colab_campaign_shards import compile_shards

    batch_file, data, _ = retained_trial
    manifest = compile_shards(plan(json.loads(batch_file.read_text())), 2)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ExchangeError, match="namespaced"):
        execute(
            batch_spec=batch_file, data_root=data, output_root=tmp_path / "shared",
            shard_manifest=path, shard_id="s01", max_new_trials=1
        )
    outputs = tmp_path / "s01" / "runs"
    alien = outputs / spec()["batch_id"] / "trials" / manifest["shards"][1]["trial_ids"][0]
    alien.mkdir(parents=True)
    with patch("src.research.colab_experiment_batch.verify_stage", return_value={
        "bundle_manifest_sha256": "a" * 64, "history_archive_sha256": "b" * 64
    }), patch("src.research.colab_experiment_batch._git_head", return_value="1" * 40):
        with pytest.raises(ExchangeError, match="foreign shard"):
            execute(
                batch_spec=batch_file, data_root=data, output_root=outputs,
                shard_manifest=path, shard_id="s01", max_new_trials=1,
                resume=True
            )


# Cross-window merge of independently transported shard ZIPs. The merger must
# accept only complete, assigned, pinned shard payloads and seal one unreviewed
# evidence set without ranking winners or touching the input ZIPs.

@contextmanager
def _merge_stage(data, run=fake_study):
    with patch("src.research.colab_experiment_batch.verify_stage", return_value={
            "bundle_manifest_sha256": "a" * 64,
            "history_archive_sha256": "b" * 64}), patch(
            "src.research.colab_experiment_batch._git_head", return_value="1" * 40), patch(
            "src.research.study_workspace.run_study", side_effect=run):
        yield


def _merge_batch(tmp_path):
    from src.research.colab_campaign_shards import compile_shards

    data = tmp_path / "data"
    pool = data / "configs/research_universes/us_selected_equities_v2.yaml"
    pool.parent.mkdir(parents=True)
    pool.write_text("symbols:\n" + "".join(f"  - S{i:03}\n" for i in range(87)))
    batch_file = tmp_path / "batch.json"
    batch_file.write_text(json.dumps(spec()))
    batch = plan(json.loads(batch_file.read_text()))
    manifest = compile_shards(batch, 2)
    manifest_file = tmp_path / "shards.json"
    manifest_file.write_text(json.dumps(manifest))
    return batch_file, data, batch, manifest, manifest_file


def _run_shard(batch_file, data, outputs, manifest_file, shard_id,
               *, run=fake_study, limit=100):
    with _merge_stage(data, run):
        return execute(batch_spec=batch_file, data_root=data, output_root=outputs,
                       shard_manifest=manifest_file, shard_id=shard_id,
                       max_new_trials=limit)


def _seal_shard(batch_file, data, outputs, archive):
    with _merge_stage(data):
        saved = checkpoint_archive(
            batch_spec=batch_file, data_root=data, output_root=outputs, archive=archive)
    return {"archive": str(archive), "archive_sha256": saved["archive_sha256"],
            "index_sha256": saved["index_sha256"]}


def _build_shard_pins(batch_file, data, manifest_file, root, *, run=fake_study,
                      limits=None):
    pins, outputs = {}, {}
    for shard_id in ("s01", "s02"):
        out = root / shard_id / "runs"
        _run_shard(batch_file, data, out, manifest_file, shard_id, run=run,
                   limit=(limits or {}).get(shard_id, 100))
        pins[shard_id] = _seal_shard(batch_file, data, out, root / f"{shard_id}.zip")
        outputs[shard_id] = out
    return pins, outputs


def _tree_bytes(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def test_merge_complete_shards_matches_single_window_evidence(tmp_path):
    from src.research.colab_campaign_shards import merge_shards

    batch_file, data, batch, manifest, manifest_file = _merge_batch(tmp_path)
    single = tmp_path / "single"
    with _merge_stage(data):
        execute(batch_spec=batch_file, data_root=data, output_root=single, max_new_trials=100)
    pins, _outputs = _build_shard_pins(batch_file, data, manifest_file, tmp_path)

    merged_root = tmp_path / "merged"
    merged_archive = tmp_path / "merged.zip"
    with _merge_stage(data):
        result = merge_shards(
            batch_spec=batch_file, data_root=data, manifest=manifest,
            shard_pins=pins, output_root=merged_root, archive=merged_archive)

    assert result["status"] == "SHARD_MERGE_SEALED_UNREVIEWED"
    assert result["shard_count"] == 2 and result["trial_count"] == 8
    assert result["ready"] == 8 and result["blocked"] == 0
    assert result["research_only"] is True and result["trade_ready"] is False
    assert result["pit_certified"] is False
    assert result["review_status"] == "incoming_unreviewed"
    assert result["ranking_performed"] is False and result["winner_claimed"] is False
    assert result["archive_sha256"] == hashlib.sha256(merged_archive.read_bytes()).hexdigest()

    expected, actual = _tree_bytes(single), _tree_bytes(merged_root)
    assert set(actual) == set(expected)
    for name in sorted(expected):
        if name.endswith("trial-result.json"):
            left, right = json.loads(expected[name]), json.loads(actual[name])
            left.pop("elapsed_seconds")
            right.pop("elapsed_seconds")
            assert left == right
        else:
            assert actual[name] == expected[name]

    restored = tmp_path / "restored"
    with _merge_stage(data):
        got = restore_archive(
            batch_spec=batch_file, data_root=data, archive=merged_archive,
            expected_archive_sha256=result["archive_sha256"],
            expected_index_sha256=result["index_sha256"], output_root=restored)
    assert got["files"] == result["index_files"] == len(expected)
    assert _tree_bytes(restored) == actual


def test_merge_refuses_missing_pin_and_incomplete_shard(tmp_path):
    from src.research.colab_campaign_shards import ShardMergeError, merge_shards

    batch_file, data, batch, manifest, manifest_file = _merge_batch(tmp_path)
    pins, _outputs = _build_shard_pins(batch_file, data, manifest_file, tmp_path)

    tampered_manifest = json.loads(json.dumps(manifest))
    tampered_manifest["shards"][0]["trial_ids"][0] = tampered_manifest["shards"][1]["trial_ids"][0]
    with _merge_stage(data):
        with pytest.raises(ShardMergeError, match="canonical batch plan"):
            merge_shards(
                batch_spec=batch_file, data_root=data, manifest=tampered_manifest,
                shard_pins=pins, output_root=tmp_path / "manifest-merged",
                archive=tmp_path / "manifest-merged.zip")
    assert not (tmp_path / "manifest-merged").exists()

    with _merge_stage(data):
        with pytest.raises(ShardMergeError, match="pins must exactly cover"):
            merge_shards(
                batch_spec=batch_file, data_root=data, manifest=manifest,
                shard_pins={"s01": pins["s01"]}, output_root=tmp_path / "missing-pin",
                archive=tmp_path / "missing-pin.zip")
    assert not (tmp_path / "missing-pin").exists()
    assert not (tmp_path / "missing-pin.zip").exists()

    chunk = tmp_path / "chunk" / "s01" / "runs"
    _run_shard(batch_file, data, chunk, manifest_file, "s01", limit=1)
    chunk_pin = _seal_shard(batch_file, data, chunk, tmp_path / "chunk-s01.zip")
    with _merge_stage(data):
        with pytest.raises(ShardMergeError, match="assignment mismatch"):
            merge_shards(
                batch_spec=batch_file, data_root=data, manifest=manifest,
                shard_pins={"s01": chunk_pin, "s02": pins["s02"]},
                output_root=tmp_path / "chunk-merged",
                archive=tmp_path / "chunk-merged.zip")
    assert not (tmp_path / "chunk-merged").exists()

    partial = tmp_path / "partial" / "s01" / "runs"
    _run_shard(batch_file, data, partial, manifest_file, "s01")
    trial_id = manifest["shards"][0]["trial_ids"][0]
    (partial / batch["batch_id"] / "trials" / trial_id / "trial-result.json").unlink()
    partial_pin = _seal_shard(batch_file, data, partial, tmp_path / "partial-s01.zip")
    with _merge_stage(data):
        with pytest.raises(ShardMergeError, match="incomplete shard trial evidence"):
            merge_shards(
                batch_spec=batch_file, data_root=data, manifest=manifest,
                shard_pins={"s01": partial_pin, "s02": pins["s02"]},
                output_root=tmp_path / "partial-merged",
                archive=tmp_path / "partial-merged.zip")
    assert not (tmp_path / "partial-merged").exists()


def test_merge_refuses_foreign_and_duplicate_trials(tmp_path):
    from src.research.colab_campaign_shards import ShardMergeError, merge_shards

    batch_file, data, batch, manifest, manifest_file = _merge_batch(tmp_path)
    pins, outputs = _build_shard_pins(batch_file, data, manifest_file, tmp_path)

    foreign_root = tmp_path / "foreign" / "s01" / "runs"
    _run_shard(batch_file, data, foreign_root, manifest_file, "s01")
    foreign_trial = manifest["shards"][1]["trial_ids"][0]
    shutil.copytree(
        outputs["s02"] / batch["batch_id"] / "trials" / foreign_trial,
        foreign_root / batch["batch_id"] / "trials" / foreign_trial)
    foreign_pin = _seal_shard(batch_file, data, foreign_root, tmp_path / "foreign-s01.zip")
    with _merge_stage(data):
        with pytest.raises(ShardMergeError, match="assignment mismatch"):
            merge_shards(
                batch_spec=batch_file, data_root=data, manifest=manifest,
                shard_pins={"s01": foreign_pin, "s02": pins["s02"]},
                output_root=tmp_path / "foreign-merged",
                archive=tmp_path / "foreign-merged.zip")
    assert not (tmp_path / "foreign-merged").exists()

    duplicate = tmp_path / "duplicate-s01.zip"
    with zipfile.ZipFile(tmp_path / "s01.zip") as pack:
        entries = [(info.filename, pack.read(info.filename)) for info in pack.infolist()]
    with zipfile.ZipFile(duplicate, "w", compression=zipfile.ZIP_DEFLATED) as pack:
        for name, body in entries:
            pack.writestr(name, body)
        name, body = next(entry for entry in entries
                          if entry[0].endswith("study-receipt.json"))
        with pytest.warns(UserWarning, match="Duplicate name"):
            pack.writestr(name, body)
    duplicate_pin = {"archive": str(duplicate),
                     "archive_sha256": hashlib.sha256(duplicate.read_bytes()).hexdigest(),
                     "index_sha256": pins["s01"]["index_sha256"]}
    with _merge_stage(data):
        with pytest.raises(ExchangeError, match="member budget"):
            merge_shards(
                batch_spec=batch_file, data_root=data, manifest=manifest,
                shard_pins={"s01": duplicate_pin, "s02": pins["s02"]},
                output_root=tmp_path / "duplicate-merged",
                archive=tmp_path / "duplicate-merged.zip")

    with _merge_stage(data):
        with pytest.raises(ShardMergeError, match="assignment mismatch"):
            merge_shards(
                batch_spec=batch_file, data_root=data, manifest=manifest,
                shard_pins={"s01": pins["s01"], "s02": pins["s01"]},
                output_root=tmp_path / "reused-merged",
                archive=tmp_path / "reused-merged.zip")
    assert not (tmp_path / "reused-merged").exists()


def test_merge_refuses_tampered_transport_and_preserves_inputs(tmp_path):
    from src.research.colab_campaign_shards import merge_shards

    batch_file, data, batch, manifest, manifest_file = _merge_batch(tmp_path)
    pins, _outputs = _build_shard_pins(batch_file, data, manifest_file, tmp_path)
    originals = {shard_id: (tmp_path / f"{shard_id}.zip").read_bytes() for shard_id in pins}

    tampered = tmp_path / "tampered-s01.zip"
    shutil.copyfile(tmp_path / "s01.zip", tampered)
    tampered.write_bytes(tampered.read_bytes() + b"tampered")
    tampered_pins = {"s01": {**pins["s01"], "archive": str(tampered)}, "s02": pins["s02"]}
    with _merge_stage(data):
        with pytest.raises(ExchangeError, match="pin/size"):
            merge_shards(
                batch_spec=batch_file, data_root=data, manifest=manifest,
                shard_pins=tampered_pins, output_root=tmp_path / "tampered-merged",
                archive=tmp_path / "tampered-merged.zip")
    assert not (tmp_path / "tampered-merged").exists()

    wrong_pins = {"s01": pins["s01"],
                  "s02": {**pins["s02"], "index_sha256": "f" * 64}}
    with _merge_stage(data):
        with pytest.raises(ExchangeError, match="index SHA"):
            merge_shards(
                batch_spec=batch_file, data_root=data, manifest=manifest,
                shard_pins=wrong_pins, output_root=tmp_path / "wrong-index-merged",
                archive=tmp_path / "wrong-index-merged.zip")
    assert not (tmp_path / "wrong-index-merged").exists()

    for shard_id, content in originals.items():
        assert (tmp_path / f"{shard_id}.zip").read_bytes() == content
    assert not (tmp_path / "tampered-merged.zip").exists()
    assert not (tmp_path / "wrong-index-merged.zip").exists()


def test_merge_refuses_existing_outputs_and_reports_flags(tmp_path):
    from src.research.colab_campaign_shards import ShardMergeError, merge_shards

    batch_file, data, batch, manifest, manifest_file = _merge_batch(tmp_path)

    def blocked_first(trial_id):
        def run(spec_path, source_root, output):
            status = "blocked" if spec_path.parent.name == trial_id else "ready"
            return fake_study(spec_path, source_root, output, status)
        return run

    blocked_trial = manifest["shards"][0]["trial_ids"][0]
    pins, _outputs = _build_shard_pins(
        batch_file, data, manifest_file, tmp_path / "blocked",
        run=blocked_first(blocked_trial))

    existing_root = tmp_path / "existing-root"
    existing_root.mkdir()
    with _merge_stage(data):
        with pytest.raises(ShardMergeError, match="fresh"):
            merge_shards(
                batch_spec=batch_file, data_root=data, manifest=manifest,
                shard_pins=pins, output_root=existing_root,
                archive=tmp_path / "existing.zip")
    existing_archive = tmp_path / "existing.zip"
    existing_archive.write_bytes(b"occupied")
    with _merge_stage(data):
        with pytest.raises(ShardMergeError, match="fresh"):
            merge_shards(
                batch_spec=batch_file, data_root=data, manifest=manifest,
                shard_pins=pins, output_root=tmp_path / "fresh-root",
                archive=existing_archive)
    assert not (tmp_path / "fresh-root").exists()
    with _merge_stage(data):
        with pytest.raises(ShardMergeError, match="outside"):
            merge_shards(
                batch_spec=batch_file, data_root=data, manifest=manifest,
                shard_pins=pins, output_root=tmp_path / "nested",
                archive=tmp_path / "nested" / "merged.zip")
    assert not (tmp_path / "nested").exists()

    merged_root = tmp_path / "merged"
    merged_archive = tmp_path / "merged.zip"
    with _merge_stage(data):
        result = merge_shards(
            batch_spec=batch_file, data_root=data, manifest=manifest,
            shard_pins=pins, output_root=merged_root, archive=merged_archive)
    assert result["ready"] == 7 and result["blocked"] == 1
    assert result["trial_count"] == 8
    assert result["review_status"] == "incoming_unreviewed"
    assert result["research_only"] is True and result["trade_ready"] is False
    assert result["pit_certified"] is False
    assert result["ranking_performed"] is False and result["winner_claimed"] is False


def test_merge_cli_exit_zero_and_blocked_exit_ten(tmp_path, capsys):
    from src.research.colab_campaign_shards import main as shard_main

    batch_file, data, batch, manifest, manifest_file = _merge_batch(tmp_path)
    pins, _outputs = _build_shard_pins(batch_file, data, manifest_file, tmp_path)
    pins_file = tmp_path / "pins.json"
    pins_file.write_text(json.dumps(pins))

    with _merge_stage(data):
        code = shard_main([
            "merge", "--batch-spec", str(batch_file), "--manifest", str(manifest_file),
            "--data-root", str(data), "--shard-pins", str(pins_file),
            "--output-root", str(tmp_path / "cli-merged"),
            "--archive", str(tmp_path / "cli-merged.zip")])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "SHARD_MERGE_SEALED_UNREVIEWED"
    assert payload["ready"] == 8 and payload["blocked"] == 0
    assert payload["trade_ready"] is False

    blocked_pins = tmp_path / "blocked-pins.json"
    blocked_pins.write_text(json.dumps({"s01": pins["s01"]}))
    with _merge_stage(data):
        code = shard_main([
            "merge", "--batch-spec", str(batch_file), "--manifest", str(manifest_file),
            "--data-root", str(data), "--shard-pins", str(blocked_pins),
            "--output-root", str(tmp_path / "cli-blocked"),
            "--archive", str(tmp_path / "cli-blocked.zip")])
    assert code == 10
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "BLOCKED_SHARD_CONTRACT: " in captured.err
    assert "pins must exactly cover" in captured.err
    assert not (tmp_path / "cli-blocked").exists()
    assert not (tmp_path / "cli-blocked.zip").exists()

