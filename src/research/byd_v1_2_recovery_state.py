"""Governed BYD V1.2 recovery/reversal state-model research.

The model is intentionally a single pre-registered, interpretable state machine.
It consumes only the sealed BYD canonical v1 data identity and never treats the
already-observed history through 2026-08-03 as a fresh holdout.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

CANONICAL_SCHEMA = "byd_canonical_adjusted_ohlcv_v1"
CANONICAL_ADJUSTED_SHA256 = (
    "0cde8d3f1b6a94406532c6e8e04fabdc20d7830d0a58034aa489e87f94b77960"
)
CANONICAL_MANIFEST_SHA256 = (
    "06202b594b036b0c815e4ffb46e9f3d14ba647d699aad0fd927f1665142a363e"
)
CANONICAL_CUTOFF = "2026-08-03"
OPEN_LABEL_POLICY = (
    "entry_and_exit_open_must_be_independently_confirmed_and_not_quarantined"
)

SHORTLIST_FACTORS = (
    "drawdown_252",
    "mom_120",
    "open_return_autocorr_20",
    "short_continuation_long_reversal",
    "open_mom_120",
    "momentum_accel_20_60",
    "skip_recent_20_60",
    "drawdown120_x_rebound20",
    "intraday_range",
    "trend_slope_120",
    "drawdown252_x_rebound60",
    "distance_from_low_20",
    "skip_recent_20_120",
    "skip_recent_10_40",
    "momentum_accel_10_40",
    "range_position_252",
    "distance_from_low_120",
)

MODEL_FACTORS = (
    "drawdown_252",
    "mom_120",
    "distance_from_low_20",
    "momentum_accel_20_60",
    "open_return_autocorr_20",
)

FACTOR_ORIENTATION = {
    "drawdown_252": -1.0,
    "mom_120": -1.0,
    "distance_from_low_20": 1.0,
    "momentum_accel_20_60": 1.0,
    "open_return_autocorr_20": 1.0,
}

MODEL_RULES = {
    "core_position": 0.75,
    "full_position": 1.00,
    "trend_expansion_drawdown_floor": -0.10,
    "recovery_drawdown_ceiling": -0.15,
    "recovery_distance_from_low_20_floor": 0.05,
    "deterioration_distance_from_low_20_ceiling": 0.03,
}

EVALUATION_WINDOWS = {
    "full_history": ("2012-01-01", CANONICAL_CUTOFF),
    "development": ("2012-01-01", "2022-12-31"),
    "fixed_validation": ("2023-01-01", "2024-12-31"),
    "retrospective_2025_plus": ("2025-01-01", CANONICAL_CUTOFF),
}


@dataclass(frozen=True)
class CanonicalResearchData:
    adjusted: pd.DataFrame
    sessions: pd.DataFrame
    manifest: dict[str, Any]


@dataclass(frozen=True)
class StrategyResult:
    name: str
    daily: pd.DataFrame
    trades: pd.DataFrame


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dataframe_sha256(frame: pd.DataFrame) -> str:
    normalised = frame.copy()
    for column in normalised.columns:
        if pd.api.types.is_datetime64_any_dtype(normalised[column]):
            normalised[column] = normalised[column].dt.strftime("%Y-%m-%d")
    payload = normalised.to_csv(
        index=False,
        float_format="%.12f",
        lineterminator="\n",
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_canonical_snapshot(root: str | Path) -> CanonicalResearchData:
    root = Path(root)
    manifest_path = root / "manifest.json"
    adjusted_path = root / "adjusted_ohlcv.csv"
    session_path = root / "session_audit.csv"
    for path in (manifest_path, adjusted_path, session_path):
        if not path.exists():
            raise FileNotFoundError(f"canonical snapshot missing {path.name}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    exact = {
        "schema_version": CANONICAL_SCHEMA,
        "adjusted_sha256": CANONICAL_ADJUSTED_SHA256,
        "manifest_sha256": CANONICAL_MANIFEST_SHA256,
        "cutoff": CANONICAL_CUTOFF,
        "open_label_policy": OPEN_LABEL_POLICY,
        "data_quality_status": "canonical_v1_pass",
        "cross_provider_stitching": False,
    }
    for key, expected in exact.items():
        if manifest.get(key) != expected:
            raise RuntimeError(
                f"canonical contract mismatch for {key}: "
                f"{manifest.get(key)!r} != {expected!r}"
            )

    adjusted = pd.read_csv(adjusted_path, parse_dates=["date"])
    sessions = pd.read_csv(session_path, parse_dates=["date"])
    if dataframe_sha256(adjusted) != CANONICAL_ADJUSTED_SHA256:
        raise RuntimeError("adjusted_ohlcv.csv does not match the sealed canonical SHA")
    if len(adjusted) != int(manifest["rows"]):
        raise RuntimeError("canonical row count drifted")
    if adjusted["date"].max().strftime("%Y-%m-%d") != CANONICAL_CUTOFF:
        raise RuntimeError("canonical adjusted history does not end at the frozen cutoff")
    if sessions["date"].duplicated().any():
        raise RuntimeError("session audit contains duplicate dates")
    required_session = {"date", "open_research_eligible"}
    if not required_session.issubset(sessions.columns):
        raise RuntimeError("session audit is missing research-eligibility fields")
    sessions["open_research_eligible"] = sessions["open_research_eligible"].astype(bool)
    return CanonicalResearchData(
        adjusted=adjusted.sort_values("date").reset_index(drop=True),
        sessions=sessions.sort_values("date").reset_index(drop=True),
        manifest=manifest,
    )


def _rolling_slope(series: pd.Series, window: int) -> pd.Series:
    x = np.arange(window, dtype=float)
    x -= x.mean()
    denominator = float(np.square(x).sum())

    def slope(values: np.ndarray) -> float:
        y = np.log(np.asarray(values, dtype=float))
        return float(np.dot(x, y - y.mean()) / denominator)

    return series.rolling(window).apply(slope, raw=True)


def build_research_dataset(
    adjusted_bars: pd.DataFrame,
    sessions: pd.DataFrame,
) -> pd.DataFrame:
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(adjusted_bars.columns))
    if missing:
        raise ValueError(f"adjusted bars missing columns: {missing}")
    frame = adjusted_bars.copy(deep=True)
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    frame = (
        frame.sort_values("date")
        .drop_duplicates("date", keep="last")
        .set_index("date")
    )
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)

    session = sessions.copy(deep=True)
    session["date"] = pd.to_datetime(session["date"], errors="raise").dt.normalize()
    session = session.set_index("date").reindex(frame.index)
    if session["open_research_eligible"].isna().any():
        raise ValueError("session audit does not cover every adjusted bar")
    frame["open_research_eligible"] = session["open_research_eligible"].astype(bool)

    close = frame["close"]
    open_ = frame["open"]
    high = frame["high"]
    low = frame["low"]
    open_return = open_.pct_change()
    daily_return = close.pct_change()

    frame["mom_2"] = close.pct_change(2)
    frame["mom_120"] = close.pct_change(120)
    frame["open_mom_120"] = open_.pct_change(120)
    frame["skip_recent_20_60"] = close.shift(20).pct_change(40)
    frame["skip_recent_20_120"] = close.shift(20).pct_change(100)
    frame["skip_recent_10_40"] = close.shift(10).pct_change(30)
    frame["momentum_accel_20_60"] = close.pct_change(20) - close.pct_change(60)
    frame["momentum_accel_10_40"] = close.pct_change(10) - close.pct_change(40)
    frame["short_continuation_long_reversal"] = frame["mom_2"] - frame["mom_120"]

    high120 = close.rolling(120).max()
    low20 = close.rolling(20).min()
    low60 = close.rolling(60).min()
    low120 = close.rolling(120).min()
    high252 = close.rolling(252).max()
    low252 = close.rolling(252).min()
    frame["drawdown_120"] = close / high120 - 1.0
    frame["drawdown_252"] = close / high252 - 1.0
    frame["distance_from_low_20"] = close / low20 - 1.0
    frame["distance_from_low_60"] = close / low60 - 1.0
    frame["distance_from_low_120"] = close / low120 - 1.0
    frame["range_position_252"] = (
        (close - low252) / (high252 - low252).replace(0.0, np.nan)
    )
    frame["drawdown120_x_rebound20"] = (
        -frame["drawdown_120"] * frame["distance_from_low_20"]
    )
    frame["drawdown252_x_rebound60"] = (
        -frame["drawdown_252"] * frame["distance_from_low_60"]
    )
    frame["trend_slope_120"] = _rolling_slope(close, 120)
    frame["open_return_autocorr_20"] = open_return.rolling(20).corr(
        open_return.shift(1)
    )
    frame["intraday_range"] = (high - low) / close

    frame["sma_60"] = close.rolling(60).mean()
    frame["sma_120"] = close.rolling(120).mean()
    frame["sma_200"] = close.rolling(200).mean()
    frame["mom_20"] = close.pct_change(20)
    frame["mom_60"] = close.pct_change(60)
    frame["realized_vol_60"] = daily_return.rolling(60).std()
    frame["historical_vol_median"] = (
        frame["realized_vol_60"]
        .rolling(756, min_periods=252)
        .median()
        .shift(1)
    )

    bull = close.gt(frame["sma_200"]) & frame["sma_60"].gt(frame["sma_200"])
    bear = close.lt(frame["sma_200"]) & frame["sma_60"].lt(frame["sma_200"])
    frame["market_state"] = np.select(
        [bull, bear],
        ["bull", "bear"],
        default="sideways",
    )
    frame["vol_state"] = np.where(
        frame["realized_vol_60"] > frame["historical_vol_median"],
        "high",
        "low",
    )

    for horizon in (5, 10, 20):
        entry_eligible = (
            frame["open_research_eligible"].shift(-1).fillna(False).astype(bool)
        )
        exit_eligible = (
            frame["open_research_eligible"]
            .shift(-(horizon + 1))
            .fillna(False)
            .astype(bool)
        )
        label = open_.shift(-(horizon + 1)) / open_.shift(-1) - 1.0
        frame[f"forward_open_return_{horizon}"] = label.where(
            entry_eligible & exit_eligible
        )
    return frame


def cluster_shortlist_factors(
    dataset: pd.DataFrame,
    *,
    threshold: float = 0.75,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    missing = sorted(set(SHORTLIST_FACTORS) - set(dataset.columns))
    if missing:
        raise ValueError(f"shortlist factors missing from dataset: {missing}")
    correlation = dataset[list(SHORTLIST_FACTORS)].corr(method="spearman")
    unseen = set(SHORTLIST_FACTORS)
    rows: list[dict[str, Any]] = []
    cluster_id = 0
    while unseen:
        seed = sorted(unseen)[0]
        component = {seed}
        frontier = [seed]
        while frontier:
            current = frontier.pop()
            neighbours = {
                factor
                for factor in unseen
                if factor != current
                and abs(float(correlation.loc[current, factor])) >= threshold
            }
            new = neighbours - component
            component.update(new)
            frontier.extend(sorted(new))
        unseen -= component
        cluster_id += 1
        for factor in sorted(component):
            rows.append(
                {
                    "cluster_id": cluster_id,
                    "factor": factor,
                    "is_model_representative": factor in MODEL_FACTORS,
                    "orientation": FACTOR_ORIENTATION.get(factor, np.nan),
                }
            )
    clusters = pd.DataFrame(rows).sort_values(["cluster_id", "factor"])
    representative_counts = clusters.groupby("cluster_id")[
        "is_model_representative"
    ].sum()
    if (representative_counts > 2).any():
        bad = representative_counts[representative_counts > 2].to_dict()
        raise RuntimeError(
            f"too many model representatives in correlation cluster: {bad}"
        )
    return clusters.reset_index(drop=True), correlation


def conditional_ic_table(dataset: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    states = {
        "all": pd.Series(True, index=dataset.index),
        **{
            f"market_{state}": dataset["market_state"].eq(state)
            for state in ("bull", "bear", "sideways")
        },
        **{
            f"vol_{state}": dataset["vol_state"].eq(state)
            for state in ("high", "low")
        },
    }
    for factor in MODEL_FACTORS:
        orientation = FACTOR_ORIENTATION[factor]
        for horizon in (5, 10, 20):
            label = f"forward_open_return_{horizon}"
            for state_name, mask in states.items():
                sample = dataset.loc[mask, [factor, label]].dropna()
                ic = (
                    float(sample[factor].corr(sample[label], method="spearman"))
                    if len(sample) >= 30
                    else float("nan")
                )
                rows.append(
                    {
                        "factor": factor,
                        "orientation": orientation,
                        "horizon": horizon,
                        "state": state_name,
                        "samples": int(len(sample)),
                        "raw_spearman_ic": ic,
                        "oriented_spearman_ic": ic * orientation,
                    }
                )
    return pd.DataFrame(rows)


def _stateful_binary(entry: pd.Series, exit_: pd.Series) -> pd.Series:
    active = False
    values: list[float] = []
    for enter_now, exit_now in zip(
        entry.fillna(False),
        exit_.fillna(False),
        strict=True,
    ):
        if active and bool(exit_now):
            active = False
        elif not active and bool(enter_now):
            active = True
        values.append(1.0 if active else 0.0)
    return pd.Series(values, index=entry.index, dtype=float)


def build_v1_2_decision_position(dataset: pd.DataFrame) -> pd.Series:
    rules = MODEL_RULES
    trend_expansion = (
        dataset["drawdown_252"] > rules["trend_expansion_drawdown_floor"]
    ) & dataset["mom_120"].gt(0.0)
    recovery_confirmed = (
        dataset["drawdown_252"] <= rules["recovery_drawdown_ceiling"]
    ) & (
        dataset["distance_from_low_20"]
        >= rules["recovery_distance_from_low_20_floor"]
    ) & (
        dataset["momentum_accel_20_60"].gt(0.0)
        | dataset["open_return_autocorr_20"].gt(0.0)
    )
    deterioration = (
        dataset["drawdown_252"] <= rules["recovery_drawdown_ceiling"]
    ) & (
        dataset["distance_from_low_20"]
        < rules["deterioration_distance_from_low_20_ceiling"]
    ) & dataset["momentum_accel_20_60"].le(0.0)
    tactical = _stateful_binary(
        trend_expansion | recovery_confirmed,
        deterioration,
    )
    position = rules["core_position"] + (
        rules["full_position"] - rules["core_position"]
    ) * tactical
    position.name = "decision_position"
    allowed = {rules["core_position"], rules["full_position"]}
    if not set(position.dropna().unique()).issubset(allowed):
        raise AssertionError("V1.2 produced an undeclared position")
    return position


def build_v1_0_decision_position(dataset: pd.DataFrame) -> pd.Series:
    risk_on = dataset["close"].gt(dataset["sma_120"]) & dataset["mom_20"].gt(0.0)
    risk_off = dataset["close"].lt(dataset["sma_120"]) & dataset["mom_60"].lt(0.0)
    tactical = _stateful_binary(risk_on, risk_off)
    position = 0.75 + 0.25 * tactical
    position.name = "decision_position"
    return position


def execute_next_eligible_open(
    decision_position: pd.Series,
    open_eligible: pd.Series,
    *,
    initial_position: float,
) -> pd.Series:
    if not decision_position.index.equals(open_eligible.index):
        raise ValueError("decision and eligibility indices must match")
    pending = initial_position
    current = initial_position
    executed: list[float] = []
    prior_decision = initial_position
    for i, (decision, eligible) in enumerate(
        zip(decision_position, open_eligible, strict=True)
    ):
        if i > 0:
            pending = prior_decision
        if bool(eligible):
            current = float(pending)
        executed.append(current)
        prior_decision = float(decision)
    return pd.Series(
        executed,
        index=decision_position.index,
        name="position_at_open",
    )


def run_strategy(
    dataset: pd.DataFrame,
    decision_position: pd.Series,
    *,
    name: str,
    cost_bps_per_turnover_unit: float,
    initial_position: float = 0.75,
) -> StrategyResult:
    position = execute_next_eligible_open(
        decision_position,
        dataset["open_research_eligible"],
        initial_position=initial_position,
    )
    open_to_next = dataset["open"].shift(-1) / dataset["open"] - 1.0
    turnover = position.diff().abs()
    turnover.iloc[0] = abs(float(position.iloc[0]))
    cost = turnover * float(cost_bps_per_turnover_unit) / 10_000.0
    daily = pd.DataFrame(
        {
            "open": dataset["open"],
            "decision_position": decision_position,
            "position_at_open": position,
            "open_research_eligible": dataset["open_research_eligible"],
            "gross_return": position * open_to_next,
            "turnover_units": turnover,
            "cost": cost,
        },
        index=dataset.index,
    )
    daily["net_return"] = daily["gross_return"] - daily["cost"]
    daily["clean_open_interval"] = (
        dataset["open_research_eligible"]
        & dataset["open_research_eligible"].shift(-1).fillna(False).astype(bool)
    )
    daily = daily.iloc[:-1].copy()
    changes = daily["position_at_open"].ne(daily["position_at_open"].shift(1))
    trades = daily.loc[
        changes,
        [
            "position_at_open",
            "turnover_units",
            "cost",
            "open_research_eligible",
        ],
    ].copy()
    trades["prior_position"] = daily["position_at_open"].shift(1).loc[trades.index]
    trades.index.name = "date"
    return StrategyResult(
        name=name,
        daily=daily,
        trades=trades.reset_index(),
    )


def run_buy_and_hold(
    dataset: pd.DataFrame,
    *,
    cost_bps_per_turnover_unit: float,
) -> StrategyResult:
    decision = pd.Series(1.0, index=dataset.index, name="decision_position")
    return run_strategy(
        dataset,
        decision,
        name="buy_hold_byd",
        cost_bps_per_turnover_unit=cost_bps_per_turnover_unit,
        initial_position=1.0,
    )


def _metrics(daily: pd.DataFrame) -> dict[str, float]:
    returns = pd.to_numeric(daily["net_return"], errors="coerce").dropna()
    if returns.empty:
        raise ValueError("no returns available for metrics")
    years = len(returns) / 252.0
    wealth = (1.0 + returns).cumprod()
    total_return = float(wealth.iloc[-1] - 1.0)
    cagr = (
        float(wealth.iloc[-1] ** (1.0 / years) - 1.0)
        if years > 0.0 and wealth.iloc[-1] > 0.0
        else -1.0
    )
    volatility = float(returns.std(ddof=0) * np.sqrt(252.0))
    sharpe = (
        float(returns.mean() / returns.std(ddof=0) * np.sqrt(252.0))
        if returns.std(ddof=0) > 0.0
        else 0.0
    )
    downside = float(
        np.sqrt(returns.clip(upper=0.0).pow(2).mean()) * np.sqrt(252.0)
    )
    sortino = (
        float(returns.mean() * 252.0 / downside)
        if downside > 0.0
        else 0.0
    )
    drawdown = wealth / wealth.cummax() - 1.0
    max_drawdown = float(drawdown.min())
    calmar = float(cagr / abs(max_drawdown)) if max_drawdown < 0.0 else 0.0
    turnover_units = float(daily.loc[returns.index, "turnover_units"].sum())
    return {
        "sessions": float(len(returns)),
        "years": float(years),
        "total_return": total_return,
        "cagr": cagr,
        "annual_volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
        "turnover_units": turnover_units,
        "round_trips_per_year": (
            turnover_units / (2.0 * years) if years > 0 else 0.0
        ),
        "exposure": float(
            daily.loc[returns.index, "position_at_open"].mean()
        ),
    }


def _window_metrics(
    result: StrategyResult,
    start: str,
    end: str,
) -> dict[str, float]:
    block = result.daily.loc[pd.Timestamp(start) : pd.Timestamp(end)]
    if block.empty:
        raise ValueError(f"empty evaluation window {start} to {end}")
    return _metrics(block)


def _defense_episodes(
    candidate: StrategyResult,
    benchmark: StrategyResult,
    start: str,
    end: str,
) -> pd.DataFrame:
    candidate_daily = candidate.daily.loc[start:end]
    benchmark_daily = benchmark.daily.reindex(candidate_daily.index)
    defensive = candidate_daily["position_at_open"] < 1.0 - 1e-12
    starts = defensive & ~defensive.shift(1, fill_value=False)
    episode_id = starts.cumsum().where(defensive)
    rows: list[dict[str, Any]] = []
    for raw_id, block in candidate_daily.groupby(episode_id):
        if pd.isna(raw_id):
            continue
        bench = benchmark_daily.loc[block.index]
        candidate_return = float((1.0 + block["net_return"]).prod() - 1.0)
        benchmark_return = float((1.0 + bench["net_return"]).prod() - 1.0)
        relative = (1.0 + candidate_return) / (1.0 + benchmark_return) - 1.0
        rows.append(
            {
                "episode_id": int(raw_id),
                "start": block.index[0],
                "end": block.index[-1],
                "sessions": int(len(block)),
                "candidate_return": candidate_return,
                "buy_hold_return": benchmark_return,
                "relative_return": float(relative),
            }
        )
    return pd.DataFrame(rows)


def _largest_positive_episode_share(episodes: pd.DataFrame) -> float:
    if episodes.empty:
        return 1.0
    positive = episodes["relative_return"].clip(lower=0.0)
    total = float(positive.sum())
    return float(positive.max() / total) if total > 0.0 else 1.0


def evaluate_v1_2(
    canonical: CanonicalResearchData,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    dataset = build_research_dataset(
        canonical.adjusted,
        canonical.sessions,
    )
    clusters, correlation = cluster_shortlist_factors(dataset)
    conditional_ic = conditional_ic_table(dataset)
    primary_cost = float(
        contract["costs"]["primary_bps_per_turnover_unit"]
    )
    stress_cost = float(
        contract["costs"]["stress_bps_per_turnover_unit"]
    )

    decision_v12 = build_v1_2_decision_position(dataset)
    decision_v10 = build_v1_0_decision_position(dataset)
    v12 = run_strategy(
        dataset,
        decision_v12,
        name="byd_v1_2_recovery_state",
        cost_bps_per_turnover_unit=primary_cost,
    )
    v12_stress = run_strategy(
        dataset,
        decision_v12,
        name="byd_v1_2_recovery_state_stress",
        cost_bps_per_turnover_unit=stress_cost,
    )
    v10 = run_strategy(
        dataset,
        decision_v10,
        name="byd_v1_0_core75_regime_mom_120_canonical",
        cost_bps_per_turnover_unit=primary_cost,
    )
    buy_hold = run_buy_and_hold(
        dataset,
        cost_bps_per_turnover_unit=primary_cost,
    )

    metrics: dict[str, dict[str, dict[str, float]]] = {}
    for window_name, (start, end) in EVALUATION_WINDOWS.items():
        metrics[window_name] = {
            "v1_2": _window_metrics(v12, start, end),
            "v1_2_stress": _window_metrics(v12_stress, start, end),
            "v1_0": _window_metrics(v10, start, end),
            "buy_hold": _window_metrics(buy_hold, start, end),
        }

    full = metrics["full_history"]
    validation = metrics["fixed_validation"]
    episodes = _defense_episodes(
        v12,
        buy_hold,
        *EVALUATION_WINDOWS["full_history"],
    )
    concentration = _largest_positive_episode_share(episodes)
    v12_full = full["v1_2"]
    buy_full = full["buy_hold"]
    v10_full = full["v1_0"]
    gates = {
        "full_cagr_retention_95pct": (
            v12_full["cagr"] >= 0.95 * buy_full["cagr"]
        ),
        "full_drawdown_improvement_3pp": (
            v12_full["max_drawdown"] - buy_full["max_drawdown"] >= 0.03
        ),
        "full_calmar_not_below_buy_hold": (
            v12_full["calmar"] >= buy_full["calmar"]
        ),
        "validation_total_return_positive": (
            validation["v1_2"]["total_return"] > 0.0
        ),
        "validation_drawdown_improvement_3pp": (
            validation["v1_2"]["max_drawdown"]
            - validation["buy_hold"]["max_drawdown"]
            >= 0.03
        ),
        "stress_40_total_return_positive": (
            full["v1_2_stress"]["total_return"] > 0.0
        ),
        "round_trip_cap": (
            v12_full["round_trips_per_year"] <= 2.0
        ),
        "episode_concentration_cap": concentration <= 0.50,
        "not_dominated_by_v1_0": (
            v12_full["cagr"] >= v10_full["cagr"] - 0.005
            and v12_full["max_drawdown"] >= v10_full["max_drawdown"] - 0.01
            and (
                v12_full["calmar"] > v10_full["calmar"]
                or v12_full["total_return"] > v10_full["total_return"]
            )
        ),
    }
    historical_supported = all(gates.values())

    last_row = dataset.loc[CANONICAL_CUTOFF]
    prospective_ledger = pd.DataFrame(
        [
            {
                "model_id": "byd_v1_2_recovery_state",
                "canonical_adjusted_sha256": CANONICAL_ADJUSTED_SHA256,
                "signal_date": CANONICAL_CUTOFF,
                "prospective_start_date": "2026-08-04",
                "execution_date": "",
                "target_position": float(decision_v12.loc[CANONICAL_CUTOFF]),
                "drawdown_252": float(last_row["drawdown_252"]),
                "mom_120": float(last_row["mom_120"]),
                "distance_from_low_20": float(
                    last_row["distance_from_low_20"]
                ),
                "momentum_accel_20_60": float(
                    last_row["momentum_accel_20_60"]
                ),
                "open_return_autocorr_20": float(
                    last_row["open_return_autocorr_20"]
                ),
                "status": "awaiting_first_post_cutoff_eligible_open",
                "realized_return": np.nan,
            }
        ]
    )

    return {
        "decision": (
            "byd_v1_2_historically_supported_prospective_confirmation_required"
            if historical_supported
            else "byd_v1_2_not_supported"
        ),
        "historical_supported": historical_supported,
        "research_only": True,
        "trade_ready": False,
        "prospective_confirmation_required": True,
        "canonical_identity": {
            "schema": CANONICAL_SCHEMA,
            "adjusted_sha256": CANONICAL_ADJUSTED_SHA256,
            "manifest_sha256": CANONICAL_MANIFEST_SHA256,
            "cutoff": CANONICAL_CUTOFF,
            "open_label_policy": OPEN_LABEL_POLICY,
        },
        "model_factors": list(MODEL_FACTORS),
        "model_rules": MODEL_RULES,
        "metrics": metrics,
        "gates": gates,
        "largest_positive_defense_episode_share": concentration,
        "clusters": clusters,
        "factor_correlation": correlation,
        "conditional_ic": conditional_ic,
        "defense_episodes": episodes,
        "v1_2": v12,
        "v1_0": v10,
        "buy_hold": buy_hold,
        "prospective_ledger": prospective_ledger,
    }
