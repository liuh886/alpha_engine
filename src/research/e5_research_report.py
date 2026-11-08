"""Summarize only a complete, hash-bound E5 shortlist ledger matrix."""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

from src.research.e5_score_reconstruction import SHORTLIST, sha, write_json

FOLDS = tuple(f"f{year}h{half}" for year in range(2023, 2027) for half in (1, 2))


def collect(root: Path) -> dict:
    rows = {}
    evaluator = None
    source = None
    for cfg in SHORTLIST:
        for fold in FOLDS:
            folder = root / cfg / fold
            row = json.loads((folder / "result.json").read_bytes())
            if set(row["files"]) != {"original-daily.parquet", "original-assets.parquet",
                                      "delayed-daily.parquet", "delayed-assets.parquet"}:
                raise ValueError("incomplete ledger inventory")
            if any(sha(folder / name) != digest for name, digest in row["files"].items()):
                raise ValueError("ledger hash differs from result receipt")
            if (row["configuration_id"] != cfg or row["fold_id"] != fold or
                    row["parity"]["status"] != "E4_DAILY_AND_AGGREGATE_PARITY_PASS" or
                    row["research_only"] is not True or row["trade_ready"] is not False):
                raise ValueError("matrix contains an unverified E5 result")
            identity = row["evaluator_code_sha256"]
            if evaluator is not None and evaluator != identity:
                raise ValueError("matrix mixes evaluator revisions")
            if source is not None and source != row["source_snapshot_sha256"]:
                raise ValueError("matrix mixes source snapshots")
            evaluator, source = identity, row["source_snapshot_sha256"]
            rows[(cfg, fold)] = row
    paired = []
    for mode in ("original", "delayed"):
        for cfg in SHORTLIST:
            for baseline in ("rule_momentum60", "rule_momentum120"):
                differences = []
                for fold in FOLDS:
                    a, b = rows[(cfg, fold)][mode], rows[(baseline, fold)][mode]
                    if a["sessions"] != b["sessions"] or abs(a["qqq_return"]-b["qqq_return"]) > 1e-12:
                        raise ValueError("paired folds are not aligned")
                    differences.append(100*(a["net_return"]-b["net_return"]))
                paired.append({"mode": mode, "configuration_id": cfg, "baseline": baseline,
                    "fold_deltas_pp": differences, "median_delta_pp": statistics.median(differences),
                    "wins": sum(d > 0 for d in differences)})
    return {"schema_version": "e5_shortlist_report_v1", "verified_config_folds": len(rows),
            "source_snapshot_sha256": source, "evaluator_code_sha256": evaluator,
            "rows": [rows[(cfg, fold)] for cfg in SHORTLIST for fold in FOLDS], "paired": paired,
            "result_sha256": {f"{cfg}/{fold}": sha(root / cfg / fold / "result.json")
                              for cfg, fold in rows},
            "research_only": True, "trade_ready": False, "pit_certified": False,
            "independent_holdout_certified": False}


def render(report: dict) -> str:
    lines = ["# E5 四策略执行与风险复核", "",
        "32 个配置×时间折全部通过 E4 原始逐日与汇总数值对照。新模式是使用已验证复权收盘价的延迟敏感性研究；没有实际成交证明。", "",
        "## 逐折对照", "",
        "收益与超额为期间累计百分比/百分点，未年化；成本损失为无成本净值与扣费净值的终值差。", "",
        "|策略|折|原净收益%|原超QQQ pp|原回撤%|原换手|成本损失pp|延迟净收益%|延迟超QQQ pp|延迟回撤%|延迟换手|5d IC|",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in report["rows"]:
        a,b = row["original"],row["delayed"]
        ic = row["signal_ic"]["rank_ic_5d"]["mean"]
        lines.append(f"|{row['configuration_id']}|{row['fold_id']}|{100*a['net_return']:.2f}|{100*a['net_excess']:.2f}|{100*a['max_drawdown']:.2f}|{a['turnover']:.2f}|{100*a['cost_loss_cumulative']:.2f}|{100*b['net_return']:.2f}|{100*b['net_excess']:.2f}|{100*b['max_drawdown']:.2f}|{b['turnover']:.2f}|{ic:.4f}|")
    lines += ["", "## 同折配对优势", "", "与60日和120日动量分别比较；不相减独立中位数，不据此宣布选模显著性。", "",
              "|模式|策略|基线|8折配对中位数pp|正折数|", "|---|---|---|---:|---:|"]
    for pair in report["paired"]:
        if pair["configuration_id"] != pair["baseline"]:
            lines.append(f"|{pair['mode']}|{pair['configuration_id']}|{pair['baseline']}|{pair['median_delta_pp']:.2f}|{pair['wins']}/8|")
    lines += ["", "## 决策解释", "",
        "延迟后的模型增量没有保持：p03 对60日/120日动量的8折配对中位数均转负，LightGBM亦然。不能仅凭2026H1仍高收益就认为模型有稳定可执行优势。延迟后的超QQQ累计收益中位数与同折基线优势是不同问题。", "",
        "2026H1→H2 的已观察盈亏变化可以由下述实际模拟个股贡献定位；它支持集中暴露和排名失效的风险诊断，不足以证明宏观状态变化的因果机制。5日IC的方向变化为独立于Top5收益计量的辅助诊断，仍受到同一历史选样与选模偏差。", ""]
    lines += ["", "## XGB p03 的 2026 年归因", "",
        "贡献是实际模拟持仓×逐日收益减分摊成本，再乘当日净值后跨日相加；单位为折初净值的百分点。成本按原引擎换手惯例分摊，不把信号名单当持仓。", ""]
    for row in report["rows"]:
        if row["configuration_id"] != "xgb_p03" or row["fold_id"] not in ("f2026h1","f2026h2"):
            continue
        a = row["original"]
        # JSON canonicalization sorts object keys; rank explicitly by contribution.
        items = sorted(a["asset_pnl_nav_units"].items(), key=lambda kv: (-kv[1], kv[0]))
        lines += [f"### {row['fold_id']}", "",
            f"净收益 {100*a['net_return']:.2f}%；正贡献最大的五股占全部正贡献 {100*a['top5_positive_pnl_share']:.2f}%；最大漂移权重 {100*a['max_drifted_weight']:.2f}%。",
            "", "|股票|净值贡献pp|", "|---|---:|"]
        for symbol, value in items[:5] + items[-5:]:
            lines.append(f"|{symbol}|{100*value:.2f}|")
    lines += ["", "## 换手与贡献集中度", "",
        "每折净值重新从1开始；以下换手是8折之和，非一条连续自融资账户。新增持仓数排除建仓首日。", "",
        "|策略|原换手合计|延迟换手合计|平均每日新增名字|正贡献Top5占比范围|", "|---|---:|---:|---:|---:|"]
    for cfg in SHORTLIST:
        selected = [r for r in report["rows"] if r["configuration_id"] == cfg]
        shares = [r["original"]["top5_positive_pnl_share"] for r in selected]
        observations = sum(r['original']['sessions']-1 for r in selected)
        new_names = sum(r['original']['mean_new_names_per_day']*(r['original']['sessions']-1) for r in selected)
        lines.append(f"|{cfg}|{sum(r['original']['turnover'] for r in selected):.2f}|{sum(r['delayed']['turnover'] for r in selected):.2f}|{new_names/observations:.2f}|{100*min(shares):.1f}–{100*max(shares):.1f}%|")
    lines += ["", "所有策略同用Top5/每日调仓/8bps；树模型每日换入更多名字，解释其换手高于长期动量。共同的权重漂移也贡献换手；此处没有更改调仓约束或事后优化排序。", "",
              "## 并列评分与信号记录的局限", "",
              "|策略|第5/6名并列的决策日|已发布信号名单与实际模拟持仓不同的日期|", "|---|---:|---:|"]
    for cfg in SHORTLIST:
        selected = [r["score_diagnostics"] for r in report["rows"] if r["configuration_id"] == cfg]
        total = sum(r["decision_dates"] for r in selected)
        lines.append(f"|{cfg}|{sum(r['top5_cutoff_tied_decisions'] for r in selected)}/{total}|{sum(r['published_signal_set_differs_from_engine_holdings_dates'] for r in selected)}/{total}|")
    lines += ["", "原信号记录用稳定降序，原引擎用NumPy默认升序取末5名，遇到边界并列可产生不同股票集合。这里严格保留原引擎规则，不根据盈亏重新选择并列处理。原始信号名单集中度因此不能替代实际持仓/贡献集中度；评分并列也构成模型稳健性限制。", ""]
    lines += ["", "## 可靠证据与限制", "",
        "- 可靠：原始回执哈希、全部32折逐日复现、引擎持仓漂移与交易观察、贡献加总、同一完整评分的延迟敏感性、严格成熟的5日IC。完整评分与Parquet账本均独立保存。",
        "- 评分来自冻结配方重建；原始模型二进制未归档。接受依据是每日收益/换手复现，不冒称模型二进制一致。",
        "- 原模式使用收盘后信息按同一收盘价成交，属于理想化研究。延迟模式使用后一个交易日的已验证复权收盘价代理；不是经过验证的真实订单、成交、下一开盘价或容量。",
        "- E4 的半L1中途换手、全额建仓/清仓与收益扣费口径保持不变；没有手续费筹资和整数股约束。数量按单位调仓前总净值归一化。",
        "- 个股贡献解释已观察模拟盈亏，不证明因果预测机制；正贡献占比不以可能接近0或为负的组合净收益作分母。",
        "- 五日IC仅使用信号和标签成熟日期均位于该验证折的样本，排除每折末5个未成熟日期；与原E4包含锚点的1日IC口径不同。",
        "- US73 是后见静态幸存者子集；历史供应商调整版本非PIT，2023–2026已用于选择。不能据此宣称独立OOS或策略晋升。未启动其他744项任务、HPO、成本重复拟合或实盘。", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--results-root", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args(argv)
    report = collect(args.results_root)
    if args.output.resolve().is_relative_to(Path(__file__).resolve().parents[2]):
        raise ValueError("private complete research report must be outside checkout")
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / "report.json", report)
    with (args.output / "研究报告.md").open("x", encoding="utf-8") as f:
        f.write(render(report))
    print("E5_REPORT_WRITTEN", report["verified_config_folds"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
