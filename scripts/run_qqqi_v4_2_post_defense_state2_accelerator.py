#!/usr/bin/env python3
"""Run the post-defense formal-state-2 TQQQ accelerator experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.v4_2_post_defense_state2_accelerator import (
    BASELINE,
    COMBINED,
    DEFENSE_ONLY,
    TAG_ONLY,
    run_post_defense_state2_accelerator_comparison,
)


def _json_default(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    raise TypeError(f"unsupported JSON value: {type(value)!r}")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=_json_default,
        )
        + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _scope_run(
    bars: Mapping[str, pd.DataFrame],
    scope: str,
    output: Path,
    baseline_contract: Mapping[str, Any],
    sgov_contract: Mapping[str, Any],
    attribution_contract: Mapping[str, Any],
    defense_contract: Mapping[str, Any],
    accelerator_contract: Mapping[str, Any],
) -> dict[str, Any]:
    headline, results, chronological, episodes, diagnostics = (
        run_post_defense_state2_accelerator_comparison(
            bars,
            baseline_contract,
            sgov_contract,
            attribution_contract,
            defense_contract,
            accelerator_contract,
        )
    )
    output.mkdir(parents=True, exist_ok=True)
    headline.to_csv(output / "headline_metrics.csv")
    chronological.to_csv(output / "chronological_metrics.csv", index=False)
    for key, result in results.items():
        result.daily.to_csv(output / f"daily_{key}.csv")
        result.trades.to_csv(output / f"trades_{key}.csv", index=False)
    for key, table in episodes.items():
        table.to_csv(output / f"{key}.csv", index=False)
    summary = {
        "scope": scope,
        "scope_role": (
            "actual_product_evidence"
            if scope == "actual"
            else "proxy_mechanism_only"
        ),
        "headline_metrics": headline.reset_index().to_dict(orient="records"),
        "chronological_metrics": chronological.to_dict(orient="records"),
        "diagnostics": diagnostics,
    }
    _write_json(output / "scope_summary.json", summary)
    return summary


def _strategy_map(scope: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row["strategy"]): dict(row) for row in scope["headline_metrics"]}


def _pct(value: Any, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value) * 100:.{digits}f}%"


def _number(value: Any, digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):.{digits}f}"


def _integer(value: Any) -> str:
    if value is None or pd.isna(value):
        return "0"
    return str(int(value))


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def _final_gate(
    actual: Mapping[str, Any],
    proxy: Mapping[str, Any],
) -> dict[str, Any]:
    actual_metrics = _strategy_map(actual)
    proxy_metrics = _strategy_map(proxy)
    scope_gate = actual["diagnostics"]["scope_gate"]
    actual_cagr_delta = (
        float(actual_metrics[COMBINED]["cagr"])
        - float(actual_metrics[DEFENSE_ONLY]["cagr"])
    )
    proxy_cagr_delta = (
        float(proxy_metrics[COMBINED]["cagr"])
        - float(proxy_metrics[DEFENSE_ONLY]["cagr"])
    )
    actual_calmar_delta = (
        float(actual_metrics[COMBINED]["calmar"])
        - float(actual_metrics[DEFENSE_ONLY]["calmar"])
    )
    proxy_calmar_delta = (
        float(proxy_metrics[COMBINED]["calmar"])
        - float(proxy_metrics[DEFENSE_ONLY]["calmar"])
    )
    direction_agreement = {
        "cagr_delta_vs_defense_only": (
            actual_cagr_delta > 0.0 and proxy_cagr_delta > 0.0
        ),
        "calmar_delta_vs_defense_only": (
            actual_calmar_delta > 0.0 and proxy_calmar_delta > 0.0
        ),
    }
    checks = {**scope_gate["checks"], **direction_agreement}
    return {
        "checks": checks,
        "actual_scope_gate": scope_gate,
        "cross_sample_metrics": {
            "actual_cagr_delta_vs_defense_only": actual_cagr_delta,
            "proxy_cagr_delta_vs_defense_only": proxy_cagr_delta,
            "actual_calmar_delta_vs_defense_only": actual_calmar_delta,
            "proxy_calmar_delta_vs_defense_only": proxy_calmar_delta,
        },
        "shadow_candidate_authorized": bool(all(checks.values())),
        "direct_promotion_authorized": False,
    }


def _decision(gate: Mapping[str, Any]) -> str:
    checks = gate["checks"]
    if gate["shadow_candidate_authorized"]:
        return "post_defense_state2_accelerator_shadow_supported"
    if not checks["cagr_gap"]:
        return "accelerator_does_not_restore_enough_cagr"
    if not checks["max_drawdown_improvement"]:
        return "accelerator_gives_back_defense_protection"
    if not checks["late_segment_calmar"]:
        return "accelerator_not_chronologically_stable"
    if not checks["accelerator_event_positive_rate"]:
        return "accelerator_event_hit_rate_too_low"
    if not checks["event_concentration"]:
        return "accelerator_benefit_too_concentrated"
    if (
        not checks["cagr_delta_vs_defense_only"]
        or not checks["calmar_delta_vs_defense_only"]
    ):
        return "accelerator_not_supported_by_long_history_proxy"
    return "post_defense_state2_accelerator_not_supported"


def _report(
    actual: Mapping[str, Any],
    proxy: Mapping[str, Any],
    final_gate: Mapping[str, Any],
    identity: Mapping[str, Any],
    contract_paths: Mapping[str, Path],
) -> str:
    strategies = [BASELINE, DEFENSE_ONLY, TAG_ONLY, COMBINED]
    names = {
        BASELINE: "当前 v4.2",
        DEFENSE_ONLY: "RSI×VIX 防守",
        TAG_ONLY: "仅条件式加速",
        COMBINED: "防守 + state 2 加速",
    }
    actual_metrics = _strategy_map(actual)
    proxy_metrics = _strategy_map(proxy)
    headline_rows: list[list[str]] = []
    for key in strategies:
        row = actual_metrics[key]
        headline_rows.append(
            [
                names[key],
                _pct(row["total_return"]),
                _pct(row["cagr"]),
                _pct(row["annual_volatility"]),
                _number(row["sharpe"]),
                _number(row["sortino"]),
                _pct(row["max_drawdown"]),
                _number(row["calmar"]),
                _number(row["turnover_units"], 1),
                _integer(row.get("accelerated_sessions")),
            ]
        )

    tail = actual["diagnostics"]["tail_risk"]
    tail_rows = [
        [
            names[key],
            _pct(tail[key]["expected_shortfall_95"]),
            _pct(tail[key]["worst_5d_return"]),
            _pct(tail[key]["worst_10d_return"]),
            _pct(tail[key]["worst_20d_return"]),
            str(tail[key]["maximum_underwater_run_sessions"]),
            _number(tail[key]["ulcer_index"], 4),
        ]
        for key in strategies
    ]

    chronological = pd.DataFrame(actual["chronological_metrics"])
    chrono_rows: list[list[str]] = []
    for key in strategies:
        for segment in ("early", "late"):
            row = chronological.loc[
                (chronological["strategy"] == key)
                & (chronological["segment"] == segment)
            ].iloc[0]
            chrono_rows.append(
                [
                    names[key],
                    "早期 60%" if segment == "early" else "后期 40%",
                    _pct(row["cagr"]),
                    _pct(row["max_drawdown"]),
                    _number(row["sharpe"]),
                    _number(row["calmar"]),
                ]
            )

    proxy_rows = [
        [
            names[key],
            _pct(actual_metrics[key]["cagr"]),
            _pct(proxy_metrics[key]["cagr"]),
            _pct(actual_metrics[key]["max_drawdown"]),
            _pct(proxy_metrics[key]["max_drawdown"]),
            _number(actual_metrics[key]["calmar"]),
            _number(proxy_metrics[key]["calmar"]),
        ]
        for key in strategies
    ]

    gate_rows = [
        [name, "通过" if passed else "未通过"]
        for name, passed in final_gate["checks"].items()
    ]
    actual_gate_metrics = final_gate["actual_scope_gate"]["metrics"]
    accelerator_summary = actual["diagnostics"]["accelerator_summary"][COMBINED]
    decision = _decision(final_gate)
    contract_lines = "\n".join(
        f"- `{name}`: `{path}` (`{_sha256(path)}`)"
        for name, path in contract_paths.items()
    )
    sample = actual["diagnostics"]["sample"]
    cross = final_gate["cross_sample_metrics"]

    lines = [
        "# RSI×VIX 防守 + 正式 state 2 条件式 TQQQ 加速：详细回测报告",
        "",
        "## 执行结论",
        "",
        f"- 决策分类：`{decision}`。",
        (
            "- 全部预注册门槛通过，只允许进入非行动性 shadow 监控。"
            if final_gate["shadow_candidate_authorized"]
            else "- 未通过全部预注册门槛，v4.2 保持唯一行动性研究基线。"
        ),
        "- 本实验没有修改 RSI、VIX、SGOV、防守确认或 v4.2 状态规则。",
        "- 加速只发生在完成一次防守后首次正式执行的连续 state 2 episode。",
        "",
        "## 1. 冻结规则与证据身份",
        "",
        f"- 实际产品样本：{sample['start']} 至 {sample['end']}，{sample['observations']} 个观测。",
        "- 防守规则完全继承 PR #467。",
        "- ordinary state 2：25% QQQ / 75% TQQQ。",
        "- accelerated state 2：100% TQQQ。",
        "- 每次防守释放只允许一次加速机会；进入第一个 state 2 episode 后即消耗。",
        "- 收盘生成状态，下一交易日开盘执行；每单位换手成本 10 bps。",
        f"- 数据身份：`{json.dumps(identity, ensure_ascii=False, sort_keys=True)}`。",
        "",
        contract_lines,
        "",
        "## 2. 实际产品样本：总体结果",
        "",
        _markdown_table(
            [
                "模型",
                "总收益",
                "CAGR",
                "波动率",
                "Sharpe",
                "Sortino",
                "最大回撤",
                "Calmar",
                "换手",
                "加速日",
            ],
            headline_rows,
        ),
        "",
        "## 3. 尾部风险",
        "",
        _markdown_table(
            [
                "模型",
                "ES 95%",
                "最差 5 日",
                "最差 10 日",
                "最差 20 日",
                "最长水下期",
                "Ulcer",
            ],
            tail_rows,
        ),
        "",
        "## 4. 时间稳定性",
        "",
        _markdown_table(
            ["模型", "分段", "CAGR", "最大回撤", "Sharpe", "Calmar"],
            chrono_rows,
        ),
        "",
        "## 5. 实际产品与长历史代理",
        "",
        _markdown_table(
            [
                "模型",
                "实际 CAGR",
                "代理 CAGR",
                "实际回撤",
                "代理回撤",
                "实际 Calmar",
                "代理 Calmar",
            ],
            proxy_rows,
        ),
        "",
        "## 6. 加速事件归因",
        "",
        f"- 加速 episode：{accelerator_summary['event_count']} 个。",
        f"- 正增量 episode：{accelerator_summary['positive_event_count']} 个。",
        f"- 正增量率：{_pct(accelerator_summary['positive_event_rate'])}。",
        f"- 中位增量收益：{_pct(accelerator_summary.get('median_marginal_return'))}。",
        f"- 正贡献合计：{_pct(accelerator_summary['total_positive_marginal_return'])}。",
        f"- 负贡献合计：{_pct(accelerator_summary['total_negative_marginal_return'])}。",
        f"- 最大正事件贡献占比：{_pct(accelerator_summary['largest_positive_event_share'])}。",
        "",
        "## 7. 晋级门槛",
        "",
        _markdown_table(["门槛", "结果"], gate_rows),
        "",
        f"- 最大回撤改善：{actual_gate_metrics['max_drawdown_improvement_pp']:.2f} pp。",
        f"- 相对 v4.2 CAGR 差距：{actual_gate_metrics['cagr_gap_pp']:.2f} pp。",
        f"- 防守模型 CAGR 损失收回比例：{actual_gate_metrics['defense_cagr_sacrifice_recovered_fraction']:.1%}。",
        f"- 后期候选 Calmar：{actual_gate_metrics['late_candidate_calmar']:.3f}；v4.2：{actual_gate_metrics['late_baseline_calmar']:.3f}。",
        f"- 最差 20 日相对 v4.2 变化：{actual_gate_metrics['worst_20d_delta_pp']:.2f} pp。",
        f"- 实际 CAGR 增量 vs 防守：{cross['actual_cagr_delta_vs_defense_only'] * 100:.2f} pp。",
        f"- 代理 CAGR 增量 vs 防守：{cross['proxy_cagr_delta_vs_defense_only'] * 100:.2f} pp。",
        f"- 实际 Calmar 增量 vs 防守：{cross['actual_calmar_delta_vs_defense_only']:.3f}。",
        f"- 代理 Calmar 增量 vs 防守：{cross['proxy_calmar_delta_vs_defense_only']:.3f}。",
        "",
        "## 8. 研究解释",
        "",
        "本实验检验的是防守后风险预算的条件式再部署，而不是更早预测反弹。",
        "只有原始 v4.2 已正式进入 state 2，额外 25% QQQ 才会替换为 TQQQ。",
        "即使回测通过，也只能建立非行动性 shadow candidate，不能直接改变 Telegram 或目标权重。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/"
            "qqqi_qqq_tqqq_v4_2_post_defense_state2_accelerator_v4_10_research.yaml"
        ),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--etf-data-bundle", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "artifacts/evidence/"
            "qqqi_qqq_tqqq_v4_2_post_defense_state2_accelerator_v4_10_research"
        ),
    )
    args = parser.parse_args()
    accelerator_contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    contract_paths = {
        "accelerator": args.contract,
        "defense": Path(accelerator_contract["boundaries"]["defense_contract"]),
        "baseline": Path(accelerator_contract["boundaries"]["baseline_contract"]),
        "sgov": Path(accelerator_contract["boundaries"]["sgov_contract"]),
        "attribution": Path(
            accelerator_contract["boundaries"]["attribution_contract"]
        ),
    }
    contracts = {
        name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, path in contract_paths.items()
    }
    bars, coverage, identity = fetch_governed_etf_strategy_bars(
        symbols=list(dict.fromkeys(accelerator_contract["data"]["required_symbols"])),
        start=accelerator_contract["data"]["start_date"],
        end=args.end_date or accelerator_contract["data"].get("end_date"),
        bundle_dir=args.etf_data_bundle,
    )
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    actual = _scope_run(
        bars,
        "actual",
        output / "actual",
        contracts["baseline"],
        contracts["sgov"],
        contracts["attribution"],
        contracts["defense"],
        contracts["accelerator"],
    )
    proxy_bars = dict(bars)
    proxy_bars["QQQI"] = bars["QQQ"].copy()
    proxy = _scope_run(
        proxy_bars,
        "qqq_proxy",
        output / "qqq_proxy",
        contracts["baseline"],
        contracts["sgov"],
        contracts["attribution"],
        contracts["defense"],
        contracts["accelerator"],
    )
    final_gate = _final_gate(actual, proxy)
    decision = _decision(final_gate)
    report = _report(actual, proxy, final_gate, identity, contract_paths)
    (output / "detailed_report_zh.md").write_text(report, encoding="utf-8")
    summary = {
        "schema_version": "1.0",
        "experiment_id": accelerator_contract["experiment_id"],
        "parent_experiment_id": accelerator_contract["parent_experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "data_identity": identity,
        "actual": actual,
        "qqq_proxy": proxy,
        "promotion_gate": final_gate,
        "decision": decision,
        "v4_2_unchanged": True,
        "telegram_targets_unchanged": True,
        "issue_348_unchanged": True,
        "direct_promotion_authorized": False,
    }
    _write_json(output / "experiment_summary.json", summary)

    files: dict[str, str] = {}
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "evidence_manifest.json":
            files[str(path.relative_to(output))] = _sha256(path)
    manifest = {
        "schema_version": "1.0",
        "experiment_id": accelerator_contract["experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "files": files,
    }
    _write_json(output / "evidence_manifest.json", manifest)
    print(
        json.dumps(
            {
                "decision": decision,
                "shadow_candidate_authorized": final_gate[
                    "shadow_candidate_authorized"
                ],
                "actual_sample": actual["diagnostics"]["sample"],
                "proxy_sample": proxy["diagnostics"]["sample"],
                "output_dir": str(output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
