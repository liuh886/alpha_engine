"""Decision report for the complete frozen E6 matrix; never selects a winner."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics

import pandas as pd

from src.research.e5_score_reconstruction import sha, write_json
from src.research.e6_execution import compare, contract
from src.research.e6_forward import status


def collect(root: Path, cfg: dict) -> dict:
    rows = []
    code = None
    for arm in cfg["arms"]:
        for strategy in cfg["strategies"]:
            for fold in cfg["folds"]:
                folder = root / "results" / arm["id"] / strategy / fold
                row = json.loads((folder / "result.json").read_bytes())
                if (row["arm_id"], row["configuration_id"], row["fold_id"]) != (
                    arm["id"],
                    strategy,
                    fold,
                ):
                    raise ValueError("E6 result identity mismatch")
                if code is not None and code != row["code_sha256"]:
                    raise ValueError("mixed E6 evaluator versions")
                code = row["code_sha256"]
                for name, digest in row["files"].items():
                    if sha(folder / name) != digest:
                        raise ValueError("E6 result component hash mismatch")
                rows.append(row)
    return compare(rows, cfg)


def render(report: dict, cfg: dict, forward: dict) -> str:
    index = {(r["arm_id"], r["configuration_id"], r["fold_id"]): r for r in report["rows"]}
    primary = cfg["primary_forward_policy"]
    lines = [
        "# E6：低换手执行是否保留机器学习增量",
        "",
        "7项执行对照×4策略×8折，共224项后验执行评估；复用E5完整评分，模型拟合次数0。所有分支先通过E5延迟控制的数值复现，再使用同一1交易日延迟、Top5、8bps与验证日历。历史已经被观察，结果不是独立OOS。",
        "",
        "主策略在查看E6结果前按设计冻结为 `weekly_min5_buffer10_asc`；不会因其他对照表现更好而替换。7项为有限执行诊断，不是新的模型参数搜索。",
        "",
        "## 预先冻结的验收",
        "",
        "对60日和120日动量分别要求：同折配对中位数>0，至少6/8折为正，合计换手率不超过该基线1.5倍。回撤逐折报告，不事后制定通过线。即使历史数字通过，实际成交容量及真正前瞻仍须单独通过。",
        "",
        "## 所有配对结果",
        "",
        "|执行对照|模型|对60d中位数pp / 正折数 / 换手比|对120d中位数pp / 正折数 / 换手比|同时通过历史筛查|",
        "|---|---|---:|---:|---|",
    ]
    for arm in cfg["arms"]:
        for model in ("xgb_p03", "lgb_p05"):
            selected = [
                p for p in report["paired"] if p["arm_id"] == arm["id"] and p["model"] == model
            ]
            values = [
                f"{p['median_delta_pp']:+.2f} / {p['positive_folds']}/8 / {p['turnover_ratio']:.2f}x"
                for p in selected
            ]
            lines.append(
                f"|{arm['id']}|{model}|{values[0]}|{values[1]}|{'PASS' if all(p['predeclared_historical_screen_pass'] for p in selected) else 'FAIL'}|"
            )
    lines += [
        "",
        "## 评分并列敏感性",
        "",
        "三种规则均按分数降序，仅并列时分别使用股票代码升序、降序、带合同ID盐的SHA256。主规则升序，另外两项仅用于敏感性，不按事后收益选规则。",
        "",
        "|模型|8折中每折最大/最小净收益之差的中位数pp|最大差pp|",
        "|---|---:|---:|",
    ]
    for model in ("xgb_p03", "lgb_p05"):
        spreads = []
        for fold in cfg["folds"]:
            values = [
                index[(arm, model, fold)]["summary"]["net_return"]
                for arm in ("daily_asc", "daily_desc", "daily_hash")
            ]
            spreads.append(100 * (max(values) - min(values)))
        lines.append(f"|{model}|{statistics.median(spreads):.2f}|{max(spreads):.2f}|")
    lines += [
        "",
        "## 固定主策略逐折风险",
        "",
        "|策略|折|净收益%|超QQQ pp|回撤%|换手|最大漂移持仓%|",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for strategy in cfg["strategies"]:
        for fold in cfg["folds"]:
            r = index[(primary, strategy, fold)]["summary"]
            lines.append(
                f"|{strategy}|{fold}|{100 * r['net_return']:.2f}|{100 * r['net_excess']:.2f}|{100 * r['max_drawdown']:.2f}|{r['turnover']:.2f}|{100 * r['max_drifted_weight']:.2f}|"
            )
    lines += [
        "",
        "## 换手是否降低",
        "",
        "|策略|每日升序换手合计|固定主策略换手合计|下降比例|",
        "|---|---:|---:|---:|",
    ]
    for strategy in cfg["strategies"]:
        base = sum(index[("daily_asc", strategy, f)]["summary"]["turnover"] for f in cfg["folds"])
        low = sum(index[(primary, strategy, f)]["summary"]["turnover"] for f in cfg["folds"])
        lines.append(f"|{strategy}|{base:.2f}|{low:.2f}|{100 * (1 - low / base):.1f}%|")
    lines += [
        "",
        "## 成交容量：门禁与代理分开",
        "",
        "73个股票均从原始v6归档匹配价格和成交量，且逐值核对Volume未被替换。代理采用原始Close×Volume的过去20交易日均值，窗口截止成交日前一交易日；包含建仓、调仓及被迫折末清仓。未使用成交日或未来成交量。",
        "",
        "参与率1%、折初资金100万/1000万美元均为预设研究场景，不代表账户。按交易权重与当日模拟净值反推初始资金上限；Close×Volume不是实际成交额或VWAP。此工具在超限时拒绝容量验收，没有伪造部分成交，收益表也不是受容量约束后已实现的收益。",
        "",
        "|主策略|交易腿数量|100万美元场景超限腿数|1000万美元场景超限腿数|最小初始资金上限代理USD|",
        "|---|---:|---:|---:|---:|",
    ]
    for strategy in cfg["strategies"]:
        values = [index[(primary, strategy, f)]["capacity"] for f in cfg["folds"]]
        lines.append(
            f"|{strategy}|{sum(r['proxy_events'] for r in values)}|{sum(r['scenario_1m_breaches'] for r in values)}|{sum(r['scenario_10m_breaches'] for r in values)}|{min(r['min_initial_capital_ceiling_proxy'] for r in values):,.0f}|"
        )
    lines += [
        "",
        "**实际容量门禁：BLOCKED。** 供应商历史Volume未被认证为当时实际股数，原始响应于2026-11-06取得，不能倒称历史首次可用。缺少实际点差、冲击、盘口及成交证据；高波动率与容量细节按每条交易腿的滞后20日波动率保存，不能仅凭代理低参与率宣布可成交。",
        "",
        "## 真正前瞻准备",
        "",
        f"已登记首个信号交易日 {forward['first_signal_session']}；固定执行规则为 `{primary}`。当前尚无未来预测或市场记录，ML模型二进制缺失：{', '.join(forward['missing_model_artifacts'])}。",
        "",
        "工具使用现有StudyWorkspace原子回执，拒绝次日开盘后补交/回填的预测，锁定模型文件哈希和既有训练输入/配方；价格包必须声明固定复权基准并绑定公司行为调整证据。5日标签成熟后才可记分；连续前瞻纸面账本不在每次读取末尾强行清仓。模型/数据源未过门禁时，不伪造未来结果或已有模型文件。",
        "",
        "前瞻本地首次见到时间不等于独立时间戳公证。先前2023–2026数据不会改名为独立留出集；本轮仍不进行训练、Colab、HPO、实盘或自动策略晋升。",
        "",
        "## 当前决策",
        "",
    ]
    for model, passed in report["primary_model_screens"].items():
        lines.append(
            f"- {model}：固定主策略历史筛查 {'PASS（仍受容量/前瞻门禁限制）' if passed else 'FAIL，未支持合理换手下持续优于两条简单动量基线'}。"
        )
    lines += [
        "- 保持预先指定的前瞻策略不变，不改选历史最优对照；实际容量和未来证据不完整时不声明E6全量验收。",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--contract", type=Path, required=True)
    p.add_argument("--run-root", type=Path, required=True)
    p.add_argument("--forward-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    if args.output.resolve().is_relative_to(Path(__file__).resolve().parents[2]):
        raise ValueError("full E6 report stays outside checkout")
    cfg = contract(args.contract)
    report = collect(args.run_root, cfg)
    forward = status(args.forward_root, datetime.now(timezone.utc))
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "comparison.json", report)
    write_json(args.output / "forward-status.json", forward)
    with (args.output / "研究报告.md").open("x", encoding="utf-8") as out:
        out.write(render(report, cfg, forward))
    print(
        json.dumps(
            {
                "completed": report["completed_policy_config_folds"],
                "primary": report["primary_model_screens"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
