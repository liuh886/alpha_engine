"""P2-E2 trial-matrix contract tests, without model fitting or private data."""
from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from src.research.cloud_exchange import ExchangeError
from src.research.colab_experiment_batch import SCHEMA, plan, execute, checkpoint, restore
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
