#!/usr/bin/env python3
"""Run the frozen v4.33 MA200-entry / MA20+VIX-release experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from src.data.adapters.cnn_fear_greed import fetch_cnn_fear_greed
from src.research.etf_rotation_experiment import StrategyResult, _return_metrics
from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.v4_2_baseline_diagnostics import tail_risk_metrics
from src.research.v4_33_ma200_ma20_vix_release import (
    BASELINE,
    GUARD,
    JOINT,
    PANIC,
    cash_next_open_return,
    run_v4_33_comparison,
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


def _cash_coverage(
    result: StrategyResult,
    bars: Mapping[str, pd.DataFrame],
    symbol: str,
) -> dict[str, Any]:
    returns = cash_next_open_return(bars, symbol, result.daily.index)
    usable = returns.iloc[:-1] if len(returns) > 1 else returns
    return {
        "symbol": symbol,
        "sessions": int(len(usable)),
        "available_sessions": int(usable.notna().sum()),
        "coverage": float(usable.notna().mean()) if len(usable) else 0.0,
    }


def _chronological(result: StrategyResult, fraction: float) -> list[dict[str, Any]]:
    daily = result.daily
    split = max(1, min(len(daily) - 1, int(len(daily) * fraction)))
    rows: list[dict[str, Any]] = []
    for segment, sample in (("early", daily.iloc[:split]), ("late", daily.iloc[split:])):
        metrics = _return_metrics(sample["net_return"], annual_risk_free_rate=0.0)
        rows.append({"strategy": result.metrics["strategy"], "segment": segment, **metrics})
    return rows


def _changed_episodes(candidate: StrategyResult, baseline: StrategyResult) -> pd.DataFrame:
    index = candidate.daily.index.intersection(baseline.daily.index)
    relative_daily = (
        np.log1p(candidate.daily.loc[index, "net_return"].astype(float))
        - np.log1p(baseline.daily.loc[index, "net_return"].astype(float))
    )
    changed = relative_daily.abs().gt(1e-12)
    starts = changed & ~changed.shift(1, fill_value=False)
    rows: list[dict[str, Any]] = []
    for event_number, start in enumerate(index[starts], start=1):
        start_location = int(index.get_loc(start))
        end_location = start_location
        while end_location + 1 < len(index) and bool(changed.iloc[end_location + 1]):
            end_location += 1
        dates = index[start_location : end_location + 1]
        candidate_log = float(np.log1p(candidate.daily.loc[dates, "net_return"]).sum())
        baseline_log = float(np.log1p(baseline.daily.loc[dates, "net_return"]).sum())
        rows.append(
            {
                "event_id": f"event_{event_number:03d}",
                "start_date": start,
                "end_date": dates[-1],
                "sessions": int(len(dates)),
                "candidate_return": float(np.exp(candidate_log) - 1.0),
                "baseline_return": float(np.exp(baseline_log) - 1.0),
                "relative_return": float(np.exp(candidate_log - baseline_log) - 1.0),
            }
        )
    return pd.DataFrame(rows)


def _largest_positive_share(episodes: pd.DataFrame) -> float:
    if episodes.empty:
        return 1.0
    positive = episodes["relative_return"].astype(float).clip(lower=0.0)
    total = float(positive.sum())
    return float(positive.max() / total) if total > 0.0 else 1.0


def _scope_run(
    bars: Mapping[str, pd.DataFrame],
    bridge_contract: Mapping[str, Any],
    fear_greed: pd.DataFrame,
    *,
    scope: str,
    cash_symbol: str,
    chronological_fraction: float,
    output: Path,
) -> dict[str, Any]:
    headline, results, diagnostics = run_v4_33_comparison(
        bars,
        bridge_contract,
        fear_greed,
        cash_symbol=cash_symbol,
    )
    output.mkdir(parents=True, exist_ok=True)
    headline.to_csv(output / "headline_metrics.csv")
    baseline = results[BASELINE]
    chronological_rows: list[dict[str, Any]] = []
    tails: dict[str, Any] = {}
    concentration: dict[str, float] = {}
    for key, result in results.items():
        result.daily.to_csv(output / f"daily_{key}.csv")
        result.trades.to_csv(output / f"trades_{key}.csv", index=False)
        chronological_rows.extend(_chronological(result, chronological_fraction))
        tails[key] = tail_risk_metrics(result)
        if key != BASELINE:
            episodes = _changed_episodes(result, baseline)
            episodes.to_csv(output / f"episodes_{key}.csv", index=False)
            concentration[key] = _largest_positive_share(episodes)
    chronological = pd.DataFrame(chronological_rows)
    chronological.to_csv(output / "chronological_metrics.csv", index=False)
    _write_json(output / "tail_risk.json", tails)
    summary = {
        "scope": scope,
        "cash_symbol": cash_symbol,
        "headline_metrics": headline.reset_index().to_dict(orient="records"),
        "chronological_metrics": chronological.to_dict(orient="records"),
        "tail_risk": tails,
        "diagnostics": diagnostics,
        "episode_concentration": concentration,
        "cash_coverage": _cash_coverage(baseline, bars, cash_symbol),
    }
    _write_json(output / "scope_summary.json", summary)
    return summary


def _strategy_map(scope: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row["strategy"]): dict(row) for row in scope["headline_metrics"]}


def _gate(
    actual: Mapping[str, Any],
    proxy: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    thresholds = contract["validation"]["retrospective_v4_3_candidate_gate"]
    am = _strategy_map(actual)
    pm = _strategy_map(proxy)
    ab, aj = am[BASELINE], am[JOINT]
    pb, pj = pm[BASELINE], pm[JOINT]

    actual_cagr_delta = (float(aj["cagr"]) - float(ab["cagr"])) * 100.0
    actual_dd_improvement = (
        float(aj["max_drawdown"]) - float(ab["max_drawdown"])
    ) * 100.0
    actual_calmar_delta = float(aj["calmar"]) - float(ab["calmar"])
    proxy_cagr_delta = (float(pj["cagr"]) - float(pb["cagr"])) * 100.0
    proxy_dd_improvement = (
        float(pj["max_drawdown"]) - float(pb["max_drawdown"])
    ) * 100.0
    proxy_calmar_delta = float(pj["calmar"]) - float(pb["calmar"])

    chronological_pass = True
    chronological_detail: dict[str, bool] = {}
    for scope_name, scope in (("actual", actual), ("proxy", proxy)):
        table = pd.DataFrame(scope["chronological_metrics"]).set_index(["strategy", "segment"])
        for segment in ("early", "late"):
            passed = float(table.loc[(JOINT, segment), "calmar"]) >= float(
                table.loc[(BASELINE, segment), "calmar"]
            )
            chronological_detail[f"{scope_name}_{segment}"] = bool(passed)
            chronological_pass &= bool(passed)

    proxy_guard_years = int(pj.get("guard_years", 0))
    largest_guard_year_share = float(pj.get("largest_guard_year_share", 1.0))
    actual_turnover_ratio = float(aj["turnover_units"]) / float(ab["turnover_units"])
    proxy_turnover_ratio = float(pj["turnover_units"]) / float(pb["turnover_units"])
    turnover_limit = 1.0 + float(thresholds["turnover_increase_max"])
    largest_episode_share = max(
        float(actual["episode_concentration"].get(JOINT, 1.0)),
        float(proxy["episode_concentration"].get(JOINT, 1.0)),
    )

    checks = {
        "actual_cagr": actual_cagr_delta >= float(thresholds["actual_cagr_delta_pp_min"]),
        "actual_max_drawdown": actual_dd_improvement
        >= float(thresholds["actual_max_drawdown_improvement_pp_min"]),
        "actual_calmar": actual_calmar_delta >= float(thresholds["actual_calmar_delta_min"]),
        "proxy_cagr": proxy_cagr_delta >= float(thresholds["proxy_cagr_delta_pp_min"]),
        "proxy_max_drawdown": proxy_dd_improvement
        >= float(thresholds["proxy_max_drawdown_improvement_pp_min"]),
        "proxy_calmar": proxy_calmar_delta >= float(thresholds["proxy_calmar_delta_min"]),
        "chronological_calmar": bool(chronological_pass),
        "proxy_guard_years": proxy_guard_years >= int(thresholds["proxy_guard_years_min"]),
        "actual_turnover": actual_turnover_ratio <= turnover_limit,
        "proxy_turnover": proxy_turnover_ratio <= turnover_limit,
    }
    return {
        "checks": checks,
        "metrics": {
            "actual_cagr_delta_pp": actual_cagr_delta,
            "actual_max_drawdown_improvement_pp": actual_dd_improvement,
            "actual_calmar_delta": actual_calmar_delta,
            "proxy_cagr_delta_pp": proxy_cagr_delta,
            "proxy_max_drawdown_improvement_pp": proxy_dd_improvement,
            "proxy_calmar_delta": proxy_calmar_delta,
            "chronological_detail": chronological_detail,
            "proxy_guard_years": proxy_guard_years,
            "largest_guard_year_share": largest_guard_year_share,
            "actual_turnover_ratio": actual_turnover_ratio,
            "proxy_turnover_ratio": proxy_turnover_ratio,
            "largest_positive_episode_share": largest_episode_share,
        },
        "retrospective_v4_3_candidate_supported": bool(all(checks.values())),
        "prospective_shadow_required": True,
        "formal_v4_3_promotion_authorized": False,
    }


def _decision(gate: Mapping[str, Any], actual: Mapping[str, Any], proxy: Mapping[str, Any]) -> str:
    if gate["retrospective_v4_3_candidate_supported"]:
        return "v4_33_retrospective_v4_3_candidate_supported"
    am, pm = _strategy_map(actual), _strategy_map(proxy)
    actual_dd = float(am[JOINT]["max_drawdown"]) - float(am[BASELINE]["max_drawdown"])
    proxy_dd = float(pm[JOINT]["max_drawdown"]) - float(pm[BASELINE]["max_drawdown"])
    if actual_dd > 0.0 and proxy_dd > 0.0:
        return "v4_33_final_release_promising_gate_failed"
    return "v4_33_final_release_not_supported"


def _report(
    actual: Mapping[str, Any],
    proxy: Mapping[str, Any],
    gate: Mapping[str, Any],
    decision: str,
) -> str:
    names = {
        BASELINE: "v4.2",
        PANIC: "v4.27 Panic Repair",
        GUARD: "v4.2 + MA200 defense / MA20+VIX release",
        JOINT: "v4.27 + MA200 defense / MA20+VIX release",
    }
    lines = [
        "# QQQ v4.33 MA200 慢熊防守 + MA20/VIX 最简释放", "",
        f"**Decision:** `{decision}`", "",
        "This is the final deterministic release variant for the MA200 state-0 defense line.",
    ]
    for title, scope in (("实际 QQQI / SGOV 产品窗口", actual), ("QQQ / BIL 长机制窗口", proxy)):
        lines.extend([
            "", f"## {title}", "",
            "| 模型 | CAGR | Max DD | Sharpe | Sortino | Calmar | Turnover | Guard sessions | Price+vol releases |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for row in scope["headline_metrics"]:
            guard_sessions = row.get("guard_sessions", 0)
            release_sessions = row.get("price_vol_release_sessions", 0)
            if pd.isna(guard_sessions):
                guard_sessions = 0
            if pd.isna(release_sessions):
                release_sessions = 0
            lines.append(
                "| " + " | ".join(
                    [
                        names[str(row["strategy"])],
                        f"{float(row['cagr']) * 100:.2f}%",
                        f"{float(row['max_drawdown']) * 100:.2f}%",
                        f"{float(row['sharpe']):.3f}",
                        f"{float(row['sortino']):.3f}",
                        f"{float(row['calmar']):.3f}",
                        f"{float(row['turnover_units']):.1f}",
                        str(int(guard_sessions)),
                        str(int(release_sessions)),
                    ]
                ) + " |"
            )
        lines.append(f"- {scope['cash_symbol']} coverage: {scope['cash_coverage']['coverage']:.2%}.")
        lines.append(
            f"- joint largest positive changed-episode share: {scope['episode_concentration'].get(JOINT, 1.0):.2%}."
        )
    lines.extend(["", "## Retrospective v4.3 candidate gate", ""])
    for name, passed in gate["checks"].items():
        lines.append(f"- {name}: {'PASS' if passed else 'FAIL'}")
    metrics = gate["metrics"]
    lines.extend([
        "",
        f"- actual CAGR delta: {metrics['actual_cagr_delta_pp']:+.2f} pp",
        f"- actual Max DD improvement: {metrics['actual_max_drawdown_improvement_pp']:+.2f} pp",
        f"- proxy CAGR delta: {metrics['proxy_cagr_delta_pp']:+.2f} pp",
        f"- proxy Max DD improvement: {metrics['proxy_max_drawdown_improvement_pp']:+.2f} pp",
        f"- largest positive changed-episode share: {metrics['largest_positive_episode_share']:.2%}",
        f"- largest proxy guard-year share: {metrics['largest_guard_year_share']:.2%}",
        "",
        "## Promotion / stop boundary", "",
        "- If the retrospective gate passes, this becomes only a v4.3 retrospective candidate and must enter prospective shadow validation.",
        "- v4.2 remains the formal baseline and alert source until a separate explicit promotion decision after non-design prospective evidence.",
        "- If the gate fails, the deterministic MA200 state-0 defense/release line is closed; no v4.34 release retuning is authorized.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/qqqi_qqq_tqqq_v4_33_ma200_ma20_vix_release.yaml"
        ),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--etf-data-bundle", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/qqqi_qqq_tqqq_v4_33_ma200_ma20_vix_release"),
    )
    args = parser.parse_args()
    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    bridge_path = Path(contract["boundaries"]["baseline_contract"])
    bridge_contract = yaml.safe_load(bridge_path.read_text(encoding="utf-8"))
    end_date = args.end_date or bridge_contract["data"].get("end_date")
    symbols = ["QQQI", "QQQ", "TQQQ", "SGOV", "BIL", "^VIX", "^VXN"]
    bars, coverage, identity = fetch_governed_etf_strategy_bars(
        symbols=symbols,
        start=bridge_contract["data"]["start_date"],
        end=end_date,
        bundle_dir=args.etf_data_bundle,
    )
    fear_greed = fetch_cnn_fear_greed(end_date=end_date)

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "market_coverage.csv", index=False)
    actual = _scope_run(
        bars,
        bridge_contract,
        fear_greed,
        scope="actual",
        cash_symbol="SGOV",
        chronological_fraction=float(contract["validation"]["chronological_train_fraction"]),
        output=output / "actual",
    )
    proxy_bars = dict(bars)
    proxy_bars["QQQI"] = bars["QQQ"].copy()
    proxy = _scope_run(
        proxy_bars,
        bridge_contract,
        fear_greed,
        scope="proxy",
        cash_symbol="BIL",
        chronological_fraction=float(contract["validation"]["chronological_train_fraction"]),
        output=output / "proxy",
    )
    minimum_coverage = float(contract["validation"]["minimum_cash_coverage"])
    if actual["cash_coverage"]["coverage"] < minimum_coverage:
        raise RuntimeError("actual SGOV cash coverage failed")
    if proxy["cash_coverage"]["coverage"] < minimum_coverage:
        raise RuntimeError("proxy BIL cash coverage failed")

    gate = _gate(actual, proxy, contract)
    decision = _decision(gate, actual, proxy)
    summary = {
        "schema_version": "1.0",
        "experiment_id": contract["experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "post_result_hypothesis": True,
        "data_identity": identity,
        "actual": actual,
        "proxy": proxy,
        "gate": gate,
        "decision": decision,
        "v4_2_changed": False,
        "alert_source_changed": False,
        "formal_v4_3_promotion_authorized": False,
        "prospective_shadow_required": True,
        "contracts": {
            "experiment": {"path": str(args.contract), "sha256": _sha256(args.contract)},
            "baseline": {"path": str(bridge_path), "sha256": _sha256(bridge_path)},
        },
    }
    _write_json(output / "experiment_summary.json", summary)
    (output / "backtest_report_zh.md").write_text(
        _report(actual, proxy, gate, decision), encoding="utf-8"
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
                "retrospective_v4_3_candidate_supported": gate[
                    "retrospective_v4_3_candidate_supported"
                ],
                "formal_v4_3_promotion_authorized": False,
                "report": str(output / "backtest_report_zh.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
