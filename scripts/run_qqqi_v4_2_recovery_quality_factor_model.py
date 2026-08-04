#!/usr/bin/env python3
"""Run the frozen v4.11 recovery-quality factor and strategy-budget experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.v4_2_recovery_quality_factor_model import (
    FactorModelOutput,
    run_recovery_quality_factor_experiment,
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
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default)
        + "\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pct(value: Any, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value) * 100:.{digits}f}%"


def _num(value: Any, digits: int = 3) -> str:
    if value is None or pd.isna(value):
        return "—"
    return f"{float(value):.{digits}f}"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def _report(
    model: FactorModelOutput,
    headline: Mapping[str, pd.DataFrame],
    episodes: Mapping[str, pd.DataFrame],
    diagnostics: Mapping[str, Any],
    identity: Mapping[str, Any],
) -> str:
    names = {
        "current_v4_2": "当前 v4.2",
        "factor_defensive_ablation": "因子防守消融",
        "factor_offensive_ablation": "因子进攻消融",
        "factor_joint_budget": "因子联合风险预算",
    }
    rows: list[list[str]] = []
    for key in names:
        metrics = headline["actual"].loc[key]
        rows.append(
            [
                names[key],
                _pct(metrics["total_return"]),
                _pct(metrics["cagr"]),
                _pct(metrics["annual_volatility"]),
                _num(metrics["sharpe"]),
                _num(metrics["sortino"]),
                _pct(metrics["max_drawdown"]),
                _num(metrics["calmar"]),
                _num(metrics["turnover_units"], 1),
            ]
        )
    proxy_rows: list[list[str]] = []
    for key in names:
        actual = headline["actual"].loc[key]
        proxy = headline["qqq_proxy"].loc[key]
        proxy_rows.append(
            [
                names[key],
                _pct(actual["cagr"]),
                _pct(proxy["cagr"]),
                _pct(actual["max_drawdown"]),
                _pct(proxy["max_drawdown"]),
                _num(actual["calmar"]),
                _num(proxy["calmar"]),
            ]
        )
    fold_rows = [
        [
            str(int(row.validation_year)),
            _num(row.roc_auc),
            _num(row.spearman_ic),
            _pct(row.top_bottom_quartile_spread),
            str(int(row.observations)),
        ]
        for row in model.fold_metrics.itertuples()
    ]
    episode_rows: list[list[str]] = []
    for row in episodes["actual"].itertuples():
        episode_rows.append(
            [
                str(row.event_id),
                pd.Timestamp(row.entry_date).date().isoformat(),
                pd.Timestamp(row.exit_date).date().isoformat(),
                str(row.factor_bucket),
                _num(row.factor_probability),
                str(int(row.sessions)),
                _pct(row.relative_return),
                _pct(row.relative_mae),
                _pct(row.relative_mfe),
            ]
        )
    factor_gate = diagnostics["factor_gate"]
    strategy_gate = diagnostics["strategy_gate"]
    factor_gate_rows = [
        [key, "通过" if bool(value) else "未通过"]
        for key, value in factor_gate["checks"].items()
    ]
    strategy_gate_rows = [
        [key, "通过" if bool(value) else "未通过"]
        for key, value in strategy_gate["checks"].items()
    ]
    coefficient_rows = [
        [str(row.feature), _num(row.coefficient, 4)]
        for row in model.coefficients.itertuples()
    ]
    metrics = model.aggregate_metrics
    lines = [
        "# v4.2 recovery-quality 因子模型与风险预算回测", "",
        "## 执行结论", "",
        f"- 最终分类：`{diagnostics['decision']}`。",
        "- 因子门槛通过。" if factor_gate["passed"] else "- 因子门槛未通过，策略收益不能解释为稳定模型优势。",
        "- 策略门槛通过，只能进入非行动性 shadow。" if strategy_gate["passed"] else "- 策略门槛未全部通过，v4.2 保持不变。",
        "- 本实验没有改变 v4.2、Telegram 或 Issue #348。", "",
        "## 1. 研究边界", "",
        "- 模型只预测未来十个交易日 TQQQ 相对 QQQ 的边际对数收益。",
        "- 2017—2023 使用十日 purge 的扩展式 walk-forward；2024 年以后完全保留。",
        "- 一个 state-2 episode 只在入场前一收盘读取一次概率，episode 内不日频调仓。",
        "- 固定映射：低分 50% TQQQ，中间 75%，高分 100%。",
        f"- 数据身份：`{json.dumps(identity, ensure_ascii=False, sort_keys=True)}`。", "",
        "## 2. pre-2024 walk-forward 因子证据", "",
        f"- Aggregate ROC AUC：{_num(metrics['roc_auc'])}。",
        f"- Aggregate Spearman IC：{_num(metrics['spearman_ic'])}。",
        f"- 顶／底四分位未来边际收益差：{_pct(metrics['top_bottom_quartile_spread'])}。",
        f"- 正向年份比例：{_pct(metrics['positive_validation_year_rate'])}。",
        f"- 最大正向年份贡献占比：{_pct(metrics['largest_positive_year_share'])}。", "",
        _table(["验证年", "AUC", "Spearman IC", "顶底四分位差", "样本"], fold_rows), "",
        "## 3. 实际 QQQI 保留样本组合结果", "",
        _table(
            ["模型", "总收益", "CAGR", "波动率", "Sharpe", "Sortino", "最大回撤", "Calmar", "换手"],
            rows,
        ), "",
        "## 4. 实际产品与 QQQ 代理方向", "",
        _table(
            ["模型", "实际 CAGR", "代理 CAGR", "实际回撤", "代理回撤", "实际 Calmar", "代理 Calmar"],
            proxy_rows,
        ), "",
        "## 5. 实际样本 state-2 episode 归因", "",
        _table(
            ["事件", "进入", "退出", "分桶", "概率", "日数", "相对收益", "相对 MAE", "相对 MFE"],
            episode_rows,
        ) if episode_rows else "实际样本没有完整 state-2 episode。",
        "", "## 6. 因子门槛", "", _table(["门槛", "结果"], factor_gate_rows),
        "", "## 7. 策略门槛", "", _table(["门槛", "结果"], strategy_gate_rows),
        "", "## 8. 标准化逻辑回归系数", "",
        "系数只解释冻结模型方向，不能据此在本样本删除或增加因子。", "",
        _table(["因子", "系数"], coefficient_rows), "",
        "## 9. 研究纪律", "",
        "无论结果如何，禁止在当前样本修改标签周期、特征、模型、概率阈值或50/75/100权重。",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/"
            "qqqi_qqq_tqqq_v4_2_recovery_quality_factor_v4_11_research.yaml"
        ),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--etf-data-bundle", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "artifacts/evidence/"
            "qqqi_qqq_tqqq_v4_2_recovery_quality_factor_v4_11_research"
        ),
    )
    args = parser.parse_args()

    factor_contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    baseline_path = Path(factor_contract["boundaries"]["baseline_contract"])
    bridge_contract = yaml.safe_load(baseline_path.read_text(encoding="utf-8"))
    bars, coverage, identity = fetch_governed_etf_strategy_bars(
        symbols=list(factor_contract["data"]["required_symbols"]),
        start=str(factor_contract["data"]["start_date"]),
        end=args.end_date or factor_contract["data"].get("end_date"),
        bundle_dir=args.etf_data_bundle,
    )
    proxy_bars = dict(bars)
    proxy_bars["QQQI"] = bars["QQQ"].copy()

    model, headline, results, episodes, diagnostics = (
        run_recovery_quality_factor_experiment(
            bars,
            proxy_bars,
            bridge_contract,
            factor_contract,
        )
    )

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    model.oof_predictions.to_csv(output / "oof_predictions.csv")
    model.holdout_predictions.to_csv(output / "holdout_predictions.csv")
    model.fold_metrics.to_csv(output / "walk_forward_fold_metrics.csv", index=False)
    model.coefficients.to_csv(output / "model_coefficients.csv", index=False)
    _write_json(output / "model_aggregate_metrics.json", model.aggregate_metrics)

    for scope in ("actual", "qqq_proxy"):
        scope_dir = output / scope
        scope_dir.mkdir(parents=True, exist_ok=True)
        headline[scope].to_csv(scope_dir / "headline_metrics.csv")
        episodes[scope].to_csv(scope_dir / "state2_episodes.csv", index=False)
        for key, result in results[scope].items():
            result.daily.to_csv(scope_dir / f"daily_{key}.csv")
            result.trades.to_csv(scope_dir / f"trades_{key}.csv", index=False)

    summary = {
        "schema_version": "1.0",
        "experiment_id": factor_contract["experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "data_identity": identity,
        "feature_names": list(model.feature_names),
        "headline": {
            scope: table.reset_index().to_dict(orient="records")
            for scope, table in headline.items()
        },
        "diagnostics": diagnostics,
    }
    _write_json(output / "experiment_summary.json", summary)
    report = _report(model, headline, episodes, diagnostics, identity)
    (output / "report.md").write_text(report, encoding="utf-8")

    files = sorted(
        path for path in output.rglob("*") if path.is_file() and path.name != "evidence_manifest.json"
    )
    manifest = {
        "schema_version": "1.0",
        "experiment_id": factor_contract["experiment_id"],
        "contract_path": str(args.contract),
        "contract_sha256": _sha256(args.contract),
        "baseline_contract_path": str(baseline_path),
        "baseline_contract_sha256": _sha256(baseline_path),
        "files": {
            str(path.relative_to(output)): _sha256(path)
            for path in files
        },
    }
    _write_json(output / "evidence_manifest.json", manifest)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
