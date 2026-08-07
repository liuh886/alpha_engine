#!/usr/bin/env python3
"""Run the frozen v4.28 volatility-term-structure experiment."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from src.data.adapters.cboe_volatility_indices import fetch_cboe_volatility_history
from src.data.adapters.cnn_fear_greed import fetch_cnn_fear_greed
from src.research.etf_rotation_experiment import StrategyResult
from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.v4_2_baseline_diagnostics import tail_risk_metrics
from src.research.v4_28_volatility_term_structure import (
    BASELINE,
    GUARD,
    JOINT,
    PANIC,
    TIMING,
    _run_weights,
    run_term_structure_comparison,
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


def _normalise_calendar(frame: pd.DataFrame) -> pd.DatetimeIndex:
    if "date" not in frame.columns:
        raise ValueError("QQQ bars missing date")
    dates = pd.to_datetime(frame["date"], errors="coerce")
    if dates.dt.tz is not None:
        dates = dates.dt.tz_localize(None)
    return pd.DatetimeIndex(dates.dropna().dt.normalize().sort_values().unique())


def _source_audit(
    qqq_bars: pd.DataFrame,
    vix9d: pd.DataFrame,
    vix3m: pd.DataFrame,
    *,
    start: str,
    minimum_coverage: float,
) -> dict[str, Any]:
    calendar = _normalise_calendar(qqq_bars)
    calendar = calendar[calendar >= pd.Timestamp(start)]
    if calendar.empty:
        raise ValueError("source-audit calendar is empty")
    rows: dict[str, Any] = {}
    for symbol, frame in (("VIX9D", vix9d), ("VIX3M", vix3m)):
        available = frame["close"].reindex(calendar).notna()
        coverage = float(available.mean())
        rows[symbol] = {
            "calendar_sessions": int(len(calendar)),
            "available_sessions": int(available.sum()),
            "missing_sessions": int((~available).sum()),
            "coverage": coverage,
            "first_observation": frame.index.min().date().isoformat(),
            "last_observation": frame.index.max().date().isoformat(),
            "passed": coverage >= minimum_coverage,
        }
    passed = all(bool(row["passed"]) for row in rows.values())
    audit = {
        "start": start,
        "minimum_coverage": minimum_coverage,
        "indices": rows,
        "passed": passed,
        "outcome_calculation_authorized": passed,
    }
    if not passed:
        raise RuntimeError(f"term-structure Phase 0 source audit failed: {audit}")
    return audit


def _weights(result: StrategyResult) -> pd.DataFrame:
    return result.daily[["weight_QQQI", "weight_QQQ", "weight_TQQQ"]].rename(
        columns={
            "weight_QQQI": "QQQI",
            "weight_QQQ": "QQQ",
            "weight_TQQQ": "TQQQ",
        }
    )


def _rebase_result(result: StrategyResult, start: str) -> StrategyResult:
    daily = result.daily.loc[result.daily.index >= pd.Timestamp(start)].copy()
    if daily.empty:
        raise ValueError(f"{result.name} is empty after rebasing to {start}")
    source = StrategyResult(result.name, daily, pd.DataFrame(), dict(result.metrics))
    return _run_weights(source, _weights(source), name=str(result.metrics["strategy"]))


def _chronological(result: StrategyResult, fraction: float) -> list[dict[str, Any]]:
    daily = result.daily
    split = max(1, min(len(daily) - 1, int(len(daily) * fraction)))
    rows: list[dict[str, Any]] = []
    for segment, sample in (("early", daily.iloc[:split]), ("late", daily.iloc[split:])):
        from src.research.etf_rotation_experiment import _return_metrics

        metrics = _return_metrics(sample["net_return"], annual_risk_free_rate=0.0)
        rows.append({"strategy": result.metrics["strategy"], "segment": segment, **metrics})
    return rows


def _overlay_episodes(candidate: StrategyResult, baseline: StrategyResult) -> pd.DataFrame:
    assets = ["QQQI", "QQQ", "TQQQ"]
    changed = pd.Series(False, index=candidate.daily.index)
    for asset in assets:
        changed |= ~np.isclose(
            candidate.daily[f"weight_{asset}"].astype(float),
            baseline.daily[f"weight_{asset}"].reindex(candidate.daily.index).astype(float),
        )
    starts = changed & ~changed.shift(1, fill_value=False)
    rows: list[dict[str, Any]] = []
    index = candidate.daily.index
    for event_number, start in enumerate(index[starts], start=1):
        start_location = int(index.get_loc(start))
        end_location = start_location
        while end_location + 1 < len(index) and bool(changed.iloc[end_location + 1]):
            end_location += 1
        end = index[end_location]
        candidate_slice = candidate.daily["net_return"].iloc[start_location : end_location + 1]
        baseline_slice = baseline.daily["net_return"].reindex(index).iloc[
            start_location : end_location + 1
        ]
        candidate_log = float(np.log1p(candidate_slice).sum())
        baseline_log = float(np.log1p(baseline_slice).sum())
        rows.append(
            {
                "event_id": f"event_{event_number:03d}",
                "start_date": start,
                "end_date": end,
                "sessions": int(end_location - start_location + 1),
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
    vix9d: pd.DataFrame,
    vix3m: pd.DataFrame,
    *,
    scope: str,
    start: str | None,
    chronological_fraction: float,
    output: Path,
) -> dict[str, Any]:
    headline, results, diagnostics = run_term_structure_comparison(
        bars, bridge_contract, fear_greed, vix9d, vix3m
    )
    if start is not None:
        results = {key: _rebase_result(result, start) for key, result in results.items()}
        headline = pd.DataFrame([dict(result.metrics) for result in results.values()]).set_index(
            "strategy"
        )

    output.mkdir(parents=True, exist_ok=True)
    headline.to_csv(output / "headline_metrics.csv")
    chronological_rows: list[dict[str, Any]] = []
    tails: dict[str, Any] = {}
    episodes: dict[str, pd.DataFrame] = {}
    baseline = results[BASELINE]
    for key, result in results.items():
        result.daily.to_csv(output / f"daily_{key}.csv")
        result.trades.to_csv(output / f"trades_{key}.csv", index=False)
        chronological_rows.extend(_chronological(result, chronological_fraction))
        tails[key] = tail_risk_metrics(result)
        if key != BASELINE:
            episode_table = _overlay_episodes(result, baseline)
            episode_table.to_csv(output / f"episodes_{key}.csv", index=False)
            episodes[key] = episode_table
    chronological = pd.DataFrame(chronological_rows)
    chronological.to_csv(output / "chronological_metrics.csv", index=False)
    _write_json(output / "tail_risk.json", tails)

    summary = {
        "scope": scope,
        "scope_role": (
            "actual_qqqi_product_evidence" if scope == "actual" else "qqq_proxy_mechanism_only"
        ),
        "rebased_start": start,
        "headline_metrics": headline.reset_index().to_dict(orient="records"),
        "chronological_metrics": chronological.to_dict(orient="records"),
        "tail_risk": tails,
        "diagnostics": diagnostics,
        "episode_concentration": {
            key: _largest_positive_share(table) for key, table in episodes.items()
        },
    }
    _write_json(output / "scope_summary.json", summary)
    return summary


def _strategy_map(scope: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row["strategy"]): dict(row) for row in scope["headline_metrics"]}


def _gate(actual: Mapping[str, Any], proxy: Mapping[str, Any], contract: Mapping[str, Any]) -> dict[str, Any]:
    thresholds = contract["validation"]["v4_3_candidate_gate"]
    actual_map = _strategy_map(actual)
    proxy_map = _strategy_map(proxy)
    actual_base = actual_map[BASELINE]
    actual_joint = actual_map[JOINT]
    proxy_base = proxy_map[BASELINE]
    proxy_joint = proxy_map[JOINT]

    actual_cagr_delta_pp = (float(actual_joint["cagr"]) - float(actual_base["cagr"])) * 100.0
    actual_dd_delta_pp = (
        float(actual_joint["max_drawdown"]) - float(actual_base["max_drawdown"])
    ) * 100.0
    actual_calmar_delta = float(actual_joint["calmar"]) - float(actual_base["calmar"])
    proxy_cagr_delta_pp = (float(proxy_joint["cagr"]) - float(proxy_base["cagr"])) * 100.0
    proxy_dd_delta_pp = (
        float(proxy_joint["max_drawdown"]) - float(proxy_base["max_drawdown"])
    ) * 100.0

    actual_chrono = pd.DataFrame(actual["chronological_metrics"]).set_index(["strategy", "segment"])
    proxy_chrono = pd.DataFrame(proxy["chronological_metrics"]).set_index(["strategy", "segment"])
    chrono_not_worse = all(
        float(table.loc[(JOINT, segment), "calmar"])
        >= float(table.loc[(BASELINE, segment), "calmar"])
        for table in (actual_chrono, proxy_chrono)
        for segment in ("early", "late")
    )
    largest_share = max(
        float(actual["episode_concentration"].get(JOINT, 1.0)),
        float(proxy["episode_concentration"].get(JOINT, 1.0)),
    )
    checks = {
        "actual_cagr": actual_cagr_delta_pp >= float(thresholds["actual_cagr_delta_pp_min"]),
        "actual_max_drawdown": actual_dd_delta_pp
        >= -float(thresholds["actual_max_drawdown_worsening_pp_max"]),
        "actual_calmar": actual_calmar_delta >= float(thresholds["actual_calmar_delta_min"]),
        "proxy_cagr": proxy_cagr_delta_pp >= float(thresholds["proxy_cagr_delta_pp_min"]),
        "proxy_max_drawdown": proxy_dd_delta_pp
        >= -float(thresholds["proxy_max_drawdown_worsening_pp_max"]),
        "chronological_calmar": bool(chrono_not_worse),
        "event_concentration": largest_share
        <= float(thresholds["largest_positive_episode_share_max"]),
    }
    return {
        "checks": checks,
        "metrics": {
            "actual_cagr_delta_pp": actual_cagr_delta_pp,
            "actual_max_drawdown_delta_pp": actual_dd_delta_pp,
            "actual_calmar_delta": actual_calmar_delta,
            "proxy_cagr_delta_pp": proxy_cagr_delta_pp,
            "proxy_max_drawdown_delta_pp": proxy_dd_delta_pp,
            "largest_positive_episode_share": largest_share,
        },
        "v4_3_candidate_supported": bool(all(checks.values())),
        "direct_promotion_authorized": False,
    }


def _decision(gate: Mapping[str, Any], actual: Mapping[str, Any]) -> str:
    if gate["v4_3_candidate_supported"]:
        return "v4_28_term_structure_v4_3_candidate_supported"
    metrics = _strategy_map(actual)
    if float(metrics[GUARD]["max_drawdown"]) > float(metrics[BASELINE]["max_drawdown"]):
        return "drawdown_guard_promising_joint_gate_failed"
    if float(metrics[TIMING]["calmar"]) > float(metrics[PANIC]["calmar"]):
        return "timing_factor_promising_joint_gate_failed"
    return "v4_28_term_structure_not_supported"


def _pct(value: Any) -> str:
    return f"{float(value) * 100:.2f}%"


def _num(value: Any) -> str:
    return f"{float(value):.3f}"


def _report(
    source_audit: Mapping[str, Any],
    actual: Mapping[str, Any],
    proxy: Mapping[str, Any],
    gate: Mapping[str, Any],
    decision: str,
) -> str:
    names = {
        BASELINE: "v4.2",
        PANIC: "v4.27 Panic Repair",
        TIMING: "v4.27 + VIX9D timing",
        GUARD: "v4.2 + backwardation guard",
        JOINT: "joint term-structure candidate",
    }
    lines = [
        "# QQQ v4.28 波动率期限结构研究", "",
        f"**Decision:** `{decision}`", "",
        "## Phase 0 数据门", "",
        f"- Cboe VIX9D/VIX3M 2014+ source audit: **{'PASS' if source_audit['passed'] else 'FAIL'}**。",
    ]
    for symbol, row in source_audit["indices"].items():
        lines.append(
            f"- {symbol}: coverage {row['coverage']:.2%}, {row['first_observation']} → {row['last_observation']}。"
        )
    for title, scope in (("实际 QQQI 产品窗口", actual), ("2014+ QQQ proxy 机制窗口", proxy)):
        lines.extend(["", f"## {title}", "", "| 模型 | CAGR | Max DD | Sharpe | Sortino | Calmar | Turnover |", "|---|---:|---:|---:|---:|---:|---:|"])
        for row in scope["headline_metrics"]:
            lines.append(
                "| " + " | ".join(
                    [
                        names[str(row["strategy"])],
                        _pct(row["cagr"]),
                        _pct(row["max_drawdown"]),
                        _num(row["sharpe"]),
                        _num(row["sortino"]),
                        _num(row["calmar"]),
                        f"{float(row['turnover_units']):.1f}",
                    ]
                ) + " |"
            )
    lines.extend(["", "## v4.3 candidate gate", ""])
    for name, passed in gate["checks"].items():
        lines.append(f"- {name}: {'PASS' if passed else 'FAIL'}")
    lines.extend(
        [
            "",
            "## Model status",
            "",
            "- v4.2 remains the formal baseline and alert source.",
            "- Passing this retrospective gate would create only a v4.3 candidate, never direct promotion.",
            "- No threshold, allocation, smoothing or delay search is permitted after these results.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/qqqi_qqq_tqqq_v4_28_term_structure_research.yaml"
        ),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--etf-data-bundle", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("artifacts/evidence/qqqi_qqq_tqqq_v4_28_term_structure_research"),
    )
    args = parser.parse_args()
    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    bridge_path = Path(contract["boundaries"]["baseline_contract"])
    bridge_contract = yaml.safe_load(bridge_path.read_text(encoding="utf-8"))
    end_date = args.end_date or bridge_contract["data"].get("end_date")
    required_symbols = ["QQQI", "QQQ", "TQQQ", "^VIX", "^VXN"]
    bars, coverage, identity = fetch_governed_etf_strategy_bars(
        symbols=required_symbols,
        start=bridge_contract["data"]["start_date"],
        end=end_date,
        bundle_dir=args.etf_data_bundle,
    )
    fear_greed = fetch_cnn_fear_greed(end_date=end_date)
    vix9d = fetch_cboe_volatility_history("VIX9D", end_date=end_date)
    vix3m = fetch_cboe_volatility_history("VIX3M", end_date=end_date)

    source_audit = _source_audit(
        bars["QQQ"],
        vix9d,
        vix3m,
        start=contract["sources"]["primary_term_structure_start"],
        minimum_coverage=float(contract["validation"]["minimum_term_structure_coverage"]),
    )

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "market_coverage.csv", index=False)
    _write_json(output / "source_audit.json", source_audit)
    actual = _scope_run(
        bars,
        bridge_contract,
        fear_greed,
        vix9d,
        vix3m,
        scope="actual",
        start=None,
        chronological_fraction=float(contract["validation"]["chronological_train_fraction"]),
        output=output / "actual",
    )
    proxy_bars = dict(bars)
    proxy_bars["QQQI"] = bars["QQQ"].copy()
    proxy = _scope_run(
        proxy_bars,
        bridge_contract,
        fear_greed,
        vix9d,
        vix3m,
        scope="proxy",
        start=contract["evidence_scopes"]["proxy"]["start_date"],
        chronological_fraction=float(contract["validation"]["chronological_train_fraction"]),
        output=output / "proxy",
    )
    gate = _gate(actual, proxy, contract)
    decision = _decision(gate, actual)
    summary = {
        "schema_version": "1.0",
        "experiment_id": contract["experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "data_identity": identity,
        "source_audit": source_audit,
        "actual": actual,
        "proxy": proxy,
        "gate": gate,
        "decision": decision,
        "v4_2_changed": False,
        "alert_source_changed": False,
        "direct_promotion_authorized": False,
        "contracts": {
            "experiment": {"path": str(args.contract), "sha256": _sha256(args.contract)},
            "baseline": {"path": str(bridge_path), "sha256": _sha256(bridge_path)},
        },
    }
    _write_json(output / "experiment_summary.json", summary)
    (output / "backtest_report_zh.md").write_text(
        _report(source_audit, actual, proxy, gate, decision), encoding="utf-8"
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
                "v4_3_candidate_supported": gate["v4_3_candidate_supported"],
                "report": str(output / "backtest_report_zh.md"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
