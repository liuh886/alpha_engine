"""E5 read-only E4 parity, canonical portfolio ledger and delayed-close research.

Reconstruction is a separate pinned-native subprocess. This evaluator never
fits a model and never treats the archived Top5 strings as executed positions.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import warnings
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from src.research.e5_score_reconstruction import (
    ARCHIVE_SHA, DRIVER_SHA, INDEX_SHA, NATIVE_SHA, PLAN_SHA, SHORTLIST,
    sha, verify_snapshot, write_json,
)
from src.research.portfolio_ledger import replay_ledger, summarize_ledger


def read_e4(path: Path) -> tuple[dict, dict]:
    raw = path.read_bytes()
    if len(raw) > 25_000_000 or hashlib.sha256(raw).hexdigest() != ARCHIVE_SHA:
        raise ValueError("E4 archive differs from independently pinned source")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        if len(z.namelist()) != len(set(z.namelist())) or z.testzip() is not None:
            raise ValueError("E4 CRC or member uniqueness failed")
        if sha_bytes(z.read("index.json")) != INDEX_SHA or sha_bytes(z.read("plan.json")) != PLAN_SHA:
            raise ValueError("E4 index/plan SHA mismatch")
        plan = json.loads(z.read("plan.json"))
        index = json.loads(z.read("index.json"))
        tasks = {t["task_id"]: t for t in plan["tasks"]}
        if set(tasks) != set(index["record_hashes"]) or len(tasks) != 288:
            raise ValueError("E4 frozen task inventory mismatch")
        expected = {"index.json", "plan.json"} | {f"records/{t}.json" for t in tasks}
        if set(z.namelist()) != expected:
            raise ValueError("unexpected E4 archive contents")
        records = {}
        for tid, digest in index["record_hashes"].items():
            content = z.read(f"records/{tid}.json")
            if sha_bytes(content) != digest:
                raise ValueError("E4 record SHA mismatch")
            rec = json.loads(content)
            if rec["task_id"] != tid or rec["status"] != "ready":
                raise ValueError("unready E4 record")
            records[(rec["configuration_id"], rec["fold_id"])] = rec
        return plan, records


def sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def compare_e4(daily: pd.DataFrame, summary: dict, record: dict) -> dict:
    """Reject parity failure before evaluating any new execution hypothesis."""
    old = pd.DataFrame(record["daily_trace"])
    if daily["date"].tolist() != old["date"].tolist():
        raise ValueError("E4 parity failed: return sessions differ")
    errors = {}
    for key in ("gross", "net", "turnover", "qqq"):
        error = np.abs(daily[key].to_numpy()-old[key].to_numpy())
        errors[key] = float(error.max())
        if not np.isfinite(error).all() or errors[key] > 5.1e-11:
            bad = int(np.argmax(error))
            raise ValueError(f"E4 parity failed: {key} {daily.iloc[bad]['date']} max_error={errors[key]}")
    for actual, archived in (("net_return", "net_cumulative_return"),
                             ("qqq_return", "qqq_cumulative_return"),
                             ("net_excess", "net_excess_return"),
                             ("max_drawdown", "max_drawdown"), ("turnover", "total_turnover")):
        if abs(summary[actual]-record[archived]) > 5.1e-9:
            raise ValueError(f"E4 aggregate parity failed: {actual}")
    return {"status": "E4_DAILY_AND_AGGREGATE_PARITY_PASS", "daily_max_abs_errors": errors,
            "daily_rounding_tolerance": 5.1e-11, "aggregate_rounding_tolerance": 5.1e-9}


def latency_scores(scores: pd.DataFrame, sessions: list[str],
                   source_calendar: list[str]) -> tuple[pd.DataFrame, dict[str, str]]:
    """Prior-session closing information executed at the next session close proxy."""
    mapping = {}
    for fill in sessions:
        pos = source_calendar.index(fill)
        if pos < 1:
            raise ValueError("latency needs an earlier information session")
        mapping[fill] = source_calendar[pos-1]
    shifted = scores.loc[list(mapping.values())].copy()
    shifted.index = sessions
    return shifted, mapping


def rank_ic(scores: pd.DataFrame, prices: pd.DataFrame,
            oos_dates: list[str]) -> dict:
    """Target-matched IC: restrict signal AND maturity to the declared OOS fold."""
    results = {}
    calendar = list(prices.index)
    for horizon in (1, 5):
        values, skipped = [], 0
        for signal in oos_dates:
            pos = calendar.index(signal)
            if pos+horizon >= len(calendar) or calendar[pos+horizon] > oos_dates[-1]:
                skipped += 1
                continue
            forward = prices.loc[calendar[pos+horizon]]/prices.loc[signal]-1
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                value = float(spearmanr(scores.loc[signal], forward).statistic)
            if np.isfinite(value):
                values.append(value)
        results[f"rank_ic_{horizon}d"] = {"mean": float(np.mean(values)) if values else None,
            "mature_oos_labels": len(values), "immature_excluded": skipped,
            "label_end_no_later_than": oos_dates[-1]}
    return results


def score_diagnostics(scores: pd.DataFrame, sessions: list[str],
                      assets: pd.DataFrame, record: dict) -> dict:
    values = np.sort(scores.loc[sessions[:-1]].to_numpy(), axis=1)
    ties = int((values[:, -5] == values[:, -6]).sum())
    # Comparison only: the archived strings never drive the ledger or portfolio.
    held = {date: set(group.loc[group["simulated_held_weight"] > 0, "symbol"])
            for date, group in assets.groupby("date")}
    mismatches = sum(set(row["top5_signal_symbols"]) != held[row["date"]]
                     for row in record["top5_score_signals_not_executed_trades"])
    return {"decision_dates": len(values), "top5_cutoff_tied_decisions": ties,
            "published_signal_set_differs_from_engine_holdings_dates": mismatches,
            "tie_policy": "UNCHANGED_E4_np.argsort_ascending_default_last5",
            "published_signal_policy": "stable_descending_not_engine_tie_policy"}


def review_one(*, snapshot: Path, scores_root: Path, record: dict,
               output: Path) -> dict:
    cfg, fold = record["configuration_id"], record["fold_id"]
    source = verify_snapshot(snapshot)
    score_root = scores_root / cfg / fold
    receipt = json.loads((score_root / "score-receipt.json").read_bytes())
    if (receipt["score_sha256"] != sha(score_root / "scores.parquet") or
            receipt["snapshot_receipt_sha256"] != sha(snapshot / "snapshot.json") or
            receipt["configuration"] != record["config"] or receipt["fold_id"] != fold or
            receipt["native_git_sha"] != NATIVE_SHA or receipt["driver_sha256"] != DRIVER_SHA or
            receipt["plan_sha256"] != PLAN_SHA):
        raise ValueError("score provenance differs from frozen E4 identity")
    prices = pd.read_parquet(snapshot / "close.parquet")
    qqq = pd.read_parquet(snapshot / "qqq.parquet")["close"]
    scores = pd.read_parquet(score_root / "scores.parquet")
    if scores.columns.tolist() != source["symbols"] or scores.columns.tolist() != prices.columns.tolist():
        raise ValueError("score/source universe mismatch")
    dates = [d["date"] for d in record["daily_trace"]]
    calendar = list(prices.index)
    anchor = calendar[calendar.index(dates[0])-1]
    sessions = [anchor, *dates]
    daily, assets = replay_ledger(scores=scores, prices=prices, qqq=qqq, sessions=sessions)
    original = summarize_ledger(daily, assets)
    parity = compare_e4(daily, original, record)
    # Do not write an accepted ledger or run delayed mode until parity has passed.
    output.mkdir(parents=True, exist_ok=False)
    daily.to_parquet(output / "original-daily.parquet", index=False)
    assets.to_parquet(output / "original-assets.parquet", index=False)
    delayed, mapping = latency_scores(scores, sessions, calendar)
    ld, la = replay_ledger(scores=delayed, prices=prices, qqq=qqq, sessions=sessions,
                           signal_sessions=mapping, mode="delayed_close_1session")
    ld.to_parquet(output / "delayed-daily.parquet", index=False)
    la.to_parquet(output / "delayed-assets.parquet", index=False)
    result = {"configuration_id": cfg, "fold_id": fold, "parity": parity,
              "original": original, "delayed": summarize_ledger(ld, la),
              "signal_ic": rank_ic(scores, prices, dates),
              "score_diagnostics": score_diagnostics(scores, sessions, assets, record),
              "score_receipt_sha256": sha(score_root / "score-receipt.json"),
              "source_snapshot_sha256": sha(snapshot / "snapshot.json"),
              "evaluator_git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"],
                  cwd=Path(__file__).resolve().parents[2], text=True).strip(),
              "evaluator_code_sha256": {name: sha(Path(__file__).parent / name) for name in
                  ("e5_execution_review.py", "portfolio_ledger.py", "walkforward/pipeline.py")},
              "execution_assumptions": {
                  "original": "after-close features filled at same close: idealized E4 only",
                  "delayed": "after-close t information, instruction before t+1 close, sourced adjusted t+1 close proxy",
                  "timestamp_resolution": "exchange session and phase; no invented intraday timestamps",
                  "actual_fill_observed": False, "price": source["price_semantics"],
                  "end_of_fold": "both modes liquidate at identical final close under E4 convention",
                  "cash_fee_funding": "not modelled by E4; normalized quantities only"},
              "research_only": True, "trade_ready": False, "pit_certified": False}
    result["files"] = {name: sha(output / name) for name in
                       ("original-daily.parquet", "original-assets.parquet",
                        "delayed-daily.parquet", "delayed-assets.parquet")}
    write_json(output / "result.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checkpoint", type=Path, required=True)
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--scores-root", type=Path, required=True)
    p.add_argument("--configuration", choices=SHORTLIST, required=True)
    p.add_argument("--fold", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        if args.output.resolve().is_relative_to(Path(__file__).resolve().parents[2]):
            raise ValueError("private results must be outside checkout")
        _, records = read_e4(args.checkpoint)
        result = review_one(snapshot=args.snapshot, scores_root=args.scores_root,
                            record=records[(args.configuration, args.fold)], output=args.output)
        print(json.dumps({"status": result["parity"]["status"],
                          "original": result["original"]["net_return"],
                          "delayed": result["delayed"]["net_return"]}))
        return 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        print(f"BLOCKED_E5: {exc}", file=sys.stderr)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
