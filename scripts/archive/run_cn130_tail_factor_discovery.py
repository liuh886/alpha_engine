"""Execute CN130 frozen-tail and factor-family discovery evidence."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.research.cn130_cross_sectional_ranking import forward_returns, load_provider_panel, stack_return_frame
from src.research.cn130_tail_factor_discovery import (
    FACTOR_REGISTRY,
    PORTFOLIO_VARIANTS,
    REPORTING_WINDOWS,
    SELECTION_WINDOWS,
    build_discovery_factors,
    factor_correlation_table,
    factor_window_metrics,
    run_portfolio,
    sector_relative_factor,
    stack_wide,
)

WINDOW_DATES = {
    "2024H1": ("2024-01-01", "2024-06-30"),
    "2024H2": ("2024-07-01", "2024-12-31"),
    "2025H1": ("2025-01-01", "2025-06-30"),
    "2025H2": ("2025-07-01", "2025-12-31"),
    "2026H1": ("2026-01-01", "2026-06-30"),
    "2026H2_PARTIAL": ("2026-07-01", "2026-12-31"),
}
SCORE_CELLS = (
    ("r0_cn_x1_0_raw_return_rank", "current_cn_ohlcv"),
    ("r2_industry_relative_rank", "current_cn_ohlcv"),
    ("r2_industry_relative_rank", "momentum_reversal"),
    ("r4_two_stage_hierarchical_rank", "momentum_reversal"),
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_json_gz(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(clean(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            compressed.write(encoded)


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format="%.10g", lineterminator="\n")


def load_ledger(ledger_dir: Path, windows: tuple[str, ...], ranking_id: str, family: str) -> pd.DataFrame:
    frames = []
    for window in windows:
        path = ledger_dir / "score_ledgers" / f"{window}__{ranking_id}__{family}.csv.gz"
        frame = pd.read_csv(path, compression="gzip", dtype={"instrument": str}, parse_dates=["datetime"])
        frame["instrument"] = frame["instrument"].str.zfill(6)
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def tail_stage(ledger_dir: Path, benchmark_execution: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    reporting: list[dict[str, Any]] = []
    detail: list[dict[str, Any]] = []
    for ranking_id, family in SCORE_CELLS:
        selection_ledger = load_ledger(ledger_dir, SELECTION_WINDOWS, ranking_id, family)
        reporting_ledger = load_ledger(ledger_dir, REPORTING_WINDOWS, ranking_id, family)
        base_by_variant: dict[str, dict[int, dict[str, Any]]] = {}
        for variant in PORTFOLIO_VARIANTS:
            base_by_variant[variant.variant_id] = {}
            for cost in (10, 20, 40):
                summary, periods, holdings = run_portfolio(
                    selection_ledger,
                    benchmark_execution,
                    variant,
                    cost,
                    windows=SELECTION_WINDOWS,
                )
                summary.update({"ranking_id": ranking_id, "feature_family": family})
                base_by_variant[variant.variant_id][cost] = summary
                flat = {k: v for k, v in summary.items() if k != "window_results"}
                summaries.append(flat)
                if cost == 20:
                    top_name = summary["top_contributor_name"]
                    top_sector = summary["top_contributor_sector"]
                    leave_name, _, _ = run_portfolio(
                        selection_ledger,
                        benchmark_execution,
                        variant,
                        cost,
                        windows=SELECTION_WINDOWS,
                        excluded_name=top_name,
                    )
                    leave_sector, _, _ = run_portfolio(
                        selection_ledger,
                        benchmark_execution,
                        variant,
                        cost,
                        windows=SELECTION_WINDOWS,
                        excluded_sector=top_sector,
                    )
                    flat["leave_one_name_relative_excess"] = leave_name["relative_excess"]
                    flat["leave_one_sector_relative_excess"] = leave_sector["relative_excess"]
                    summaries[-1] = flat
                    detail.append(
                        {
                            "ranking_id": ranking_id,
                            "feature_family": family,
                            "variant_id": variant.variant_id,
                            "cost_bps": cost,
                            "window_results": summary["window_results"],
                            "top_name": top_name,
                            "top_sector": top_sector,
                            "leave_one_name_relative_excess": leave_name["relative_excess"],
                            "leave_one_sector_relative_excess": leave_sector["relative_excess"],
                            "periods": periods.to_dict(orient="records"),
                            "holdings": holdings.to_dict(orient="records"),
                        }
                    )
            for reporting_window in REPORTING_WINDOWS:
                report_summary, _, _ = run_portfolio(
                    reporting_ledger,
                    benchmark_execution,
                    variant,
                    20,
                    windows=(reporting_window,),
                )
                reporting.append(
                    {
                        "ranking_id": ranking_id,
                        "feature_family": family,
                        "window": reporting_window,
                        **{k: v for k, v in report_summary.items() if k != "window_results"},
                    }
                )

    frame = pd.DataFrame(summaries)
    reporting_frame = pd.DataFrame(reporting)
    # Complete support fields after all cost rows are available.
    twenty = frame.loc[frame["cost_bps"] == 20].copy()
    forty = frame.loc[frame["cost_bps"] == 40, ["ranking_id", "feature_family", "variant_id", "relative_excess"]].rename(columns={"relative_excess": "relative_excess_40bps"})
    twenty = twenty.merge(forty, on=["ranking_id", "feature_family", "variant_id"], how="left")
    twenty["support_gate_pass"] = (
        (twenty["positive_excess_windows"] >= 3)
        & (twenty["relative_excess"] > 0.0)
        & (twenty["relative_excess_40bps"] > 0.0)
        & (twenty["maximum_name_absolute_contribution_share"] <= 0.35)
        & (twenty["maximum_sector_absolute_contribution_share"] <= 0.55)
        & (twenty["leave_one_name_relative_excess"] > 0.0)
        & (twenty["leave_one_sector_relative_excess"] > 0.0)
    )
    global_neighbors = ["global_top3", "global_top5", "global_top8"]
    sector_neighbors = ["global_top5_sector_cap1", "global_top5_sector_cap2", "sector_3x1", "sector_4x1", "sector_5x1", "sector_3x2"]
    source_support: list[dict[str, Any]] = []
    for (ranking_id, family), group in twenty.groupby(["ranking_id", "feature_family"], sort=True):
        global_pass = int(group.loc[group["variant_id"].isin(global_neighbors), "support_gate_pass"].sum())
        sector_pass = int(group.loc[group["variant_id"].isin(sector_neighbors), "support_gate_pass"].sum())
        source_support.append(
            {
                "ranking_id": ranking_id,
                "feature_family": family,
                "global_neighbor_pass_count": global_pass,
                "sector_variant_pass_count": sector_pass,
                "tail_source_supported": global_pass >= 2 or sector_pass >= 2,
            }
        )
    decision = {
        "tail_source_support": source_support,
        "tail_signal_supported": any(row["tail_source_supported"] for row in source_support),
        "supporting_score_sources": [row for row in source_support if row["tail_source_supported"]],
    }
    return twenty.sort_values(["support_gate_pass", "relative_excess"], ascending=[False, False]), reporting_frame, detail, decision


def factor_stage(panel, symbols, classification, baseline_score: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    factors = build_discovery_factors(panel.fields, symbols, "000300")
    close = panel.fields["close"].loc[:, symbols]
    forward = stack_return_frame(forward_returns(close, horizon=10), "forward_return")["forward_return"]
    sector_map = {str(key): value["sector"] for key, value in classification.items()}
    index_template = forward.index
    sectors = pd.Series(index=index_template, data=index_template.get_level_values("instrument").map(sector_map), name="sector")
    registry = {row["factor"]: row for row in FACTOR_REGISTRY}
    factor_series: dict[str, pd.Series] = {}
    raw_for_corr: dict[str, pd.Series] = {}
    for name, wide in factors.items():
        direction = int(registry[name]["direction"])
        raw = stack_wide(wide, name) * direction
        raw_for_corr[name] = raw
        factor_series[f"{name}__global"] = raw
        factor_series[f"{name}__sector_relative"] = sector_relative_factor(raw, sectors)

    rows: list[dict[str, Any]] = []
    window_rows: list[dict[str, Any]] = []
    for factor_id, series in factor_series.items():
        factor_name, mode = factor_id.rsplit("__", 1)
        family = registry[factor_name]["family"]
        per_window = []
        for window in SELECTION_WINDOWS:
            start, end = WINDOW_DATES[window]
            metrics = factor_window_metrics(series, forward, baseline_score, start, end)
            row = {"factor_id": factor_id, "factor": factor_name, "mode": mode, "family": family, "window": window, **metrics}
            window_rows.append(row)
            per_window.append(row)
        rank_ics = [row["mean_rank_ic"] for row in per_window]
        incremental = [row["mean_incremental_rank_ic"] for row in per_window]
        spreads = [row["mean_top_bottom_spread"] for row in per_window]
        leave_one = [float(np.mean([rank_ics[j] for j in range(4) if j != i])) for i in range(4)]
        summary = {
            "factor_id": factor_id,
            "factor": factor_name,
            "mode": mode,
            "family": family,
            "mean_window_rank_ic": float(np.mean(rank_ics)),
            "mean_window_rank_icir": float(np.mean([row["rank_icir"] for row in per_window])),
            "positive_windows": int(sum(value > 0.0 for value in rank_ics)),
            "worst_window_rank_ic": float(min(rank_ics)),
            "mean_incremental_rank_ic": float(np.mean(incremental)),
            "mean_top_bottom_spread": float(np.mean(spreads)),
            "minimum_leave_one_window_mean_rank_ic": float(min(leave_one)),
        }
        summary["support_gate_pass"] = bool(
            summary["mean_window_rank_ic"] >= 0.015
            and summary["positive_windows"] >= 3
            and summary["worst_window_rank_ic"] >= -0.01
            and summary["mean_incremental_rank_ic"] >= 0.005
            and summary["mean_top_bottom_spread"] >= 0.0025
            and summary["minimum_leave_one_window_mean_rank_ic"] >= 0.005
        )
        rows.append(summary)

    factor_summary = pd.DataFrame(rows).sort_values(["support_gate_pass", "mean_window_rank_ic"], ascending=[False, False])
    factor_windows = pd.DataFrame(window_rows)

    # Family composites use equal-weight cross-sectional percentile ranks; no return-based weights.
    family_rows: list[dict[str, Any]] = []
    for mode in ("global", "sector_relative"):
        for family in sorted({row["family"] for row in FACTOR_REGISTRY}):
            members = [f"{row['factor']}__{mode}" for row in FACTOR_REGISTRY if row["family"] == family]
            frame = pd.concat([factor_series[member].rename(member) for member in members], axis=1)
            composite = frame.groupby(level="datetime", sort=False).rank(method="average", pct=True).mean(axis=1)
            per_window = []
            for window in SELECTION_WINDOWS:
                start, end = WINDOW_DATES[window]
                per_window.append(factor_window_metrics(composite, forward, baseline_score, start, end))
            rank_ics = [row["mean_rank_ic"] for row in per_window]
            incremental = [row["mean_incremental_rank_ic"] for row in per_window]
            spreads = [row["mean_top_bottom_spread"] for row in per_window]
            leave_one = [float(np.mean([rank_ics[j] for j in range(4) if j != i])) for i in range(4)]
            item = {
                "family_id": f"{family}__{mode}",
                "family": family,
                "mode": mode,
                "member_count": len(members),
                "mean_window_rank_ic": float(np.mean(rank_ics)),
                "positive_windows": int(sum(value > 0.0 for value in rank_ics)),
                "worst_window_rank_ic": float(min(rank_ics)),
                "mean_incremental_rank_ic": float(np.mean(incremental)),
                "mean_top_bottom_spread": float(np.mean(spreads)),
                "minimum_leave_one_window_mean_rank_ic": float(min(leave_one)),
            }
            item["support_gate_pass"] = bool(
                item["mean_window_rank_ic"] >= 0.015
                and item["positive_windows"] >= 3
                and item["worst_window_rank_ic"] >= -0.01
                and item["mean_incremental_rank_ic"] >= 0.005
                and item["mean_top_bottom_spread"] >= 0.0025
                and item["minimum_leave_one_window_mean_rank_ic"] >= 0.005
            )
            family_rows.append(item)
    family_summary = pd.DataFrame(family_rows).sort_values(["support_gate_pass", "mean_window_rank_ic"], ascending=[False, False])

    selection_dates = forward.index.get_level_values("datetime")
    selection_mask = (selection_dates >= "2024-01-01") & (selection_dates <= "2025-12-31")
    corr_frame = pd.concat([series.loc[selection_mask].rename(name) for name, series in raw_for_corr.items()], axis=1)
    correlation = factor_correlation_table(corr_frame)
    supported = factor_summary.loc[factor_summary["support_gate_pass"]].copy()
    nonredundant: list[str] = []
    for factor in supported["factor"].drop_duplicates():
        if all(abs(float(correlation.loc[factor, existing])) <= 0.80 for existing in nonredundant):
            nonredundant.append(factor)
    supported_families = family_summary.loc[family_summary["support_gate_pass"], "family"].nunique()
    decision = {
        "supported_factor_ids": supported["factor_id"].tolist(),
        "supported_family_ids": family_summary.loc[family_summary["support_gate_pass"], "family_id"].tolist(),
        "nonredundant_supported_factors": nonredundant,
        "supported_family_count": int(supported_families),
        "factor_model_rebuild_authorized": bool(supported_families >= 2 or len(nonredundant) >= 4),
    }
    correlation_long = correlation.stack().rename("rank_correlation").reset_index().rename(columns={"level_0": "factor_a", "level_1": "factor_b"})
    return factor_summary, factor_windows, family_summary, correlation_long, decision


def report_markdown(identity: dict[str, Any], tail: pd.DataFrame, reporting: pd.DataFrame, factor_summary: pd.DataFrame, family_summary: pd.DataFrame, decision: dict[str, Any]) -> str:
    lines = [
        "# CN130 极端尾部、行业分层与因子族探索报告",
        "",
        "> CN130成员、10日预测周期和2026-08-03 provider保持不变。2026H1与2026H2_PARTIAL仅用于报告。",
        "",
        "## 执行身份",
        "",
        f"- Provider identity: `{identity['provider_identity_sha256']}`",
        f"- Universe SHA256: `{identity['universe_sha256']}`",
        f"- Classification SHA256: `{identity['classification_sha256']}`",
        "- `research_only=true`; `trade_ready=false`。",
        "",
        "## Stage A：冻结分数尾部组合",
        "",
        "| 排序来源 | 特征族 | 组合 | 20bps相对超额 | 最大回撤 | 正窗口 | Precision@K | 名称集中 | 行业集中 | 留一名称 | 留一行业 | 40bps超额 | Gate |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in tail.itertuples(index=False):
        lines.append(
            f"| {row.ranking_id} | {row.feature_family} | {row.variant_id} | {row.relative_excess:.2%} | {row.max_drawdown:.2%} | {int(row.positive_excess_windows)}/4 | {row.precision_at_k:.1%} | {row.maximum_name_absolute_contribution_share:.1%} | {row.maximum_sector_absolute_contribution_share:.1%} | {row.leave_one_name_relative_excess:.2%} | {row.leave_one_sector_relative_excess:.2%} | {row.relative_excess_40bps:.2%} | {'PASS' if row.support_gate_pass else 'FAIL'} |"
        )
    lines.extend([
        "",
        "## 2026报告窗口（不参与选择）",
        "",
        "| 窗口 | 排序来源 | 特征族 | 组合 | 相对超额 | 最大回撤 | Precision@K |",
        "|---|---|---|---|---:|---:|---:|",
    ])
    for row in reporting.sort_values(["window", "relative_excess"], ascending=[True, False]).itertuples(index=False):
        lines.append(f"| {row.window} | {row.ranking_id} | {row.feature_family} | {row.variant_id} | {row.relative_excess:.2%} | {row.max_drawdown:.2%} | {row.precision_at_k:.1%} |")
    lines.extend([
        "",
        "## Stage B：单因子与因子族",
        "",
        "### 单因子前20",
        "",
        "| 因子 | 模式 | 因子族 | Mean Rank IC | 正窗口 | 最差窗口 | 增量IC | Mean Spread | LOO最小值 | Gate |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
    ])
    for row in factor_summary.head(20).itertuples(index=False):
        lines.append(f"| {row.factor} | {row.mode} | {row.family} | {row.mean_window_rank_ic:.4f} | {int(row.positive_windows)}/4 | {row.worst_window_rank_ic:.4f} | {row.mean_incremental_rank_ic:.4f} | {row.mean_top_bottom_spread:.2%} | {row.minimum_leave_one_window_mean_rank_ic:.4f} | {'PASS' if row.support_gate_pass else 'FAIL'} |")
    lines.extend([
        "",
        "### 因子族组合",
        "",
        "| 因子族 | 模式 | 成员数 | Mean Rank IC | 正窗口 | 最差窗口 | 增量IC | Mean Spread | Gate |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|",
    ])
    for row in family_summary.itertuples(index=False):
        lines.append(f"| {row.family} | {row.mode} | {int(row.member_count)} | {row.mean_window_rank_ic:.4f} | {int(row.positive_windows)}/4 | {row.worst_window_rank_ic:.4f} | {row.mean_incremental_rank_ic:.4f} | {row.mean_top_bottom_spread:.2%} | {'PASS' if row.support_gate_pass else 'FAIL'} |")
    lines.extend([
        "",
        "## 最终裁决",
        "",
        f"- Decision: `{decision['decision']}`",
        f"- Tail signal supported: {decision['tail']['tail_signal_supported']}",
        f"- Factor model rebuild authorized: {decision['factors']['factor_model_rebuild_authorized']}",
        f"- Supported factor IDs: {', '.join(decision['factors']['supported_factor_ids']) or 'none'}",
        f"- Supported family IDs: {', '.join(decision['factors']['supported_family_ids']) or 'none'}",
        "- 本研究不会自动创建或晋级CN x1.1。",
        "",
        "## 解释边界",
        "",
        "- Stage A使用冻结分数，只检验极端尾部与行业分散是否有经济意义。",
        "- Stage B只按IC、稳定性、增量信息与冗余筛选，不使用最终组合收益挑因子。",
        "- 静态精选池存在生存者偏差；PIT市值与基本面仍未覆盖。",
    ])
    return "\n".join(lines) + "\n"


def run(root: Path, provider_dir: Path, ledger_dir: Path, output_dir: Path) -> None:
    universe_path = root / "configs/research_universes/cn_selected_equities_v3.yaml"
    classification_path = root / "configs/research_classifications/cn130_sector_industry_v1.yaml"
    universe = yaml.safe_load(universe_path.read_text(encoding="utf-8"))
    classification = yaml.safe_load(classification_path.read_text(encoding="utf-8"))["symbols"]
    classification = {str(key).zfill(6): value for key, value in classification.items()}
    symbols = [str(value).zfill(6) for value in universe["symbols"]]
    panel = load_provider_panel(provider_dir, [*symbols, "000300"])
    benchmark_execution = forward_returns(panel.fields["close"][["000300"]], horizon=10, delay=1)["000300"]
    tail, reporting, detail, tail_decision = tail_stage(ledger_dir, benchmark_execution)

    r0 = load_ledger(ledger_dir, SELECTION_WINDOWS, "r0_cn_x1_0_raw_return_rank", "current_cn_ohlcv")
    baseline_score = r0.set_index(["datetime", "instrument"])["score"].sort_index()
    factor_summary, factor_windows, family_summary, correlations, factor_decision = factor_stage(
        panel, symbols, classification, baseline_score
    )
    if factor_decision["factor_model_rebuild_authorized"]:
        decision_name = "factor_families_supported_model_rebuild_authorized"
    elif tail_decision["tail_signal_supported"]:
        decision_name = "tail_signal_supported_factor_rebuild_required"
    else:
        decision_name = "tail_signal_not_supported_factor_rebuild_required"
    decision = {"decision": decision_name, "tail": tail_decision, "factors": factor_decision, "research_only": True, "trade_ready": False}
    manifest = json.loads((provider_dir / "provider_manifest.json").read_text(encoding="utf-8"))
    identity = {
        "provider_identity_sha256": manifest["provider_identity_sha256"],
        "provider_cutoff": manifest["calendar"]["last_day"],
        "universe_sha256": sha(universe_path),
        "classification_sha256": sha(classification_path),
        "score_ledger_files": len(list((ledger_dir / "score_ledgers").glob("*.csv.gz"))),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "tail_portfolio_selection_summary.csv", tail)
    write_csv(output_dir / "tail_portfolio_reporting_summary.csv", reporting)
    write_json_gz(output_dir / "tail_portfolio_details.json.gz", detail)
    write_csv(output_dir / "factor_summary.csv", factor_summary)
    write_csv(output_dir / "factor_window_summary.csv", factor_windows)
    write_csv(output_dir / "factor_family_summary.csv", family_summary)
    write_csv(output_dir / "factor_rank_correlations.csv", correlations)
    write_json(output_dir / "execution_identity.json", identity)
    write_json(output_dir / "decision.json", decision)
    report = report_markdown(identity, tail, reporting, factor_summary, family_summary, decision)
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    evidence_files = sorted(
        path for path in output_dir.iterdir()
        if path.is_file() and path.name != "evidence_manifest.json"
    )
    write_json(
        output_dir / "evidence_manifest.json",
        {
            "schema_version": "1.0.0",
            "experiment_id": "cn130_tail_factor_discovery_v1",
            "decision": decision,
            "files": [
                {
                    "path": path.name,
                    "sha256": sha(path),
                    "bytes": path.stat().st_size,
                }
                for path in evidence_files
            ],
            "research_only": True,
            "trade_ready": False,
        },
    )
    print(json.dumps(clean(decision), ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-dir", type=Path, required=True)
    parser.add_argument("--ledger-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run(args.root.resolve(), args.provider_dir.resolve(), args.ledger_dir.resolve(), args.output_dir.resolve())


if __name__ == "__main__":
    main()
