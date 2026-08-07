#!/usr/bin/env python3
"""Run the frozen v4.30 Cboe SKEW source and state-0 information audit."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.data.adapters.cboe_volatility_indices import fetch_cboe_volatility_history
from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.v4_30_skew_state0_information import (
    build_skew_trace,
    build_state0_forward_paths,
    information_gate,
    summarize_state0_information,
)
from src.research.vxn_bridge_allocation_experiment import run_bridge_allocation_comparison

V4_2_KEY = "rotation_vxn_bridge_v4_2_50_50"


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


def _qqq_calendar(frame: pd.DataFrame, start: str, end: str | None) -> pd.DatetimeIndex:
    dates = pd.to_datetime(frame["date"], errors="coerce")
    if dates.dt.tz is not None:
        dates = dates.dt.tz_localize(None)
    dates = dates.dropna().dt.normalize()
    mask = dates >= pd.Timestamp(start)
    if end is not None:
        mask &= dates <= pd.Timestamp(end)
    return pd.DatetimeIndex(dates.loc[mask].unique()).sort_values()


def _source_audit(
    qqq_bars: pd.DataFrame,
    skew: pd.DataFrame,
    *,
    proxy_start: str,
    required_first_date: str,
    end_date: str | None,
    coverage_min: float,
) -> dict[str, Any]:
    first = skew.index.min()
    last = skew.index.max()
    source_start = max(pd.Timestamp(proxy_start), first)
    calendar = _qqq_calendar(qqq_bars, source_start.date().isoformat(), end_date)
    available = skew["close"].reindex(calendar).notna()
    missing = calendar[~available]
    if len(missing):
        locations = [calendar.get_loc(date) for date in missing]
        gap = 1
        max_gap = 1
        for previous, current in zip(locations, locations[1:]):
            if current == previous + 1:
                gap += 1
                max_gap = max(max_gap, gap)
            else:
                gap = 1
    else:
        max_gap = 0
    coverage = float(available.mean()) if len(available) else 0.0
    first_date_pass = first <= pd.Timestamp(required_first_date)
    coverage_pass = coverage >= coverage_min
    passed = bool(first_date_pass and coverage_pass)
    return {
        "provider": "Cboe Global Markets",
        "symbol": "SKEW",
        "first_observation": first.date().isoformat(),
        "last_observation": last.date().isoformat(),
        "required_first_date_on_or_before": required_first_date,
        "first_date_pass": first_date_pass,
        "calendar_start": source_start.date().isoformat(),
        "calendar_sessions": int(len(calendar)),
        "available_sessions": int(available.sum()),
        "missing_sessions": int((~available).sum()),
        "maximum_consecutive_missing_sessions": int(max_gap),
        "coverage": coverage,
        "coverage_min": coverage_min,
        "coverage_pass": coverage_pass,
        "passed": passed,
        "phase1_authorized": passed,
    }


def _source_failure(
    output: Path,
    contract: dict[str, Any],
    contract_path: Path,
    bridge_path: Path,
    error: Exception,
) -> int:
    audit = {
        "provider": "Cboe Global Markets",
        "symbol": "SKEW",
        "endpoint": contract["source"]["endpoint"],
        "passed": False,
        "phase1_authorized": False,
        "error_type": type(error).__name__,
        "error": str(error),
    }
    result = {
        "schema_version": "1.0",
        "experiment_id": contract["experiment_id"],
        "research_only": True,
        "portfolio_constructed": False,
        "source_audit": audit,
        "information_gate": None,
        "decision": "skew_official_numeric_source_unavailable",
        "contracts": {
            "experiment": {"path": str(contract_path), "sha256": _sha256(contract_path)},
            "baseline": {"path": str(bridge_path), "sha256": _sha256(bridge_path)},
        },
    }
    _write_json(output / "source_audit.json", audit)
    _write_json(output / "experiment_summary.json", result)
    (output / "research_report_zh.md").write_text(
        "# QQQ v4.30 SKEW Phase 0\n\n"
        "**Decision:** `skew_official_numeric_source_unavailable`\n\n"
        "官方 Cboe SKEW 数值历史端点未通过获取/解析，因此按预注册规则停止。"
        "未使用第三方历史、未进行 source splicing、未计算任何 forward outcomes、未构建 portfolio。\n\n"
        f"- error: `{type(error).__name__}: {error}`\n",
        encoding="utf-8",
    )
    return 0


def _decision(audit: dict[str, Any], gate: dict[str, Any] | None) -> str:
    if not audit["passed"]:
        return "skew_official_numeric_source_gate_failed"
    if gate is not None and gate["portfolio_experiment_authorized"]:
        return "skew_state0_information_gate_passed"
    return "skew_state0_information_not_stable"


def _report(
    audit: dict[str, Any],
    summary: pd.DataFrame | None,
    gate: dict[str, Any] | None,
    decision: str,
) -> str:
    lines = [
        "# QQQ v4.30 Cboe SKEW state-0 信息审计",
        "",
        f"**Decision:** `{decision}`",
        "",
        "## Phase 0 source gate",
        "",
        f"- Cboe SKEW history: {audit['first_observation']} → {audit['last_observation']}。",
        f"- trading-calendar coverage: {audit['coverage']:.2%}。",
        f"- missing sessions: {audit['missing_sessions']}；maximum consecutive gap: {audit['maximum_consecutive_missing_sessions']}。",
        f"- source gate: {'PASS' if audit['passed'] else 'FAIL'}。",
    ]
    if summary is not None and gate is not None:
        lines.extend([
            "",
            "## Phase 1 state-0 information test",
            "",
            "High SKEW is frozen as `SKEW >= rolling 252-session 80th percentile`. Signals are close-time; forward paths begin with the first return executable after the next open.",
            "",
            "| Segment | Group | Obs | Years | 20d median ret | 20d q10 ret | 20d median MaxDD | 60d median ret | 60d q10 ret | 60d median MaxDD |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for _, row in summary.iterrows():
            lines.append(
                "| " + " | ".join(
                    [
                        str(row["segment"]), str(row["group"]), str(int(row["observations"])),
                        str(int(row["years"])), f"{float(row['median_return_20d']) * 100:.2f}%",
                        f"{float(row['return_q10_20d']) * 100:.2f}%",
                        f"{float(row['median_max_drawdown_20d']) * 100:.2f}%",
                        f"{float(row['median_return_60d']) * 100:.2f}%",
                        f"{float(row['return_q10_60d']) * 100:.2f}%",
                        f"{float(row['median_max_drawdown_60d']) * 100:.2f}%",
                    ]
                ) + " |"
            )
        lines.extend(["", "## Information gate", ""])
        for name, passed in gate["checks"].items():
            lines.append(f"- {name}: {'PASS' if passed else 'FAIL'}")
        lines.extend([
            "",
            f"- high-SKEW state-0 observations: {gate['metrics']['high_skew_observations']}。",
            f"- calendar years: {gate['metrics']['high_skew_years']}。",
            f"- largest year share: {gate['metrics']['largest_high_skew_year_share']:.2%}。",
        ])
    lines.extend([
        "",
        "## Model status",
        "",
        "- No portfolio is constructed in v4.30.",
        "- v4.2 remains the formal baseline and alert source.",
        "- Only a passing information gate may authorize a separately frozen portfolio experiment.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("configs/research_paradigms/qqqi_qqq_tqqq_v4_30_skew_state0_information.yaml"),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--etf-data-bundle", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/qqqi_qqq_tqqq_v4_30_skew_state0_information"),
    )
    args = parser.parse_args()
    contract_path = args.contract
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    bridge_path = Path(contract["boundaries"]["baseline_contract"])
    bridge_contract = yaml.safe_load(bridge_path.read_text(encoding="utf-8"))
    end_date = args.end_date or bridge_contract["data"].get("end_date")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)

    symbols = ["QQQI", "QQQ", "TQQQ", "^VIX", "^VXN"]
    bars, coverage, identity = fetch_governed_etf_strategy_bars(
        symbols=symbols,
        start=bridge_contract["data"]["start_date"],
        end=end_date,
        bundle_dir=args.etf_data_bundle,
    )
    coverage.to_csv(output / "market_coverage.csv", index=False)

    try:
        skew = fetch_cboe_volatility_history("SKEW", end_date=end_date)
    except Exception as error:
        return _source_failure(output, contract, contract_path, bridge_path, error)

    audit = _source_audit(
        bars["QQQ"],
        skew,
        proxy_start=contract["boundaries"]["proxy_start_date"],
        required_first_date=contract["boundaries"]["required_source_first_date_on_or_before"],
        end_date=end_date,
        coverage_min=float(contract["boundaries"]["source_coverage_min"]),
    )
    _write_json(output / "source_audit.json", audit)
    if not audit["passed"]:
        decision = _decision(audit, None)
        result = {
            "schema_version": "1.0",
            "experiment_id": contract["experiment_id"],
            "research_only": True,
            "portfolio_constructed": False,
            "data_identity": identity,
            "source_audit": audit,
            "information_gate": None,
            "decision": decision,
        }
        _write_json(output / "experiment_summary.json", result)
        (output / "research_report_zh.md").write_text(
            _report(audit, None, None, decision), encoding="utf-8"
        )
        return 0

    proxy_bars = dict(bars)
    proxy_bars["QQQI"] = bars["QQQ"].copy()
    _, bridge_results, _, _ = run_bridge_allocation_comparison(proxy_bars, bridge_contract)
    baseline = bridge_results[V4_2_KEY]
    daily = baseline.daily.loc[
        baseline.daily.index >= pd.Timestamp(contract["boundaries"]["proxy_start_date"])
    ].copy()
    trace = build_skew_trace(daily, skew)
    paths = build_state0_forward_paths(daily, trace)
    summary = summarize_state0_information(paths)
    gate = information_gate(paths, summary)
    decision = _decision(audit, gate)

    paths.to_csv(output / "state0_forward_paths.csv", index=False)
    summary.to_csv(output / "state0_information_summary.csv", index=False)
    _write_json(output / "information_gate.json", gate)
    result = {
        "schema_version": "1.0",
        "experiment_id": contract["experiment_id"],
        "research_only": True,
        "portfolio_constructed": False,
        "data_identity": identity,
        "source_audit": audit,
        "information_gate": gate,
        "decision": decision,
        "v4_2_changed": False,
        "alert_source_changed": False,
        "contracts": {
            "experiment": {"path": str(contract_path), "sha256": _sha256(contract_path)},
            "baseline": {"path": str(bridge_path), "sha256": _sha256(bridge_path)},
        },
    }
    _write_json(output / "experiment_summary.json", result)
    (output / "research_report_zh.md").write_text(
        _report(audit, summary, gate, decision), encoding="utf-8"
    )
    manifest = {
        "schema_version": "1.0",
        "experiment_id": contract["experiment_id"],
        "outputs": {
            str(path.relative_to(output)): _sha256(path)
            for path in sorted(output.rglob("*"))
            if path.is_file()
        },
    }
    _write_json(output / "evidence_manifest.json", manifest)
    print(
        json.dumps(
            {
                "decision": decision,
                "portfolio_experiment_authorized": gate["portfolio_experiment_authorized"],
                "report": str(output / "research_report_zh.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
