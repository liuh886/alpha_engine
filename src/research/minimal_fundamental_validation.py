"""Validate the frozen medium-frequency fundamental candidate without model search."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from src.research.fundamental_acceleration import run_fundamental_acceleration


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _load_contract(path: Path) -> tuple[dict[str, Any], dict[str, Any], Path]:
    contract = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise ValueError("fundamental contract must be a YAML mapping")
    validation = contract.get("validation")
    if not isinstance(validation, dict):
        raise ValueError("fundamental contract is missing validation gates")
    root = path.resolve().parents[2]
    pool_path = root / str(contract["pool_spec"])
    pool = yaml.safe_load(pool_path.read_text(encoding="utf-8"))
    if not isinstance(pool, dict) or pool.get("pool_id") != "us_small_pool_v1":
        raise ValueError("validation requires frozen us_small_pool_v1")
    return contract, pool, pool_path


def _pool_membership(pool: Mapping[str, Any]) -> tuple[dict[str, str], list[str]]:
    basket_by_symbol = {
        str(symbol).upper(): str(basket)
        for basket, meta in pool["baskets"].items()
        for symbol in meta["symbols"]
    }
    references = [str(symbol).upper() for symbol in pool.get("references", {})]
    return basket_by_symbol, references


def _verify_factor_artifacts(output: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
    manifest_path = output / "evidence_manifest.json"
    manifest = _load_json(manifest_path)
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("factor evidence manifest has no outputs")
    for filename in ("factor_scores.json", "selection_history.json", "decision.json"):
        path = output / filename
        if outputs.get(filename) != _sha256_file(path):
            raise ValueError(f"factor artifact hash mismatch: {filename}")
    scores = _load_json(output / "factor_scores.json").get("rows")
    selections = _load_json(output / "selection_history.json").get("rows")
    if not isinstance(scores, list) or not isinstance(selections, list):
        raise ValueError("factor artifacts must contain rows")
    return scores, selections, _sha256_file(manifest_path)


def _load_prices(path: Path, required_symbols: set[str]) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"symbol": "string"})
    required = {"date", "symbol", "open", "close"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("prices missing columns: " + ", ".join(missing))
    frame = frame[["date", "symbol", "open", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    for field in ("open", "close"):
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    if frame[["date", "open", "close"]].isna().any().any():
        raise ValueError("prices contain invalid dates or values")
    if (frame[["open", "close"]] <= 0).any().any():
        raise ValueError("prices must be positive")
    if frame.duplicated(["date", "symbol"]).any():
        raise ValueError("prices contain duplicate date-symbol identities")
    missing_symbols = sorted(required_symbols - set(frame["symbol"].unique()))
    if missing_symbols:
        raise ValueError("prices missing frozen symbols: " + ", ".join(missing_symbols))
    return frame.sort_values(["date", "symbol"]).reset_index(drop=True)


def _rank_percentile(series: pd.Series) -> pd.Series:
    if len(series) == 1:
        return pd.Series(1.0, index=series.index, dtype="float64")
    return series.rank(method="average", pct=True)


@dataclass(frozen=True)
class Holding:
    basket: str
    entry_session_index: int


def _no_sma_selections(
    *,
    score_rows: list[dict[str, Any]],
    contract: Mapping[str, Any],
    basket_by_symbol: Mapping[str, str],
    benchmark_dates: pd.DatetimeIndex,
) -> list[dict[str, Any]]:
    key = str(contract["stable_factor_key"])
    frame = pd.DataFrame(
        [row for row in score_rows if row.get("stable_factor_key") == key]
    )
    required = {
        "date",
        "symbol",
        "basket",
        "revenue_growth_acceleration",
        "gross_margin_yoy_change",
    }
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError("factor rows missing fields: " + ", ".join(missing))
    frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    for field in ("revenue_growth_acceleration", "gross_margin_yoy_change"):
        frame[field] = pd.to_numeric(frame[field], errors="coerce")
    policy = contract["portfolio"]
    entry_threshold = 1.0 - float(policy["entry_top_fraction"])
    retention_threshold = float(policy["retention_min_percentile"])
    minimum_holding = int(policy["minimum_holding_sessions"])
    max_replacements = int(policy["maximum_replacements_per_basket_per_evaluation"])
    max_holdings = int(policy["maximum_holdings_per_basket"])
    session_index = {date: index for index, date in enumerate(benchmark_dates)}
    holdings: dict[str, Holding] = {}
    output: list[dict[str, Any]] = []

    for as_of in sorted(frame["date"].unique()):
        as_of = pd.Timestamp(as_of)
        if as_of not in session_index:
            continue
        snapshot = frame[frame["date"] == as_of].copy()
        snapshot["component_complete"] = snapshot[
            ["revenue_growth_acceleration", "gross_margin_yoy_change"]
        ].notna().all(axis=1)
        snapshot["selection_percentile"] = pd.NA
        for _, basket_frame in snapshot.groupby("basket", sort=True):
            eligible = basket_frame.index[basket_frame["component_complete"]]
            if len(eligible) == 0:
                continue
            revenue_rank = _rank_percentile(
                snapshot.loc[eligible, "revenue_growth_acceleration"]
            )
            margin_rank = _rank_percentile(
                snapshot.loc[eligible, "gross_margin_yoy_change"]
            )
            snapshot.loc[eligible, "selection_percentile"] = (
                revenue_rank + margin_rank
            ) / 2.0
        by_symbol = snapshot.set_index("symbol", drop=False)
        current_session = session_index[as_of]
        changes: dict[str, dict[str, list[str]]] = {}
        for basket in sorted(set(basket_by_symbol.values())):
            kept: list[str] = []
            removed: list[str] = []
            for symbol, holding in list(holdings.items()):
                if holding.basket != basket:
                    continue
                row = by_symbol.loc[symbol]
                held = current_session - holding.entry_session_index
                percentile = row["selection_percentile"]
                hard_invalid = not bool(row["component_complete"])
                retention_failed = pd.isna(percentile) or float(percentile) < retention_threshold
                if hard_invalid or (retention_failed and held >= minimum_holding):
                    removed.append(symbol)
                    holdings.pop(symbol)
                else:
                    kept.append(symbol)
            slots = max(0, max_holdings - len(kept))
            additions_allowed = min(max_replacements, slots)
            candidates = snapshot[
                (snapshot["basket"] == basket)
                & snapshot["component_complete"]
                & ~snapshot["symbol"].isin(holdings)
                & (snapshot["selection_percentile"] >= entry_threshold)
            ].sort_values(["selection_percentile", "symbol"], ascending=[False, True])
            added = list(candidates.head(additions_allowed)["symbol"])
            for symbol in added:
                holdings[symbol] = Holding(basket=basket, entry_session_index=current_session)
            changes[basket] = {
                "kept": sorted(kept),
                "added": sorted(added),
                "removed": sorted(removed),
            }
        output.append(
            {
                "date": as_of.date().isoformat(),
                "selected_symbols": sorted(holdings),
                "changes_by_basket": changes,
            }
        )
    return output


def _targets_from_factor_selections(
    rows: list[dict[str, Any]],
    basket_by_symbol: Mapping[str, str],
) -> dict[pd.Timestamp, dict[str, float]]:
    grouped: dict[pd.Timestamp, dict[str, list[str]]] = {}
    for row in rows:
        date = pd.Timestamp(row["date"]).normalize()
        basket = str(row["basket"])
        selected = [str(symbol).upper() for symbol in row.get("selected_symbols", [])]
        grouped.setdefault(date, {})[basket] = selected
    targets: dict[pd.Timestamp, dict[str, float]] = {}
    for date, by_basket in grouped.items():
        active = {basket: symbols for basket, symbols in by_basket.items() if symbols}
        weights: dict[str, float] = {}
        for basket, symbols in active.items():
            basket_weight = 1.0 / len(active)
            for symbol in symbols:
                if basket_by_symbol.get(symbol) != basket:
                    raise ValueError("selection basket identity mismatch")
                weights[symbol] = basket_weight / len(symbols)
        targets[date] = weights
    return targets


def _targets_from_simple_rows(
    rows: list[dict[str, Any]],
    basket_by_symbol: Mapping[str, str],
) -> dict[pd.Timestamp, dict[str, float]]:
    targets: dict[pd.Timestamp, dict[str, float]] = {}
    for row in rows:
        date = pd.Timestamp(row["date"]).normalize()
        selected = [str(symbol).upper() for symbol in row.get("selected_symbols", [])]
        by_basket: dict[str, list[str]] = {}
        for symbol in selected:
            by_basket.setdefault(basket_by_symbol[symbol], []).append(symbol)
        weights: dict[str, float] = {}
        for basket, symbols in by_basket.items():
            basket_weight = 1.0 / len(by_basket)
            for symbol in symbols:
                weights[symbol] = basket_weight / len(symbols)
        targets[date] = weights
    return targets


def _portfolio_series(
    *,
    targets: Mapping[pd.Timestamp, Mapping[str, float]],
    open_wide: pd.DataFrame,
    cost_bps: float,
) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
    dates = open_wide.index
    symbols = list(open_wide.columns)
    effective_targets: dict[pd.Timestamp, Mapping[str, float]] = {}
    for signal_date, weights in targets.items():
        location = dates.searchsorted(signal_date, side="right")
        if location < len(dates):
            effective_targets[dates[location]] = weights
    weight_rows = pd.DataFrame(index=dates, columns=symbols, dtype="float64")
    for date, weights in effective_targets.items():
        weight_rows.loc[date] = 0.0
        for symbol, value in weights.items():
            weight_rows.at[date, symbol] = float(value)
    weights = weight_rows.ffill().fillna(0.0)
    turnover = weights.diff().abs().sum(axis=1)
    if not weights.empty:
        turnover.iloc[0] = weights.iloc[0].abs().sum()
    forward_returns = open_wide.shift(-1).div(open_wide).sub(1.0)
    gross = (weights * forward_returns).sum(axis=1, min_count=1).fillna(0.0)
    net = gross - turnover * (float(cost_bps) / 10000.0)
    return net.iloc[:-1], turnover.iloc[:-1], weights.iloc[:-1]


def _max_drawdown(returns: pd.Series) -> float:
    wealth = (1.0 + returns.fillna(0.0)).cumprod()
    drawdown = wealth.div(wealth.cummax()).sub(1.0)
    return float(drawdown.min()) if not drawdown.empty else 0.0


def _metrics(
    *,
    returns: pd.Series,
    turnover: pd.Series,
    weights: pd.DataFrame,
    start: str,
    end: str,
) -> dict[str, float | int | None]:
    mask = (returns.index >= pd.Timestamp(start)) & (returns.index <= pd.Timestamp(end))
    period_returns = returns.loc[mask]
    period_turnover = turnover.reindex(period_returns.index).fillna(0.0)
    period_weights = weights.reindex(period_returns.index).fillna(0.0)
    if period_returns.empty:
        raise ValueError(f"no returns in validation window {start} to {end}")
    years = max((period_returns.index[-1] - period_returns.index[0]).days / 365.25, 1 / 12)
    total_return = float((1.0 + period_returns).prod() - 1.0)
    return {
        "session_count": int(len(period_returns)),
        "total_return": total_return,
        "max_drawdown": _max_drawdown(period_returns),
        "annual_turnover": float(period_turnover.sum() / years),
        "maximum_symbol_weight": float(period_weights.max().max()),
    }


def _holding_durations(targets: Mapping[pd.Timestamp, Mapping[str, float]], dates: pd.DatetimeIndex) -> list[int]:
    session_index = {date: index for index, date in enumerate(dates)}
    entries: dict[str, int] = {}
    durations: list[int] = []
    previous: set[str] = set()
    for date, weights in sorted(targets.items()):
        location = dates.searchsorted(date, side="right")
        if location >= len(dates):
            continue
        current = {symbol for symbol, weight in weights.items() if weight > 0}
        for symbol in current - previous:
            entries[symbol] = location
        for symbol in previous - current:
            entry = entries.pop(symbol, location)
            durations.append(location - entry)
        previous = current
    final_index = len(dates) - 1
    durations.extend(final_index - entry for entry in entries.values())
    return durations


def _decision(
    *,
    candidate: Mapping[str, Mapping[str, float | int | None]],
    qqq: Mapping[str, Mapping[str, float | int | None]],
    equal_weight: Mapping[str, Mapping[str, float | int | None]],
    average_holding_sessions: float,
    gates: Mapping[str, Any],
) -> tuple[str, list[str]]:
    failed: list[str] = []
    for window in ("development", "falsification"):
        current = candidate[window]
        if float(current["total_return"]) <= float(qqq[window]["total_return"]):
            failed.append(f"{window}_qqq_relative_return")
        if float(current["total_return"]) <= float(equal_weight[window]["total_return"]):
            failed.append(f"{window}_equal_weight_relative_return")
        if float(current["max_drawdown"]) < float(gates["maximum_drawdown_floor"]):
            failed.append(f"{window}_maximum_drawdown")
    if max(float(candidate[window]["annual_turnover"]) for window in candidate) > float(
        gates["annual_turnover_ceiling"]
    ):
        failed.append("annual_turnover")
    if average_holding_sessions < float(gates["average_holding_sessions_floor"]):
        failed.append("average_holding_sessions")
    if max(float(candidate[window]["maximum_symbol_weight"]) for window in candidate) > float(
        gates["maximum_symbol_weight_ceiling"]
    ):
        failed.append("maximum_symbol_weight")
    return (
        "simple_fundamental_factor_independent_validation_required"
        if not failed
        else "simple_fundamental_factor_not_supported",
        failed,
    )


def run_minimal_fundamental_validation(
    *,
    contract_path: str | Path,
    fundamentals_csv: str | Path,
    prices_csv: str | Path,
    output_dir: str | Path,
    registry_db: str | Path | None = None,
) -> dict[str, Any]:
    contract_path = Path(contract_path).resolve()
    prices_path = Path(prices_csv).resolve()
    fundamentals_path = Path(fundamentals_csv).resolve()
    output = Path(output_dir).resolve()
    contract, pool, pool_path = _load_contract(contract_path)
    basket_by_symbol, references = _pool_membership(pool)
    benchmark = str(contract["benchmark"]).upper()
    required_symbols = set(basket_by_symbol) | set(references)
    prices = _load_prices(prices_path, required_symbols)
    open_wide = prices.pivot(index="date", columns="symbol", values="open").sort_index()
    benchmark_dates = open_wide.index[open_wide[benchmark].notna()]
    factor_output = output / "factor_run"
    run_fundamental_acceleration(
        contract_path=contract_path,
        fundamentals_csv=fundamentals_path,
        prices_csv=prices_path,
        output_dir=factor_output,
        registry_db=registry_db,
    )
    score_rows, selection_rows, factor_manifest_hash = _verify_factor_artifacts(factor_output)
    candidate_targets = _targets_from_factor_selections(selection_rows, basket_by_symbol)
    no_sma_rows = _no_sma_selections(
        score_rows=score_rows,
        contract=contract,
        basket_by_symbol=basket_by_symbol,
        benchmark_dates=benchmark_dates,
    )
    no_sma_targets = _targets_from_simple_rows(no_sma_rows, basket_by_symbol)
    cost_bps = float(contract["portfolio"]["transaction_cost_bps_per_one_way_turnover"])
    candidate_returns, candidate_turnover, candidate_weights = _portfolio_series(
        targets=candidate_targets,
        open_wide=open_wide[list(basket_by_symbol)],
        cost_bps=cost_bps,
    )
    no_sma_returns, no_sma_turnover, no_sma_weights = _portfolio_series(
        targets=no_sma_targets,
        open_wide=open_wide[list(basket_by_symbol)],
        cost_bps=cost_bps,
    )
    benchmark_returns = open_wide[benchmark].shift(-1).div(open_wide[benchmark]).sub(1.0).iloc[:-1]
    equal_weight_returns = (
        open_wide[list(basket_by_symbol)].shift(-1).div(open_wide[list(basket_by_symbol)]).sub(1.0)
    ).mean(axis=1).iloc[:-1]
    zero_turnover = pd.Series(0.0, index=benchmark_returns.index)
    benchmark_weights = pd.DataFrame({benchmark: 1.0}, index=benchmark_returns.index)
    equal_weights = pd.DataFrame(
        1.0 / len(basket_by_symbol),
        index=equal_weight_returns.index,
        columns=list(basket_by_symbol),
    )
    windows = contract["windows"]
    metrics: dict[str, dict[str, dict[str, float | int | None]]] = {}
    series = {
        "candidate_with_sma100": (candidate_returns, candidate_turnover, candidate_weights),
        "candidate_without_sma100": (no_sma_returns, no_sma_turnover, no_sma_weights),
        "equal_weight_pool": (equal_weight_returns, zero_turnover, equal_weights),
        "qqq": (benchmark_returns, zero_turnover, benchmark_weights),
    }
    for name, (returns, turnover, weights) in series.items():
        metrics[name] = {
            "development": _metrics(
                returns=returns,
                turnover=turnover,
                weights=weights,
                start=str(windows["development_start"]),
                end=str(windows["development_end"]),
            ),
            "falsification": _metrics(
                returns=returns,
                turnover=turnover,
                weights=weights,
                start=str(windows["falsification_start"]),
                end=str(windows["falsification_end"]),
            ),
        }
    durations = _holding_durations(candidate_targets, benchmark_dates)
    average_holding = float(sum(durations) / len(durations)) if durations else 0.0
    decision, failed = _decision(
        candidate=metrics["candidate_with_sma100"],
        qqq=metrics["qqq"],
        equal_weight=metrics["equal_weight_pool"],
        average_holding_sessions=average_holding,
        gates=contract["validation"],
    )
    result = {
        "schema_version": "1.0",
        "decision": decision,
        "factor_contract_id": contract["factor_contract_id"],
        "research_only": True,
        "trade_ready": False,
        "performance_evaluated": True,
        "independent_validation_completed": False,
        "candidate": "candidate_with_sma100",
        "failed_gates": failed,
        "average_holding_sessions": average_holding,
        "metrics": metrics,
    }
    _write_json(output / "decision.json", result)
    report_lines = [
        "# Minimal Fundamental Validation",
        "",
        f"Decision: `{decision}`",
        "",
        "This is a fixed daily-bar, medium-frequency evaluation. No parameter search or model fitting was performed.",
        "",
        f"Average holding sessions: `{average_holding:.2f}`",
        f"Failed gates: `{', '.join(failed) if failed else 'none'}`",
    ]
    (output / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "inputs": {
            "contract_sha256": _sha256_file(contract_path),
            "pool_sha256": _sha256_file(pool_path),
            "fundamentals_sha256": _sha256_file(fundamentals_path),
            "prices_sha256": _sha256_file(prices_path),
            "factor_run_manifest_sha256": factor_manifest_hash,
        },
        "outputs": {
            "decision.json": _sha256_file(output / "decision.json"),
            "report.md": _sha256_file(output / "report.md"),
        },
    }
    manifest["manifest_identity_sha256"] = _canonical_hash(manifest)
    _write_json(output / "evidence_manifest.json", manifest)
    return result
