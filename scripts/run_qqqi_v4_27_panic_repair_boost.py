#!/usr/bin/env python3
"""Run the frozen QQQ v4.27 Panic Repair Boost research comparison."""

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
from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.v4_2_panic_repair_boost import run_panic_repair_comparison

BASELINE = "current_v4_2"
CANDIDATE = "v4_27_panic_repair_boost"


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


def _boost_episodes(candidate: Any, baseline: Any) -> pd.DataFrame:
    active = candidate.daily["panic_repair_active_at_open"].astype(bool)
    starts = active & ~active.shift(1, fill_value=False)
    rows: list[dict[str, Any]] = []
    index = candidate.daily.index

    for event_number, start in enumerate(index[starts], start=1):
        start_location = int(index.get_loc(start))
        end_location = start_location
        while end_location + 1 < len(index) and bool(active.iloc[end_location + 1]):
            end_location += 1
        end = index[end_location]
        candidate_window = candidate.daily.iloc[start_location : end_location + 1]
        baseline_window = baseline.daily.loc[candidate_window.index]
        candidate_log = float(np.log1p(candidate_window["net_return"]).sum())
        baseline_log = float(np.log1p(baseline_window["net_return"]).sum())
        rows.append(
            {
                "boost_episode": event_number,
                "start_date": start,
                "end_date": end,
                "sessions": int(end_location - start_location + 1),
                "candidate_return": float(np.exp(candidate_log) - 1.0),
                "v4_2_return": float(np.exp(baseline_log) - 1.0),
                "relative_return": float(np.exp(candidate_log - baseline_log) - 1.0),
            }
        )
    return pd.DataFrame(rows)


def _scope_run(
    *,
    bars: Mapping[str, pd.DataFrame],
    fear_greed: pd.DataFrame,
    bridge_contract: Mapping[str, Any],
    output: Path,
    scope: str,
) -> dict[str, Any]:
    headline, results = run_panic_repair_comparison(
        bars,
        bridge_contract,
        fear_greed,
    )
    output.mkdir(parents=True, exist_ok=True)
    headline.to_csv(output / "headline_metrics.csv")

    for key, result in results.items():
        result.daily.to_csv(output / f"daily_{key}.csv")
        result.trades.to_csv(output / f"trades_{key}.csv", index=False)

    episodes = _boost_episodes(results[CANDIDATE], results[BASELINE])
    episodes.to_csv(output / "boost_episodes.csv", index=False)
    candidate_daily = results[CANDIDATE].daily

    summary = {
        "scope": scope,
        "scope_role": (
            "actual_product_evidence"
            if scope == "actual"
            else "reliable_2021_plus_proxy_mechanism"
        ),
        "sample": {
            "start": candidate_daily.index.min().date().isoformat(),
            "end": candidate_daily.index.max().date().isoformat(),
            "observations": int(len(candidate_daily)),
        },
        "headline_metrics": headline.reset_index(names="strategy").to_dict(
            orient="records"
        ),
        "panic_cluster_count": int(candidate_daily["panic_start_at_close"].sum()),
        "boost_sessions": int(candidate_daily["panic_repair_active_at_open"].sum()),
        "boost_episodes": episodes.to_dict(orient="records"),
    }
    _write_json(output / "scope_summary.json", summary)
    return summary


def _strategy_map(scope: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row["strategy"]): dict(row)
        for row in scope["headline_metrics"]
    }


def _pct(value: Any) -> str:
    return f"{float(value) * 100:.2f}%"


def _report(actual: Mapping[str, Any], proxy: Mapping[str, Any]) -> str:
    actual_metrics = _strategy_map(actual)
    proxy_metrics = _strategy_map(proxy)
    lines = [
        "# QQQ v4.27 Panic Repair Boost formal replay",
        "",
        "**Status:** research-only; v4.2 baseline and alerts unchanged.",
        "",
        "## Actual QQQI product window",
        "",
        "| Strategy | CAGR | Max DD | Sharpe | Sortino | Calmar |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for key in (BASELINE, CANDIDATE):
        row = actual_metrics[key]
        lines.append(
            f"| {key} | {_pct(row['cagr'])} | {_pct(row['max_drawdown'])} | "
            f"{float(row['sharpe']):.3f} | {float(row['sortino']):.3f} | "
            f"{float(row['calmar']):.3f} |"
        )
    lines.extend(
        [
            "",
            f"- Panic clusters: {actual['panic_cluster_count']}.",
            f"- Boost sessions: {actual['boost_sessions']}.",
            "",
            "## Reliable 2021+ QQQ proxy",
            "",
            "| Strategy | CAGR | Max DD | Sharpe | Sortino | Calmar |",
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for key in (BASELINE, CANDIDATE):
        row = proxy_metrics[key]
        lines.append(
            f"| {key} | {_pct(row['cagr'])} | {_pct(row['max_drawdown'])} | "
            f"{float(row['sharpe']):.3f} | {float(row['sortino']):.3f} | "
            f"{float(row['calmar']):.3f} |"
        )
    lines.extend(
        [
            "",
            f"- Panic clusters: {proxy['panic_cluster_count']}.",
            f"- Boost sessions: {proxy['boost_sessions']}.",
            "",
            "No promotion decision is authorized by this replay. The next admissible "
            "step is prospective shadow observation of the frozen rule.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/"
            "qqqi_qqq_tqqq_v4_27_panic_repair_boost_research.yaml"
        ),
    )
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--etf-data-bundle", type=Path, default=None)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(
            "artifacts/evidence/"
            "qqqi_qqq_tqqq_v4_27_panic_repair_boost_research"
        ),
    )
    args = parser.parse_args()

    contract = yaml.safe_load(args.contract.read_text(encoding="utf-8"))
    baseline_path = Path(contract["boundaries"]["baseline_contract"])
    baseline_contract = yaml.safe_load(baseline_path.read_text(encoding="utf-8"))
    end_date = args.end_date or contract["data"].get("end_date")

    bars, coverage, identity = fetch_governed_etf_strategy_bars(
        symbols=contract["data"]["required_symbols"],
        start=contract["data"]["start_date"],
        end=end_date,
        bundle_dir=args.etf_data_bundle,
    )
    fear_greed = fetch_cnn_fear_greed(end_date=end_date)

    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    coverage.to_csv(output / "coverage.csv", index=False)
    fear_greed.to_csv(output / "fear_greed.csv")

    actual = _scope_run(
        bars=bars,
        fear_greed=fear_greed,
        bridge_contract=baseline_contract,
        output=output / "actual",
        scope="actual",
    )
    proxy_bars = dict(bars)
    proxy_bars["QQQI"] = bars["QQQ"].copy()
    proxy = _scope_run(
        bars=proxy_bars,
        fear_greed=fear_greed,
        bridge_contract=baseline_contract,
        output=output / "qqq_proxy",
        scope="qqq_proxy",
    )

    summary = {
        "schema_version": "1.0",
        "experiment_id": contract["experiment_id"],
        "research_only": True,
        "trade_ready": False,
        "data_identity": identity,
        "contract": {
            "path": str(args.contract),
            "sha256": _sha256(args.contract),
        },
        "baseline_contract": {
            "path": str(baseline_path),
            "sha256": _sha256(baseline_path),
        },
        "actual": actual,
        "qqq_proxy": proxy,
        "direct_promotion_authorized": False,
        "prospective_shadow_authorized": False,
        "v4_2_changed": False,
        "alerts_changed": False,
    }
    _write_json(output / "experiment_summary.json", summary)
    (output / "backtest_report.md").write_text(
        _report(actual, proxy),
        encoding="utf-8",
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
                "experiment_id": contract["experiment_id"],
                "report": str(output / "backtest_report.md"),
                "direct_promotion_authorized": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
