"""Deterministic, per-security cycle signal engine for the frozen focus list."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from src.research.research_artifacts import write_json


REQUIRED_PRICE_COLUMNS = ("date", "symbol", "open", "high", "low", "close")
VALID_STATES = ("WATCH", "ENTER", "HOLD", "REDUCE", "EXIT")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_focus_signal_spec(path: str | Path) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("focus signal spec must be a mapping")
    validate_focus_signal_spec(payload)
    return payload


def validate_focus_signal_spec(spec: Mapping[str, Any]) -> None:
    universe = spec.get("universe", {})
    signal = spec.get("signal", {})
    symbols = list(universe.get("symbols", []))
    signal_symbols = list(universe.get("signal_symbols", []))
    references = list(universe.get("market_reference_symbols", [])) + list(
        universe.get("sector_reference_symbols", [])
    )

    if not symbols or len(symbols) != len(set(symbols)):
        raise ValueError("focus universe must be non-empty and unique")
    if not signal_symbols or not set(signal_symbols).issubset(symbols):
        raise ValueError("signal_symbols must be a non-empty subset of symbols")
    if set(signal_symbols).intersection(references):
        raise ValueError("reference symbols cannot also be signal targets")
    if signal.get("states") != list(VALID_STATES):
        raise ValueError("unexpected focus signal state contract")
    if spec.get("objective", {}).get("cross_sectional_ranking") is not False:
        raise ValueError("focus signal engine cannot use cross-sectional ranking")
    if spec.get("parameter_search", {}).get("allowed") is not False:
        raise ValueError("parameter search must remain disabled")


def load_long_ohlcv_csv(path: str | Path, spec: Mapping[str, Any]) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    missing_columns = [column for column in REQUIRED_PRICE_COLUMNS if column not in frame]
    if missing_columns:
        raise ValueError(f"price CSV missing columns: {missing_columns}")

    frame = frame.copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="raise").dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str).str.strip().str.upper()
    aliases = {
        str(provider).upper(): str(display).upper()
        for display, provider in spec["universe"].get("provider_aliases", {}).items()
    }
    frame["symbol"] = frame["symbol"].replace(aliases)

    for column in ("open", "high", "low", "close", "volume"):
        if column in frame:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame[list(REQUIRED_PRICE_COLUMNS[2:])].isna().any().any():
        raise ValueError("price CSV contains non-numeric or missing OHLC values")
    if frame.duplicated(["date", "symbol"]).any():
        raise ValueError("price CSV contains duplicate date/symbol rows")

    frame = frame.sort_values(["symbol", "date"]).reset_index(drop=True)
    required_symbols = set(map(str, spec["universe"]["symbols"]))
    available_symbols = set(frame["symbol"].unique())
    missing_symbols = sorted(required_symbols - available_symbols)
    if missing_symbols:
        raise ValueError(f"price CSV missing required focus symbols: {missing_symbols}")
    return frame


def _true_range(group: pd.DataFrame) -> pd.Series:
    previous_close = group["close"].shift(1)
    components = pd.concat(
        [
            group["high"] - group["low"],
            (group["high"] - previous_close).abs(),
            (group["low"] - previous_close).abs(),
        ],
        axis=1,
    )
    return components.max(axis=1)


def _regime_labels(close: pd.Series, sma50: pd.Series, sma200: pd.Series) -> pd.Series:
    bull = (close > sma200) & (sma50 > sma200)
    bear = (close < sma200) & (sma50 < sma200)
    recovery = (close > sma200) & (sma50 <= sma200)
    return pd.Series(
        np.select(
            [bull, bear, recovery],
            ["bull", "bear", "recovery"],
            default="sideways_or_high_volatility",
        ),
        index=close.index,
        dtype="object",
    )


def compute_focus_indicators(
    prices: pd.DataFrame,
    spec: Mapping[str, Any],
) -> pd.DataFrame:
    signal_cfg = spec["signal"]
    trend_cfg = signal_cfg["security_trend"]
    medium = int(trend_cfg["medium_trend_days"])
    long_days = int(trend_cfg["long_trend_days"])
    rel_days = int(trend_cfg["relative_momentum_days"])
    breakout_days = int(trend_cfg["breakout_days"])
    atr_days = int(trend_cfg["atr_days"])

    rows: list[pd.DataFrame] = []
    for symbol, raw_group in prices.groupby("symbol", sort=False):
        group = raw_group.sort_values("date").copy()
        group["sma_50"] = group["close"].rolling(medium, min_periods=medium).mean()
        group["sma_100"] = group["close"].rolling(long_days, min_periods=long_days).mean()
        group["sma_200"] = group["close"].rolling(200, min_periods=200).mean()
        group["sma_50_slope"] = group["sma_50"].diff()
        group["return_63"] = group["close"] / group["close"].shift(rel_days) - 1.0
        group["prior_high_20"] = (
            group["close"].shift(1).rolling(breakout_days, min_periods=breakout_days).max()
        )
        group["atr_20"] = _true_range(group).rolling(atr_days, min_periods=atr_days).mean()
        rows.append(group)

    indicators = pd.concat(rows, ignore_index=True)
    qqq_symbol = str(signal_cfg["market_regime"]["reference"])
    qqq = indicators[indicators["symbol"] == qqq_symbol].copy()
    if qqq.empty:
        raise ValueError(f"market reference {qqq_symbol} is absent")
    qqq = qqq.sort_values("date")
    qqq["risk_on"] = (qqq["close"] > qqq["sma_200"]) & (
        qqq["sma_50"] > qqq["sma_200"]
    )
    qqq["market_regime"] = _regime_labels(qqq["close"], qqq["sma_50"], qqq["sma_200"])
    qqq_context = qqq[
        ["date", "return_63", "risk_on", "market_regime", "sma_50", "sma_200", "close"]
    ].rename(
        columns={
            "return_63": "qqq_return_63",
            "sma_50": "qqq_sma_50",
            "sma_200": "qqq_sma_200",
            "close": "qqq_close",
        }
    )
    indicators = indicators.merge(qqq_context, on="date", how="left", validate="many_to_one")
    indicators["rel_mom_63_vs_qqq"] = indicators["return_63"] - indicators["qqq_return_63"]
    return indicators.sort_values(["symbol", "date"]).reset_index(drop=True)


def _next_session_map(reference_dates: pd.Series) -> dict[pd.Timestamp, pd.Timestamp | None]:
    dates = list(pd.Series(reference_dates.dropna().unique()).sort_values())
    result: dict[pd.Timestamp, pd.Timestamp | None] = {}
    for index, value in enumerate(dates):
        current = pd.Timestamp(value)
        result[current] = pd.Timestamp(dates[index + 1]) if index + 1 < len(dates) else None
    return result


def _watch_reasons(row: pd.Series) -> list[str]:
    reasons: list[str] = []
    if not bool(row["risk_on"]):
        reasons.append("WATCH_MARKET_RISK_OFF")
    if row["close"] <= row["sma_100"]:
        reasons.append("WATCH_BELOW_SMA100")
    if row["sma_50_slope"] <= 0:
        reasons.append("WATCH_SMA50_SLOPE_NONPOSITIVE")
    if row["rel_mom_63_vs_qqq"] <= 0:
        reasons.append("WATCH_RELATIVE_MOMENTUM_NONPOSITIVE")
    if row["close"] <= row["prior_high_20"]:
        reasons.append("WATCH_NO_BREAKOUT")
    return reasons or ["WATCH_ENTRY_NOT_CONFIRMED"]


def _indicator_payload(row: pd.Series, trailing_stop: float | None) -> dict[str, Any]:
    fields = (
        "close",
        "sma_50",
        "sma_100",
        "sma_50_slope",
        "rel_mom_63_vs_qqq",
        "prior_high_20",
        "atr_20",
        "qqq_close",
        "qqq_sma_50",
        "qqq_sma_200",
    )
    payload: dict[str, Any] = {}
    for field in fields:
        value = row[field]
        payload[field] = None if pd.isna(value) else float(value)
    payload["trailing_stop_3atr"] = None if trailing_stop is None else float(trailing_stop)
    return payload


def generate_signal_history(
    indicators: pd.DataFrame,
    spec: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    signal_symbols = list(map(str, spec["universe"]["signal_symbols"]))
    qqq_symbol = str(spec["signal"]["market_regime"]["reference"])
    sector_symbol = str(spec["signal"]["sector_context"]["reference"])
    multiple = float(spec["signal"]["security_trend"]["trailing_stop_atr_multiple"])
    next_sessions = _next_session_map(indicators.loc[indicators["symbol"] == qqq_symbol, "date"])

    history: list[dict[str, Any]] = []
    for symbol in signal_symbols:
        group = indicators[indicators["symbol"] == symbol].sort_values("date")
        position_open = False
        previous_state = "WATCH"
        peak_high: float | None = None
        trailing_stop: float | None = None

        for _, row in group.iterrows():
            required = (
                "sma_50",
                "sma_100",
                "sma_50_slope",
                "rel_mom_63_vs_qqq",
                "prior_high_20",
                "atr_20",
                "qqq_sma_50",
                "qqq_sma_200",
            )
            sufficient = not row[list(required)].isna().any()
            reasons: list[str]

            if not sufficient:
                state = "EXIT" if position_open else "WATCH"
                reasons = [
                    "EXIT_INSUFFICIENT_DATA_FAIL_CLOSED"
                    if position_open
                    else "WATCH_INSUFFICIENT_HISTORY"
                ]
                if position_open:
                    position_open = False
                    peak_high = None
                    trailing_stop = None
            elif not position_open:
                enter = bool(
                    row["risk_on"]
                    and row["close"] > row["sma_100"]
                    and row["sma_50_slope"] > 0
                    and row["rel_mom_63_vs_qqq"] > 0
                    and row["close"] > row["prior_high_20"]
                )
                if enter:
                    state = "ENTER"
                    reasons = ["ENTER_BREAKOUT_TREND_RELATIVE_STRENGTH_CONFIRMED"]
                    position_open = True
                    peak_high = float(row["high"])
                    trailing_stop = peak_high - multiple * float(row["atr_20"])
                else:
                    state = "WATCH"
                    reasons = _watch_reasons(row)
            else:
                peak_high = max(float(peak_high), float(row["high"]))
                candidate_stop = peak_high - multiple * float(row["atr_20"])
                trailing_stop = max(float(trailing_stop), candidate_stop)
                if not bool(row["risk_on"]):
                    state = "EXIT"
                    reasons = ["EXIT_MARKET_RISK_OFF"]
                elif float(row["close"]) <= trailing_stop:
                    state = "EXIT"
                    reasons = ["EXIT_TRAILING_STOP_3ATR"]
                elif row["close"] <= row["sma_50"] or row["rel_mom_63_vs_qqq"] <= 0:
                    state = "REDUCE"
                    reasons = []
                    if row["close"] <= row["sma_50"]:
                        reasons.append("REDUCE_BELOW_SMA50")
                    if row["rel_mom_63_vs_qqq"] <= 0:
                        reasons.append("REDUCE_RELATIVE_MOMENTUM_NONPOSITIVE")
                else:
                    state = "HOLD"
                    reasons = ["HOLD_TREND_AND_STOP_INTACT"]

                if state == "EXIT":
                    position_open = False
                    peak_high = None
                    trailing_stop = None

            date = pd.Timestamp(row["date"])
            actionable = next_sessions.get(date)
            history.append(
                {
                    "date": date.date().isoformat(),
                    "symbol": symbol,
                    "state": state,
                    "previous_state": previous_state,
                    "state_changed": state != previous_state,
                    "position_open_after_close": bool(position_open),
                    "reason_codes": reasons,
                    "market_regime": str(row["market_regime"]),
                    "risk_on": None if pd.isna(row["risk_on"]) else bool(row["risk_on"]),
                    "actionable_from": None if actionable is None else actionable.date().isoformat(),
                    "indicators": _indicator_payload(row, trailing_stop),
                }
            )
            previous_state = state

    reference_history: list[dict[str, Any]] = []
    for symbol, role in ((qqq_symbol, "market_regime"), (sector_symbol, "sector_context")):
        group = indicators[indicators["symbol"] == symbol].sort_values("date")
        for _, row in group.iterrows():
            regime = _regime_labels(
                pd.Series([row["close"]]),
                pd.Series([row["sma_50"]]),
                pd.Series([row["sma_200"]]),
            ).iloc[0]
            reference_history.append(
                {
                    "date": pd.Timestamp(row["date"]).date().isoformat(),
                    "symbol": symbol,
                    "role": role,
                    "regime": str(regime),
                    "close": float(row["close"]),
                    "sma_50": None if pd.isna(row["sma_50"]) else float(row["sma_50"]),
                    "sma_200": None if pd.isna(row["sma_200"]) else float(row["sma_200"]),
                }
            )
    return history, reference_history


def run_focus_watchlist_signal(
    *,
    spec_path: str | Path,
    prices_csv: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    spec_path = Path(spec_path)
    prices_csv = Path(prices_csv)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    spec = load_focus_signal_spec(spec_path)
    prices = load_long_ohlcv_csv(prices_csv, spec)
    indicators = compute_focus_indicators(prices, spec)
    signal_history, reference_history = generate_signal_history(indicators, spec)

    latest: dict[str, dict[str, Any]] = {}
    for row in signal_history:
        latest[row["symbol"]] = row
    latest_references: dict[str, dict[str, Any]] = {}
    for row in reference_history:
        latest_references[row["symbol"]] = row

    provider_identity = sha256_file(prices_csv)
    spec_identity = sha256_file(spec_path)
    signal_payload = {
        "schema_version": "1.0",
        "experiment_id": spec["experiment_id"],
        "provider_identity_sha256": provider_identity,
        "spec_identity_sha256": spec_identity,
        "rows": signal_history,
    }
    reference_payload = {
        "schema_version": "1.0",
        "experiment_id": spec["experiment_id"],
        "rows": reference_history,
    }
    current_payload = {
        "schema_version": "1.0",
        "experiment_id": spec["experiment_id"],
        "signals": latest,
        "references": latest_references,
        "research_only": True,
        "trade_ready": False,
    }
    decision_payload = {
        "schema_version": "1.0",
        "experiment_id": spec["experiment_id"],
        "decision": "implementation_contract_passed",
        "research_only": True,
        "trade_ready": False,
        "performance_evaluated": False,
        "reserved_performance_opened": False,
        "signal_symbol_count": len(spec["universe"]["signal_symbols"]),
        "focus_symbol_count": len(spec["universe"]["symbols"]),
    }

    signal_path = output_dir / "signal_history.json"
    reference_path = output_dir / "reference_history.json"
    current_path = output_dir / "current_signals.json"
    decision_path = output_dir / "decision.json"
    write_json(signal_path, signal_payload)
    write_json(reference_path, reference_payload)
    write_json(current_path, current_payload)
    write_json(decision_path, decision_payload)

    manifest = {
        "schema_version": "1.0",
        "experiment_id": spec["experiment_id"],
        "provider_identity_sha256": provider_identity,
        "spec_identity_sha256": spec_identity,
        "input": {"prices_csv": str(prices_csv)},
        "outputs": {
            "signal_history.json": sha256_file(signal_path),
            "reference_history.json": sha256_file(reference_path),
            "current_signals.json": sha256_file(current_path),
            "decision.json": sha256_file(decision_path),
        },
        "manifest_identity_sha256": canonical_sha256(
            {
                "provider": provider_identity,
                "spec": spec_identity,
                "signal_rows": len(signal_history),
                "reference_rows": len(reference_history),
            }
        ),
    }
    write_json(output_dir / "evidence_manifest.json", manifest)
    return decision_payload
