"""Promote BYD Dividend Sleeve V1.0 into the formal backtest catalog.

The historical performance path is rebuilt only from immutable BYD and 515180
artifacts. The package evidence cutoff follows the existing CN formal freshness
cutoff. When that cutoff is later than the historical snapshot, an append-only
paired observation for that exact date must exist; this advances monitoring
metadata without rewriting historical returns.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.research.byd_515180_allocation import (
    PRIMARY_COST_BPS,
    STRESS_COST_BPS,
    build_decisions,
    evaluation_table,
    metrics,
    prepare_common_dataset,
)
from src.research.byd_515180_execution import run_allocation

MODEL_ID = "byd_dividend_sleeve_v1_0"
DISPLAY_NAME = "BYD Dividend Sleeve V1.0"
PACKAGE_NAME = f"{MODEL_ID}.json"
HISTORICAL_CUTOFF = "2026-08-03"
BYD_SNAPSHOT_SHA256 = "2e56595d3363b201469f6eefe5dd6390ba156da6fb7ea32a8348d25f06bac179"
ETF_ARTIFACT_SHA256 = "7e077664516b74546ec118f2bf0484ee650577a0898623f3f0cb8623397e061f"
ETF_ADJUSTED_SHA256 = "2173afbe2fcbc8875de55ce0ff9bcb25b1c9f184c5cd273ade682244393c67a5"


class FormalPromotionError(ValueError):
    """Raised when formal promotion evidence is incomplete or inconsistent."""


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalPromotionError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FormalPromotionError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, tuple):
        return [_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if pd.isna(value):
        return None
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    text = json.dumps(
        _clean(payload),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return hashlib.sha256(text.encode()).hexdigest()


def _weights(row: pd.Series) -> dict[str, float]:
    return {
        "BYD": float(row["position_byd_weight"]),
        "515180.SH": float(row["position_etf_weight"]),
        "CASH": float(row["position_cash_weight"]),
    }


def _action(old: float, new: float) -> str:
    if math.isclose(old, new, abs_tol=1e-15):
        return "HOLD"
    if old == 0.0 and new > 0.0:
        return "BUY"
    if old > 0.0 and new == 0.0:
        return "SELL"
    return "INCREASE" if new > old else "DECREASE"


def _monitoring(prospective_root: Path, cutoff: str) -> dict[str, Any]:
    manifest = _object(prospective_root / "manifest.json")
    if manifest.get("schema_version") != "byd_515180_prospective_v1":
        raise FormalPromotionError("prospective manifest schema mismatch")
    if manifest.get("append_only") is not True:
        raise FormalPromotionError("prospective store is not append-only")

    eligible_dates = sorted(
        date
        for date in dict(manifest.get("observation_sha256", {}))
        if date <= cutoff
    )
    if cutoff > HISTORICAL_CUTOFF and cutoff not in eligible_dates:
        raise FormalPromotionError(
            f"formal cutoff {cutoff} lacks an exact paired observation"
        )

    if not eligible_dates:
        return {
            "status": "historical_release_pending_live_monitoring",
            "latest_signal_date": None,
            "observation_count": 0,
            "prospective_eligible_observation_count": 0,
            "completed_defense_episode_count": 0,
            "latest_observation_sha256": None,
            "latest_observation_status": None,
            "latest_common_open_eligible": None,
            "latest_target_weights": None,
            "monitoring_issue": 529,
            "promotion_issue": 557,
        }

    count = 0
    prospective_count = 0
    latest: dict[str, Any] | None = None
    for date in eligible_dates:
        observation = _object(prospective_root / "observations" / f"{date}.json")
        if observation.get("signal_date") != date:
            raise FormalPromotionError(f"paired observation date mismatch: {date}")
        count += 1
        prospective_count += int(observation.get("prospective_eligible") is True)
        latest = observation
    assert latest is not None
    latest_date = str(latest["signal_date"])
    expected_sha = dict(manifest["observation_sha256"])[latest_date]
    observed_sha = hashlib.sha256(
        (prospective_root / "observations" / f"{latest_date}.json").read_bytes()
    ).hexdigest()
    if observed_sha != expected_sha:
        raise FormalPromotionError("latest paired observation SHA mismatch")

    return {
        "status": "post_promotion_prospective_monitoring",
        "latest_signal_date": latest_date,
        "observation_count": count,
        "prospective_eligible_observation_count": prospective_count,
        "completed_defense_episode_count": (
            int(manifest.get("completed_defense_episode_count", 0))
            if latest_date == manifest.get("last_signal_date")
            else 0
        ),
        "latest_observation_sha256": expected_sha,
        "latest_observation_status": latest.get("status"),
        "latest_common_open_eligible": latest.get("common_open_eligible"),
        "latest_prospective_eligible": latest.get("prospective_eligible"),
        "latest_target_weights": dict(latest["targets"]["v1_dividend_75_25"]),
        "prospective_manifest_sha256": _sha256(prospective_root / "manifest.json"),
        "monitoring_issue": 529,
        "promotion_issue": 557,
    }


def build_package(
    *,
    byd_dir: Path,
    etf_dir: Path,
    prospective_root: Path,
    cutoff: str,
    generated_at: str,
) -> dict[str, Any]:
    common, signals, _ = prepare_common_dataset(byd_dir, etf_dir)
    decisions = build_decisions(common, signals)
    candidate_20 = run_allocation(
        "v1_dividend_75_25",
        common,
        decisions["v1_dividend_75_25"],
        cost_bps=PRIMARY_COST_BPS,
    )
    candidate_40 = run_allocation(
        "v1_dividend_75_25",
        common,
        decisions["v1_dividend_75_25"],
        cost_bps=STRESS_COST_BPS,
    )
    baseline_20 = run_allocation(
        "byd_v1_cash",
        common,
        decisions["byd_v1_cash"],
        cost_bps=PRIMARY_COST_BPS,
    )
    baseline_40 = run_allocation(
        "byd_v1_cash",
        common,
        decisions["byd_v1_cash"],
        cost_bps=STRESS_COST_BPS,
    )

    daily = candidate_20.daily
    baseline_daily = baseline_20.daily
    if not daily.index.equals(baseline_daily.index):
        raise FormalPromotionError("candidate and baseline daily paths differ")

    report: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    account = 1.0
    benchmark = 1.0
    peak = 1.0
    previous = {"BYD": 0.0, "515180.SH": 0.0, "CASH": 1.0}
    contribution = {
        "BYD": {"gross": 0.0, "cost": 0.0},
        "515180.SH": {"gross": 0.0, "cost": 0.0},
        "CASH": {"gross": 0.0, "cost": 0.0},
    }

    for date, row in daily.iterrows():
        date_key = pd.Timestamp(date).strftime("%Y-%m-%d")
        net = float(row["net_return"])
        baseline_net = float(baseline_daily.loc[date, "net_return"])
        account *= 1.0 + net
        benchmark *= 1.0 + baseline_net
        peak = max(peak, account)
        current = _weights(row)
        report.append(
            {
                "date": date_key,
                "account": account,
                "bench_byd_v1_cash": benchmark,
                "period_return": net,
                "benchmark_return": baseline_net,
                "relative_excess_return": (1.0 + net) / (1.0 + baseline_net) - 1.0,
                "gross_return": float(row["gross_return"]),
                "transaction_cost": float(row["cost"]),
                "turnover": float(row["turnover_units"]),
                "drawdown": account / peak - 1.0,
                "weight_BYD": current["BYD"],
                "weight_515180": current["515180.SH"],
                "weight_cash": current["CASH"],
                "common_open_eligible": bool(row["common_open_eligible"]),
                "trace_frequency": "daily_open_to_open",
            }
        )
        prices = {
            "BYD": float(common.loc[date, "byd_open"]),
            "515180.SH": float(common.loc[date, "etf_open"]),
            "CASH": 1.0,
        }
        for instrument, weight in current.items():
            if weight > 0.0:
                positions.append(
                    {
                        "date": date_key,
                        "instrument": instrument,
                        "weight": weight,
                        "price": prices[instrument],
                        "base_v1_target": float(signals.loc[date, "base_byd_weight"]),
                        "market_state": str(common.loc[date, "market_state"]),
                        "vol_state": str(common.loc[date, "vol_state"]),
                    }
                )

        changes = {
            instrument: abs(current[instrument] - previous[instrument])
            for instrument in current
        }
        denominator = sum(changes.values())
        cost = float(row["cost"])
        for instrument in current:
            delta = current[instrument] - previous[instrument]
            allocated_cost = cost * changes[instrument] / denominator if denominator else 0.0
            if not math.isclose(delta, 0.0, abs_tol=1e-15):
                trades.append(
                    {
                        "date": date_key,
                        "instrument": instrument,
                        "action": _action(previous[instrument], current[instrument]),
                        "previous_weight": previous[instrument],
                        "target_weight": current[instrument],
                        "weight_delta": delta,
                        "transaction_cost": allocated_cost,
                        "reason": "canonical_byd_v1_0_state_change",
                        "common_open_eligible": bool(row["common_open_eligible"]),
                    }
                )
            contribution[instrument]["cost"] += allocated_cost
        contribution["BYD"]["gross"] += current["BYD"] * float(row["byd_return"])
        contribution["515180.SH"]["gross"] += current["515180.SH"] * float(row["etf_return"])
        previous = current

    attribution = []
    for instrument, values in contribution.items():
        attribution.append(
            {
                "instrument": instrument,
                "name": instrument,
                "gross_contribution": values["gross"],
                "transaction_cost": values["cost"],
                "value": values["gross"] - values["cost"],
                "semantics": "arithmetic daily contribution less allocated transition cost",
            }
        )

    candidate_metrics = metrics(candidate_20.daily)
    baseline_metrics = metrics(baseline_20.daily)
    stress_metrics = metrics(candidate_40.daily)
    stress_baseline_metrics = metrics(baseline_40.daily)
    evaluation = pd.concat(
        [
            evaluation_table(
                {
                    "v1_dividend_75_25": candidate_20,
                    "byd_v1_cash": baseline_20,
                },
                PRIMARY_COST_BPS,
            ),
            evaluation_table(
                {
                    "v1_dividend_75_25": candidate_40,
                    "byd_v1_cash": baseline_40,
                },
                STRESS_COST_BPS,
            ),
        ],
        ignore_index=True,
    )

    monitoring = _monitoring(prospective_root, cutoff)
    return {
        "schema_version": "1.0.0",
        "record_type": "formal_model_backtest",
        "backtest_id": "byd_dividend_sleeve_v1_0-formal-issue-557",
        "model_id": MODEL_ID,
        "display_name": DISPLAY_NAME,
        "market": "cn",
        "benchmark": "BYD V1.0 cash sleeve",
        "publication_status": "accepted_formal_baseline",
        "generated_at": generated_at,
        "evidence_cutoff": cutoff,
        "research_only": True,
        "trade_ready": False,
        "trace_frequency": "daily_open_to_open",
        "date_range": {
            "start": pd.Timestamp(daily.index.min()).strftime("%Y-%m-%d"),
            "end": pd.Timestamp(daily.index.max()).strftime("%Y-%m-%d"),
        },
        "metrics": {
            "Total Return": candidate_metrics["total_return"],
            "CAGR": candidate_metrics["cagr"],
            "Annualized Volatility": candidate_metrics["annual_volatility"],
            "Sharpe Ratio": candidate_metrics["sharpe"],
            "Max Drawdown": candidate_metrics["max_drawdown"],
            "Calmar Ratio": candidate_metrics["calmar"],
            "Turnover": candidate_metrics["turnover_units"],
            "Round Trips Per Year": candidate_metrics["round_trips_per_year"],
            "Benchmark Return": baseline_metrics["total_return"],
            "Benchmark CAGR": baseline_metrics["cagr"],
            "Incremental CAGR": candidate_metrics["cagr"] - baseline_metrics["cagr"],
            "Stress 40bps Total Return": stress_metrics["total_return"],
            "Stress 40bps Benchmark Return": stress_baseline_metrics["total_return"],
        },
        "portfolio_contract": {
            "symbols": ["BYD", "515180.SH", "CASH"],
            "signal_time": "session_close_t",
            "execution_time": "next_common_independently_confirmed_eligible_open_t_plus_1",
            "cost_bps": PRIMARY_COST_BPS,
            "stress_cost_bps": STRESS_COST_BPS,
            "risk_on": {"BYD": 1.0, "515180.SH": 0.0, "CASH": 0.0},
            "defense": {"BYD": 0.75, "515180.SH": 0.25, "CASH": 0.0},
        },
        "report": report,
        "positions": positions,
        "trades": trades,
        "attribution": attribution,
        "window_summary": evaluation.to_dict("records"),
        "operational_monitoring": monitoring,
        "freshness": {
            "status": "current",
            "required_cutoff": cutoff,
            "latest_completed_session": cutoff,
            "latest_realized_holding_end": HISTORICAL_CUTOFF,
            "model_selection_reopened": False,
            "monitoring_source": "append_only_byd_515180_prospective_store",
        },
        "evidence": {
            "source_issue": 525,
            "promotion_issue": 557,
            "monitoring_issue": 529,
            "byd_snapshot_sha256": BYD_SNAPSHOT_SHA256,
            "etf_artifact_sha256": ETF_ARTIFACT_SHA256,
            "etf_adjusted_sha256": ETF_ADJUSTED_SHA256,
            "historical_result_report": "docs/research/byd_515180_core_dividend.md",
            "formal_config": "configs/models/byd_dividend_sleeve_v1_0.yaml",
        },
        "evidence_completeness": {
            "status": "complete",
            "performance_trace": "retained_exact_daily_open_to_open_path",
            "holdings": "retained_exact_daily_weights",
            "trades": "retained_exact_weight_changes",
            "attribution": "derived_exact_from_retained_daily_components",
            "prospective_monitoring": "append_only_identity_bound_metadata",
            "missing": [],
        },
        "interpretation_notes": [
            "User-directed accepted formal baseline; automatic promotion was not used.",
            "The historical result has no fresh holdout; research_only=true and trade_ready=false remain hard boundaries.",
            "Issue #529 continues as post-promotion prospective monitoring and does not rewrite the historical path.",
        ],
    }


def promote(
    *,
    root: Path,
    byd_dir: Path,
    etf_dir: Path,
    prospective_root: Path,
    generated_at: str,
) -> dict[str, Any]:
    root = root.resolve()
    catalog = _object(root / "catalog.json")
    freshness = _object(root / "freshness.json")
    markets = freshness.get("markets")
    if not isinstance(markets, dict) or not markets.get("cn"):
        raise FormalPromotionError("CN formal freshness cutoff is missing")
    cutoff = str(markets["cn"])
    package = build_package(
        byd_dir=byd_dir,
        etf_dir=etf_dir,
        prospective_root=prospective_root,
        cutoff=cutoff,
        generated_at=generated_at,
    )
    package_sha = _write_json(root / PACKAGE_NAME, package)

    records = [
        dict(row)
        for row in catalog.get("records", [])
        if isinstance(row, dict) and row.get("model_id") != MODEL_ID
    ]
    records.append(
        {
            "display_name": DISPLAY_NAME,
            "display_order": 4,
            "model_id": MODEL_ID,
            "path": PACKAGE_NAME,
            "publication_status": "accepted_formal_baseline",
            "sha256": package_sha,
        }
    )
    records.sort(key=lambda row: (int(row.get("display_order", 999)), str(row.get("model_id"))))
    catalog["records"] = records
    catalog["published_at"] = generated_at
    catalog["research_only"] = True
    catalog["trade_ready"] = False
    _write_json(root / "catalog.json", catalog)

    required = [str(value) for value in freshness.get("required_models", [])]
    if MODEL_ID not in required:
        required.append(MODEL_ID)
    freshness["required_models"] = required
    freshness["declared_at"] = generated_at
    freshness["research_only"] = True
    freshness["trade_ready"] = False
    _write_json(root / "freshness.json", freshness)

    return {
        "schema_version": "1.0.0",
        "status": "accepted_formal_baseline_promoted",
        "model_id": MODEL_ID,
        "package_sha256": package_sha,
        "evidence_cutoff": cutoff,
        "historical_date_range_end": package["date_range"]["end"],
        "latest_signal_date": package["operational_monitoring"]["latest_signal_date"],
        "research_only": True,
        "trade_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("data/research/formal_backtests"))
    parser.add_argument("--byd-dir", type=Path, required=True)
    parser.add_argument("--etf-dir", type=Path, required=True)
    parser.add_argument(
        "--prospective-root",
        type=Path,
        default=Path("data/research/byd_515180_prospective"),
    )
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--receipt", type=Path, default=None)
    args = parser.parse_args()
    receipt = promote(
        root=args.root,
        byd_dir=args.byd_dir,
        etf_dir=args.etf_dir,
        prospective_root=args.prospective_root,
        generated_at=args.generated_at,
    )
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt is not None:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
