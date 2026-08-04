#!/usr/bin/env python3
"""Run the frozen BYD V1.1 momentum-factor and XGBoost contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.run_byd_v1_0 import (
    _data_manifest,
    _fetch_governed_provider,
    _json_ready,
    _load_contract,
    _load_csv,
    _validate_provider_frame,
)
from src.data.adapters.base import FetchRequest
from src.data.adapters.yfinance_adapter import YFinanceAdapter
from src.research.byd_single_asset_v1 import normalise_ohlcv
from src.research.byd_xgb_v1_1 import evaluate_byd_v1_1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("configs/research_paradigms/byd_v1_1_xgb.yaml"),
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input-csv", type=Path)
    source.add_argument(
        "--fetch-provider",
        choices=("auto", "baostock", "akshare", "yfinance"),
    )
    parser.add_argument("--benchmark-csv", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def _load_benchmark_csv(path: Path) -> pd.DataFrame:
    return normalise_ohlcv(pd.read_csv(path))


def _fetch_csi300(contract: dict[str, Any]) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    start = str(contract["data"]["history_start"])
    cutoff = str(contract["data"]["cutoff"])
    symbol = str(contract["benchmark_context"]["provider_symbol"])
    try:
        result = YFinanceAdapter().fetch_daily_bars(
            FetchRequest(symbol=symbol, market="cn", start=start, end=cutoff)
        )
        benchmark = normalise_ohlcv(result.df)
        if benchmark.index[-1] != pd.Timestamp(cutoff):
            raise ValueError(
                f"CSI300 exact cutoff missing: latest={benchmark.index[-1].date()}"
            )
        return benchmark, {
            "status": "enabled",
            "provider": result.provider,
            "provider_symbol": result.provider_symbol,
            "rows": int(len(benchmark)),
            "first_date": benchmark.index[0].strftime("%Y-%m-%d"),
            "last_date": benchmark.index[-1].strftime("%Y-%m-%d"),
        }
    except Exception as exc:
        return None, {
            "status": "disabled",
            "reason": f"{type(exc).__name__}: {exc}",
            "policy": "disable_relative_features_and_record_reason",
        }


def _candidate_table(summary: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in summary["candidate_rows"]:
        validation = row["validation_metrics"]
        stress = row["validation_stress_40_metrics"]
        rows.append(
            {
                "mapping": row["mapping"],
                "validation_pass": row["validation_pass"],
                "validation_total_return": validation["total_return"],
                "validation_cagr": validation["cagr"],
                "validation_max_drawdown": validation["max_drawdown"],
                "validation_calmar": validation["calmar"],
                "validation_sortino": validation["sortino"],
                "validation_exposure": validation["exposure"],
                "validation_round_trips_per_year": validation[
                    "round_trips_per_year"
                ],
                "stress_40_total_return": stress["total_return"],
                "positive_quarter_share": row["positive_quarter_share"],
                **{f"gate_{key}": value for key, value in row["gates"].items()},
            }
        )
    return pd.DataFrame(rows)


def _write_report(
    output_dir: Path,
    summary: dict[str, Any],
    candidate_table: pd.DataFrame,
    factor_table: pd.DataFrame,
    data_manifest: dict[str, Any],
    benchmark_manifest: dict[str, Any],
) -> None:
    selected = summary["selected_mapping"] or "none"
    baselines = summary["baselines"]
    buy_hold = baselines["buy_hold_validation"]
    v1 = baselines["v1_rule_validation"]
    factor = baselines["best_single_factor_validation"]
    constant75 = baselines["constant75_validation"]
    quality = summary["prediction_quality"]
    latest = summary["latest_snapshot"]
    factor_top = factor_table.sort_values(
        "development_spearman", key=lambda values: values.abs(), ascending=False
    ).head(12)
    lines = [
        "# BYD V1.1 momentum-factor and XGBoost research",
        "",
        "> Research only. `trade_ready=false`. BYD V1.0 is treated as a rule baseline, not an XGBoost model.",
        "",
        "## Decision",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Selected mapping: `{selected}`",
        f"- Market-relative features enabled: `{summary['market_relative_features_enabled']}`",
        f"- Latest prediction date: `{pd.Timestamp(latest['date']).date()}`",
        f"- Latest predicted 10-session return: `{latest['prediction']:.4f}`",
        f"- Latest targets: `{summary['latest_mapping_targets']}`",
        "",
        "## Data identity",
        "",
        f"- BYD provider: `{data_manifest['provider']}`",
        f"- BYD rows: `{data_manifest['rows']}`",
        f"- BYD range: `{data_manifest['first_date']}` to `{data_manifest['last_date']}`",
        f"- BYD SHA-256: `{data_manifest['sha256']}`",
        f"- CSI300 context: `{benchmark_manifest}`",
        "",
        "## Fixed validation baselines: 2023–2024",
        "",
        "| Baseline | Total return | CAGR | Max drawdown | Calmar |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| BYD buy-and-hold | {buy_hold['total_return']:.4f} | {buy_hold['cagr']:.4f} | {buy_hold['max_drawdown']:.4f} | {buy_hold['calmar']:.4f} |",
        f"| BYD V1.0 rule | {v1['total_return']:.4f} | {v1['cagr']:.4f} | {v1['max_drawdown']:.4f} | {v1['calmar']:.4f} |",
        f"| Best development-only factor | {factor['total_return']:.4f} | {factor['cagr']:.4f} | {factor['max_drawdown']:.4f} | {factor['calmar']:.4f} |",
        f"| Constant 75% BYD | {constant75['total_return']:.4f} | {constant75['cagr']:.4f} | {constant75['max_drawdown']:.4f} | {constant75['calmar']:.4f} |",
        "",
        "## XGBoost mappings",
        "",
        candidate_table.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Prediction quality",
        "",
        f"- OOS samples: `{quality['samples']}`",
        f"- OOS Spearman: `{quality['spearman']:.4f}`",
        f"- OOS Pearson: `{quality['pearson']:.4f}`",
        f"- Direction hit rate: `{quality['direction_hit_rate']:.4f}`",
        f"- Years above 50% hit rate: `{quality['years_above_50pct']}`",
        f"- Annual hit rates: `{quality['annual_hit_rates']}`",
        f"- Maximum mean feature gain share: `{summary['maximum_mean_feature_importance_share']:.4f}`",
        "",
        "## Development-only momentum factor ranking",
        "",
        factor_top[
            [
                "factor",
                "orientation",
                "development_spearman",
                "validation_spearman",
                "validation_direction_hit_rate",
                "validation_quintile_monotonicity",
                "validation_top_bottom_spread",
                "holdout_spearman",
            ]
        ].to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Retrospective holdout",
        "",
    ]
    holdout = summary["retrospective_holdout"]
    if holdout is None:
        lines.append(
            "No XGBoost position mapping passed the fixed 2023–2024 validation gates."
        )
    else:
        candidate = holdout["candidate_metrics"]
        v1_holdout = holdout["v1_metrics"]
        lines.extend(
            [
                f"- Classification: `{holdout['classification']}`",
                f"- Pass: `{holdout['pass']}`",
                f"- Candidate total return: `{candidate['total_return']:.4f}`",
                f"- V1 rule total return: `{v1_holdout['total_return']:.4f}`",
                f"- Candidate CAGR: `{candidate['cagr']:.4f}`",
                f"- V1 rule CAGR: `{v1_holdout['cagr']:.4f}`",
                f"- Candidate max drawdown: `{candidate['max_drawdown']:.4f}`",
                f"- 40 bps total return: `{holdout['candidate_stress_40_metrics']['total_return']:.4f}`",
                "",
                "### Holdout gates",
                "",
            ]
        )
        for gate, passed in holdout["gates"].items():
            lines.append(f"- {'PASS' if passed else 'FAIL'} `{gate}`")
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "A supported result would establish only a historical BYD V1.1 research baseline. A failed result must remain failed: the feature family, thresholds, split, and XGBoost parameters cannot be changed after reading validation or holdout evidence.",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = _parse_args()
    contract = _load_contract(args.contract)
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.input_csv is not None:
            raw, source = _load_csv(args.input_csv)
            daily = _validate_provider_frame(raw, contract)
        else:
            daily, source = _fetch_governed_provider(contract, args.fetch_provider)
        if args.benchmark_csv is not None:
            benchmark = _load_benchmark_csv(args.benchmark_csv)
            benchmark_manifest = {
                "status": "enabled",
                "provider": "local_csv",
                "path": str(args.benchmark_csv),
                "rows": int(len(benchmark)),
                "first_date": benchmark.index[0].strftime("%Y-%m-%d"),
                "last_date": benchmark.index[-1].strftime("%Y-%m-%d"),
            }
        else:
            benchmark, benchmark_manifest = _fetch_csi300(contract)
    except Exception as exc:
        blocked = {
            "experiment_id": contract.get("experiment_id"),
            "decision": "data_blocked",
            "research_only": True,
            "trade_ready": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        (output_dir / "data_blocked.json").write_text(
            json.dumps(blocked, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        raise

    summary = evaluate_byd_v1_1(daily, contract, benchmark)
    data_manifest = _data_manifest(daily, source)
    dataset = summary.pop("dataset")
    candidate_results = summary.pop("candidate_results")
    summary.pop("candidate_stress_results")
    summary.pop("baseline_results")
    factor_correlation = summary.pop("factor_correlation")
    predictions = summary.pop("walk_forward_predictions")
    fit_manifest = summary.pop("fit_manifest")
    feature_importance = summary.pop("feature_importance")
    aggregate_importance = summary.pop("aggregate_feature_importance")

    daily.to_csv(output_dir / "byd_ohlcv.csv", index=True, date_format="%Y-%m-%d")
    dataset.to_csv(
        output_dir / "momentum_dataset.csv", index=True, date_format="%Y-%m-%d"
    )
    factor_table = pd.DataFrame(summary["factor_diagnostics"])
    factor_table.to_csv(output_dir / "factor_diagnostics.csv", index=False)
    factor_correlation.to_csv(output_dir / "factor_correlation.csv")
    predictions.to_csv(output_dir / "predictions.csv", index=True, date_format="%Y-%m-%d")
    fit_manifest.to_csv(output_dir / "fit_manifest.csv", index=False)
    feature_importance.to_csv(output_dir / "feature_importance.csv", index=False)
    aggregate_importance.to_csv(
        output_dir / "aggregate_feature_importance.csv", index=False
    )
    candidate_table = _candidate_table(summary)
    candidate_table.to_csv(output_dir / "candidate_summary.csv", index=False)

    selected = summary["selected_mapping"]
    if selected is not None:
        result = candidate_results[selected]
        result.daily.to_csv(
            output_dir / "selected_daily.csv",
            index=True,
            date_format="%Y-%m-%d",
        )
        result.trades.to_csv(output_dir / "selected_trades.csv", index=False)

    summary["data_manifest"] = data_manifest
    summary["benchmark_manifest"] = benchmark_manifest
    (output_dir / "summary.json").write_text(
        json.dumps(
            _json_ready(summary),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    _write_report(
        output_dir,
        summary,
        candidate_table,
        factor_table,
        data_manifest,
        benchmark_manifest,
    )
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "selected_mapping": selected,
                "provider": data_manifest["provider"],
                "market_relative_features_enabled": summary[
                    "market_relative_features_enabled"
                ],
                "latest_prediction": summary["latest_snapshot"]["prediction"],
                "output_dir": str(output_dir),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
