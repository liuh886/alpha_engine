"""Governed US87 sector map and point-in-time market-style helpers."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

STYLE_DIMENSIONS = (
    "beta60_bucket",
    "vol60_bucket",
    "momentum20_bucket",
    "momentum60_bucket",
    "liquidity20_bucket",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_pool_symbols(path: Path) -> list[str]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected mapping in {path}")
    symbols = payload.get("symbols")
    if not isinstance(symbols, list) or not all(isinstance(value, str) for value in symbols):
        raise ValueError("pool symbols must be a list of strings")
    normalized = [value.strip().upper() for value in symbols]
    if len(normalized) != len(set(normalized)):
        raise ValueError("pool symbols contain duplicates")
    expected = int(payload.get("candidate_count", -1))
    if len(normalized) != expected:
        raise ValueError(f"pool candidate_count={expected} but found {len(normalized)} symbols")
    return normalized


def load_sector_classification(
    path: Path,
    pool_symbols: list[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("classification asset must be a mapping")
    raw_records = payload.get("records")
    if not isinstance(raw_records, dict):
        raise ValueError("classification records must be a mapping")
    canonical_records = json.dumps(
        raw_records,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    records_sha256 = hashlib.sha256(canonical_records).hexdigest()
    if records_sha256 != str(payload.get("records_sha256", "")):
        raise ValueError("classification record hash does not match manifest")
    actual = {str(symbol).strip().upper() for symbol in raw_records}
    expected = set(pool_symbols)
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    if missing or unknown:
        raise ValueError(f"sector classification mismatch: missing={missing}, unknown={unknown}")
    if len(raw_records) != int(payload.get("candidate_count", -1)):
        raise ValueError("classification row count does not match manifest")
    if "QQQ" in actual:
        raise ValueError("QQQ must remain outside the candidate classification")
    common = {
        "classification_standard": str(payload.get("classification_standard", "")),
        "source_provider": str(payload.get("source_provider", "")),
        "source_effective_date": str(payload.get("source_effective_date", "")),
        "retrieval_date": str(payload.get("retrieval_date", "")),
    }
    if any(not value.strip() for value in common.values()):
        raise ValueError("classification common metadata must be complete")
    rows: list[dict[str, str]] = []
    for symbol in sorted(actual):
        record = raw_records.get(symbol)
        if not isinstance(record, dict):
            raise ValueError(f"classification record for {symbol} must be a mapping")
        row = {
            "symbol": symbol,
            "canonical_entity_name": str(record.get("entity", "")).strip(),
            "sector": str(record.get("sector", "")).strip(),
            "industry": str(record.get("industry", "")).strip(),
            "confidence": str(record.get("confidence", "")).strip(),
            "manual_override_rationale": str(record.get("manual_override", "")).strip(),
            **common,
        }
        for column in (
            "canonical_entity_name",
            "sector",
            "industry",
            "confidence",
        ):
            if not row[column]:
                raise ValueError(f"classification contains empty {column} for {symbol}")
        rows.append(row)
    frame = pd.DataFrame(rows)
    tigo = frame.loc[frame["symbol"] == "TIGO"]
    if len(tigo) != 1 or "Millicom" not in str(tigo.iloc[0]["canonical_entity_name"]):
        raise ValueError("TIGO must resolve to Millicom International Cellular")
    tigo_energy = frame.loc[
        frame["canonical_entity_name"].str.contains("Tigo Energy", case=False),
        "symbol",
    ].tolist()
    if tigo_energy != ["TYGO"]:
        raise ValueError("Tigo Energy may only be bound to TYGO")
    manifest = {key: value for key, value in payload.items() if key != "records"}
    manifest["records_sha256_verified"] = records_sha256
    return frame, manifest


def _bucket(
    values: pd.Series,
    labels: tuple[str, str, str],
) -> pd.Series:
    numeric = pd.to_numeric(values, errors="coerce")
    finite = numeric.where(np.isfinite(numeric))
    ranks = finite.rank(method="first", pct=True)
    result = pd.Series("unknown", index=values.index, dtype=object)
    result.loc[ranks <= 1 / 3] = labels[0]
    result.loc[(ranks > 1 / 3) & (ranks <= 2 / 3)] = labels[1]
    result.loc[ranks > 2 / 3] = labels[2]
    return result


def compute_style_snapshot(
    closes: pd.DataFrame,
    volumes: pd.DataFrame,
    date: pd.Timestamp,
    symbols: list[str],
    *,
    benchmark: str = "QQQ",
) -> pd.DataFrame:
    """Compute point-in-time market styles using completed sessions before date."""

    date = pd.Timestamp(date).normalize()
    history_close = closes.loc[closes.index < date].tail(81)
    history_volume = volumes.loc[volumes.index < date].tail(30)
    if benchmark not in history_close.columns:
        raise ValueError(f"benchmark {benchmark} missing from close history")
    qqq_returns = history_close[benchmark].pct_change(fill_method=None).dropna().tail(60)
    qqq_var = float(qqq_returns.var(ddof=1)) if len(qqq_returns) >= 40 else float("nan")
    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        close = history_close[symbol].dropna() if symbol in history_close else pd.Series(dtype=float)
        returns = close.pct_change(fill_method=None).dropna().tail(60)
        aligned = pd.concat([returns, qqq_returns], axis=1, join="inner").dropna()
        beta60 = (
            float(aligned.iloc[:, 0].cov(aligned.iloc[:, 1]) / qqq_var)
            if len(aligned) >= 40 and np.isfinite(qqq_var) and qqq_var > 1e-15
            else float("nan")
        )
        vol60 = (
            float(returns.std(ddof=1) * math.sqrt(252))
            if len(returns) >= 40
            else float("nan")
        )
        momentum20 = (
            float(close.iloc[-1] / close.iloc[-21] - 1)
            if len(close) >= 21 and close.iloc[-21] > 0
            else float("nan")
        )
        momentum60 = (
            float(close.iloc[-1] / close.iloc[-61] - 1)
            if len(close) >= 61 and close.iloc[-61] > 0
            else float("nan")
        )
        liquidity20 = float("nan")
        if symbol in history_volume and symbol in history_close:
            dollar_volume = (
                history_close[symbol].reindex(history_volume.index)
                * history_volume[symbol]
            ).replace([np.inf, -np.inf], np.nan).dropna().tail(20)
            positive = dollar_volume.loc[dollar_volume > 0]
            if len(positive) >= 10:
                liquidity20 = float(positive.median())
        rows.append(
            {
                "rebalance_date": date,
                "instrument": symbol,
                "beta60_qqq": beta60,
                "vol60_annualized": vol60,
                "momentum20": momentum20,
                "momentum60": momentum60,
                "median_dollar_volume20": liquidity20,
            }
        )
    frame = pd.DataFrame(rows)
    frame["beta60_bucket"] = _bucket(
        frame["beta60_qqq"], ("low_beta", "mid_beta", "high_beta")
    )
    frame["vol60_bucket"] = _bucket(
        frame["vol60_annualized"], ("low_vol", "mid_vol", "high_vol")
    )
    frame["momentum20_bucket"] = _bucket(
        frame["momentum20"], ("laggard_20d", "neutral_20d", "leader_20d")
    )
    frame["momentum60_bucket"] = _bucket(
        frame["momentum60"], ("laggard_60d", "neutral_60d", "leader_60d")
    )
    frame["liquidity20_bucket"] = _bucket(
        frame["median_dollar_volume20"],
        ("low_liquidity", "mid_liquidity", "high_liquidity"),
    )
    return frame


def cap_sector_weights(
    weights: pd.Series,
    sector_by_symbol: dict[str, str],
    cap: float,
) -> pd.Series:
    """Cap aggregate sector exposure and redistribute excess deterministically."""

    if not 0 < cap <= 1:
        raise ValueError("sector cap must be in (0, 1]")
    result = weights.astype(float).copy()
    if result.empty or float(result.sum()) <= 0:
        return result
    result /= float(result.sum())
    sectors = pd.Series(
        {symbol: sector_by_symbol.get(str(symbol), "") for symbol in result.index},
        dtype=object,
    )
    if sectors.eq("").any():
        raise ValueError("missing sector while applying sector cap")
    for _ in range(100):
        sector_weights = result.groupby(sectors).sum()
        over = sector_weights.loc[sector_weights > cap + 1e-12]
        if over.empty:
            break
        changed = False
        for sector, sector_weight in over.sort_index().items():
            members = sectors.index[sectors == sector]
            scale = cap / float(sector_weight)
            removed = float(result.loc[members].sum() * (1 - scale))
            result.loc[members] *= scale
            sector_weights = result.groupby(sectors).sum()
            eligible_sectors = sector_weights.loc[sector_weights < cap - 1e-12]
            capacity = (cap - eligible_sectors).clip(lower=0)
            total_capacity = float(capacity.sum())
            if removed <= 1e-15:
                continue
            if total_capacity + 1e-12 < removed:
                raise ValueError("sector cap has insufficient redistribution capacity")
            for target_sector, target_capacity in capacity.sort_index().items():
                allocation = removed * float(target_capacity) / total_capacity
                target_members = sectors.index[sectors == target_sector]
                base = result.loc[target_members]
                if float(base.sum()) <= 0:
                    result.loc[target_members] += allocation / len(target_members)
                else:
                    result.loc[target_members] += base / float(base.sum()) * allocation
            changed = True
        if not changed:
            break
    if not math.isclose(float(result.sum()), 1.0, rel_tol=0.0, abs_tol=1e-10):
        result /= float(result.sum())
    final_sector_weights = result.groupby(sectors).sum()
    if (final_sector_weights > cap + 1e-9).any():
        raise ValueError("sector cap could not be satisfied")
    return result


def style_coverage(frame: pd.DataFrame) -> dict[str, float]:
    metrics = {
        "beta60_qqq": "beta60_qqq",
        "vol60_annualized": "vol60_annualized",
        "momentum20": "momentum20",
        "momentum60": "momentum60",
        "median_dollar_volume20": "median_dollar_volume20",
    }
    return {
        key: float(np.isfinite(pd.to_numeric(frame[column], errors="coerce")).mean())
        for key, column in metrics.items()
    }
