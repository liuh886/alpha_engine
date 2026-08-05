"""Run one bounded CN130 ranking batch for one half-year window."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

import src.research.cn130_ranking_pipeline as core
from src.research.cn130_cross_sectional_ranking import (
    attach_classification,
    build_feature_matrices,
    forward_returns,
    load_provider_panel,
    make_label,
    predict_ranker,
    rank_metrics,
    score_stability,
    stack_return_frame,
)

WINDOWS = {
    "2024H1": ("2024-01-01", "2024-06-30"),
    "2024H2": ("2024-07-01", "2024-12-31"),
    "2025H1": ("2025-01-01", "2025-06-30"),
    "2025H2": ("2025-07-01", "2025-12-31"),
    "2026H1": ("2026-01-01", "2026-06-30"),
    "2026H2_PARTIAL": ("2026-07-01", "2026-12-31"),
}
BATCHES = {
    "r0r1": ["r0_cn_x1_0_raw_return_rank", "r1_benchmark_relative_rank"],
    "r2": ["r2_industry_relative_rank"],
    "r3": ["r3_risk_residual_rank"],
    "r4": ["r4_two_stage_hierarchical_rank"],
}


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(core.clean_json(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    output = frame.copy()
    for column in output.columns:
        if pd.api.types.is_datetime64_any_dtype(output[column]):
            output[column] = output[column].dt.strftime("%Y-%m-%d")
    output.to_csv(
        path,
        index=False,
        compression={"method": "gzip", "mtime": 0} if path.suffix == ".gz" else None,
        float_format="%.10g",
        lineterminator="\n",
    )


def run(root: Path, provider_dir: Path, output_dir: Path, window_label: str, batch: str) -> None:
    universe = load_yaml(root / "configs/research_universes/cn_selected_equities_v3.yaml")
    classification = load_yaml(root / "configs/research_classifications/cn130_sector_industry_v1.yaml")["symbols"]
    symbols = [str(x) for x in universe["symbols"]]
    panel = load_provider_panel(provider_dir, [*symbols, core.BENCHMARK])
    families, metadata_parts = build_feature_matrices(panel, symbols=symbols, benchmark=core.BENCHMARK)
    controls = core.risk_controls(metadata_parts)
    combined_metadata = (
        metadata_parts["beta_60"]
        .join(metadata_parts["realized_volatility_20"], how="outer")
        .join(metadata_parts["trailing_amount_20"], how="outer")
        .join(metadata_parts["momentum_20"], how="outer")
        .join(metadata_parts["price_to_ma50"], how="outer")
    )
    combined_metadata["log_trailing_amount_20"] = np.log(combined_metadata["trailing_amount_20"].where(combined_metadata["trailing_amount_20"] > 0.0))
    close = panel.fields["close"]
    raw_returns = stack_return_frame(forward_returns(close[symbols], horizon=10), "raw_forward_return")
    execution_returns = stack_return_frame(forward_returns(close[symbols], horizon=10, delay=1), "execution_forward_return")
    benchmark_raw = forward_returns(close[[core.BENCHMARK]], horizon=10)[core.BENCHMARK]

    requested_start, requested_end = WINDOWS[window_label]
    dates = panel.calendar[(panel.calendar >= requested_start) & (panel.calendar <= requested_end)]
    if len(dates) < 2:
        raise ValueError(f"window {window_label} has no data")
    window = core.WindowSpec(window_label, dates.min(), dates.max(), window_label in {x[0] for x in core.SELECTION_WINDOWS})
    train_dates = core.purged_training_dates(panel.calendar, window.start)
    test_dates = core.eligible_test_dates(panel.calendar, window.start, window.end)
    train_raw = core.slice_dates(raw_returns, train_dates)
    test_raw = core.slice_dates(raw_returns, test_dates)
    test_execution = core.slice_dates(execution_returns, test_dates)
    test_metadata = core.slice_dates(combined_metadata, test_dates)
    targets = {
        "raw": make_label(train_raw, mode="raw", benchmark_returns=benchmark_raw, classification=classification),
        "benchmark_relative": make_label(train_raw, mode="benchmark_relative", benchmark_returns=benchmark_raw, classification=classification),
        "sector_relative": make_label(train_raw, mode="sector_relative", benchmark_returns=benchmark_raw, classification=classification),
    }
    if batch == "r3":
        targets["risk_residual_partial"] = make_label(train_raw, mode="risk_residual_partial", benchmark_returns=benchmark_raw, classification=classification, risk_controls=controls)

    score_cache: dict[tuple[str, str], pd.DataFrame] = {}
    summaries: list[dict[str, Any]] = []
    for ranking_id in BATCHES[batch]:
        for family in core.candidate_families(ranking_id):
            train_x = core.slice_dates(families[family], train_dates)
            test_x = core.slice_dates(families[family], test_dates)
            if ranking_id == "r1_benchmark_relative_rank":
                scores = score_cache[("r0_cn_x1_0_raw_return_rank", family)].copy()
            else:
                scores = core.fit_predict_cell(
                    ranking_id=ranking_id,
                    train_features=train_x,
                    test_features=test_x,
                    train_target=targets[core.target_mode(ranking_id)],
                    classification=classification,
                    seed=42,
                )
                score_cache[(ranking_id, family)] = scores
            metrics, daily = rank_metrics(scores, test_raw, classification=classification)
            metrics.update(score_stability(scores, top_k=15, rebalance_every=10))
            status = "ineligible_partial_r3" if ranking_id == "r3_risk_residual_rank" else "eligible"
            summary = {
                "ranking_id": ranking_id,
                "feature_family": family,
                "window": window_label,
                "target_status": status,
                **metrics,
            }
            summaries.append(summary)
            daily["ranking_id"] = ranking_id
            daily["feature_family"] = family
            daily["window"] = window_label
            write_csv(output_dir / "daily" / f"{window_label}__{ranking_id}__{family}.csv.gz", daily)

            ledger = scores.join(test_raw).join(test_execution).join(test_metadata)
            ledger = ledger.join(attach_classification(ledger.index, classification)).reset_index()
            ledger["ranking_id"] = ranking_id
            ledger["feature_family"] = family
            ledger["window"] = window_label
            ledger["target_status"] = status
            ledger["cross_sectional_rank"] = ledger.groupby("datetime")["score"].rank(method="first", ascending=False)
            ledger["benchmark_raw_return"] = ledger["datetime"].map(benchmark_raw)
            ledger["benchmark_relative_return"] = ledger["raw_forward_return"] - ledger["benchmark_raw_return"]
            ledger["sector_relative_return"] = ledger["raw_forward_return"] - ledger.groupby(["datetime", "sector"])["raw_forward_return"].transform("median")
            lifecycle_start = ledger["instrument"].map(panel.lifecycle["start"])
            lifecycle_end = ledger["instrument"].map(panel.lifecycle["end"])
            ledger["lifecycle_status"] = np.where((ledger["datetime"] >= lifecycle_start) & (ledger["datetime"] <= lifecycle_end), "active", "outside_lifecycle")
            ledger["tradability_status"] = np.where(ledger["execution_forward_return"].notna(), "return_available", "unavailable")
            write_csv(output_dir / "score_ledgers" / f"{window_label}__{ranking_id}__{family}.csv.gz", ledger)
            print(f"{window_label} {ranking_id} {family}: rank_ic={metrics['mean_rank_ic']:.4f} spread={metrics['mean_top_bottom_spread']:.4f}", flush=True)

    write_json(output_dir / "summaries" / f"{window_label}__{batch}.json", summaries)
    if batch == "r0r1":
        identity = core.label_rank_identity(targets["raw"], targets["benchmark_relative"])
        identity["window"] = window_label
        write_json(output_dir / "equivalence" / f"{window_label}.json", identity)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--window", choices=sorted(WINDOWS), required=True)
    parser.add_argument("--batch", choices=sorted(BATCHES), required=True)
    args = parser.parse_args()
    run(args.root.resolve(), args.provider_dir.resolve(), args.output_dir.resolve(), args.window, args.batch)


if __name__ == "__main__":
    main()
