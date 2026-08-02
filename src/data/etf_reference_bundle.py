from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd
import yaml

from src.data.adapters.base import DataFetchError, FetchRequest, MarketDataAdapter
from src.data.adapters.tiingo_adapter import TiingoAdapter
from src.data.adapters.yfinance_adapter import YFinanceAdapter
from src.data.provider_catalog import provider_manifest_entry
from src.data.validation.schema import validate_market_data

ETF_REFERENCE_SYMBOLS = ("QQQ", "QQQI", "TQQQ")
MANIFEST_NAME = "bundle_manifest.json"


class ETFReferenceBundleError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _load_contract(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ETFReferenceBundleError("ETF bundle contract must be a mapping")
    instruments = payload.get("instruments")
    if not isinstance(instruments, list) or not instruments:
        raise ETFReferenceBundleError("ETF bundle contract has no instruments")
    symbols = [str(item.get("symbol", "")).strip().upper() for item in instruments]
    if symbols != list(ETF_REFERENCE_SYMBOLS):
        raise ETFReferenceBundleError(
            f"ETF bundle symbols must be exactly {list(ETF_REFERENCE_SYMBOLS)}"
        )
    return payload


def _normalise_frame(frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
    required = {
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "factor",
    }
    missing = sorted(required.difference(frame.columns))
    if missing:
        raise ETFReferenceBundleError(f"{symbol} bars missing columns: {missing}")
    out = frame.copy()
    out["date"] = (
        pd.to_datetime(out["date"], errors="coerce")
        .dt.tz_localize(None)
        .dt.normalize()
    )
    for column in required.difference({"date"}):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = (
        out.dropna(subset=["date", "open", "high", "low", "close"])
        .sort_values("date")
        .drop_duplicates(subset=["date"], keep="last")
        .reset_index(drop=True)
    )
    valid, _, errors = validate_market_data(out, symbol)
    if not valid:
        raise ETFReferenceBundleError(
            f"{symbol} schema validation failed: {'; '.join(errors)}"
        )
    if out.empty:
        raise ETFReferenceBundleError(f"{symbol} has no usable bars")
    return out


def _event_dates(frame: pd.DataFrame) -> set[pd.Timestamp]:
    if "cash_distribution" not in frame.columns or "split_factor" not in frame.columns:
        return set()
    cash = pd.to_numeric(frame["cash_distribution"], errors="coerce").fillna(0.0)
    split = pd.to_numeric(frame["split_factor"], errors="coerce").fillna(1.0)
    dates = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    mask = cash.ne(0.0) | split.ne(1.0)
    return {pd.Timestamp(value) for value in dates.loc[mask].dropna()}


def _event_window_dates(
    common_dates: Sequence[pd.Timestamp],
    events: set[pd.Timestamp],
    window_sessions: int,
) -> set[pd.Timestamp]:
    positions = {pd.Timestamp(date): index for index, date in enumerate(common_dates)}
    allowed: set[pd.Timestamp] = set()
    for event in events:
        if event not in positions:
            continue
        center = positions[event]
        lo = max(0, center - window_sessions)
        hi = min(len(common_dates), center + window_sessions + 1)
        allowed.update(pd.Timestamp(common_dates[index]) for index in range(lo, hi))
    return allowed


def _compounded_return(series: pd.Series) -> float:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return 0.0
    return float((1.0 + values).prod() - 1.0)


def _compounded_drift(primary: pd.Series, fallback: pd.Series) -> float:
    primary_growth = 1.0 + _compounded_return(primary)
    fallback_growth = 1.0 + _compounded_return(fallback)
    if primary_growth <= 0.0 or fallback_growth <= 0.0:
        return float("inf")
    return abs(float(primary_growth / fallback_growth - 1.0))


def _maximum_annual_open_drift(comparison: pd.DataFrame) -> float:
    usable = comparison[
        ["primary_open_return", "fallback_open_return"]
    ].dropna()
    if usable.empty:
        return 0.0
    drifts = [
        _compounded_drift(
            group["primary_open_return"],
            group["fallback_open_return"],
        )
        for _, group in usable.groupby(usable.index.year)
    ]
    return max(drifts, default=0.0)


def reconcile_adjusted_bars(
    primary: pd.DataFrame | None,
    fallback: pd.DataFrame | None,
    *,
    symbol: str,
    settings: Mapping[str, Any],
) -> dict[str, Any]:
    if primary is None or fallback is None:
        return {
            "symbol": symbol,
            "status": "provider_missing",
            "primary_present": primary is not None,
            "fallback_present": fallback is not None,
            "overlap_sessions": 0,
            "reason": "independent reconciliation requires both providers",
        }

    left = _normalise_frame(primary, symbol).set_index("date")
    right = _normalise_frame(fallback, symbol).set_index("date")
    common = left.index.intersection(right.index).sort_values()
    minimum = int(settings.get("minimum_overlap_sessions", 20))
    if len(common) < minimum:
        return {
            "symbol": symbol,
            "status": "quarantine",
            "primary_present": True,
            "fallback_present": True,
            "overlap_sessions": int(len(common)),
            "reason": f"overlap below minimum {minimum}",
        }

    comparison = pd.DataFrame(index=common)
    comparison["primary_close_return"] = left.loc[common, "close"].pct_change()
    comparison["fallback_close_return"] = right.loc[common, "close"].pct_change()
    comparison["primary_open_return"] = left.loc[common, "open"].pct_change()
    comparison["fallback_open_return"] = right.loc[common, "open"].pct_change()
    comparison["close_diff"] = (
        comparison["primary_close_return"]
        - comparison["fallback_close_return"]
    ).abs()
    comparison["open_diff"] = (
        comparison["primary_open_return"]
        - comparison["fallback_open_return"]
    ).abs()
    close_diff = comparison["close_diff"].dropna()
    open_diff = comparison["open_diff"].dropna()
    p99_close = float(close_diff.quantile(0.99)) if not close_diff.empty else 0.0
    max_close = float(close_diff.max()) if not close_diff.empty else 0.0
    p99_open = float(open_diff.quantile(0.99)) if not open_diff.empty else 0.0
    max_open = float(open_diff.max()) if not open_diff.empty else 0.0
    full_period_open_drift = _compounded_drift(
        comparison["primary_open_return"],
        comparison["fallback_open_return"],
    )
    max_annual_open_drift = _maximum_annual_open_drift(comparison)

    close_p99_limit = float(
        settings.get("consensus_p99_adjusted_close_return_diff", 0.001)
    )
    close_max_limit = float(
        settings.get("consensus_max_adjusted_close_return_diff", 0.01)
    )
    open_p99_limit = float(
        settings.get(
            "consensus_p99_adjusted_open_return_diff",
            close_p99_limit,
        )
    )
    open_max_limit = float(
        settings.get(
            "consensus_max_adjusted_open_return_diff",
            close_max_limit,
        )
    )
    annual_open_drift_limit = float(
        settings.get("consensus_max_annual_compounded_open_return_drift", 0.002)
    )
    full_open_drift_limit = float(
        settings.get("consensus_max_full_period_compounded_open_return_drift", 0.002)
    )
    material_limit = float(settings.get("material_return_difference", 0.01))
    event_window = int(settings.get("corporate_action_window_sessions", 1))
    material_dates = {
        pd.Timestamp(value)
        for value in comparison.index[
            comparison[["close_diff", "open_diff"]]
            .max(axis=1)
            .gt(material_limit)
        ]
    }
    allowed_event_dates = _event_window_dates(
        [pd.Timestamp(value) for value in common],
        _event_dates(primary),
        event_window,
    )

    close_consensus = (
        p99_close <= close_p99_limit and max_close <= close_max_limit
    )
    open_execution_consensus = (
        p99_open <= open_p99_limit
        and max_open <= open_max_limit
        and max_annual_open_drift <= annual_open_drift_limit
        and full_period_open_drift <= full_open_drift_limit
    )
    if close_consensus and open_execution_consensus:
        status = "consensus"
        reason = (
            "closing total returns and opening execution returns agree within "
            "their separate frozen distribution and compounded-drift tolerances"
        )
    elif material_dates and material_dates.issubset(allowed_event_dates):
        status = "explainable_corporate_action_difference"
        reason = "material return differences are confined to Tiingo action windows"
    else:
        status = "quarantine"
        reason = (
            "provider disagreement exceeds the close-return, open-return, or "
            "compounded execution-drift contract"
        )

    return {
        "symbol": symbol,
        "status": status,
        "primary_present": True,
        "fallback_present": True,
        "overlap_sessions": int(len(common)),
        "primary_only_sessions": int(len(left.index.difference(right.index))),
        "fallback_only_sessions": int(len(right.index.difference(left.index))),
        "p99_abs_close_return_diff": p99_close,
        "max_abs_close_return_diff": max_close,
        "p99_abs_open_return_diff": p99_open,
        "max_abs_open_return_diff": max_open,
        "max_abs_annual_compounded_open_return_drift": max_annual_open_drift,
        "abs_full_period_compounded_open_return_drift": full_period_open_drift,
        "close_consensus": close_consensus,
        "open_execution_consensus": open_execution_consensus,
        "material_difference_dates": [
            value.date().isoformat() for value in sorted(material_dates)
        ],
        "recorded_action_dates": [
            value.date().isoformat() for value in sorted(_event_dates(primary))
        ],
        "reason": reason,
    }


def _corporate_actions(frame: pd.DataFrame | None, symbol: str) -> pd.DataFrame:
    columns = ["symbol", "date", "cash_distribution", "split_factor"]
    if frame is None or not {
        "cash_distribution",
        "split_factor",
    }.issubset(frame.columns):
        return pd.DataFrame(columns=columns)
    out = frame[["date", "cash_distribution", "split_factor"]].copy()
    out["date"] = pd.to_datetime(out["date"], errors="coerce").dt.normalize()
    out["cash_distribution"] = pd.to_numeric(
        out["cash_distribution"], errors="coerce"
    ).fillna(0.0)
    out["split_factor"] = pd.to_numeric(
        out["split_factor"], errors="coerce"
    ).fillna(1.0)
    out = out.loc[
        out["cash_distribution"].ne(0.0)
        | out["split_factor"].ne(1.0)
    ].copy()
    out.insert(0, "symbol", symbol)
    return out[columns].reset_index(drop=True)


def _fetch_source(
    adapter: MarketDataAdapter | None,
    *,
    symbol: str,
    start: str,
    end: str | None,
) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    if adapter is None:
        return None, {"ok": False, "error": "provider is not configured"}
    try:
        result = adapter.fetch_daily_bars(
            FetchRequest(symbol=symbol, market="us", start=start, end=end)
        )
        frame = _normalise_frame(result.df, symbol)
        return frame, {
            "ok": True,
            "provider": result.provider,
            "provider_symbol": result.provider_symbol or symbol,
            "rows": int(len(frame)),
            "first_date": frame["date"].min().date().isoformat(),
            "last_date": frame["date"].max().date().isoformat(),
            "metadata": dict(result.df.attrs.get("provider_metadata", {})),
        }
    except (DataFetchError, ETFReferenceBundleError, ValueError) as exc:
        return None, {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def build_etf_reference_bundle(
    *,
    contract_path: str | Path,
    output_root: str | Path,
    end: str | None = None,
    primary_adapter: MarketDataAdapter | None = None,
    fallback_adapter: MarketDataAdapter | None = None,
) -> dict[str, Any]:
    contract_file = Path(contract_path).resolve()
    contract = _load_contract(contract_file)
    root = Path(output_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    start = str(contract["history"]["requested_start"])
    settings = dict(contract.get("reconciliation", {}))

    if primary_adapter is None and os.getenv("TIINGO_API_TOKEN", "").strip():
        primary_adapter = TiingoAdapter()
    if fallback_adapter is None:
        fallback_adapter = YFinanceAdapter()

    source_frames: dict[str, dict[str, pd.DataFrame | None]] = {}
    coverage_rows: list[dict[str, Any]] = []
    reconciliation_rows: list[dict[str, Any]] = []
    action_frames: list[pd.DataFrame] = []
    file_hashes: dict[str, str] = {}

    for symbol in ETF_REFERENCE_SYMBOLS:
        primary, primary_attempt = _fetch_source(
            primary_adapter, symbol=symbol, start=start, end=end
        )
        fallback, fallback_attempt = _fetch_source(
            fallback_adapter, symbol=symbol, start=start, end=end
        )
        source_frames[symbol] = {"tiingo": primary, "yfinance": fallback}

        for provider, frame in (("tiingo", primary), ("yfinance", fallback)):
            if frame is None:
                continue
            source_path = root / "sources" / provider / f"{symbol}.csv"
            source_path.parent.mkdir(parents=True, exist_ok=True)
            frame.to_csv(source_path, index=False)
            file_hashes[str(source_path.relative_to(root))] = _sha256(source_path)

        reconciliation = reconcile_adjusted_bars(
            primary,
            fallback,
            symbol=symbol,
            settings=settings,
        )
        reconciliation_rows.append(reconciliation)
        permitted_primary = reconciliation["status"] in {
            "consensus",
            "explainable_corporate_action_difference",
        }
        if primary is not None and (permitted_primary or fallback is None):
            canonical = primary
            selected_provider = "tiingo"
        elif fallback is not None:
            canonical = fallback
            selected_provider = "yfinance"
        else:
            canonical = None
            selected_provider = None

        canonical_status = "missing"
        if canonical is not None:
            canonical_path = root / "canonical" / f"{symbol}.csv"
            canonical_path.parent.mkdir(parents=True, exist_ok=True)
            canonical.to_csv(canonical_path, index=False)
            file_hashes[str(canonical_path.relative_to(root))] = _sha256(
                canonical_path
            )
            canonical_status = "ready"

        actions = _corporate_actions(primary, symbol)
        action_frames.append(actions)
        action_path = root / "corporate_actions" / f"{symbol}.csv"
        action_path.parent.mkdir(parents=True, exist_ok=True)
        actions.to_csv(action_path, index=False)
        file_hashes[str(action_path.relative_to(root))] = _sha256(action_path)

        coverage_rows.append(
            {
                "symbol": symbol,
                "canonical_status": canonical_status,
                "selected_provider": selected_provider,
                "reconciliation_status": reconciliation["status"],
                "professional_source_ok": bool(primary_attempt.get("ok")),
                "fallback_source_ok": bool(fallback_attempt.get("ok")),
                "canonical_rows": int(len(canonical)) if canonical is not None else 0,
                "canonical_first_date": (
                    canonical["date"].min().date().isoformat()
                    if canonical is not None
                    else None
                ),
                "canonical_last_date": (
                    canonical["date"].max().date().isoformat()
                    if canonical is not None
                    else None
                ),
                "corporate_action_rows": int(len(actions)),
                "primary_attempt": json.dumps(primary_attempt, sort_keys=True),
                "fallback_attempt": json.dumps(fallback_attempt, sort_keys=True),
            }
        )

    coverage = (
        pd.DataFrame(coverage_rows).sort_values("symbol").reset_index(drop=True)
    )
    reconciliations = (
        pd.DataFrame(reconciliation_rows)
        .sort_values("symbol")
        .reset_index(drop=True)
    )
    all_actions = (
        pd.concat(action_frames, ignore_index=True)
        if action_frames
        else pd.DataFrame()
    )
    coverage_path = root / "coverage.csv"
    reconciliation_path = root / "reconciliation.csv"
    actions_path = root / "corporate_actions.csv"
    coverage.to_csv(coverage_path, index=False)
    reconciliations.to_csv(reconciliation_path, index=False)
    all_actions.to_csv(actions_path, index=False)
    for path in (coverage_path, reconciliation_path, actions_path):
        file_hashes[str(path.relative_to(root))] = _sha256(path)

    ready_rows = coverage.loc[coverage["canonical_status"].eq("ready")]
    strategy_data_ready = len(ready_rows) == len(ETF_REFERENCE_SYMBOLS)
    common_start: str | None = None
    common_end: str | None = None
    if strategy_data_ready:
        starts = pd.to_datetime(ready_rows["canonical_first_date"], errors="coerce")
        ends = pd.to_datetime(ready_rows["canonical_last_date"], errors="coerce")
        if starts.isna().any() or ends.isna().any():
            strategy_data_ready = False
        else:
            start_value = pd.Timestamp(starts.max())
            end_value = pd.Timestamp(ends.min())
            strategy_data_ready = start_value <= end_value
            if strategy_data_ready:
                common_start = start_value.date().isoformat()
                common_end = end_value.date().isoformat()

    professional_source_ready = bool(
        strategy_data_ready
        and coverage["professional_source_ok"].all()
        and coverage["fallback_source_ok"].all()
        and reconciliations["status"]
        .isin(["consensus", "explainable_corporate_action_difference"])
        .all()
    )
    manifest = {
        "schema_version": "1.1",
        "bundle_id": str(contract["bundle_id"]),
        "research_only": True,
        "trade_ready": False,
        "contract_path": str(contract_file),
        "contract_sha256": _sha256(contract_file),
        "symbols": list(ETF_REFERENCE_SYMBOLS),
        "requested_start": start,
        "requested_end": end,
        "common_history_start": common_start,
        "common_history_end": common_end,
        "strategy_data_ready": strategy_data_ready,
        "professional_source_ready": professional_source_ready,
        "selected_providers": {
            str(row.symbol): row.selected_provider
            for row in coverage.itertuples()
        },
        "reconciliation_status": {
            str(row.symbol): row.status for row in reconciliations.itertuples()
        },
        "provider_contracts": {
            "tiingo": provider_manifest_entry("tiingo"),
            "yfinance": provider_manifest_entry("yfinance"),
        },
        "files": dict(sorted(file_hashes.items())),
        "limitations": [
            "Yahoo-only bundles are research-usable but not professionally corroborated.",
            "No QQQI observations are synthesized before its actual first source row.",
            "Synthetic amount is diagnostic only and is not reported turnover.",
            "Open-price reconciliation uses a separate distribution and compounded-drift gate because vendor opening prints are noisier than closing total returns.",
            "This bundle does not change or promote any strategy rule.",
        ],
    }
    manifest_path = root / MANIFEST_NAME
    _write_json(manifest_path, manifest)
    return manifest


def load_etf_reference_bundle(
    bundle_root: str | Path,
    *,
    symbols: Sequence[str] = ETF_REFERENCE_SYMBOLS,
    require_strategy_ready: bool = True,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, dict[str, Any]]:
    root = Path(bundle_root).resolve()
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ETFReferenceBundleError(
            f"ETF bundle manifest is missing: {manifest_path}"
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if require_strategy_ready and manifest.get("strategy_data_ready") is not True:
        raise ETFReferenceBundleError("ETF bundle is not strategy-data ready")

    requested = [str(symbol).strip().upper() for symbol in symbols]
    undeclared = sorted(set(requested).difference(manifest.get("symbols", [])))
    if undeclared:
        raise ETFReferenceBundleError(
            f"ETF bundle does not declare symbols: {undeclared}"
        )

    bars: dict[str, pd.DataFrame] = {}
    for symbol in requested:
        path = root / "canonical" / f"{symbol}.csv"
        relative = str(path.relative_to(root))
        expected_hash = manifest.get("files", {}).get(relative)
        if not path.is_file() or not expected_hash:
            raise ETFReferenceBundleError(f"canonical ETF file is missing: {symbol}")
        actual_hash = _sha256(path)
        if actual_hash != expected_hash:
            raise ETFReferenceBundleError(
                f"canonical ETF hash mismatch for {symbol}: "
                f"{actual_hash} != {expected_hash}"
            )
        bars[symbol] = _normalise_frame(pd.read_csv(path), symbol)

    coverage_path = root / "coverage.csv"
    coverage = pd.read_csv(coverage_path)
    return bars, coverage, manifest
