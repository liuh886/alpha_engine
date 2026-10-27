"""Research Review Formatter.

Renders human-friendly GitHub Flavored Markdown and terminal table summaries
from study inspection receipts without requiring researchers to read raw JSON.
"""

from __future__ import annotations

from typing import Any


def format_study_review(inspected: dict[str, Any]) -> str:
    """Format an inspected study dictionary into a clear, readable Markdown review report."""
    study_id = inspected.get("study_id", "unknown")
    status = inspected.get("status", "unknown").upper()
    hypothesis = inspected.get("hypothesis", study_id)
    study_hash = inspected.get("study_hash", "n/a")
    source_commit = inspected.get("source_commit", "n/a")
    pit_certified = inspected.get("pit_certified", False)

    status_badge = "🟢 READY" if status == "READY" else "🔴 BLOCKED"

    lines = [
        f"# Research Study Review: {hypothesis}",
        "",
        f"- **Study ID**: `{study_id}`",
        f"- **Status**: {status_badge}",
        f"- **Study Receipt Hash**: `{study_hash}`",
        f"- **Source Commit SHA**: `{source_commit}`",
        f"- **PIT Certified**: {'Yes' if pit_certified else 'False (Observation cutoff verified only)'}",
        "",
    ]

    # Blocked status reporting
    if status == "BLOCKED":
        blocked_reasons = inspected.get("blocked_reasons", [])
        lines.extend([
            "## ⚠️ Study Blocked Reasons",
            "",
        ])
        if blocked_reasons:
            for r in blocked_reasons:
                lines.append(f"- `{r}`")
        else:
            lines.append("- `unknown_block_reason`")
        lines.append("")

    # Study Specific Performance / Outcomes Presentation
    if study_id in {"us_tech_vol_reversal_v1", "cross_sectional_xgb_v1"} or "oos_net_return" in inspected:
        lines.extend([
            "## Executive Performance Summary (Out-of-Sample)",
            "",
            "| Performance Indicator | Value | Interpretation |",
            "| :--- | :--- | :--- |",
        ])

        def _fmt_pct(val: Any) -> str:
            if val is None:
                return "n/a"
            v = float(val) * 100.0
            return f"+{v:.2f}%" if v > 0 else f"{v:.2f}%"

        def _fmt_num(val: Any) -> str:
            if val is None:
                return "n/a"
            return f"{float(val):.4f}"

        lines.append(f"| OOS Net Cumulative Return | {_fmt_pct(inspected.get('oos_net_return'))} | Realized net return after full turnover frictions |")
        bench_ret = inspected.get("benchmark_return") or inspected.get("qqq_or_benchmark_return")
        lines.append(f"| Benchmark Cumulative Return | {_fmt_pct(bench_ret)} | Reference benchmark baseline over identical window |")
        lines.append(f"| OOS Net Excess Return | {_fmt_pct(inspected.get('oos_net_excess_return'))} | Alpha over benchmark baseline |")
        lines.append(f"| Annualized Sharpe Ratio | {_fmt_num(inspected.get('oos_sharpe'))} | Risk-adjusted excess return per unit of volatility |")
        lines.append(f"| Maximum Drawdown | {_fmt_pct(inspected.get('oos_max_drawdown'))} | Peak-to-trough maximum portfolio decline from 1.0 |")

        if inspected.get("rank_ic") is not None:
            lines.append(f"| Mean Daily Rank IC | {_fmt_num(inspected.get('rank_ic'))} | Cross-sectional Spearman correlation (signal to return) |")
        if inspected.get("ic_ir") is not None:
            lines.append(f"| IC Information Ratio (IC-IR) | {_fmt_num(inspected.get('ic_ir'))} | Stability of Rank IC over time |")

        lines.append("")

        # Fold detail if present
        if "folds" in inspected and isinstance(inspected["folds"], list):
            lines.extend([
                "### Expanding Folds Breakdown",
                "",
                "| Fold ID | Status | Selected Parameters | OOS Net Return | Sessions Count |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ])
            for f in inspected["folds"]:
                fid = f.get("fold_id", "n/a")
                f_status = f.get("status", "n/a")
                f_params = str(f.get("selected_parameters", {}))
                f_ret = _fmt_pct(f.get("oos_net_return"))
                f_sess = f.get("oos_sessions_count", "n/a")
                lines.append(f"| {fid} | {f_status} | {f_params} | {f_ret} | {f_sess} |")
            lines.append("")

        # Feature importance if present
        if inspected.get("feature_importance"):
            lines.extend([
                "### Feature Importance (XGBoost Gain Attribution)",
                "",
                "| Feature | Gain Weight |",
                "| :--- | :--- |",
            ])
            for feat, weight in sorted(inspected["feature_importance"].items(), key=lambda x: x[1], reverse=True):
                lines.append(f"| `{feat}` | {float(weight):.2%} |")
            lines.append("")

    elif study_id == "factor_exploration_v1":
        lines.extend([
            "## Factor Monotonicity & Predictive Power (Rank IC)",
            "",
            f"- **Evaluated Trading Sessions**: {inspected.get('evaluated_sessions_count', 'n/a')}",
            f"- **Primary Mean Rank IC**: {inspected.get('mean_rank_ic', 'n/a')}",
            f"- **Primary IC-IR**: {inspected.get('ic_ir', 'n/a')}",
            "",
        ])
        summaries = inspected.get("factor_summaries")
        if summaries and isinstance(summaries, dict):
            lines.extend([
                "| Factor Name | Mean Rank IC | Std Rank IC | IC-IR | Positive Rate | Sample Count |",
                "| :--- | :--- | :--- | :--- | :--- | :--- |",
            ])
            for f_name, f_data in sorted(summaries.items()):
                m_ic = f_data.get("mean_rank_ic", "n/a")
                s_ic = f_data.get("std_rank_ic", "n/a")
                ir = f_data.get("ic_ir", "n/a")
                pos = f_data.get("positive_ic_rate", 0)
                cnt = f_data.get("observations_count", 0)
                lines.append(f"| `{f_name}` | {m_ic} | {s_ic} | {ir} | {float(pos):.1%} | {cnt} |")
            lines.append("")

        latest = inspected.get("latest_rankings")
        if latest and isinstance(latest, dict):
            lines.extend([
                "### Latest Cross-Sectional Ranking Snapshot",
                "",
                "| Rank | Symbol | Details |",
                "| :--- | :--- | :--- |",
            ])
            for sym, item in sorted(latest.items(), key=lambda x: x[1].get("rank", 999)):
                r = item.get("rank")
                details = ", ".join(f"{k}={v}" for k, v in item.items() if k != "rank")
                lines.append(f"| {r} | `{sym}` | {details} |")
            lines.append("")

    elif study_id == "ashare_rdi_v1":
        lines.extend([
            "## Risk Decision Event & Forward Realized Horizons",
            "",
            f"- **Decision Session**: `{inspected.get('decision_session', 'n/a')}`",
            "",
        ])
        outcomes = inspected.get("outcomes")
        if outcomes and isinstance(outcomes, dict):
            lines.extend([
                "| Forward Horizon | Realized Cumulative Return | Worst Intra-Horizon Return | Entry Session | Exit Session |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ])
            for h in inspected.get("horizons", []):
                h_str = str(h)
                if h_str in outcomes:
                    o = outcomes[h_str]
                    ret = f"{float(o.get('forward_return', 0)) * 100:.2f}%"
                    worst = f"{float(o.get('worst_intrahorizon_return', 0)) * 100:.2f}%"
                    entry = o.get("entry_session", "n/a")
                    exit_s = o.get("exit_session", "n/a")
                    lines.append(f"| {h} Sessions | {ret} | {worst} | {entry} | {exit_s} |")
            lines.append("")

    # PIT Limitations & Disclaimers
    limitations = inspected.get("pit_limitations", [])
    if limitations:
        lines.extend([
            "## Methodology & Governance Limitations",
            "",
        ])
        for lim in limitations:
            lines.append(f"- `{lim}`")
        lines.append("")

    lines.extend([
        "> [!IMPORTANT]",
        "> Research receipts are descriptive empirical artifacts (`research_only=true`, `trade_ready=false`).",
        "> They are NOT trading signals, live recommendations, or proof of prospective alpha.",
    ])

    return "\n".join(lines)
