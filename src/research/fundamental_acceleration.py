"""Point-in-time fundamental acceleration scores and low-turnover selections."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd
import yaml

from src.research.factor_knowledge_registry import FactorCardInput, FactorKnowledgeRegistry

REQUIRED_FUNDAMENTAL_COLUMNS = {
    "symbol",
    "fiscal_period_end",
    "filed_date",
    "revenue",
    "gross_profit",
    "currency",
    "form_type",
    "accession_id",
}
REQUIRED_PRICE_COLUMNS = {"date", "symbol", "close"}
COMPONENT_KEYS = ("revenue_growth_acceleration", "gross_margin_yoy_change")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _repository_root(path: Path) -> Path:
    for parent in [path.parent, *path.parents]:
        if (parent / "pyproject.toml").exists():
            return parent
    raise ValueError(f"unable to resolve repository root from {path}")


def load_contract(path: str | Path) -> tuple[dict[str, Any], dict[str, Any], Path, Path]:
    resolved = Path(path).resolve()
    contract = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(contract, dict):
        raise ValueError("factor contract must be a YAML mapping")
    if contract.get("status") != "frozen_pre_evaluation":
        raise ValueError("factor contract is not frozen for pre-evaluation use")
    truth = contract.get("truth_boundary", {})
    if truth.get("research_only") is not True or truth.get("trade_ready") is not False:
        raise ValueError("factor contract truth boundary is invalid")
    root = _repository_root(resolved)
    pool_path = root / str(contract["pool_spec"])
    pool = yaml.safe_load(pool_path.read_text(encoding="utf-8"))
    if not isinstance(pool, dict) or pool.get("pool_id") != "us_small_pool_v1":
        raise ValueError("factor contract requires frozen us_small_pool_v1")
    return contract, pool, resolved, pool_path


def _pool_membership(pool: Mapping[str, Any]) -> tuple[dict[str, str], list[str]]:
    basket_by_symbol: dict[str, str] = {}
    for basket, meta in pool.get("baskets", {}).items():
        for symbol in meta.get("symbols", []):
            canonical = str(symbol).upper()
            if canonical in basket_by_symbol:
                raise ValueError(f"duplicate pool symbol: {canonical}")
            basket_by_symbol[canonical] = str(basket)
    references = [str(symbol).upper() for symbol in pool.get("references", {})]
    return basket_by_symbol, references


def load_fundamentals(
    path: str | Path,
    contract: Mapping[str, Any],
    symbols: set[str],
) -> pd.DataFrame:
    frame = pd.read_csv(
        Path(path).resolve(),
        dtype={"symbol": "string", "accession_id": "string"},
    )
    missing = sorted(REQUIRED_FUNDAMENTAL_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError("fundamentals missing columns: " + ", ".join(missing))
    frame = frame[list(REQUIRED_FUNDAMENTAL_COLUMNS)].copy()
    frame["symbol"] = frame["symbol"].str.upper().str.strip()
    frame["fiscal_period_end"] = pd.to_datetime(frame["fiscal_period_end"], errors="coerce")
    frame["filed_date"] = pd.to_datetime(frame["filed_date"], errors="coerce")
    frame["revenue"] = pd.to_numeric(frame["revenue"], errors="coerce")
    frame["gross_profit"] = pd.to_numeric(frame["gross_profit"], errors="coerce")
    frame["currency"] = frame["currency"].astype(str).str.upper().str.strip()
    frame["form_type"] = frame["form_type"].astype(str).str.upper().str.strip()
    frame["accession_id"] = frame["accession_id"].astype(str).str.strip()
    numeric_fields = ["fiscal_period_end", "filed_date", "revenue", "gross_profit"]
    if frame[numeric_fields].isna().any().any():
        raise ValueError("fundamentals contain invalid dates or numeric values")
    if (frame["filed_date"] < frame["fiscal_period_end"]).any():
        raise ValueError("filed_date cannot precede fiscal_period_end")
    accepted = {
        str(value).upper() for value in contract["point_in_time_input"]["accepted_form_types"]
    }
    frame = frame[frame["form_type"].isin(accepted) & frame["symbol"].isin(symbols)].copy()
    if frame.empty:
        raise ValueError("fundamentals contain no frozen-pool observations")
    if (frame["revenue"] <= 0).any():
        raise ValueError("revenue must be positive")
    frame = frame.sort_values(
        ["symbol", "fiscal_period_end", "filed_date", "accession_id"]
    ).drop_duplicates(["symbol", "fiscal_period_end", "filed_date"], keep="last")
    duplicates = frame.duplicated(["symbol", "fiscal_period_end"], keep=False)
    if duplicates.any() and frame.loc[duplicates, "filed_date"].duplicated().any():
        raise ValueError("ambiguous duplicate fundamental filing identity")
    return frame.reset_index(drop=True)


def compute_pit_features(fundamentals: pd.DataFrame) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for symbol, group in fundamentals.groupby("symbol", sort=True):
        period_latest = (
            group.sort_values(["fiscal_period_end", "filed_date", "accession_id"])
            .drop_duplicates("fiscal_period_end", keep="last")
            .sort_values("fiscal_period_end")
            .reset_index(drop=True)
        )
        period_latest["gross_margin"] = period_latest["gross_profit"] / period_latest["revenue"]
        period_latest["revenue_yoy"] = (
            period_latest["revenue"] / period_latest["revenue"].shift(4) - 1.0
        )
        period_latest["revenue_growth_acceleration"] = period_latest["revenue_yoy"] - period_latest[
            "revenue_yoy"
        ].shift(1)
        period_latest["gross_margin_yoy_change"] = period_latest["gross_margin"] - period_latest[
            "gross_margin"
        ].shift(4)
        currencies = period_latest["currency"]
        comparable = (
            currencies.eq(currencies.shift(1))
            & currencies.eq(currencies.shift(4))
            & currencies.eq(currencies.shift(5))
        )
        period_latest["currency_comparable"] = comparable
        period_latest.loc[~comparable, list(COMPONENT_KEYS)] = pd.NA
        period_latest["symbol"] = symbol
        rows.append(period_latest)
    if not rows:
        return pd.DataFrame()
    return (
        pd.concat(rows, ignore_index=True)
        .sort_values(["symbol", "filed_date", "fiscal_period_end"])
        .reset_index(drop=True)
    )


def load_prices(path: str | Path, required_symbols: set[str]) -> pd.DataFrame:
    frame = pd.read_csv(Path(path).resolve(), dtype={"symbol": "string"})
    missing = sorted(REQUIRED_PRICE_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError("prices missing columns: " + ", ".join(missing))
    frame = frame[["date", "symbol", "close"]].copy()
    frame["symbol"] = frame["symbol"].str.upper().str.strip()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    if frame[["date", "close"]].isna().any().any() or (frame["close"] <= 0).any():
        raise ValueError("prices contain invalid dates or closes")
    frame = frame[frame["symbol"].isin(required_symbols)].copy()
    if frame.duplicated(["date", "symbol"]).any():
        raise ValueError("prices contain duplicate date-symbol rows")
    missing_symbols = sorted(required_symbols - set(frame["symbol"].unique()))
    if missing_symbols:
        raise ValueError("prices missing frozen symbols: " + ", ".join(missing_symbols))
    return frame.sort_values(["symbol", "date"]).reset_index(drop=True)


def _rank_percentile(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.Series(index=series.index, dtype="float64")
    if len(series) == 1:
        return pd.Series(1.0, index=series.index, dtype="float64")
    return series.rank(method="average", pct=True)


@dataclass(frozen=True)
class Holding:
    symbol: str
    basket: str
    entry_session_index: int


def _evaluation_dates(benchmark_dates: pd.DatetimeIndex, interval: int) -> list[pd.Timestamp]:
    dates = list(benchmark_dates[::interval])
    if dates[-1] != benchmark_dates[-1]:
        dates.append(benchmark_dates[-1])
    return dates


def build_factor_history(
    *,
    contract: Mapping[str, Any],
    pool: Mapping[str, Any],
    features: pd.DataFrame,
    prices: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    basket_by_symbol, references = _pool_membership(pool)
    benchmark = str(contract["benchmark"]).upper()
    if benchmark not in references:
        raise ValueError("benchmark must be declared as a pool reference")
    price_wide = prices.pivot(index="date", columns="symbol", values="close").sort_index()
    benchmark_dates = price_wide.index[price_wide[benchmark].notna()]
    if benchmark_dates.empty:
        raise ValueError("benchmark has no valid price dates")
    portfolio = contract["portfolio"]
    sma_sessions = int(portfolio["eligibility"]["price_above_sma_sessions"])
    sma = price_wide.rolling(sma_sessions, min_periods=sma_sessions).mean()
    evaluation_dates = _evaluation_dates(
        benchmark_dates, int(portfolio["evaluation_interval_sessions"])
    )
    entry_threshold = 1.0 - float(portfolio["entry_top_fraction"])
    retention_threshold = float(portfolio["retention_min_percentile"])
    minimum_holding = int(portfolio["minimum_holding_sessions"])
    max_holdings = int(portfolio["maximum_holdings_per_basket"])
    max_replacements = int(portfolio["maximum_replacements_per_basket_per_evaluation"])
    composite_key = str(contract["stable_factor_key"])
    holdings: dict[str, Holding] = {}
    scores: list[dict[str, Any]] = []
    selections: list[dict[str, Any]] = []
    features_by_symbol = {
        symbol: group.sort_values(["filed_date", "fiscal_period_end"])
        for symbol, group in features.groupby("symbol", sort=True)
    }
    session_index = {date: index for index, date in enumerate(benchmark_dates)}

    for evaluation_date in evaluation_dates:
        snapshots: list[dict[str, Any]] = []
        for symbol, basket in sorted(basket_by_symbol.items()):
            symbol_features = features_by_symbol.get(symbol)
            available = (
                pd.DataFrame()
                if symbol_features is None
                else symbol_features[symbol_features["filed_date"] <= evaluation_date]
            )
            latest = None if available.empty else available.iloc[-1]
            close = price_wide.at[evaluation_date, symbol]
            sma_value = sma.at[evaluation_date, symbol]
            components = {
                key: None if latest is None or pd.isna(latest[key]) else float(latest[key])
                for key in COMPONENT_KEYS
            }
            reasons: list[str] = []
            if latest is None:
                reasons.append("NO_PUBLISHED_FUNDAMENTAL_SNAPSHOT")
            elif any(value is None for value in components.values()):
                reasons.append("FUNDAMENTAL_COMPONENT_INCOMPLETE")
            if pd.isna(close) or pd.isna(sma_value):
                reasons.append("PRICE_OR_SMA100_INCOMPLETE")
            elif float(close) <= float(sma_value):
                reasons.append("PRICE_BELOW_SMA100")
            snapshots.append(
                {
                    "date": evaluation_date.date().isoformat(),
                    "symbol": symbol,
                    "basket": basket,
                    "filed_date": (
                        None if latest is None else latest["filed_date"].date().isoformat()
                    ),
                    "fiscal_period_end": (
                        None if latest is None else latest["fiscal_period_end"].date().isoformat()
                    ),
                    **components,
                    "price": None if pd.isna(close) else float(close),
                    "sma100": None if pd.isna(sma_value) else float(sma_value),
                    "eligible": not reasons,
                    "reason_codes": reasons,
                }
            )

        snapshot = pd.DataFrame(snapshots)
        for basket, basket_frame in snapshot.groupby("basket", sort=True):
            eligible_index = basket_frame.index[basket_frame["eligible"]]
            for component in COMPONENT_KEYS:
                snapshot.loc[eligible_index, f"{component}_percentile"] = _rank_percentile(
                    pd.to_numeric(snapshot.loc[eligible_index, component], errors="coerce")
                )
            percentile_columns = [f"{component}_percentile" for component in COMPONENT_KEYS]
            snapshot.loc[eligible_index, "composite_percentile"] = snapshot.loc[
                eligible_index, percentile_columns
            ].mean(axis=1)

            current_session = session_index[evaluation_date]
            rows_by_symbol = snapshot.set_index("symbol", drop=False)
            kept: list[str] = []
            removed: list[str] = []
            for symbol, holding in list(holdings.items()):
                if holding.basket != basket:
                    continue
                row = rows_by_symbol.loc[symbol]
                held_sessions = current_session - holding.entry_session_index
                percentile = row.get("composite_percentile")
                retention_failed = pd.isna(percentile) or float(percentile) < retention_threshold
                if not bool(row["eligible"]) or (
                    retention_failed and held_sessions >= minimum_holding
                ):
                    removed.append(symbol)
                    holdings.pop(symbol)
                else:
                    kept.append(symbol)

            available_slots = max(0, max_holdings - len(kept))
            additions_allowed = min(max_replacements, available_slots)
            candidates = snapshot[
                (snapshot["basket"] == basket)
                & snapshot["eligible"]
                & ~snapshot["symbol"].isin(kept)
                & ~snapshot["symbol"].isin(holdings)
                & (snapshot["composite_percentile"] >= entry_threshold)
            ].sort_values(["composite_percentile", "symbol"], ascending=[False, True])
            added = list(candidates.head(additions_allowed)["symbol"])
            for symbol in added:
                holdings[symbol] = Holding(symbol, basket, current_session)

            selected = sorted(kept + added)
            active_baskets = {holding.basket for holding in holdings.values()}
            basket_weight = 1.0 / len(active_baskets) if active_baskets else 0.0
            selections.append(
                {
                    "date": evaluation_date.date().isoformat(),
                    "basket": basket,
                    "selected_symbols": selected,
                    "kept_symbols": sorted(kept),
                    "added_symbols": sorted(added),
                    "removed_symbols": sorted(removed),
                    "target_weight_per_symbol": (
                        basket_weight / len(selected) if selected else 0.0
                    ),
                }
            )

        selected_symbols = set(holdings)
        for row in snapshot.to_dict(orient="records"):
            symbol = str(row["symbol"])
            composite = row.get("composite_percentile")
            base_reasons = list(row.get("reason_codes", []))
            if symbol in selected_symbols:
                base_reasons.append("LOW_TURNOVER_PORTFOLIO_SELECTED")
            scores.append(
                {
                    **row,
                    "selected": symbol in selected_symbols,
                    "stable_factor_key": composite_key,
                    "score": None if pd.isna(composite) else float(composite),
                    "percentile": None if pd.isna(composite) else float(composite),
                    "reason_codes": base_reasons,
                }
            )
            for component in COMPONENT_KEYS:
                percentile = row.get(f"{component}_percentile")
                scores.append(
                    {
                        "date": row["date"],
                        "symbol": symbol,
                        "basket": row["basket"],
                        "filed_date": row["filed_date"],
                        "fiscal_period_end": row["fiscal_period_end"],
                        "stable_factor_key": component,
                        "score": row.get(component),
                        "percentile": None if pd.isna(percentile) else float(percentile),
                        "selected": symbol in selected_symbols,
                        "eligible": row["eligible"],
                        "reason_codes": base_reasons,
                    }
                )
    return scores, selections


def _card(
    contract: Mapping[str, Any],
    *,
    key: str,
    name: str,
    definition: str,
    family: str,
    transformation: str,
    thesis: str,
) -> FactorCardInput:
    version = str(contract["factor_version"])
    return FactorCardInput(
        stable_factor_key=key,
        factor_version=version,
        name=name,
        canonical_definition=definition,
        information_family=family,
        update_frequency="quarterly_after_public_filing",
        availability_lag_days=0,
        transformation=transformation,
        orientation="higher_is_better",
        neutralization="within_primary_basket",
        thesis=thesis,
        code_identity="src/research/fundamental_acceleration.py",
        status="data_blocked",
        spec_path="configs/factors/us_fundamental_acceleration_v1.yaml",
        source_kind="native_v2",
        source_ref=f"us_fundamental_acceleration_v1:{key}:{version}",
    )


def register_factor_cards(registry_db: str | Path, contract: Mapping[str, Any]) -> list[str]:
    registry = FactorKnowledgeRegistry(registry_db)
    cards = [
        _card(
            contract,
            key="revenue_growth_acceleration",
            name="Revenue growth acceleration",
            definition=str(contract["components"]["revenue_growth_acceleration"]["definition"]),
            family="growth",
            transformation="within_basket_percentile_rank",
            thesis="Improving revenue growth may identify strengthening operating momentum.",
        ),
        _card(
            contract,
            key="gross_margin_yoy_change",
            name="Gross-margin year-over-year improvement",
            definition=str(contract["components"]["gross_margin_yoy_change"]["definition"]),
            family="quality",
            transformation="within_basket_percentile_rank",
            thesis=(
                "Improving gross margin may distinguish higher-quality growth "
                "from revenue expansion without economics."
            ),
        ),
        _card(
            contract,
            key=str(contract["stable_factor_key"]),
            name="Equal-weight fundamental acceleration",
            definition=(
                "0.5 * rank(revenue growth acceleration) + 0.5 * rank(gross-margin YoY change)"
            ),
            family="composite",
            transformation="equal_weight_within_basket_percentile_mean",
            thesis=(
                "Growth acceleration confirmed by margin improvement may provide "
                "a slower and more durable security-selection signal."
            ),
        ),
    ]
    return [registry.register_card(card) for card in cards]


def run_fundamental_acceleration(
    *,
    contract_path: str | Path,
    fundamentals_csv: str | Path,
    prices_csv: str | Path,
    output_dir: str | Path,
    registry_db: str | Path | None = None,
) -> dict[str, Any]:
    contract, pool, resolved_contract, pool_path = load_contract(contract_path)
    basket_by_symbol, references = _pool_membership(pool)
    required_symbols = set(basket_by_symbol) | set(references)
    fundamentals_path = Path(fundamentals_csv).resolve()
    prices_path = Path(prices_csv).resolve()
    fundamentals = load_fundamentals(fundamentals_path, contract, set(basket_by_symbol))
    features = compute_pit_features(fundamentals)
    prices = load_prices(prices_path, required_symbols)
    score_history, selection_history = build_factor_history(
        contract=contract,
        pool=pool,
        features=features,
        prices=prices,
    )
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    payloads: dict[str, dict[str, Any]] = {
        "factor_scores.json": {
            "schema_version": "1.0",
            "factor_contract_id": contract["factor_contract_id"],
            "market": "us",
            "research_only": True,
            "trade_ready": False,
            "rows": score_history,
        },
        "selection_history.json": {
            "schema_version": "1.0",
            "factor_contract_id": contract["factor_contract_id"],
            "rows": selection_history,
        },
    }
    for filename, payload in payloads.items():
        _write_json(output / filename, payload)
    card_ids = [] if registry_db is None else register_factor_cards(registry_db, contract)
    decision = {
        "schema_version": "1.0",
        "decision": "fundamental_acceleration_scores_ready",
        "factor_contract_id": contract["factor_contract_id"],
        "research_only": True,
        "trade_ready": False,
        "performance_evaluated": False,
        "independent_validation_completed": False,
        "score_row_count": len(score_history),
        "selection_row_count": len(selection_history),
        "registered_card_ids": card_ids,
    }
    _write_json(output / "decision.json", decision)
    output_hashes = {
        filename: _sha256_file(output / filename) for filename in [*payloads, "decision.json"]
    }
    manifest: dict[str, Any] = {
        "schema_version": "1.0",
        "factor_contract_id": contract["factor_contract_id"],
        "inputs": {
            "contract_sha256": _sha256_file(resolved_contract),
            "pool_sha256": _sha256_file(pool_path),
            "fundamentals_sha256": _sha256_file(fundamentals_path),
            "prices_sha256": _sha256_file(prices_path),
        },
        "outputs": output_hashes,
        "score_row_count": len(score_history),
        "selection_row_count": len(selection_history),
    }
    manifest["manifest_identity_sha256"] = _canonical_hash(manifest)
    _write_json(output / "evidence_manifest.json", manifest)
    return decision
