#!/usr/bin/env python3
"""Run the frozen BYD V1.0 single-asset research contract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from src.research.byd_single_asset_v1 import (
    build_candidate_positions,
    build_features,
    evaluate_research,
    normalise_ohlcv,
    run_backtest,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path("configs/research_paradigms/byd_v1_0.yaml"),
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input-csv", type=Path)
    source.add_argument("--fetch-akshare", action="store_true")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def _load_contract(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        contract = yaml.safe_load(handle)
    if not isinstance(contract, dict):
        raise ValueError("contract must be a YAML mapping")
    return contract


def _fetch_akshare(contract: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    import akshare as ak

    instrument = contract["instrument"]
    source = contract["data"]["primary_source"]
    start = str(contract["data"]["history_start"]).replace("-", "")
    cutoff = str(contract["data"]["cutoff"]).replace("-", "")
    symbol = str(instrument["provider_symbol"])
    adjust = str(source["adjustment"])
    frame = ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start,
        end_date=cutoff,
        adjust=adjust,
    )
    metadata = {
        "provider": "akshare",
        "provider_endpoint": "stock_zh_a_hist",
        "provider_symbol": symbol,
        "period": "daily",
        "start_date": start,
        "end_date": cutoff,
        "adjustment": adjust,
    }
    return frame, metadata


def _load_csv(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = pd.read_csv(path)
    return frame, {"provider": "local_csv", "path": str(path)}


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _data_manifest(daily: pd.DataFrame, source: dict[str, Any]) -> dict[str, Any]:
    payload = daily.to_csv(index=True, date_format="%Y-%m-%d").encode("utf-8")
    return {
        **source,
        "rows": int(len(daily)),
        "first_date": daily.index[0].strftime("%Y-%m-%d"),
        "last_date": daily.index[-1].strftime("%Y-%m-%d"),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "columns": list(daily.columns),
    }


def _candidate_table(summary: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for row in summary["candidate_rows"]:
        selection = row["selection_metrics"]
        validation = row["validation_metrics"]
        rows.append(
            {
                "candidate": row["candidate"],
                "selection_pass": row["selection_pass"],
                "selection_cagr": selection["cagr"],
                "selection_max_drawdown": selection["max_drawdown"],
                "selection_calmar": selection["calmar"],
                "selection_sortino": selection["sortino"],
                "round_trips_per_year": selection["round_trips_per_year"],
                "validation_cagr": validation["cagr"],
                "validation_max_drawdown": validation["max_drawdown"],
                "validation_calmar": validation["calmar"],
                "positive_year_fraction": row["positive_year_fraction"],
                "largest_positive_year_share": row["largest_positive_year_share"],
                "selection_stress_40_total_return": row["selection_stress_40_total_return"],
                "selection_total_return_ex_best_trade": row[
                    "selection_total_return_ex_best_trade"
                ],
            }
        )
    return pd.DataFrame(rows)


def _write_report(
    output_dir: Path,
    summary: dict[str, Any],
    candidate_table: pd.DataFrame,
    manifest: dict[str, Any],
) -> None:
    selected = summary["selected_candidate"] or "none"
    quarantine = summary["quarantine"]
    lines = [
        "# BYD V1.0 baseline research",
        "",
        "> Research only. `trade_ready=false`. Signals are close-decided and executed at the next open.",
        "",
        "## Decision",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Selected candidate: `{selected}`",
        f"- Latest governed data: `{summary['latest_data_date']}`",
        f"- Current open position: `{summary['selected_current_open_position']}`",
        f"- Latest close signal for next open: `{summary['selected_latest_close_signal_for_next_open']}`",
        "",
        "## Data identity",
        "",
        f"- Provider: `{manifest['provider']}`",
        f"- Rows: `{manifest['rows']}`",
        f"- Range: `{manifest['first_date']}` to `{manifest['last_date']}`",
        f"- SHA-256: `{manifest['sha256']}`",
        "",
        "## Candidate comparison",
        "",
        candidate_table.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Quarantine",
        "",
    ]
    if quarantine is None:
        lines.append("No candidate passed the selection gates, so the quarantine window was not used for promotion.")
    else:
        lines.extend(
            [
                f"- Pass: `{quarantine['pass']}`",
                f"- Candidate total return: `{quarantine['candidate_metrics']['total_return']:.4f}`",
                f"- Buy-and-hold total return: `{quarantine['buy_hold_metrics']['total_return']:.4f}`",
                f"- Candidate max drawdown: `{quarantine['candidate_metrics']['max_drawdown']:.4f}`",
                f"- Buy-and-hold max drawdown: `{quarantine['buy_hold_metrics']['max_drawdown']:.4f}`",
                f"- 40 bps total return: `{quarantine['stress_40_total_return']:.4f}`",
                f"- Return excluding best trade: `{quarantine['total_return_ex_best_trade']:.4f}`",
                "",
                "### Gates",
                "",
            ]
        )
        for gate, passed in quarantine["gates"].items():
            lines.append(f"- {'PASS' if passed else 'FAIL'} `{gate}`")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "A supported result establishes only the frozen BYD V1.0 research baseline. It does not establish live-trading readiness, and the 2025+ quarantine evidence may not be used to retune the rule.",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = _parse_args()
    contract = _load_contract(args.contract)
    raw, source = _fetch_akshare(contract) if args.fetch_akshare else _load_csv(args.input_csv)
    daily = normalise_ohlcv(raw)
    cutoff = pd.Timestamp(str(contract["data"]["cutoff"]))
    daily = daily.loc[:cutoff]
    if daily.empty or daily.index[-1] != cutoff:
        latest = daily.index[-1].strftime("%Y-%m-%d") if not daily.empty else "none"
        raise ValueError(f"expected exact cutoff {cutoff.date()}, latest available date is {latest}")

    summary = evaluate_research(daily, contract)
    manifest = _data_manifest(daily, source)
    summary["data_manifest"] = manifest
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    daily.to_csv(output_dir / "byd_ohlcv.csv", index=True, date_format="%Y-%m-%d")
    candidate_table = _candidate_table(summary)
    candidate_table.to_csv(output_dir / "candidate_summary.csv", index=False)

    selected = summary["selected_candidate"]
    if selected is not None:
        features = build_features(daily)
        position = build_candidate_positions(features)[selected]
        selected_result = run_backtest(
            features,
            position,
            float(contract["costs"]["primary_bps_per_turnover_unit"]),
            selected,
        )
        selected_result.daily.to_csv(
            output_dir / "selected_daily.csv", index=True, date_format="%Y-%m-%d"
        )
        selected_result.trades.to_csv(output_dir / "selected_trades.csv", index=False)

    (output_dir / "summary.json").write_text(
        json.dumps(_json_ready(summary), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_report(output_dir, summary, candidate_table, manifest)
    print(json.dumps({"decision": summary["decision"], "selected_candidate": selected, "output_dir": str(output_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
