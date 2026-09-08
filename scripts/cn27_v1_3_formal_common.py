"""Shared CN_27 V1.3 formal row-level builders for publication and refresh.

The frozen k2 reconstruction below is byte-faithful to the user-directed
formal publication: the refresh path reuses these exact builders over
extended bars so that every row at or before the prior evidence cutoff must
reproduce bit-identically (verified by the append-only prefix gate). No model
selection lives here: callers must pass the frozen k2 recipe explicitly and
verify its identity before calling.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from src.artifacts.model_run_bundle_v2 import canonical_json_bytes
from src.research.all_weather_alpha_rotation import canonical_sha256, sha256_file
from src.research.cn27_v1_2 import (
    _block_bootstrap_sharpe,
    compute_v1_2_features,
    score_v1_2_features,
)
from src.research.cn27_v1_3 import concentration_audit, contribution_attribution
from src.research.cn27_v1_3_projected import (
    DiscoveryBacktestResult,
    load_projected_discovery_contract,
    run_projected_recipe,
)

MODEL_ID = "cn_27_v1_3"
STRATEGY_ID = "cn_27"
FAMILY_ID = "cn_27_rotation"
RECIPE_ID = "k2_projected_22_45_n8"
FAILED_GATES = ["timing_perturbation_sharpe", "bootstrap_p05"]


class Cn27V13FormalError(ValueError):
    """Raised when the CN_27 V1.3 formal boundary cannot be proven."""


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Cn27V13FormalError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise Cn27V13FormalError(f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload))


def _repository_path(path: Path) -> str:
    return path.resolve().relative_to(Path.cwd().resolve()).as_posix()


def _close(left: object, right: object, label: str) -> None:
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        raise Cn27V13FormalError(f"non-numeric comparison: {label}")
    if abs(float(left) - float(right)) > 1e-10:
        raise Cn27V13FormalError(f"historical evidence drifted: {label}")


def _action(previous: float, target: float) -> str:
    if previous <= 1e-12:
        return "BUY"
    if target <= 1e-12:
        return "SELL"
    return "INCREASE" if target > previous else "DECREASE"


def _benchmark_path(bars: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.Series:
    benchmark = (
        bars.loc[bars["symbol"].astype(str).str.zfill(6).eq("000300")]
        .sort_values("date")
        .set_index("date")["open"]
        .reindex(dates)
        .ffill()
        .pct_change(fill_method=None)
        .fillna(0.0)
    )
    return benchmark.astype(float)


@dataclass(frozen=True)
class K2Context:
    contract: Any
    recipe: dict[str, Any]
    bars: pd.DataFrame
    result: DiscoveryBacktestResult
    full: Mapping[str, Any]
    bootstrap: dict[str, Any]
    bootstrap_policy: Mapping[str, Any]
    audit_summary: dict[str, Any]
    attribution: pd.DataFrame
    attribution_summary: dict[str, Any]


def load_k2_context(contract_path: str | Path) -> K2Context:
    """Run the frozen k2 recipe over the contract-bound bars."""

    contract = load_projected_discovery_contract(contract_path)
    recipe = next(
        (
            dict(row)
            for row in contract.spec["candidate_recipes"]
            if row["id"] == RECIPE_ID
        ),
        None,
    )
    if recipe is None:
        raise Cn27V13FormalError("frozen k2 recipe is missing")
    bars = pd.read_csv(contract.prices_path, dtype={"symbol": str}, parse_dates=["date"])
    features = compute_v1_2_features(bars, contract)
    scoring_recipe = {**contract.spec["frozen_signal"], "id": "frozen_v1_2_signal"}
    scored, _ = score_v1_2_features(features, scoring_recipe, contract)
    result = run_projected_recipe(
        bars,
        features,
        contract,
        recipe,
        scored_features=scored,
    )
    bootstrap_policy = contract.spec["robustness_tests"]["block_bootstrap"]
    bootstrap = _block_bootstrap_sharpe(
        result.daily["net_return"],
        samples=int(bootstrap_policy["samples"]),
        block_sessions=int(bootstrap_policy["block_sessions"]),
        seed=int(bootstrap_policy["seed"]),
    )
    _, audit_summary = concentration_audit(result.daily, contract)
    attribution, attribution_summary = contribution_attribution(
        result.daily, bars, contract
    )
    return K2Context(
        contract=contract,
        recipe=recipe,
        bars=bars,
        result=result,
        full=result.metrics_by_window["development"],
        bootstrap=bootstrap,
        bootstrap_policy=bootstrap_policy,
        audit_summary=audit_summary,
        attribution=attribution,
        attribution_summary=attribution_summary,
    )


def compare_retained_metrics(context: K2Context, retained: Mapping[str, Any]) -> None:
    """Compare a fresh reconstruction against the sealed discovery summary."""

    comparisons = {
        "total_return": "full_total_return",
        "cagr": "full_cagr",
        "annual_volatility": "full_annual_volatility",
        "sharpe_log_excess": "full_sharpe_log_excess",
        "maximum_drawdown": "full_maximum_drawdown",
        "annual_one_way_turnover": "full_annual_one_way_turnover",
        "transaction_cost_paid": "full_transaction_cost_paid",
    }
    for observed, expected in comparisons.items():
        _close(context.full[observed], retained[expected], observed)
    _close(
        context.bootstrap["sharpe_percentile_05"],
        retained["bootstrap_sharpe_percentile_05"],
        "bootstrap_sharpe_percentile_05",
    )
    for key, value in context.audit_summary.items():
        _close(value, retained[key], key)
    for key in (
        "maximum_single_name_positive_contribution_share",
        "maximum_single_sector_positive_contribution_share",
    ):
        _close(context.attribution_summary[key], retained[key], key)


def build_backtest_rows(
    bars: pd.DataFrame,
    contract: Any,
    result: DiscoveryBacktestResult,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Rebuild report/positions/trades rows from a recipe result."""

    daily = result.daily.copy()
    dates = pd.DatetimeIndex(daily.index)
    benchmark_return = _benchmark_path(bars, dates)
    benchmark_equity = (1.0 + benchmark_return).cumprod()
    open_returns = {
        symbol: (
            bars.loc[bars["symbol"].astype(str).str.zfill(6).eq(symbol)]
            .sort_values("date")
            .set_index("date")["open"]
            .reindex(dates)
            .ffill()
            .pct_change(fill_method=None)
            .fillna(0.0)
        )
        for symbol in (*contract.candidate_symbols, contract.defensive_symbol)
    }
    previous: dict[str, float] = {"CASH": 1.0}
    report: list[dict[str, Any]] = []
    positions: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    names = {
        str(row["symbol"]).zfill(6): str(row["name"]) for row in contract.pool["symbols"]
    }
    sectors = {
        str(row["symbol"]).zfill(6): str(row["sector"])
        for row in contract.pool["symbols"]
    }
    for date, row in daily.iterrows():
        date_text = pd.Timestamp(date).date().isoformat()
        weights = {
            key: float(value)
            for key, value in json.loads(str(row["asset_weights"])).items()
        }
        if float(row["cash_weight"]) > 1e-12:
            weights["CASH"] = float(row["cash_weight"])
        report.append(
            {
                "date": date_text,
                "gross_return": float(row["gross_return"]),
                "transaction_cost": float(row["transaction_cost"]),
                "net_return": float(row["net_return"]),
                "account": float(row["equity"]),
                "benchmark_return": float(benchmark_return.loc[date]),
                "benchmark_account": float(benchmark_equity.loc[date]),
                "drawdown": float(row["equity"] / daily.loc[:date, "equity"].max() - 1.0),
                "one_way_turnover": float(row["one_way_turnover"]),
                "equity_exposure": float(row["equity_exposure"]),
                "etf_weight": float(row["etf_weight"]),
                "cash_weight": float(row["cash_weight"]),
                "holding_count": int(row["holding_count"]),
                "pending_execution": bool(row["pending_execution"]),
                "target_drift_due_to_trade_lock": float(
                    row["target_drift_due_to_trade_lock"]
                ),
            }
        )
        for symbol, weight in sorted(weights.items()):
            if symbol == "CASH":
                name, sector, role = "Cash", "cash", "cash"
            elif symbol == contract.defensive_symbol:
                name, sector, role = (
                    "Dividend ETF 515180",
                    "defensive_etf",
                    "defensive_etf",
                )
            else:
                name, sector, role = names[symbol], sectors[symbol], "candidate_equity"
            positions.append(
                {
                    "date": date_text,
                    "instrument": symbol,
                    "name": name,
                    "sector": sector,
                    "role": role,
                    "weight": weight,
                }
            )
        gross_factor = 1.0 + float(row["gross_return"])
        before = {
            symbol: previous.get(symbol, 0.0)
            * (1.0 + float(open_returns[symbol].loc[date]))
            / gross_factor
            for symbol in previous
            if symbol != "CASH"
        }
        before["CASH"] = previous.get("CASH", 0.0) / gross_factor
        changes = {
            symbol: weights.get(symbol, 0.0) - before.get(symbol, 0.0)
            for symbol in sorted(set(weights) | set(before))
        }
        changed_total = sum(abs(value) for value in changes.values())
        for symbol, delta in changes.items():
            if abs(delta) <= 1e-12:
                continue
            trades.append(
                {
                    "date": date_text,
                    "instrument": symbol,
                    "action": _action(before.get(symbol, 0.0), weights.get(symbol, 0.0)),
                    "previous_weight": before.get(symbol, 0.0),
                    "target_weight": weights.get(symbol, 0.0),
                    "weight_delta": delta,
                    "transaction_cost": (
                        float(row["transaction_cost"]) * abs(delta) / changed_total
                        if changed_total > 1e-12
                        else 0.0
                    ),
                    "reason": "scheduled_rank_and_project_or_locked_target_retry",
                }
            )
        previous = weights
    return report, positions, trades


def build_attribution_payload(
    attribution: pd.DataFrame,
) -> list[dict[str, Any]]:
    attribution_rows = attribution.copy()
    attribution_rows["date"] = pd.to_datetime(attribution_rows["date"]).dt.strftime(
        "%Y-%m-%d"
    )
    attribution_payload = attribution_rows.to_dict(orient="records")
    gross_by_symbol = attribution.groupby(["symbol", "sector"], as_index=False)[
        "gross_contribution"
    ].sum()
    for row in gross_by_symbol.to_dict(orient="records"):
        attribution_payload.append(
            {
                "date": None,
                "symbol": row["symbol"],
                "sector": row["sector"],
                "gross_contribution": float(row["gross_contribution"]),
                "attribution_level": "full_window_instrument",
            }
        )
    return attribution_payload


def run_k2_variant_battery(
    *,
    bars: pd.DataFrame,
    features: pd.DataFrame,
    scored: pd.DataFrame,
    contract: Any,
    recipe: Mapping[str, Any],
    base_result: DiscoveryBacktestResult,
) -> dict[str, Any]:
    """Run the frozen robustness battery for the single k2 recipe.

    Mirrors the per-recipe variant loop of the discovery screen so refresh
    evidence stays current without reopening model selection: every variant
    reuses the frozen recipe and only the observation window extends.
    """

    from src.research.cn27_v1_3 import _parameter_variants

    robustness = contract.spec["robustness_tests"]

    def execute(
        active_recipe: Mapping[str, object] = recipe,
        *,
        cost_multiplier: float = 1.0,
        delay: int = 1,
        phase: int = 0,
        excluded: frozenset[str] = frozenset(),
    ) -> DiscoveryBacktestResult:
        return run_projected_recipe(
            bars,
            features,
            contract,
            active_recipe,
            cost_multiplier=cost_multiplier,
            execution_delay_sessions=delay,
            rebalance_phase_offset=phase,
            excluded_sectors=excluded,
            scored_features=scored,
        )

    stress = execute(cost_multiplier=float(robustness["cost_multiplier"]))
    delayed = execute(delay=int(robustness["execution_delay_sessions"]))
    phase_sharpes = {
        "0": float(base_result.metrics_by_window["development"]["sharpe_log_excess"])
    }
    for phase in robustness["rebalance_phase_offsets"]:
        phase_result = execute(phase=int(phase))
        phase_sharpes[str(phase)] = float(
            phase_result.metrics_by_window["development"]["sharpe_log_excess"]
        )
    risk_model = contract.spec["frozen_risk_model"]
    parameter_policy = contract.spec["parameter_perturbations"]
    parameter_rows: list[dict[str, Any]] = [
        {
            "recipe_id": RECIPE_ID,
            "variant": "base",
            "sharpe_log_excess": float(
                base_result.metrics_by_window["development"]["sharpe_log_excess"]
            ),
            "maximum_drawdown_magnitude": abs(
                float(base_result.metrics_by_window["development"]["maximum_drawdown"])
            ),
        }
    ]
    for label, variant in _parameter_variants(recipe, risk_model, parameter_policy):
        variant_result = execute(variant)
        metrics = variant_result.metrics_by_window["development"]
        parameter_rows.append(
            {
                "recipe_id": RECIPE_ID,
                "variant": label,
                "sharpe_log_excess": float(metrics["sharpe_log_excess"]),
                "maximum_drawdown_magnitude": abs(float(metrics["maximum_drawdown"])),
            }
        )
    sectors = sorted({str(row["sector"]) for row in contract.pool["symbols"]})
    sector_rows: list[dict[str, Any]] = []
    for sector in sectors:
        sector_result = execute(excluded=frozenset({sector}))
        metrics = sector_result.metrics_by_window["development"]
        sector_rows.append(
            {
                "recipe_id": RECIPE_ID,
                "excluded_sector": sector,
                "sharpe_log_excess": float(metrics["sharpe_log_excess"]),
                "maximum_drawdown": float(metrics["maximum_drawdown"]),
                "annual_one_way_turnover": float(metrics["annual_one_way_turnover"]),
            }
        )
    bootstrap_policy = contract.spec["robustness_tests"]["block_bootstrap"]
    bootstrap = _block_bootstrap_sharpe(
        base_result.daily["net_return"],
        samples=int(bootstrap_policy["samples"]),
        block_sessions=int(bootstrap_policy["block_sessions"]),
        seed=int(bootstrap_policy["seed"]),
    )
    return {
        "double_cost_full_sharpe": float(
            stress.metrics_by_window["development"]["sharpe_log_excess"]
        ),
        "delay_two_full_sharpe": float(
            delayed.metrics_by_window["development"]["sharpe_log_excess"]
        ),
        "phase_sharpes": phase_sharpes,
        "parameter_rows": parameter_rows,
        "sector_rows": sector_rows,
        "bootstrap": bootstrap,
        "bootstrap_policy": bootstrap_policy,
    }


def build_window_summary(
    *,
    result: DiscoveryBacktestResult,
    phase_sharpes: Mapping[str, Any],
    delay_two_full_sharpe: float,
    parameter_rows: list[dict[str, Any]],
    sector_rows: list[dict[str, Any]],
    bootstrap: Mapping[str, Any],
    bootstrap_policy: Mapping[str, Any],
    failed_gates: list[str],
) -> list[dict[str, Any]]:
    window_summary: list[dict[str, Any]] = [
        {"test": "chronological_fold", "fold": name, **metrics}
        for name, metrics in result.metrics_by_window.items()
        if name != "development"
    ]
    window_summary.extend(
        {
            "test": "timing_perturbation",
            "variant": key,
            "sharpe_log_excess": float(value),
        }
        for key, value in phase_sharpes.items()
    )
    window_summary.append(
        {
            "test": "execution_delay",
            "variant": "two_sessions",
            "sharpe_log_excess": float(delay_two_full_sharpe),
        }
    )
    for row in parameter_rows:
        window_summary.append({"test": "parameter_neighborhood", **row})
    for row in sector_rows:
        window_summary.append({"test": "leave_one_sector_out", **row})
    window_summary.extend(
        [
            {
                "test": "block_bootstrap",
                "samples": int(bootstrap_policy["samples"]),
                "block_sessions": int(bootstrap_policy["block_sessions"]),
                **bootstrap,
            },
            {
                "test": "frozen_gate_result",
                "supported": False,
                "passed": 19,
                "total": 21,
                "failed_gates": failed_gates,
            },
        ]
    )
    return window_summary
