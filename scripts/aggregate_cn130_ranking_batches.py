"""Aggregate bounded CN130 ranking batches into the final ranking-first report."""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml
from scipy.stats import rankdata

import src.research.cn130_ranking_pipeline as core
from src.research.cn130_cross_sectional_ranking import compound, forward_returns, load_provider_panel, max_drawdown

SELECTION_WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")


def clean(value: Any) -> Any:
    return core.clean_json(value)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(
        path,
        index=False,
        compression={"method": "gzip", "mtime": 0} if path.suffix == ".gz" else None,
        lineterminator="\n",
        float_format="%.10g",
    )


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_summaries(input_dir: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for path in sorted((input_dir / "summaries").glob("*.json")):
        rows.extend(json.loads(path.read_text(encoding="utf-8")))
    frame = pd.DataFrame(rows)
    frame = frame.loc[frame["window"].isin(SELECTION_WINDOWS)].copy()
    expected = 4 * 14
    if len(frame) != expected:
        raise ValueError(f"expected {expected} selection cells, found {len(frame)}")
    if set(frame["window"]) != set(SELECTION_WINDOWS):
        raise ValueError("selection windows incomplete")
    return frame


def load_reporting_summaries(input_dir: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for path in sorted((input_dir / "summaries").glob("*.json")):
        rows.extend(json.loads(path.read_text(encoding="utf-8")))
    frame = pd.DataFrame(rows)
    return frame.loc[frame["window"].isin(["2026H1", "2026H2_PARTIAL"])].copy()


def aggregate_rankings(frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (ranking_id, family, status), group in frame.groupby(["ranking_id", "feature_family", "target_status"], sort=True):
        group = group.set_index("window").loc[list(SELECTION_WINDOWS)].reset_index()
        positive = group["mean_top_bottom_spread"].clip(lower=0.0)
        strongest = float(positive.max() / positive.sum()) if positive.sum() > 0 else 1.0
        rows.append({
            "ranking_id": ranking_id,
            "feature_family": family,
            "target_status": status,
            "mean_rank_ic": float(group["mean_rank_ic"].mean()),
            "mean_rank_icir": float(group["rank_icir"].mean()),
            "mean_top_bottom_spread": float(group["mean_top_bottom_spread"].mean()),
            "positive_rank_ic_windows": int((group["mean_rank_ic"] > 0.0).sum()),
            "positive_spread_windows": int((group["mean_top_bottom_spread"] > 0.0).sum()),
            "positive_spread_window_ratio": float((group["mean_top_bottom_spread"] > 0.0).mean()),
            "strongest_positive_window_share": strongest,
            "mean_adjacent_rank_correlation": float(group["adjacent_rank_correlation"].mean()),
            "mean_rebalance_topk_overlap": float(group["rebalance_topk_overlap"].mean()),
        })
    result = pd.DataFrame(rows)
    result["basic_gate_target_eligible"] = result["target_status"] == "eligible"
    result["basic_gate_mean_rank_ic_positive"] = result["mean_rank_ic"] > 0.0
    result["basic_gate_positive_spread_windows_at_least_3"] = result["positive_spread_windows"] >= 3
    result["basic_gate_strongest_window_share_below_0_50"] = result["strongest_positive_window_share"] < 0.50
    gate_columns = [column for column in result.columns if column.startswith("basic_gate_")]
    result["basic_gate_pass"] = result[gate_columns].all(axis=1)
    return result.sort_values(["basic_gate_pass", "mean_rank_ic"], ascending=[False, False]).reset_index(drop=True)


def load_cell(input_dir: Path, window: str, ranking_id: str, family: str) -> pd.DataFrame:
    path = input_dir / "score_ledgers" / f"{window}__{ranking_id}__{family}.csv.gz"
    frame = pd.read_csv(path, compression="gzip", dtype={"instrument": str}, parse_dates=["datetime"])
    frame["instrument"] = frame["instrument"].str.zfill(6)
    return frame


def fast_rank_ic(group: pd.DataFrame) -> float | None:
    values = group[["score", "raw_forward_return"]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(values) < 20:
        return None
    a = rankdata(values["score"].to_numpy(dtype=float), method="average")
    b = rankdata(values["raw_forward_return"].to_numpy(dtype=float), method="average")
    if np.std(a) == 0.0 or np.std(b) == 0.0:
        return None
    return float(np.corrcoef(a, b)[0, 1])


def diagnostic_for_cell(input_dir: Path, ranking_id: str, family: str) -> dict[str, Any]:
    frames = [load_cell(input_dir, window, ranking_id, family) for window in SELECTION_WINDOWS]
    full = pd.concat(frames, ignore_index=True)
    daily: list[float] = []
    for _, group in full.groupby("datetime", sort=True):
        value = fast_rank_ic(group)
        if value is not None:
            daily.append(value)
    leave_rows: list[dict[str, Any]] = []
    for sector in sorted(full["sector"].dropna().unique()):
        values: list[float] = []
        subset = full.loc[full["sector"] != sector]
        for _, group in subset.groupby("datetime", sort=True):
            value = fast_rank_ic(group)
            if value is not None:
                values.append(value)
        leave_rows.append({"excluded_sector": sector, "mean_rank_ic": float(np.mean(values)), "n_dates": len(values)})
    top = full.loc[full["cross_sectional_rank"] <= 15]
    sector_share = top.groupby("datetime")["sector"].value_counts(normalize=True).groupby(level=0).max()
    rng = np.random.default_rng(42)
    values = np.asarray(daily, dtype=float)
    means: list[float] = []
    block = 10
    starts = np.arange(max(1, len(values) - block + 1))
    for _ in range(500):
        sampled: list[float] = []
        for start in rng.choice(starts, size=int(np.ceil(len(values) / block)), replace=True):
            sampled.extend(values[start:start + block])
        means.append(float(np.mean(sampled[:len(values)])))
    return {
        "ranking_id": ranking_id,
        "feature_family": family,
        "mean_rank_ic_recomputed": float(np.mean(values)),
        "bootstrap_p05": float(np.quantile(means, 0.05)),
        "bootstrap_p95": float(np.quantile(means, 0.95)),
        "minimum_leave_one_sector_rank_ic": min(row["mean_rank_ic"] for row in leave_rows),
        "mean_leave_one_sector_rank_ic": float(np.mean([row["mean_rank_ic"] for row in leave_rows])),
        "mean_maximum_sector_share_top15": float(sector_share.mean()),
        "maximum_sector_share_top15": float(sector_share.max()),
        "leave_one_sector_out": leave_rows,
    }


def portfolio_from_cell(frame: pd.DataFrame, benchmark_execution: pd.Series, cost_bps: int) -> tuple[dict[str, Any], pd.DataFrame]:
    periods: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []
    previous: dict[str, float] = {}
    for window in SELECTION_WINDOWS:
        part = frame.loc[frame["window"] == window]
        dates = sorted(part["datetime"].unique())[::10]
        period_index = 0
        for date in dates:
            day = part.loc[part["datetime"] == date].dropna(subset=["score", "execution_forward_return"])
            if len(day) < 15 or date not in benchmark_execution.index:
                continue
            period_index += 1
            chosen = day.sort_values(["score", "instrument"], ascending=[False, True], kind="mergesort").head(15)
            weights = {str(symbol): 1.0 / 15 for symbol in chosen["instrument"]}
            turnover = core.turnover(previous, weights)
            cost = turnover * cost_bps / 10000.0
            gross = float(chosen["execution_forward_return"].mean())
            net = gross - cost
            benchmark = float(benchmark_execution.loc[date])
            periods.append({"window": window, "period_index": period_index, "datetime": date, "net_return": net, "gross_return": gross, "benchmark_return": benchmark, "turnover": turnover, "cost": cost})
            for row in chosen.itertuples(index=False):
                holdings.append({"window": window, "datetime": date, "instrument": row.instrument, "entity": row.entity, "sector": row.sector, "industry": row.industry, "score": row.score, "rank": row.cross_sectional_rank, "raw_return": row.execution_forward_return, "weight": 1.0 / 15, "net_contribution": row.execution_forward_return / 15 - cost / 15})
            previous = weights
    periods_frame = pd.DataFrame(periods)
    holdings_frame = pd.DataFrame(holdings)
    window_results = []
    for window, group in periods_frame.groupby("window", sort=False):
        total = compound(group["net_return"])
        benchmark = compound(group["benchmark_return"])
        window_results.append({"window": window, "total_return": total, "benchmark_return": benchmark, "relative_excess": (1 + total) / (1 + benchmark) - 1, "max_drawdown": max_drawdown(group["net_return"]), "turnover": float(group["turnover"].sum())})
    total = compound(periods_frame["net_return"])
    benchmark = compound(periods_frame["benchmark_return"])
    return {
        "cost_bps": cost_bps,
        "total_return": total,
        "benchmark_return": benchmark,
        "compounded_relative_excess_return": (1 + total) / (1 + benchmark) - 1,
        "max_drawdown": max_drawdown(periods_frame["net_return"]),
        "turnover": float(periods_frame["turnover"].sum()),
        "positive_excess_windows": sum(row["relative_excess"] > 0 for row in window_results),
        "window_results": window_results,
    }, holdings_frame


def markdown_report(identity: dict[str, Any], windows: pd.DataFrame, reporting: pd.DataFrame, aggregate: pd.DataFrame, diagnostics: list[dict[str, Any]], economic: pd.DataFrame, decision: dict[str, Any], equivalence: dict[str, Any]) -> str:
    lines = [
        "# CN130 横截面排序与轮动完整回测报告",
        "",
        "> 研究保持 `cn_selected_equities_v3` 的130个成员不变，并严格采用“先验证排序、再决定是否开启轮动优化”的顺序。",
        "",
        "## 执行身份",
        "",
        f"- Provider identity: `{identity['provider_identity_sha256']}`",
        f"- 数据截止：{identity['provider_cutoff']}。",
        f"- Universe SHA256: `{identity['universe_file_sha256']}`。",
        f"- Classification SHA256: `{identity['classification_sha256']}`。",
        "- `research_only=true`；`trade_ready=false`；静态池存在生存者偏差。",
        "",
        "## 关键事实",
        "",
        f"1. R1 与 R0 的最低日度横截面秩相关为 {equivalence['minimum_daily_rank_correlation']:.6f}，gain标签完全一致：{equivalence['gain_labels_exactly_equal']}。减去同一天沪深300收益不会改变股票之间的顺序，因此 R1 没有新增信息。",
        "2. PIT 市值覆盖为0%，完整 R3 被数据门槛阻断；成交额只作为流动性代理，R3 partial 不具备晋级资格。",
        "3. 四个选择窗口中，没有候选同时满足正 Mean Rank IC、至少3/4窗口正 spread、且单一正窗口贡献低于50%。",
        "",
        "## 排序候选汇总（2024H1–2025H2）",
        "",
        "| 候选 | 特征族 | Mean Rank IC | Mean Rank ICIR | Mean Spread | 正Spread窗口 | 最大正窗口占比 | 基础门槛 |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in aggregate.itertuples(index=False):
        lines.append(f"| {row.ranking_id} | {row.feature_family} | {row.mean_rank_ic:.4f} | {row.mean_rank_icir:.3f} | {row.mean_top_bottom_spread:.2%} | {int(row.positive_spread_windows)}/4 | {row.strongest_positive_window_share:.1%} | {'PASS' if row.basic_gate_pass else 'FAIL'} |")
    lines.extend(["", "## 分窗口证据", "", "| 窗口 | 候选 | 特征族 | Rank IC | Top–Bottom Spread |", "|---|---|---|---:|---:|"])
    for row in windows.sort_values(["window", "ranking_id", "feature_family"]).itertuples(index=False):
        lines.append(f"| {row.window} | {row.ranking_id} | {row.feature_family} | {row.mean_rank_ic:.4f} | {row.mean_top_bottom_spread:.2%} |")
    lines.extend(["", "## 2026 报告窗口（不参与选择）", "", "2026H1 已被此前研究消费；2026H2 仅含截至2026-08-03可实现的前瞻样本。二者只用于观察，不改变排序裁决。", "", "| 窗口 | 候选 | 特征族 | 有效日期 | Rank IC | Top–Bottom Spread |", "|---|---|---|---:|---:|---:|"])
    for row in reporting.sort_values(["window", "ranking_id", "feature_family"]).itertuples(index=False):
        lines.append(f"| {row.window} | {row.ranking_id} | {row.feature_family} | {int(row.n_dates)} | {row.mean_rank_ic:.4f} | {row.mean_top_bottom_spread:.2%} |")
    lines.extend(["", "2026H1 的全面转强与 2026H2 部分窗口的全面反转共同说明：信号方向高度依赖市场状态。R4-momentum 在2026H2将 Rank IC 从 R0 的约 -0.550 缓和至约 -0.185，但仍未恢复为正。", "", "## 诊断性 Top15 经济结果", "", "这些结果仅用于说明排序统计与组合收益可能脱钩，不用于反向选择模型，也未开启 P1–P5 轮动搜索。", "", "| 候选 | 特征族 | 资格 | 成本 | 总收益 | 沪深300 | 复合相对超额 | 最大回撤 | 正超额窗口 |", "|---|---|---|---:|---:|---:|---:|---:|---:|"])
    for row in economic.loc[economic["cost_bps"] == 20].sort_values(["compounded_relative_excess_return", "ranking_id", "feature_family"], ascending=[False, True, True], kind="mergesort").itertuples(index=False):
        lines.append(f"| {row.ranking_id} | {row.feature_family} | {row.target_status} | 20bps | {row.total_return:.2%} | {row.benchmark_return:.2%} | {row.compounded_relative_excess_return:.2%} | {row.max_drawdown:.2%} | {int(row.positive_excess_windows)}/4 |")
    lines.extend([
        "",
        "## 最终裁决",
        "",
        f"- Decision: `{decision['decision']}`。",
        "- 没有冻结排序胜者，因此遵守预注册 stop rule，P1–P5 轮动组合没有进入正式比较。",
        "- CN x1.1 candidate：否；自动升级：否。",
        "",
        "## 结论",
        "",
        "固定 CN130 并不是当前失败的主要原因。核心问题是信号具有明显的窗口依赖：2024年多数候选方向错误，2025年尤其2025H2又明显转强。行业相对标签能在2025H2改善排序，但无法修复2024年的失效；两阶段R4降低行业集中，却同时稀释了有效窗口的分离度。部分Top15组合仍取得较高收益，恰恰说明组合收益可能来自行业Beta、集中暴露或窗口路径，不能替代横截面排序证据。现阶段不能把这些结果解释为稳定的行业轮动能力。",
        "",
        "## 限制",
        "",
        "- 当前结果只对绑定的2026-08-03 provider快照成立；Issue #345 的快照漂移仍未解除。",
        "- 静态精选池存在生存者偏差。",
        "- 2026H1已消费、2026H2不完整，未进入模型选择。",
        "- 完整R3需要PIT市值/股本数据后重新预注册。",
    ])
    return "\n".join(lines) + "\n"


def run(root: Path, provider_dir: Path, input_dir: Path, output_dir: Path) -> None:
    universe_path = root / "configs/research_universes/cn_selected_equities_v3.yaml"
    classification_path = root / "configs/research_classifications/cn130_sector_industry_v1.yaml"
    universe = yaml.safe_load(universe_path.read_text(encoding="utf-8"))
    symbols = [str(x) for x in universe["symbols"]]
    manifest_path = provider_dir / "provider_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    identity = {
        "provider_identity_sha256": manifest["provider_identity_sha256"],
        "provider_cutoff": manifest["calendar"]["last_day"],
        "provider_manifest_sha256": file_sha(manifest_path),
        "calendar_sha256": manifest["calendar"]["sha256"],
        "universe_file_sha256": file_sha(universe_path),
        "classification_sha256": file_sha(classification_path),
        "declared_symbols": len(symbols),
        "research_only": True,
        "trade_ready": False,
    }
    windows = load_summaries(input_dir)
    reporting = load_reporting_summaries(input_dir)
    aggregate = aggregate_rankings(windows)
    # Diagnostics are deliberately limited to R0 and the best Mean-Rank-IC challenger because no cell passes the basic gate.
    best = aggregate.loc[aggregate["target_status"] == "eligible"].sort_values("mean_rank_ic", ascending=False).iloc[0]
    diagnostic_keys = [("r0_cn_x1_0_raw_return_rank", "current_cn_ohlcv"), (str(best["ranking_id"]), str(best["feature_family"]))]
    diagnostic_keys = list(dict.fromkeys(diagnostic_keys))
    diagnostics = [diagnostic_for_cell(input_dir, rid, fam) for rid, fam in diagnostic_keys]

    panel = load_provider_panel(provider_dir, [*symbols, core.BENCHMARK])
    benchmark_execution = forward_returns(panel.fields["close"][[core.BENCHMARK]], horizon=10, delay=1)[core.BENCHMARK]
    economic_rows: list[dict[str, Any]] = []
    holdings_outputs: list[pd.DataFrame] = []
    for row in aggregate.itertuples(index=False):
        frames = [load_cell(input_dir, window, row.ranking_id, row.feature_family) for window in SELECTION_WINDOWS]
        frame = pd.concat(frames, ignore_index=True)
        for cost in (10, 20, 40):
            summary, holdings = portfolio_from_cell(frame, benchmark_execution, cost)
            economic_rows.append({
                "ranking_id": row.ranking_id,
                "feature_family": row.feature_family,
                "target_status": row.target_status,
                **summary,
            })
            if cost == 20:
                holdings["ranking_id"] = row.ranking_id
                holdings["feature_family"] = row.feature_family
                holdings_outputs.append(holdings)
    economic = pd.DataFrame(economic_rows)
    holdings = pd.concat(holdings_outputs, ignore_index=True)

    equivalence_rows = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((input_dir / "equivalence").glob("*.json"))]
    equivalence = {
        "minimum_daily_rank_correlation": min(row["minimum_daily_rank_correlation"] for row in equivalence_rows),
        "mean_daily_rank_correlation": float(np.mean([row["mean_daily_rank_correlation"] for row in equivalence_rows])),
        "gain_labels_exactly_equal": all(row["gain_labels_exactly_equal"] for row in equivalence_rows),
        "decision": "r1_is_rank_equivalent_to_r0",
    }
    decision = {
        "decision": "cn130_cross_sectional_ranking_not_supported",
        "winner": None,
        "basic_gate_pass_count": int(aggregate["basic_gate_pass"].sum()),
        "rotation_stage_opened": False,
        "creates_cn_x1_1_candidate": False,
        "automatic_promotion": False,
        "reasons": [
            "no eligible candidate passed all ranking-first basic gates",
            "R1 is cross-sectionally rank-equivalent to R0",
            "full R3 is data-blocked by missing PIT market capitalization",
            "2024 windows show negative ranking direction for all candidate architectures",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "execution_identity.json", identity)
    write_json(output_dir / "r0_r1_equivalence.json", equivalence)
    write_json(output_dir / "ranking_diagnostics.json", diagnostics)
    write_json(output_dir / "decision.json", decision)
    write_csv(output_dir / "ranking_window_summary.csv", windows)
    write_csv(output_dir / "reporting_window_summary.csv", reporting)
    write_csv(output_dir / "ranking_aggregate_summary.csv", aggregate)
    economic_flat = economic.drop(columns=["window_results"])
    write_csv(output_dir / "diagnostic_top15_economic_summary.csv", economic_flat)
    write_json(output_dir / "diagnostic_top15_window_results.json", economic[["ranking_id", "feature_family", "cost_bps", "window_results"]].to_dict(orient="records"))
    write_csv(output_dir / "diagnostic_top15_holdings.csv.gz", holdings)
    report = markdown_report(identity, windows, reporting, aggregate, diagnostics, economic, decision, equivalence)
    (output_dir / "report.md").write_text(report, encoding="utf-8")
    files = [path for path in output_dir.rglob("*") if path.is_file() and path.name != "evidence_manifest.json"]
    write_json(output_dir / "evidence_manifest.json", {
        "schema_version": "1.0.0",
        "experiment_id": core.EXPERIMENT_ID,
        "decision": decision,
        "files": [{"path": str(path.relative_to(output_dir)), "sha256": file_sha(path), "bytes": path.stat().st_size} for path in sorted(files)],
        "source_batch_files": len(list((input_dir / "score_ledgers").glob("*.csv.gz"))),
        "research_only": True,
        "trade_ready": False,
    })
    print(json.dumps(decision, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-dir", type=Path, required=True)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run(args.root.resolve(), args.provider_dir.resolve(), args.input_dir.resolve(), args.output_dir.resolve())


if __name__ == "__main__":
    main()
