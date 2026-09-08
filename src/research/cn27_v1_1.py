"""Evidence builder for the sealed CN_27 V1.1 risk-adjusted momentum candidate."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from src.research.all_weather_alpha_rotation import (
    AllWeatherBacktestResult,
    _return_metrics,
    canonical_sha256,
    evaluate_byd_v1_3_challenge,
    load_all_weather_contract,
    normalise_long_bars,
    sha256_file,
)
from src.research.cn27_sharpe_discovery import (
    CN27DiscoveryContract,
    compute_discovery_features,
    load_discovery_contract,
    run_discovery_recipe,
    write_json,
)


@dataclass(frozen=True)
class CN27V11Contract:
    spec: dict[str, Any]
    spec_path: Path
    discovery: CN27DiscoveryContract
    selected_recipe: dict[str, Any]
    root: Path


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected YAML mapping: {path}")
    return payload


def _verify_manifest(path: Path, *, expected_identity: str | None = None) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    body = dict(payload)
    identity = str(body.pop("manifest_identity_sha256", ""))
    if canonical_sha256(body) != identity:
        raise ValueError(f"manifest identity mismatch: {path}")
    if expected_identity is not None and identity != expected_identity:
        raise ValueError(f"unexpected manifest identity: {path}")
    for name, expected in payload.get("outputs", {}).items():
        if sha256_file(path.parent / name) != expected:
            raise ValueError(f"manifest output hash mismatch: {name}")
    return payload


def load_cn27_v1_1_contract(path: str | Path) -> CN27V11Contract:
    spec_path = Path(path).resolve()
    root = spec_path.parents[2]
    spec = _load_yaml(spec_path)
    if spec.get("status") != "frozen_retrospective_candidate":
        raise ValueError("CN_27 V1.1 contract must be frozen")
    if spec.get("research_only") is not True or spec.get("trade_ready") is not False:
        raise ValueError("CN_27 V1.1 must remain research-only")
    lineage = spec["lineage"]
    discovery_path = (root / str(lineage["discovery_experiment"])).resolve()
    if sha256_file(discovery_path) != str(lineage["discovery_experiment_sha256"]):
        raise ValueError("CN_27 V1.1 discovery contract hash mismatch")
    discovery = load_discovery_contract(discovery_path)
    identity = spec["identity"]
    if sha256_file(discovery.pool_path) != str(identity["pool_sha256"]):
        raise ValueError("CN_27 V1.1 pool hash mismatch")
    if sha256_file(discovery.prices_path) != str(identity["source_prices_sha256"]):
        raise ValueError("CN_27 V1.1 source price hash mismatch")

    screen_path = (root / str(lineage["sealed_screen_manifest"])).resolve()
    if sha256_file(screen_path) != str(lineage["sealed_screen_manifest_file_sha256"]):
        raise ValueError("CN_27 V1.1 screen manifest file hash mismatch")
    screen_manifest = _verify_manifest(screen_path)
    selection = json.loads((screen_path.parent / "selection.json").read_text(encoding="utf-8"))
    if selection["selection_identity_sha256"] != str(
        lineage["sealed_selection_identity_sha256"]
    ):
        raise ValueError("CN_27 V1.1 selection identity mismatch")
    if screen_manifest["selection_identity_sha256"] != selection["selection_identity_sha256"]:
        raise ValueError("CN_27 V1.1 selection is not bound by screen manifest")

    holdout_path = (root / str(lineage["holdout_manifest"])).resolve()
    if sha256_file(holdout_path) != str(lineage["holdout_manifest_file_sha256"]):
        raise ValueError("CN_27 V1.1 holdout manifest file hash mismatch")
    _verify_manifest(
        holdout_path,
        expected_identity=str(lineage["holdout_manifest_identity_sha256"]),
    )
    recipe = dict(selection["selected_recipe"])
    model_factors = {str(k): float(v) for k, v in spec["factor_model"]["combination"].items()}
    if recipe["factors"] != model_factors:
        raise ValueError("CN_27 V1.1 factor combination differs from sealed selection")
    for field in (
        "rebalance_sessions",
        "top_k",
        "exit_rank_buffer",
        "maximum_names_per_sector",
        "weighting",
        "absolute_momentum_filter",
    ):
        if recipe[field] != spec["portfolio"][field]:
            raise ValueError(f"CN_27 V1.1 portfolio field differs from selection: {field}")
    return CN27V11Contract(
        spec=spec,
        spec_path=spec_path,
        discovery=discovery,
        selected_recipe=recipe,
        root=root,
    )


def _metrics_for_range(
    daily: pd.DataFrame,
    *,
    start: str,
    end: str,
) -> dict[str, Any]:
    sample = daily.loc[start:end]
    metrics = _return_metrics(
        sample["net_return"],
        annual_sessions=252,
        annual_risk_free_rate=0.02,
    )
    metrics["annual_one_way_turnover"] = float(
        sample["one_way_turnover"].sum() / (len(sample) / 252.0)
    )
    metrics["transaction_cost_paid"] = float(sample["transaction_cost"].sum())
    metrics["average_equity_exposure"] = float(sample["equity_exposure"].mean())
    metrics["average_holding_count"] = float(sample["holding_count"].mean())
    return metrics


def contribution_attribution(
    daily: pd.DataFrame,
    bars: pd.DataFrame,
    contract: CN27V11Contract,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Reconcile daily gross returns to beginning weights and open-to-open returns."""

    clean = normalise_long_bars(bars)
    calendar = pd.DatetimeIndex(daily.index)
    assets = (*contract.discovery.candidate_symbols, contract.discovery.defensive_symbol)
    open_returns = {
        symbol: clean.loc[clean["symbol"].eq(symbol)].set_index("date")["open"]
        .reindex(calendar)
        .ffill()
        .pct_change(fill_method=None)
        .fillna(0.0)
        for symbol in assets
    }
    sector_by_symbol = {
        str(row["symbol"]).zfill(6): str(row["sector"])
        for row in contract.discovery.pool["symbols"]
    }
    rows: list[dict[str, Any]] = []
    for date, daily_row in daily.iterrows():
        return_weights = json.loads(str(daily_row["return_weights"]))
        for symbol, weight in return_weights.items():
            contribution = float(weight) * float(open_returns[symbol].loc[date])
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "sector": sector_by_symbol.get(symbol, "defensive_etf"),
                    "return_weight": float(weight),
                    "open_return": float(open_returns[symbol].loc[date]),
                    "gross_contribution": contribution,
                }
            )
    attribution = pd.DataFrame(rows)
    reconciled = attribution.groupby("date")["gross_contribution"].sum().reindex(calendar).fillna(0.0)
    difference = reconciled - daily["gross_return"]
    if float(difference.abs().max()) > 1e-10:
        raise ValueError("CN_27 V1.1 contribution attribution does not reconcile")
    stocks = attribution.loc[attribution["symbol"].isin(contract.discovery.candidate_symbols)]
    name_positive = stocks.groupby("symbol")["gross_contribution"].sum().clip(lower=0.0)
    sector_positive = stocks.groupby("sector")["gross_contribution"].sum().clip(lower=0.0)
    name_total = float(name_positive.sum())
    sector_total = float(sector_positive.sum())
    summary = {
        "maximum_single_name_positive_contribution_share": (
            float(name_positive.max() / name_total) if name_total > 1e-12 else None
        ),
        "maximum_single_sector_positive_contribution_share": (
            float(sector_positive.max() / sector_total) if sector_total > 1e-12 else None
        ),
        "largest_positive_name": str(name_positive.idxmax()) if name_total > 1e-12 else None,
        "largest_positive_sector": (
            str(sector_positive.idxmax()) if sector_total > 1e-12 else None
        ),
        "maximum_daily_reconciliation_error": float(difference.abs().max()),
    }
    return attribution, summary


def _load_predecessor_daily(contract: CN27V11Contract) -> tuple[pd.DataFrame, str]:
    identity = contract.discovery.spec["identity"]
    manifest_path = (contract.root / str(identity["cn_27_v1_0_manifest"])).resolve()
    if sha256_file(manifest_path) != str(identity["cn_27_v1_0_manifest_file_sha256"]):
        raise ValueError("CN_27 V1.0 predecessor manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    daily_path = manifest_path.parent / "daily.csv"
    if sha256_file(daily_path) != manifest["outputs"]["daily.csv"]:
        raise ValueError("CN_27 V1.0 predecessor daily hash mismatch")
    return pd.read_csv(daily_path, parse_dates=["date"]).set_index("date"), sha256_file(
        daily_path
    )


def _selected_factor_stability(contract: CN27V11Contract) -> dict[str, Any]:
    screen_path = (contract.root / str(contract.spec["lineage"]["sealed_screen_manifest"])).resolve()
    diagnostics = pd.read_csv(screen_path.parent / "factor_diagnostics.csv")
    factor_ids = list(contract.selected_recipe["factors"])
    selected = diagnostics.loc[diagnostics["factor_id"].isin(factor_ids)].copy()
    pivot = selected.pivot(index="factor_id", columns="window", values="mean_rank_ic")
    pivot["same_direction"] = np.sign(pivot["development"]) == np.sign(
        pivot["selection_validation"]
    )
    return {
        "selected_factor_count": len(factor_ids),
        "same_direction_factor_count": int(pivot["same_direction"].sum()),
        "same_direction_share": float(pivot["same_direction"].mean()),
        "factors": pivot.reset_index().to_dict(orient="records"),
    }


def run_cn27_v1_1_evidence(
    contract_path: str | Path,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Run and materialize the frozen CN_27 V1.1 candidate without further selection."""

    contract = load_cn27_v1_1_contract(contract_path)
    bars = pd.read_csv(
        contract.discovery.prices_path,
        dtype={"symbol": str},
        parse_dates=["date"],
    )
    features = compute_discovery_features(bars, contract.discovery)
    end = str(contract.spec["evaluation"]["full_window"]["end"])
    windows = ("development", "selection_validation", "locked_test")
    primary = run_discovery_recipe(
        bars,
        features,
        contract.discovery,
        contract.selected_recipe,
        end_date=end,
        window_names=windows,
    )
    stress = run_discovery_recipe(
        bars,
        features,
        contract.discovery,
        contract.selected_recipe,
        end_date=end,
        window_names=windows,
        cost_multiplier=float(contract.spec["costs"]["stress_multiplier"]),
    )
    full_window = contract.spec["evaluation"]["full_window"]
    if len(primary.daily) != int(full_window["sessions"]):
        raise ValueError("CN_27 V1.1 full-window session mismatch")
    full_metrics = _metrics_for_range(
        primary.daily,
        start=str(full_window["start"]),
        end=str(full_window["end"]),
    )
    stress_full_metrics = _metrics_for_range(
        stress.daily,
        start=str(full_window["start"]),
        end=str(full_window["end"]),
    )
    predecessor_daily, predecessor_daily_sha = _load_predecessor_daily(contract)
    predecessor_metrics = _metrics_for_range(
        predecessor_daily.assign(
            equity_exposure=predecessor_daily["stock_weight"],
            holding_count=predecessor_daily["holding_count"],
        ),
        start=str(full_window["start"]),
        end=str(full_window["end"]),
    )
    attribution, attribution_summary = contribution_attribution(primary.daily, bars, contract)
    factor_stability = _selected_factor_stability(contract)

    byd_contract = load_all_weather_contract(
        contract.root / "configs/research_paradigms/cn_27_v1_0.yaml"
    )
    benchmark_result = AllWeatherBacktestResult(
        daily=primary.daily,
        trades=pd.DataFrame(),
        round_trips=pd.DataFrame(),
        coverage=pd.DataFrame(),
        indicators=pd.DataFrame(),
        metrics=full_metrics,
    )
    byd_comparison, paired = evaluate_byd_v1_3_challenge(benchmark_result, byd_contract)
    byd_comparison["challenger_model_version_id"] = str(contract.spec["model_version_id"])

    gate = contract.spec["support_gates"]
    gate_results = {
        "full_window_minimum_sharpe_log_excess": (
            full_metrics["sharpe_log_excess"]
            >= float(gate["full_window_minimum_sharpe_log_excess"])
        ),
        "full_window_maximum_annual_one_way_turnover": (
            full_metrics["annual_one_way_turnover"]
            <= float(gate["full_window_maximum_annual_one_way_turnover"])
        ),
        "full_window_maximum_drawdown_magnitude": (
            abs(full_metrics["maximum_drawdown"])
            <= float(gate["full_window_maximum_drawdown_magnitude"])
        ),
        "full_window_double_cost_minimum_sharpe_log_excess": (
            stress_full_metrics["sharpe_log_excess"]
            >= float(gate["full_window_double_cost_minimum_sharpe_log_excess"])
        ),
        "locked_test_minimum_sharpe_log_excess": (
            primary.metrics_by_window["locked_test"]["sharpe_log_excess"]
            >= float(gate["locked_test_minimum_sharpe_log_excess"])
        ),
        "locked_test_maximum_annual_one_way_turnover": (
            primary.metrics_by_window["locked_test"]["annual_one_way_turnover"]
            <= float(gate["locked_test_maximum_annual_one_way_turnover"])
        ),
        "maximum_single_name_positive_contribution_share": (
            attribution_summary["maximum_single_name_positive_contribution_share"]
            <= float(gate["maximum_single_name_positive_contribution_share"])
        ),
        "maximum_single_sector_positive_contribution_share": (
            attribution_summary["maximum_single_sector_positive_contribution_share"]
            <= float(gate["maximum_single_sector_positive_contribution_share"])
        ),
        "minimum_average_holding_count": (
            full_metrics["average_holding_count"] >= float(gate["minimum_average_holding_count"])
        ),
    }
    passed = all(gate_results.values())
    decision = {
        "schema_version": "1.0",
        "model_version_id": str(contract.spec["model_version_id"]),
        "decision": (
            "historically_supported_pending_prospective_validation"
            if passed
            else "historical_support_gates_not_passed"
        ),
        "all_support_gates_passed": passed,
        "support_gate_results": gate_results,
        "sharpe_target_reached": full_metrics["sharpe_log_excess"] >= 1.0,
        "turnover_reduced_vs_v1_0": (
            full_metrics["annual_one_way_turnover"]
            < predecessor_metrics["annual_one_way_turnover"]
        ),
        "fresh_historical_holdout": False,
        "prospective_validation_required": True,
        "automatic_promotion_allowed": False,
        "selected_pool_readiness_claimed": False,
        "research_only": True,
        "trade_ready": False,
    }
    metrics = {
        "schema_version": "1.0",
        "model_version_id": str(contract.spec["model_version_id"]),
        "full_window": full_metrics,
        "double_cost_full_window": stress_full_metrics,
        "by_window": primary.metrics_by_window,
        "double_cost_by_window": stress.metrics_by_window,
        "cn_27_v1_0_full_window": predecessor_metrics,
        "factor_stability": factor_stability,
        "attribution_summary": attribution_summary,
    }
    comparison = {
        "schema_version": "1.0",
        "cn_27_v1_1_vs_cn_27_v1_0": {
            "challenger": full_metrics,
            "predecessor": predecessor_metrics,
            "sharpe_improvement": (
                full_metrics["sharpe_log_excess"] - predecessor_metrics["sharpe_log_excess"]
            ),
            "annual_turnover_reduction": (
                predecessor_metrics["annual_one_way_turnover"]
                - full_metrics["annual_one_way_turnover"]
            ),
        },
        "cn_27_v1_1_vs_byd_v1_3": byd_comparison,
    }

    output = (
        (contract.root / str(contract.spec["evidence"]["output_dir"])).resolve()
        if output_dir is None
        else Path(output_dir).resolve()
    )
    output.mkdir(parents=True, exist_ok=True)
    primary.daily.reset_index().to_csv(output / "daily.csv", index=False, date_format="%Y-%m-%d")
    stress.daily.reset_index().to_csv(
        output / "double_cost_daily.csv", index=False, date_format="%Y-%m-%d"
    )
    attribution.to_csv(output / "attribution.csv", index=False, date_format="%Y-%m-%d")
    paired.to_csv(output / "byd_comparison_daily.csv", index=False, date_format="%Y-%m-%d")
    write_json(output / "metrics.json", metrics)
    write_json(output / "comparison.json", comparison)
    write_json(output / "decision.json", decision)

    report = "\n".join(
        [
            "# CN_27 V1.1 risk-adjusted momentum evidence",
            "",
            f"- Decision: `{decision['decision']}`",
            "- Research only: `true`; trade ready: `false`",
            "- Fresh historical holdout: `false`",
            f"- Full-window Sharpe: {full_metrics['sharpe_log_excess']:.4f}",
            f"- Full-window annual turnover: {full_metrics['annual_one_way_turnover']:.4f}x",
            f"- Full-window maximum drawdown: {full_metrics['maximum_drawdown']:.2%}",
            f"- Locked-test Sharpe: {primary.metrics_by_window['locked_test']['sharpe_log_excess']:.4f}",
            f"- Double-cost full-window Sharpe: {stress_full_metrics['sharpe_log_excess']:.4f}",
            f"- V1.0 full-window Sharpe: {predecessor_metrics['sharpe_log_excess']:.4f}",
            f"- V1.0 full-window annual turnover: {predecessor_metrics['annual_one_way_turnover']:.4f}x",
            "",
            "## Evidence limits",
            "",
            "The locked-test recipe was sealed before its metrics were opened, but the pool and all",
            "history had already been observed. This is retrospective support, not fresh validation.",
            "Formal promotion requires unchanged prospective evidence after 2026-09-04.",
        ]
    )
    (output / "report.md").write_text(report + "\n", encoding="utf-8")

    output_names = [
        "daily.csv",
        "double_cost_daily.csv",
        "metrics.json",
        "attribution.csv",
        "byd_comparison_daily.csv",
        "comparison.json",
        "decision.json",
        "report.md",
    ]
    outputs = {name: sha256_file(output / name) for name in output_names}
    identity = {
        "model_contract_sha256": sha256_file(contract.spec_path),
        "pool_sha256": sha256_file(contract.discovery.pool_path),
        "source_prices_sha256": sha256_file(contract.discovery.prices_path),
        "discovery_implementation_sha256": sha256_file(
            contract.root / "src/research/cn27_sharpe_discovery.py"
        ),
        "evidence_implementation_sha256": sha256_file(Path(__file__)),
        "sealed_screen_manifest_file_sha256": sha256_file(
            contract.root / str(contract.spec["lineage"]["sealed_screen_manifest"])
        ),
        "holdout_manifest_file_sha256": sha256_file(
            contract.root / str(contract.spec["lineage"]["holdout_manifest"])
        ),
        "predecessor_daily_sha256": predecessor_daily_sha,
        "byd_benchmark_manifest_sha256": byd_comparison["benchmark_manifest_sha256"],
        "byd_benchmark_performance_sha256": byd_comparison["benchmark_performance_sha256"],
    }
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "model_version_id": str(contract.spec["model_version_id"]),
        "identity": identity,
        "outputs": outputs,
        "decision": decision["decision"],
        "research_only": True,
        "trade_ready": False,
    }
    manifest["manifest_identity_sha256"] = canonical_sha256(manifest)
    write_json(output / "evidence_manifest.json", manifest)
    return {
        "decision": decision["decision"],
        "all_support_gates_passed": passed,
        "full_window": full_metrics,
        "locked_test": primary.metrics_by_window["locked_test"],
        "double_cost_full_window": stress_full_metrics,
        "predecessor_full_window": predecessor_metrics,
        "factor_stability": factor_stability,
        "attribution_summary": attribution_summary,
        "manifest_identity_sha256": manifest["manifest_identity_sha256"],
        "research_only": True,
        "trade_ready": False,
    }
