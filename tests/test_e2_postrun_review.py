"""Offline receipts review: the selected model must be compared on matched folds."""
from __future__ import annotations

import hashlib
import json
import zipfile

import pytest

from src.research.e2_postrun_review import ReviewError, review


def _serial(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha(value):
    return hashlib.sha256(value).hexdigest()


def _fixture(tmp_path, *, corrupt=False):
    batch_id = "research-v2-fixture"
    runner = "a" * 40
    trials = []
    entries = {}
    for model in ("rule", "model"):
        for seed in (17, 42):
            tid = f"{model}-fold_a-{seed}"
            trials.append({"trial_id": tid, "configuration_id": model,
                           "fold_id": "fold_a", "seed": seed})
            base = f"{batch_id}/trials/{tid}/"
            value = 0.2 if model == "rule" else 0.25
            receipt = {"status": "ready", "git_commit": runner, "pit_certified": False,
                       "trade_ready": False, "research_only": True,
                       "overall_oos_net_excess_return": value,
                       "overall_oos_max_drawdown": -0.1,
                       "rank_ic": 0.05, "oos_sessions_count": 10,
                       "overall_benchmark_cumulative_return": 0.05,
                       "experiment_receipt": {"test_start": "2026-01-01",
                                              "test_end": "2026-01-20"}}
            raw = _serial(receipt)
            entries[base + "study-receipt.json"] = raw
            entries[base + "trial-result.json"] = _serial({
                "study_status": "ready", "runner_git_sha": runner,
                "receipt_sha256": _sha(raw), "elapsed_seconds": 2.0})
            entries[base + "study-spec.json"] = _serial({"xgb_params": {"seed": seed}})
    plan = {"batch_id": batch_id, "run_id": "run123", "runner_git_sha": runner,
            "trial_count": len(trials), "trials": trials}
    entries[f"{batch_id}/batch-plan.json"] = _serial(plan)
    index = {"batch_id": batch_id, "runner_git_sha": runner,
             "research_only": True, "trade_ready": False,
             "history_archive_sha256": "b" * 64,
             "files": [{"path": k, "sha256": _sha(v), "size": len(v)}
                       for k, v in sorted(entries.items())]}
    report = {"schema_version": "p2_e2_validation_comparison_v1",
              "run_id": "run123",
              "validation_ranking": ["model"],
              "configurations": []}
    for name, phase, value in (("rule", "baseline", 0.2), ("model", "search", 0.25)):
        report["configurations"].append({
            "configuration_id": name, "candidate_id": name,
            "model_family": "momentum_20d" if name == "rule" else "xgboost",
            "phase": phase, "ready_tasks": 2, "planned_tasks": 2, "complete": True,
            "median_validation_net_excess": value,
            "seed_repetitions_identical": True,
            "fold_diagnostics": [{"fold_id": "fold_a", "ready_seeds": 2,
                                  "median_net_excess": value, "worst_drawdown": -0.1,
                                  "distinct_performance_vectors": 1}]})
    path = tmp_path / "checkpoint.zip"
    with zipfile.ZipFile(path, "w") as z:
        for name, raw in entries.items():
            z.writestr(name, raw if not corrupt or not name.endswith("study-receipt.json")
                       else raw + b"tampered")
        z.writestr("checkpoint-index.json", _serial(index))
    compare = tmp_path / "comparison.json"
    compare.write_text(json.dumps(report))
    return path, compare, _sha(_serial(index))


def test_review_recomputes_paired_baseline(tmp_path):
    path, compare, index_hash = _fixture(tmp_path)
    result = review(path, compare,
                    expected_archive_sha256=_sha(path.read_bytes()),
                    expected_index_sha256=index_hash)
    assert result["ready_trials_verified"] == 4
    assert result["unique_fold_configuration_groups"] == 2
    assert result["identical_seed_outcome_groups"] == 2
    assert result["paired_search_candidates"][0]["median_paired_delta_pp"] == 5
    assert result["independent_holdout_certified"] is False
    assert result["trade_ready"] is False


def test_review_rejects_tampered_receipt(tmp_path):
    path, compare, _ = _fixture(tmp_path, corrupt=True)
    with pytest.raises(ReviewError, match="checkpoint member mismatch"):
        review(path, compare)


def test_review_rejects_wrong_archive_identity(tmp_path):
    path, compare, _ = _fixture(tmp_path)
    with pytest.raises(ReviewError, match="checkpoint ZIP SHA256 mismatch"):
        review(path, compare, expected_archive_sha256="0" * 64)


def test_review_rejects_false_performance_ranking(tmp_path):
    path, compare, _ = _fixture(tmp_path)
    data = json.loads(compare.read_text())
    data["configurations"][1]["fold_diagnostics"][0]["median_net_excess"] = 0.99
    compare.write_text(json.dumps(data))
    with pytest.raises(ReviewError, match="mismatch with published comparison"):
        review(path, compare)
