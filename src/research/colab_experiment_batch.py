"""P2-E2 bounded Colab/local experiment batch using the existing XGBoost study.

No new ranker, data provider, hosted scheduler, or trade output. The runner
iterates frozen validation folds × model hyperparameters × seeds, saves each
existing Study Workspace receipt, and can resume at completed trial boundaries.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from src.research.cloud_exchange import ExchangeError
from src.research.v5_isolated_staging import verify_stage

SHA = re.compile(r"[0-9a-f]{64}")
NAME = re.compile(r"[a-z][a-z0-9_-]{2,63}")
SCHEMA = "p2_e2_xgb_validation_batch_v1"
ALLOWED_PARAMS = {"max_depth", "learning_rate", "num_boost_round"}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _write_new(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as out:
        json.dump(data, out, indent=2, sort_keys=True, allow_nan=False)
        out.write("\n")


def _git_head() -> str:
    root = Path(__file__).resolve().parents[2]
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def plan(spec: dict, data_root: Path | None = None) -> dict[str, Any]:
    """Validate a complete, bounded selection-only search without executing."""
    if not isinstance(spec, dict) or spec.get("schema_version") != SCHEMA:
        raise ExchangeError("unsupported batch schema")
    if not isinstance(spec.get("batch_id"), str) or not NAME.fullmatch(spec["batch_id"]):
        raise ExchangeError("invalid batch_id")
    if (not isinstance(spec.get("runner_git_sha"), str) or
            not re.fullmatch("[0-9a-f]{40}", spec["runner_git_sha"])):
        raise ExchangeError("exact experiment runner SHA required")
    if (not isinstance(spec.get("v5_bundle_manifest_sha256"), str) or
            not SHA.fullmatch(spec["v5_bundle_manifest_sha256"]) or
            not isinstance(spec.get("history_archive_sha256"), str) or
            not SHA.fullmatch(spec["history_archive_sha256"])):
        raise ExchangeError("source hashes must be independently pinned")
    if spec.get("purpose") != "validation_search_only":
        raise ExchangeError("batch is for validation search, NOT final holdout or production")
    base = spec.get("study")
    if not isinstance(base, dict) or base.get("study_id") != "cross_sectional_xgb_v1":
        raise ExchangeError("first batch must reuse existing XGBoost study")
    if (base.get("market") != "us" or
            base.get("pool_id") != "us_selected_equities_v2" or
            base.get("symbols") != "$US87" or base.get("benchmark") != "QQQ" or
            base.get("price_mode") != "anchored_adjusted"):
        raise ExchangeError("batch must retain full US87, QQQ and price-basis contract")
    # Fields must match existing Study Workspace config exactly, except 4 fold dates.
    from src.research.study_workspace import DEFAULT_XGB_CONFIG
    sample = DEFAULT_XGB_CONFIG.to_dict()
    if set(base) != set(sample) or set(base["xgb_params"]) != set(sample["xgb_params"]):
        raise ExchangeError("batch base study does not match existing study template fields")
    if (base.get("top_k", 0) <= 0 or base["top_k"] > 87 or
            base.get("cost_bps", -1) < 0 or base.get("slippage_bps", -1) < 0 or
            base.get("features") != list(DEFAULT_XGB_CONFIG.features)):
        raise ExchangeError("invalid benchmark/cost/feature contract")
    folds = spec.get("validation_folds")
    if not isinstance(folds, list) or not folds or len(folds) > 8:
        raise ExchangeError("1..8 explicitly frozen chronological folds required")
    for i, fold in enumerate(folds):
        if not isinstance(fold, dict) or set(fold) != {
                "fold_id", "train_start", "train_end", "test_start", "test_end"}:
            raise ExchangeError("invalid fold fields")
        if not NAME.fullmatch(str(fold["fold_id"])):
            raise ExchangeError("invalid fold_id")
        if not all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(fold[k])) for k in
                   ("train_start", "train_end", "test_start", "test_end")):
            raise ExchangeError("invalid dates")
        if not (fold["train_start"] < fold["train_end"] < fold["test_start"]
                <= fold["test_end"] <= base["as_of_cutoff"] <= "2026-11-03"):
            raise ExchangeError("out-of-range or overlapping train/validation dates")
        if i and folds[i - 1]["test_end"] >= fold["test_start"]:
            raise ExchangeError("validation windows overlap")
    search = spec.get("search_space")
    if not isinstance(search, dict) or not search or set(search) - ALLOWED_PARAMS:
        raise ExchangeError("unsupported search dimension")
    for key, values in search.items():
        if not isinstance(values, list) or not values or len(values) > 12:
            raise ExchangeError("search dimension must be a small explicit list")
        for value in values:
            if key == "learning_rate":
                if (not isinstance(value, (int, float)) or isinstance(value, bool) or
                        not 0 < value <= 1):
                    raise ExchangeError("invalid learning rate")
            elif not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1000:
                raise ExchangeError("invalid integer XGBoost parameter")
    seeds = spec.get("seeds")
    if (not isinstance(seeds, list) or not seeds or len(seeds) > 10 or
            any(not isinstance(s, int) or isinstance(s, bool) or not 0 <= s <= 2**31 - 1
                for s in seeds) or len(seeds) != len(set(seeds))):
        raise ExchangeError("invalid deterministic seeds")
    max_trials = spec.get("max_trials")
    if (not isinstance(max_trials, int) or isinstance(max_trials, bool)
            or not 1 <= max_trials <= 100):
        raise ExchangeError("explicit max_trials must be between 1 and 100")
    if data_root is not None:
        root_doc = verify_stage(data_root)
        if (root_doc["bundle_manifest_sha256"] != spec["v5_bundle_manifest_sha256"] or
                root_doc["history_archive_sha256"] != spec["history_archive_sha256"]):
            raise ExchangeError("staged input root differs from experiment source")
    combos = itertools.product(
        folds, seeds, itertools.product(*[search[k] for k in sorted(search)]))
    trials = []
    for fold, seed, param_values in combos:
        params = dict(zip(sorted(search), param_values))
        study = {**base, **{k: fold[k] for k in
                 ("train_start", "train_end", "test_start", "test_end")}}
        study["as_of_cutoff"] = base["as_of_cutoff"]
        study["xgb_params"] = {**base["xgb_params"], **params, "seed": seed}
        study["symbols"] = "$US87"
        digest = _digest(_canonical(study))
        trials.append({"trial_id": f'{fold["fold_id"]}-s{seed}-{digest[:12]}',
                       "fold_id": fold["fold_id"], "seed": seed,
                       "params": params, "study": study, "study_sha256": digest})
        if len(trials) > max_trials:
            raise ExchangeError("search product exceeds max_trials budget")
    if len({t["trial_id"] for t in trials}) != len(trials):
        raise ExchangeError("duplicate trial identity")
    return {"schema_version": SCHEMA, "batch_id": spec["batch_id"],
            "batch_spec_sha256": _digest(_canonical(spec)),
            "runner_git_sha": spec["runner_git_sha"],
            "data": {"v5_bundle_manifest_sha256": spec["v5_bundle_manifest_sha256"],
                     "history_archive_sha256": spec["history_archive_sha256"]},
            "role": "validation_search_only", "trial_count": len(trials),
            "trials": trials, "trade_ready": False, "pit_certified": False,
            "research_only": True}


def execute(*, batch_spec: Path, data_root: Path, output_root: Path,
            resume: bool = False, max_new_trials: int | None = None) -> dict:
    """Run existing Study Workspace specs, checkpoint one immutable receipt per trial."""
    if max_new_trials is not None and (not isinstance(max_new_trials, int)
                                       or not 1 <= max_new_trials <= 100):
        raise ExchangeError("max_new_trials must be within 1..100")
    spec = json.loads(batch_spec.read_text(encoding="utf-8"))
    batch = plan(spec, data_root)
    if _git_head() != batch["runner_git_sha"]:
        raise ExchangeError("runner checkout revision mismatch")
    if output_root.resolve().is_relative_to(Path(__file__).resolve().parents[2]):
        raise ExchangeError("training outputs must remain outside the public Git repo")
    # Source stage must be a fresh isolated root, not the original Git checkout.
    if data_root.resolve().is_relative_to(Path(__file__).resolve().parents[2]):
        raise ExchangeError("training data must use isolated v5 stage")
    from src.research.study_workspace import load_study_spec, run_study
    import yaml

    pool = yaml.safe_load((data_root / "configs/research_universes/"
                           "us_selected_equities_v2.yaml").read_text(encoding="utf-8"))
    symbols = list(pool["symbols"])
    if len(symbols) != 87 or len(set(symbols)) != 87:
        raise ExchangeError("staged full US87 pool invalid")
    path = output_root / batch["batch_id"]
    if path.exists() and not resume:
        raise ExchangeError("immutable batch exists; use --resume after inspecting it")
    path.mkdir(parents=True, exist_ok=True)
    frozen = path / "batch-plan.json"
    if frozen.exists():
        existing = json.loads(frozen.read_text(encoding="utf-8"))
        if existing != batch:
            raise ExchangeError("resume batch spec/hash differs")
    else:
        _write_new(frozen, batch)
    completed = 0
    new = 0
    blocked = 0
    for entry in batch["trials"]:
        td = path / "trials" / entry["trial_id"]
        run_spec = {**entry["study"], "symbols": symbols}
        cfg_path = td / "study-spec.json"
        out = td / "study-receipt.json"
        receipt = td / "trial-result.json"
        if receipt.exists():
            rec = json.loads(receipt.read_text(encoding="utf-8"))
            if (not resume or rec.get("trial_id") != entry["trial_id"] or
                    rec.get("study_spec_sha256") != _digest(_canonical(run_spec)) or
                    not out.is_file() or
                    rec.get("receipt_sha256") != _digest(out.read_bytes())):
                raise ExchangeError("resume result identity mismatch")
            completed += 1
            continue
        if max_new_trials is not None and new >= max_new_trials:
            break
        if out.exists():
            raise ExchangeError("incomplete prior trial requires manual review")
        if cfg_path.exists():
            if json.loads(cfg_path.read_text(encoding="utf-8")) != run_spec:
                raise ExchangeError("existing frozen trial spec differs")
        else:
            _write_new(cfg_path, run_spec)
        load_study_spec(cfg_path)  # canonical Study Workspace validation
        result = run_study(cfg_path, data_root, output=out)
        if result["status"] not in ("ready", "blocked"):
            raise ExchangeError("unexpected study receipt status")
        _write_new(receipt, {
            "schema_version": "p2_e2_batch_trial_receipt_v1",
            "batch_spec_sha256": batch["batch_spec_sha256"],
            "runner_git_sha": batch["runner_git_sha"],
            "trial_id": entry["trial_id"],
            "study_spec_sha256": _digest(_canonical(run_spec)),
            "receipt_sha256": _digest(out.read_bytes()),
            "study_status": result["status"],
            "blocked_reasons": result.get("blocked_reasons", []),
            "research_only": True, "trade_ready": False, "pit_certified": False,
            "review_status": "incoming_unreviewed"})
        new += 1
        if result["status"] == "blocked":
            blocked += 1
    pending = len(batch["trials"]) - completed - new
    return {"status": ("BATCH_PARTIAL_CHECKPOINT_READY" if pending else
                       "BATCH_EXECUTED_RESEARCH_ONLY"), "batch_id": batch["batch_id"],
            "trials": len(batch["trials"]), "resumed_trials": completed,
            "new_trials": new, "pending_trials": pending, "blocked_trials": blocked,
            "review_status": "incoming_unreviewed",
            "trade_ready": False, "pit_certified": False}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    for cmd in ("plan", "run"):
        subp = sub.add_parser(cmd)
        subp.add_argument("--batch-spec", required=True, type=Path)
        if cmd == "run":
            subp.add_argument("--data-root", required=True, type=Path)
            subp.add_argument("--output-root", required=True, type=Path)
            subp.add_argument("--resume", action="store_true")
            subp.add_argument("--max-new-trials", type=int)
    args = p.parse_args(argv)
    try:
        if args.action == "plan":
            spec = json.loads(args.batch_spec.read_text(encoding="utf-8"))
            result = plan(spec)
            # Plan output includes explicit spec inputs, not private source bars.
            print(json.dumps(result, indent=2))
        else:
            print(json.dumps(execute(batch_spec=args.batch_spec, data_root=args.data_root,
                                     output_root=args.output_root, resume=args.resume,
                                     max_new_trials=args.max_new_trials), indent=2))
        return 0
    except (ExchangeError, OSError, ValueError, KeyError, TypeError,
            subprocess.CalledProcessError) as exc:
        print(f"BLOCKED_COLAB_BATCH: {exc}", file=sys.stderr)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
