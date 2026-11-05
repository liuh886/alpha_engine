"""P2-E2 trial-matrix contract tests, without model fitting or private data."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.research.cloud_exchange import ExchangeError
from src.research.colab_experiment_batch import SCHEMA, plan, execute
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
        s["validation_folds"][1]["test_start"] = "2026-02-01"
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
