"""Shared helpers for maintained active cross-sectional ranker current targets."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.artifacts.strategy_signal_ledger import (
    StrategySignalLedgerError,
    read_latest_evaluation,
)
from src.factors.ranker_snapshot import build_ranker_factor_snapshot

REBALANCE_SESSIONS = 10
COST_BPS = 20


class RankerCurrentTargetError(ValueError):
    """Raised when a current target cannot be proven from frozen semantics."""


def _json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RankerCurrentTargetError(f"JSON root must be an object: {path}")
    return payload


def _canonical_sha(payload: Mapping[str, Any]) -> str:
    text = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _latest_formal_weights(
    package: Mapping[str, Any],
) -> tuple[str, dict[str, float]]:
    positions = package.get("positions")
    if not isinstance(positions, list) or not positions:
        raise RankerCurrentTargetError("formal package has no positions")
    dates = sorted({str(row.get("date", "")) for row in positions if isinstance(row, dict)})
    if not dates or not dates[-1]:
        raise RankerCurrentTargetError("formal positions have no signal date")
    anchor = dates[-1]
    weights = {
        str(row["instrument"]): float(row["weight"])
        for row in positions
        if isinstance(row, dict) and str(row.get("date", "")) == anchor
    }
    if not weights or abs(sum(weights.values()) - 1.0) > 1e-6:
        raise RankerCurrentTargetError("latest formal weights are invalid")
    return anchor, dict(sorted(weights.items()))


def load_previous_state(*, formal_package: Path, ledger_dir: Path) -> tuple[str, dict[str, float]]:
    """Bootstrap one active model from its own formal state, then require its ledger."""

    formal_anchor, formal_weights = _latest_formal_weights(_json(formal_package))
    try:
        record = read_latest_evaluation(
            ledger_dir,
            model_version_id=ledger_dir.name,
        )
    except (OSError, json.JSONDecodeError, StrategySignalLedgerError) as exc:
        raise RankerCurrentTargetError("latest live ranker record is invalid") from exc
    if record is None:
        return formal_anchor, formal_weights
    signal = record.get("signal")
    if not isinstance(signal, dict):
        raise RankerCurrentTargetError("latest live ranker record is invalid")
    signal_date = str(signal.get("signal_date", ""))
    target = signal.get("target_weights")
    if not signal_date or not isinstance(target, dict) or not target:
        raise RankerCurrentTargetError("latest live ranker record is invalid")
    live_weights = {str(key): float(value) for key, value in target.items()}
    if abs(sum(live_weights.values()) - 1.0) > 1e-6:
        raise RankerCurrentTargetError("latest live target weights do not sum to one")
    if pd.Timestamp(signal_date) < pd.Timestamp(formal_anchor):
        raise RankerCurrentTargetError(
            "formal ranker state is ahead of canonical ledger: "
            f"formal={formal_anchor} ledger={signal_date}"
        )
    return signal_date, dict(sorted(live_weights.items()))


def next_due_session(
    *,
    anchor: str,
    sessions: Sequence[pd.Timestamp],
    cadence: int = REBALANCE_SESSIONS,
) -> str | None:
    """Return exactly the cadence-th provider session after the last target."""

    dates = (
        pd.DatetimeIndex(pd.to_datetime(list(sessions)))
        .tz_localize(None)
        .normalize()
        .unique()
        .sort_values()
    )
    anchor_ts = pd.Timestamp(anchor).normalize()
    matches = np.flatnonzero(dates == anchor_ts)
    if len(matches) != 1:
        raise RankerCurrentTargetError(
            f"previous signal date {anchor} is not uniquely present in provider calendar"
        )
    due_index = int(matches[0]) + int(cadence)
    if due_index >= len(dates):
        return None
    return pd.Timestamp(dates[due_index]).strftime("%Y-%m-%d")


def merge_governed_market_sessions(
    *,
    evidence_path: Path,
    live_sessions: Sequence[pd.Timestamp],
    as_of: str,
) -> pd.DatetimeIndex:
    """Join audited history with a bounded live benchmark increment for cadence checks."""

    evidence = _json(evidence_path)
    bars = evidence.get("bars")
    if not isinstance(bars, list) or not bars:
        raise RankerCurrentTargetError("governed benchmark evidence has no bars")
    governed = [
        str(row.get("time", ""))
        for row in bars
        if isinstance(row, dict) and row.get("time")
    ]
    if not governed:
        raise RankerCurrentTargetError("governed benchmark evidence has no sessions")
    dates = (
        pd.DatetimeIndex(pd.to_datetime([*governed, *list(live_sessions)]))
        .tz_localize(None)
        .normalize()
        .unique()
        .sort_values()
    )
    return dates[dates <= pd.Timestamp(as_of).normalize()]


def _turnover(previous: Mapping[str, float], target: Mapping[str, float]) -> float:
    names = set(previous) | set(target)
    return 0.5 * sum(
        abs(target.get(name, 0.0) - previous.get(name, 0.0)) for name in names
    )


def _factor_summary(
    *,
    model_family_id: str,
    signal_date: str,
    target_weights: Mapping[str, float],
    features: pd.DataFrame,
    factor_columns: Mapping[str, str],
    library_sources: Sequence[str | Path] | None = None,
) -> dict[str, Any]:
    target_names = list(target_weights)
    instruments = features.index.get_level_values("instrument")
    selected = features.loc[instruments.isin(target_names)].copy()
    if selected.empty:
        raise RankerCurrentTargetError("factor reference basket has no rows")
    factor_values: dict[str, float] = {}
    references: dict[str, dict[str, Any]] = {}
    for factor_id, column in factor_columns.items():
        if column not in features.columns:
            raise RankerCurrentTargetError(f"missing current factor column: {column}")
        series = selected[column]
        weighted = 0.0
        used = 0.0
        for index, value in series.items():
            instrument = str(index[1]) if isinstance(index, tuple) else str(index)
            weight = float(target_weights.get(instrument, 0.0))
            if weight and pd.notna(value):
                weighted += weight * float(value)
                used += weight
        if used <= 0.0:
            raise RankerCurrentTargetError(
                f"factor {factor_id} has no reference observations"
            )
        value = weighted / used
        factor_values[factor_id] = value
        references[factor_id] = {
            "reference_weighted_mean": value,
            "universe_mean": float(features[column].mean()),
            "reference_weight_covered": used,
        }
    return build_ranker_factor_snapshot(
        model_family_id=model_family_id,
        signal_date=signal_date,
        latest_data_date=signal_date,
        factor_values=factor_values,
        factor_references=references,
        data_freshness_ok=True,
        library_sources=library_sources,
    )


def _explanation_summary(explanations: Mapping[str, Any]) -> dict[str, Any]:
    rows = explanations.get("rows")
    if not isinstance(rows, list):
        raise RankerCurrentTargetError("ranker explanations have no rows")
    return {
        "method": explanations.get("method"),
        "score_reconciliation": explanations.get("score_reconciliation"),
        "decision_role": explanations.get("decision_role"),
        "rows": [
            {
                "instrument": row.get("instrument"),
                "decision_role": row.get("decision_role"),
                "score": row.get("score"),
                "bias": row.get("bias"),
                "top_positive": row.get("top_positive", []),
                "top_negative": row.get("top_negative", []),
            }
            for row in rows
            if isinstance(row, Mapping)
        ],
    }


def _signal_payload(
    *,
    model_version_id: str,
    model_family_id: str,
    signal_date: str,
    market_cutoff: str,
    previous_weights: Mapping[str, float],
    target_weights: Mapping[str, float],
    factor_evidence: Mapping[str, Any],
    model_identity: Mapping[str, Any],
    reason_code: str,
    diagnostics: Mapping[str, Any],
) -> dict[str, Any]:
    turnover = _turnover(previous_weights, target_weights)
    changed = turnover > 1e-12
    core: dict[str, Any] = {
        "model_version_id": model_version_id,
        "model_family_id": model_family_id,
        "model_identity": dict(model_identity),
        "signal_date": signal_date,
        "latest_data_date": signal_date,
        "market_cutoff": market_cutoff,
        "execution_time": "next_eligible_open",
        "current_weights": dict(sorted(previous_weights.items())),
        "target_weights": dict(sorted(target_weights.items())),
        "turnover_units": turnover,
        "estimated_transaction_cost": turnover * COST_BPS / 10000.0,
        "estimated_transaction_cost_bps": COST_BPS,
        "data_freshness_ok": True,
        "factor_evidence": dict(factor_evidence),
        "factor_freshness_ok": factor_evidence.get("freshness") == "current",
        "signal_state": "rebalance" if changed else "no_change",
        "action": "REBALANCE" if changed else "HOLD",
        "reason_code": reason_code,
        "diagnostics": dict(diagnostics),
        "research_only": True,
        "trade_ready": False,
    }
    core["fingerprint"] = _canonical_sha(core)
    core["should_alert"] = changed
    return core


def _select_cn_sector_breadth(
    day: pd.DataFrame,
    *,
    sectors: int,
    names_per_sector: int,
) -> pd.DataFrame:
    ranked = day.dropna(subset=["score", "sector"]).copy()
    ranked = ranked.sort_values(
        ["score", "instrument"],
        ascending=[False, True],
        kind="mergesort",
    )
    ranked["score_pct"] = ranked["score"].rank(method="average", pct=True)
    sector_scores = ranked.groupby("sector", sort=True)["score_pct"].apply(
        lambda series: float(series.nlargest(min(3, len(series))).mean())
    )
    selected = list(
        sector_scores.sort_values(ascending=False, kind="mergesort")
        .head(sectors)
        .index
    )
    pieces = [
        ranked.loc[ranked["sector"] == sector].head(names_per_sector)
        for sector in selected
    ]
    return pd.concat(pieces, ignore_index=False) if pieces else ranked.head(0)
