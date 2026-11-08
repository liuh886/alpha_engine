"""Compile bounded multi-model research into the existing Colab batch runner.

This is a specification compiler and derived comparison, never another trainer,
model registry, adaptive final-test optimizer or evidence admission path.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import random
from datetime import date
from pathlib import Path
from typing import Any

from src.research.cloud_exchange import ExchangeError

SCHEMA = "p2_e2_model_search_campaign_v1"
PARAMS = {
    "xgboost": {"max_depth", "learning_rate", "num_boost_round"},
    "lightgbm": {"max_depth", "learning_rate", "num_boost_round", "num_leaves", "min_data_in_leaf"},
    "momentum_20d": set(),
}


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _common_history(spec: dict, data_root: Path, sessions: list[str], last: date) -> dict:
    import yaml
    symbols = yaml.safe_load((data_root / "configs/research_universes/us_selected_equities_v2.yaml").read_text(encoding="utf-8"))["symbols"]
    dates = []
    for symbol in [*symbols, "QQQ"]:
        doc = json.loads((data_root / f"data/research/market_evidence/us/symbols/{symbol}.json").read_text(encoding="utf-8"))
        dates.append({bar["time"] for bar in doc["bars"]})
    common = set.intersection(*dates)
    required = {s for s in sessions if spec["study"]["train_start"] <= s <= str(last)}
    if not required.issubset(common):
        raise ExchangeError("full-pool common history does not cover campaign/holdout sessions")
    return {"common_first": min(common), "common_last": max(common), "common_sessions": len(common)}


def compile_campaign(spec: dict, data_root: Path | None = None) -> dict:
    from src.research import colab_experiment_batch as core
    from src.research.study_workspace import DEFAULT_XGB_CONFIG
    import exchange_calendars as xc

    if spec.get("schema_version") != SCHEMA or spec.get("selection_metric") != "median_validation_net_excess":
        raise ExchangeError("unsupported campaign/selection contract")
    optimization = spec.get("optimization", {})
    if (optimization.get("method") != "seeded_random_without_replacement" or
            type(optimization.get("seed")) is not int or
            type(optimization.get("max_configurations")) is not int or
            type(spec.get("max_trials")) is not int or
            not 1 <= optimization.get("max_configurations", 0) <= 50 or
            not 1 <= spec.get("max_trials", 0) <= 1000):
        raise ExchangeError("explicit bounded search configuration required")
    holdout = spec.get("final_holdout", {})
    try:
        first, last = (date.fromisoformat(holdout[k]) for k in ("start_date", "end_date"))
    except (KeyError, ValueError, TypeError) as exc:
        raise ExchangeError("explicit reserved final holdout dates required") from exc
    if (first > last or str(last) > "2026-08-04" or
            holdout.get("prior_consumption_status") != "NOT_CERTIFIED" or
            spec["study"]["as_of_cutoff"] >= str(first)):
        raise ExchangeError("holdout must be excluded from all search cutoffs; prior use not certified")
    # The existing v1 validator remains the authority for source, pool, date,
    # reference, seed and research boundaries. Only candidate expansion differs.
    proto = {k: v for k, v in spec.items() if k in (
        "batch_id", "runner_git_sha", "v5_bundle_manifest_sha256", "history_archive_sha256",
        "purpose", "study", "validation_folds", "seeds")}
    proto.update(schema_version=core.SCHEMA, search_space={"max_depth": [3]}, max_trials=100)
    skeleton = core.plan(proto, data_root)
    for fold in spec["validation_folds"]:
        if fold["test_end"] >= str(first):
            raise ExchangeError("validation enters reserved final holdout")
    embargo = spec.get("minimum_embargo_sessions")
    if type(embargo) is not int or not 5 <= embargo <= 20:
        raise ExchangeError("5..20 exchange-session embargo required")
    calendar = xc.get_calendar("XNYS", start=spec["study"]["train_start"], end=str(last))
    sessions = [s.strftime("%Y-%m-%d") for s in calendar.sessions]
    for fold in spec["validation_folds"]:
        if sum(fold["train_end"] < s < fold["test_start"] for s in sessions) < embargo:
            raise ExchangeError("training/validation embargo is insufficient")
    feature_sets = spec.get("feature_sets", {})
    allowed_features = set(DEFAULT_XGB_CONFIG.features)
    if not feature_sets or any(not isinstance(v, list) or not v or any(not isinstance(f, str) for f in v) or len(set(v)) != len(v) or
                               set(v) - allowed_features for v in feature_sets.values()):
        raise ExchangeError("feature sets require unique supported OHLCV feature IDs")
    candidates = spec.get("candidates")
    if not isinstance(candidates, list) or not candidates or len(candidates) > 12:
        raise ExchangeError("explicit small candidate list required")
    rng = random.Random(optimization["seed"])
    configurations, seen_ids, seen_configs = [], set(), set()
    for candidate in candidates:
        if set(candidate) != {"candidate_id", "model_family", "feature_set", "phase", "search_space",
                              "configuration_budget", "fixed_params", "cost_bps", "slippage_bps"}:
            raise ExchangeError("candidate fields mismatch")
        cid, family = candidate["candidate_id"], candidate["model_family"]
        if not core.NAME.fullmatch(cid) or cid in seen_ids or family not in PARAMS:
            raise ExchangeError("invalid/duplicate candidate identity or model family")
        seen_ids.add(cid)
        if candidate["feature_set"] not in feature_sets or candidate["phase"] not in ("search", "baseline", "ablation", "stress"):
            raise ExchangeError("unsupported candidate feature set/phase")
        features = feature_sets[candidate["feature_set"]]
        if family == "momentum_20d" and features != ["return_20d"]:
            raise ExchangeError("momentum baseline must declare exactly return_20d")
        grid, fixed = candidate["search_space"], candidate["fixed_params"]
        if (not isinstance(grid, dict) or not isinstance(fixed, dict) or
                (set(grid) | set(fixed)) - PARAMS[family] or set(grid) & set(fixed)):
            raise ExchangeError("unsupported model-family parameter")
        for key, values in {**{k: [v] for k, v in fixed.items()}, **grid}.items():
            if not isinstance(values, list) or not values or len(values) > 12 or len(set(values)) != len(values):
                raise ExchangeError("invalid finite search dimension")
            for value in values:
                if type(value) not in (int, float) or not (
                    0 < value <= 1 if key == "learning_rate" else
                    type(value) is int and 1 <= value <= (8 if key == "max_depth" else 500)):
                    raise ExchangeError("search parameter exceeds bounded model budget")
        if any(type(candidate[k]) not in (int, float) or not 0 <= candidate[k] <= 100 for k in ("cost_bps", "slippage_bps")):
            raise ExchangeError("invalid predeclared cost scenario")
        keys = sorted(grid)
        combos = list(itertools.product(*(grid[k] for k in keys)))
        budget = candidate["configuration_budget"]
        if type(budget) is not int or not 1 <= budget <= min(50, len(combos)):
            raise ExchangeError("configuration budget exceeds candidate search space")
        for index, values in enumerate(rng.sample(combos, budget)):
            defaults = {} if family == "momentum_20d" else {
                k: v for k, v in spec["study"]["xgb_params"].items() if k != "seed"}
            params = {**defaults, **fixed, **dict(zip(keys, values))}
            identity = _sha([family, params, features, candidate["cost_bps"], candidate["slippage_bps"]])
            if identity in seen_configs:
                raise ExchangeError("duplicate model configuration; do not count identical fits twice")
            seen_configs.add(identity)
            configurations.append({"configuration_id": f"{cid}-p{index:02}", "candidate_id": cid,
                "model_family": family, "feature_set": candidate["feature_set"], "features": features,
                "phase": candidate["phase"], "params": params,
                "cost_bps": candidate["cost_bps"], "slippage_bps": candidate["slippage_bps"]})
    if len(configurations) > optimization["max_configurations"]:
        raise ExchangeError("campaign exceeds total configuration budget")
    trials = []
    groups = [[c for c in configurations if c["candidate_id"] == candidate["candidate_id"]]
              for candidate in candidates]
    schedule = [group[index] for index in range(max(map(len, groups)))
                for group in groups if index < len(group)]
    for template in skeleton["trials"]:
        for configuration in schedule:
            study = {**template["study"], "features": configuration["features"],
                "cost_bps": configuration["cost_bps"], "slippage_bps": configuration["slippage_bps"],
                "xgb_params": {**configuration["params"], "seed": template["seed"]}}
            if configuration["model_family"] != "xgboost":
                study["model_family"] = configuration["model_family"]
            digest = _sha(study)
            trials.append({"trial_id": f'{configuration["configuration_id"]}-{template["fold_id"]}-s{template["seed"]}-{digest[:12]}',
                "fold_id": template["fold_id"], "seed": template["seed"],
                "configuration_id": configuration["configuration_id"], "candidate_id": configuration["candidate_id"],
                "params": configuration["params"], "study": study, "study_sha256": digest})
    if len(trials) > spec["max_trials"]:
        raise ExchangeError("campaign exceeds fit-task budget")
    availability = _common_history(spec, data_root, sessions, last) if data_root is not None else None
    return {**skeleton, "schema_version": SCHEMA, "run_id": _sha(spec),
        "batch_spec_sha256": _sha(spec), "trial_count": len(trials), "trials": trials,
        "configurations": configurations, "configuration_count": len(configurations),
        "final_holdout": holdout, "holdout_evaluated": False, "minimum_embargo_sessions": embargo,
        "selection_metric": spec["selection_metric"], "source_availability": availability,
        "multiple_comparison_warning": "Many dependent fold/seed trials do not add independent history or certify alpha."}


def comparison_report(batch_spec: Path, data_root: Path, output_root: Path) -> dict:
    """Derive validation-only tables; never run or rank on the final holdout."""
    import statistics
    from src.research import colab_experiment_batch as core
    batch, symbols = core._inputs(batch_spec, data_root)
    if batch["schema_version"] != SCHEMA:
        raise ExchangeError("comparison requires a model-search campaign")
    core._output_files(batch, symbols, output_root)
    rows = []
    for cfg in batch["configurations"]:
        trials = [t for t in batch["trials"] if t["configuration_id"] == cfg["configuration_id"]]
        observations, blocked = [], 0
        for trial in trials:
            directory = output_root / batch["batch_id"] / "trials" / trial["trial_id"]
            if not (directory / "trial-result.json").exists():
                continue
            status = core._trial_status(directory, trial, batch, {**trial["study"], "symbols": symbols})
            if status == "ready":
                observations.append(json.loads((directory / "study-receipt.json").read_text(encoding="utf-8")))
            else:
                blocked += 1
        complete = len(observations) == len(trials)
        rows.append({k: cfg[k] for k in ("configuration_id", "candidate_id", "model_family", "feature_set", "phase", "params", "cost_bps", "slippage_bps")} | {
            "planned_tasks": len(trials), "ready_tasks": len(observations), "blocked_tasks": blocked,
            "complete": complete, "eligible_for_validation_ranking": complete and cfg["phase"] == "search",
            "median_validation_net_excess": statistics.median(r["overall_oos_net_excess_return"] for r in observations) if observations else None,
            "worst_validation_drawdown": min((r["overall_oos_max_drawdown"] for r in observations), default=None),
            "median_validation_rank_ic": statistics.median(r["rank_ic"] for r in observations) if observations else None})
    ranking = sorted((r for r in rows if r["eligible_for_validation_ranking"]),
                     key=lambda r: (-r["median_validation_net_excess"], r["configuration_id"]))
    return {"schema_version": "p2_e2_validation_comparison_v1", "run_id": batch["run_id"],
        "selection_metric": batch["selection_metric"], "configurations": rows,
        "validation_ranking": [r["configuration_id"] for r in ranking],
        "final_holdout": batch["final_holdout"], "holdout_evaluated": False,
        "model_promoted": False, "trade_ready": False, "pit_certified": False,
        "review_status": "incoming_unreviewed", "research_only": True,
        "limitations": [batch["multiple_comparison_warning"],
            "Medians across dependent folds/seeds are descriptive and do not certify alpha or independent test performance."]}
