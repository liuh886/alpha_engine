#!/usr/bin/env python3
"""Refresh the accepted QQQ Rotation v4.3 formal package append-only."""
from __future__ import annotations

import argparse
import copy
import math
from collections.abc import Mapping
from numbers import Integral, Real
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from scripts.refresh_allocation_formal import _qqq_metrics_from_report
from src.artifacts.formal_refresh import FormalRefreshError, load_object, sha256, write_object
from src.artifacts.qqq_v4_3_formal import ASSETS, JOINT_STRATEGY, MODEL_ID, build_formal_package
from src.data.adapters.cnn_fear_greed import fetch_cnn_fear_greed
from src.research.etf_rotation_experiment import _return_metrics
from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.v4_33_ma200_ma20_vix_release import run_v4_33_comparison


class QqqV43RefreshError(FormalRefreshError):
    """Raised when the frozen v4.3 model path cannot be extended safely."""


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if hasattr(value, "item"):
        return _json_safe(value.item())
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _report_prefix(package: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = package.get("report")
    if not isinstance(rows, list) or not rows:
        raise QqqV43RefreshError("current v4.3 report is missing")
    return {
        str(row["date"]): row
        for row in rows
        if isinstance(row, Mapping) and row.get("date")
    }


def _verify_historical_prefix(
    current: Mapping[str, Any], candidate: Mapping[str, Any]
) -> None:
    """Fail closed on model-path drift while preserving frozen economic evidence."""
    old = _report_prefix(current)
    new = _report_prefix(candidate)
    integer_fields = ("position_state", "decision_state")
    text_fields = ("position_label", "decision_reason", "executed_reason")
    boolean_fields = ("panic_repair_active", "slow_bear_defense_active")
    weight_fields = tuple(f"weight_{asset}" for asset in ASSETS)

    for date, prior in old.items():
        refreshed = new.get(date)
        if refreshed is None:
            raise QqqV43RefreshError(f"v4.3 historical row disappeared: {date}")
        for field in integer_fields:
            if field in prior and int(prior[field]) != int(refreshed.get(field)):
                raise QqqV43RefreshError(
                    f"v4.3 historical decision path changed on {date}: {field}"
                )
        for field in text_fields:
            if field in prior and str(prior[field]) != str(refreshed.get(field)):
                raise QqqV43RefreshError(
                    f"v4.3 historical decision path changed on {date}: {field}"
                )
        for field in boolean_fields:
            if field in prior and bool(prior[field]) is not bool(refreshed.get(field)):
                raise QqqV43RefreshError(
                    f"v4.3 historical overlay changed on {date}: {field}"
                )
        for field in weight_fields:
            if field not in prior:
                continue
            right = refreshed.get(field)
            if right is None or not math.isclose(
                float(prior[field]), float(right), rel_tol=0.0, abs_tol=1e-12
            ):
                raise QqqV43RefreshError(
                    f"v4.3 historical allocation changed on {date}: {field}"
                )


def _latest_weights(package: Mapping[str, Any]) -> dict[str, float]:
    positions = package.get("positions")
    if not isinstance(positions, list) or not positions:
        raise QqqV43RefreshError("current v4.3 positions are missing")
    latest = max(
        str(row.get("date") or "") for row in positions if isinstance(row, Mapping)
    )
    return {
        str(row["instrument"]): float(row["weight"])
        for row in positions
        if isinstance(row, Mapping) and str(row.get("date")) == latest
    }


def _increment_attribution(
    existing: object,
    daily: pd.DataFrame,
    appended_dates: set[str],
    previous_weights: Mapping[str, float],
) -> list[dict[str, Any]]:
    contribution = {asset: 0.0 for asset in ASSETS}
    if isinstance(existing, list):
        for item in existing:
            if not isinstance(item, Mapping):
                continue
            instrument = str(item.get("instrument") or "")
            if instrument in contribution:
                contribution[instrument] = float(item.get("value") or 0.0)

    prior = {asset: float(previous_weights.get(asset, 0.0)) for asset in ASSETS}
    for timestamp, row in daily.iterrows():
        key = pd.Timestamp(timestamp).date().isoformat()
        if key not in appended_dates:
            continue
        weights = {asset: float(row[f"weight_{asset}"]) for asset in ASSETS}
        returns = {
            asset: float(row[f"{asset}_next_open_return"]) for asset in ASSETS
        }
        if not all(math.isfinite(value) for value in returns.values()):
            continue
        for asset in ASSETS:
            contribution[asset] += weights[asset] * returns[asset]
        changes = {asset: abs(weights[asset] - prior[asset]) for asset in ASSETS}
        denominator = sum(changes.values())
        if denominator:
            cost = float(row["transaction_cost"])
            for asset in ASSETS:
                contribution[asset] -= cost * changes[asset] / denominator
        prior = weights

    return [
        {
            "instrument": asset,
            "name": asset,
            "value": contribution[asset],
            "semantics": "arithmetic daily contribution less allocated transition cost",
        }
        for asset in ASSETS
    ]


def _window_summary(report: list[dict[str, Any]]) -> list[dict[str, Any]]:
    frame = pd.DataFrame(report)
    if frame.empty:
        raise QqqV43RefreshError("v4.3 report is empty")
    frame["date"] = pd.to_datetime(frame["date"], errors="raise")
    split = max(1, min(len(frame) - 1, int(len(frame) * 0.60)))
    windows = (
        ("full", frame),
        ("early_60pct", frame.iloc[:split]),
        ("late_40pct", frame.iloc[split:]),
    )
    rows: list[dict[str, Any]] = []
    for label, sample in windows:
        returns = pd.Series(
            pd.to_numeric(sample["period_return"], errors="raise").to_numpy(),
            index=pd.DatetimeIndex(sample["date"]),
            dtype=float,
        )
        metrics = _return_metrics(returns, annual_risk_free_rate=0.0)
        rows.append(
            {
                "window": label,
                "start": sample["date"].min().date().isoformat(),
                "end": sample["date"].max().date().isoformat(),
                "observations": int(len(sample)),
                "total_return": float(metrics["total_return"]),
                "cagr": float(metrics["cagr"]),
                "annual_volatility": float(metrics["annual_volatility"]),
                "sharpe": float(metrics["sharpe"]),
                "sortino": float(metrics["sortino"]),
                "max_drawdown": float(metrics["max_drawdown"]),
                "calmar": float(metrics["calmar"]),
            }
        )
    return rows


def refresh(
    *,
    current_package: Path,
    bundle_dir: Path,
    bridge_contract_path: Path,
    cutoff: str,
    generated_at: str,
    output: Path,
) -> dict[str, Any]:
    current = load_object(current_package)
    if current.get("model_id") != MODEL_ID:
        raise QqqV43RefreshError("QQQ refresh requires the accepted v4.3 package")

    contract = yaml.safe_load(bridge_contract_path.read_text(encoding="utf-8"))
    bars, coverage, data_identity = fetch_governed_etf_strategy_bars(
        symbols=["QQQI", "QQQ", "TQQQ", "SGOV", "^VIX", "^VXN"],
        start=contract["data"]["start_date"],
        end=cutoff,
        bundle_dir=bundle_dir,
    )
    fear_greed = fetch_cnn_fear_greed(end_date=cutoff)
    _, results, diagnostics = run_v4_33_comparison(
        bars, contract, fear_greed, cash_symbol="SGOV"
    )
    result = results[JOINT_STRATEGY]
    latest_economic = result.daily.index.max().date().isoformat()
    evidence = _json_safe(
        {
            **dict(current.get("evidence") or {}),
            "refresh_adapter": "refresh_qqq_v4_3_formal.append_only",
            "refresh_source_package_sha256": sha256(current_package),
            "baseline_contract_path": bridge_contract_path.as_posix(),
            "baseline_contract_sha256": sha256(bridge_contract_path),
            "bundle_manifest_sha256": sha256(bundle_dir / "bundle_manifest.json"),
            "data_identity": data_identity,
            "coverage": coverage.to_dict("records"),
            "retrospective_diagnostics": diagnostics,
            "model_selection_reopened": False,
        }
    )
    freshness = {
        "status": "current",
        "required_cutoff": cutoff,
        "latest_completed_session": cutoff,
        "latest_realized_holding_end": latest_economic,
        "model_selection_reopened": False,
        "data_bundle_id": data_identity.get("bundle_id"),
        "research_only": True,
        "trade_ready": False,
    }
    replay = _json_safe(
        build_formal_package(
            result,
            bars,
            generated_at=generated_at,
            evidence_cutoff=cutoff,
            backtest_id=f"{MODEL_ID}-through-{cutoff.replace('-', '_')}",
            evidence=evidence,
            freshness=freshness,
        )
    )
    _verify_historical_prefix(current, replay)

    package = copy.deepcopy(current)
    old_report = _report_prefix(current)
    boundary = max(old_report)
    appended_report = [
        dict(row)
        for row in replay["report"]
        if str(row.get("date") or "") > boundary
    ]
    if not appended_report:
        raise QqqV43RefreshError("v4.3 refresh produced no new realized sessions")
    appended_dates = {str(row["date"]) for row in appended_report}
    package["report"].extend(appended_report)
    package["positions"].extend(
        dict(row)
        for row in replay["positions"]
        if str(row.get("date") or "") in appended_dates
    )
    package["trades"].extend(
        dict(row)
        for row in replay["trades"]
        if str(row.get("date") or "") in appended_dates
    )

    previous_weights = _latest_weights(current)
    package["attribution"] = _increment_attribution(
        current.get("attribution"), result.daily, appended_dates, previous_weights
    )
    metrics = _qqq_metrics_from_report(package["report"], annual_risk_free_rate=0.0)
    benchmark_return = float(
        (1.0 + pd.to_numeric(pd.DataFrame(package["report"])["bench"], errors="raise")).prod()
        - 1.0
    )
    package["metrics"] = {
        **dict(package.get("metrics") or {}),
        **metrics,
        "Benchmark Return": benchmark_return,
    }
    package["window_summary"] = _window_summary(package["report"])
    package["backtest_id"] = f"{MODEL_ID}-through-{cutoff.replace('-', '_')}"
    package["generated_at"] = generated_at
    package["evidence_cutoff"] = cutoff
    package["date_range"] = {**dict(package["date_range"]), "end": latest_economic}
    package["freshness"] = freshness
    package["evidence"] = {
        **dict(evidence),
        "append_only_boundary": boundary,
        "historical_economic_evidence_recomputed": False,
    }
    package["research_only"] = True
    package["trade_ready"] = False

    output.parent.mkdir(parents=True, exist_ok=True)
    write_object(output, package)
    return {
        "model_id": MODEL_ID,
        "status": "refreshed",
        "evidence_cutoff": cutoff,
        "economic_end": latest_economic,
        "appended_sessions": len(appended_dates),
        "output_sha256": sha256(output),
        "model_selection_reopened": False,
        "research_only": True,
        "trade_ready": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current-package", type=Path, required=True)
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument(
        "--bridge-contract",
        type=Path,
        default=Path("configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"),
    )
    parser.add_argument("--cutoff", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = refresh(
        current_package=args.current_package,
        bundle_dir=args.bundle_dir,
        bridge_contract_path=args.bridge_contract,
        cutoff=args.cutoff,
        generated_at=args.generated_at,
        output=args.output,
    )
    print(receipt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
