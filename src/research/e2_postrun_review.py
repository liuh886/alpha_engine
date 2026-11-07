"""Read-only, hash-verified postrun review of an E2 research checkpoint.

Uses actual study receipts, not only the published ranking. No model promotion,
holdout access, trade execution, data repair, network calls or provider input.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import statistics
import sys
import zipfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

from src.research.colab_experiment_batch import CHECKPOINT_SCHEMA, MAX_CHECKPOINT_BYTES


class ReviewError(ValueError):
    """An evidence-integrity or comparability check failed."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _median(values: list[float]) -> float:
    if not values or not all(math.isfinite(v) for v in values):
        raise ReviewError("missing or non-finite performance observations")
    return float(statistics.median(values))


def _same(actual: float, expected: float, *, context: str) -> None:
    # The original study receipts store 4-decimal rounded outcomes.
    if not math.isfinite(actual) or not math.isfinite(expected):
        raise ReviewError(f"non-finite performance observation: {context}")
    if abs(actual - expected) > 0.00011:
        raise ReviewError(f"mismatch with published comparison: {context}: {actual} != {expected}")


def review(checkpoint_zip: Path, comparison_file: Path, *,
           expected_archive_sha256: str | None = None,
           expected_index_sha256: str | None = None) -> dict[str, Any]:
    """Recompute every fold/config aggregate from independently hashed receipts."""
    if (checkpoint_zip.is_symlink() or comparison_file.is_symlink() or
            checkpoint_zip.stat().st_size > MAX_CHECKPOINT_BYTES + 1024 * 1024 or
            comparison_file.stat().st_size > MAX_CHECKPOINT_BYTES):
        raise ReviewError("review input exceeds bounded regular-file budget")
    raw = checkpoint_zip.read_bytes()
    archive_sha = _sha(raw)
    if expected_archive_sha256 and archive_sha != expected_archive_sha256:
        raise ReviewError("checkpoint ZIP SHA256 mismatch")
    comparison_bytes = comparison_file.read_bytes()
    report = json.loads(comparison_bytes)
    if (report.get("schema_version") != "p2_e2_validation_comparison_v1" or
            report.get("holdout_evaluated") is not False or
            report.get("trade_ready") is not False or report.get("model_promoted") is not False):
        raise ReviewError("unsupported comparison report schema")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        members = z.namelist()
        if (len(members) > 3002 or sum(i.file_size for i in z.infolist()) >
                MAX_CHECKPOINT_BYTES + 1024 * 1024):
            raise ReviewError("checkpoint exceeds member/uncompressed budget")
        if len(set(members)) != len(members):
            raise ReviewError("ZIP has duplicate members")
        index_bytes = z.read("checkpoint-index.json")
        index_sha = _sha(index_bytes)
        if expected_index_sha256 and index_sha != expected_index_sha256:
            raise ReviewError("checkpoint index SHA256 mismatch")
        index = json.loads(index_bytes)
        if (index.get("schema_version") != CHECKPOINT_SCHEMA or
                index.get("research_only") is not True or index.get("trade_ready") is not False or
                index.get("pit_certified") is not False):
            raise ReviewError("not a bounded research-only checkpoint")
        checks = index["files"]
        indexed_names = {f["path"] for f in checks}
        if len(indexed_names) != len(checks) or set(members) != indexed_names | {"checkpoint-index.json"}:
            raise ReviewError("unexpected or missing checkpoint members")
        for item in checks:
            name = item["path"]
            parts = PurePosixPath(name)
            if parts.is_absolute() or ".." in parts.parts or "\\" in name:
                raise ReviewError("unsafe ZIP member path")
            body = z.read(name)
            if len(body) != item["size"] or _sha(body) != item["sha256"]:
                raise ReviewError(f"checkpoint member mismatch: {name}")
        batch_id = index["batch_id"]
        plan_path = f"{batch_id}/batch-plan.json"
        plan = json.loads(z.read(plan_path))
        if (plan["batch_id"] != batch_id or
                plan["run_id"] != report["run_id"] or
                plan["runner_git_sha"] != index["runner_git_sha"] or
                plan["batch_spec_sha256"] != index["batch_identity_sha256"] or
                any(plan["data"].get(k) != index.get(k) for k in
                    ("history_archive_sha256", "v5_bundle_manifest_sha256")) or
                len(plan["trials"]) != plan["trial_count"]):
            raise ReviewError("batch/report/runner identity mismatch")
        configs = {c["configuration_id"]: c for c in report["configurations"]}
        if len(configs) != len(report["configurations"]):
            raise ReviewError("duplicate configuration in published report")
        planned_configs = {c["configuration_id"]: c for c in plan["configurations"]}
        if len(planned_configs) != len(plan["configurations"]) or set(configs) != set(planned_configs):
            raise ReviewError("published configuration set differs from frozen plan")
        for cid, cfg in configs.items():
            if any(cfg.get(k) != v for k, v in planned_configs[cid].items() if k not in ("features",)):
                raise ReviewError("published configuration identity differs from frozen plan")
        receipt_groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
        seen_trials: set[str] = set()
        seen_config_fold_seeds: set[tuple[str, str, int]] = set()
        elapsed: list[float] = []
        family_time: dict[str, list[float]] = defaultdict(list)
        for trial in plan["trials"]:
            trial_id = trial["trial_id"]
            if trial_id in seen_trials:
                raise ReviewError("duplicate frozen trial ID")
            seen_trials.add(trial_id)
            observation_id = (trial["configuration_id"], trial["fold_id"], trial["seed"])
            if observation_id in seen_config_fold_seeds:
                raise ReviewError("duplicate config/fold/seed identity")
            seen_config_fold_seeds.add(observation_id)
            base = f"{batch_id}/trials/{trial_id}/"
            study_raw = z.read(base + "study-receipt.json")
            study = json.loads(study_raw)
            wrapper = json.loads(z.read(base + "trial-result.json"))
            spec = json.loads(z.read(base + "study-spec.json"))
            expected_spec = dict(trial["study"])
            if expected_spec.get("symbols") == "$US87":
                symbols = spec.get("symbols", [])
                if not isinstance(symbols, list) or len(symbols) != 87 or len(set(symbols)) != 87:
                    raise ReviewError("resolved US87 study pool is not complete")
                expected_spec["symbols"] = symbols
            identity = {k: v for k, v in study.items() if k not in ("study_hash", "generated_at_utc")}
            if (spec != expected_spec or study.get("experiment_receipt") != spec or
                    study.get("study_hash") != _sha(_canonical(identity)) or
                    trial.get("study_sha256") != _sha(_canonical(trial["study"])) or
                    wrapper.get("study_spec_sha256") != _sha(_canonical(spec)) or
                    wrapper.get("trial_id") != trial_id or
                    wrapper.get("batch_spec_sha256") != plan["batch_spec_sha256"]):
                raise ReviewError(f"study/spec/wrapper identity or inner hash mismatch: {trial_id}")
            if (study.get("status") != "ready" or wrapper.get("study_status") != "ready" or
                    wrapper["receipt_sha256"] != _sha(study_raw) or
                    wrapper.get("runner_git_sha") != index["runner_git_sha"] or
                    study.get("git_commit") != index["runner_git_sha"] or
                    study.get("pit_certified") is not False or
                    study.get("trade_ready") is not False or
                    study.get("research_only") is not True or
                    spec.get("xgb_params", {}).get("seed") != trial["seed"]):
                raise ReviewError(f"unready or mismatched trial receipt {trial_id}")
            key = (trial["configuration_id"], trial["fold_id"])
            if trial["configuration_id"] not in configs:
                raise ReviewError("missing configuration for trial")
            receipt_groups[key].append(study)
            seconds = float(wrapper["elapsed_seconds"])
            if not math.isfinite(seconds) or seconds < 0:
                raise ReviewError("invalid elapsed_seconds")
            elapsed.append(seconds)
            family_time[configs[key[0]]["model_family"]].append(seconds)
        folded: dict[str, dict[str, dict]] = defaultdict(dict)
        identical_groups = 0
        aggregate_excess: dict[str, float] = {}
        for cfg_id, config in configs.items():
            results = [key for key in receipt_groups if key[0] == cfg_id]
            total = sum(len(receipt_groups[k]) for k in results)
            if total != config["ready_tasks"] or total != config["planned_tasks"] or not config["complete"]:
                raise ReviewError(f"incomplete/mismatched configuration: {cfg_id}")
            diagnostic_folds = [d["fold_id"] for d in config["fold_diagnostics"]]
            if (len(set(diagnostic_folds)) != len(diagnostic_folds) or
                    set(diagnostic_folds) != {fold for _, fold in results}):
                raise ReviewError("fold diagnostics differ from frozen trial coverage")
            for diag in config["fold_diagnostics"]:
                fold = diag["fold_id"]
                rows = receipt_groups.get((cfg_id, fold), [])
                if len(rows) != diag["ready_seeds"]:
                    raise ReviewError(f"fold/seed coverage mismatch {cfg_id}/{fold}")
                windows = {(r["experiment_receipt"]["test_start"], r["experiment_receipt"]["test_end"],
                            r["oos_sessions_count"]) for r in rows}
                if len(windows) != 1:
                    raise ReviewError("seed windows/session counts differ within fold")
                for row in rows:
                    _same(float(row["overall_benchmark_cumulative_return"]),
                          float(rows[0]["overall_benchmark_cumulative_return"]), context="seed QQQ parity")
                excess = _median([float(r["overall_oos_net_excess_return"]) for r in rows])
                drawdown = min(float(r["overall_oos_max_drawdown"]) for r in rows)
                _same(excess, float(diag["median_net_excess"]), context=f"{cfg_id}/{fold} excess")
                _same(drawdown, float(diag["worst_drawdown"]), context=f"{cfg_id}/{fold} drawdown")
                vectors = {(r["overall_oos_net_excess_return"], r["overall_oos_max_drawdown"],
                            r["rank_ic"]) for r in rows}
                if len(vectors) != diag["distinct_performance_vectors"]:
                    raise ReviewError(f"seed outcome count mismatch: {cfg_id}/{fold}")
                identical_groups += len(vectors) == 1
                folded[cfg_id][fold] = {"net_excess": excess, "worst_drawdown": drawdown,
                                        "rank_ic": _median([float(r["rank_ic"]) for r in rows]),
                                        "distinct_outcomes": len(vectors),
                                        "sessions": rows[0]["oos_sessions_count"],
                                        "start": rows[0]["experiment_receipt"]["test_start"],
                                        "end": rows[0]["experiment_receipt"]["test_end"],
                                        "qqq_return": rows[0]["overall_benchmark_cumulative_return"]}
            aggregate_excess[cfg_id] = _median([r["overall_oos_net_excess_return"] for k in results for r in receipt_groups[k]])
            _same(aggregate_excess[cfg_id],
                  float(config["median_validation_net_excess"]), context=f"{cfg_id} median")
            if all(f["distinct_outcomes"] == 1 for f in folded[cfg_id].values()) != config["seed_repetitions_identical"]:
                raise ReviewError("seed summary mismatch")
        baselines = [c["configuration_id"] for c in configs.values() if c["phase"] == "baseline"]
        if len(baselines) != 1:
            raise ReviewError("expected exactly one baseline")
        baseline = baselines[0]
        reference_folds = sorted(folded[baseline])
        if len(reference_folds) == 0:
            raise ReviewError("empty baseline")
        for cfg_id in folded:
            if sorted(folded[cfg_id]) != reference_folds:
                raise ReviewError("fold set not comparable")
            for fold in reference_folds:
                if any(folded[cfg_id][fold][key] != folded[baseline][fold][key]
                       for key in ("start", "end", "sessions")):
                    raise ReviewError("paired fold windows/session counts differ")
                _same(folded[cfg_id][fold]["qqq_return"],
                      folded[baseline][fold]["qqq_return"], context="QQQ fold parity")
        paired = []
        expected_ranking = sorted((cid for cid, cfg in configs.items() if cfg["phase"] == "search"),
                                  key=lambda cid: (-aggregate_excess[cid], cid))
        if report["validation_ranking"] != expected_ranking:
            raise ReviewError("validation ranking identities/order differ from verified observations")
        for cfg_id in report["validation_ranking"]:
            if configs[cfg_id]["phase"] != "search":
                raise ReviewError("non-search configuration entered ranking")
            deltas = [
                100 * (folded[cfg_id][fold]["net_excess"] - folded[baseline][fold]["net_excess"])
                for fold in reference_folds
            ]
            paired.append({"configuration_id": cfg_id,
                           "median_validation_net_excess_pp": round(
                               100 * configs[cfg_id]["median_validation_net_excess"], 4),
                           "paired_deltas_vs_momentum_pp": [round(d, 4) for d in deltas],
                           "median_paired_delta_pp": round(_median(deltas), 4),
                           "wins_vs_momentum": sum(d > 0 for d in deltas)})
        if len(paired) != sum(c["phase"] == "search" for c in configs.values()):
            raise ReviewError("incomplete validation search ranking")
        stress = {}
        controls = {c["candidate_id"]: c for c in configs.values()}
        if "xgb_control" in controls and "xgb_cost_stress" in controls:
            control, high = (controls[key]["configuration_id"]
                             for key in ("xgb_control", "xgb_cost_stress"))
            deltas = [100 * (folded[control][fold]["net_excess"] -
                             folded[high][fold]["net_excess"]) for fold in reference_folds]
            stress = {"control": control, "stress": high,
                      "paired_cost_loss_pp": [round(d, 4) for d in deltas],
                      "median_cost_loss_pp": round(_median(deltas), 4),
                      "warning": "stress compares the fixed control, not a selected search winner"}
        return {
            "schema_version": "p2_e3_postrun_review_v1",
            "evidence_status": ("VERIFIED_EXECUTION_RESEARCH_PROVISIONAL" if
                                expected_archive_sha256 and expected_index_sha256 else
                                "INTERNAL_INTEGRITY_ONLY_RESEARCH_PROVISIONAL"),
            "external_archive_and_index_pins_verified": bool(expected_archive_sha256 and expected_index_sha256),
            "comparison_sha256": _sha(comparison_bytes),
            "reviewer_code_sha256": _sha(Path(__file__).read_bytes()),
            "archive_sha256": archive_sha, "index_sha256": index_sha,
            "batch_id": batch_id, "run_id": report["run_id"],
            "source_sha256": index["history_archive_sha256"],
            "runner_sha": index["runner_git_sha"],
            "index_files_verified": len(checks),
            "ready_trials_verified": len(seen_trials),
            "study_spec_and_inner_hashes_verified": len(seen_trials),
            "unique_fold_configuration_groups": len(receipt_groups),
            "identical_seed_outcome_groups": identical_groups,
            "baseline": baseline, "folds": reference_folds,
            "paired_search_candidates": paired,
            "cost_stress_control": stress,
            "training_seconds_sum": round(sum(elapsed), 4),
            "training_seconds_median": round(_median(elapsed), 4),
            "training_seconds_by_family": {k: round(sum(v), 4) for k, v in
                                           sorted(family_time.items())},
            "wall_clock_end_to_end_seconds": None,
            "colab_compute_units_consumed": None,
            "independent_holdout_certified": False,
            "trade_ready": False, "model_promoted": False,
            "caveats": ["three folds are dependent through expanding train history and fixed universe",
                        "identical seed metrics are not independent evidence",
                        "no daily trade/attribution ledger in this checkpoint",
                        "independent holdout, source vintages and PIT not certified"],
        }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checkpoint", required=True, type=Path)
    p.add_argument("--comparison", required=True, type=Path)
    p.add_argument("--expected-archive-sha256")
    p.add_argument("--expected-index-sha256")
    p.add_argument("--output", type=Path)
    args = p.parse_args(argv)
    try:
        result = review(args.checkpoint, args.comparison,
                        expected_archive_sha256=args.expected_archive_sha256,
                        expected_index_sha256=args.expected_index_sha256)
        body = json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as f:
                f.write(body)
        print(body)
        return 0
    except (ReviewError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print(f"BLOCKED_E2_REVIEW: {exc}", file=sys.stderr)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
