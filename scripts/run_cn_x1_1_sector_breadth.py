"""Validate and converge the fixed CN x1.1 sector-breadth model candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
import yaml

from src.research.cn130_cross_sectional_ranking import forward_returns, load_provider_panel
from src.research.cn130_tail_factor_discovery import PortfolioVariant
from src.research.cn_x1_1_sector_breadth import (
    SectorBreadthModelSpec,
    block_bootstrap_relative_excess,
    run_sector_breadth_portfolio,
)

REVERSE_WINDOWS = ("2022H2", "2023H1", "2023H2")
SELECTION_WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")
REPORTING_WINDOWS = ("2026H1", "2026H2_PARTIAL")
ALL_HISTORY_WINDOWS = REVERSE_WINDOWS + SELECTION_WINDOWS
RANKING_ID = "r0_cn_x1_0_raw_return_rank"
FEATURE_FAMILY = "current_cn_ohlcv"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return value


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(clean(payload), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, float_format="%.10g", lineterminator="\n")


def find_ledger(roots: Sequence[Path], window: str) -> Path:
    filename = f"{window}__{RANKING_ID}__{FEATURE_FAMILY}.csv.gz"
    matches: list[Path] = []
    for root in roots:
        matches.extend(sorted(root.rglob(filename)))
    unique = {path.resolve(): path for path in matches}
    if len(unique) != 1:
        raise ValueError(f"expected one ledger for {window}, found {list(unique)}")
    return next(iter(unique.values()))


def load_ledgers(roots: Sequence[Path], windows: Sequence[str]) -> tuple[pd.DataFrame, list[Path]]:
    frames: list[pd.DataFrame] = []
    paths: list[Path] = []
    for window in windows:
        path = find_ledger(roots, window)
        frame = pd.read_csv(
            path,
            compression="gzip",
            dtype={"instrument": str},
            parse_dates=["datetime"],
        )
        frame["instrument"] = frame["instrument"].str.zfill(6)
        if "window" not in frame.columns:
            frame["window"] = window
        frames.append(frame)
        paths.append(path)
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values(
        ["window", "datetime", "score", "instrument"],
        ascending=[True, True, False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    return combined, paths


def flatten_summary(label: str, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "evaluation": label,
        **{key: value for key, value in summary.items() if key not in {"windows"}},
        "windows": "|".join(summary["windows"]),
    }


def report_markdown(
    decision: dict[str, Any],
    model_spec: dict[str, Any],
    evaluation: pd.DataFrame,
    half_year: pd.DataFrame,
    robustness: pd.DataFrame,
    bootstrap: dict[str, Any],
) -> str:
    lines = [
        "# CN x1.1 Sector Breadth 候选验证报告",
        "",
        f"**Decision:** `{decision['decision']}`",
        "",
        "## 固定模型",
        "",
        f"- Model ID: `{model_spec['model_id']}`",
        "- 冻结CN x1.0 R0评分；按每日Top3广度给行业打分；选择四个行业；每行业Top1；四股等权。",
        f"- 每{model_spec['rebalance_sessions']}个交易日再平衡，延迟{model_spec['execution_delay_sessions']}个交易日执行，成本{model_spec['cost_bps']}bps/换手。",
        "- 本轮没有新增因子、没有收益权重、没有根据留出期调整参数。",
        "",
        "## 主评估",
        "",
        "| 区间 | 相对超额 | 最大回撤 | 正窗口 | 组合胜率 | Precision@K | 名称集中 | 行业集中 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in evaluation.itertuples(index=False):
        lines.append(
            f"| {row.evaluation} | {row.relative_excess:.2%} | {row.max_drawdown:.2%} | "
            f"{int(row.positive_excess_windows)} | {row.portfolio_benchmark_hit_rate:.1%} | "
            f"{row.precision_at_k:.1%} | {row.maximum_name_absolute_contribution_share:.1%} | "
            f"{row.maximum_sector_absolute_contribution_share:.1%} |"
        )
    lines.extend(
        [
            "",
            "## 半年度结果",
            "",
            "| 集合 | 窗口 | 相对超额 | 最大回撤 | 胜率 | 换手 |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in half_year.itertuples(index=False):
        lines.append(
            f"| {row.evaluation} | {row.window} | {row.relative_excess:.2%} | "
            f"{row.max_drawdown:.2%} | {row.benchmark_hit_rate:.1%} | {row.turnover:.2f} |"
        )
    lines.extend(
        [
            "",
            "## 架构压力测试",
            "",
            "| 测试 | 参数 | 相对超额 | 最大回撤 | Gate |",
            "|---|---|---:|---:|---|",
        ]
    )
    for row in robustness.itertuples(index=False):
        lines.append(
            f"| {row.test_type} | {row.parameter} | {row.relative_excess:.2%} | "
            f"{row.max_drawdown:.2%} | {'PASS' if row.gate_pass else 'FAIL'} |"
        )
    lines.extend(
        [
            "",
            "## Block bootstrap（报告项）",
            "",
            f"- 正相对超额概率：{bootstrap['probability_positive']:.1%}",
            f"- 5% / 中位数 / 95%：{bootstrap['p05']:.2%} / {bootstrap['median']:.2%} / {bootstrap['p95']:.2%}",
            "",
            "## 门槛",
            "",
        ]
    )
    for gate, passed in decision["gates"].items():
        lines.append(f"- `{gate}`: {'PASS' if passed else 'FAIL'}")
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 2022H2—2023H2为反向历史留出；2024H1—2025H2为既有选择证据；2026仅报告。",
            "- 固定精选池仍存在生存者偏差，候选授权不等于自动晋级生产基准。",
            "- 若全部门槛通过，本模型命名为 `CN x1.1 Candidate A — Sector Breadth`。",
            "",
        ]
    )
    return "\n".join(lines)


def run(
    root: Path,
    provider_dir: Path,
    ledger_roots: Sequence[Path],
    output_dir: Path,
) -> dict[str, Any]:
    spec = SectorBreadthModelSpec()
    universe_path = root / "configs/research_universes/cn_selected_equities_v3.yaml"
    classification_path = root / "configs/research_classifications/cn130_sector_industry_v1.yaml"
    universe = yaml.safe_load(universe_path.read_text(encoding="utf-8"))
    symbols = [str(value).zfill(6) for value in universe["symbols"]]
    if len(symbols) != 130 or len(set(symbols)) != 130:
        raise ValueError("CN130 universe identity is not exact")

    ledger, ledger_paths = load_ledgers(
        ledger_roots,
        REVERSE_WINDOWS + SELECTION_WINDOWS + REPORTING_WINDOWS,
    )
    panel = load_provider_panel(provider_dir, [*symbols, spec.benchmark])
    benchmark_execution = forward_returns(
        panel.fields["close"][[spec.benchmark]],
        horizon=10,
        delay=spec.execution_delay_sessions,
    )[spec.benchmark]
    candidate = spec.variant()

    reverse, reverse_periods, reverse_holdings, reverse_windows = run_sector_breadth_portfolio(
        ledger,
        benchmark_execution,
        candidate,
        windows=REVERSE_WINDOWS,
        rebalance_sessions=spec.rebalance_sessions,
        cost_bps=spec.cost_bps,
    )
    selection, selection_periods, selection_holdings, selection_windows = run_sector_breadth_portfolio(
        ledger,
        benchmark_execution,
        candidate,
        windows=SELECTION_WINDOWS,
        rebalance_sessions=spec.rebalance_sessions,
        cost_bps=spec.cost_bps,
    )
    reporting, reporting_periods, reporting_holdings, reporting_windows = run_sector_breadth_portfolio(
        ledger,
        benchmark_execution,
        candidate,
        windows=REPORTING_WINDOWS,
        rebalance_sessions=spec.rebalance_sessions,
        cost_bps=spec.cost_bps,
    )
    combined, combined_periods, combined_holdings, combined_windows = run_sector_breadth_portfolio(
        ledger,
        benchmark_execution,
        candidate,
        windows=ALL_HISTORY_WINDOWS,
        rebalance_sessions=spec.rebalance_sessions,
        cost_bps=spec.cost_bps,
    )

    selection_40, _, _, _ = run_sector_breadth_portfolio(
        ledger,
        benchmark_execution,
        candidate,
        windows=SELECTION_WINDOWS,
        rebalance_sessions=spec.rebalance_sessions,
        cost_bps=40,
    )
    combined_40, _, _, _ = run_sector_breadth_portfolio(
        ledger,
        benchmark_execution,
        candidate,
        windows=ALL_HISTORY_WINDOWS,
        rebalance_sessions=spec.rebalance_sessions,
        cost_bps=40,
    )

    selection_leave_name, _, _, _ = run_sector_breadth_portfolio(
        ledger,
        benchmark_execution,
        candidate,
        windows=SELECTION_WINDOWS,
        rebalance_sessions=spec.rebalance_sessions,
        cost_bps=spec.cost_bps,
        excluded_name=selection["top_contributor_name"],
    )
    selection_leave_sector, _, _, _ = run_sector_breadth_portfolio(
        ledger,
        benchmark_execution,
        candidate,
        windows=SELECTION_WINDOWS,
        rebalance_sessions=spec.rebalance_sessions,
        cost_bps=spec.cost_bps,
        excluded_sector=selection["top_contributor_sector"],
    )
    combined_leave_name, _, _, _ = run_sector_breadth_portfolio(
        ledger,
        benchmark_execution,
        candidate,
        windows=ALL_HISTORY_WINDOWS,
        rebalance_sessions=spec.rebalance_sessions,
        cost_bps=spec.cost_bps,
        excluded_name=combined["top_contributor_name"],
    )
    combined_leave_sector, _, _, _ = run_sector_breadth_portfolio(
        ledger,
        benchmark_execution,
        candidate,
        windows=ALL_HISTORY_WINDOWS,
        rebalance_sessions=spec.rebalance_sessions,
        cost_bps=spec.cost_bps,
        excluded_sector=combined["top_contributor_sector"],
    )

    robustness_rows: list[dict[str, Any]] = []
    frequency_passes: list[bool] = []
    for interval in (5, 10, 15):
        summary, _, _, _ = run_sector_breadth_portfolio(
            ledger,
            benchmark_execution,
            candidate,
            windows=ALL_HISTORY_WINDOWS,
            rebalance_sessions=interval,
            cost_bps=spec.cost_bps,
        )
        passed = summary["relative_excess"] > 0.0
        frequency_passes.append(passed)
        robustness_rows.append(
            {
                "test_type": "rebalance_frequency",
                "parameter": f"{interval}_sessions",
                "relative_excess": summary["relative_excess"],
                "max_drawdown": summary["max_drawdown"],
                "gate_pass": passed,
            }
        )

    neighbor_passes = 0
    for variant in (
        PortfolioVariant("sector_3x1", "sector_hierarchical", sectors=3, names_per_sector=1),
        PortfolioVariant("sector_5x1", "sector_hierarchical", sectors=5, names_per_sector=1),
        PortfolioVariant("sector_3x2", "sector_hierarchical", sectors=3, names_per_sector=2),
    ):
        summary, _, _, _ = run_sector_breadth_portfolio(
            ledger,
            benchmark_execution,
            variant,
            windows=ALL_HISTORY_WINDOWS,
            rebalance_sessions=spec.rebalance_sessions,
            cost_bps=spec.cost_bps,
        )
        passed = summary["relative_excess"] > 0.0
        neighbor_passes += int(passed)
        robustness_rows.append(
            {
                "test_type": "neighbor_architecture",
                "parameter": variant.variant_id,
                "relative_excess": summary["relative_excess"],
                "max_drawdown": summary["max_drawdown"],
                "gate_pass": passed,
            }
        )

    for label, summary in (
        ("combined_40bps", combined_40),
        ("leave_top_name", combined_leave_name),
        ("leave_top_sector", combined_leave_sector),
    ):
        robustness_rows.append(
            {
                "test_type": "stress",
                "parameter": label,
                "relative_excess": summary["relative_excess"],
                "max_drawdown": summary["max_drawdown"],
                "gate_pass": summary["relative_excess"] > 0.0,
            }
        )
    robustness = pd.DataFrame(robustness_rows)

    reverse_worst = float(reverse_windows["relative_excess"].min())
    gates = {
        "reverse_compounded_relative_excess_positive": reverse["relative_excess"] > 0.0,
        "reverse_positive_windows_at_least_2_of_3": reverse["positive_excess_windows"] >= 2,
        "reverse_worst_window_above_minus_10pct": reverse_worst >= -0.10,
        "reverse_max_drawdown_above_minus_25pct": reverse["max_drawdown"] >= -0.25,
        "reverse_portfolio_hit_rate_at_least_50pct": reverse["portfolio_benchmark_hit_rate"] >= 0.50,
        "selection_positive_windows_at_least_3_of_4": selection["positive_excess_windows"] >= 3,
        "selection_20bps_relative_excess_positive": selection["relative_excess"] > 0.0,
        "selection_40bps_relative_excess_positive": selection_40["relative_excess"] > 0.0,
        "selection_name_concentration_below_35pct": selection["maximum_name_absolute_contribution_share"] <= 0.35,
        "selection_sector_concentration_below_55pct": selection["maximum_sector_absolute_contribution_share"] <= 0.55,
        "selection_leave_one_name_positive": selection_leave_name["relative_excess"] > 0.0,
        "selection_leave_one_sector_positive": selection_leave_sector["relative_excess"] > 0.0,
        "all_rebalance_frequencies_positive": all(frequency_passes),
        "at_least_two_neighbor_architectures_positive": neighbor_passes >= 2,
        "combined_40bps_positive": combined_40["relative_excess"] > 0.0,
        "combined_leave_one_name_positive": combined_leave_name["relative_excess"] > 0.0,
        "combined_leave_one_sector_positive": combined_leave_sector["relative_excess"] > 0.0,
    }
    if all(gates.values()):
        decision_name = "cn_x1_1_sector_breadth_candidate_authorized"
    elif selection["relative_excess"] > 0.0 and combined["relative_excess"] > 0.0:
        decision_name = "sector_breadth_architecture_supported_not_candidate_ready"
    else:
        decision_name = "sector_breadth_architecture_rejected"
    decision = {
        "schema_version": "cn_x1_1_sector_breadth_validation_v1",
        "decision": decision_name,
        "candidate_name": (
            "CN x1.1 Candidate A — Sector Breadth"
            if decision_name == "cn_x1_1_sector_breadth_candidate_authorized"
            else ""
        ),
        "gates": gates,
        "automatic_production_promotion": False,
        "research_only": True,
        "trade_ready": decision_name == "cn_x1_1_sector_breadth_candidate_authorized",
    }

    evaluation = pd.DataFrame(
        [
            flatten_summary("reverse_holdout", reverse),
            flatten_summary("selection", selection),
            flatten_summary("combined_history", combined),
            flatten_summary("reporting_2026", reporting),
        ]
    )
    half_year = pd.concat(
        [
            reverse_windows.assign(evaluation="reverse_holdout"),
            selection_windows.assign(evaluation="selection"),
            reporting_windows.assign(evaluation="reporting"),
        ],
        ignore_index=True,
    )
    periods = pd.concat(
        [
            reverse_periods.assign(evaluation="reverse_holdout"),
            selection_periods.assign(evaluation="selection"),
            reporting_periods.assign(evaluation="reporting"),
        ],
        ignore_index=True,
    )
    holdings = pd.concat(
        [
            reverse_holdings.assign(evaluation="reverse_holdout"),
            selection_holdings.assign(evaluation="selection"),
            reporting_holdings.assign(evaluation="reporting"),
        ],
        ignore_index=True,
    )
    bootstrap = block_bootstrap_relative_excess(combined_periods)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "model_spec.json", spec.to_dict())
    write_json(output_dir / "decision.json", decision)
    write_json(output_dir / "bootstrap_summary.json", bootstrap)
    write_csv(output_dir / "evaluation_summary.csv", evaluation)
    write_csv(output_dir / "half_year_results.csv", half_year)
    write_csv(output_dir / "robustness_summary.csv", robustness)
    write_csv(output_dir / "rebalance_periods.csv", periods)
    write_csv(output_dir / "holdings.csv", holdings)

    provider_manifest = json.loads(
        (provider_dir / "provider_manifest.json").read_text(encoding="utf-8")
    )
    manifest = {
        "schema_version": "cn_x1_1_sector_breadth_evidence_v1",
        "decision": decision_name,
        "provider_identity_sha256": provider_manifest["provider_identity_sha256"],
        "provider_cutoff": provider_manifest["calendar"]["last_day"],
        "universe_sha256": sha256(universe_path),
        "classification_sha256": sha256(classification_path),
        "ledger_files": [
            {"path": str(path), "sha256": sha256(path)} for path in ledger_paths
        ],
        "reverse_windows": list(REVERSE_WINDOWS),
        "selection_windows": list(SELECTION_WINDOWS),
        "reporting_windows": list(REPORTING_WINDOWS),
        "research_only": True,
        "trade_ready": decision["trade_ready"],
    }
    write_json(output_dir / "manifest.json", manifest)
    (output_dir / "report.md").write_text(
        report_markdown(decision, spec.to_dict(), evaluation, half_year, robustness, bootstrap),
        encoding="utf-8",
    )
    files = sorted(
        path for path in output_dir.iterdir() if path.is_file() and path.name != "evidence_manifest.json"
    )
    write_json(
        output_dir / "evidence_manifest.json",
        {
            "schema_version": "1.0.0",
            "experiment_id": spec.model_id,
            "decision": decision,
            "files": [
                {"path": path.name, "sha256": sha256(path), "bytes": path.stat().st_size}
                for path in files
            ],
        },
    )
    print(json.dumps(clean(decision), ensure_ascii=False, indent=2))
    return decision


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--provider-dir", type=Path, required=True)
    parser.add_argument(
        "--ledger-dir",
        dest="ledger_dirs",
        type=Path,
        action="append",
        required=True,
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run(
        args.root.resolve(),
        args.provider_dir.resolve(),
        [path.resolve() for path in args.ledger_dirs],
        args.output_dir.resolve(),
    )


if __name__ == "__main__":
    main()
