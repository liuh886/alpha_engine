#!/usr/bin/env python3
"""Promote the certified CN x1.1 candidate into a complete formal backtest."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

MODEL_ID = "cn_x1_1"
DISPLAY_NAME = "CN x1.1"
BACKTEST_ID = "cn_x1_1-formal-31022910416"
WORKFLOW_RUN_ID = 31022910416
ARTIFACT_ID = 8937409026
ARTIFACT_DIGEST = (
    "sha256:e540e400dbefd5178122444e709182323f1b363a3c41496fd8212e5095ee5a4b"
)
GENERATED_AT = "2026-08-05T17:36:00Z"
EVIDENCE_CUTOFF = "2026-08-03"
LATEST_REALIZED_END = "2026-07-29"


class PromotionError(ValueError):
    """Raised when the frozen candidate evidence cannot support promotion."""


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PromotionError(f"JSON root must be an object: {path}")
    return payload


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frozen_evidence_bytes(path: Path) -> bytes:
    payload = path.read_bytes()
    if path.suffix.lower() == ".csv":
        return payload.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    return hashlib.sha256((text + "\n").encode("utf-8")).hexdigest()


def _float(value: str | None) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def _optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _bool(value: str | None) -> bool:
    return str(value).strip().lower() == "true"


def verify_evidence(evidence_root: Path) -> dict[str, Any]:
    evidence_manifest = _json(evidence_root / "evidence_manifest.json")
    decision = _json(evidence_root / "decision.json")
    manifest = _json(evidence_root / "manifest.json")
    model_spec = _json(evidence_root / "model_spec.json")

    if evidence_manifest.get("experiment_id") != (
        "cn_x1_1_regime_gated_sector_breadth_v1"
    ):
        raise PromotionError("unexpected experiment identity")
    if decision.get("candidate_authorized") is not True:
        raise PromotionError("candidate is not authorized")
    if decision.get("decision") != "cn_x1_1_regime_gated_candidate_authorized":
        raise PromotionError("candidate decision mismatch")
    if decision.get("model_rules_changed") is not False:
        raise PromotionError("candidate rules changed after certification")
    if decision.get("economic_evidence_changed") is not False:
        raise PromotionError("candidate evidence changed after certification")
    if manifest.get("provider_cutoff") != EVIDENCE_CUTOFF:
        raise PromotionError("provider cutoff mismatch")
    if model_spec.get("model_id") != "cn_x1_1_regime_gated_sector_breadth_v1":
        raise PromotionError("model specification mismatch")

    declared_files = evidence_manifest.get("files")
    if not isinstance(declared_files, list) or not declared_files:
        raise PromotionError("evidence file manifest is empty")
    for row in declared_files:
        if not isinstance(row, dict):
            raise PromotionError("invalid evidence file row")
        relative = str(row.get("path") or "")
        path = evidence_root / relative
        if not path.is_file():
            raise PromotionError(f"missing frozen evidence: {relative}")
        frozen_bytes = _frozen_evidence_bytes(path)
        if hashlib.sha256(frozen_bytes).hexdigest() != row.get("sha256"):
            raise PromotionError(f"frozen evidence hash mismatch: {relative}")
        if len(frozen_bytes) != int(row.get("bytes", -1)):
            raise PromotionError(f"frozen evidence byte-size mismatch: {relative}")

    return {
        "decision": decision,
        "manifest": manifest,
        "model_spec": model_spec,
        "evidence_manifest": evidence_manifest,
    }


def _action(previous: float, target: float) -> str:
    if previous == 0.0 and target > 0.0:
        return "BUY"
    if previous > 0.0 and target == 0.0:
        return "SELL"
    if target > previous:
        return "INCREASE"
    return "DECREASE"


def build_package(evidence_root: Path, *, generated_at: str = GENERATED_AT) -> dict[str, Any]:
    verified = verify_evidence(evidence_root)
    periods = _csv(evidence_root / "rebalance_periods.csv")
    holdings = _csv(evidence_root / "holdings.csv")
    windows = _csv(evidence_root / "half_year_results.csv")
    evaluations = _csv(evidence_root / "evaluation_summary.csv")
    state_coverage = _csv(evidence_root / "yearly_state_coverage.csv")

    if len(periods) != 102:
        raise PromotionError(f"expected 102 rebalance periods, found {len(periods)}")
    if len(holdings) != 252:
        raise PromotionError(f"expected 252 holding rows, found {len(holdings)}")

    holdings_by_date: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in holdings:
        holdings_by_date[row["datetime"]].append(row)

    report: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    instrument_attribution: dict[tuple[str, str, str], dict[str, Any]] = {}
    sector_attribution: dict[str, dict[str, Any]] = {}
    previous_weights: dict[str, float] = {}
    account = 1.0
    benchmark_account = 1.0
    peak = 1.0
    max_drawdown = 0.0
    total_turnover = 0.0
    total_cost = 0.0
    risk_on_count = 0

    for index, period in enumerate(periods):
        date = period["datetime"]
        net_return = _float(period["net_return"])
        benchmark_return = _float(period["benchmark_return"])
        gross_return = _float(period["gross_return"])
        turnover = _float(period["turnover"])
        cost = _float(period["cost"])
        risk_on = _bool(period["risk_on"])
        account_before = account
        benchmark_before = benchmark_account
        account *= 1.0 + net_return
        benchmark_account *= 1.0 + benchmark_return
        peak = max(peak, account)
        drawdown = account / peak - 1.0
        max_drawdown = min(max_drawdown, drawdown)
        total_turnover += turnover
        total_cost += cost
        risk_on_count += int(risk_on)

        period_holdings = holdings_by_date.get(date, [])
        if not period_holdings:
            raise PromotionError(f"no holdings retained for rebalance date {date}")
        current_weights = {
            row["instrument"]: _float(row["weight"]) for row in period_holdings
        }
        if abs(sum(current_weights.values()) - 1.0) > 1e-9:
            raise PromotionError(f"weights do not sum to one on {date}")

        report.append(
            {
                "date": date,
                "account_before": account_before,
                "account": account,
                "bench_hs300_before": benchmark_before,
                "bench_hs300": benchmark_account,
                "period_return": net_return,
                "gross_return": gross_return,
                "benchmark_return": benchmark_return,
                "excess_return": net_return - benchmark_return,
                "relative_log_return": _float(period["relative_log_return"]),
                "turnover": turnover,
                "transaction_cost": cost,
                "drawdown": drawdown,
                "window": period["window"],
                "evaluation": period["evaluation"],
                "risk_on": risk_on,
                "risk_state": "risk_on" if risk_on else "risk_off_csi300_fallback",
                "votes": int(period["votes"]),
                "long_trend": _bool(period["long_trend"]),
                "medium_momentum": _bool(period["medium_momentum"]),
                "cross_sectional_breadth": _bool(
                    period["cross_sectional_breadth"]
                ),
                "breadth_value": _float(period["breadth_value"]),
                "benchmark_hit": _bool(period["benchmark_hit"]),
                "trace_frequency": "non_overlapping_10_session",
            }
        )

        for row in period_holdings:
            instrument = row["instrument"]
            entity = row["entity"]
            sector = row["sector"]
            weight = _float(row["weight"])
            contribution = _float(row["net_contribution"])
            positions.append(
                {
                    "date": date,
                    "instrument": instrument,
                    "name": entity,
                    "sector": sector,
                    "weight": weight,
                    "score": _optional_float(row["score"]),
                    "raw_return": _float(row["raw_return"]),
                    "benchmark_return": _float(row["benchmark_return"]),
                    "net_contribution": contribution,
                    "precision_hit": _bool(row["precision_hit"]),
                    "window": row["window"],
                    "evaluation": row["evaluation"],
                    "risk_state": "risk_on" if risk_on else "risk_off_csi300_fallback",
                }
            )
            key = (instrument, entity, sector)
            item = instrument_attribution.setdefault(
                key,
                {
                    "instrument": instrument,
                    "name": entity,
                    "sector": sector,
                    "value": 0.0,
                    "periods_held": 0,
                    "risk_on_periods": 0,
                    "risk_off_periods": 0,
                },
            )
            item["value"] += contribution
            item["periods_held"] += 1
            item["risk_on_periods"] += int(risk_on)
            item["risk_off_periods"] += int(not risk_on)
            sector_item = sector_attribution.setdefault(
                sector,
                {
                    "instrument": f"sector:{sector}",
                    "name": sector,
                    "value": 0.0,
                    "periods_held": 0,
                    "attribution_level": "sector",
                },
            )
            sector_item["value"] += contribution
            sector_item["periods_held"] += 1

        all_instruments = sorted(set(previous_weights) | set(current_weights))
        changed = {
            instrument: abs(
                current_weights.get(instrument, 0.0)
                - previous_weights.get(instrument, 0.0)
            )
            for instrument in all_instruments
        }
        changed_total = sum(changed.values())
        for instrument in all_instruments:
            previous = previous_weights.get(instrument, 0.0)
            target = current_weights.get(instrument, 0.0)
            delta = target - previous
            if abs(delta) <= 1e-12:
                continue
            allocated_cost = cost * changed[instrument] / changed_total if changed_total else 0.0
            source = next(
                (row for row in period_holdings if row["instrument"] == instrument),
                None,
            )
            trades.append(
                {
                    "date": date,
                    "instrument": instrument,
                    "action": _action(previous, target),
                    "previous_weight": previous,
                    "target_weight": target,
                    "weight_delta": delta,
                    "transaction_cost": allocated_cost,
                    "reason": "regime_gated_sector_breadth_rebalance",
                    "risk_state": "risk_on" if risk_on else "risk_off_csi300_fallback",
                    "window": period["window"],
                    "entity": source["entity"] if source else None,
                    "sector": source["sector"] if source else None,
                    "period_index": index,
                }
            )
        previous_weights = current_weights

    strategy_return = account - 1.0
    benchmark_return = benchmark_account - 1.0
    relative_excess = account / benchmark_account - 1.0
    historical = next(
        row for row in evaluations if row["evaluation"] == "historical_2022H2_2025H2"
    )
    reporting = next(row for row in evaluations if row["evaluation"] == "reporting_2026")

    attribution = list(instrument_attribution.values()) + list(sector_attribution.values())
    attribution.sort(key=lambda row: abs(float(row["value"])), reverse=True)

    model_spec = verified["model_spec"]
    manifest = verified["manifest"]
    package = {
        "schema_version": "1.0.0",
        "record_type": "formal_model_backtest",
        "backtest_id": BACKTEST_ID,
        "model_id": MODEL_ID,
        "display_name": DISPLAY_NAME,
        "market": "cn",
        "benchmark": "000300",
        "publication_status": "accepted_formal_baseline",
        "generated_at": generated_at,
        "evidence_cutoff": EVIDENCE_CUTOFF,
        "research_only": True,
        "trade_ready": False,
        "trace_frequency": "non_overlapping_10_session",
        "date_range": {"start": periods[0]["datetime"], "end": EVIDENCE_CUTOFF},
        "metrics": {
            "Total Return": strategy_return,
            "Benchmark Return": benchmark_return,
            "Compounded Relative Excess Return": relative_excess,
            "Max Drawdown": max_drawdown,
            "Turnover": total_turnover,
            "Transaction Cost": total_cost,
            "Rebalance Count": float(len(periods)),
            "Risk-On Share": risk_on_count / len(periods),
            "Historical Relative Excess Return": _float(historical["relative_excess"]),
            "Historical Risk-On Active Hit Rate": _float(
                historical["risk_on_active_hit_rate"]
            ),
            "2026 Reporting Relative Excess Return": _float(
                reporting["relative_excess"]
            ),
        },
        "portfolio_contract": {
            "universe": "cn_selected_equities_v3",
            "universe_size": 130,
            "active_score": "r0_cn_x1_0_raw_return_rank",
            "active_score_provider": "current_cn_ohlcv",
            "sector_score": "mean_daily_percentile_of_sector_top3_names",
            "selected_sectors": int(model_spec["sectors"]),
            "names_per_sector": int(model_spec["names_per_sector"]),
            "risk_on_weighting": "four_names_equal_weight",
            "risk_off_fallback": "100_percent_CSI300",
            "regime_votes": [
                "CSI300_close_above_MA200",
                "CSI300_60_session_return_positive",
                "CN130_share_above_own_MA60_at_least_50_percent",
            ],
            "votes_required": int(model_spec["votes_required"]),
            "holding_sessions": int(model_spec["horizon_sessions"]),
            "rebalance_sessions": int(model_spec["rebalance_sessions"]),
            "execution_delay_sessions": int(model_spec["execution_delay_sessions"]),
            "cost_bps": int(model_spec["cost_bps"]),
        },
        "report": report,
        "positions": positions,
        "trades": trades,
        "attribution": attribution,
        "window_summary": [
            {
                **row,
                "total_return": _float(row["total_return"]),
                "benchmark_return": _float(row["benchmark_return"]),
                "relative_excess": _float(row["relative_excess"]),
                "max_drawdown": _float(row["max_drawdown"]),
                "all_period_hit_rate": _float(row["all_period_hit_rate"]),
                "risk_on_share": _float(row["risk_on_share"]),
                "turnover": _float(row["turnover"]),
                "rebalance_count": int(row["rebalance_count"]),
            }
            for row in windows
        ],
        "state_summary": [
            {
                "year": int(row["year"]),
                "risk_on_count": int(row["risk_on_count"]),
                "risk_off_count": int(row["risk_off_count"]),
                "risk_on_share": _float(row["risk_on_share"]),
                "both_states_present": _bool(row["both_states_present"]),
            }
            for row in state_coverage
        ],
        "evaluation_summary": [
            {
                key: (
                    _float(value)
                    if key
                    in {
                        "total_return",
                        "benchmark_return",
                        "relative_excess",
                        "max_drawdown",
                        "all_period_hit_rate",
                        "risk_on_active_hit_rate",
                        "risk_on_share",
                        "risk_on_relative_excess",
                        "risk_off_relative_excess",
                        "risk_off_total_cost",
                        "turnover",
                        "maximum_name_absolute_contribution_share",
                        "maximum_sector_absolute_contribution_share",
                    }
                    else int(value)
                    if key in {"rebalance_sessions", "cost_bps", "positive_excess_windows", "rebalance_count"}
                    else value
                )
                for key, value in row.items()
            }
            for row in evaluations
        ],
        "evidence": {
            "workflow_run_id": WORKFLOW_RUN_ID,
            "artifact_id": ARTIFACT_ID,
            "artifact_digest": ARTIFACT_DIGEST,
            "contract_path": "configs/models/cn_x1_1.yaml",
            "notebook_path": "notebooks/models/cn_x1_1_complete_backtest.ipynb",
            "candidate_evidence_root": (
                "data/research/cn_x1_1_regime_gated_candidate_v1"
            ),
            "candidate_authorization_pr": 576,
            "candidate_validation_pr": 574,
            "sector_breadth_pr": 572,
            "provider_identity": "sha256:" + str(manifest["provider_identity_sha256"]),
            "provider_cutoff": manifest["provider_cutoff"],
            "universe_sha256": manifest["universe_sha256"],
            "classification_sha256": manifest["classification_sha256"],
            "frozen_economic_identity_verified": True,
            "all_gate_checks_passed": all(
                bool(value) for value in verified["decision"]["gates"].values()
            ),
            "row_counts": {
                "rebalance_periods": len(periods),
                "positions": len(positions),
                "trades": len(trades),
                "attribution_rows": len(attribution),
            },
        },
        "evidence_completeness": {
            "status": "complete",
            "performance_trace": "retained_exact_non_overlapping_10_session_trace",
            "holdings": "retained_exact_all_rebalance_targets",
            "trades": "derived_exact_from_consecutive_retained_target_weights",
            "attribution": "retained_exact_net_security_contributions_and_derived_sector_sums",
            "risk_states": "retained_exact_all_rebalance_decisions_and_votes",
            "missing": [],
        },
        "freshness": {
            "schema_version": "1.0.0",
            "status": "current",
            "required_cutoff": EVIDENCE_CUTOFF,
            "latest_completed_session": EVIDENCE_CUTOFF,
            "latest_realized_holding_end": LATEST_REALIZED_END,
            "partial_final_window": "2026H2_PARTIAL",
            "model_selection_reopened": False,
        },
        "interpretation_notes": [
            "CN x1.1 is the user-directed formal successor to CN x1.0.",
            "The active score remains the frozen CN x1.0 R0 score; CN x1.1 changes portfolio construction and adds a fully PIT regime gate.",
            "Risk-off periods intentionally hold CSI300; benchmark tracking after costs is evaluated with a fallback-aware contract.",
            "Historical model-selection evidence ends at 2025-12-31; 2026 is reporting-only and did not alter the frozen rule.",
            "The provider is certified through 2026-08-03; the latest realized ten-session holding ends 2026-07-29.",
            "Research evidence only; not authorization for live or automated trading.",
        ],
    }
    return package


def update_catalog(root: Path, package_sha: str, *, generated_at: str) -> None:
    catalog_path = root / "catalog.json"
    catalog = _json(catalog_path)
    records = catalog.get("records")
    if not isinstance(records, list):
        raise PromotionError("formal catalog records are missing")
    retained = [
        row
        for row in records
        if isinstance(row, dict) and row.get("model_id") not in {"cn_x1_0", MODEL_ID}
    ]
    retained.append(
        {
            "display_name": DISPLAY_NAME,
            "display_order": 3,
            "model_id": MODEL_ID,
            "path": f"{MODEL_ID}.json",
            "publication_status": "accepted_formal_baseline",
            "sha256": package_sha,
        }
    )
    retained.sort(key=lambda row: (int(row["display_order"]), str(row["model_id"])))
    catalog["published_at"] = generated_at
    catalog["records"] = retained
    _write_json(catalog_path, catalog)


def update_freshness(root: Path, *, generated_at: str) -> None:
    path = root / "freshness.json"
    payload = _json(path)
    for key in (
        "required_models",
        "freshness_receipt_required_models",
        "date_range_end_required_models",
    ):
        values = payload.get(key)
        if not isinstance(values, list):
            raise PromotionError(f"freshness {key} is missing")
        payload[key] = [MODEL_ID if value == "cn_x1_0" else value for value in values]
    payload["declared_at"] = generated_at
    _write_json(path, payload)


def promote(
    root: Path,
    evidence_root: Path,
    *,
    generated_at: str = GENERATED_AT,
    receipt: Path | None = None,
) -> dict[str, Any]:
    package = build_package(evidence_root, generated_at=generated_at)
    package_path = root / f"{MODEL_ID}.json"
    package_sha = _write_json(package_path, package)
    update_catalog(root, package_sha, generated_at=generated_at)
    update_freshness(root, generated_at=generated_at)
    result = {
        "schema_version": "1.0.0",
        "status": "cn_x1_1_formal_promotion_reproduced",
        "model_id": MODEL_ID,
        "package": str(package_path),
        "package_sha256": package_sha,
        "evidence_cutoff": EVIDENCE_CUTOFF,
        "workflow_run_id": WORKFLOW_RUN_ID,
        "artifact_id": ARTIFACT_ID,
        "artifact_digest": ARTIFACT_DIGEST,
        "research_only": True,
        "trade_ready": False,
    }
    if receipt is not None:
        _write_json(receipt, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("data/research/formal_backtests"),
    )
    parser.add_argument(
        "--evidence-root",
        type=Path,
        default=Path("data/research/cn_x1_1_regime_gated_candidate_v1"),
    )
    parser.add_argument("--generated-at", default=GENERATED_AT)
    parser.add_argument("--receipt", type=Path, default=None)
    args = parser.parse_args()
    result = promote(
        args.root,
        args.evidence_root,
        generated_at=args.generated_at,
        receipt=args.receipt,
    )
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
