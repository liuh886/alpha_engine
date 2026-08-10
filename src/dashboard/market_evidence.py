"""Build browser-ready market evidence from governed market providers.

The market substrate is shared across formal models. It owns adjusted OHLCV,
chart studies and canonical factor diagnostics; Formal Model Run Bundles remain
the source of model trade events. The output is static, hash-bound JSON for the
Strategy Console and never authorizes trading.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.factors.library import FactorLibrary, load_factor_library
from src.factors.panel import QlibFactorEvaluator


class MarketEvidenceError(ValueError):
    """Raised when market evidence cannot be published truthfully."""


DEFAULT_LIBRARY = Path("configs/factor_libraries/ohlcv.yaml")
MARKET_EVIDENCE_IDENTITY_VERSION = "1.0.0"
SERIES_FACTOR_GROUP = {
    "us": "momentum_volatility_volume",
    "cn": "cn_balanced_ohlcv",
}
FORMAL_PROVIDER_ALIASES: dict[str, dict[str, str]] = {
    "cn": {
        "BYD": "002594",
        "515180.SH": "515180",
        "CSI300": "000300",
        "000300.SH": "000300",
    },
    "us": {},
}


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _write_json(path: Path, payload: Mapping[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _canonical_json(payload)
    path.write_bytes(encoded)
    return _sha256_bytes(encoded)


def _finite(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _safe_symbol_path(symbol: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", symbol.strip())
    if not value:
        raise MarketEvidenceError("symbol cannot map to an empty path")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MarketEvidenceError(f"JSON object required: {path}")
    return payload


def _market_evidence_input_identity(
    *,
    market: str,
    manifest_path: Path,
    packages: Sequence[Mapping[str, Any]],
    factor_library: FactorLibrary,
) -> str:
    repository_root = Path(__file__).resolve().parents[2]
    implementation_paths = (
        Path(__file__).resolve(),
        repository_root / "src/factors/library.py",
        repository_root / "src/factors/panel.py",
    )
    payload = {
        "identity_version": MARKET_EVIDENCE_IDENTITY_VERSION,
        "market": market,
        "provider_manifest_sha256": _sha256_file(manifest_path),
        "formal_packages": [
            {
                "model_id": str(package.get("model_id", "")),
                "sha256": _sha256_bytes(_canonical_json(package)),
            }
            for package in sorted(
                packages,
                key=lambda value: str(value.get("model_id", "")),
            )
        ],
        "factor_library_sha256": factor_library.source_sha256,
        "implementation_files": {
            path.relative_to(repository_root).as_posix(): _sha256_file(path)
            for path in implementation_paths
        },
        "research_only": True,
        "trade_ready": False,
    }
    return _sha256_bytes(_canonical_json(payload))


def _bounded_evidence_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise MarketEvidenceError(f"market evidence path escaped its root: {relative}")
    return candidate


def _reuse_market_evidence_tree(
    *,
    source_root: Path,
    destination_root: Path,
    expected_input_identity: str,
) -> dict[str, Any] | None:
    """Copy only a fully verified content-addressed market evidence tree."""

    catalog_path = source_root / "catalog.json"
    if not catalog_path.is_file():
        return None
    catalog = _load_json(catalog_path)
    if catalog.get("input_identity_sha256") != expected_input_identity:
        return None
    if catalog.get("research_only") is not True or catalog.get("trade_ready") is not False:
        raise MarketEvidenceError("reusable market evidence crossed research boundary")

    declared: list[tuple[str, str]] = [
        (
            str(catalog.get("factor_diagnostics_path", "")),
            str(catalog.get("factor_diagnostics_sha256", "")),
        )
    ]
    for row in catalog.get("symbols", []):
        if not isinstance(row, dict):
            raise MarketEvidenceError("reusable market evidence catalog is malformed")
        declared.append((str(row.get("path", "")), str(row.get("sha256", ""))))
    if len(declared) != int(catalog.get("symbol_count", 0)) + 1:
        raise MarketEvidenceError("reusable market evidence symbol count mismatch")

    verified: list[tuple[Path, Path]] = []
    for relative, expected_sha in declared:
        if not relative or len(expected_sha) != 64:
            raise MarketEvidenceError("reusable market evidence identity is incomplete")
        source = _bounded_evidence_path(source_root, relative)
        if not source.is_file() or _sha256_file(source) != expected_sha:
            raise MarketEvidenceError(f"reusable market evidence hash mismatch: {relative}")
        verified.append((source, destination_root / relative))

    if destination_root.exists() and any(destination_root.iterdir()):
        raise MarketEvidenceError(f"market evidence destination is not empty: {destination_root}")
    destination_root.mkdir(parents=True, exist_ok=True)
    for source, destination in verified:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    shutil.copy2(catalog_path, destination_root / "catalog.json")
    return catalog


def _instrument_id(market: str, provider_symbol: str) -> str:
    return f"{market.lower()}:{provider_symbol.upper()}"


def _provider_symbol_for_formal_instrument(market: str, formal_instrument: object) -> str | None:
    source = str(formal_instrument or "").strip().upper()
    if not source or source == "CASH":
        return None
    alias = FORMAL_PROVIDER_ALIASES.get(market.lower(), {}).get(source)
    if alias:
        return alias
    if market.lower() == "cn" and re.fullmatch(r"\d{6}\.(SH|SZ)", source):
        return source[:6]
    return source


def _chart_studies(frame: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    close = pd.to_numeric(frame["close"], errors="coerce")
    middle = close.rolling(20, min_periods=20).mean()
    sigma = close.rolling(20, min_periods=20).std(ddof=0)
    upper = middle + 2.0 * sigma
    lower = middle - 2.0 * sigma

    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False, min_periods=9).mean()
    histogram = macd - signal

    delta = close.diff()
    gains = delta.clip(lower=0.0)
    losses = -delta.clip(upper=0.0)
    average_gain = gains.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    average_loss = losses.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    ready = average_gain.notna() & average_loss.notna()
    relative_strength = average_gain / average_loss.where(average_loss != 0.0)
    rsi = 100.0 - 100.0 / (1.0 + relative_strength)
    rsi = rsi.where(~(ready & (average_loss == 0.0) & (average_gain > 0.0)), 100.0)
    rsi = rsi.where(~(ready & (average_gain == 0.0) & (average_loss > 0.0)), 0.0)
    rsi = rsi.where(~(ready & (average_gain == 0.0) & (average_loss == 0.0)), 50.0)

    dates = pd.to_datetime(frame["date"], errors="coerce")

    def rows(columns: Mapping[str, pd.Series]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for index, date in enumerate(dates):
            if pd.isna(date):
                continue
            row: dict[str, Any] = {"time": pd.Timestamp(date).date().isoformat()}
            valid = True
            for key, series in columns.items():
                value = _finite(series.iloc[index])
                if value is None:
                    valid = False
                    break
                row[key] = value
            if valid:
                output.append(row)
        return output

    return {
        "boll20": rows({"middle": middle, "upper": upper, "lower": lower}),
        "macd_12_26_9": rows({"macd": macd, "signal": signal, "histogram": histogram}),
        "rsi14": rows({"value": rsi}),
    }


def _bars(frame: pd.DataFrame) -> list[dict[str, Any]]:
    required = ("date", "open", "high", "low", "close", "volume")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise MarketEvidenceError(f"OHLCV source is missing columns: {missing}")
    output: list[dict[str, Any]] = []
    for row in frame.loc[:, list(required)].itertuples(index=False):
        date = pd.to_datetime(row.date, errors="coerce")
        values = [_finite(value) for value in (row.open, row.high, row.low, row.close, row.volume)]
        if pd.isna(date) or any(value is None for value in values):
            continue
        open_value, high, low, close, volume = values
        if open_value is None or high is None or low is None or close is None or volume is None:
            continue
        if min(open_value, high, low, close) <= 0 or high < low:
            continue
        output.append(
            {
                "time": pd.Timestamp(date).date().isoformat(),
                "open": open_value,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )
    if not output:
        raise MarketEvidenceError("OHLCV source contains no valid bars")
    return output


def _formal_packages(formal_root: Path, market: str) -> list[dict[str, Any]]:
    packages: list[dict[str, Any]] = []
    for path in sorted(formal_root.glob("*.json")):
        payload = _load_json(path)
        if payload.get("record_type") != "formal_model_backtest":
            continue
        if str(payload.get("market", "")).lower() != market:
            continue
        if payload.get("research_only") is not True or payload.get("trade_ready") is not False:
            raise MarketEvidenceError(f"formal package crossed research boundary: {path}")
        packages.append(payload)
    if not packages:
        raise MarketEvidenceError(f"no formal model packages found for {market}")
    return packages


def _trade_events(
    packages: Sequence[Mapping[str, Any]], market: str
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, str]]:
    events: dict[str, list[dict[str, Any]]] = {}
    labels: dict[str, str] = {}
    for package in packages:
        model_id = str(package.get("model_id", ""))
        model_name = str(package.get("display_name", model_id))
        run_id = str(package.get("backtest_id", ""))
        positions = package.get("positions", [])
        if isinstance(positions, list):
            for row in positions:
                if not isinstance(row, dict):
                    continue
                source_instrument = str(row.get("instrument", "")).strip().upper()
                provider_symbol = _provider_symbol_for_formal_instrument(market, source_instrument)
                label = str(row.get("name") or row.get("entity") or "").strip()
                if provider_symbol:
                    labels.setdefault(
                        provider_symbol, label or source_instrument or provider_symbol
                    )
        trades = package.get("trades", [])
        if not isinstance(trades, list):
            continue
        for row in trades:
            if not isinstance(row, dict):
                continue
            source_instrument = str(row.get("instrument", "")).strip().upper()
            provider_symbol = _provider_symbol_for_formal_instrument(market, source_instrument)
            date = str(row.get("date", ""))
            action = str(row.get("action", "")).upper()
            if (
                not provider_symbol
                or not date
                or action not in {"BUY", "SELL", "INCREASE", "DECREASE"}
            ):
                continue
            labels.setdefault(provider_symbol, source_instrument or provider_symbol)
            event = {
                "time": date,
                "instrument_id": _instrument_id(market, provider_symbol),
                "source_instrument": source_instrument,
                "model_id": model_id,
                "model_name": model_name,
                "run_id": run_id,
                "action": action,
                "previous_weight": _finite(row.get("previous_weight")),
                "target_weight": _finite(row.get("target_weight")),
                "weight_delta": _finite(row.get("weight_delta")),
                "reason": str(row.get("reason") or row.get("executed_reason") or ""),
                "research_only": True,
                "trade_ready": False,
            }
            events.setdefault(provider_symbol, []).append(event)
    for rows in events.values():
        rows.sort(
            key=lambda row: (
                str(row["time"]),
                str(row["model_id"]),
                str(row["action"]),
            )
        )
    return events, labels


def _rename_factor_frame(
    evaluated: pd.DataFrame,
    factor_ids: Sequence[str],
) -> pd.DataFrame:
    if len(evaluated.columns) != len(factor_ids):
        raise MarketEvidenceError("factor evaluator returned an unexpected column count")
    result = evaluated.copy()
    result.columns = list(factor_ids)
    return result


def _filter_factor_frame(evaluated: pd.DataFrame, symbols: Sequence[str]) -> pd.DataFrame:
    if not isinstance(evaluated.index, pd.MultiIndex):
        return evaluated
    names = list(evaluated.index.names)
    instrument_level = names.index("instrument") if "instrument" in names else 0
    allowed = {str(symbol).upper() for symbol in symbols}
    mask = [
        str(value).upper() in allowed
        for value in evaluated.index.get_level_values(instrument_level)
    ]
    return evaluated.loc[mask]


def _factor_stats(
    evaluated: pd.DataFrame,
    library: FactorLibrary,
    factor_ids: Sequence[str],
    *,
    market: str,
    pool_id: str,
    start: str,
    cutoff: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for factor_id in factor_ids:
        definition = library.factor(factor_id)
        raw = pd.to_numeric(evaluated[factor_id], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
        finite = raw.dropna().astype(float)
        if finite.empty:
            rows.append(
                {
                    "factor_id": factor_id,
                    "display_name": definition.display_name,
                    "information_family": definition.information_family,
                    "implementation_hash": definition.implementation_hash,
                    "sample_count": 0,
                    "missing_count": int(raw.isna().sum()),
                    "status": "unavailable",
                }
            )
            continue
        values = finite.to_numpy(dtype=float)
        q01, q05, q25, q50, q75, q95, q99 = np.quantile(
            values, [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]
        )
        low = float(q01)
        high = float(q99)
        if math.isclose(low, high, rel_tol=0.0, abs_tol=1e-15):
            high = low + 1e-12
        clipped = values[(values >= low) & (values <= high)]
        counts, edges = np.histogram(clipped, bins=24, range=(low, high))
        histogram = [
            {
                "lower": float(edges[index]),
                "upper": float(edges[index + 1]),
                "count": int(counts[index]),
            }
            for index in range(len(counts))
        ]
        rows.append(
            {
                "factor_id": factor_id,
                "display_name": definition.display_name,
                "information_family": definition.information_family,
                "implementation_hash": definition.implementation_hash,
                "market": market,
                "pool_id": pool_id,
                "start": start,
                "cutoff": cutoff,
                "sample_count": int(len(finite)),
                "missing_count": int(raw.isna().sum()),
                "mean": float(finite.mean()),
                "std": float(finite.std(ddof=0)),
                "min": float(finite.min()),
                "q01": float(q01),
                "q05": float(q05),
                "q25": float(q25),
                "median": float(q50),
                "q75": float(q75),
                "q95": float(q95),
                "q99": float(q99),
                "max": float(finite.max()),
                "histogram_display_clip": [low, high],
                "below_histogram_clip": int((values < low).sum()),
                "above_histogram_clip": int((values > high).sum()),
                "histogram": histogram,
                "status": "ready",
            }
        )
    return rows


def _symbol_factor_frame(evaluated: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if not isinstance(evaluated.index, pd.MultiIndex):
        return pd.DataFrame()
    names = list(evaluated.index.names)
    instrument_level = names.index("instrument") if "instrument" in names else 0
    try:
        frame = evaluated.xs(symbol, level=instrument_level).copy()
    except KeyError:
        return pd.DataFrame()
    frame.index = pd.to_datetime(frame.index, errors="coerce")
    frame = frame.loc[~frame.index.isna()].sort_index()
    return frame.loc[~frame.index.duplicated(keep="last")]


def _factor_series(
    frame: pd.DataFrame, factor_ids: Sequence[str]
) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for factor_id in factor_ids:
        if factor_id not in frame.columns:
            continue
        rows: list[dict[str, Any]] = []
        for date, raw in frame[factor_id].items():
            value = _finite(raw)
            if value is None:
                continue
            rows.append({"time": pd.Timestamp(date).date().isoformat(), "value": value})
        if rows:
            output[factor_id] = rows
    return output


def build_market_evidence(
    *,
    market: str,
    provider_root: Path,
    formal_root: Path,
    output_root: Path,
    factor_library_path: Path = DEFAULT_LIBRARY,
    reuse_root: Path | None = None,
) -> dict[str, Any]:
    market = market.lower()
    if market not in SERIES_FACTOR_GROUP:
        raise MarketEvidenceError(f"unsupported market: {market}")

    provider_root = provider_root.resolve()
    formal_root = formal_root.resolve()
    output_root = output_root.resolve() / market
    manifest_path = provider_root / "artifacts" / "selected_pool_price_refresh_manifest.json"
    manifest = _load_json(manifest_path)
    if (
        manifest.get("status") != "selected_pool_price_refresh_ready"
        or manifest.get("promotion_eligible") is not True
    ):
        raise MarketEvidenceError(f"selected-pool provider is not publication eligible: {market}")
    if str(manifest.get("market", "")) != market:
        raise MarketEvidenceError("provider manifest market mismatch")

    records = [row for row in manifest.get("records", []) if isinstance(row, dict)]
    symbols = [str(row.get("symbol", "")).strip().upper() for row in records if row.get("symbol")]
    if not symbols or len(symbols) != len(set(symbols)):
        raise MarketEvidenceError("selected-pool provider symbols must be non-empty and unique")
    candidate_symbols = [
        str(value).strip().upper()
        for value in manifest.get("candidate_symbols", [])
        if str(value).strip()
    ]
    if (
        not candidate_symbols
        or len(candidate_symbols) != int(manifest.get("candidate_count", 0))
        or not set(candidate_symbols).issubset(symbols)
    ):
        raise MarketEvidenceError("selected-pool candidate identity is incomplete")
    benchmark = str(manifest.get("benchmark", "")).strip().upper()
    auxiliary_symbols = [
        str(value).strip().upper()
        for value in manifest.get("auxiliary_symbols", [])
        if str(value).strip()
    ]
    source_hashes = {
        str(row.get("symbol", "")).strip().upper(): str(row.get("output_sha256", ""))
        for row in records
    }

    packages = _formal_packages(formal_root, market)
    events, labels = _trade_events(packages, market)
    uncovered = sorted(set(events) - set(symbols))
    if uncovered:
        raise MarketEvidenceError(
            "formal traded securities are missing from governed provider: " + ", ".join(uncovered)
        )
    traded_symbols = sorted(events)

    library = load_factor_library(factor_library_path)
    input_identity = _market_evidence_input_identity(
        market=market,
        manifest_path=manifest_path,
        packages=packages,
        factor_library=library,
    )
    if reuse_root is not None:
        reusable_catalog = _reuse_market_evidence_tree(
            source_root=reuse_root.resolve() / market,
            destination_root=output_root,
            expected_input_identity=input_identity,
        )
        if reusable_catalog is not None:
            return {
                "market": market,
                "symbol_count": int(reusable_catalog["symbol_count"]),
                "traded_symbol_count": sum(
                    int(row.get("formal_event_count", 0)) > 0
                    for row in reusable_catalog.get("symbols", [])
                    if isinstance(row, dict)
                ),
                "factor_count": len(
                    _load_json(output_root / "factor-diagnostics.json").get("factors", [])
                ),
                "catalog_sha256": _sha256_file(output_root / "catalog.json"),
                "input_identity_sha256": input_identity,
                "reused": True,
            }
    market_factor_ids = [
        definition.factor_id
        for definition in library.catalog.definitions
        if market in definition.markets
    ]
    market_definitions = [library.factor(factor_id) for factor_id in market_factor_ids]
    expressions = [definition.expression for definition in market_definitions]
    provider_uri = provider_root / "data" / "providers" / market
    evaluator = QlibFactorEvaluator(provider_uri=provider_uri, market=market)
    evaluated = _rename_factor_frame(
        evaluator.evaluate(
            symbols=symbols,
            expressions=expressions,
            start=str(manifest.get("start")),
            end=str(manifest.get("cutoff")),
        ),
        market_factor_ids,
    )
    candidate_factor_frame = _filter_factor_frame(evaluated, candidate_symbols)

    factor_group = library[SERIES_FACTOR_GROUP[market]]
    series_factor_ids = list(factor_group.factor_ids)
    stats_payload = {
        "schema_version": "1.1",
        "evidence_type": "factor_distribution_evidence",
        "market": market,
        "pool_id": str(manifest.get("pool_id", "")),
        "start": str(manifest.get("start", "")),
        "cutoff": str(manifest.get("cutoff", "")),
        "provider_manifest_sha256": _sha256_file(manifest_path),
        "factor_library_sha256": library.source_sha256,
        "catalog_implementation_hash": library.catalog.implementation_hash(),
        "distribution_universe": "selected_pool_candidates_only",
        "candidate_count": len(candidate_symbols),
        "factors": _factor_stats(
            candidate_factor_frame,
            library,
            market_factor_ids,
            market=market,
            pool_id=str(manifest.get("pool_id", "")),
            start=str(manifest.get("start", "")),
            cutoff=str(manifest.get("cutoff", "")),
        ),
        "research_only": True,
        "trade_ready": False,
    }
    factor_stats_sha = _write_json(output_root / "factor-diagnostics.json", stats_payload)

    catalog_rows: list[dict[str, Any]] = []
    csv_root = provider_root / "data" / "csv_source"
    for symbol in symbols:
        source_path = csv_root / f"{symbol}.csv"
        if not source_path.is_file():
            raise MarketEvidenceError(f"selected-pool CSV is missing: {source_path}")
        source_sha = _sha256_file(source_path)
        if source_hashes.get(symbol) and source_hashes[symbol] != source_sha:
            raise MarketEvidenceError(f"selected-pool CSV hash mismatch: {symbol}")
        frame = pd.read_csv(source_path)
        bars = _bars(frame)
        symbol_factors = _factor_series(_symbol_factor_frame(evaluated, symbol), series_factor_ids)
        roles: list[str] = []
        if symbol in candidate_symbols:
            roles.append("selected_pool_candidate")
        if symbol == benchmark:
            roles.append("benchmark")
        if symbol in auxiliary_symbols:
            roles.append("formal_auxiliary")
        if symbol in events:
            roles.append("formal_traded")
        source_instruments = sorted(
            {
                str(event["source_instrument"])
                for event in events.get(symbol, [])
                if event.get("source_instrument")
            }
        )
        payload = {
            "schema_version": "1.1",
            "evidence_type": "security_market_evidence",
            "market": market,
            "instrument_id": _instrument_id(market, symbol),
            "provider_symbol": symbol,
            "symbol": symbol,
            "source_instruments": source_instruments,
            "roles": roles,
            "name": labels.get(symbol, symbol),
            "start": bars[0]["time"],
            "cutoff": bars[-1]["time"],
            "source_csv_sha256": source_sha,
            "provider_manifest_sha256": _sha256_file(manifest_path),
            "bars": bars,
            "chart_studies": _chart_studies(frame),
            "formal_model_events": events.get(symbol, []),
            "factor_series": symbol_factors,
            "factor_series_scope": {
                "group": SERIES_FACTOR_GROUP[market],
                "factor_ids": sorted(symbol_factors),
                "materialization_rule": "published_for_every_market_evidence_security",
            },
            "research_only": True,
            "trade_ready": False,
        }
        relative = Path("symbols") / f"{_safe_symbol_path(symbol)}.json"
        payload_sha = _write_json(output_root / relative, payload)
        catalog_rows.append(
            {
                "instrument_id": _instrument_id(market, symbol),
                "provider_symbol": symbol,
                "symbol": symbol,
                "source_instruments": source_instruments,
                "roles": roles,
                "name": labels.get(symbol, symbol),
                "path": relative.as_posix(),
                "sha256": payload_sha,
                "start": bars[0]["time"],
                "cutoff": bars[-1]["time"],
                "formal_event_count": len(events.get(symbol, [])),
                "factor_series_available": bool(symbol_factors),
            }
        )

    catalog = {
        "schema_version": "1.1",
        "evidence_type": "market_evidence_catalog",
        "market": market,
        "pool_id": str(manifest.get("pool_id", "")),
        "candidate_count": len(candidate_symbols),
        "benchmark": benchmark,
        "auxiliary_symbols": auxiliary_symbols,
        "start": str(manifest.get("start", "")),
        "cutoff": str(manifest.get("cutoff", "")),
        "provider_identity_sha256": str(manifest.get("provider_identity_sha256", "")),
        "provider_manifest_sha256": _sha256_file(manifest_path),
        "factor_diagnostics_path": "factor-diagnostics.json",
        "factor_diagnostics_sha256": factor_stats_sha,
        "factor_library_sha256": library.source_sha256,
        "series_factor_group": SERIES_FACTOR_GROUP[market],
        "input_identity_sha256": input_identity,
        "symbol_count": len(catalog_rows),
        "symbols": catalog_rows,
        "research_only": True,
        "trade_ready": False,
    }
    catalog_sha = _write_json(output_root / "catalog.json", catalog)
    return {
        "market": market,
        "symbol_count": len(catalog_rows),
        "traded_symbol_count": len(traded_symbols),
        "factor_count": len(market_factor_ids),
        "catalog_sha256": catalog_sha,
        "input_identity_sha256": input_identity,
        "reused": False,
    }
