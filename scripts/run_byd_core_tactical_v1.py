#!/usr/bin/env python3
"""Run the frozen BYD V1.0 core/tactical research contract."""

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
from src.research.byd_core_tactical_v1 import (
    build_candidate_positions,
    build_features,
    evaluate_research,
)
from src.research.byd_single_asset_v1 import run_backtest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(
            "configs/research_paradigms/byd_v1_0_core_tactical.yaml"
        ),
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input-csv", type=Path)
    source.add_argument(
        "--fetch-provider",
        choices=("auto", "baostock", "akshare", "yfinance"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def _candidate_table(summary: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in summary["candidate_rows"]:
        selection = row["selection_metrics"]
        validation = row["validation_metrics"]
        rows.append(
            {
                "candidate": row["candidate"],
                "selection_pass": row["selection_pass"],
                "selection_cagr_retention": row["selection_cagr_retention"],
                "selection_cagr": selection["cagr"],
                "selection_max_drawdown": selection["max_drawdown"],
                "selection_calmar": selection["calmar"],
                "selection_sortino": selection["sortino"],
                "selection_exposure": selection["exposure"],
                "round_trips_per_year": selection["round_trips_per_year"],
                "validation_total_return": validation["total_return"],
                "validation_cagr": validation["cagr"],
                "validation_max_drawdown": validation["max_drawdown"],
                "validation_calmar": validation["calmar"],
                "stress_40_selection_total_return": row[
                    "selection_stress_40_metrics"
                ]["total_return"],
                "largest_positive_defense_episode_share": row[
                    "largest_positive_defense_episode_share"
                ],
            }
        )
    return pd.DataFrame(rows)


def _selected_episodes(summary: dict[str, Any]) -> pd.DataFrame:
    selected = summary["selected_candidate"]
    if selected is None:
        return pd.DataFrame(
            columns=[
                "candidate",
                "window",
                "episode_id",
                "start",
                "end",
                "sessions",
                "minimum_position",
                "candidate_return",
                "buy_hold_return",
                "relative_return",
            ]
        )
    row = next(
        item for item in summary["candidate_rows"] if item["candidate"] == selected
    )
    records: list[dict[str, Any]] = []
    for episode in row["defense_episodes"]:
        records.append(
            {"candidate": selected, "window": "selection", **episode}
        )
    holdout = summary["retrospective_holdout"]
    if holdout is not None:
        for episode in holdout["defense_episodes"]:
            records.append(
                {
                    "candidate": selected,
                    "window": "retrospective_holdout",
                    **episode,
                }
            )
    return pd.DataFrame.from_records(records)


def _write_report(
    output_dir: Path,
    summary: dict[str, Any],
    candidate_table: pd.DataFrame,
    manifest: dict[str, Any],
) -> None:
    selected = summary["selected_candidate"] or "none"
    holdout = summary["retrospective_holdout"]
    benchmark_selection = summary["buy_hold_selection_metrics"]
    benchmark_validation = summary["buy_hold_validation_metrics"]
    lines = [
        "# BYD V1.0 core/tactical baseline",
        "",
        "> Research only. `trade_ready=false`. The 2025+ result is a retrospective holdout, not prospective evidence.",
        "",
        "## Decision",
        "",
        f"- Decision: `{summary['decision']}`",
        f"- Selected candidate: `{selected}`",
        f"- Latest governed data: `{summary['latest_data_date']}`",
        f"- Current executed open position: `{summary['selected_current_open_position']}`",
        f"- Latest close target for next open: `{summary['selected_latest_close_target_for_next_open']}`",
        f"- Prospective confirmation required: `{summary['prospective_confirmation_required']}`",
        "",
        "## Data identity",
        "",
        f"- Provider: `{manifest['provider']}`",
        f"- Adjustment: `{manifest.get('adjustment', 'declared by input')}`",
        f"- Rows: `{manifest['rows']}`",
        f"- Range: `{manifest['first_date']}` to `{manifest['last_date']}`",
        f"- SHA-256: `{manifest['sha256']}`",
        "",
        "## Buy-and-hold reference",
        "",
        f"- 2012–2024 CAGR: `{benchmark_selection['cagr']:.4f}`",
        f"- 2012–2024 max drawdown: `{benchmark_selection['max_drawdown']:.4f}`",
        f"- 2012–2024 Calmar: `{benchmark_selection['calmar']:.4f}`",
        f"- 2023–2024 CAGR: `{benchmark_validation['cagr']:.4f}`",
        f"- 2023–2024 max drawdown: `{benchmark_validation['max_drawdown']:.4f}`",
        "",
        "## Frozen candidate comparison",
        "",
        candidate_table.to_markdown(index=False, floatfmt=".4f"),
        "",
        "## Retrospective holdout",
        "",
    ]
    if holdout is None:
        lines.append(
            "No candidate passed the pre-2025 selection gates, so no holdout candidate was promoted."
        )
    else:
        candidate_metrics = holdout["candidate_metrics"]
        benchmark_metrics = holdout["buy_hold_metrics"]
        lines.extend(
            [
                f"- Classification: `{holdout['classification']}`",
                f"- Pass: `{holdout['pass']}`",
                f"- Candidate total return: `{candidate_metrics['total_return']:.4f}`",
                f"- Buy-and-hold total return: `{benchmark_metrics['total_return']:.4f}`",
                f"- Candidate CAGR: `{candidate_metrics['cagr']:.4f}`",
                f"- Buy-and-hold CAGR: `{benchmark_metrics['cagr']:.4f}`",
                f"- Candidate max drawdown: `{candidate_metrics['max_drawdown']:.4f}`",
                f"- Buy-and-hold max drawdown: `{benchmark_metrics['max_drawdown']:.4f}`",
                f"- Candidate Calmar: `{candidate_metrics['calmar']:.4f}`",
                f"- Buy-and-hold Calmar: `{benchmark_metrics['calmar']:.4f}`",
                f"- 40 bps total return: `{holdout['stress_40_metrics']['total_return']:.4f}`",
                "",
                "### Gates",
                "",
            ]
        )
        for gate, passed in holdout["gates"].items():
            lines.append(f"- {'PASS' if passed else 'FAIL'} `{gate}`")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "A supported decision establishes the BYD V1.0 retrospective research baseline only. It does not authorize an order, live allocation, or trade-ready promotion. The selected rule must accumulate independent prospective shadow evidence before any status change.",
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
            daily, source = _fetch_governed_provider(
                contract, args.fetch_provider
            )
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
            json.dumps(blocked, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        raise

    summary = evaluate_research(daily, contract)
    manifest = _data_manifest(daily, source)
    summary["data_manifest"] = manifest
    daily.to_csv(
        output_dir / "byd_ohlcv.csv", index=True, date_format="%Y-%m-%d"
    )

    candidate_table = _candidate_table(summary)
    candidate_table.to_csv(output_dir / "candidate_summary.csv", index=False)
    episodes = _selected_episodes(summary)
    episodes.to_csv(output_dir / "defense_episodes.csv", index=False)

    selected = summary["selected_candidate"]
    if selected is not None:
        features = build_features(daily)
        position = build_candidate_positions(features)[selected]
        result = run_backtest(
            features,
            position,
            float(contract["costs"]["primary_bps_per_turnover_unit"]),
            selected,
        )
        result.daily.to_csv(
            output_dir / "selected_daily.csv",
            index=True,
            date_format="%Y-%m-%d",
        )
        result.trades.to_csv(output_dir / "selected_trades.csv", index=False)

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
    _write_report(output_dir, summary, candidate_table, manifest)
    print(
        json.dumps(
            {
                "decision": summary["decision"],
                "selected_candidate": selected,
                "provider": manifest["provider"],
                "latest_close_target_for_next_open": summary[
                    "selected_latest_close_target_for_next_open"
                ],
                "output_dir": str(output_dir),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
