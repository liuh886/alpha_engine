"""Refresh accepted QQQ v4.2 and BYD v1.2 formal packages append-only."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from scripts.promote_byd_v1_2_formal import build_package as build_byd_package
from src.artifacts.formal_refresh import FormalRefreshError, load_object, sha256, write_object
from src.research.etf_rotation_experiment import _return_metrics
from src.research.etf_strategy_data import fetch_governed_etf_strategy_bars
from src.research.vix_rotation_experiment import config_from_contract
from src.research.vxn_bridge_allocation_experiment import run_bridge_allocation_comparison


class AllocationRefreshError(FormalRefreshError):
    """Raised when a frozen allocation model cannot be refreshed."""


QQQ_MODEL = "qqqi_qqq_tqqq_v4_2"
QQQ_STRATEGY = "rotation_vxn_bridge_v4_2_50_50"
BYD_MODEL = "byd_v1_2_convex_momentum_budget_v1"
QQQ_ASSETS = ("QQQI", "QQQ", "TQQQ")


def _manifest_digest(payload: Mapping[str, Any]) -> str:
    body = dict(payload)
    body.pop("manifest_sha256", None)
    return hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    output = frame.copy()
    if "date" in output.columns:
        output["date"] = pd.to_datetime(output["date"]).dt.strftime("%Y-%m-%d")
    output.to_csv(path, index=False, lineterminator="\n", float_format="%.12g")


def _next_weights(package: Mapping[str, Any]) -> dict[str, float]:
    positions = package.get("positions")
    if not isinstance(positions, list) or not positions:
        return {}
    latest = max(str(row.get("date") or "") for row in positions if isinstance(row, dict))
    return {
        str(row["instrument"]): float(row["weight"])
        for row in positions
        if isinstance(row, dict) and str(row.get("date")) == latest
    }


def _action(previous: float, target: float) -> str:
    if previous == 0.0 and target > 0.0:
        return "BUY"
    if previous > 0.0 and target == 0.0:
        return "SELL"
    return "INCREASE" if target > previous else "DECREASE"


def _verify_qqq_decision_overlap(
    existing_by_date: Mapping[str, Mapping[str, Any]], daily: pd.DataFrame
) -> None:
    """Fail closed on model-path drift while leaving frozen economic evidence untouched."""

    observed: set[str] = set()
    for timestamp, row in daily.iterrows():
        key = pd.Timestamp(timestamp).date().isoformat()
        existing = existing_by_date.get(key)
        if existing is None:
            continue
        observed.add(key)
        integer_fields = {
            "position_state": int(row["position_state"]),
            "decision_state": int(row["decision_state"]),
        }
        for field, expected in integer_fields.items():
            if field in existing and int(existing[field]) != expected:
                raise AllocationRefreshError(
                    f"QQQ historical decision path changed on {key}: {field}"
                )
        text_fields = {
            "position_label": str(row["position_label"]),
            "decision_reason": str(row["decision_reason"]),
            "executed_reason": str(row["executed_reason"]),
        }
        for field, expected in text_fields.items():
            if field in existing and str(existing[field]) != expected:
                raise AllocationRefreshError(
                    f"QQQ historical decision path changed on {key}: {field}"
                )
        for asset in QQQ_ASSETS:
            field = f"weight_{asset}"
            if field in existing and not math.isclose(
                float(existing[field]),
                float(row[field]),
                rel_tol=0.0,
                abs_tol=1e-12,
            ):
                raise AllocationRefreshError(
                    f"QQQ historical decision path changed on {key}: {field}"
                )

    expected_overlap = {
        key
        for key, row in existing_by_date.items()
        if "position_state" in row and "decision_state" in row
    }
    missing = sorted(expected_overlap - observed)
    if missing:
        raise AllocationRefreshError(
            f"QQQ current replay is missing {len(missing)} frozen decision dates; first={missing[0]}"
        )


def _qqq_metrics_from_report(
    report: list[dict[str, Any]], *, annual_risk_free_rate: float
) -> dict[str, float]:
    frame = pd.DataFrame(report)
    if frame.empty or "period_return" not in frame:
        raise AllocationRefreshError("QQQ formal report has no realized returns")
    index = pd.to_datetime(frame["date"], errors="coerce")
    returns = pd.Series(
        pd.to_numeric(frame["period_return"], errors="coerce").to_numpy(),
        index=index,
        dtype=float,
    )
    metrics = _return_metrics(
        returns,
        annual_risk_free_rate=annual_risk_free_rate,
    )
    required = (
        "total_return",
        "cagr",
        "annual_volatility",
        "sharpe",
        "sortino",
        "max_drawdown",
        "calmar",
    )
    if any(not math.isfinite(float(metrics[key])) for key in required):
        raise AllocationRefreshError("QQQ refreshed summary metrics are not finite")
    return {
        "Total Return": float(metrics["total_return"]),
        "CAGR": float(metrics["cagr"]),
        "Annualized Volatility": float(metrics["annual_volatility"]),
        "Sharpe Ratio": float(metrics["sharpe"]),
        "Sortino Ratio": float(metrics["sortino"]),
        "Max Drawdown": float(metrics["max_drawdown"]),
        "Calmar Ratio": float(metrics["calmar"]),
        "Turnover": float(pd.to_numeric(frame.get("turnover"), errors="coerce").fillna(0.0).sum()),
        "Transaction Cost": float(
            pd.to_numeric(frame.get("transaction_cost"), errors="coerce").fillna(0.0).sum()
        ),
    }


def _increment_qqq_attribution(
    *,
    existing: object,
    daily: pd.DataFrame,
    appended_dates: set[str],
    previous_weights: Mapping[str, float],
) -> list[dict[str, Any]]:
    contribution = {asset: 0.0 for asset in QQQ_ASSETS}
    if isinstance(existing, list):
        for item in existing:
            if not isinstance(item, Mapping):
                continue
            instrument = str(item.get("instrument") or "")
            if instrument in contribution:
                contribution[instrument] = float(item.get("value") or 0.0)

    prior = {asset: float(previous_weights.get(asset, 0.0)) for asset in QQQ_ASSETS}
    for timestamp, row in daily.iterrows():
        key = pd.Timestamp(timestamp).date().isoformat()
        if key not in appended_dates:
            continue
        weights = {asset: float(row[f"weight_{asset}"]) for asset in QQQ_ASSETS}
        returns = {
            asset: float(row[f"{asset}_next_open_return"]) for asset in QQQ_ASSETS
        }
        if not all(math.isfinite(value) for value in returns.values()):
            continue
        for asset in QQQ_ASSETS:
            contribution[asset] += weights[asset] * returns[asset]
        changes = {asset: abs(weights[asset] - prior[asset]) for asset in QQQ_ASSETS}
        denominator = sum(changes.values())
        if denominator:
            cost = float(row["transaction_cost"])
            for asset in QQQ_ASSETS:
                contribution[asset] -= cost * changes[asset] / denominator
        prior = weights

    return [
        {
            "instrument": asset,
            "name": asset,
            "value": contribution[asset],
            "semantics": "arithmetic daily contribution less allocated transition cost",
        }
        for asset in QQQ_ASSETS
    ]


def refresh_qqq(
    *,
    current_package: Path,
    bundle_dir: Path,
    contract_path: Path,
    cutoff: str,
    generated_at: str,
    output: Path,
) -> dict[str, Any]:
    package = copy.deepcopy(load_object(current_package))
    if package.get("model_id") != QQQ_MODEL:
        raise AllocationRefreshError("QQQ refresh requires the accepted v4.2 package")
    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    boundaries = contract["boundaries"]
    symbols = [
        *boundaries["tradable_symbols"],
        boundaries["vix_symbol"],
        boundaries["vxn_symbol"],
    ]
    bars, coverage, data_identity = fetch_governed_etf_strategy_bars(
        symbols=list(dict.fromkeys(symbols)),
        start=contract["data"]["start_date"],
        end=cutoff,
        bundle_dir=bundle_dir,
    )
    _, results, _, diagnostics = run_bridge_allocation_comparison(bars, contract)
    if QQQ_STRATEGY not in results:
        raise AllocationRefreshError("frozen v4.2 result is missing")
    daily = results[QQQ_STRATEGY].daily.copy()
    daily.index = pd.to_datetime(daily.index).tz_localize(None).normalize()
    existing_dates = {
        str(row.get("date")) for row in package.get("report", []) if isinstance(row, dict)
    }
    existing_by_date = {
        str(row.get("date")): row
        for row in package.get("report", [])
        if isinstance(row, dict) and row.get("date")
    }
    _verify_qqq_decision_overlap(existing_by_date, daily)

    account = float(package["report"][-1]["account"])
    benchmark = float(package["report"][-1]["bench_qqq"])
    peak = max(float(row["account"]) for row in package["report"])
    previous = _next_weights(package)
    attribution_previous = dict(previous)
    existing_attribution = copy.deepcopy(package.get("attribution"))
    appended_dates: set[str] = set()
    for timestamp, row in daily.iterrows():
        key = timestamp.date().isoformat()
        if key in existing_dates or key > cutoff:
            continue
        net = float(row["net_return"])
        if not math.isfinite(net):
            continue
        qqq_return = float(row["QQQ_next_open_return"])
        if not math.isfinite(qqq_return):
            continue
        account *= 1.0 + net
        benchmark *= 1.0 + qqq_return
        peak = max(peak, account)
        weights = {
            "QQQI": float(row["weight_QQQI"]),
            "QQQ": float(row["weight_QQQ"]),
            "TQQQ": float(row["weight_TQQQ"]),
        }
        package["report"].append(
            {
                "date": key,
                "account": account,
                "bench_qqq": benchmark,
                "bench": qqq_return,
                "turnover": float(row["turnover_units"]),
                "period_return": net,
                "gross_return": float(row["gross_return"]),
                "transaction_cost": float(row["transaction_cost"]),
                "position_state": int(row["position_state"]),
                "position_label": str(row["position_label"]),
                "decision_state": int(row["decision_state"]),
                "decision_reason": str(row["decision_reason"]),
                "executed_reason": str(row["executed_reason"]),
                "weight_QQQI": weights["QQQI"],
                "weight_QQQ": weights["QQQ"],
                "weight_TQQQ": weights["TQQQ"],
                "drawdown": account / peak - 1.0,
                "trace_frequency": "daily_open_to_open",
            }
        )
        prices = {
            "QQQI": float(row["QQQI_open"]),
            "QQQ": float(row["QQQ_open"]),
            "TQQQ": float(row["TQQQ_open"]),
        }
        for instrument, weight in weights.items():
            if weight <= 0.0:
                continue
            package["positions"].append(
                {
                    "date": key,
                    "instrument": instrument,
                    "weight": weight,
                    "price": prices[instrument],
                    "position_state": int(row["position_state"]),
                    "position_label": str(row["position_label"]),
                    "executed_reason": str(row["executed_reason"]),
                }
            )
        union = sorted(set(previous) | set(weights))
        absolute_change = sum(
            abs(weights.get(name, 0.0) - previous.get(name, 0.0)) for name in union
        )
        for instrument in union:
            old = previous.get(instrument, 0.0)
            target = weights.get(instrument, 0.0)
            delta = target - old
            if math.isclose(delta, 0.0, abs_tol=1e-15):
                continue
            allocated = (
                float(row["transaction_cost"]) * abs(delta) / absolute_change
                if absolute_change
                else 0.0
            )
            package["trades"].append(
                {
                    "date": key,
                    "instrument": instrument,
                    "action": _action(old, target),
                    "previous_weight": old,
                    "target_weight": target,
                    "weight_delta": delta,
                    "transaction_cost": allocated,
                    "reason": str(row["executed_reason"]),
                    "position_state": int(row["position_state"]),
                    "position_label": str(row["position_label"]),
                    "vix_close": float(row["vix_close"]),
                    "vix_regime": str(row["vix_regime"]),
                    "vxn_close": float(row["vxn_close"]),
                    "vxn_regime": str(row["vxn_regime"]),
                }
            )
        previous = weights
        existing_dates.add(key)
        appended_dates.add(key)

    if not appended_dates:
        raise AllocationRefreshError("QQQ refresh produced no new realized sessions")

    package["attribution"] = _increment_qqq_attribution(
        existing=existing_attribution,
        daily=daily,
        appended_dates=appended_dates,
        previous_weights=attribution_previous,
    )
    config = config_from_contract(contract)
    package["metrics"] = {
        **dict(package["metrics"]),
        **_qqq_metrics_from_report(
            package["report"],
            annual_risk_free_rate=config.annual_risk_free_rate,
        ),
    }
    latest_economic = max(
        [str(row.get("date")) for row in package["report"] if isinstance(row, dict)]
    )
    package["backtest_id"] = f"{QQQ_MODEL}-through-{cutoff.replace('-', '_')}"
    package["generated_at"] = generated_at
    package["evidence_cutoff"] = cutoff
    package["date_range"] = {**dict(package["date_range"]), "end": latest_economic}
    package["freshness"] = {
        "status": "current",
        "required_cutoff": cutoff,
        "latest_completed_session": cutoff,
        "latest_realized_holding_end": latest_economic,
        "model_selection_reopened": False,
        "data_bundle_id": data_identity.get("bundle_id"),
        "research_only": True,
        "trade_ready": False,
    }
    package["evidence"] = {
        **dict(package.get("evidence") or {}),
        "refresh_adapter": "refresh_allocation_formal.qqq_v4_2",
        "contract_path": contract_path.as_posix(),
        "contract_sha256": sha256(contract_path),
        "bundle_manifest_sha256": sha256(bundle_dir / "bundle_manifest.json"),
        "data_identity": data_identity,
        "coverage": coverage.to_dict("records"),
        "retrospective_diagnostics": diagnostics,
        "append_only_boundary": max(existing_by_date),
        "historical_economic_evidence_recomputed": False,
        "model_selection_reopened": False,
    }
    package["research_only"] = True
    package["trade_ready"] = False
    write_object(output, package)
    return {
        "model_id": QQQ_MODEL,
        "appended_sessions": len(appended_dates),
        "output_sha256": sha256(output),
    }


def _extend_byd_input(
    *,
    base_dir: Path,
    shadow_store: Path,
    cutoff: str,
    output_dir: Path,
) -> dict[str, Any]:
    shutil.copytree(base_dir, output_dir)
    adjusted_path = output_dir / "adjusted_ohlcv.csv"
    session_path = output_dir / "session_audit.csv"
    manifest_path = output_dir / "manifest.json"
    adjusted = pd.read_csv(adjusted_path, parse_dates=["date"])
    sessions = pd.read_csv(session_path, parse_dates=["date"])
    manifest = load_object(manifest_path)
    frozen_cutoff = pd.Timestamp(manifest["cutoff"])
    rows: list[dict[str, Any]] = []
    session_rows: list[dict[str, Any]] = []
    observation_hashes: dict[str, str] = {}
    for path in sorted((shadow_store / "observations").glob("*.json")):
        observation = load_object(path)
        signal_date = str(observation.get("signal_date") or path.stem)
        timestamp = pd.Timestamp(signal_date)
        if timestamp <= frozen_cutoff or signal_date > cutoff:
            continue
        chain = observation.get("chain_linked_adjusted_ohlcv")
        if not isinstance(chain, Mapping):
            raise AllocationRefreshError(f"BYD adjusted observation is missing: {signal_date}")
        required = ("open", "high", "low", "close", "volume")
        if any(value not in chain for value in required):
            raise AllocationRefreshError(f"BYD observation is incomplete: {signal_date}")
        rows.append({"date": signal_date, **{key: float(chain[key]) for key in required}})
        session_rows.append(
            {
                "date": signal_date,
                "open_research_eligible": bool(observation.get("open_research_eligible", False)),
            }
        )
        observation_hashes[signal_date] = sha256(path)
    if not rows or max(row["date"] for row in rows) != cutoff:
        raise AllocationRefreshError("BYD prospective observations do not reach target cutoff")
    adjusted = pd.concat([adjusted, pd.DataFrame(rows)], ignore_index=True)
    adjusted = adjusted.sort_values("date").drop_duplicates("date", keep="last")
    sessions = pd.concat([sessions, pd.DataFrame(session_rows)], ignore_index=True)
    sessions = sessions.sort_values("date").drop_duplicates("date", keep="last")
    _write_csv(adjusted_path, adjusted)
    _write_csv(session_path, sessions)
    manifest.update(
        {
            "schema_version": "byd_canonical_adjusted_ohlcv_v2",
            "cutoff": cutoff,
            "last_date": cutoff,
            "rows": int(len(adjusted)),
            "adjusted_sha256": sha256(adjusted_path),
            "session_audit_sha256": sha256(session_path),
            "observation_sha256": observation_hashes,
            "source_shadow_manifest_sha256": sha256(shadow_store / "manifest.json"),
        }
    )
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    write_object(manifest_path, manifest)
    return manifest


def _extend_etf_input(
    *,
    base_dir: Path,
    paired_store: Path,
    cutoff: str,
    output_dir: Path,
) -> dict[str, Any]:
    shutil.copytree(base_dir, output_dir)
    raw_path = output_dir / "raw_ohlcv.csv"
    adjusted_path = output_dir / "adjusted_ohlcv.csv"
    session_path = output_dir / "session_audit.csv"
    actions_path = output_dir / "corporate_actions.csv"
    manifest_path = output_dir / "manifest.json"
    raw = pd.read_csv(raw_path, parse_dates=["date"])
    adjusted = pd.read_csv(adjusted_path, parse_dates=["date"])
    sessions = pd.read_csv(session_path, parse_dates=["date"])
    actions = pd.read_csv(actions_path, parse_dates=["date"])
    manifest = load_object(manifest_path)
    frozen_cutoff = pd.Timestamp(manifest["cutoff"])
    raw_rows: list[dict[str, Any]] = []
    adjusted_rows: list[dict[str, Any]] = []
    session_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    observation_hashes: dict[str, str] = {}
    for path in sorted((paired_store / "observations").glob("*.json")):
        observation = load_object(path)
        signal_date = str(observation.get("signal_date") or path.stem)
        timestamp = pd.Timestamp(signal_date)
        if timestamp <= frozen_cutoff or signal_date > cutoff:
            continue
        etf = observation.get("etf")
        if not isinstance(etf, Mapping):
            raise AllocationRefreshError(f"ETF observation is missing: {signal_date}")
        raw_row = etf.get("primary_raw_ohlcv")
        adjusted_row = etf.get("chain_linked_adjusted_ohlcv")
        if not isinstance(raw_row, Mapping) or not isinstance(adjusted_row, Mapping):
            raise AllocationRefreshError(f"ETF observation is incomplete: {signal_date}")
        required = ("open", "high", "low", "close", "volume")
        if any(key not in raw_row or key not in adjusted_row for key in required):
            raise AllocationRefreshError(f"ETF OHLCV is incomplete: {signal_date}")
        raw_values = {key: float(raw_row[key]) for key in required}
        adjusted_values = {key: float(adjusted_row[key]) for key in required}
        raw_rows.append({"date": signal_date, **raw_values})
        factor = adjusted_values["close"] / raw_values["close"]
        extension = {column: None for column in adjusted.columns}
        extension.update(
            {
                "date": signal_date,
                **adjusted_values,
                "factor": factor,
                "adjustment_anchor_date": adjusted.iloc[-1].get("adjustment_anchor_date"),
                "adjustment_anchor_factor": adjusted.iloc[-1].get("adjustment_anchor_factor"),
                "price_role": "adjusted_feature_and_label",
            }
        )
        adjusted_rows.append(extension)
        session_rows.append(
            {
                "date": signal_date,
                "open_research_eligible": bool(etf.get("open_research_eligible", False)),
            }
        )
        company_actions = etf.get("company_actions")
        if isinstance(company_actions, Mapping):
            dividend = float(company_actions.get("dividend", 0.0))
            split = float(company_actions.get("stock_split", 0.0))
            if dividend or split:
                action = {column: None for column in actions.columns}
                action.update(
                    {
                        "date": signal_date,
                        "dividend": dividend,
                        "stock_split": split,
                    }
                )
                action_rows.append(action)
        observation_hashes[signal_date] = sha256(path)
    if not raw_rows or max(row["date"] for row in raw_rows) != cutoff:
        raise AllocationRefreshError("ETF paired observations do not reach target cutoff")
    raw = pd.concat([raw, pd.DataFrame(raw_rows)], ignore_index=True)
    raw = raw.sort_values("date").drop_duplicates("date", keep="last")
    adjusted = pd.concat([adjusted, pd.DataFrame(adjusted_rows)], ignore_index=True)
    adjusted = adjusted.sort_values("date").drop_duplicates("date", keep="last")
    sessions = pd.concat([sessions, pd.DataFrame(session_rows)], ignore_index=True)
    sessions = sessions.sort_values("date").drop_duplicates("date", keep="last")
    if action_rows:
        actions = pd.concat([actions, pd.DataFrame(action_rows)], ignore_index=True)
        actions = actions.sort_values("date").drop_duplicates("date", keep="last")
    _write_csv(raw_path, raw)
    _write_csv(adjusted_path, adjusted)
    _write_csv(session_path, sessions)
    _write_csv(actions_path, actions)
    manifest.update(
        {
            "schema_version": "cn_etf_canonical_total_return_v2",
            "cutoff": cutoff,
            "last_date": cutoff,
            "rows": int(len(adjusted)),
            "raw_sha256": sha256(raw_path),
            "adjusted_sha256": sha256(adjusted_path),
            "session_audit_sha256": sha256(session_path),
            "corporate_actions_sha256": sha256(actions_path),
            "observation_sha256": observation_hashes,
            "source_paired_manifest_sha256": sha256(paired_store / "manifest.json"),
        }
    )
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    write_object(manifest_path, manifest)
    return manifest


def refresh_byd(
    *,
    current_package: Path,
    base_byd_dir: Path,
    base_etf_dir: Path,
    shadow_store: Path,
    paired_store: Path,
    signal_ledger: Path,
    cutoff: str,
    generated_at: str,
    output: Path,
) -> dict[str, Any]:
    current = load_object(current_package)
    if current.get("model_id") != BYD_MODEL:
        raise AllocationRefreshError("BYD refresh requires the accepted BYD v1.2 package")
    with tempfile.TemporaryDirectory(prefix="formal-byd-refresh-") as temporary:
        root = Path(temporary)
        byd_dir = root / "byd"
        etf_dir = root / "etf"
        byd_manifest = _extend_byd_input(
            base_dir=base_byd_dir,
            shadow_store=shadow_store,
            cutoff=cutoff,
            output_dir=byd_dir,
        )
        etf_manifest = _extend_etf_input(
            base_dir=base_etf_dir,
            paired_store=paired_store,
            cutoff=cutoff,
            output_dir=etf_dir,
        )

        import src.research.byd_515180_allocation as allocation

        allocation.ETF_CUTOFF = cutoff
        allocation.ETF_SCHEMA = str(etf_manifest["schema_version"])
        allocation.WINDOWS["retrospective_2025_plus"] = ("2025-01-01", cutoff)
        allocation.WINDOWS["full_overlap"] = ("2019-11-26", cutoff)
        candidate = build_byd_package(
            byd_dir=byd_dir,
            etf_dir=etf_dir,
            signal_ledger=signal_ledger,
            cutoff=cutoff,
            generated_at=generated_at,
        )
    for field in ("report", "positions", "trades"):
        old = current.get(field)
        new = candidate.get(field)
        if not isinstance(old, list) or not isinstance(new, list) or new[: len(old)] != old:
            raise AllocationRefreshError(f"BYD historical {field} changed")
    if candidate.get("portfolio_contract") != current.get("portfolio_contract"):
        raise AllocationRefreshError("BYD portfolio contract changed")
    candidate["backtest_id"] = f"{BYD_MODEL}-through-{cutoff.replace('-', '_')}"
    candidate["evidence_cutoff"] = cutoff
    candidate["generated_at"] = generated_at
    candidate["date_range"] = {
        **dict(candidate["date_range"]),
        "end": min(str(candidate["date_range"]["end"]), cutoff),
    }
    candidate["freshness"] = {
        "status": "current",
        "required_cutoff": cutoff,
        "latest_completed_session": cutoff,
        "latest_realized_holding_end": str(candidate["date_range"]["end"]),
        "model_selection_reopened": False,
        "research_only": True,
        "trade_ready": False,
    }
    candidate["evidence"] = {
        **dict(candidate.get("evidence") or {}),
        "refresh_adapter": "refresh_allocation_formal.byd_v1_2",
        "byd_extended_manifest_sha256": str(byd_manifest["manifest_sha256"]),
        "etf_extended_manifest_sha256": str(etf_manifest["manifest_sha256"]),
        "shadow_store_manifest_sha256": sha256(shadow_store / "manifest.json"),
        "paired_store_manifest_sha256": sha256(paired_store / "manifest.json"),
        "model_selection_reopened": False,
    }
    candidate["research_only"] = True
    candidate["trade_ready"] = False
    write_object(output, candidate)
    return {
        "model_id": BYD_MODEL,
        "appended_sessions": len(candidate["report"]) - len(current["report"]),
        "output_sha256": sha256(output),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    qqq = subparsers.add_parser("qqq")
    qqq.add_argument("--current-package", type=Path, required=True)
    qqq.add_argument("--bundle-dir", type=Path, required=True)
    qqq.add_argument(
        "--contract",
        type=Path,
        default=Path("configs/research_paradigms/qqqi_qqq_tqqq_vxn_bridge_v4_2.yaml"),
    )
    qqq.add_argument("--cutoff", required=True)
    qqq.add_argument("--generated-at", required=True)
    qqq.add_argument("--output", type=Path, required=True)

    byd = subparsers.add_parser("byd")
    byd.add_argument("--current-package", type=Path, required=True)
    byd.add_argument("--base-byd-dir", type=Path, required=True)
    byd.add_argument("--base-etf-dir", type=Path, required=True)
    byd.add_argument("--shadow-store", type=Path, required=True)
    byd.add_argument("--paired-store", type=Path, required=True)
    byd.add_argument("--signal-ledger", type=Path, required=True)
    byd.add_argument("--cutoff", required=True)
    byd.add_argument("--generated-at", required=True)
    byd.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "qqq":
        result = refresh_qqq(
            current_package=args.current_package,
            bundle_dir=args.bundle_dir,
            contract_path=args.contract,
            cutoff=args.cutoff,
            generated_at=args.generated_at,
            output=args.output,
        )
    else:
        result = refresh_byd(
            current_package=args.current_package,
            base_byd_dir=args.base_byd_dir,
            base_etf_dir=args.base_etf_dir,
            shadow_store=args.shadow_store,
            paired_store=args.paired_store,
            signal_ledger=args.signal_ledger,
            cutoff=args.cutoff,
            generated_at=args.generated_at,
            output=args.output,
        )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
