"""Publish BYD v1.2 convex momentum as the accepted formal baseline.

The package is rebuilt from the immutable BYD and 515180 artifacts. BYD v1.1
is retained inside the package as the exact daily benchmark. Promotion is
explicitly user-authorized; no automatic or fresh-holdout claim is made.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd

from scripts.promote_byd_dividend_sleeve_formal import (
    BYD_SNAPSHOT_SHA256,
    ETF_ADJUSTED_SHA256,
    ETF_ARTIFACT_SHA256,
    _action,
    _object,
    _write_json,
)
from src.research.byd_515180_allocation import (
    PRIMARY_COST_BPS,
    STRESS_COST_BPS,
    metrics,
    prepare_common_dataset,
)
from src.research.byd_v1_2_convex_momentum import (
    BASELINE,
    CANDIDATE,
    CONVEX_POWER,
    FULL_INCREMENT_MOMENTUM,
    MAX_FINANCED_INCREMENT,
    build_evaluation,
    episode_attribution,
    period_attribution,
    run_candidates,
)
from src.research.byd_v1_2_trend_expansion import (
    PRIMARY_FINANCING_RATE,
    STRESS_FINANCING_RATE,
)

MODEL_ID = CANDIDATE
DISPLAY_NAME = "BYD v1.2"
PACKAGE_NAME = f"{MODEL_ID}.json"
SUPERSEDED_MODEL_ID = "byd_dividend_sleeve_v1_0"
HISTORICAL_CUTOFF = "2026-08-03"


class BYDV12FormalPromotionError(ValueError):
    """Raised when the formal BYD v1.2 package cannot be reproduced."""


def _weights(row: pd.Series) -> dict[str, float]:
    return {
        "BYD": float(row["position_byd_weight"]),
        "515180.SH": float(row["position_etf_weight"]),
        "CASH": float(row["position_cash_weight"]),
    }


def _signal_monitoring(root: Path) -> dict[str, Any]:
    latest = root / "latest.json"
    if not latest.exists():
        return {
            "status": "formal_signal_ledger_pending_first_evaluation",
            "ledger": root.as_posix(),
            "latest_signal_date": None,
            "latest_fingerprint": None,
            "latest_target_weights": None,
            "delivery_status": None,
        }
    payload = _object(latest)
    if payload.get("model_id") != MODEL_ID:
        raise BYDV12FormalPromotionError("signal ledger model identity mismatch")
    return {
        "status": "formal_signal_monitoring_active",
        "ledger": root.as_posix(),
        "latest_signal_date": payload.get("signal_date"),
        "latest_fingerprint": payload.get("fingerprint"),
        "latest_target_weights": payload.get("target_weights"),
        "delivery_status": payload.get("delivery_status"),
    }


def build_package(
    *,
    byd_dir: Path,
    etf_dir: Path,
    signal_ledger: Path,
    cutoff: str,
    generated_at: str,
) -> dict[str, Any]:
    common, signals, _ = prepare_common_dataset(byd_dir, etf_dir)
    primary, state = run_candidates(
        common,
        signals,
        cost_bps=PRIMARY_COST_BPS,
        annual_financing_rate=PRIMARY_FINANCING_RATE,
    )
    stress, _ = run_candidates(
        common,
        signals,
        cost_bps=STRESS_COST_BPS,
        annual_financing_rate=STRESS_FINANCING_RATE,
    )
    candidate = primary[CANDIDATE]
    baseline = primary[BASELINE]
    candidate_stress = stress[CANDIDATE]
    baseline_stress = stress[BASELINE]
    if not candidate.daily.index.equals(baseline.daily.index):
        raise BYDV12FormalPromotionError("candidate and baseline paths differ")

    report: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    account = 1.0
    benchmark = 1.0
    peak = 1.0
    previous = {"BYD": 0.0, "515180.SH": 0.0, "CASH": 1.0}
    contribution = {
        "BYD": {"gross": 0.0, "transaction_cost": 0.0, "financing_cost": 0.0},
        "515180.SH": {"gross": 0.0, "transaction_cost": 0.0, "financing_cost": 0.0},
        "CASH": {"gross": 0.0, "transaction_cost": 0.0, "financing_cost": 0.0},
    }

    for date, row in candidate.daily.iterrows():
        key = pd.Timestamp(date).strftime("%Y-%m-%d")
        baseline_row = baseline.daily.loc[date]
        net = float(row["net_return"])
        benchmark_net = float(baseline_row["net_return"])
        account *= 1.0 + net
        benchmark *= 1.0 + benchmark_net
        peak = max(peak, account)
        current = _weights(row)
        state_row = state.loc[date]
        report.append(
            {
                "date": key,
                "account": account,
                "bench_byd_v1_1": benchmark,
                "period_return": net,
                "benchmark_return": benchmark_net,
                "relative_excess_return": (1.0 + net) / (1.0 + benchmark_net) - 1.0,
                "gross_return": float(row["gross_return"]),
                "transaction_cost": float(row["cost"]),
                "financing_cost": float(row["financing_cost"]),
                "turnover": float(row["turnover_units"]),
                "drawdown": account / peak - 1.0,
                "weight_BYD": current["BYD"],
                "weight_515180": current["515180.SH"],
                "weight_cash": current["CASH"],
                "base_BYD_weight": float(state_row["base_byd_weight"]),
                "trend_expansion_active": bool(state_row["trend_expansion_active"]),
                "momentum_20": float(state_row["mom_20"]),
                "momentum_scale": float(state_row["momentum_scale"]),
                "financed_increment": float(state_row["financed_increment"]),
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
            if not math.isclose(weight, 0.0, abs_tol=1e-15):
                positions.append(
                    {
                        "date": key,
                        "instrument": instrument,
                        "weight": weight,
                        "price": prices[instrument],
                        "base_BYD_weight": float(state_row["base_byd_weight"]),
                        "market_state": str(state_row["market_state"]),
                        "vol_state": str(state_row["vol_state"]),
                        "momentum_20": float(state_row["mom_20"]),
                        "momentum_scale": float(state_row["momentum_scale"]),
                        "financed_increment": float(state_row["financed_increment"]),
                    }
                )

        changes = {
            instrument: abs(current[instrument] - previous[instrument])
            for instrument in current
        }
        denominator = sum(changes.values())
        transaction_cost = float(row["cost"])
        for instrument in current:
            delta = current[instrument] - previous[instrument]
            allocated = (
                transaction_cost * changes[instrument] / denominator
                if denominator
                else 0.0
            )
            contribution[instrument]["transaction_cost"] += allocated
            if not math.isclose(delta, 0.0, abs_tol=1e-15):
                trades.append(
                    {
                        "date": key,
                        "instrument": instrument,
                        "action": _action(previous[instrument], current[instrument]),
                        "previous_weight": previous[instrument],
                        "target_weight": current[instrument],
                        "weight_delta": delta,
                        "transaction_cost": allocated,
                        "reason": "convex_momentum_budget_state_or_scale_change",
                        "common_open_eligible": bool(row["common_open_eligible"]),
                    }
                )
        contribution["BYD"]["gross"] += current["BYD"] * float(row["byd_return"])
        contribution["515180.SH"]["gross"] += current["515180.SH"] * float(row["etf_return"])
        contribution["CASH"]["financing_cost"] += float(row["financing_cost"])
        previous = current

    attribution = []
    for instrument, values in contribution.items():
        total_cost = values["transaction_cost"] + values["financing_cost"]
        attribution.append(
            {
                "instrument": instrument,
                "name": instrument,
                "gross_contribution": values["gross"],
                "transaction_cost": values["transaction_cost"],
                "financing_cost": values["financing_cost"],
                "value": values["gross"] - total_cost,
                "semantics": "arithmetic daily contribution less allocated transaction and financing costs",
            }
        )

    evaluation = build_evaluation(primary, stress)
    periods = period_attribution(primary)
    episodes = episode_attribution(primary)
    candidate_metrics = metrics(candidate.daily)
    baseline_metrics = metrics(baseline.daily)
    stress_metrics = metrics(candidate_stress.daily)
    stress_baseline_metrics = metrics(baseline_stress.daily)
    relative_stress = (
        (1.0 + stress_metrics["total_return"])
        / (1.0 + stress_baseline_metrics["total_return"])
        - 1.0
    )

    return {
        "schema_version": "1.0.0",
        "record_type": "formal_model_backtest",
        "backtest_id": f"{MODEL_ID}-formal-user-authorized-2026-08-06",
        "model_id": MODEL_ID,
        "display_name": DISPLAY_NAME,
        "market": "cn",
        "benchmark": "BYD v1.1",
        "publication_status": "accepted_formal_baseline",
        "generated_at": generated_at,
        "evidence_cutoff": cutoff,
        "research_only": True,
        "trade_ready": False,
        "trace_frequency": "daily_open_to_open",
        "date_range": {
            "start": pd.Timestamp(candidate.daily.index.min()).strftime("%Y-%m-%d"),
            "end": pd.Timestamp(candidate.daily.index.max()).strftime("%Y-%m-%d"),
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
            "Stress Relative Terminal Wealth": relative_stress,
            "Financed Sessions": int(candidate.daily["borrowed_weight"].gt(0.0).sum()),
            "Completed Expansion Episodes": int(len(episodes)),
            "Maximum Positive Period Share": float(periods["positive_contribution_share"].max()),
            "Maximum Positive Episode Share": float(episodes["positive_contribution_share"].max()),
        },
        "portfolio_contract": {
            "symbols": ["BYD", "515180.SH", "CASH"],
            "signal_time": "session_close_t",
            "execution_time": "next_common_independently_confirmed_eligible_open_t_plus_1",
            "cost_bps": PRIMARY_COST_BPS,
            "stress_cost_bps": STRESS_COST_BPS,
            "primary_annual_financing_rate": PRIMARY_FINANCING_RATE,
            "stress_annual_financing_rate": STRESS_FINANCING_RATE,
            "defense": {"BYD": 0.75, "515180.SH": 0.25, "CASH": 0.0},
            "offense": {"BYD": 1.0, "515180.SH": 0.0, "CASH": 0.0},
            "maximum_expansion": {"BYD": 1.125, "515180.SH": 0.0, "CASH": -0.125},
            "convex_momentum_budget": {
                "full_increment_momentum": FULL_INCREMENT_MOMENTUM,
                "convex_power": CONVEX_POWER,
                "maximum_financed_increment": MAX_FINANCED_INCREMENT,
            },
        },
        "report": report,
        "positions": positions,
        "trades": trades,
        "attribution": attribution,
        "window_summary": evaluation.to_dict("records"),
        "period_attribution": periods.to_dict("records"),
        "episode_attribution": episodes.to_dict("records"),
        "operational_monitoring": _signal_monitoring(signal_ledger),
        "freshness": {
            "status": "current",
            "required_cutoff": cutoff,
            "latest_completed_session": cutoff,
            "latest_realized_holding_end": pd.Timestamp(candidate.daily.index.max()).strftime("%Y-%m-%d"),
            "model_selection_reopened": False,
            "monitoring_source": signal_ledger.as_posix(),
        },
        "evidence": {
            "source_challenge_issue": 592,
            "selection_issue": 596,
            "promotion_authority": "explicit_user_direction_2026_08_06",
            "byd_snapshot_sha256": BYD_SNAPSHOT_SHA256,
            "etf_artifact_sha256": ETF_ARTIFACT_SHA256,
            "etf_adjusted_sha256": ETF_ADJUSTED_SHA256,
            "candidate_contract": "configs/research_candidates/byd_v1_2_convex_momentum_budget_v1.yaml",
            "formal_config": "configs/models/byd_v1_2_convex_momentum_budget_v1.yaml",
            "implementation": "src/research/byd_v1_2_convex_momentum.py",
        },
        "evidence_completeness": {
            "status": "complete",
            "performance_trace": "retained_exact_daily_open_to_open_path",
            "holdings": "retained_exact_daily_weights_including_financing",
            "trades": "retained_exact_weight_changes",
            "attribution": "derived_exact_from_retained_daily_components",
            "robustness": "primary_stress_period_and_episode_attribution",
            "signal_monitoring": "repository_persisted_identity_bound_ledger",
            "missing": [],
        },
        "interpretation_notes": [
            "User-directed accepted formal baseline; automatic promotion was not used.",
            "The candidate was selected on consumed historical evidence and has no fresh historical holdout.",
            "The user explicitly authorized promotion before completion of the originally planned forward validation window.",
            "research_only=true and trade_ready=false remain hard boundaries.",
            "BYD v1.1 is retained as the exact daily benchmark inside this package.",
        ],
    }


def promote(
    *,
    root: Path,
    byd_dir: Path,
    etf_dir: Path,
    signal_ledger: Path,
    generated_at: str,
) -> dict[str, Any]:
    root = root.resolve()
    catalog = _object(root / "catalog.json")
    freshness = _object(root / "freshness.json")
    markets = freshness.get("markets")
    if not isinstance(markets, dict) or not markets.get("cn"):
        raise BYDV12FormalPromotionError("CN formal freshness cutoff is missing")
    cutoff = str(markets["cn"])
    package = build_package(
        byd_dir=byd_dir,
        etf_dir=etf_dir,
        signal_ledger=signal_ledger,
        cutoff=cutoff,
        generated_at=generated_at,
    )
    package_sha = _write_json(root / PACKAGE_NAME, package)

    records = [
        dict(row)
        for row in catalog.get("records", [])
        if isinstance(row, dict)
        and row.get("model_id") not in {MODEL_ID, SUPERSEDED_MODEL_ID}
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
    records.sort(
        key=lambda row: (int(row.get("display_order", 999)), str(row.get("model_id")))
    )
    catalog["records"] = records
    catalog["published_at"] = generated_at
    catalog["research_only"] = True
    catalog["trade_ready"] = False
    _write_json(root / "catalog.json", catalog)

    required = [
        str(value)
        for value in freshness.get("required_models", [])
        if str(value) not in {MODEL_ID, SUPERSEDED_MODEL_ID}
    ]
    required.append(MODEL_ID)
    freshness["required_models"] = required
    freshness["declared_at"] = generated_at
    freshness["research_only"] = True
    freshness["trade_ready"] = False
    _write_json(root / "freshness.json", freshness)

    old_package = root / f"{SUPERSEDED_MODEL_ID}.json"
    if old_package.exists():
        old_package.unlink()

    return {
        "schema_version": "1.0.0",
        "status": "accepted_formal_baseline_promoted",
        "model_id": MODEL_ID,
        "superseded_model_id": SUPERSEDED_MODEL_ID,
        "package_sha256": package_sha,
        "evidence_cutoff": cutoff,
        "historical_date_range_end": package["date_range"]["end"],
        "promotion_authority": "explicit_user_direction_2026_08_06",
        "research_only": True,
        "trade_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path("data/research/formal_backtests")
    )
    parser.add_argument("--byd-dir", type=Path, required=True)
    parser.add_argument("--etf-dir", type=Path, required=True)
    parser.add_argument(
        "--signal-ledger",
        type=Path,
        default=Path("data/research/byd_v1_2_signal_ledger"),
    )
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--receipt", type=Path)
    args = parser.parse_args()
    receipt = promote(
        root=args.root,
        byd_dir=args.byd_dir,
        etf_dir=args.etf_dir,
        signal_ledger=args.signal_ledger,
        generated_at=args.generated_at,
    )
    text = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
