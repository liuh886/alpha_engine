#!/usr/bin/env python3
"""Materialize the complete CN x1.2 preview and formal Bundle v2 evidence.

The row-level input is emitted by the frozen #954 development replay.  This
publisher verifies it against the portable rejected-experiment receipt and the
user-directed promotion receipt before deriving the frontend performance,
portfolio, trades, and attribution sections.  It never changes the failed gate
or consumes the reserved 2026H2 holdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from src.artifacts.formal_evidence_standard import validate_formal_evidence_bundle
from src.artifacts.formal_preview_builder import build_preview_bundle
from src.artifacts.model_run_bundle_v2 import canonical_json_bytes
from src.artifacts.model_run_exporter import update_catalog
from src.artifacts.native_formal_promotion import promote_preview_bundle
from src.governance.active_strategy_catalog import (
    DEFAULT_CATALOG_PATH,
    ActiveStrategy,
    load_active_strategy_catalog,
)


MODEL_ID = "cn_x1_2"
CANDIDATE_ID = "cn_x1_2_alpha158_breadth_scaled"
EXPERIMENT_ID = "cn_x1_2_alpha158_breadth_scaled_v1"
FAILED_GATE = "2026h1_drawdown_worsening_within_3pp"
BACKTEST_ID = "cn_x1_2-through-2026_06_30"
GENERATED_AT = "2026-08-14T14:00:00Z"
EVIDENCE_CUTOFF = "2026-06-30"
LATEST_REALIZED_HOLDING_END = "2026-06-23"


class CnX12EvidenceError(ValueError):
    """Raised when CN x1.2 evidence cannot be published without invention."""


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CnX12EvidenceError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise CnX12EvidenceError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_list(value: object, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise CnX12EvidenceError(f"{label} must be a list of objects")
    return value


def _same_numbers(left: Mapping[str, Any], right: Mapping[str, Any], *, label: str) -> None:
    if set(left) != set(right):
        raise CnX12EvidenceError(f"{label} keys drifted")
    for key in left:
        lvalue = left[key]
        rvalue = right[key]
        if isinstance(lvalue, (int, float)) and isinstance(rvalue, (int, float)):
            if abs(float(lvalue) - float(rvalue)) > 1e-12:
                raise CnX12EvidenceError(f"{label}.{key} drifted")
        elif lvalue != rvalue:
            raise CnX12EvidenceError(f"{label}.{key} drifted")


def _verify_inputs(
    portfolio_path: Path,
    experiment_path: Path,
    promotion_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    portfolio = _object(portfolio_path)
    experiment = _object(experiment_path)
    promotion = _object(promotion_path)
    if (
        portfolio.get("schema_version") != "1.0.0"
        or portfolio.get("record_type") != "cn_x1_2_challenger_portfolio_evidence"
        or portfolio.get("experiment_id") != EXPERIMENT_ID
        or portfolio.get("candidate_id") != CANDIDATE_ID
        or portfolio.get("no_2026h2_evidence_consumed") is not True
        or portfolio.get("research_only") is not True
        or portfolio.get("trade_ready") is not False
    ):
        raise CnX12EvidenceError("row-level portfolio evidence boundary drifted")
    if (
        experiment.get("experiment_id") != EXPERIMENT_ID
        or experiment.get("decision")
        != "cn_x1_2_alpha158_breadth_scaled_development_rejected"
        or experiment.get("no_2026h2_evidence_consumed") is not True
        or experiment.get("research_only") is not True
        or experiment.get("trade_ready") is not False
    ):
        raise CnX12EvidenceError("portable experiment receipt boundary drifted")
    boundary = experiment.get("development_boundary")
    checks = boundary.get("checks") if isinstance(boundary, Mapping) else None
    failed = sorted(key for key, passed in (checks or {}).items() if passed is not True)
    if boundary.get("supported") is not False or failed != [FAILED_GATE]:
        raise CnX12EvidenceError("failed preregistered gate must remain explicit")
    if (
        promotion.get("model_id") != MODEL_ID
        or promotion.get("decision") != "promoted_by_explicit_user_governance_exception"
        or promotion.get("research_only") is not True
        or promotion.get("trade_ready") is not False
    ):
        raise CnX12EvidenceError("user-directed promotion boundary drifted")
    promoted_rows = promotion.get("portfolio_evidence")
    if (
        not isinstance(promoted_rows, Mapping)
        or promoted_rows.get("sha256") != _sha256(portfolio_path)
        or promoted_rows.get("cost_paths_bps") != [20, 60]
    ):
        raise CnX12EvidenceError("row-level portfolio evidence hash is not promotion-bound")

    selected = experiment.get("selected_candidate")
    cost_paths = portfolio.get("cost_paths")
    if not isinstance(selected, Mapping) or not isinstance(cost_paths, Mapping):
        raise CnX12EvidenceError("selected candidate or cost paths are missing")
    base = cost_paths.get("20")
    stress = cost_paths.get("60")
    if not isinstance(base, Mapping) or not isinstance(stress, Mapping):
        raise CnX12EvidenceError("both 20bps and 60bps row-level paths are required")
    for label, path, summary_key in (
        ("20bps", base, "base_20bps"),
        ("60bps", stress, "stress_60bps"),
    ):
        summary = path.get("summary")
        expected = selected.get(summary_key)
        if not isinstance(summary, Mapping) or not isinstance(expected, Mapping):
            raise CnX12EvidenceError(f"{label} summary is missing")
        _same_numbers(summary, expected, label=label)
        periods = _require_list(path.get("periods"), f"{label}.periods")
        holdings = _require_list(path.get("holdings"), f"{label}.holdings")
        if not periods or not holdings:
            raise CnX12EvidenceError(f"{label} row-level evidence is empty")
        if any(str(row.get("datetime") or "") > EVIDENCE_CUTOFF for row in periods):
            raise CnX12EvidenceError(f"{label} consumed evidence after 2026H1")
        reproduced = experiment.get("portfolio_reproduction", {}).get(
            "20" if label == "20bps" else "60"
        )
        if not isinstance(reproduced, Mapping):
            raise CnX12EvidenceError(f"{label} reproduction evidence is missing")
        if (
            path.get("periods_sha256") != reproduced.get("first_periods")
            or path.get("holdings_sha256") != reproduced.get("first_holdings")
            or reproduced.get("first_periods") != reproduced.get("second_periods")
            or reproduced.get("first_holdings") != reproduced.get("second_holdings")
        ):
            raise CnX12EvidenceError(f"{label} row evidence/reproduction hash mismatch")
    return portfolio, experiment, promotion, dict(base)


def _risk_state(period: Mapping[str, Any]) -> str:
    if period.get("risk_on") is True:
        return "risk_on_breadth_scaled"
    return "risk_off_csi300_fallback"


def _action(previous: float, target: float) -> str:
    if previous == 0.0 and target > 0.0:
        return "BUY"
    if previous > 0.0 and target == 0.0:
        return "SELL"
    return "INCREASE" if target > previous else "DECREASE"


def build_package(
    portfolio_path: Path,
    experiment_path: Path,
    promotion_path: Path,
    *,
    generated_at: str = GENERATED_AT,
) -> dict[str, Any]:
    portfolio, experiment, promotion, base = _verify_inputs(
        portfolio_path, experiment_path, promotion_path
    )
    periods = _require_list(base["periods"], "20bps.periods")
    holdings = _require_list(base["holdings"], "20bps.holdings")
    selected = dict(experiment["selected_candidate"])
    per_window = dict(experiment["per_window_metrics"])

    holdings_by_date: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in holdings:
        holdings_by_date[str(row["datetime"])].append(row)

    report: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    instrument_attribution: dict[tuple[str, str, str], dict[str, Any]] = {}
    sector_attribution: dict[str, dict[str, Any]] = {}
    previous_weights: dict[str, float] = {}
    account = benchmark_account = peak = 1.0
    max_drawdown = total_turnover = total_cost = 0.0

    for period_index, period in enumerate(periods):
        date = str(period["datetime"])
        net_return = float(period["net_return"])
        benchmark_return = float(period["benchmark_return"])
        account_before = account
        benchmark_before = benchmark_account
        account *= 1.0 + net_return
        benchmark_account *= 1.0 + benchmark_return
        peak = max(peak, account)
        drawdown = account / peak - 1.0
        max_drawdown = min(max_drawdown, drawdown)
        total_turnover += float(period["turnover"])
        total_cost += float(period["cost"])
        state = _risk_state(period)
        rows = holdings_by_date.get(date, [])
        if not rows:
            raise CnX12EvidenceError(f"no retained holdings for {date}")
        current_weights = {str(row["instrument"]): float(row["weight"]) for row in rows}
        if abs(sum(current_weights.values()) - 1.0) > 1e-9:
            raise CnX12EvidenceError(f"retained weights do not sum to one on {date}")

        report.append(
            {
                "date": date,
                "account_before": account_before,
                "account": account,
                "bench_hs300_before": benchmark_before,
                "bench_hs300": benchmark_account,
                "period_return": net_return,
                "gross_return": float(period["gross_return"]),
                "benchmark_return": benchmark_return,
                "excess_return": net_return - benchmark_return,
                "relative_log_return": float(period["relative_log_return"]),
                "turnover": float(period["turnover"]),
                "transaction_cost": float(period["cost"]),
                "drawdown": drawdown,
                "window": str(period["window"]),
                "risk_on": bool(period["risk_on"]),
                "risk_on_eligible": bool(period["risk_on_eligible"]),
                "risk_state": state,
                "votes": int(period["votes"]),
                "long_trend": bool(period["long_trend"]),
                "medium_momentum": bool(period["medium_momentum"]),
                "cross_sectional_breadth": bool(period["cross_sectional_breadth"]),
                "breadth_value": float(period["breadth_value"]),
                "active_share": float(period["active_share"]),
                "benchmark_sleeve": float(period["benchmark_sleeve"]),
                "benchmark_hit": bool(period["benchmark_hit"]),
                "trace_frequency": "non_overlapping_10_session",
            }
        )

        for row in rows:
            instrument = str(row["instrument"])
            entity = str(row["entity"])
            sector = str(row["sector"])
            contribution = float(row["net_contribution"])
            positions.append(
                {
                    "date": date,
                    "instrument": instrument,
                    "name": entity,
                    "sector": sector,
                    "weight": float(row["weight"]),
                    "score": row.get("score"),
                    "raw_return": float(row["raw_return"]),
                    "benchmark_return": float(row["benchmark_return"]),
                    "net_contribution": contribution,
                    "precision_hit": bool(row["precision_hit"]),
                    "window": str(row["window"]),
                    "risk_state": state,
                    "active_share": float(period["active_share"]),
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
                    "attribution_level": "instrument",
                },
            )
            item["value"] += contribution
            item["periods_held"] += 1
            item["risk_on_periods"] += int(period["risk_on"] is True)
            item["risk_off_periods"] += int(period["risk_on"] is not True)
            sector_item = sector_attribution.setdefault(
                sector,
                {
                    "instrument": f"sector:{sector}",
                    "name": sector,
                    "sector": sector,
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
        current_by_instrument = {str(row["instrument"]): row for row in rows}
        for instrument in all_instruments:
            previous = previous_weights.get(instrument, 0.0)
            target = current_weights.get(instrument, 0.0)
            delta = target - previous
            if abs(delta) <= 1e-12:
                continue
            source = current_by_instrument.get(instrument)
            trades.append(
                {
                    "date": date,
                    "instrument": instrument,
                    "action": _action(previous, target),
                    "previous_weight": previous,
                    "target_weight": target,
                    "weight_delta": delta,
                    "transaction_cost": (
                        float(period["cost"]) * changed[instrument] / changed_total
                        if changed_total
                        else 0.0
                    ),
                    "reason": "breadth_scaled_regime_rebalance",
                    "risk_state": state,
                    "window": str(period["window"]),
                    "entity": source.get("entity") if source else None,
                    "sector": source.get("sector") if source else None,
                    "period_index": period_index,
                }
            )
        previous_weights = current_weights

    window_summary: list[dict[str, Any]] = []
    for window in experiment["development_windows"]:
        base_row = dict(per_window[CANDIDATE_ID]["20"][window])
        stress_row = dict(per_window[CANDIDATE_ID]["60"][window])
        incumbent_row = dict(per_window["baseline_cn_x1_1"]["20"][window])
        base_row.update(
            {
                "cost_bps": 20,
                "stress_cost_bps": 60,
                "stress_total_return": stress_row["total_return"],
                "stress_relative_excess": stress_row["relative_excess"],
                "stress_max_drawdown": stress_row["max_drawdown"],
                "incumbent_relative_excess": incumbent_row["relative_excess"],
                "incumbent_max_drawdown": incumbent_row["max_drawdown"],
                "relative_excess_delta_vs_incumbent": (
                    float(base_row["relative_excess"])
                    - float(incumbent_row["relative_excess"])
                ),
                "preregistered_drawdown_gate_passed": (
                    window != "2026H1"
                    or experiment["development_boundary"]["checks"][FAILED_GATE] is True
                ),
            }
        )
        window_summary.append(base_row)

    attribution = list(instrument_attribution.values()) + list(sector_attribution.values())
    attribution.sort(key=lambda row: abs(float(row["value"])), reverse=True)
    base_summary = dict(selected["base_20bps"])
    package = {
        "schema_version": "1.0.0",
        "record_type": "formal_model_backtest",
        "backtest_id": BACKTEST_ID,
        "model_id": MODEL_ID,
        "display_name": "CN x1.2",
        "market": "cn",
        "benchmark": "000300",
        "publication_status": "accepted_formal_baseline",
        "generated_at": generated_at,
        "evidence_cutoff": EVIDENCE_CUTOFF,
        "research_only": True,
        "trade_ready": False,
        "trace_frequency": "non_overlapping_10_session",
        "date_range": {"start": str(periods[0]["datetime"]), "end": EVIDENCE_CUTOFF},
        "metrics": {
            "Total Return": account - 1.0,
            "Benchmark Return": benchmark_account - 1.0,
            "Compounded Relative Excess Return": account / benchmark_account - 1.0,
            "Max Drawdown": max_drawdown,
            "Turnover": total_turnover,
            "Transaction Cost": total_cost,
            "Mean Rank IC": float(selected["mean_rank_ic"]),
            "Mean ICIR": float(selected["mean_icir"]),
            "Risk-On Share": float(base_summary["risk_on_share"]),
            "Risk-On Active Hit Rate": float(base_summary["risk_on_active_hit_rate"]),
            "Stress 60bps Relative Excess": float(
                selected["stress_60bps"]["relative_excess"]
            ),
        },
        "portfolio_contract": {
            "universe": "cn_selected_equities_v3",
            "universe_size": 130,
            "candidate": CANDIDATE_ID,
            "signal": "frozen_17_factor_xgboost_rank_ndcg",
            "selected_sectors": 4,
            "names_per_sector": 1,
            "risk_on_weighting": "equal_weight_across_four_names",
            "regime_rule": "two_of_three",
            "active_exposure": "clamp(cross_sectional_breadth / 0.50, 0, 1)",
            "benchmark_sleeve": "one_minus_active_exposure_in_CSI300",
            "risk_off_fallback": "100_percent_CSI300",
            "horizon_sessions": 10,
            "holding_sessions": 10,
            "rebalance_sessions": 10,
            "execution_delay_sessions": 1,
            "cost_bps": 20,
            "stress_cost_bps": 60,
        },
        "report": report,
        "positions": positions,
        "trades": trades,
        "attribution": attribution,
        "window_summary": window_summary,
        "evidence": {
            "experiment_receipt": experiment_path.as_posix(),
            "experiment_receipt_sha256": _sha256(experiment_path),
            "portfolio_evidence": portfolio_path.as_posix(),
            "portfolio_evidence_sha256": _sha256(portfolio_path),
            "promotion_receipt": promotion_path.as_posix(),
            "promotion_receipt_sha256": _sha256(promotion_path),
            "provider_identity_sha256": experiment["observed_provider_identity_sha256"],
            "classification_sha256": experiment["sector_classification_sha256"],
            "exact_score_reproduction": True,
            "exact_portfolio_reproduction": True,
            "preregistered_gates_supported": False,
            "failed_gate": FAILED_GATE,
            "promotion_authority": promotion["promotion_authority"],
            "no_2026h2_evidence_consumed": True,
            "row_counts": {
                "rebalance_periods": len(report),
                "positions": len(positions),
                "trades": len(trades),
                "attribution_rows": len(attribution),
            },
        },
        "evidence_completeness": {
            "status": "complete",
            "performance_trace": "retained_exact_non_overlapping_10_session_trace",
            "holdings": "retained_exact_all_rebalance_targets_including_CSI300_sleeve",
            "trades": "derived_exact_from_consecutive_retained_target_weights",
            "attribution": "retained_exact_net_security_contributions_and_derived_sector_sums",
            "risk_states": "retained_exact_votes_active_share_and_benchmark_sleeve",
            "robustness": "retained_exact_20bps_and_60bps_five_window_results",
            "missing": [],
        },
        "freshness": {
            "schema_version": "1.0.0",
            "status": "frozen_development_evidence",
            "required_cutoff": EVIDENCE_CUTOFF,
            "latest_completed_session": EVIDENCE_CUTOFF,
            "latest_realized_holding_end": LATEST_REALIZED_HOLDING_END,
            "reserved_holdout_start": "2026-07-01",
            "model_selection_reopened": False,
        },
        "interpretation_notes": [
            "CN x1.2 is the user-directed research-baseline successor to CN x1.1.",
            "The preregistered experiment remains rejected because the 2026H1 drawdown-worsening gate failed; this bundle does not relabel it as passed.",
            "The performance, holdings, trades, attribution, risk-state, active-share, and 60bps stress evidence are bound to the exact reproduced #954 row-level frames.",
            "Evidence ends at 2026-06-30 and no 2026H2 holdout evidence was consumed.",
            "Research evidence only; not authorization for live or automated trading.",
        ],
    }
    _same_numbers(
        {
            "total_return": package["metrics"]["Total Return"],
            "benchmark_return": package["metrics"]["Benchmark Return"],
            "relative_excess": package["metrics"]["Compounded Relative Excess Return"],
            "max_drawdown": package["metrics"]["Max Drawdown"],
            "turnover": package["metrics"]["Turnover"],
        },
        {
            key: base_summary[key]
            for key in (
                "total_return",
                "benchmark_return",
                "relative_excess",
                "max_drawdown",
                "turnover",
            )
        },
        label="derived package summary",
    )
    return package


def _strategy(path: Path) -> ActiveStrategy:
    catalog = load_active_strategy_catalog(path)
    strategy = catalog.by_model_version_id.get(MODEL_ID)
    if strategy is None:
        raise CnX12EvidenceError("CN x1.2 is not the active CN strategy")
    return strategy


def _retained_active_manifests(
    root: Path,
    catalog_path: Path,
    strategy_catalog_path: Path,
    replacement: Path,
) -> list[Path]:
    active = load_active_strategy_catalog(strategy_catalog_path)
    catalog = _object(catalog_path)
    rows = catalog.get("records")
    if not isinstance(rows, list):
        raise CnX12EvidenceError(f"bundle catalog records are missing: {catalog_path}")
    by_model = {
        str(row.get("model_version_id") or ""): row
        for row in rows
        if isinstance(row, Mapping)
    }
    manifests = [replacement]
    for model_id in active.active_model_version_ids:
        if model_id == MODEL_ID:
            continue
        row = by_model.get(model_id)
        if not isinstance(row, Mapping):
            raise CnX12EvidenceError(f"active bundle is missing for {model_id}")
        manifest = root / str(row.get("manifest_path") or "")
        if not manifest.is_file():
            raise CnX12EvidenceError(f"active manifest is missing: {manifest}")
        manifests.append(manifest)
    return manifests


def _advance_freshness_policy(formal_root: Path) -> None:
    path = formal_root / "freshness.json"
    policy = _object(path)
    for key in (
        "required_models",
        "date_range_end_required_models",
        "freshness_receipt_required_models",
    ):
        values = policy.get(key)
        if not isinstance(values, list):
            raise CnX12EvidenceError(f"freshness policy field is missing: {key}")
        advanced: list[str] = []
        for value in values:
            model_id = MODEL_ID if value == "cn_x1_1" else str(value)
            if model_id not in advanced:
                advanced.append(model_id)
        policy[key] = advanced
    path.write_bytes(canonical_json_bytes(policy))


def materialize(
    portfolio_path: Path,
    experiment_path: Path,
    promotion_path: Path,
    source_output: Path,
    preview_root: Path,
    formal_root: Path,
    strategy_catalog_path: Path,
    *,
    update_catalogs: bool,
) -> dict[str, Any]:
    package = build_package(portfolio_path, experiment_path, promotion_path)
    source_output.parent.mkdir(parents=True, exist_ok=True)
    source_output.write_bytes(canonical_json_bytes(package))
    strategy = _strategy(strategy_catalog_path)
    preview_root = preview_root.resolve()
    formal_root = formal_root.resolve()
    preview_manifest = build_preview_bundle(
        source_output, strategy, output_root=preview_root
    )
    formal_manifest = promote_preview_bundle(
        preview_manifest.parent, formal_root, strategy
    )
    validate_formal_evidence_bundle(formal_manifest.parent)
    if update_catalogs:
        preview_catalog = preview_root / "catalog.json"
        formal_catalog = formal_root / "catalog.json"
        update_catalog(
            _retained_active_manifests(
                preview_root,
                preview_catalog,
                strategy_catalog_path,
                preview_manifest,
            ),
            catalog_path=preview_catalog,
            channel="preview",
        )
        update_catalog(
            _retained_active_manifests(
                formal_root,
                formal_catalog,
                strategy_catalog_path,
                formal_manifest,
            ),
            catalog_path=formal_catalog,
            channel="formal",
        )
        _advance_freshness_policy(formal_root)
    return {
        "schema_version": "1.0.0",
        "status": "cn_x1_2_complete_bundle_materialized",
        "source_path": source_output.as_posix(),
        "source_sha256": _sha256(source_output),
        "preview_manifest": preview_manifest.as_posix(),
        "preview_manifest_sha256": _sha256(preview_manifest),
        "formal_manifest": formal_manifest.as_posix(),
        "formal_manifest_sha256": _sha256(formal_manifest),
        "catalogs_updated": update_catalogs,
        "preregistered_gates_supported": False,
        "failed_gate": FAILED_GATE,
        "no_2026h2_evidence_consumed": True,
        "research_only": True,
        "trade_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--portfolio-evidence",
        type=Path,
        default=Path(
            "data/research/cn_x1_2_alpha158_breadth_scaled_v1/"
            "challenger_portfolio_evidence.json"
        ),
    )
    parser.add_argument(
        "--experiment-receipt",
        type=Path,
        default=Path(
            "data/research/experiment_receipts/"
            "cn_x1_2_alpha158_breadth_scaled_v1.json"
        ),
    )
    parser.add_argument(
        "--promotion-receipt",
        type=Path,
        default=Path(
            "data/research/experiment_receipts/"
            "cn_x1_2_user_directed_promotion_v1.json"
        ),
    )
    parser.add_argument(
        "--source-output",
        type=Path,
        default=Path(
            "data/research/historical_model_evidence/"
            "cn_x1_2_alpha158_breadth_scaled_v1.json"
        ),
    )
    parser.add_argument("--preview-root", type=Path, default=Path("data/research/model_runs"))
    parser.add_argument(
        "--formal-root", type=Path, default=Path("data/research/formal_model_runs")
    )
    parser.add_argument(
        "--strategy-catalog", type=Path, default=DEFAULT_CATALOG_PATH
    )
    parser.add_argument(
        "--no-update-catalogs",
        action="store_true",
        help="Build the CN bundle without changing the shared preview/formal catalogs.",
    )
    args = parser.parse_args()
    receipt = materialize(
        args.portfolio_evidence,
        args.experiment_receipt,
        args.promotion_receipt,
        args.source_output,
        args.preview_root,
        args.formal_root,
        args.strategy_catalog,
        update_catalogs=not args.no_update_catalogs,
    )
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
