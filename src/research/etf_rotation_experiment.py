"""Research-only QQQI/QQQ/TQQQ state-machine experiment.

The implementation deliberately separates four concerns:

1. adjusted daily-bar acquisition through AlphaEngine's existing adapter;
2. close-of-session signal construction using QQQ only;
3. next-session-open execution with open-to-open economic returns;
4. descriptive evaluation and parameter-sensitivity diagnostics.

No function in this module places orders or marks an experiment trade-ready.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from itertools import product
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

STATE_TO_SYMBOL = {0: "QQQI", 1: "QQQ", 2: "TQQQ"}
STATE_TO_LABEL = {0: "defensive", 1: "attack", 2: "leveraged_attack"}
REQUIRED_SYMBOLS = ("QQQI", "QQQ", "TQQQ")


@dataclass(frozen=True)
class RotationConfig:
    """Frozen strategy and execution parameters for one experiment run."""

    ma_long: int = 200
    ma_short: int = 20
    buffer: float = 0.01
    n_rise: int = 3
    n_fall: int = 3
    drawdown_threshold: float = 0.10
    n_exit_short: int = 2
    high_window: int = 252
    bollinger_window: int = 20
    bollinger_std: float = 2.0
    require_above_bollinger_mid: bool = True
    exit_on_ma_short_fall: bool = False
    transaction_cost_bps_per_leg: float = 10.0
    annual_risk_free_rate: float = 0.0
    charge_initial_entry: bool = True

    def __post_init__(self) -> None:
        integer_fields = {
            "ma_long": self.ma_long,
            "ma_short": self.ma_short,
            "n_rise": self.n_rise,
            "n_fall": self.n_fall,
            "n_exit_short": self.n_exit_short,
            "high_window": self.high_window,
            "bollinger_window": self.bollinger_window,
        }
        for name, value in integer_fields.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.ma_long <= self.ma_short:
            raise ValueError("ma_long must exceed ma_short")
        if not 0.0 <= self.buffer < 0.25:
            raise ValueError("buffer must be in [0, 0.25)")
        if not 0.0 < self.drawdown_threshold < 1.0:
            raise ValueError("drawdown_threshold must be in (0, 1)")
        if self.bollinger_std <= 0:
            raise ValueError("bollinger_std must be positive")
        if self.transaction_cost_bps_per_leg < 0:
            raise ValueError("transaction_cost_bps_per_leg must be non-negative")


@dataclass
class StrategyResult:
    """One strategy's aligned daily trace, trades, and summary metrics."""

    name: str
    daily: pd.DataFrame
    trades: pd.DataFrame
    metrics: dict[str, Any]


def _normalise_bars(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    required = {"date", "open", "close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"{symbol} bars missing columns: {missing}")
    out = frame.copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    for column in ("open", "close"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.dropna(subset=["date", "open", "close"])
    out = out[(out["open"] > 0) & (out["close"] > 0)]
    out = out.sort_values("date")
    if out.empty:
        raise ValueError(f"{symbol} has no usable bars")
    if out["date"].duplicated().any():
        raise ValueError(f"{symbol} contains duplicate dates")
    return out.set_index("date")[["open", "close"]]


def fetch_adjusted_daily_bars(
    *,
    symbols: Sequence[str] = REQUIRED_SYMBOLS,
    start: str = "2010-01-01",
    end: str | None = None,
    adapter: Any | None = None,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    """Fetch adjusted OHLC bars through AlphaEngine's existing Yahoo adapter.

    The adapter already requests ``auto_adjust=True``. Therefore both ``open``
    and ``close`` are on the same corporate-action-adjusted basis, which permits
    next-open execution without mixing raw and adjusted prices.
    """

    if adapter is None:
        from src.data.adapters.yfinance_adapter import YFinanceAdapter

        adapter = YFinanceAdapter()
    from src.data.adapters.base import FetchRequest

    bars: dict[str, pd.DataFrame] = {}
    coverage: list[dict[str, Any]] = []
    for raw_symbol in symbols:
        symbol = str(raw_symbol).strip().upper()
        result = adapter.fetch_daily_bars(
            FetchRequest(symbol=symbol, market="us", start=start, end=end)
        )
        frame = _normalise_bars(result.df, symbol).reset_index()
        bars[symbol] = frame
        coverage.append(
            {
                "symbol": symbol,
                "provider": result.provider,
                "provider_symbol": result.provider_symbol or symbol,
                "first_date": frame["date"].min().date().isoformat(),
                "last_date": frame["date"].max().date().isoformat(),
                "rows": int(len(frame)),
            }
        )
    return bars, pd.DataFrame(coverage).sort_values("symbol").reset_index(drop=True)


def build_signal_frame(qqq_bars: pd.DataFrame, config: RotationConfig) -> pd.DataFrame:
    """Calculate every signal using QQQ data available at that session close."""

    qqq = _normalise_bars(qqq_bars, "QQQ")
    close = qqq["close"]
    signal = pd.DataFrame(index=qqq.index)
    signal["qqq_close"] = close
    signal["ma_long"] = close.rolling(config.ma_long, min_periods=config.ma_long).mean()
    signal["ma_short"] = close.rolling(config.ma_short, min_periods=config.ma_short).mean()
    signal["std_short"] = close.rolling(
        config.bollinger_window, min_periods=config.bollinger_window
    ).std(ddof=0)
    signal["bb_mid"] = close.rolling(
        config.bollinger_window, min_periods=config.bollinger_window
    ).mean()
    signal["bb_upper"] = signal["bb_mid"] + config.bollinger_std * signal["std_short"]
    signal["bb_lower"] = signal["bb_mid"] - config.bollinger_std * signal["std_short"]
    signal["high_window"] = close.rolling(
        config.high_window, min_periods=config.high_window
    ).max()
    signal["drawdown"] = close / signal["high_window"] - 1.0
    signal["return_63d"] = close.pct_change(63)

    ma_diff = signal["ma_short"].diff()
    signal["ma_short_rising"] = (
        ma_diff.gt(0)
        .rolling(config.n_rise, min_periods=config.n_rise)
        .sum()
        .eq(config.n_rise)
    )
    signal["ma_short_falling"] = (
        ma_diff.lt(0)
        .rolling(config.n_fall, min_periods=config.n_fall)
        .sum()
        .eq(config.n_fall)
    )
    signal["below_ma_short_n"] = (
        close.lt(signal["ma_short"])
        .rolling(config.n_exit_short, min_periods=config.n_exit_short)
        .sum()
        .eq(config.n_exit_short)
    )

    long_ready = signal["ma_long"].notna()
    short_ready = signal["ma_short"].notna()
    enter_attack = (
        long_ready
        & short_ready
        & close.gt(signal["ma_long"] * (1.0 + config.buffer))
        & signal["ma_short_rising"]
    )
    if config.require_above_bollinger_mid:
        enter_attack &= close.gt(signal["bb_mid"])
    signal["enter_attack"] = enter_attack.fillna(False)
    signal["enter_leveraged"] = (
        long_ready
        & short_ready
        & close.gt(signal["ma_long"] * (1.0 + config.buffer))
        & close.gt(signal["ma_short"])
        & signal["ma_short_rising"]
        & signal["drawdown"].le(-config.drawdown_threshold)
    ).fillna(False)
    signal["defensive_break"] = (
        long_ready & close.lt(signal["ma_long"] * (1.0 - config.buffer))
    ).fillna(False)
    signal["exit_leveraged"] = signal["below_ma_short_n"].fillna(False)

    signal["regime"] = "transition"
    signal.loc[close.lt(signal["ma_long"]), "regime"] = "weak_below_ma200"
    sideways = (
        close.ge(signal["ma_long"])
        & signal["return_63d"].abs().lt(0.05)
        & signal["return_63d"].notna()
    )
    signal.loc[sideways, "regime"] = "sideways_above_ma200"
    uptrend = (
        close.ge(signal["ma_long"])
        & signal["return_63d"].ge(0.05)
        & signal["ma_short_rising"]
    )
    signal.loc[uptrend, "regime"] = "uptrend"
    return signal


def generate_decision_states(
    signal: pd.DataFrame,
    config: RotationConfig,
    *,
    version: str,
) -> pd.DataFrame:
    """Generate the desired state decided at each close for the next open."""

    version_key = version.upper()
    if version_key not in {"A", "B"}:
        raise ValueError("version must be 'A' or 'B'")
    state = 0
    states: list[int] = []
    reasons: list[str] = []
    for row in signal.itertuples():
        next_state = state
        reason = "hold"
        if version_key == "A":
            if state == 0 and bool(row.enter_attack):
                next_state = 1
                reason = "enter_qqq_trend_confirmed"
            elif state == 1 and bool(row.defensive_break):
                next_state = 0
                reason = "exit_qqq_ma_long_break"
            elif state == 1 and config.exit_on_ma_short_fall and bool(row.ma_short_falling):
                next_state = 0
                reason = "exit_qqq_ma_short_falling"
        else:
            if bool(row.defensive_break):
                next_state = 0
                reason = "global_defensive_ma_long_break"
            elif state == 0 and bool(row.enter_attack):
                next_state = 1
                reason = "enter_qqq_trend_confirmed"
            elif state == 1 and bool(row.enter_leveraged):
                next_state = 2
                reason = "enter_tqqq_recovery_from_drawdown"
            elif state == 2 and bool(row.exit_leveraged):
                next_state = 1
                reason = "exit_tqqq_ma_short_break"
        state = next_state
        states.append(state)
        reasons.append(reason)
    return pd.DataFrame(
        {"decision_state": states, "decision_reason": reasons}, index=signal.index
    )


def prepare_rotation_data(
    bars: Mapping[str, pd.DataFrame], config: RotationConfig
) -> pd.DataFrame:
    """Align the common tradable interval while retaining QQQ indicator warm-up."""

    missing = sorted(set(REQUIRED_SYMBOLS) - {str(key).upper() for key in bars})
    if missing:
        raise ValueError(f"bars missing required symbols: {missing}")
    normalised = {
        symbol: _normalise_bars(bars[symbol], symbol) for symbol in REQUIRED_SYMBOLS
    }
    signal = build_signal_frame(bars["QQQ"], config)
    common_index = normalised["QQQI"].index
    for symbol in ("QQQ", "TQQQ"):
        common_index = common_index.intersection(normalised[symbol].index)
    common_index = common_index.sort_values()
    if common_index.empty:
        raise ValueError("required symbols have no common sessions")

    frame = signal.reindex(common_index).copy()
    for symbol in REQUIRED_SYMBOLS:
        frame[f"{symbol}_open"] = normalised[symbol].reindex(common_index)["open"]
        frame[f"{symbol}_close"] = normalised[symbol].reindex(common_index)["close"]
        frame[f"{symbol}_next_open_return"] = (
            frame[f"{symbol}_open"].shift(-1) / frame[f"{symbol}_open"] - 1.0
        )
    frame = frame[frame["ma_long"].notna() & frame["ma_short"].notna()].copy()
    if len(frame) < 40:
        raise ValueError("common post-warm-up sample is too short for evaluation")
    return frame


def _return_metrics(
    returns: pd.Series,
    *,
    annual_risk_free_rate: float = 0.0,
) -> dict[str, float | int | str]:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        return {
            "observations": 0,
            "total_return": np.nan,
            "cagr": np.nan,
            "annual_volatility": np.nan,
            "sharpe": np.nan,
            "sortino": np.nan,
            "max_drawdown": np.nan,
            "calmar": np.nan,
        }
    equity = (1.0 + clean).cumprod()
    years = len(clean) / 252.0
    total_return = float(equity.iloc[-1] - 1.0)
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else np.nan
    volatility = float(clean.std(ddof=0) * np.sqrt(252.0))
    daily_rf = (1.0 + annual_risk_free_rate) ** (1.0 / 252.0) - 1.0
    excess = clean - daily_rf
    sharpe = (
        float(excess.mean() / clean.std(ddof=0) * np.sqrt(252.0))
        if clean.std(ddof=0) > 1e-12
        else np.nan
    )
    downside = np.minimum(excess.to_numpy(dtype=float), 0.0)
    downside_dev = float(np.sqrt(np.mean(np.square(downside))))
    sortino = (
        float(excess.mean() / downside_dev * np.sqrt(252.0))
        if downside_dev > 1e-12
        else np.nan
    )
    drawdown = equity / equity.cummax() - 1.0
    max_drawdown = float(drawdown.min())
    calmar = float(cagr / abs(max_drawdown)) if max_drawdown < -1e-12 else np.nan
    return {
        "observations": int(len(clean)),
        "start_date": clean.index.min().date().isoformat(),
        "end_date": clean.index.max().date().isoformat(),
        "total_return": total_return,
        "cagr": cagr,
        "annual_volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_drawdown,
        "calmar": calmar,
    }


def _average_holding_days(position: pd.Series) -> float:
    if position.empty:
        return np.nan
    groups = position.ne(position.shift()).cumsum()
    lengths = position.groupby(groups).size()
    return float(lengths.mean()) if not lengths.empty else np.nan


def run_rotation_backtest(
    prepared: pd.DataFrame,
    config: RotationConfig,
    *,
    version: str,
) -> StrategyResult:
    """Run one state machine with next-open execution and open-to-open returns."""

    decision = generate_decision_states(prepared, config, version=version)
    daily = prepared.join(decision)
    daily["position_state"] = decision["decision_state"].shift(1).fillna(0).astype(int)
    daily["position_symbol"] = daily["position_state"].map(STATE_TO_SYMBOL)
    daily["position_label"] = daily["position_state"].map(STATE_TO_LABEL)
    daily["trade_reason"] = decision["decision_reason"].shift(1).fillna("initial_state")

    gross = pd.Series(index=daily.index, dtype=float)
    for state, symbol in STATE_TO_SYMBOL.items():
        mask = daily["position_state"].eq(state)
        gross.loc[mask] = daily.loc[mask, f"{symbol}_next_open_return"]
    daily["gross_return"] = gross

    previous = daily["position_state"].shift(1)
    switched = daily["position_state"].ne(previous)
    legs = pd.Series(0.0, index=daily.index)
    legs.loc[switched & previous.notna()] = 2.0
    if config.charge_initial_entry and len(legs):
        legs.iloc[0] = 1.0
    daily["turnover_legs"] = legs
    daily["transaction_cost"] = (
        legs * config.transaction_cost_bps_per_leg / 10_000.0
    )
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily = daily[daily["net_return"].notna()].copy()
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0

    trade_mask = daily["turnover_legs"].gt(0)
    trades = pd.DataFrame(
        {
            "date": daily.index[trade_mask],
            "from_state": daily["position_state"].shift(1).loc[trade_mask].values,
            "to_state": daily.loc[trade_mask, "position_state"].values,
            "to_symbol": daily.loc[trade_mask, "position_symbol"].values,
            "reason": daily.loc[trade_mask, "trade_reason"].values,
            "turnover_legs": daily.loc[trade_mask, "turnover_legs"].values,
            "cost": daily.loc[trade_mask, "transaction_cost"].values,
        }
    )
    if not trades.empty:
        trades["from_state"] = trades["from_state"].astype("Int64")

    metrics = _return_metrics(
        daily["net_return"], annual_risk_free_rate=config.annual_risk_free_rate
    )
    metrics.update(
        {
            "strategy": f"rotation_{version.upper()}",
            "switch_count": int((daily["turnover_legs"] == 2.0).sum()),
            "trade_events_including_initial": int(trade_mask.sum()),
            "average_holding_days": _average_holding_days(daily["position_state"]),
            "turnover_legs": float(daily["turnover_legs"].sum()),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "pct_time_qqqi": float(daily["position_state"].eq(0).mean()),
            "pct_time_qqq": float(daily["position_state"].eq(1).mean()),
            "pct_time_tqqq": float(daily["position_state"].eq(2).mean()),
        }
    )
    return StrategyResult(f"Rotation {version.upper()}", daily, trades, metrics)


def run_buy_and_hold(
    prepared: pd.DataFrame,
    config: RotationConfig,
    *,
    symbol: str,
) -> StrategyResult:
    """Run a common-window buy-and-hold baseline using adjusted next-open returns."""

    symbol = symbol.upper()
    if symbol not in REQUIRED_SYMBOLS:
        raise ValueError(f"unsupported baseline symbol: {symbol}")
    daily = prepared[[f"{symbol}_next_open_return"]].rename(
        columns={f"{symbol}_next_open_return": "gross_return"}
    )
    daily = daily[daily["gross_return"].notna()].copy()
    daily["transaction_cost"] = 0.0
    if config.charge_initial_entry and not daily.empty:
        daily.iloc[0, daily.columns.get_loc("transaction_cost")] = (
            config.transaction_cost_bps_per_leg / 10_000.0
        )
    daily["net_return"] = daily["gross_return"] - daily["transaction_cost"]
    daily["equity"] = (1.0 + daily["net_return"]).cumprod()
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    metrics = _return_metrics(
        daily["net_return"], annual_risk_free_rate=config.annual_risk_free_rate
    )
    metrics.update(
        {
            "strategy": f"buy_hold_{symbol}",
            "switch_count": 0,
            "trade_events_including_initial": int(config.charge_initial_entry),
            "average_holding_days": float(len(daily)),
            "turnover_legs": float(config.charge_initial_entry),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "pct_time_qqqi": float(symbol == "QQQI"),
            "pct_time_qqq": float(symbol == "QQQ"),
            "pct_time_tqqq": float(symbol == "TQQQ"),
        }
    )
    trades = pd.DataFrame(
        columns=["date", "from_state", "to_state", "to_symbol", "reason", "turnover_legs", "cost"]
    )
    return StrategyResult(f"Buy & Hold {symbol}", daily, trades, metrics)


def run_default_comparison(
    bars: Mapping[str, pd.DataFrame], config: RotationConfig
) -> tuple[pd.DataFrame, dict[str, StrategyResult], pd.DataFrame]:
    """Evaluate the three baselines plus rotation versions A and B."""

    prepared = prepare_rotation_data(bars, config)
    results: dict[str, StrategyResult] = {}
    for symbol in REQUIRED_SYMBOLS:
        results[f"buy_hold_{symbol}"] = run_buy_and_hold(prepared, config, symbol=symbol)
    results["rotation_A"] = run_rotation_backtest(prepared, config, version="A")
    results["rotation_B"] = run_rotation_backtest(prepared, config, version="B")
    metrics = pd.DataFrame([result.metrics for result in results.values()]).set_index("strategy")
    return metrics.sort_index(), results, prepared


def conditional_asset_metrics(prepared: pd.DataFrame) -> pd.DataFrame:
    """Compare QQQI and QQQ within QQQ-defined contemporaneous regimes."""

    rows: list[dict[str, Any]] = []
    for regime in ("weak_below_ma200", "sideways_above_ma200", "uptrend", "transition"):
        mask = prepared["regime"].eq(regime)
        for symbol in ("QQQI", "QQQ"):
            series = prepared.loc[mask, f"{symbol}_next_open_return"].dropna()
            metrics = _return_metrics(series)
            rows.append(
                {
                    "regime": regime,
                    "symbol": symbol,
                    "sessions": int(len(series)),
                    "cumulative_return": metrics["total_return"],
                    "annualized_volatility": metrics["annual_volatility"],
                    "sharpe": metrics["sharpe"],
                    "max_drawdown": metrics["max_drawdown"],
                    "positive_day_ratio": float(series.gt(0).mean()) if len(series) else np.nan,
                }
            )
    return pd.DataFrame(rows).set_index(["regime", "symbol"])


def recovery_event_study(
    prepared: pd.DataFrame,
    *,
    horizon_sessions: int = 20,
) -> pd.DataFrame:
    """Compare QQQ and QQQI after QQQ crosses back above its long moving average."""

    if horizon_sessions <= 0:
        raise ValueError("horizon_sessions must be positive")
    cross = prepared["qqq_close"].gt(prepared["ma_long"]) & prepared["qqq_close"].shift(1).le(
        prepared["ma_long"].shift(1)
    )
    rows: list[dict[str, Any]] = []
    event_dates = list(prepared.index[cross.fillna(False)])
    for event_date in event_dates:
        location = prepared.index.get_loc(event_date)
        window = prepared.iloc[location : location + horizon_sessions]
        if len(window) < horizon_sessions:
            continue
        row: dict[str, Any] = {"event_date": event_date}
        for symbol in ("QQQI", "QQQ"):
            values = window[f"{symbol}_next_open_return"].dropna()
            if len(values) < horizon_sessions:
                row[f"{symbol}_return"] = np.nan
            else:
                row[f"{symbol}_return"] = float((1.0 + values).prod() - 1.0)
        row["QQQ_minus_QQQI"] = row["QQQ_return"] - row["QQQI_return"]
        rows.append(row)
    return pd.DataFrame(rows)


def phase_metrics(
    results: Mapping[str, StrategyResult],
    periods: Mapping[str, tuple[str, str]],
    *,
    minimum_sessions: int = 20,
) -> pd.DataFrame:
    """Evaluate named periods, reporting unavailable pre-QQQI windows explicitly."""

    rows: list[dict[str, Any]] = []
    for period_name, (start, end) in periods.items():
        start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
        for key, result in results.items():
            series = result.daily.loc[start_ts:end_ts, "net_return"]
            coverage = "available" if len(series) >= minimum_sessions else "insufficient_common_history"
            metrics = _return_metrics(series) if coverage == "available" else {}
            rows.append(
                {
                    "period": period_name,
                    "strategy": key,
                    "coverage": coverage,
                    "sessions": int(len(series)),
                    "total_return": metrics.get("total_return", np.nan),
                    "cagr": metrics.get("cagr", np.nan),
                    "max_drawdown": metrics.get("max_drawdown", np.nan),
                    "sharpe": metrics.get("sharpe", np.nan),
                }
            )
    return pd.DataFrame(rows).set_index(["period", "strategy"])


def chronological_split_metrics(
    result: StrategyResult,
    *,
    train_fraction: float = 0.60,
) -> pd.DataFrame:
    """Apply one frozen strategy to early and late common-history segments."""

    if not 0.2 <= train_fraction <= 0.8:
        raise ValueError("train_fraction must be between 0.2 and 0.8")
    series = result.daily["net_return"].dropna()
    split_at = max(1, min(len(series) - 1, int(len(series) * train_fraction)))
    pieces = {"early_common_sample": series.iloc[:split_at], "late_common_sample": series.iloc[split_at:]}
    rows = []
    for name, values in pieces.items():
        row = {"segment": name, **_return_metrics(values)}
        rows.append(row)
    return pd.DataFrame(rows).set_index("segment")


def run_sensitivity_grid(
    bars: Mapping[str, pd.DataFrame],
    base_config: RotationConfig,
    grid: Mapping[str, Sequence[Any]],
    *,
    version: str = "B",
) -> pd.DataFrame:
    """Run a descriptive grid without selecting or promoting a winning parameter set."""

    allowed = {
        "ma_long",
        "buffer",
        "n_rise",
        "drawdown_threshold",
        "n_exit_short",
        "bollinger_window",
        "bollinger_std",
    }
    unknown = sorted(set(grid) - allowed)
    if unknown:
        raise ValueError(f"unsupported sensitivity parameters: {unknown}")
    names = list(grid)
    values = [list(grid[name]) for name in names]
    rows: list[dict[str, Any]] = []
    for combination in product(*values):
        updates = dict(zip(names, combination))
        config = replace(base_config, **updates)
        prepared = prepare_rotation_data(bars, config)
        result = run_rotation_backtest(prepared, config, version=version)
        rows.append({**updates, **result.metrics})
    return pd.DataFrame(rows)


def stability_summary(
    grid_results: pd.DataFrame,
    *,
    baseline_metrics: Mapping[str, Any],
) -> dict[str, Any]:
    """Summarise dispersion around the frozen default, not the best backtest."""

    required = {"cagr", "max_drawdown", "calmar"}
    missing = sorted(required - set(grid_results.columns))
    if missing:
        raise ValueError(f"grid results missing metrics: {missing}")
    cagr = pd.to_numeric(grid_results["cagr"], errors="coerce").dropna()
    mdd = pd.to_numeric(grid_results["max_drawdown"], errors="coerce").dropna()
    baseline_cagr = float(baseline_metrics["cagr"])
    baseline_mdd = float(baseline_metrics["max_drawdown"])
    cagr_relative_spread = (
        float((cagr.quantile(0.90) - cagr.quantile(0.10)) / abs(baseline_cagr))
        if abs(baseline_cagr) > 1e-12 and not cagr.empty
        else np.nan
    )
    mdd_relative_spread = (
        float((mdd.abs().quantile(0.90) - mdd.abs().quantile(0.10)) / abs(baseline_mdd))
        if abs(baseline_mdd) > 1e-12 and not mdd.empty
        else np.nan
    )
    return {
        "parameter_combinations": int(len(grid_results)),
        "cagr_p10": float(cagr.quantile(0.10)) if not cagr.empty else np.nan,
        "cagr_median": float(cagr.median()) if not cagr.empty else np.nan,
        "cagr_p90": float(cagr.quantile(0.90)) if not cagr.empty else np.nan,
        "max_drawdown_abs_p10": float(mdd.abs().quantile(0.10)) if not mdd.empty else np.nan,
        "max_drawdown_abs_median": float(mdd.abs().median()) if not mdd.empty else np.nan,
        "max_drawdown_abs_p90": float(mdd.abs().quantile(0.90)) if not mdd.empty else np.nan,
        "cagr_relative_p10_p90_spread": cagr_relative_spread,
        "mdd_relative_p10_p90_spread": mdd_relative_spread,
        "heuristic_robust": bool(
            np.isfinite(cagr_relative_spread)
            and np.isfinite(mdd_relative_spread)
            and cagr_relative_spread < 0.20
            and mdd_relative_spread < 0.30
        ),
        "note": "Heuristic follows the experiment contract; it is not a promotion gate.",
    }


def config_as_dict(config: RotationConfig) -> dict[str, Any]:
    return asdict(config)
