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


def _fixture(tmp_path, *, corrupt=False, two_folds=False, two_search=False):
    batch_id = "research-v2-fixture"
    runner = "a" * 40
    identity = "c" * 64
    trials = []
    entries = {}
    configurations = [{"configuration_id": model, "candidate_id": model,
                       "model_family": "momentum_20d" if model == "rule" else "xgboost",
                       "phase": "baseline" if model == "rule" else "search"}
                      for model in (("rule", "model", "model_other") if two_search else ("rule", "model"))]
    folds = ("fold_a", "fold_b") if two_folds else ("fold_a",)
    for cfg in configurations:
        model = cfg["configuration_id"]
        for fold in folds:
            for seed in (17, 42):
                tid = f"{model}-{fold}-{seed}"
                spec = {"xgb_params": {"seed": seed}, "symbols": ["AAA", "BBB"],
                        "test_start": "2026-01-01" if fold == "fold_a" else "2026-02-01",
                        "test_end": "2026-01-20" if fold == "fold_a" else "2026-02-20"}
                trials.append({"trial_id": tid, "configuration_id": model,
                               "fold_id": fold, "seed": seed, "study": spec,
                               "study_sha256": _sha(_serial(spec).rstrip(b"\n"))})
                base = f"{batch_id}/trials/{tid}/"
                value = 0.2 if model == "rule" else 0.25
                receipt = {"status": "ready", "git_commit": runner, "pit_certified": False,
                           "trade_ready": False, "research_only": True,
                           "overall_oos_net_excess_return": value,
                           "overall_oos_max_drawdown": -0.1,
                           "rank_ic": 0.05, "oos_sessions_count": 10,
                           "overall_benchmark_cumulative_return": 0.05,
                           "experiment_receipt": spec}
                receipt["study_hash"] = _sha(_serial(receipt).rstrip(b"\n"))
                raw = _serial(receipt)
                entries[base + "study-receipt.json"] = raw
                entries[base + "trial-result.json"] = _serial({
                    "study_status": "ready", "runner_git_sha": runner,
                    "trial_id": tid, "batch_spec_sha256": identity,
                    "study_spec_sha256": _sha(_serial(spec).rstrip(b"\n")),
                    "receipt_sha256": _sha(raw), "elapsed_seconds": 2.0})
                entries[base + "study-spec.json"] = _serial(spec)
    source_data = {"history_archive_sha256": "b" * 64, "v5_bundle_manifest_sha256": "d" * 64}
    plan = {"batch_id": batch_id, "run_id": identity, "runner_git_sha": runner,
            "batch_spec_sha256": identity, "data": source_data,
            "trial_count": len(trials), "trials": trials, "configurations": configurations}
    entries[f"{batch_id}/batch-plan.json"] = _serial(plan)
    index = {"batch_id": batch_id, "runner_git_sha": runner,
             "schema_version": "p2_e2_unreviewed_trial_checkpoint_v1",
             "research_only": True, "trade_ready": False, "pit_certified": False,
             "batch_identity_sha256": identity, **source_data,
             "files": [{"path": k, "sha256": _sha(v), "size": len(v)}
                       for k, v in sorted(entries.items())]}
    report = {"schema_version": "p2_e2_validation_comparison_v1",
              "run_id": identity, "holdout_evaluated": False,
              "trade_ready": False, "model_promoted": False,
              "validation_ranking": [c["configuration_id"] for c in configurations if c["phase"] == "search"],
              "configurations": []}
    for cfg in configurations:
        name, phase = cfg["configuration_id"], cfg["phase"]
        value = 0.2 if name == "rule" else 0.25
        report["configurations"].append({
            "configuration_id": name, "candidate_id": name,
            "model_family": "momentum_20d" if name == "rule" else "xgboost",
            "phase": phase, "ready_tasks": 2 * len(folds), "planned_tasks": 2 * len(folds), "complete": True,
            "median_validation_net_excess": value,
            "seed_repetitions_identical": True,
            "fold_diagnostics": [{"fold_id": fold, "ready_seeds": 2,
                                  "median_net_excess": value, "worst_drawdown": -0.1,
                                  "distinct_performance_vectors": 1} for fold in folds]})
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


@pytest.mark.parametrize("metric", ["median_validation_net_excess", "median_net_excess", "worst_drawdown"])
def test_review_rejects_nonfinite_published_metrics(tmp_path, metric):
    path, compare, _ = _fixture(tmp_path)
    report = json.loads(compare.read_text())
    target = report["configurations"][1]
    if metric != "median_validation_net_excess":
        target = target["fold_diagnostics"][0]
    target[metric] = float("nan")
    compare.write_text(json.dumps(report))
    with pytest.raises(ReviewError, match="non-finite"):
        review(path, compare)


@pytest.mark.parametrize("ranking", [["model", "model"], ["model_other", "model"]])
def test_review_rejects_duplicated_or_reordered_search_ranking(tmp_path, ranking):
    path, compare, _ = _fixture(tmp_path, two_search=True)
    report = json.loads(compare.read_text())
    report["validation_ranking"] = ranking
    compare.write_text(json.dumps(report))
    with pytest.raises(ReviewError, match="ranking identities/order"):
        review(path, compare)


@pytest.mark.parametrize("duplicate", [False, True])
def test_review_requires_each_frozen_fold_exactly_once(tmp_path, duplicate):
    path, compare, _ = _fixture(tmp_path, two_folds=True)
    report = json.loads(compare.read_text())
    for config in report["configurations"]:
        config["fold_diagnostics"] = ([config["fold_diagnostics"][0]] * 2 if duplicate else
                                       config["fold_diagnostics"][:1])
    compare.write_text(json.dumps(report))
    with pytest.raises(ReviewError, match="fold diagnostics"):
        review(path, compare)


def _reseal(path, mutate):
    with zipfile.ZipFile(path) as z:
        files = {n: z.read(n) for n in z.namelist()}
    index = json.loads(files.pop("checkpoint-index.json"))
    mutate(files)
    index["files"] = [{"path": k, "size": len(v), "sha256": _sha(v)} for k, v in sorted(files.items())]
    with zipfile.ZipFile(path, "w") as z:
        for name, raw in files.items():
            z.writestr(name, raw)
        z.writestr("checkpoint-index.json", _serial(index))


@pytest.mark.parametrize("kind", ["inner_study_hash", "study_spec", "wrapper_trial_id"])
def test_review_checks_semantic_identities_even_if_index_is_resealed(tmp_path, kind):
    path, compare, _ = _fixture(tmp_path)

    def mutate(files):
        name = next(n for n in files if n.endswith("/study-receipt.json"))
        wrapper_path = name.replace("study-receipt.json", "trial-result.json")
        wrapper = json.loads(files[wrapper_path])
        if kind == "inner_study_hash":
            receipt = json.loads(files[name])
            receipt["unreviewed_extra_claim"] = True
            files[name] = _serial(receipt)
            wrapper["receipt_sha256"] = _sha(files[name])
        elif kind == "study_spec":
            spec_path = name.replace("study-receipt.json", "study-spec.json")
            spec = json.loads(files[spec_path])
            spec["xgb_params"]["max_depth"] = 99
            files[spec_path] = _serial(spec)
            wrapper["study_spec_sha256"] = _sha(_serial(spec).rstrip(b"\n"))
        else:
            wrapper["trial_id"] = "unrelated-trial"
        files[wrapper_path] = _serial(wrapper)

    _reseal(path, mutate)
    with pytest.raises(ReviewError, match="identity or inner hash"):
        review(path, compare)


def test_unpinned_review_never_claims_external_evidence_verification(tmp_path):
    path, compare, _ = _fixture(tmp_path)
    result = review(path, compare)
    assert result["evidence_status"] == "INTERNAL_INTEGRITY_ONLY_RESEARCH_PROVISIONAL"
    assert result["external_archive_and_index_pins_verified"] is False


def test_review_checks_configuration_labels_against_frozen_plan(tmp_path):
    path, compare, _ = _fixture(tmp_path)
    report = json.loads(compare.read_text())
    report["configurations"][1]["model_family"] = "invented_model"
    compare.write_text(json.dumps(report))
    with pytest.raises(ReviewError, match="configuration identity"):
        review(path, compare)


@pytest.mark.parametrize("all_seeds", [False, True])
def test_review_refuses_unpaired_session_counts(tmp_path, all_seeds):
    path, compare, _ = _fixture(tmp_path)

    def mutate(files):
        names = [n for n in files if "/trials/model-" in n and n.endswith("study-receipt.json")]
        for name in names if all_seeds else names[:1]:
            receipt = json.loads(files[name])
            receipt.pop("study_hash")
            receipt["oos_sessions_count"] = 11
            receipt["study_hash"] = _sha(_serial(receipt).rstrip(b"\n"))
            files[name] = _serial(receipt)
            wrapper_path = name.replace("study-receipt.json", "trial-result.json")
            wrapper = json.loads(files[wrapper_path])
            wrapper["receipt_sha256"] = _sha(files[name])
            files[wrapper_path] = _serial(wrapper)

    _reseal(path, mutate)
    with pytest.raises(ReviewError, match="windows/session counts differ"):
        review(path, compare)


@pytest.mark.parametrize("flag", ["model_promoted", "holdout_evaluated", "trade_ready"])
def test_review_refuses_promotion_or_holdout_claims(tmp_path, flag):
    path, compare, _ = _fixture(tmp_path)
    report = json.loads(compare.read_text())
    report[flag] = True
    compare.write_text(json.dumps(report))
    with pytest.raises(ReviewError, match="unsupported comparison"):
        review(path, compare)


def test_review_rejects_oversized_uncompressed_checkpoint(tmp_path):
    from src.research.colab_experiment_batch import MAX_CHECKPOINT_BYTES

    path, compare, _ = _fixture(tmp_path)
    with zipfile.ZipFile(path, "a", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("oversized.json", b"x" * (MAX_CHECKPOINT_BYTES + 1024 * 1024 + 1))
    with pytest.raises(ReviewError, match="uncompressed budget"):
        review(path, compare)
