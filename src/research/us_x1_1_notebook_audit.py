"""Build a complete, auditable US x1.1 backtest bundle from frozen evidence.

This module intentionally performs no model search. It consumes the deterministic
provider source CSVs and the Experiment 007 score ledgers, reconstructs the exact
Top-15 equal-weight 10-session portfolio, and exports signal, trade, holding,
performance and attribution tables suitable for notebook inspection.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

WINDOWS = ("2024H1", "2024H2", "2025H1", "2025H2")
TOPK = 15
HORIZON_SESSIONS = 10
REBALANCE_SESSIONS = 10
BASE_COST_BPS = 20
EXPECTED_PROVIDER_IDENTITY = "5c09d0fbc8348e182ce8829c44d43d96aaae4ed8a2c2ba8901e69034a7c6aa95"
EXPECTED_PARAMETER_IDENTITY = "c45831d096e5da0d8e0fe15762ec29c949d69ff9d6dfc022fa7f6244b5e6ec0d"


@dataclass(frozen=True)
class BacktestAudit:
    manifest: dict[str, Any]
    identity_checks: pd.DataFrame
    daily_signals: pd.DataFrame
    rebalance_signals: pd.DataFrame
    trades: pd.DataFrame
    holdings: pd.DataFrame
    periods: pd.DataFrame
    security_attribution: pd.DataFrame
    window_attribution: pd.DataFrame
    regime_attribution: pd.DataFrame
    reproduction_summary: pd.DataFrame


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, frame: pd.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    output = frame.copy()
    for column in output.columns:
        if pd.api.types.is_datetime64_any_dtype(output[column]):
            output[column] = output[column].dt.strftime("%Y-%m-%d")
    output.to_csv(path, index=False, lineterminator="\n", float_format="%.17g")
    return _sha256_file(path)


def _resolve_provider_paths(provider_root: Path) -> tuple[Path, Path]:
    candidates = [provider_root, provider_root / "provider_a"]
    for candidate in candidates:
        csv_root = candidate / "data" / "csv_source"
        manifest = candidate / "data" / "providers" / "us" / "provider_manifest.json"
        if csv_root.is_dir() and manifest.is_file():
            return csv_root.resolve(), manifest.resolve()
    raise FileNotFoundError(
        "provider root must contain data/csv_source and data/providers/us/provider_manifest.json"
    )


def _resolve_reproduction_root(reproduction_root: Path) -> Path:
    candidates = [
        reproduction_root,
        reproduction_root / "evidence" / "us_x1_1_deterministic_reproduction_v1",
    ]
    for candidate in candidates:
        if (candidate / "deterministic_reproduction.json").is_file():
            return candidate.resolve()
    raise FileNotFoundError("reproduction root must contain deterministic_reproduction.json")


def _rank_scores(scores: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for date, group in scores.groupby("datetime", sort=True):
        ranked = group.sort_values(
            ["score", "instrument"],
            ascending=[False, True],
            kind="mergesort",
        ).copy()
        ranked["rank"] = np.arange(1, len(ranked) + 1, dtype=int)
        ranked["datetime"] = pd.Timestamp(date)
        rows.append(ranked)
    if not rows:
        raise ValueError("score ledger is empty")
    return pd.concat(rows, ignore_index=True)


def _load_scores(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = ["datetime", "instrument", "score"]
    if list(frame.columns) != required:
        raise ValueError(f"score ledger columns must equal {required}: {path}")
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="raise").dt.normalize()
    frame["instrument"] = frame["instrument"].astype(str)
    frame["score"] = pd.to_numeric(frame["score"], errors="raise")
    if frame.duplicated(["datetime", "instrument"]).any():
        raise ValueError(f"duplicate score rows: {path}")
    if not np.isfinite(frame["score"].to_numpy(dtype=float)).all():
        raise ValueError(f"non-finite score rows: {path}")
    return frame.sort_values(["datetime", "instrument"], kind="mergesort").reset_index(drop=True)


def _load_prices(
    csv_root: Path,
    symbols: list[str],
    provider_manifest: dict[str, Any],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    expected_files = {
        str(row["name"]): str(row["sha256"])
        for row in provider_manifest.get("source_csvs", [])
        if isinstance(row, dict) and "name" in row and "sha256" in row
    }
    rows: list[pd.DataFrame] = []
    identity_rows: list[dict[str, Any]] = []
    for symbol in sorted(set(symbols)):
        path = csv_root / f"{symbol}.csv"
        if not path.is_file():
            raise FileNotFoundError(f"missing provider source CSV: {path}")
        observed_sha = _sha256_file(path)
        expected_sha = expected_files.get(path.name)
        match = expected_sha == observed_sha
        identity_rows.append(
            {
                "check_type": "source_csv_sha256",
                "scope": symbol,
                "expected": expected_sha,
                "observed": observed_sha,
                "passed": bool(match),
            }
        )
        if not match:
            raise ValueError(f"source CSV identity mismatch: {path.name}")
        frame = pd.read_csv(path)
        required = {"date", "close"}
        if not required.issubset(frame.columns):
            raise ValueError(f"missing required price columns in {path}")
        frame = frame.loc[:, ["date", "close"]].copy()
        frame["datetime"] = pd.to_datetime(frame.pop("date"), errors="raise").dt.normalize()
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.sort_values("datetime", kind="mergesort").reset_index(drop=True)
        frame["exit_date"] = frame["datetime"].shift(-HORIZON_SESSIONS)
        frame["exit_close"] = frame["close"].shift(-HORIZON_SESSIONS)
        frame["forward_return"] = frame["exit_close"] / frame["close"] - 1.0
        frame["instrument"] = symbol
        rows.append(frame)
    return pd.concat(rows, ignore_index=True), identity_rows


def _max_drawdown(period_returns: pd.Series) -> float:
    equity = (1.0 + period_returns.astype(float)).cumprod()
    if not len(equity):
        return 0.0
    running_peak = np.maximum.accumulate(np.concatenate(([1.0], equity.to_numpy(dtype=float))))[1:]
    drawdown = equity.to_numpy(dtype=float) / running_peak - 1.0
    return float(drawdown.min())


def _compound(values: pd.Series | list[float]) -> float:
    array = np.asarray(values, dtype=float)
    return float(np.prod(1.0 + array) - 1.0)


def _expected_window(summary: dict[str, Any], window: str) -> dict[str, Any]:
    for row in summary["run_a"]["windows"]:
        if row["window"] == window:
            return dict(row["cost_stress"][str(BASE_COST_BPS)])
    raise KeyError(window)


def _window_hashes(summary: dict[str, Any], window: str) -> dict[str, str]:
    for row in summary["window_determinism"]:
        if row["window"] == window:
            return {str(k): str(v) for k, v in row["run_a"].items()}
    raise KeyError(window)


def _semantic_rank_check(observed: pd.DataFrame, expected: pd.DataFrame) -> None:
    columns = ["datetime", "instrument", "rank"]
    pd.testing.assert_frame_equal(
        observed[columns].reset_index(drop=True),
        expected[columns].reset_index(drop=True),
        check_exact=True,
        check_dtype=False,
    )
    if not np.allclose(
        observed["score"].to_numpy(dtype=float),
        expected["score"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-15,
    ):
        raise ValueError("rank ledger score values differ")


def _build_window(
    *,
    window: str,
    reproduction_root: Path,
    prices: pd.DataFrame,
    summary: dict[str, Any],
) -> dict[str, Any]:
    ledger_root = reproduction_root / "ledgers" / "a" / window
    score_path = ledger_root / "scores.csv"
    rank_path = ledger_root / "ranks.csv"
    selection_path = ledger_root / "top15_selections.csv"
    expected_hashes = _window_hashes(summary, window)
    identity_rows: list[dict[str, Any]] = []
    for check_name, path, key in (
        ("score_ledger_sha256", score_path, "score_sha256"),
        ("rank_ledger_sha256", rank_path, "rank_sha256"),
        ("source_top15_ledger_sha256", selection_path, "top15_selection_sha256"),
    ):
        observed = _sha256_file(path)
        expected = expected_hashes[key]
        identity_rows.append(
            {
                "check_type": check_name,
                "scope": window,
                "expected": expected,
                "observed": observed,
                "passed": observed == expected,
            }
        )
        if observed != expected:
            raise ValueError(f"{check_name} mismatch for {window}")

    scores = _load_scores(score_path)
    source_ranks = pd.read_csv(rank_path)
    source_ranks["datetime"] = pd.to_datetime(
        source_ranks["datetime"], errors="raise"
    ).dt.normalize()
    source_ranks["instrument"] = source_ranks["instrument"].astype(str)
    source_ranks["score"] = pd.to_numeric(source_ranks["score"], errors="raise")
    source_ranks["rank"] = pd.to_numeric(source_ranks["rank"], errors="raise").astype(int)
    recomputed_ranks = _rank_scores(scores)
    _semantic_rank_check(recomputed_ranks, source_ranks)
    identity_rows.append(
        {
            "check_type": "rank_semantic_rebuild",
            "scope": window,
            "expected": "exact instruments/ranks; score atol <= 1e-15",
            "observed": "matched",
            "passed": True,
        }
    )

    window_prices = prices.loc[prices["instrument"].isin(scores["instrument"].unique())]
    aligned = scores.merge(
        window_prices,
        on=["datetime", "instrument"],
        how="left",
        validate="one_to_one",
    )
    aligned["economic_eligible"] = np.isfinite(aligned["forward_return"].to_numpy(dtype=float))
    economic = aligned.loc[aligned["economic_eligible"]].copy()
    economic_ranks = _rank_scores(economic[["datetime", "instrument", "score"]])
    economic = economic.drop(columns=["score"]).merge(
        economic_ranks,
        on=["datetime", "instrument"],
        how="inner",
        validate="one_to_one",
    )
    economic = economic.sort_values(
        ["datetime", "rank", "instrument"], kind="mergesort"
    ).reset_index(drop=True)
    dates = [pd.Timestamp(value) for value in sorted(economic["datetime"].unique())]
    rebalance_dates = dates[::REBALANCE_SESSIONS]

    daily = aligned.merge(
        recomputed_ranks[["datetime", "instrument", "rank"]],
        on=["datetime", "instrument"],
        how="left",
        validate="one_to_one",
    )
    daily["source_top15"] = daily["rank"] <= TOPK
    daily["window"] = window
    daily = daily[
        [
            "window",
            "datetime",
            "instrument",
            "score",
            "rank",
            "source_top15",
            "economic_eligible",
            "close",
            "exit_date",
            "exit_close",
            "forward_return",
        ]
    ].sort_values(["datetime", "rank", "instrument"], kind="mergesort")

    qqq = prices.loc[prices["instrument"] == "QQQ"].set_index("datetime")
    previous_weights: dict[str, float] = {}
    period_rows: list[dict[str, Any]] = []
    holding_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    rebalance_signal_rows: list[dict[str, Any]] = []
    attribution_rows: list[dict[str, Any]] = []

    for period_index, rebalance_date in enumerate(rebalance_dates, start=1):
        day = economic.loc[economic["datetime"] == rebalance_date].copy()
        selected = day.sort_values(["rank", "instrument"], kind="mergesort").head(TOPK)
        if len(selected) != TOPK:
            raise ValueError(f"fewer than {TOPK} eligible names on {rebalance_date}")
        current_weights = {str(name): 1.0 / TOPK for name in selected["instrument"]}
        union = sorted(set(previous_weights) | set(current_weights))
        absolute_weight_change = sum(
            abs(current_weights.get(name, 0.0) - previous_weights.get(name, 0.0)) for name in union
        )
        turnover = 0.5 * absolute_weight_change
        transaction_cost = turnover * BASE_COST_BPS / 10000.0

        qqq_row = qqq.loc[rebalance_date]
        benchmark_return = float(qqq_row["forward_return"])
        holding_end_date = pd.Timestamp(qqq_row["exit_date"])
        gross_return = float(selected["forward_return"].mean())
        net_return = gross_return - transaction_cost
        excess_return = net_return - benchmark_return

        selected_map = selected.set_index("instrument")
        trade_cost_by_name: dict[str, float] = {}
        for instrument in union:
            previous_weight = float(previous_weights.get(instrument, 0.0))
            target_weight = float(current_weights.get(instrument, 0.0))
            delta = target_weight - previous_weight
            if previous_weight == 0.0 and target_weight > 0.0:
                action = "BUY"
            elif previous_weight > 0.0 and target_weight == 0.0:
                action = "SELL"
            elif abs(delta) <= 1e-15:
                action = "HOLD"
            elif delta > 0:
                action = "INCREASE"
            else:
                action = "DECREASE"
            allocated_cost = (
                transaction_cost * abs(delta) / absolute_weight_change
                if absolute_weight_change > 0
                else 0.0
            )
            trade_cost_by_name[instrument] = allocated_cost
            row = selected_map.loc[instrument] if instrument in selected_map.index else None
            trade_rows.append(
                {
                    "window": window,
                    "period_index": period_index,
                    "rebalance_date": rebalance_date,
                    "holding_end_date": holding_end_date,
                    "instrument": instrument,
                    "action": action,
                    "rank": int(row["rank"]) if row is not None else np.nan,
                    "score": float(row["score"]) if row is not None else np.nan,
                    "previous_weight": previous_weight,
                    "target_weight": target_weight,
                    "weight_delta": delta,
                    "absolute_weight_change": abs(delta),
                    "allocated_transaction_cost": allocated_cost,
                }
            )

        for _, row in selected.iterrows():
            instrument = str(row["instrument"])
            gross_contribution = float(row["forward_return"]) / TOPK
            trading_cost = float(trade_cost_by_name.get(instrument, 0.0))
            net_contribution = gross_contribution - trading_cost
            common = {
                "window": window,
                "period_index": period_index,
                "rebalance_date": rebalance_date,
                "holding_end_date": holding_end_date,
                "instrument": instrument,
                "rank": int(row["rank"]),
                "score": float(row["score"]),
                "entry_close": float(row["close"]),
                "exit_close": float(row["exit_close"]),
                "forward_return": float(row["forward_return"]),
                "target_weight": 1.0 / TOPK,
                "previous_weight": float(previous_weights.get(instrument, 0.0)),
                "weight_delta": 1.0 / TOPK - float(previous_weights.get(instrument, 0.0)),
            }
            common["action"] = "BUY" if common["previous_weight"] == 0.0 else "HOLD"
            rebalance_signal_rows.append(dict(common))
            holding_rows.append(dict(common))
            attribution_rows.append(
                {
                    **common,
                    "gross_contribution": gross_contribution,
                    "allocated_transaction_cost": trading_cost,
                    "net_contribution": net_contribution,
                    "qqq_return": benchmark_return,
                    "qqq_regime": "QQQ_UP" if benchmark_return >= 0 else "QQQ_DOWN",
                }
            )

        period_rows.append(
            {
                "window": window,
                "period_index": period_index,
                "rebalance_date": rebalance_date,
                "holding_end_date": holding_end_date,
                "n_holdings": TOPK,
                "gross_return": gross_return,
                "turnover": turnover,
                "transaction_cost": transaction_cost,
                "net_return": net_return,
                "qqq_return": benchmark_return,
                "excess_return": excess_return,
                "entered_names": sum(
                    previous_weights.get(name, 0.0) == 0.0 for name in current_weights
                ),
                "exited_names": sum(
                    current_weights.get(name, 0.0) == 0.0 for name in previous_weights
                ),
                "retained_names": len(set(previous_weights) & set(current_weights)),
            }
        )
        previous_weights = current_weights

    periods = pd.DataFrame(period_rows)
    periods["strategy_equity"] = (1.0 + periods["net_return"]).cumprod()
    periods["qqq_equity"] = (1.0 + periods["qqq_return"]).cumprod()
    strategy_peak = np.maximum.accumulate(
        np.concatenate(([1.0], periods["strategy_equity"].to_numpy(dtype=float)))
    )[1:]
    qqq_peak = np.maximum.accumulate(
        np.concatenate(([1.0], periods["qqq_equity"].to_numpy(dtype=float)))
    )[1:]
    periods["strategy_drawdown"] = (
        periods["strategy_equity"].to_numpy(dtype=float) / strategy_peak - 1.0
    )
    periods["qqq_drawdown"] = periods["qqq_equity"].to_numpy(dtype=float) / qqq_peak - 1.0

    expected = _expected_window(summary, window)
    observed = {
        "total_return": _compound(periods["net_return"]),
        "benchmark_return": _compound(periods["qqq_return"]),
        "excess_return": _compound(periods["net_return"]) - _compound(periods["qqq_return"]),
        "turnover": float(periods["turnover"].sum()),
        "costs": float(periods["transaction_cost"].sum()),
        "max_drawdown": _max_drawdown(periods["net_return"]),
        "n_periods": int(len(periods)),
    }
    tolerances = {
        "total_return": 1e-6,
        "benchmark_return": 1e-6,
        "excess_return": 1e-6,
        "turnover": 1e-6,
        "costs": 1e-6,
        "max_drawdown": 1e-6,
        "n_periods": 0.0,
    }
    reproduction_rows: list[dict[str, Any]] = []
    for metric, actual in observed.items():
        expected_value = float(expected[metric]) if metric != "n_periods" else int(expected[metric])
        delta = float(actual) - float(expected_value)
        passed = abs(delta) <= tolerances[metric]
        reproduction_rows.append(
            {
                "scope": window,
                "metric": metric,
                "expected": expected_value,
                "observed": actual,
                "delta": delta,
                "tolerance": tolerances[metric],
                "passed": passed,
            }
        )
        if not passed:
            raise ValueError(
                f"Experiment 007 mismatch for {window}/{metric}: {actual} != {expected_value}"
            )

    return {
        "identity_rows": identity_rows,
        "daily": daily.reset_index(drop=True),
        "rebalance_signals": pd.DataFrame(rebalance_signal_rows),
        "trades": pd.DataFrame(trade_rows),
        "holdings": pd.DataFrame(holding_rows),
        "periods": periods,
        "attribution": pd.DataFrame(attribution_rows),
        "reproduction_rows": reproduction_rows,
        "observed_summary": observed,
    }


def _security_summary(attribution: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    gross = attribution.groupby("instrument", as_index=False).agg(
        periods_held=("period_index", "count"),
        windows_held=("window", "nunique"),
        gross_contribution=("gross_contribution", "sum"),
        holding_cost=("allocated_transaction_cost", "sum"),
        average_forward_return=("forward_return", "mean"),
        win_rate=("forward_return", lambda values: float((values > 0).mean())),
        average_rank=("rank", "mean"),
    )
    all_costs = (
        trades.groupby("instrument", as_index=False)["allocated_transaction_cost"]
        .sum()
        .rename(columns={"allocated_transaction_cost": "total_trading_cost"})
    )
    result = gross.merge(all_costs, on="instrument", how="outer").fillna(0.0)
    result["net_contribution"] = result["gross_contribution"] - result["total_trading_cost"]
    return result.sort_values("net_contribution", ascending=False, kind="mergesort").reset_index(
        drop=True
    )


def _window_summary(periods: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for window, group in periods.groupby("window", sort=False):
        gross = _compound(group["gross_return"])
        net = _compound(group["net_return"])
        benchmark = _compound(group["qqq_return"])
        rows.append(
            {
                "window": window,
                "gross_selection_return": gross,
                "transaction_cost_drag": gross - net,
                "net_strategy_return": net,
                "qqq_return": benchmark,
                "simple_excess_return": net - benchmark,
                "turnover": float(group["turnover"].sum()),
                "transaction_cost": float(group["transaction_cost"].sum()),
                "max_drawdown": _max_drawdown(group["net_return"]),
                "positive_periods": int((group["net_return"] > 0).sum()),
                "periods": int(len(group)),
            }
        )
    return pd.DataFrame(rows)


def _regime_summary(periods: pd.DataFrame) -> pd.DataFrame:
    frame = periods.copy()
    frame["qqq_regime"] = np.where(frame["qqq_return"] >= 0, "QQQ_UP", "QQQ_DOWN")
    rows: list[dict[str, Any]] = []
    for regime, group in frame.groupby("qqq_regime", sort=True):
        rows.append(
            {
                "qqq_regime": regime,
                "periods": int(len(group)),
                "gross_selection_return": _compound(group["gross_return"]),
                "net_strategy_return": _compound(group["net_return"]),
                "qqq_return": _compound(group["qqq_return"]),
                "arithmetic_excess_contribution": float(group["excess_return"].sum()),
                "turnover": float(group["turnover"].sum()),
                "transaction_cost": float(group["transaction_cost"].sum()),
            }
        )
    return pd.DataFrame(rows)


def build_complete_backtest(
    provider_root: Path | str,
    reproduction_root: Path | str,
    output_dir: Path | str,
) -> BacktestAudit:
    provider_root = Path(provider_root).resolve()
    reproduction_root = _resolve_reproduction_root(Path(reproduction_root).resolve())
    output_dir = Path(output_dir).resolve()
    csv_root, provider_manifest_path = _resolve_provider_paths(provider_root)
    provider_manifest = _load_json(provider_manifest_path)
    summary = _load_json(reproduction_root / "deterministic_reproduction.json")

    identity_rows: list[dict[str, Any]] = []
    observed_provider = str(provider_manifest.get("provider_identity_sha256", ""))
    identity_rows.append(
        {
            "check_type": "provider_identity_sha256",
            "scope": "US provider",
            "expected": EXPECTED_PROVIDER_IDENTITY,
            "observed": observed_provider,
            "passed": observed_provider == EXPECTED_PROVIDER_IDENTITY,
        }
    )
    if observed_provider != EXPECTED_PROVIDER_IDENTITY:
        raise ValueError("unexpected deterministic provider identity")
    observed_parameter = str(summary["parameter_identity"]["identity_sha256"])
    identity_rows.append(
        {
            "check_type": "parameter_identity_sha256",
            "scope": "US x1.1",
            "expected": EXPECTED_PARAMETER_IDENTITY,
            "observed": observed_parameter,
            "passed": observed_parameter == EXPECTED_PARAMETER_IDENTITY,
        }
    )
    if observed_parameter != EXPECTED_PARAMETER_IDENTITY:
        raise ValueError("unexpected US x1.1 parameter identity")
    if tuple(summary.get("decision_windows", [])) != WINDOWS:
        raise ValueError("unexpected Experiment 007 decision windows")
    if "2026H1" not in summary.get("consumed_reporting_windows_excluded", []):
        raise ValueError("2026H1 exclusion is missing")

    score_symbols: set[str] = {"QQQ"}
    for window in WINDOWS:
        scores = _load_scores(reproduction_root / "ledgers" / "a" / window / "scores.csv")
        score_symbols.update(scores["instrument"].unique())
    prices, source_identity_rows = _load_prices(csv_root, sorted(score_symbols), provider_manifest)
    identity_rows.extend(source_identity_rows)

    window_results = [
        _build_window(
            window=window,
            reproduction_root=reproduction_root,
            prices=prices,
            summary=summary,
        )
        for window in WINDOWS
    ]
    for result in window_results:
        identity_rows.extend(result["identity_rows"])

    daily = pd.concat([result["daily"] for result in window_results], ignore_index=True)
    rebalance_signals = pd.concat(
        [result["rebalance_signals"] for result in window_results], ignore_index=True
    )
    trades = pd.concat([result["trades"] for result in window_results], ignore_index=True)
    holdings = pd.concat([result["holdings"] for result in window_results], ignore_index=True)
    periods = pd.concat([result["periods"] for result in window_results], ignore_index=True)
    attribution = pd.concat([result["attribution"] for result in window_results], ignore_index=True)
    reproduction = pd.DataFrame(
        [row for result in window_results for row in result["reproduction_rows"]]
    )

    window_attribution = _window_summary(periods)
    security_attribution = _security_summary(attribution, trades)
    regime_attribution = _regime_summary(periods)

    observed_strategy = _compound(window_attribution["net_strategy_return"])
    observed_benchmark = _compound(window_attribution["qqq_return"])
    observed_relative = (1.0 + observed_strategy) / (1.0 + observed_benchmark) - 1.0
    expected_cost = summary["run_a"]["cost_stress"][str(BASE_COST_BPS)]
    aggregate_rows = [
        (
            "compounded_strategy_return",
            observed_strategy,
            float(expected_cost["compounded_strategy_return"]),
        ),
        (
            "compounded_benchmark_return",
            observed_benchmark,
            float(expected_cost["compounded_benchmark_return"]),
        ),
        (
            "compounded_relative_excess_return",
            observed_relative,
            float(expected_cost["compounded_relative_excess_return"]),
        ),
    ]
    for metric, observed, expected in aggregate_rows:
        delta = observed - expected
        passed = abs(delta) <= 2e-6
        reproduction.loc[len(reproduction)] = {
            "scope": "aggregate",
            "metric": metric,
            "expected": expected,
            "observed": observed,
            "delta": delta,
            "tolerance": 2e-6,
            "passed": passed,
        }
        if not passed:
            raise ValueError(f"aggregate Experiment 007 mismatch: {metric}")

    identity_checks = pd.DataFrame(identity_rows)
    if not identity_checks["passed"].all() or not reproduction["passed"].all():
        raise ValueError("audit contains failed checks")

    output_dir.mkdir(parents=True, exist_ok=True)
    exports = {
        "identity_checks.csv": identity_checks,
        "daily_signals.csv": daily,
        "rebalance_signals.csv": rebalance_signals,
        "trade_ledger.csv": trades,
        "holdings.csv": holdings,
        "period_returns.csv": periods,
        "security_attribution.csv": security_attribution,
        "window_attribution.csv": window_attribution,
        "regime_attribution.csv": regime_attribution,
        "reproduction_summary.csv": reproduction,
    }
    export_hashes = {name: _write_csv(output_dir / name, frame) for name, frame in exports.items()}
    manifest = {
        "schema_version": "1.0",
        "decision": "complete_backtest_reproduced",
        "model_id": "us_x1_1",
        "research_only": True,
        "trade_ready": False,
        "provider_identity_sha256": observed_provider,
        "parameter_identity_sha256": observed_parameter,
        "source_artifacts": {
            "provider_workflow_run": 30742690159,
            "provider_artifact_id": 8831837784,
            "reproduction_workflow_run": 30743067256,
            "reproduction_artifact_id": 8831960659,
        },
        "windows": list(WINDOWS),
        "excluded_windows": ["2026H1"],
        "portfolio_contract": {
            "topk": TOPK,
            "weighting": "equal_weight",
            "horizon_sessions": HORIZON_SESSIONS,
            "rebalance_sessions": REBALANCE_SESSIONS,
            "cost_bps": BASE_COST_BPS,
            "turnover_formula": "0.5 * sum(abs(target_weight - previous_weight))",
            "return_expression": "Ref($close, -10) / $close - 1",
        },
        "row_counts": {name: int(len(frame)) for name, frame in exports.items()},
        "aggregate_result": {
            "exact_ledger_compounded_strategy_return": observed_strategy,
            "exact_ledger_compounded_benchmark_return": observed_benchmark,
            "exact_ledger_compounded_relative_excess_return": observed_relative,
            "experiment_007_reported_compounded_strategy_return": float(
                expected_cost["compounded_strategy_return"]
            ),
            "experiment_007_reported_compounded_benchmark_return": float(
                expected_cost["compounded_benchmark_return"]
            ),
            "experiment_007_reported_compounded_relative_excess_return": float(
                expected_cost["compounded_relative_excess_return"]
            ),
            "aggregate_rounding_note": (
                "Experiment 007 aggregates compound six-decimal window metrics; "
                "exact ledger compounding differs by less than 2e-6."
            ),
            "worst_window_drawdown": float(window_attribution["max_drawdown"].min()),
            "total_turnover": float(periods["turnover"].sum()),
            "total_transaction_cost": float(periods["transaction_cost"].sum()),
        },
        "all_identity_checks_passed": True,
        "all_reproduction_checks_passed": True,
        "exports_sha256": export_hashes,
    }
    _write_json(output_dir / "audit_manifest.json", manifest)
    return BacktestAudit(
        manifest=manifest,
        identity_checks=identity_checks,
        daily_signals=daily,
        rebalance_signals=rebalance_signals,
        trades=trades,
        holdings=holdings,
        periods=periods,
        security_attribution=security_attribution,
        window_attribution=window_attribution,
        regime_attribution=regime_attribution,
        reproduction_summary=reproduction,
    )
