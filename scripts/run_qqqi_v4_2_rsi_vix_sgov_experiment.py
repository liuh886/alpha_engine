#!/usr/bin/env python3
"""Run the frozen RSI × VIX adaptive SGOV ablation and write a detailed report."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.v4_2_rsi_vix_sgov_experiment import run_rsi_vix_sgov_comparison


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default)
        + "\n",
        encoding="utf-8",
    )


def _scope_run(
    bars: Mapping[str, pd.DataFrame],
    scope: str,
    output: Path,
    baseline_contract: Mapping[str, Any],
    sgov_contract: Mapping[str, Any],
    attribution_contract: Mapping[str, Any],
    overlay_contract: Mapping[str, Any],
) -> dict[str, Any]:
    headline, results, chronological, episodes, diagnostics = (
        run_rsi_vix_sgov_comparison(
            bars,
            baseline_contract,
            sgov_contract,
            attribution_contract,
            overlay_contract,
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
        "scope_role": "actual_product_evidence" if scope == "actual" else "proxy_mechanism_only",
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


def _markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def _decision(gate: Mapping[str, Any]) -> str:
    checks = gate["checks"]
    if bool(gate["shadow_candidate_authorized"]):
        return "joint_overlay_shadow_supported"
    if checks["max_drawdown_improvement"] and not checks["median_recovery_lag"]:
        return "downside_improves_recovery_fails"
    if checks["median_recovery_lag"] and not checks["max_drawdown_improvement"]:
        return "recovery_improves_downside_insufficient"
    if not checks["beats_vix_only_on_two_metrics"] or not checks["beats_rsi_only_on_two_metrics"]:
        return "rsi_adds_no_incremental_value"
    if not checks["chronological_stability"]:
        return "benefit_not_chronologically_stable"
    if not checks["event_concentration"]:
        return "event_concentration_too_high"
    return "adaptive_overlay_not_supported"


def _report(
    actual: Mapping[str, Any],
    proxy: Mapping[str, Any],
    identity: Mapping[str, Any],
    contract_paths: Mapping[str, Path],
) -> str:
    actual_metrics = _strategy_map(actual)
    proxy_metrics = _strategy_map(proxy)
    strategies = [
        "current_v4_2",
        "static_blended_sgov",
        "vix_only_adaptive_sgov",
        "rsi_only_adaptive_sgov",
        "rsi_vix_adaptive_sgov",
    ]
    names = {
        "current_v4_2": "v4.2",
        "static_blended_sgov": "静态 QQQI/SGOV",
        "vix_only_adaptive_sgov": "VIX-only 自适应",
        "rsi_only_adaptive_sgov": "RSI-only 自适应",
        "rsi_vix_adaptive_sgov": "RSI × VIX 自适应",
    }
    headline_rows = []
    for key in strategies:
        row = actual_metrics[key]
        headline_rows.append([
            names[key], _pct(row["total_return"]), _pct(row["cagr"]),
            _pct(row["annual_volatility"]), _number(row["sharpe"]),
            _number(row["sortino"]), _pct(row["max_drawdown"]),
            _number(row["calmar"]), _number(row["turnover_units"], 1),
        ])
    tail = actual["diagnostics"]["tail_risk"]
    tail_rows = []
    for key in strategies:
        row = tail[key]
        tail_rows.append([
            names[key], _pct(row["expected_shortfall_95"]),
            _pct(row["worst_5d_return"]), _pct(row["worst_10d_return"]),
            _pct(row["worst_20d_return"]), str(row["maximum_underwater_run_sessions"]),
            _number(row["ulcer_index"], 4),
        ])
    opportunity = actual["diagnostics"]["opportunity_metrics"]
    false_defense = actual["diagnostics"]["false_defense"]
    opportunity_rows = []
    for key in strategies:
        row = opportunity[key]
        false_row = false_defense.get(key, {})
        opportunity_rows.append([
            names[key], _number(row["upside_capture_vs_qqq"]),
            _number(row["downside_capture_vs_qqq"]),
            _pct(row["qqq_top_decile_sgov_exposure_rate"]),
            _pct(false_row.get("false_defense_rate")),
            _pct(actual_metrics[key].get("average_sgov_weight")),
        ])
    gate = actual["diagnostics"]["promotion_gate"]
    gate_rows = [[name, "通过" if passed else "未通过"] for name, passed in gate["checks"].items()]
    gate_metrics = gate["metrics"]
    decision = _decision(gate)
    proxy_rows = []
    for key in strategies:
        actual_row = actual_metrics[key]
        proxy_row = proxy_metrics[key]
        proxy_rows.append([
            names[key], _pct(actual_row["cagr"]), _pct(proxy_row["cagr"]),
            _pct(actual_row["max_drawdown"]), _pct(proxy_row["max_drawdown"]),
            _number(actual_row["calmar"]), _number(proxy_row["calmar"]),
        ])
    chronological = pd.DataFrame(actual["chronological_metrics"])
    chrono_rows = []
    for key in strategies:
        for segment in ("early", "late"):
            row = chronological.loc[
                (chronological["strategy"] == key) & (chronological["segment"] == segment)
            ].iloc[0]
            chrono_rows.append([
                names[key], "早期 60%" if segment == "early" else "后期 40%",
                _pct(row["cagr"]), _pct(row["max_drawdown"]),
                _number(row["sharpe"]), _number(row["calmar"]),
            ])
    sample = actual["diagnostics"]["sample"]
    contract_lines = "\n".join(
        f"- `{name}`: `{path}` (`{_sha256(path)}`)" for name, path in contract_paths.items()
    )
    lines = [
        "# QQQ v4.2 与 RSI × VIX 自适应 SGOV 回测报告", "",
        "## 结论", "", f"- 决策分类：`{decision}`。",
        "- 联合模型通过全部门槛，只能进入非行动性 shadow 监控。"
        if gate["shadow_candidate_authorized"] else "- 联合模型未通过全部晋级门槛，v4.2 保持不变。",
        "- 本实验没有修改 v4.2 状态序列、state 2 权重、Telegram 信号或 Issue #348。", "",
        "## 实验边界", "",
        f"- 实际产品样本：{sample['start']} 至 {sample['end']}，{sample['observations']} 个观测。",
        "- 交易成本：每单位换手 10 bps；收盘生成信号，下一交易日开盘执行。",
        "- RSI：QQQ Wilder RSI(14)；激活 `<45`，释放 `>50` 连续两个收盘。",
        "- 联合激活要求 VIX stress；联合释放要求 VIX easing 或 normalized。",
        "- state 2 始终为 25% QQQ / 75% TQQQ。",
        f"- 数据身份：`{json.dumps(identity, ensure_ascii=False, sort_keys=True)}`。", "", contract_lines, "",
        "## 1. 实际产品样本：总体表现", "",
        _markdown_table(["模型", "总收益", "CAGR", "波动率", "Sharpe", "Sortino", "最大回撤", "Calmar", "换手单位"], headline_rows), "",
        "## 2. 尾部风险与水下期", "",
        _markdown_table(["模型", "ES 95%", "最差 5 日", "最差 10 日", "最差 20 日", "最长水下期", "Ulcer"], tail_rows), "",
        "## 3. 上涨捕捉、下跌捕捉与 SGOV 机会成本", "",
        _markdown_table(["模型", "上涨捕捉", "下跌捕捉", "顶十分位上涨日仍持 SGOV", "错误防守率", "平均 SGOV 权重"], opportunity_rows), "",
        "## 4. 时间稳定性", "",
        _markdown_table(["模型", "分段", "CAGR", "最大回撤", "Sharpe", "Calmar"], chrono_rows), "",
        "## 5. 实际产品与 QQQ 长历史代理", "",
        "代理样本只把防守端 QQQI 替换为 QQQ，用于检查机制方向，不能当作真实产品业绩。", "",
        _markdown_table(["模型", "实际 CAGR", "代理 CAGR", "实际回撤", "代理回撤", "实际 Calmar", "代理 Calmar"], proxy_rows), "",
        "## 6. RSI × VIX 晋级门槛", "", _markdown_table(["门槛", "结果"], gate_rows), "",
        f"- 最大回撤改善：{gate_metrics['max_drawdown_improvement_pp']:.2f} pp。",
        f"- CAGR 牺牲：{gate_metrics['cagr_sacrifice_pp']:.2f} pp。",
        f"- 主要回撤改善率：{gate_metrics['major_trough_improvement_rate']:.1%}。",
        f"- 主要谷底中位保护：{gate_metrics['median_major_trough_protection_pp']:.2f} pp。",
        f"- 中位复苏延迟：{gate_metrics['median_recovery_lag_sessions']} 个交易日。",
        f"- 最大正贡献事件占比：{gate_metrics['largest_positive_event_share']:.1%}。", "",
        "## 7. 方法解释", "",
        "RSI 只描述 QQQ 的短期价格恶化或修复；VIX 确认是否伴随系统性压力扩张或收敛。",
        "任何回测结果都不能直接改变 v4.2；通过也只能建立非行动性的 shadow candidate。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=Path("configs/research_paradigms/qqqi_qqq_tqqq_v4_2_rsi_vix_adaptive_sgov_v4_9_research.yaml"))
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--etf-data-bundle", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/evidence/qqqi_qqq_tqqq_v4_2_rsi_vix_adaptive_sgov_v4_9_research"))
    args = parser.parse_args()
    overlay_contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    contract_paths = {
        "overlay": args.contract,
        "baseline": Path(overlay_contract["boundaries"]["baseline_contract"]),
        "sgov": Path(overlay_contract["boundaries"]["sgov_contract"]),
        "attribution": Path(overlay_contract["boundaries"]["attribution_contract"]),
    }
    baseline_contract = yaml.safe_load(contract_paths["baseline"].read_text(encoding="utf-8"))
    sgov_contract = yaml.safe_load(contract_paths["sgov"].read_text(encoding="utf-8"))
    attribution_contract = yaml.safe_load(contract_paths["attribution"].read_text(encoding="utf-8"))
    bars, coverage, identity = fetch_governed_etf_strategy_bars(
        symbols=list(dict.fromkeys(overlay_contract["data"]["required_symbols"])),
        start=overlay_contract["data"]["start_date"],
        end=args.end_date or overlay_contract["data"].get("end_date"),
        bundle_dir=args.etf_data_bundle,
    )
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    actual = _scope_run(bars, "actual", output / "actual", baseline_contract, sgov_contract, attribution_contract, overlay_contract)
    proxy_bars = dict(bars)
    proxy_bars["QQQI"] = bars["QQQ"].copy()
    proxy = _scope_run(proxy_bars, "qqq_proxy", output / "qqq_proxy", baseline_contract, sgov_contract, attribution_contract, overlay_contract)
    gate = actual["diagnostics"]["promotion_gate"]
    decision = _decision(gate)
    summary = {
        "schema_version": "1.0", "experiment_id": overlay_contract["experiment_id"],
        "research_only": True, "trade_ready": False, "data_identity": identity,
        "contracts": {name: {"path": str(path), "sha256": _sha256(path)} for name, path in contract_paths.items()},
        "actual": actual, "qqq_proxy": proxy, "decision": decision,
        "shadow_candidate_authorized": bool(gate["shadow_candidate_authorized"]),
        "direct_promotion_authorized": False, "v4_2_changed": False, "issue_348_changed": False,
    }
    _write_json(output / "experiment_summary.json", summary)
    (output / "backtest_report_zh.md").write_text(_report(actual, proxy, identity, contract_paths), encoding="utf-8")
    manifest = {
        "schema_version": "1.0", "experiment_id": overlay_contract["experiment_id"],
        "outputs": {str(path.relative_to(output)): _sha256(path) for path in sorted(output.rglob("*")) if path.is_file()},
    }
    _write_json(output / "evidence_manifest.json", manifest)
    print(json.dumps({"decision": decision, "report": str(output / "backtest_report_zh.md")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
