"""Rebuild only missing E4 shortlist scores using the pinned private E4 driver.

Run this file as a subprocess so native model/data imports come exclusively from
the frozen checkout. Original model binaries were not archived: these are recipe
reconstructions, accepted only after independent daily E4 trace parity.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import platform
import subprocess
import sys
from pathlib import Path

PLAN_SHA = "5146093d121b2fc2fa291450dea3ef7b0a2cf7d00ab26dc44dec8d771eddb2c5"
DRIVER_SHA = "ff44d808be2f3391d9216f824c6e14f836803d56355131b680de66999615c62c"
NATIVE_SHA = "0c8152496ebeeed559ceab9b095594501fca516b"
ARCHIVE_SHA = "f689d5494dcec4022218acadc94768e3e669ed308dadc331d660ba60091551d4"
INDEX_SHA = "c8c6a4446f4eacb3adb3a7e03a7077ea9febb0102651c3c0339fd10f9dc11dc4"
SHORTLIST = ("xgb_p03", "lgb_p05", "rule_momentum60", "rule_momentum120")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, obj: dict) -> None:
    with path.open("x", encoding="utf-8") as out:
        json.dump(obj, out, indent=2, sort_keys=True, allow_nan=False)
        out.write("\n")


def verify_snapshot(root: Path) -> dict:
    receipt = json.loads((root / "snapshot.json").read_bytes())
    if sha(root / "plan.json") != PLAN_SHA:
        raise ValueError("source plan differs from the frozen E4 plan")
    if set(receipt["files"]) != {"close.parquet", "volume.parquet", "qqq.parquet", "plan.json"}:
        raise ValueError("unexpected or missing snapshot component")
    plan = json.loads((root / "plan.json").read_bytes())
    if (receipt["source_history_sha256"] != plan["v6_history_archive_sha256"] or
            receipt["source_manifest_sha256"] != plan["v6_bundle_manifest_sha256"] or
            receipt["symbols"] != plan["symbols"] or receipt["sessions"] != 1466 or
            receipt["native_git_sha"] != NATIVE_SHA or receipt["driver_sha256"] != DRIVER_SHA):
        raise ValueError("snapshot source identity mismatch")
    for name, digest in receipt["files"].items():
        if sha(root / name) != digest:
            raise ValueError("source snapshot hash mismatch")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("snapshot", "scores"))
    parser.add_argument("--native-root", type=Path, required=True)
    parser.add_argument("--driver", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--stage-root", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--configuration", choices=SHORTLIST)
    parser.add_argument("--fold")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    for target in (args.snapshot if args.action == "snapshot" else args.output,):
        if target is not None and target.resolve().is_relative_to(Path(__file__).resolve().parents[2]):
            raise ValueError("private data must be outside checkout")
    root = args.native_root.resolve()
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if actual != NATIVE_SHA or sha(args.driver) != DRIVER_SHA:
        raise ValueError("frozen native checkout or E4 driver identity mismatch")
    subprocess.run(["git", "diff", "--exit-code", "HEAD", "--", "src", "pyproject.toml", "uv.lock"], cwd=root, check=True)
    sys.path.insert(0, str(root))
    import numpy as np
    import pandas as pd
    import xgboost
    import lightgbm
    from src.data import research_slice
    if not Path(research_slice.__file__).resolve().is_relative_to(root):
        raise ValueError("native import escaped frozen checkout")
    spec = importlib.util.spec_from_file_location("pinned_private_e4_driver", args.driver)
    if spec is None or spec.loader is None:
        raise ValueError("cannot load pinned E4 driver")
    driver = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(driver)
    environment = {"python": platform.python_version(), "platform": platform.platform(),
                   "numpy": np.__version__, "pandas": pd.__version__,
                   "xgboost": xgboost.__version__, "lightgbm": lightgbm.__version__}
    provenance = {"native_git_sha": actual, "driver_sha256": DRIVER_SHA,
                  "reconstructor_sha256": sha(Path(__file__)), "environment": environment}
    if args.action == "snapshot":
        if args.plan is None or args.stage_root is None or sha(args.plan) != PLAN_SHA:
            raise ValueError("snapshot requires pinned E4 plan and verified v6 stage")
        p = json.loads(args.plan.read_bytes())
        close, volume, qqq = driver.market_data(stage_root=args.stage_root, p=p)
        args.snapshot.mkdir(parents=True, exist_ok=False)
        (args.snapshot / "plan.json").write_bytes(args.plan.read_bytes())
        close.to_parquet(args.snapshot / "close.parquet")
        volume.to_parquet(args.snapshot / "volume.parquet")
        qqq.to_frame("close").to_parquet(args.snapshot / "qqq.parquet")
        write_json(args.snapshot / "snapshot.json", provenance | {
            "source_history_sha256": p["v6_history_archive_sha256"],
            "source_manifest_sha256": p["v6_bundle_manifest_sha256"],
            "price_semantics": "v6_anchored_adjusted_Yahoo_total_return_close_not_raw_executable_quote",
            "symbols": p["symbols"], "sessions": len(close),
            "files": {name: sha(args.snapshot / name) for name in
                      ("plan.json", "close.parquet", "volume.parquet", "qqq.parquet")}})
        print("VERIFIED_SOURCE_SNAPSHOT_WRITTEN")
        return 0
    receipt = verify_snapshot(args.snapshot)
    p = json.loads((args.snapshot / "plan.json").read_bytes())
    if args.configuration is None or args.output is None or args.fold not in {f["id"] for f in p["folds"]}:
        raise ValueError("scores require an approved configuration, fold and fresh output")
    close = pd.read_parquet(args.snapshot / "close.parquet")
    volume = pd.read_parquet(args.snapshot / "volume.parquet")
    features = driver.feature_panels(close, volume)
    fold = driver.prepare_fold(args.fold, p, close, features)
    # One extra earlier anchor supports a distinct one-session execution latency.
    anchor_pos = list(close.index).index(fold["eval_sessions"][0])
    extended = [close.index[anchor_pos-1], *fold["eval_sessions"]]
    fold["eval_sessions"] = extended
    fold["X_eval"] = pd.DataFrame(np.column_stack([
        features[name].loc[extended, p["symbols"]].to_numpy(dtype="float64").reshape(-1)
        for name in driver.BASE_FIELDS]), columns=list(driver.BASE_FIELDS))
    cfg = next(c for c in p["configurations"] if c["id"] == args.configuration)
    scores = driver.fit_score(cfg, fold, features, p["symbols"])
    args.output.mkdir(parents=True, exist_ok=False)
    pd.DataFrame(scores, index=extended, columns=p["symbols"]).to_parquet(args.output / "scores.parquet")
    write_json(args.output / "score-receipt.json", provenance | {
        "configuration": cfg, "fold_id": args.fold, "plan_sha256": PLAN_SHA,
        "snapshot_receipt_sha256": sha(args.snapshot / "snapshot.json"),
        "score_sha256": sha(args.output / "scores.parquet"),
        "X_train_sha256": hashlib.sha256(fold["X_train"].to_numpy().tobytes()).hexdigest(),
        "y_train_sha256": hashlib.sha256(fold["y_train"].to_numpy().tobytes()).hexdigest(),
        "train_end": fold["train_end"], "train_sessions": len(fold["train_sessions"]),
        "source_history_sha256": receipt["source_history_sha256"],
        "model_artifact_status": "REBUILT_FROZEN_RECIPE_ORIGINAL_BINARY_NOT_ARCHIVED",
        "model_fits": 0 if cfg["family"] == "rule" else 1,
        "research_only": True, "trade_ready": False, "pit_certified": False})
    print("REBUILT_SCORES_REQUIRES_E4_DAILY_PARITY", args.configuration, args.fold)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
