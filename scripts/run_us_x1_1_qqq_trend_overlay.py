"""Validate fixed QQQ trend overlays across US x1.1 development windows.

The experiment consumes the deterministic provider and exact Experiment 007
score/selection ledgers. It changes only target gross exposure when the QQQ
trailing 20-session price trend is negative. No model fitting or score search is
performed, and 2026H1 is excluded.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from scripts.run_us_x1_1_drawdown_attribution_phase_a import (
    REBALANCE_DAYS,
    RETURN_EXPRESSION,
    StrategySpec,
    _drawdown_path,
    _evaluate,
    _rank_day,
    _return_lookup,
    _write_csv,
    _write_json,
)
from src.research.qlib_execution_common import normalize_qlib_frame_index
from src.research.us_qlib_execution_adapter import QlibUSExecutionRuntime

EXPECTED_PROVIDER = "5c09d0fbc8348e182ce8829c44d43d96aaae4ed8a2c2ba8901e69034a7c6aa95"
WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")
COST_STRESS_BPS = (20, 40, 60)
MATERIAL_WINDOW_DRAWDOWN_IMPROVEMENT = 0.01
CANDIDATE_WORST_DRAWDOWN_IMPROVEMENT = 0.04
EXCESS_RETENTION_GATE = 0.90
NEGATIVE_WINDOW_OVERRIDE_DRAWDOWN = 0.08

STRATEGIES = (
    StrategySpec("baseline_100pct", 15, "equal", qqq_negative_trend_gross=1.0),
    StrategySpec("qqq_trend_50pct", 15, "equal", qqq_negative_trend_gross=0.5),
    StrategySpec("qqq_trend_cash", 15, "equal", qqq_negative_trend_gross=0.0),
)


@dataclass(frozen=True)
class WindowInputs:
    window: str
    scores: pd.DataFrame
    aligned_scores: pd.DataFrame
    returns: dict[pd.Timestamp, dict[str, float]]
    benchmark: dict[pd.Timestamp, float]
    closes: pd.DataFrame
    score_sha256: str
    economic_score_sha256: str
    selection_sha256: str
    economic_selection_sha256: str
    removed_score_rows: int


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON mapping: {path}")
    return payload


def _load_scores(path: Path, expected_sha256: str) -> pd.DataFrame:
    observed = _sha256_file(path)
    if observed != expected_sha256:
        raise ValueError(
            f"score identity mismatch for {path}: {observed} != {expected_sha256}"
        )
    frame = pd.read_csv(path)
    required = ["datetime", "instrument", "score"]
    if list(frame.columns) != required:
        raise ValueError(f"score columns must be {required}")
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="raise").dt.normalize()
    frame["instrument"] = frame["instrument"].astype(str)
    frame["score"] = pd.to_numeric(frame["score"], errors="raise")
    if frame.duplicated(["datetime", "instrument"]).any():
        raise ValueError("score ledger contains duplicate rows")
    if not np.isfinite(frame["score"].to_numpy(dtype=float)).all():
        raise ValueError("score ledger contains non-finite values")
    return frame.sort_values(["datetime", "instrument"], kind="mergesort").reset_index(
        drop=True
    )


def _load_selection(path: Path, expected_sha256: str) -> pd.DataFrame:
    observed = _sha256_file(path)
    if observed != expected_sha256:
        raise ValueError(
            f"selection identity mismatch for {path}: {observed} != {expected_sha256}"
        )
    frame = pd.read_csv(path)
    required = ["datetime", "instrument", "score", "rank", "target_weight"]
    if list(frame.columns) != required:
        raise ValueError(f"selection columns must be {required}")
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="raise").dt.normalize()
    frame["instrument"] = frame["instrument"].astype(str)
    frame["score"] = pd.to_numeric(frame["score"], errors="raise")
    frame["rank"] = pd.to_numeric(frame["rank"], errors="raise").astype(int)
    frame["target_weight"] = pd.to_numeric(frame["target_weight"], errors="raise")
    return frame.reset_index(drop=True)


def _align_scores(scores: pd.DataFrame, raw_returns: pd.DataFrame) -> pd.DataFrame:
    valid = raw_returns.reset_index()[["datetime", "instrument", "return"]].copy()
    valid["datetime"] = pd.to_datetime(valid["datetime"]).dt.normalize()
    valid["instrument"] = valid["instrument"].astype(str)
    valid = valid.loc[np.isfinite(valid["return"].to_numpy(dtype=float))]
    keys = valid[["datetime", "instrument"]].drop_duplicates()
    aligned = scores.merge(
        keys,
        on=["datetime", "instrument"],
        how="inner",
        validate="one_to_one",
    )
    return aligned.sort_values(["datetime", "instrument"], kind="mergesort").reset_index(
        drop=True
    )


def _selection_ledger(scores: pd.DataFrame) -> pd.DataFrame:
    """Build a daily Top-15 identity ledger from the supplied score layer."""

    dates = [pd.Timestamp(value) for value in sorted(scores["datetime"].unique())]
    rows: list[dict[str, Any]] = []
    for date in dates:
        ranked = _rank_day(scores.loc[scores["datetime"] == date].copy()).head(15)
        if len(ranked) != 15:
            raise ValueError(f"fewer than 15 eligible names on {date.date()}")
        for _, row in ranked.iterrows():
            rows.append(
                {
                    "datetime": date,
                    "instrument": str(row["instrument"]),
                    "score": float(row["score"]),
                    "rank": int(row["rank"]),
                    "target_weight": 1.0 / 15.0,
                }
            )
    return pd.DataFrame(rows)


def _frame_sha256(frame: pd.DataFrame, path: Path) -> str:
    _write_csv(path, frame)
    return _sha256_file(path)


def _compare_selection_identity(observed: pd.DataFrame, expected: pd.DataFrame) -> None:
    pd.testing.assert_frame_equal(
        observed.reset_index(drop=True),
        expected.reset_index(drop=True),
        check_exact=True,
        check_dtype=False,
        check_like=False,
    )


def _compounded(values: pd.Series | list[float]) -> float:
    array = np.asarray(values, dtype=float)
    return float(np.prod(1.0 + array) - 1.0)


def _state_evidence(
    periods: pd.DataFrame,
    baseline_periods: pd.DataFrame,
) -> dict[str, Any]:
    if len(periods) != len(baseline_periods):
        raise ValueError("variant and baseline period counts differ")
    if not periods["rebalance_date"].reset_index(drop=True).equals(
        baseline_periods["rebalance_date"].reset_index(drop=True)
    ):
        raise ValueError("variant and baseline rebalance dates differ")
    reduced = periods["gross_exposure"] < 1.0 - 1e-12
    full = ~reduced
    rebound = (
        (periods["qqq_trend_state"] == "negative")
        & (periods["benchmark_return"] > 0)
    )
    upside_forgone = float(
        np.maximum(
            baseline_periods.loc[rebound, "net_return"].to_numpy(dtype=float)
            - periods.loc[rebound, "net_return"].to_numpy(dtype=float),
            0.0,
        ).sum()
    )

    def summarize(mask: pd.Series) -> dict[str, Any]:
        subset = periods.loc[mask]
        return {
            "n_periods": int(mask.sum()),
            "arithmetic_net_return_contribution": float(subset["net_return"].sum()),
            "compounded_net_return": _compounded(subset["net_return"].tolist()),
            "compounded_benchmark_return": _compounded(
                subset["benchmark_return"].tolist()
            ),
            "arithmetic_excess_contribution": float(subset["excess_return"].sum()),
        }

    return {
        "average_gross_exposure": float(periods["gross_exposure"].mean()),
        "reduced_risk_rebalances": int(reduced.sum()),
        "reduced_risk_share": float(reduced.mean()),
        "full_risk_state": summarize(full),
        "reduced_risk_state": summarize(reduced),
        "negative_trend_rebound_periods": int(rebound.sum()),
        "upside_forgone_on_negative_trend_rebounds": upside_forgone,
    }


def _recovery_comparison(
    baseline: dict[str, Any],
    variant: dict[str, Any],
) -> dict[str, Any]:
    baseline_recovery = baseline.get("recovery_date")
    variant_recovery = variant.get("recovery_date")
    if baseline_recovery and variant_recovery:
        delta = (
            pd.Timestamp(variant_recovery) - pd.Timestamp(baseline_recovery)
        ).days
        status = "accelerated" if delta < 0 else "delayed" if delta > 0 else "same_date"
        return {"status": status, "calendar_day_delta": int(delta)}
    if baseline_recovery and not variant_recovery:
        return {"status": "variant_not_recovered", "calendar_day_delta": None}
    if not baseline_recovery and variant_recovery:
        return {"status": "variant_recovers_baseline_not", "calendar_day_delta": None}
    return {"status": "neither_recovered", "calendar_day_delta": None}


def _aggregate(
    strategy_id: str,
    cost_bps: int,
    window_results: list[dict[str, Any]],
) -> dict[str, Any]:
    strategy_return = float(
        np.prod([1.0 + row["total_return"] for row in window_results]) - 1.0
    )
    benchmark_return = float(
        np.prod([1.0 + row["benchmark_return"] for row in window_results]) - 1.0
    )
    relative_excess = float((1.0 + strategy_return) / (1.0 + benchmark_return) - 1.0)
    positive = [
        float(row["excess_return"])
        for row in window_results
        if row["excess_return"] > 0
    ]
    strongest_share = max(positive) / sum(positive) if positive else 0.0
    total_periods = sum(int(row["n_periods"]) for row in window_results)
    weighted_gross = sum(
        float(row["state_evidence"]["average_gross_exposure"])
        * int(row["n_periods"])
        for row in window_results
    )
    return {
        "strategy_id": strategy_id,
        "cost_bps": cost_bps,
        "compounded_strategy_return": strategy_return,
        "compounded_benchmark_return": benchmark_return,
        "compounded_relative_excess_return": relative_excess,
        "worst_drawdown": min(float(row["max_drawdown"]) for row in window_results),
        "positive_excess_windows": sum(
            row["excess_return"] > 0 for row in window_results
        ),
        "strongest_positive_window_share": strongest_share,
        "average_gross_exposure": weighted_gross / total_periods if total_periods else 0.0,
        "positive_relative_excess": relative_excess > 0,
    }


def _candidate_gate(
    strategy_id: str,
    aggregates: dict[str, dict[str, dict[str, Any]]],
    windows: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, Any]:
    baseline_20 = aggregates["baseline_100pct"]["20"]
    candidate_20 = aggregates[strategy_id]["20"]
    candidate_60 = aggregates[strategy_id]["60"]
    worst_improvement = float(
        candidate_20["worst_drawdown"] - baseline_20["worst_drawdown"]
    )
    retained = (
        float(candidate_20["compounded_relative_excess_return"])
        / float(baseline_20["compounded_relative_excess_return"])
        if baseline_20["compounded_relative_excess_return"] > 0
        else 0.0
    )
    benefit_windows: list[str] = []
    new_negative_windows: list[str] = []
    window_evidence: list[dict[str, Any]] = []
    for window in WINDOWS:
        base = windows[window]["baseline_100pct"]["20"]
        candidate = windows[window][strategy_id]["20"]
        improvement = float(candidate["max_drawdown"] - base["max_drawdown"])
        material = improvement >= MATERIAL_WINDOW_DRAWDOWN_IMPROVEMENT
        if material:
            benefit_windows.append(window)
        if base["excess_return"] > 0 and candidate["excess_return"] < 0:
            new_negative_windows.append(window)
        window_evidence.append(
            {
                "window": window,
                "drawdown_improvement": improvement,
                "excess_change": float(
                    candidate["excess_return"] - base["excess_return"]
                ),
                "material_drawdown_benefit": material,
            }
        )
    no_negative_gate = (
        not new_negative_windows
        or worst_improvement >= NEGATIVE_WINDOW_OVERRIDE_DRAWDOWN
    )
    gates = {
        "worst_drawdown_improvement_gate": worst_improvement
        >= CANDIDATE_WORST_DRAWDOWN_IMPROVEMENT,
        "retained_relative_excess_gate": retained >= EXCESS_RETENTION_GATE,
        "positive_60bps_relative_excess_gate": candidate_60[
            "compounded_relative_excess_return"
        ]
        > 0,
        "no_new_negative_window_gate": no_negative_gate,
        "benefit_in_two_windows_gate": len(benefit_windows) >= 2,
    }
    return {
        "strategy_id": strategy_id,
        "worst_drawdown_improvement": worst_improvement,
        "retained_relative_excess_ratio": retained,
        "benefit_windows": benefit_windows,
        "new_negative_excess_windows": new_negative_windows,
        "window_evidence": window_evidence,
        "gates": gates,
        "supported": all(gates.values()),
    }


def _decision(gates: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {row["strategy_id"]: row for row in gates}
    if by_id["qqq_trend_50pct"]["supported"]:
        decision = "qqq_trend_50pct_portfolio_candidate_supported"
        selected = "qqq_trend_50pct"
    elif by_id["qqq_trend_cash"]["supported"]:
        decision = "qqq_trend_cash_portfolio_candidate_supported"
        selected = "qqq_trend_cash"
    else:
        selected = None
        material_counts = [len(row["benefit_windows"]) for row in gates]
        upside_failure = any(
            not row["gates"]["retained_relative_excess_gate"]
            or not row["gates"]["no_new_negative_window_gate"]
            for row in gates
        )
        meaningful_risk_path = any(
            row["worst_drawdown_improvement"]
            >= CANDIDATE_WORST_DRAWDOWN_IMPROVEMENT
            or len(row["benefit_windows"]) >= 2
            for row in gates
        )
        if upside_failure and meaningful_risk_path:
            decision = "trend_overlay_destroys_too_much_upside"
        elif max(material_counts, default=0) > 0:
            decision = "trend_overlay_window_specific"
        else:
            decision = "no_overlay_improves_us_x1_1"
    return {
        "decision": decision,
        "selected_portfolio_contract": selected,
        "candidate_gates": gates,
        "automatic_model_update": False,
        "creates_us_x1_2_candidate": False,
        "research_only": True,
        "trade_ready": False,
    }


def _load_window_inputs(
    runtime: QlibUSExecutionRuntime,
    reproduction_root: Path,
    reproduction: dict[str, Any],
    window: str,
    output_dir: Path,
) -> WindowInputs:
    expected = next(
        row for row in reproduction["run_a"]["windows"] if row["window"] == window
    )
    ledger_root = reproduction_root / "ledgers" / "a" / window
    score_path = ledger_root / "scores.csv"
    selection_path = ledger_root / "top15_selections.csv"
    scores = _load_scores(score_path, str(expected["score_sha256"]))
    expected_selection = _load_selection(
        selection_path,
        str(expected["top15_selection_sha256"]),
    )
    symbols = sorted(scores["instrument"].unique())
    dates = [pd.Timestamp(value) for value in sorted(scores["datetime"].unique())]
    start, end = dates[0], dates[-1]
    raw_returns = normalize_qlib_frame_index(
        runtime.features(
            symbols,
            [RETURN_EXPRESSION],
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        )
    )
    raw_returns.columns = ["return"]
    aligned_scores = _align_scores(scores, raw_returns)

    source_selection = _selection_ledger(scores)
    source_selection_path = (
        output_dir / "identity" / window / "source_daily_top15_selections.csv"
    )
    source_selection_sha = _frame_sha256(source_selection, source_selection_path)
    _compare_selection_identity(source_selection, expected_selection)
    if source_selection_sha != str(expected["top15_selection_sha256"]):
        raise ValueError(
            f"source selection byte identity mismatch for {window}: "
            f"{source_selection_sha} != {expected['top15_selection_sha256']}"
        )

    economic_score_path = output_dir / "identity" / window / "economic_scores.csv"
    economic_score_sha = _frame_sha256(aligned_scores, economic_score_path)
    economic_selection = _selection_ledger(aligned_scores)
    economic_selection_path = (
        output_dir / "identity" / window / "economic_daily_top15_selections.csv"
    )
    economic_selection_sha = _frame_sha256(
        economic_selection,
        economic_selection_path,
    )

    benchmark_frame = normalize_qlib_frame_index(
        runtime.features(
            ["QQQ"],
            [RETURN_EXPRESSION],
            start.strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        )
    )
    benchmark_frame.columns = ["return"]
    benchmark = {
        pd.Timestamp(date): float(group["return"].iloc[0])
        for date, group in benchmark_frame.reset_index().groupby("datetime")
    }
    close_frame = normalize_qlib_frame_index(
        runtime.features(
            [*symbols, "QQQ"],
            ["$close"],
            (start - pd.Timedelta(days=120)).strftime("%Y-%m-%d"),
            end.strftime("%Y-%m-%d"),
        )
    )
    close_frame.columns = ["close"]
    closes = close_frame["close"].unstack(level="instrument").sort_index()
    return WindowInputs(
        window=window,
        scores=scores,
        aligned_scores=aligned_scores,
        returns=_return_lookup(raw_returns),
        benchmark=benchmark,
        closes=closes,
        score_sha256=str(expected["score_sha256"]),
        economic_score_sha256=economic_score_sha,
        selection_sha256=source_selection_sha,
        economic_selection_sha256=economic_selection_sha,
        removed_score_rows=len(scores) - len(aligned_scores),
    )


def run(
    root: Path,
    provider_uri: Path,
    reproduction_root: Path,
    output_dir: Path,
) -> dict[str, Any]:
    root = root.resolve()
    output_dir = output_dir.resolve()
    reproduction_root = reproduction_root.resolve()
    reproduction = _load_json(reproduction_root / "deterministic_reproduction.json")
    if tuple(reproduction["decision_windows"]) != WINDOWS:
        raise ValueError("Experiment 007 decision-window contract changed")
    if "2026H1" not in reproduction["consumed_reporting_windows_excluded"]:
        raise ValueError("2026H1 exclusion is missing")

    runtime = QlibUSExecutionRuntime(provider_uri=provider_uri.resolve())
    runtime.initialize(root)
    provider = str(runtime.metadata().get("provider_identity_sha256", ""))
    if provider != EXPECTED_PROVIDER:
        raise ValueError(f"unexpected provider identity: {provider}")

    inputs = {
        window: _load_window_inputs(
            runtime,
            reproduction_root,
            reproduction,
            window,
            output_dir,
        )
        for window in WINDOWS
    }
    window_results: dict[str, dict[str, dict[str, Any]]] = {}
    period_frames: dict[tuple[str, str, int], pd.DataFrame] = {}
    for window in WINDOWS:
        window_results[window] = {}
        data = inputs[window]
        for spec in STRATEGIES:
            window_results[window][spec.strategy_id] = {}
            for cost in COST_STRESS_BPS:
                result, periods, _ = _evaluate(
                    data.aligned_scores,
                    data.returns,
                    data.benchmark,
                    data.closes,
                    spec,
                    cost,
                )
                period_frames[(window, spec.strategy_id, cost)] = periods
                drawdown = _drawdown_path(periods)
                result = {
                    **result,
                    "drawdown_path": drawdown,
                }
                window_results[window][spec.strategy_id][str(cost)] = result
                _write_csv(
                    output_dir
                    / "ledgers"
                    / window
                    / f"{spec.strategy_id}_{cost}bps_periods.csv",
                    periods,
                )

        expected = next(
            row for row in reproduction["run_a"]["windows"] if row["window"] == window
        )
        for cost in COST_STRESS_BPS:
            observed = window_results[window]["baseline_100pct"][str(cost)]
            expected_cost = expected["cost_stress"][str(cost)]
            for key in (
                "total_return",
                "benchmark_return",
                "excess_return",
                "max_drawdown",
                "turnover",
                "costs",
            ):
                if not math.isclose(
                    float(observed[key]),
                    float(expected_cost[key]),
                    rel_tol=0.0,
                    abs_tol=1e-6,
                ):
                    raise ValueError(
                        f"baseline mismatch {window} {cost}bps {key}: "
                        f"{observed[key]} != {expected_cost[key]}"
                    )

        for cost in COST_STRESS_BPS:
            baseline_periods = period_frames[(window, "baseline_100pct", cost)]
            baseline_drawdown = window_results[window]["baseline_100pct"][str(cost)][
                "drawdown_path"
            ]
            for spec in STRATEGIES:
                result = window_results[window][spec.strategy_id][str(cost)]
                periods = period_frames[(window, spec.strategy_id, cost)]
                result["state_evidence"] = _state_evidence(
                    periods,
                    baseline_periods,
                )
                result["recovery_vs_baseline"] = _recovery_comparison(
                    baseline_drawdown,
                    result["drawdown_path"],
                )
                result["score_identity_sha256"] = inputs[window].score_sha256
                result["economic_score_identity_sha256"] = inputs[
                    window
                ].economic_score_sha256
                result["source_top15_selection_identity_sha256"] = inputs[
                    window
                ].selection_sha256
                result["economic_top15_selection_identity_sha256"] = inputs[
                    window
                ].economic_selection_sha256
                result["selection_changed_from_baseline"] = False

    aggregates: dict[str, dict[str, dict[str, Any]]] = {}
    for spec in STRATEGIES:
        aggregates[spec.strategy_id] = {}
        for cost in COST_STRESS_BPS:
            aggregates[spec.strategy_id][str(cost)] = _aggregate(
                spec.strategy_id,
                cost,
                [window_results[w][spec.strategy_id][str(cost)] for w in WINDOWS],
            )

    gates = [
        _candidate_gate("qqq_trend_50pct", aggregates, window_results),
        _candidate_gate("qqq_trend_cash", aggregates, window_results),
    ]
    decision = _decision(gates)
    payload = {
        "schema_version": "1.0",
        "experiment_id": "us_x1_1_qqq_trend_overlay_v1",
        "issue": 396,
        "parent_model_id": "us_x1_1",
        "provider_identity_sha256": provider,
        "decision_windows": list(WINDOWS),
        "consumed_reporting_windows_excluded": ["2026H1"],
        "portfolio_contracts": {
            spec.strategy_id: {
                "top_n": spec.top_n,
                "weighting": spec.weighting,
                "rebalance_days": REBALANCE_DAYS,
                "qqq_negative_trend_gross": spec.qqq_negative_trend_gross,
                "trend_definition": "QQQ close[t-1] / close[t-21] - 1 < 0",
            }
            for spec in STRATEGIES
        },
        "identity_proof": {
            window: {
                "source_score_sha256": inputs[window].score_sha256,
                "economic_score_sha256": inputs[window].economic_score_sha256,
                "source_daily_top15_selection_sha256": inputs[
                    window
                ].selection_sha256,
                "economic_daily_top15_selection_sha256": inputs[
                    window
                ].economic_selection_sha256,
                "removed_score_rows_without_raw_forward_return": inputs[
                    window
                ].removed_score_rows,
                "selection_matches_experiment_007": True,
                "economic_selection_basis": (
                    "source_scores_intersect_non_null_raw_forward_returns_before_ranking"
                ),
            }
            for window in WINDOWS
        },
        "window_results": window_results,
        "aggregate_results": aggregates,
        "decision": decision,
        "governance": {
            "model_refit": False,
            "score_search": False,
            "lookback_search": False,
            "threshold_search": False,
            "combined_controls": False,
            "research_only": True,
            "trade_ready": False,
        },
    }
    _write_json(output_dir / "qqq_trend_overlay.json", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--provider-uri", type=Path, required=True)
    parser.add_argument("--reproduction-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    payload = run(
        args.root,
        args.provider_uri,
        args.reproduction_root,
        args.output_dir,
    )
    print(
        json.dumps(
            {
                "decision": payload["decision"],
                "aggregate_results": payload["aggregate_results"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
