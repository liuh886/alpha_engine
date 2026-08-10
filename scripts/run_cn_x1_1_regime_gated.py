"""Validate the preregistered CN x1.1 regime-gated sector-breadth model."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
import yaml

from scripts.run_cn_x1_1_sector_breadth import load_ledgers
from src.research.cn130_cross_sectional_ranking import forward_returns, load_provider_panel
from src.research.cn_x1_1_regime_gated import (
    RegimeGateSpec,
    build_regime_state,
    run_regime_portfolio,
    yearly_state_coverage,
)

HISTORICAL_WINDOWS = (
    "2022H2",
    "2023H1",
    "2023H2",
    "2024H1",
    "2024H2",
    "2025H1",
    "2025H2",
)
REPORTING_WINDOWS = ("2026H1",)


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
    if isinstance(value, np.integer):
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


def flatten(label: str, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "evaluation": label,
        **{key: value for key, value in summary.items() if key != "windows"},
        "windows": "|".join(summary["windows"]),
    }


def report_markdown(
    decision: dict[str, Any],
    summaries: pd.DataFrame,
    half_year: pd.DataFrame,
    yearly: pd.DataFrame,
    neighbors: pd.DataFrame,
) -> str:
    lines = [
        "# CN x1.1 Regime-Gated Sector Breadth 验证报告",
        "",
        f"**Decision:** `{decision['decision']}`",
        "",
        "## 固定状态门",
        "",
        "- CSI300高于MA200；CSI300 60日动量为正；CN130中至少50%高于各自MA60。",
        "- 三项中至少两项成立时进入四行业Top1组合，否则持有CSI300。",
        "- 状态在评分日计算，次一交易日执行；所有状态切换均计入换手和成本。",
        "",
        "## 汇总",
        "",
        "| 区间 | 相对超额 | 最大回撤 | 正半年 | 全期胜率 | Risk-on胜率 | Risk-on占比 | Risk-on相对超额 | Risk-off相对超额 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summaries.itertuples(index=False):
        lines.append(
            f"| {row.evaluation} | {row.relative_excess:.2%} | {row.max_drawdown:.2%} | "
            f"{int(row.positive_excess_windows)} | {row.all_period_hit_rate:.1%} | "
            f"{row.risk_on_active_hit_rate:.1%} | {row.risk_on_share:.1%} | "
            f"{row.risk_on_relative_excess:.2%} | {row.risk_off_relative_excess:.2%} |"
        )
    lines.extend(
        [
            "",
            "## 半年度结果",
            "",
            "| 窗口 | 相对超额 | 最大回撤 | 全期胜率 | Risk-on占比 | 换手 |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in half_year.itertuples(index=False):
        lines.append(
            f"| {row.window} | {row.relative_excess:.2%} | {row.max_drawdown:.2%} | "
            f"{row.all_period_hit_rate:.1%} | {row.risk_on_share:.1%} | {row.turnover:.2f} |"
        )
    lines.extend(
        [
            "",
            "## 年度状态覆盖",
            "",
            "| 年份 | Risk-on | Risk-off | Risk-on占比 | 两种状态均存在 |",
            "|---:|---:|---:|---:|---|",
        ]
    )
    for row in yearly.itertuples(index=False):
        lines.append(
            f"| {int(row.year)} | {int(row.risk_on_count)} | {int(row.risk_off_count)} | "
            f"{row.risk_on_share:.1%} | {'是' if row.both_states_present else '否'} |"
        )
    lines.extend(
        [
            "",
            "## 邻近规则（报告项）",
            "",
            "| 规则 | 再平衡 | 相对超额 | 最大回撤 | 正超额 |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for row in neighbors.itertuples(index=False):
        lines.append(
            f"| {row.rule} | {int(row.rebalance_sessions)} | {row.relative_excess:.2%} | "
            f"{row.max_drawdown:.2%} | {'是' if row.positive else '否'} |"
        )
    lines.extend(["", "## 原预注册门槛", ""])
    for name, passed in decision["gates"].items():
        lines.append(f"- `{name}`: {'PASS' if passed else 'FAIL'}")
    lines.extend(
        [
            "",
            "## 评价边界",
            "",
            "- `all_period_hit_rate`严格执行#573原始合同；风险关闭期持有CSI300，因此净成本后不可能逐期跑赢CSI300。",
            "- `risk_on_active_hit_rate`单独报告，不用于本轮事后替换原门槛。",
            "- 2026仅作为最终护栏，不用于修改状态规则。",
            "- 即使模型经济表现被支持，原合同未全部通过时也不会在本轮授权候选。",
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
    spec = RegimeGateSpec()
    universe_path = root / "configs/research_universes/cn_selected_equities_v3.yaml"
    classification_path = root / "configs/research_classifications/cn130_sector_industry_v1.yaml"
    universe = yaml.safe_load(universe_path.read_text(encoding="utf-8"))
    symbols = [str(value).zfill(6) for value in universe["symbols"]]
    if len(symbols) != 130 or len(set(symbols)) != 130:
        raise ValueError("CN130 universe identity is not exact")

    ledger, ledger_paths = load_ledgers(
        ledger_roots,
        HISTORICAL_WINDOWS + REPORTING_WINDOWS,
    )
    panel = load_provider_panel(
        provider_dir,
        [*symbols, spec.benchmark],
        fields=("close",),
    )
    symbols = [s for s in symbols if s in panel.fields["close"].columns]
    close = panel.fields["close"]
    state = build_regime_state(
        close,
        symbols=symbols,
        benchmark=spec.benchmark,
        long_ma_sessions=spec.long_ma_sessions,
        momentum_sessions=spec.momentum_sessions,
        breadth_ma_sessions=spec.breadth_ma_sessions,
        breadth_threshold=spec.breadth_threshold,
    )
    benchmark_returns = forward_returns(
        close[[spec.benchmark]],
        horizon=spec.horizon_sessions,
        delay=spec.execution_delay_sessions,
    )[spec.benchmark]

    historical, historical_periods, historical_holdings, historical_windows = (
        run_regime_portfolio(
            ledger,
            benchmark_returns,
            state,
            windows=HISTORICAL_WINDOWS,
            variant=spec.variant(),
            rule=spec.rule,
            rebalance_sessions=spec.rebalance_sessions,
            cost_bps=spec.cost_bps,
        )
    )
    reporting, reporting_periods, reporting_holdings, reporting_windows = (
        run_regime_portfolio(
            ledger,
            benchmark_returns,
            state,
            windows=REPORTING_WINDOWS,
            variant=spec.variant(),
            rule=spec.rule,
            rebalance_sessions=spec.rebalance_sessions,
            cost_bps=spec.cost_bps,
        )
    )
    historical_40, _, _, _ = run_regime_portfolio(
        ledger,
        benchmark_returns,
        state,
        windows=HISTORICAL_WINDOWS,
        variant=spec.variant(),
        rule=spec.rule,
        rebalance_sessions=spec.rebalance_sessions,
        cost_bps=40,
    )
    leave_name, _, _, _ = run_regime_portfolio(
        ledger,
        benchmark_returns,
        state,
        windows=HISTORICAL_WINDOWS,
        variant=spec.variant(),
        rule=spec.rule,
        rebalance_sessions=spec.rebalance_sessions,
        cost_bps=spec.cost_bps,
        excluded_name=historical["top_contributor_name"],
    )
    leave_sector, _, _, _ = run_regime_portfolio(
        ledger,
        benchmark_returns,
        state,
        windows=HISTORICAL_WINDOWS,
        variant=spec.variant(),
        rule=spec.rule,
        rebalance_sessions=spec.rebalance_sessions,
        cost_bps=spec.cost_bps,
        excluded_sector=historical["top_contributor_sector"],
    )

    neighbor_rows: list[dict[str, Any]] = []
    for rule, interval in (
        ("trend_only", 10),
        ("momentum_and_breadth", 10),
        ("three_of_three", 10),
        ("two_of_three", 15),
    ):
        summary, _, _, _ = run_regime_portfolio(
            ledger,
            benchmark_returns,
            state,
            windows=HISTORICAL_WINDOWS,
            variant=spec.variant(),
            rule=rule,
            rebalance_sessions=interval,
            cost_bps=spec.cost_bps,
        )
        neighbor_rows.append(
            {
                "rule": rule,
                "rebalance_sessions": interval,
                "relative_excess": summary["relative_excess"],
                "max_drawdown": summary["max_drawdown"],
                "positive": summary["relative_excess"] > 0.0,
            }
        )
    neighbors = pd.DataFrame(neighbor_rows)
    yearly = yearly_state_coverage(historical_periods)
    full_year_state_gate = bool(
        yearly.loc[yearly["year"].isin([2023, 2024, 2025]), "both_states_present"].all()
    )
    risk_off_cost_gate = bool(
        historical["risk_off_relative_excess"]
        >= -historical["risk_off_total_cost"] - 0.001
    )
    combined_reporting_relative = reporting["relative_excess"]
    gates = {
        "historical_relative_excess_positive": historical["relative_excess"] > 0.0,
        "historical_positive_half_years_at_least_5_of_7": historical["positive_excess_windows"] >= 5,
        "historical_worst_half_year_above_minus_10pct": float(historical_windows["relative_excess"].min()) >= -0.10,
        "historical_max_drawdown_above_minus_25pct": historical["max_drawdown"] >= -0.25,
        "historical_all_period_hit_rate_at_least_50pct": historical["all_period_hit_rate"] >= 0.50,
        "historical_40bps_relative_excess_positive": historical_40["relative_excess"] > 0.0,
        "leave_one_top_name_positive": leave_name["relative_excess"] > 0.0,
        "leave_one_top_sector_positive": leave_sector["relative_excess"] > 0.0,
        "risk_on_share_between_25_and_80pct": 0.25 <= historical["risk_on_share"] <= 0.80,
        "both_states_present_2023_to_2025": full_year_state_gate,
        "risk_on_relative_excess_positive": historical["risk_on_relative_excess"] > 0.0,
        "risk_off_relative_no_worse_than_cost_drag": risk_off_cost_gate,
        "at_least_two_neighbor_rules_positive": int(neighbors["positive"].sum()) >= 2,
        "combined_2026_relative_excess_positive": combined_reporting_relative > 0.0,
    }
    if all(gates.values()):
        decision_name = "cn_x1_1_regime_gated_candidate_authorized"
    elif historical["relative_excess"] > 0.0 and historical["positive_excess_windows"] >= 5:
        decision_name = "regime_gate_supported_not_candidate_ready"
    else:
        decision_name = "regime_gate_rejected"
    decision = {
        "schema_version": "cn_x1_1_regime_gated_validation_v1",
        "decision": decision_name,
        "candidate_name": (
            "CN x1.1 Candidate A — Regime-Gated Sector Breadth"
            if decision_name == "cn_x1_1_regime_gated_candidate_authorized"
            else ""
        ),
        "candidate_authorized": decision_name == "cn_x1_1_regime_gated_candidate_authorized",
        "gates": gates,
        "automatic_production_promotion": False,
        "research_only": True,
        "trade_ready": False,
    }

    summaries = pd.DataFrame(
        [flatten("historical_2022H2_2025H2", historical), flatten("reporting_2026", reporting)]
    )
    half_year = pd.concat(
        [
            historical_windows.assign(evaluation="historical"),
            reporting_windows.assign(evaluation="reporting"),
        ],
        ignore_index=True,
    )
    periods = pd.concat(
        [
            historical_periods.assign(evaluation="historical"),
            reporting_periods.assign(evaluation="reporting"),
        ],
        ignore_index=True,
    )
    holdings = pd.concat(
        [
            historical_holdings.assign(evaluation="historical"),
            reporting_holdings.assign(evaluation="reporting"),
        ],
        ignore_index=True,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "model_spec.json", spec.to_dict())
    write_json(output_dir / "decision.json", decision)
    write_csv(output_dir / "evaluation_summary.csv", summaries)
    write_csv(output_dir / "half_year_results.csv", half_year)
    write_csv(output_dir / "yearly_state_coverage.csv", yearly)
    write_csv(output_dir / "neighbor_rule_summary.csv", neighbors)
    write_csv(output_dir / "rebalance_periods.csv", periods)
    write_csv(output_dir / "holdings.csv", holdings)

    provider_manifest = json.loads(
        (provider_dir / "provider_manifest.json").read_text(encoding="utf-8")
    )
    manifest = {
        "schema_version": "cn_x1_1_regime_gated_evidence_v1",
        "decision": decision_name,
        "provider_identity_sha256": provider_manifest["provider_identity_sha256"],
        "provider_cutoff": provider_manifest["calendar"]["last_day"],
        "universe_sha256": sha256(universe_path),
        "classification_sha256": sha256(classification_path),
        "ledger_files": [
            {"path": str(path), "sha256": sha256(path)} for path in ledger_paths
        ],
        "historical_windows": list(HISTORICAL_WINDOWS),
        "reporting_windows": list(REPORTING_WINDOWS),
        "research_only": True,
        "trade_ready": False,
    }
    write_json(output_dir / "manifest.json", manifest)
    (output_dir / "report.md").write_text(
        report_markdown(decision, summaries, half_year, yearly, neighbors),
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
        "--ledger-dir", dest="ledger_dirs", type=Path, action="append", required=True
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
