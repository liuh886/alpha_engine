"""Research-only all-weather CN equity/515180 rotation experiment.

The engine keeps candidate equities, the executable defensive ETF and the
non-executable benchmark role-separated.  Signals are calculated from each
instrument's own close history and can only become actionable at a later open.
"""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml


REQUIRED_BAR_COLUMNS = ("date", "symbol", "open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class AllWeatherContract:
    spec: dict[str, Any]
    pool: dict[str, Any]
    reference_registry: dict[str, Any]
    spec_path: Path
    pool_path: Path
    reference_registry_path: Path
    candidate_symbols: tuple[str, ...]
    defensive_etf_symbol: str
    benchmark_symbol: str


@dataclass
class AllWeatherBacktestResult:
    daily: pd.DataFrame
    trades: pd.DataFrame
    round_trips: pd.DataFrame
    coverage: pd.DataFrame
    indicators: pd.DataFrame
    metrics: dict[str, Any]


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_yaml(path: Path, *, label: str) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a YAML mapping: {path}")
    return payload


def _repository_root(path: Path) -> Path:
    for candidate in (path.resolve().parent, *path.resolve().parents):
        if (candidate / "AGENTS.md").is_file() and (candidate / "configs").is_dir():
            return candidate
    raise ValueError(f"cannot resolve repository root from {path}")


def _canonical_to_provider_symbol(value: object) -> str:
    symbol = str(value).strip().upper().split(".", maxsplit=1)[0]
    return symbol.zfill(6) if symbol.isdigit() else symbol


def load_all_weather_contract(spec_path: str | Path) -> AllWeatherContract:
    resolved_spec = Path(spec_path).resolve()
    spec = _load_yaml(resolved_spec, label="all-weather spec")
    root = _repository_root(resolved_spec)
    pool_path = (root / str(spec.get("identity", {}).get("pool_spec", ""))).resolve()
    registry_path = (
        root / str(spec.get("identity", {}).get("reference_registry", ""))
    ).resolve()
    pool = _load_yaml(pool_path, label="all-weather pool")
    registry = _load_yaml(registry_path, label="reference registry")

    if spec.get("research_only") is not True or spec.get("trade_ready") is not False:
        raise ValueError("all-weather spec must remain research_only=true and trade_ready=false")
    if pool.get("research_only") is not True or pool.get("trade_ready") is not False:
        raise ValueError("all-weather pool must remain research_only=true and trade_ready=false")
    if spec.get("market") != "cn" or pool.get("market") != "cn":
        raise ValueError("all-weather experiment is market-isolated to cn")
    if spec.get("selected_pool_readiness_claim_allowed") is not False:
        raise ValueError("strategy-specific pool cannot claim selected-pool readiness")
    if pool.get("authoritative_for_selected_pool_readiness") is not False:
        raise ValueError("strategy-specific pool cannot be authoritative for selected-pool readiness")

    symbol_rows = pool.get("symbols")
    if not isinstance(symbol_rows, list):
        raise ValueError("pool symbols must be a list")
    symbols = tuple(str(row.get("symbol", "")).strip() for row in symbol_rows if isinstance(row, dict))
    if not symbols or any(not value for value in symbols):
        raise ValueError("every pool member requires a symbol")
    if len(set(symbols)) != len(symbols):
        raise ValueError("pool contains duplicate symbols")
    if len(symbols) != int(pool.get("candidate_count", -1)):
        raise ValueError("pool candidate_count does not match symbols")

    identity = spec.get("identity", {})
    defensive = _canonical_to_provider_symbol(identity.get("defensive_etf"))
    benchmark = _canonical_to_provider_symbol(identity.get("benchmark"))
    if defensive in symbols or benchmark in symbols:
        raise ValueError("reference instruments cannot enter the candidate cross-section")
    cn_references = registry.get("markets", {}).get("cn", {}).get("instruments", {})
    matched = [
        row
        for row in cn_references.values()
        if isinstance(row, dict)
        and _canonical_to_provider_symbol(row.get("canonical_symbol")) == defensive
    ]
    if len(matched) != 1:
        raise ValueError(f"defensive ETF {defensive} must resolve exactly once in registry")
    reference = matched[0]
    if reference.get("executable") is not True or reference.get("candidate_eligible") is not False:
        raise ValueError("defensive ETF must be executable and candidate-ineligible")
    roles = set(reference.get("roles", []))
    if "defensive_sleeve" not in roles:
        raise ValueError("defensive ETF lacks defensive_sleeve role")

    portfolio = spec.get("portfolio", {})
    max_positions = int(portfolio.get("maximum_stock_positions", 0))
    stock_weight = float(portfolio.get("stock_target_weight", 0.0))
    maximum_stock_weight = float(portfolio.get("maximum_stock_weight", 0.0))
    if max_positions <= 0 or not 0.0 < stock_weight <= 1.0:
        raise ValueError("portfolio position count and weight must be positive")
    if max_positions * stock_weight > maximum_stock_weight + 1e-12:
        raise ValueError("configured positions exceed maximum stock weight")
    if maximum_stock_weight > 1.0:
        raise ValueError("maximum stock weight cannot exceed one")

    slope_definition = str(spec.get("factors", {}).get("sma20_slope_definition", ""))
    if slope_definition not in {"one_session_difference", "three_session_relative"}:
        raise ValueError(f"unsupported SMA20 slope definition: {slope_definition}")
    if slope_definition == "three_session_relative":
        slope_periods = int(spec["factors"].get("sma20_slope_periods", 0))
        if slope_periods != 3:
            raise ValueError("three_session_relative SMA20 slope requires exactly 3 periods")

    return AllWeatherContract(
        spec=spec,
        pool=pool,
        reference_registry=registry,
        spec_path=resolved_spec,
        pool_path=pool_path,
        reference_registry_path=registry_path,
        candidate_symbols=symbols,
        defensive_etf_symbol=defensive,
        benchmark_symbol=benchmark,
    )


def normalise_long_bars(frame: pd.DataFrame) -> pd.DataFrame:
    missing = sorted(set(REQUIRED_BAR_COLUMNS) - set(frame.columns))
    if missing:
        raise ValueError(f"price data missing columns: {missing}")
    out = frame[list(REQUIRED_BAR_COLUMNS)].copy()
    out["symbol"] = out["symbol"].astype(str).str.strip().str.upper().map(
        _canonical_to_provider_symbol
    )
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.tz_localize(None).dt.normalize()
    for column in ("open", "high", "low", "close", "volume"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.dropna(subset=["date", "symbol", "open", "high", "low", "close"])
    out = out[(out[["open", "high", "low", "close"]] > 0.0).all(axis=1)]
    if out.duplicated(["date", "symbol"]).any():
        duplicate = out.loc[out.duplicated(["date", "symbol"], keep=False), ["date", "symbol"]]
        raise ValueError(f"duplicate price rows: {duplicate.head().to_dict(orient='records')}")
    envelope_ok = out["high"].ge(out[["open", "close", "low"]].max(axis=1)) & out[
        "low"
    ].le(out[["open", "close", "high"]].min(axis=1))
    if not envelope_ok.all():
        raise ValueError("OHLC envelope violation")
    return out.sort_values(["symbol", "date"]).reset_index(drop=True)


def _rsi_simple(close: pd.Series, window: int) -> pd.Series:
    delta = close.diff()
    average_gain = delta.clip(lower=0.0).rolling(window, min_periods=window).mean()
    average_loss = (-delta.clip(upper=0.0)).rolling(window, min_periods=window).mean()
    ratio = average_gain / average_loss.replace(0.0, np.nan)
    rsi = 100.0 - 100.0 / (1.0 + ratio)
    rsi = rsi.mask(average_loss.eq(0.0) & average_gain.gt(0.0), 100.0)
    return rsi.mask(average_loss.eq(0.0) & average_gain.eq(0.0))


def compute_all_weather_indicators(
    bars: pd.DataFrame,
    spec: Mapping[str, Any],
) -> pd.DataFrame:
    """Compute the document-defined factors without cross-symbol forward fill."""

    clean = normalise_long_bars(bars)
    factors = spec["factors"]
    score_weights = factors["score"]
    entry = spec["entry"]
    frames: list[pd.DataFrame] = []
    for symbol, raw in clean.groupby("symbol", sort=True):
        item = raw.sort_values("date").copy()
        close = item["close"]
        for window in factors["sma_windows"]:
            item[f"sma{int(window)}"] = close.rolling(int(window), min_periods=int(window)).mean()
        slope_definition = str(factors["sma20_slope_definition"])
        if slope_definition == "one_session_difference":
            item["sma20_slope"] = item["sma20"].diff()
        elif slope_definition == "three_session_relative":
            slope_periods = int(factors["sma20_slope_periods"])
            item["sma20_slope"] = item["sma20"] / item["sma20"].shift(slope_periods) - 1.0
        else:
            raise ValueError(f"unsupported SMA20 slope definition: {slope_definition}")
        item["bias20"] = close / item["sma20"] - 1.0
        ema_fast = close.ewm(span=int(factors["ema_fast"]), adjust=False).mean()
        ema_slow = close.ewm(span=int(factors["ema_slow"]), adjust=False).mean()
        item["macd"] = ema_fast - ema_slow
        item["macd_signal"] = item["macd"].ewm(
            span=int(factors["macd_signal"]), adjust=False
        ).mean()
        item["macd_hist"] = item["macd"] - item["macd_signal"]
        item["rsi14"] = _rsi_simple(close, int(factors["rsi_window"]))
        true_range = pd.concat(
            [(close - close.shift(1)).abs(), (close - item["open"]).abs()], axis=1
        ).max(axis=1)
        item["atr14"] = true_range.rolling(
            int(factors["atr_window"]), min_periods=int(factors["atr_window"])
        ).mean()
        item["close_ratio_20"] = close / close.shift(int(factors["momentum_window"]))
        excess_bias = (item["bias20"] - float(score_weights["bias_penalty_threshold"])).clip(
            lower=0.0
        )
        item["score"] = (
            float(score_weights["slope_sma20"]) * item["sma20_slope"]
            + float(score_weights["macd_hist"]) * item["macd_hist"]
            + float(score_weights["close_ratio_20"]) * item["close_ratio_20"]
            - float(score_weights["excess_bias_penalty"]) * excess_bias
        )
        item["entry_eligible"] = (
            item["sma5"].gt(item["sma20"])
            & close.gt(item["sma20"])
            & item["macd"].gt(item["macd_signal"])
            & item["macd_hist"].ge(float(entry["minimum_macd_hist"]))
            & item["bias20"].between(
                float(entry["bias20"]["minimum"]), float(entry["bias20"]["maximum"])
            )
            & item["rsi14"].between(
                float(entry["rsi14"]["minimum"]), float(entry["rsi14"]["maximum"])
            )
        )
        item["one_price_lock"] = np.isclose(item["high"], item["low"], rtol=0.0, atol=1e-12)
        frames.append(item)
    if not frames:
        raise ValueError("price data has no usable rows")
    return pd.concat(frames, ignore_index=True).sort_values(["date", "symbol"]).reset_index(
        drop=True
    )


def contract_identity(contract: AllWeatherContract) -> dict[str, str]:
    source = contract.spec["source"]
    source_document_sha256 = source.get("document_sha256") or source.get(
        "corrected_document_sha256"
    )
    if not source_document_sha256:
        raise ValueError("all-weather contract requires a source document SHA-256")
    return {
        "spec_sha256": sha256_file(contract.spec_path),
        "pool_sha256": sha256_file(contract.pool_path),
        "reference_registry_sha256": sha256_file(contract.reference_registry_path),
        "source_document_sha256": str(source_document_sha256),
        "implementation_sha256": sha256_file(Path(__file__)),
    }


def canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _coverage_table(bars: pd.DataFrame, required_symbols: tuple[str, ...]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for symbol in required_symbols:
        item = bars.loc[bars["symbol"].eq(symbol)]
        rows.append(
            {
                "symbol": symbol,
                "status": "ready" if not item.empty else "provider_missing",
                "rows": int(len(item)),
                "first_date": None if item.empty else item["date"].min().date().isoformat(),
                "last_date": None if item.empty else item["date"].max().date().isoformat(),
            }
        )
    return pd.DataFrame(rows)


def _return_metrics(
    returns: pd.Series,
    *,
    annual_sessions: int,
    annual_risk_free_rate: float,
) -> dict[str, Any]:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        raise ValueError("cannot calculate metrics from empty returns")
    equity = (1.0 + clean).cumprod()
    years = len(clean) / float(annual_sessions)
    total_return = float(equity.iloc[-1] - 1.0)
    cagr = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else np.nan
    annual_volatility = float(clean.std(ddof=0) * np.sqrt(annual_sessions))
    daily_rf_log = np.log1p(annual_risk_free_rate) / annual_sessions
    log_excess = np.log1p(clean.clip(lower=-0.999999999)) - daily_rf_log
    sharpe = (
        float(log_excess.mean() / log_excess.std(ddof=0) * np.sqrt(annual_sessions))
        if log_excess.std(ddof=0) > 1e-12
        else np.nan
    )
    drawdown = equity / equity.cummax() - 1.0
    maximum_drawdown = float(drawdown.min())
    calmar = float(cagr / abs(maximum_drawdown)) if maximum_drawdown < -1e-12 else np.nan
    return {
        "observations": int(len(clean)),
        "start_date": clean.index.min().date().isoformat(),
        "end_date": clean.index.max().date().isoformat(),
        "total_return": total_return,
        "cagr": cagr,
        "annual_volatility": annual_volatility,
        "sharpe_log_excess": sharpe,
        "maximum_drawdown": maximum_drawdown,
        "calmar": calmar,
    }


def evaluate_byd_v1_3_challenge(
    result: AllWeatherBacktestResult,
    contract: AllWeatherContract,
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Compare CN_27 with the hash-bound formal BYD v1.3 trace on common sessions."""

    challenge = contract.spec.get("challenge")
    if not isinstance(challenge, dict):
        raise ValueError("CN_27 challenge contract is missing")
    root = _repository_root(contract.spec_path)
    manifest_path = (root / str(challenge["benchmark_manifest"])).resolve()
    if not manifest_path.is_relative_to(root):
        raise ValueError("benchmark manifest must stay inside the repository")
    if sha256_file(manifest_path) != str(challenge["benchmark_manifest_sha256"]):
        raise ValueError("BYD v1.3 benchmark manifest hash mismatch")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_model = str(challenge["benchmark_model_version_id"])
    if manifest.get("model_version_id") != expected_model:
        raise ValueError("BYD v1.3 benchmark model identity mismatch")
    if manifest.get("research_only") is not True or manifest.get("trade_ready") is not False:
        raise ValueError("BYD v1.3 benchmark must remain research-only")
    performance_section = next(
        (row for row in manifest.get("sections", []) if row.get("section_id") == "performance"),
        None,
    )
    if not isinstance(performance_section, dict):
        raise ValueError("BYD v1.3 benchmark performance section is missing")
    performance_path = (manifest_path.parent / str(performance_section["path"])).resolve()
    expected_performance_sha = str(challenge["benchmark_performance_sha256"])
    if performance_section.get("sha256") != expected_performance_sha:
        raise ValueError("BYD v1.3 manifest performance identity mismatch")
    if sha256_file(performance_path) != expected_performance_sha:
        raise ValueError("BYD v1.3 performance hash mismatch")

    performance = json.loads(performance_path.read_text(encoding="utf-8"))
    if performance.get("trace_frequency") != "daily_open_to_open":
        raise ValueError("BYD v1.3 benchmark is not a daily open-to-open trace")
    benchmark = pd.DataFrame(performance.get("report", []))
    required_columns = {"date", "period_return", "turnover", "transaction_cost"}
    missing = sorted(required_columns - set(benchmark.columns))
    if missing:
        raise ValueError(f"BYD v1.3 benchmark trace missing columns: {missing}")
    benchmark["date"] = pd.to_datetime(benchmark["date"], errors="raise").dt.normalize()
    if benchmark["date"].duplicated().any():
        raise ValueError("BYD v1.3 benchmark trace contains duplicate dates")
    benchmark = benchmark.set_index("date").sort_index()

    window = challenge["common_window"]
    start, end = pd.Timestamp(window["start"]), pd.Timestamp(window["end"])
    cn = result.daily.loc[start:end].copy()
    byd = benchmark.loc[start:end].copy()
    if bool(challenge["require_exact_session_alignment"]) and not cn.index.equals(byd.index):
        raise ValueError("CN_27 and BYD v1.3 common-window sessions do not align exactly")
    required_sessions = int(window["required_sessions"])
    if len(cn) != required_sessions or len(byd) != required_sessions:
        raise ValueError(
            f"challenge requires {required_sessions} aligned sessions; got CN_27={len(cn)}, "
            f"BYD={len(byd)}"
        )

    annual_sessions = int(contract.spec["metrics"]["annual_sessions"])
    annual_rf = float(contract.spec["metrics"]["annual_risk_free_rate"])
    cn_metrics = _return_metrics(
        cn["net_return"],
        annual_sessions=annual_sessions,
        annual_risk_free_rate=annual_rf,
    )
    byd_metrics = _return_metrics(
        byd["period_return"],
        annual_sessions=annual_sessions,
        annual_risk_free_rate=annual_rf,
    )
    years = required_sessions / float(annual_sessions)
    cn_metrics["annual_one_way_turnover"] = float(cn["one_way_turnover"].sum() / years)
    if challenge["benchmark_turnover_normalization"] != "half_sum_absolute_weight_change":
        raise ValueError("unsupported BYD v1.3 turnover normalization")
    byd_metrics["annual_one_way_turnover"] = float(byd["turnover"].sum() / 2.0 / years)
    cn_metrics["transaction_cost_paid"] = float(cn["transaction_cost"].sum())
    byd_metrics["transaction_cost_paid"] = float(byd["transaction_cost"].sum())
    financing = (
        pd.to_numeric(byd["financing_cost"], errors="coerce").fillna(0.0)
        if "financing_cost" in byd
        else pd.Series(0.0, index=byd.index)
    )
    byd_metrics["financing_cost_paid"] = float(financing.sum())

    gates = challenge["gates"]
    gate_results = {
        "total_return_strictly_above_benchmark": (
            cn_metrics["total_return"] > byd_metrics["total_return"]
        ),
        "cagr_strictly_above_benchmark": cn_metrics["cagr"] > byd_metrics["cagr"],
        "sharpe_log_excess_strictly_above_benchmark": (
            cn_metrics["sharpe_log_excess"] > byd_metrics["sharpe_log_excess"]
        ),
        "maximum_drawdown_not_worse_than_benchmark": (
            cn_metrics["maximum_drawdown"] >= byd_metrics["maximum_drawdown"]
        ),
        "calmar_strictly_above_benchmark": cn_metrics["calmar"] > byd_metrics["calmar"],
        "maximum_annual_one_way_turnover": (
            cn_metrics["annual_one_way_turnover"]
            <= float(gates["maximum_annual_one_way_turnover"])
        ),
    }
    risk_return_gate_names = (
        "total_return_strictly_above_benchmark",
        "cagr_strictly_above_benchmark",
        "sharpe_log_excess_strictly_above_benchmark",
        "maximum_drawdown_not_worse_than_benchmark",
        "calmar_strictly_above_benchmark",
    )
    risk_return_dominance = all(gate_results[name] for name in risk_return_gate_names)
    passed = all(gate_results.values())

    paired = pd.DataFrame(
        {
            "date": cn.index,
            "cn_27_net_return": cn["net_return"].to_numpy(),
            "byd_v1_3_net_return": byd["period_return"].to_numpy(),
            "cn_27_one_way_turnover": cn["one_way_turnover"].to_numpy(),
            "byd_v1_3_one_way_turnover": byd["turnover"].to_numpy() / 2.0,
        }
    )
    paired["cn_27_equity"] = (1.0 + paired["cn_27_net_return"]).cumprod()
    paired["byd_v1_3_equity"] = (1.0 + paired["byd_v1_3_net_return"]).cumprod()
    summary = {
        "schema_version": "1.0",
        "challenger_model_version_id": str(contract.spec["model_version_id"]),
        "benchmark_model_version_id": expected_model,
        "benchmark_manifest": str(challenge["benchmark_manifest"]),
        "benchmark_manifest_sha256": sha256_file(manifest_path),
        "benchmark_performance_sha256": sha256_file(performance_path),
        "common_window": {
            "start": start.date().isoformat(),
            "end": end.date().isoformat(),
            "sessions": required_sessions,
        },
        "challenger": cn_metrics,
        "benchmark": byd_metrics,
        "gate_results": gate_results,
        "historical_risk_return_dominance": risk_return_dominance,
        "turnover_efficiency_vs_benchmark": (
            cn_metrics["annual_one_way_turnover"]
            <= byd_metrics["annual_one_way_turnover"]
        ),
        "all_frozen_gates_passed": passed,
        "decision": (
            "historical_common_window_challenge_passed_no_fresh_holdout"
            if passed
            else "historical_common_window_challenge_not_passed"
        ),
        "fresh_historical_holdout": False,
        "research_only": True,
        "trade_ready": False,
    }
    return summary, paired


def _exit_reasons(
    row: pd.Series,
    *,
    entry_price: float,
    peak_high: float,
    exit_spec: Mapping[str, Any],
) -> list[str]:
    reasons: list[str] = []
    peak_profit = peak_high / entry_price - 1.0
    if (
        peak_profit >= float(exit_spec["divergence_profit_threshold"])
        and float(row["rsi14"]) > float(exit_spec["divergence_rsi_threshold"])
        and float(row["macd_hist"]) < float(row["previous_macd_hist"])
    ):
        reasons.append("divergence_take_profit")
    if (
        peak_profit >= float(exit_spec["trailing_activation_profit"])
        and float(row["close"]) <= peak_high * float(exit_spec["trailing_peak_ratio"])
    ):
        reasons.append("trailing_profit_protection")
    if (
        float(row["macd"]) < float(row["macd_signal"])
        or float(row["close"])
        < float(row["sma20"]) * float(exit_spec["trend_break_sma20_ratio"])
    ):
        reasons.append("trend_break")
    if float(row["close"]) <= entry_price * float(exit_spec["hard_stop_entry_ratio"]):
        reasons.append("hard_stop")
    return reasons


def _one_way_cost(
    before: Mapping[str, float],
    after: Mapping[str, float],
    *,
    candidate_symbols: tuple[str, ...],
    defensive_symbol: str,
    cost_spec: Mapping[str, Any],
) -> tuple[float, float, float, float]:
    stock_buys = sum(max(float(after[s]) - float(before[s]), 0.0) for s in candidate_symbols)
    stock_sells = sum(max(float(before[s]) - float(after[s]), 0.0) for s in candidate_symbols)
    etf_delta = float(after[defensive_symbol]) - float(before[defensive_symbol])
    cost = (
        stock_buys * float(cost_spec["stock_buy_rate"])
        + stock_sells * float(cost_spec["stock_sell_rate"])
        + max(etf_delta, 0.0) * float(cost_spec["etf_buy_rate"])
        + max(-etf_delta, 0.0) * float(cost_spec["etf_sell_rate"])
    )
    traded_assets = stock_buys + stock_sells + abs(etf_delta)
    return cost, traded_assets / 2.0, stock_buys, stock_sells


def run_all_weather_backtest(
    bars: pd.DataFrame,
    contract: AllWeatherContract,
) -> AllWeatherBacktestResult:
    """Run the frozen membership state machine with next-open execution."""

    clean = normalise_long_bars(bars)
    required = (
        *contract.candidate_symbols,
        contract.defensive_etf_symbol,
        contract.benchmark_symbol,
    )
    coverage = _coverage_table(clean, required)
    missing = coverage.loc[coverage["status"].ne("ready"), "symbol"].tolist()
    if missing:
        raise ValueError(f"required instruments missing from price data: {missing}")

    indicators = compute_all_weather_indicators(
        clean.loc[clean["symbol"].isin(contract.candidate_symbols)], contract.spec
    )
    indicators["previous_macd_hist"] = indicators.groupby("symbol", sort=False)[
        "macd_hist"
    ].shift(1)
    indicator_rows = {
        (pd.Timestamp(row.date), str(row.symbol)): row
        for row in indicators.itertuples(index=False)
    }

    defensive = contract.defensive_etf_symbol
    candidates = contract.candidate_symbols
    assets = (*candidates, defensive)
    by_symbol = {symbol: clean.loc[clean["symbol"].eq(symbol)].set_index("date") for symbol in required}
    calendar = pd.DatetimeIndex(by_symbol[defensive].index).sort_values().unique()
    evaluation_start = pd.Timestamp(contract.spec["data"]["evaluation_start"])
    cutoff = pd.Timestamp(contract.spec["data"]["cutoff"])
    calendar = calendar[(calendar >= evaluation_start) & (calendar <= cutoff)]
    if len(calendar) < 2:
        raise ValueError("evaluation calendar requires at least two ETF sessions")

    opens: dict[str, pd.Series] = {}
    observed: dict[str, pd.Series] = {}
    locked: dict[str, pd.Series] = {}
    highs: dict[str, pd.Series] = {}
    for symbol in assets:
        source = by_symbol[symbol]
        observed[symbol] = pd.Series(calendar.isin(source.index), index=calendar)
        opens[symbol] = source["open"].reindex(calendar).ffill()
        highs[symbol] = source["high"].reindex(calendar)
        one_price = np.isclose(source["high"], source["low"], rtol=0.0, atol=1e-12)
        locked[symbol] = pd.Series(one_price, index=source.index).reindex(calendar).fillna(False)
    open_returns = pd.DataFrame(
        {symbol: opens[symbol].pct_change(fill_method=None).fillna(0.0) for symbol in assets},
        index=calendar,
    )

    max_positions = int(contract.spec["portfolio"]["maximum_stock_positions"])
    target_weight = float(contract.spec["portfolio"]["stock_target_weight"])
    max_stock_weight = float(contract.spec["portfolio"]["maximum_stock_weight"])
    weights = {symbol: 0.0 for symbol in assets}
    weights["CASH"] = 1.0
    pending: tuple[str, ...] = ()
    entry_prices: dict[str, float] = {}
    peak_highs: dict[str, float] = {}
    entry_dates: dict[str, pd.Timestamp] = {}
    pending_exit_reasons: dict[str, list[str]] = {}
    daily_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    round_trip_rows: list[dict[str, Any]] = []
    equity = 1.0

    for step, date in enumerate(calendar):
        relative = {symbol: 1.0 + float(open_returns.loc[date, symbol]) for symbol in assets}
        gross_return = sum(weights[symbol] * (relative[symbol] - 1.0) for symbol in assets)
        gross_factor = 1.0 + gross_return
        if gross_factor <= 0.0:
            raise ValueError(f"non-positive portfolio gross factor on {date.date()}")
        before = {symbol: weights[symbol] * relative[symbol] / gross_factor for symbol in assets}
        before["CASH"] = weights["CASH"] / gross_factor

        desired = set(pending)
        after = dict(before)
        # Eligible exits run before entries. Missing or one-price bars defer the change.
        for symbol in candidates:
            can_trade = bool(observed[symbol].loc[date]) and not bool(locked[symbol].loc[date])
            if symbol not in desired and can_trade:
                after[symbol] = 0.0

        etf_can_trade = bool(observed[defensive].loc[date]) and not bool(locked[defensive].loc[date])
        capacity = max_stock_weight
        if not etf_can_trade:
            capacity = min(capacity, max(0.0, 1.0 - float(before[defensive])))
        # Reset every tradable desired name before assigning fixed targets.
        # Untradable weights remain economically held and consume capacity.
        for symbol in pending:
            can_trade = bool(observed[symbol].loc[date]) and not bool(locked[symbol].loc[date])
            if can_trade:
                after[symbol] = 0.0
        for symbol in pending:
            can_trade = bool(observed[symbol].loc[date]) and not bool(locked[symbol].loc[date])
            if not can_trade:
                continue
            other = sum(after[item] for item in candidates if item != symbol)
            if other + target_weight <= capacity + 1e-12:
                after[symbol] = target_weight

        stock_total = sum(after[symbol] for symbol in candidates)
        locked_stock_weight = sum(
            after[symbol]
            for symbol in candidates
            if not bool(observed[symbol].loc[date]) or bool(locked[symbol].loc[date])
        )
        passive_limit_breach = stock_total > max_stock_weight + 1e-10
        if passive_limit_breach and locked_stock_weight <= 0.0:
            raise ValueError(f"tradable stock exposure exceeds frozen maximum on {date.date()}")
        if etf_can_trade:
            after[defensive] = max(0.0, 1.0 - stock_total)
        after["CASH"] = 1.0 - sum(after[symbol] for symbol in assets)
        if after["CASH"] < -1e-10:
            raise ValueError(f"execution would create leverage on {date.date()}")
        after["CASH"] = max(0.0, after["CASH"])

        cost, one_way_turnover, stock_buys, stock_sells = _one_way_cost(
            before,
            after,
            candidate_symbols=candidates,
            defensive_symbol=defensive,
            cost_spec=contract.spec["costs"],
        )
        if step == 0 and not bool(contract.spec["costs"]["charge_initial_entry"]):
            cost = 0.0
        net_return = gross_return - cost
        equity *= 1.0 + net_return

        membership_before = {symbol for symbol in candidates if before[symbol] > 1e-10}
        membership_after = {symbol for symbol in candidates if after[symbol] > 1e-10}
        for symbol in assets:
            delta = after[symbol] - before[symbol]
            if abs(delta) <= 1e-12:
                continue
            if symbol == defensive:
                reason = "residual_defensive_rebalance"
            elif delta > 0.0 and symbol not in membership_before:
                reason = "entry_signal"
            elif delta < 0.0 and symbol not in membership_after:
                reason = "+".join(pending_exit_reasons.get(symbol, ["membership_exit"]))
            else:
                reason = "target_weight_rebalance"
            rate = (
                float(contract.spec["costs"]["etf_buy_rate" if delta > 0 else "etf_sell_rate"])
                if symbol == defensive
                else float(
                    contract.spec["costs"]["stock_buy_rate" if delta > 0 else "stock_sell_rate"]
                )
            )
            trade_rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "side": "buy" if delta > 0 else "sell",
                    "weight_change": abs(float(delta)),
                    "cost_rate": rate,
                    "cost": abs(float(delta)) * rate,
                    "reason": reason,
                    "signal_date": None if step == 0 else calendar[step - 1],
                }
            )

        for symbol in sorted(membership_after - membership_before):
            if not bool(observed[symbol].loc[date]):
                continue
            entry_prices[symbol] = float(opens[symbol].loc[date])
            peak_highs[symbol] = entry_prices[symbol]
            entry_dates[symbol] = date
        for symbol in sorted(membership_before - membership_after):
            exit_price = float(opens[symbol].loc[date])
            entry_price = entry_prices.pop(symbol)
            round_trip_rows.append(
                {
                    "symbol": symbol,
                    "entry_date": entry_dates.pop(symbol),
                    "exit_date": date,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "return": exit_price / entry_price - 1.0,
                    "exit_reasons": "+".join(pending_exit_reasons.get(symbol, [])),
                }
            )
            peak_highs.pop(symbol, None)

        for symbol in membership_after:
            high = highs[symbol].loc[date]
            if pd.notna(high):
                peak_highs[symbol] = max(peak_highs.get(symbol, float(high)), float(high))

        exits: dict[str, list[str]] = {}
        survivors: list[str] = []
        for symbol in sorted(membership_after):
            raw_row = indicator_rows.get((date, symbol))
            if raw_row is None:
                survivors.append(symbol)
                continue
            row = pd.Series(raw_row._asdict())
            reasons = _exit_reasons(
                row,
                entry_price=entry_prices[symbol],
                peak_high=peak_highs[symbol],
                exit_spec=contract.spec["exit"],
            )
            if reasons:
                exits[symbol] = reasons
            else:
                survivors.append(symbol)

        vacancies = max_positions - len(survivors)
        entrants: list[str] = []
        if vacancies > 0:
            ranked: list[tuple[float, str]] = []
            for symbol in candidates:
                if symbol in membership_after:
                    continue
                raw_row = indicator_rows.get((date, symbol))
                if raw_row is None or not bool(raw_row.entry_eligible) or pd.isna(raw_row.score):
                    continue
                ranked.append((float(raw_row.score), symbol))
            ranked.sort(key=lambda value: (-value[0], value[1]))
            entrants = [symbol for _, symbol in ranked[:vacancies]]
        pending = tuple([*survivors, *entrants])
        pending_exit_reasons = exits

        daily_rows.append(
            {
                "date": date,
                "gross_return": gross_return,
                "transaction_cost": cost,
                "net_return": net_return,
                "equity": equity,
                "stock_weight": stock_total,
                "etf_weight": after[defensive],
                "cash_weight": after["CASH"],
                "holding_count": len(membership_after),
                "holdings": json.dumps(sorted(membership_after), ensure_ascii=False),
                "next_target_holdings": json.dumps(list(pending), ensure_ascii=False),
                "exit_signals": json.dumps(exits, sort_keys=True, ensure_ascii=False),
                "one_way_turnover": one_way_turnover,
                "stock_buy_weight": stock_buys,
                "stock_sell_weight": stock_sells,
                "trade_locked_stock_weight": locked_stock_weight,
                "stock_limit_breach_due_to_trade_lock": passive_limit_breach,
            }
        )
        weights = after

    daily = pd.DataFrame(daily_rows).set_index("date")
    daily["drawdown"] = daily["equity"] / daily["equity"].cummax() - 1.0
    trades = pd.DataFrame(trade_rows)
    round_trips = pd.DataFrame(round_trip_rows)
    metrics = _return_metrics(
        daily["net_return"],
        annual_sessions=int(contract.spec["metrics"]["annual_sessions"]),
        annual_risk_free_rate=float(contract.spec["metrics"]["annual_risk_free_rate"]),
    )
    years = len(daily) / float(contract.spec["metrics"]["annual_sessions"])
    metrics.update(
        {
            "annual_one_way_turnover": float(daily["one_way_turnover"].sum() / years),
            "transaction_cost_paid": float(daily["transaction_cost"].sum()),
            "average_stock_weight": float(daily["stock_weight"].mean()),
            "average_etf_weight": float(daily["etf_weight"].mean()),
            "round_trips": int(len(round_trips)),
            "win_rate": (
                float(round_trips["return"].gt(0.0).mean()) if not round_trips.empty else np.nan
            ),
            "profit_factor": (
                _profit_factor(round_trips["return"]) if not round_trips.empty else np.nan
            ),
            "research_only": True,
            "trade_ready": False,
            "baselines": _baseline_metrics(clean, contract, calendar),
        }
    )
    return AllWeatherBacktestResult(
        daily=daily,
        trades=trades,
        round_trips=round_trips,
        coverage=coverage,
        indicators=indicators,
        metrics=metrics,
    )


def _profit_factor(returns: pd.Series) -> float:
    gains = float(returns.loc[returns > 0.0].sum())
    losses = abs(float(returns.loc[returns < 0.0].sum()))
    return gains / losses if losses > 1e-12 else np.nan


def _baseline_metrics(
    bars: pd.DataFrame,
    contract: AllWeatherContract,
    calendar: pd.DatetimeIndex,
) -> dict[str, dict[str, Any]]:
    annual_sessions = int(contract.spec["metrics"]["annual_sessions"])
    annual_rf = float(contract.spec["metrics"]["annual_risk_free_rate"])

    def open_returns(symbol: str) -> pd.Series:
        source = bars.loc[bars["symbol"].eq(symbol)].set_index("date")["open"]
        return source.reindex(calendar).ffill().pct_change(fill_method=None).fillna(0.0)

    etf_returns = open_returns(contract.defensive_etf_symbol)
    etf_returns.iloc[0] -= float(contract.spec["costs"]["etf_buy_rate"])
    benchmark_returns = open_returns(contract.benchmark_symbol)
    candidate_matrix = pd.DataFrame(
        {symbol: open_returns(symbol) for symbol in contract.candidate_symbols}, index=calendar
    )
    equal_weight_returns = candidate_matrix.mean(axis=1)
    equal_weight_returns.iloc[0] -= float(contract.spec["costs"]["stock_buy_rate"])
    return {
        "buy_hold_515180": _return_metrics(
            etf_returns,
            annual_sessions=annual_sessions,
            annual_risk_free_rate=annual_rf,
        ),
        "buy_hold_csi300": _return_metrics(
            benchmark_returns,
            annual_sessions=annual_sessions,
            annual_risk_free_rate=annual_rf,
        ),
        "equal_weight_27": _return_metrics(
            equal_weight_returns,
            annual_sessions=annual_sessions,
            annual_risk_free_rate=annual_rf,
        ),
    }


def _build_cn_router(provider_order: list[str]):
    from src.data.adapters.akshare_adapter import AkShareAdapter
    from src.data.adapters.akshare_sina_adapter import AkShareSinaAdapter
    from src.data.adapters.efinance_adapter import EFinanceAdapter
    from src.data.adapters.tencent_fqkline_adapter import TencentQfqHistoryAdapter
    from src.data.adapters.yfinance_adapter import YFinanceAdapter
    from src.data.router import MarketDataRouter

    adapters = [
        AkShareSinaAdapter(),
        AkShareAdapter(),
        EFinanceAdapter(),
        TencentQfqHistoryAdapter(),
        YFinanceAdapter(),
    ]
    return MarketDataRouter(adapters=adapters, policy={"cn": provider_order})


def fetch_all_weather_bars(
    contract: AllWeatherContract,
    *,
    max_workers: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch one complete adjusted history per symbol with auditable fallback."""

    if max_workers <= 0:
        raise ValueError("max_workers must be positive")
    symbols = (
        *contract.candidate_symbols,
        contract.defensive_etf_symbol,
        contract.benchmark_symbol,
    )
    start = str(contract.spec["data"]["fetch_start"])
    cutoff = str(contract.spec["data"]["cutoff"])
    provider_order = [str(value) for value in contract.spec["data"]["ordered_providers"]]

    def fetch_one(symbol: str) -> tuple[str, pd.DataFrame | None, dict[str, Any]]:
        router = _build_cn_router(provider_order)
        response = router.fetch_daily_bars(
            symbol=symbol,
            market="cn",
            start=start,
            end=cutoff,
            validate=True,
        )
        attempts = [attempt.to_dict() for attempt in response.attempts]
        if not response.ok or response.result is None:
            return symbol, None, {"symbol": symbol, "status": "provider_missing", "attempts": attempts}
        frame = response.result.df.copy()
        frame.insert(1, "symbol", symbol)
        return symbol, frame, {
            "symbol": symbol,
            "status": "ready",
            "provider": response.result.provider,
            "provider_symbol": response.result.provider_symbol,
            "rows": int(len(frame)),
            "first_date": pd.Timestamp(frame["date"].min()).date().isoformat(),
            "last_date": pd.Timestamp(frame["date"].max()).date().isoformat(),
            "attempts": attempts,
        }

    frames: dict[str, pd.DataFrame] = {}
    records: dict[str, dict[str, Any]] = {}
    if max_workers == 1:
        # Several optional CN provider packages initialize embedded native
        # runtimes during import.  Serial execution is the stable Windows path.
        for requested_symbol in symbols:
            symbol, frame, record = fetch_one(requested_symbol)
            records[symbol] = record
            if frame is not None:
                frames[symbol] = frame
    else:
        # Import provider packages once before worker threads are created.
        _build_cn_router(provider_order)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(fetch_one, symbol): symbol for symbol in symbols}
            for future in as_completed(futures):
                symbol, frame, record = future.result()
                records[symbol] = record
                if frame is not None:
                    frames[symbol] = frame
    coverage = pd.DataFrame([records[symbol] for symbol in symbols])
    failed = coverage.loc[coverage["status"].ne("ready"), "symbol"].tolist()
    if failed:
        details = {
            row["symbol"]: [attempt.get("error") for attempt in row["attempts"]]
            for row in coverage.to_dict(orient="records")
            if row["status"] != "ready"
        }
        raise ValueError(f"price refresh failed closed for {failed}: {details}")
    return normalise_long_bars(pd.concat([frames[symbol] for symbol in symbols], ignore_index=True)), coverage


def _json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(_json_value(dict(payload)), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _external_claim_audit(metrics: Mapping[str, Any]) -> dict[str, Any]:
    claims = {
        "total_return": 2.4641,
        "cagr": 0.5365,
        "annual_volatility": 0.1323,
        "maximum_drawdown": -0.1332,
        "sharpe_log_excess": 3.90,
        "calmar": 4.03,
        "annual_one_way_turnover": 0.156,
    }
    tolerances = {
        "total_return": 0.005,
        "cagr": 0.005,
        "annual_volatility": 0.005,
        "maximum_drawdown": 0.005,
        "sharpe_log_excess": 0.05,
        "calmar": 0.05,
        "annual_one_way_turnover": 0.005,
    }
    comparisons: dict[str, Any] = {}
    for name, claimed in claims.items():
        observed = float(metrics[name])
        difference = observed - claimed
        comparisons[name] = {
            "claimed": claimed,
            "observed": observed,
            "difference": difference,
            "tolerance": tolerances[name],
            "reproduced": abs(difference) <= tolerances[name],
        }
    return {
        "source_status": "unverified_external_claims",
        "all_claims_reproduced": all(row["reproduced"] for row in comparisons.values()),
        "comparisons": comparisons,
    }


def materialize_all_weather_evidence(
    *,
    output_dir: str | Path,
    source_prices_path: str | Path,
    contract: AllWeatherContract,
    result: AllWeatherBacktestResult,
    provider_coverage: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Write one manifest-bound research evidence bundle."""

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    source_path = Path(source_prices_path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"source price artifact is missing: {source_path}")

    daily_path = output / "daily.csv"
    trades_path = output / "trades.csv"
    round_trips_path = output / "round_trips.csv"
    coverage_path = output / "coverage.csv"
    indicators_path = output / "factor_signal_history.csv"
    metrics_path = output / "metrics.json"
    decision_path = output / "decision.json"
    report_path = output / "report.md"
    comparison_path = output / "benchmark_comparison.json"
    comparison_daily_path = output / "benchmark_comparison_daily.csv"

    result.daily.reset_index().to_csv(daily_path, index=False, date_format="%Y-%m-%d")
    result.trades.to_csv(trades_path, index=False, date_format="%Y-%m-%d")
    result.round_trips.to_csv(round_trips_path, index=False, date_format="%Y-%m-%d")
    combined_coverage = result.coverage.copy()
    if provider_coverage is not None and not provider_coverage.empty:
        provider = provider_coverage.copy()
        if "attempts" in provider:
            provider["attempts"] = provider["attempts"].map(
                lambda value: json.dumps(_json_value(value), sort_keys=True, ensure_ascii=False)
            )
        combined_coverage = combined_coverage.drop(
            columns=[column for column in combined_coverage if column != "symbol"], errors="ignore"
        ).merge(provider, on="symbol", how="left", validate="one_to_one")
    combined_coverage.to_csv(coverage_path, index=False)
    result.indicators.to_csv(indicators_path, index=False, date_format="%Y-%m-%d")
    _write_json(metrics_path, result.metrics)

    comparison = None
    if isinstance(contract.spec.get("challenge"), dict):
        comparison, comparison_daily = evaluate_byd_v1_3_challenge(result, contract)
        _write_json(comparison_path, comparison)
        comparison_daily.to_csv(comparison_daily_path, index=False, date_format="%Y-%m-%d")

    if contract.spec.get("evidence", {}).get("preserve_external_claims_as_unverified") is True:
        claim_audit = _external_claim_audit(result.metrics)
    else:
        claim_audit = {
            "source_status": str(
                contract.spec.get("evidence", {}).get(
                    "external_synthetic_claims_status", "not_part_of_this_contract"
                )
            ),
            "all_claims_reproduced": False,
            "comparisons": {},
        }
    stress = result.daily.loc[
        str(contract.spec["evidence"]["stress_window"]["start"]) : str(
            contract.spec["evidence"]["stress_window"]["end"]
        )
    ]
    stress_summary = {
        "observations": int(len(stress)),
        "total_return": (
            float((1.0 + stress["net_return"]).prod() - 1.0) if not stress.empty else None
        ),
        "average_etf_weight": float(stress["etf_weight"].mean()) if not stress.empty else None,
        "minimum_etf_weight": float(stress["etf_weight"].min()) if not stress.empty else None,
    }
    decision = {
        "schema_version": "1.0",
        "experiment_id": str(contract.spec["experiment_id"]),
        "decision": (
            comparison["decision"]
            if comparison is not None
            else (
                "external_performance_claims_reproduced"
                if claim_audit["all_claims_reproduced"]
                else "external_performance_claims_not_reproduced"
            )
        ),
        "research_only": True,
        "trade_ready": False,
        "selected_pool_readiness_claimed": False,
        "strategy_specific_pool": True,
        "candidate_count": len(contract.candidate_symbols),
        "defensive_etf": f"{contract.defensive_etf_symbol}.SH",
        "benchmark": f"{contract.benchmark_symbol}.SH",
        "claim_audit": claim_audit,
        "stress_window": stress_summary,
    }
    if comparison is not None:
        decision["benchmark_challenge"] = {
            "benchmark_model_version_id": comparison["benchmark_model_version_id"],
            "common_window": comparison["common_window"],
            "historical_risk_return_dominance": comparison[
                "historical_risk_return_dominance"
            ],
            "turnover_efficiency_vs_benchmark": comparison[
                "turnover_efficiency_vs_benchmark"
            ],
            "all_frozen_gates_passed": comparison["all_frozen_gates_passed"],
            "fresh_historical_holdout": False,
        }
    _write_json(decision_path, decision)

    if comparison is None:
        comparison_section = ["## 外部绩效主张复核", ""]
        comparison_section.extend(
            [
                "| 指标 | 文档主张 | 本次结果 | 差异 | 复现 |",
                "|---|---:|---:|---:|:---:|",
            ]
        )
        for name, item in claim_audit["comparisons"].items():
            comparison_section.append(
                f"| {name} | {item['claimed']:.6f} | {item['observed']:.6f} | "
                f"{item['difference']:.6f} | {'是' if item['reproduced'] else '否'} |"
            )
    else:
        comparison_section = [
            "## BYD v1.3 同窗挑战",
            "",
            "| 指标 | CN_27 V1.0 | BYD v1.3 | CN_27 胜出 |",
            "|---|---:|---:|:---:|",
        ]
        pairs = (
            ("total_return", "total_return_strictly_above_benchmark"),
            ("cagr", "cagr_strictly_above_benchmark"),
            ("annual_volatility", None),
            ("sharpe_log_excess", "sharpe_log_excess_strictly_above_benchmark"),
            ("maximum_drawdown", "maximum_drawdown_not_worse_than_benchmark"),
            ("calmar", "calmar_strictly_above_benchmark"),
            ("annual_one_way_turnover", None),
        )
        for metric_name, gate_name in pairs:
            cn_value = comparison["challenger"][metric_name]
            byd_value = comparison["benchmark"][metric_name]
            if gate_name is None:
                won = cn_value <= byd_value if metric_name == "annual_volatility" else False
                if metric_name == "annual_one_way_turnover":
                    won = comparison["turnover_efficiency_vs_benchmark"]
            else:
                won = comparison["gate_results"][gate_name]
            comparison_section.append(
                f"| {metric_name} | {cn_value:.6f} | {byd_value:.6f} | "
                f"{'是' if won else '否'} |"
            )
        comparison_section.extend(
            [
                "",
                f"- 冻结门槛全部通过：{comparison['all_frozen_gates_passed']}",
                f"- 风险收益五项占优：{comparison['historical_risk_return_dominance']}",
                f"- 换手效率高于 BYD：{comparison['turnover_efficiency_vs_benchmark']}",
                "- 该比较使用已观察历史，不构成新鲜样本验证或自动晋级依据。",
            ]
        )
    report = "\n".join(
        [
            f"# {contract.spec.get('display_name', '全天候多资产阿尔法轮动 v1')} 研究报告",
            "",
            "> 研究边界：`research_only=true`；`trade_ready=false`。本实验使用独立冻结的",
            "> 27 股策略池，不声明满足 CN130 selected-pool readiness gate。",
            "",
            f"- 决策：`{decision['decision']}`",
            f"- 评估区间：{result.metrics['start_date']} 至 {result.metrics['end_date']}",
            f"- 防守 ETF：{contract.defensive_etf_symbol}.SH（不进入候选截面）",
            f"- 基准：{contract.benchmark_symbol}.SH（不可执行）",
            "- 信号与执行：收盘生成信号，下一可交易开盘执行；无同收盘成交。",
            "- 参数：最多 5 股、每股目标 15%、股票上限 75%、余额进入 515180.SH。",
            "",
            *comparison_section,
            "",
            "## 2024 年初压力窗口",
            "",
            f"- 观察数：{stress_summary['observations']}",
            f"- 组合收益：{stress_summary['total_return']}",
            f"- 平均红利 ETF 权重：{stress_summary['average_etf_weight']}",
            "",
            "## 解释限制",
            "",
            (
                "CN_27 V1.0 使用事后补充确认的三日相对 SMA20 斜率；全部历史均已被观察，"
                "因此结果只属于回溯挑战证据。"
                if comparison is not None
                else "原文没有唯一规定 SMA20 slope 的窗口，也把持仓数、单股权重写成区间。"
            ),
            (
                "后续不得在同一历史上修改成员、因子、成本或阈值并把结果描述为新鲜验证。"
                if comparison is not None
                else "v1 冻结为 SMA20 单日差分、最多 5 股、每股 15%，不在观察结果后改参。"
            ),
        ]
    )
    report_path.write_text(report + "\n", encoding="utf-8")

    output_paths = [
        daily_path,
        trades_path,
        round_trips_path,
        coverage_path,
        indicators_path,
        metrics_path,
        decision_path,
        report_path,
    ]
    if comparison is not None:
        output_paths.extend([comparison_path, comparison_daily_path])
    outputs = {path.name: sha256_file(path) for path in output_paths}
    identity = contract_identity(contract)
    manifest = {
        "schema_version": "1.0",
        "experiment_id": str(contract.spec["experiment_id"]),
        "research_only": True,
        "trade_ready": False,
        "contract_identity": identity,
        "source_prices": {"path": str(source_path), "sha256": sha256_file(source_path)},
        "outputs": outputs,
    }
    manifest["manifest_identity_sha256"] = canonical_sha256(manifest)
    _write_json(output / "evidence_manifest.json", manifest)
    return decision
