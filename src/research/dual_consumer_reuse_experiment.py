"""RI-04 / B3: Dual-consumer research reuse experiment.

Governed under Track B (#1296) and ADR-0005.
Demonstrates that two completely distinct research consumers:
  Consumer 1: CN Cross-Sectional Ranking / Momentum Research
  Consumer 2: A-Share RDI Forward Event Horizon Readiness
share the exact same parameterized `get_research_data_slice()` data plane,
PIT cutoff filtering, and cryptographic receipts without duplicate data cleaning.

Non-negotiable invariants:
- research_only=true, trade_ready=false, trade_signal=false.
- RDI descriptive risk evaluation is NEVER promoted to a live trading signal.
- Fail-closed: missing tail sessions or PIT violations are honestly reported as blocked.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.data.research_slice import DataSliceRequest, get_research_data_slice
from src.research.ashare_rdi.contracts import RiskEvent
from src.research.ashare_rdi.outcomes import PriceBar, forward_outcomes


def run_cn_cross_sectional_research_experiment(
    request: DataSliceRequest,
    *,
    root: Path | None = None,
) -> dict[str, Any]:
    """Consumer 1: CN Cross-Sectional Research using shared data slice.

    Extracts market evidence bars, constructs wide cross-sectional panels,
    computes 20-session momentum and rolling volatility features, and produces
    a deterministic ranking receipt cryptographically bound to the input data hash.
    """
    slice_res = get_research_data_slice(request, root=root)
    receipt = slice_res.receipt

    if receipt.get("status") != "ready" or slice_res.data is None:
        return {
            "consumer": "cn_cross_sectional_research",
            "status": "blocked",
            "reason": "Underlying research data slice is blocked fail-closed",
            "data_slice_receipt": receipt,
            "metrics": None,
            "rankings": None,
            "experiment_hash": None,
            "research_only": True,
            "trade_ready": False,
            "trade_signal": False,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    df = slice_res.data
    close_wide = df.pivot(index="time", columns="symbol", values="close")
    volume_wide = df.pivot(index="time", columns="symbol", values="volume")

    # Compute governed cross-sectional technical features
    mom20 = (close_wide / close_wide.shift(20)) - 1.0
    vol20 = close_wide.pct_change(fill_method=None).rolling(20).std()
    volume_ratio20 = (volume_wide / volume_wide.rolling(20).mean()) - 1.0

    latest_time = str(close_wide.index[-1])
    latest_mom = mom20.loc[latest_time].to_dict()
    latest_vol = vol20.loc[latest_time].to_dict()
    latest_vol_ratio = volume_ratio20.loc[latest_time].to_dict()

    # Sort symbols by momentum descending
    sorted_symbols = sorted(
        request.symbols,
        key=lambda s: (latest_mom.get(s) is not None, latest_mom.get(s, float("-inf"))),
        reverse=True,
    )
    rankings = {
        sym: {
            "rank": rank + 1,
            "momentum_20": latest_mom.get(sym),
            "volatility_20": latest_vol.get(sym),
            "volume_ratio_20": latest_vol_ratio.get(sym),
        }
        for rank, sym in enumerate(sorted_symbols)
    }

    experiment_payload = {
        "consumer": "cn_cross_sectional_research",
        "as_of_cutoff": request.as_of_cutoff,
        "evaluation_time": latest_time,
        "symbols": list(request.symbols),
        "rankings": rankings,
        "data_hash": receipt["data_hash"],
    }
    raw_bytes = json.dumps(experiment_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    experiment_hash = hashlib.sha256(raw_bytes).hexdigest()

    return {
        "consumer": "cn_cross_sectional_research",
        "status": "ready",
        "evaluation_time": latest_time,
        "data_slice_receipt": receipt,
        "metrics": {
            "evaluated_symbols_count": len(request.symbols),
            "total_trading_sessions": len(close_wide),
        },
        "rankings": rankings,
        "experiment_hash": experiment_hash,
        "research_only": True,
        "trade_ready": False,
        "trade_signal": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def run_rdi_event_horizon_readiness_experiment(
    request: DataSliceRequest,
    *,
    event: RiskEvent | None = None,
    decision_session: str | None = None,
    horizons: tuple[int, ...] = (7, 14, 28),
    root: Path | None = None,
) -> dict[str, Any]:
    """Consumer 2: A-Share RDI Event Horizon Readiness using shared data slice.

    Evaluates realized 7/14/28-session forward outcomes for CSI300 (000300)
    or reference ETFs following a macro risk decision session.

    #1272 Contract Enforcement:
    1. Must bind to an authoritative RiskEvent with verified source provenance
       (source_id, source_hash, announced_at, available_at).
    2. Missing event source or incomplete event archive strictly fails closed
       with 'blocked_event_pit_coverage'; missing events cannot be treated as zero
       or substituted with arbitrary unanchored dates.
    3. If event availability postdates the request cutoff (available_at > cutoff),
       evaluation is strictly blocked against lookahead.
    4. If tail price sessions before cutoff are insufficient, honestly reports
       blocked without fabricating or forward-filling missing sessions.
    """
    slice_res = get_research_data_slice(request, root=root)
    receipt = slice_res.receipt

    # 1. Base data slice check
    if receipt.get("status") != "ready" or slice_res.data is None:
        return {
            "consumer": "ashare_rdi_readiness",
            "status": "blocked",
            "reason": "Underlying research data slice is blocked fail-closed",
            "data_slice_receipt": receipt,
            "decision_session": decision_session,
            "event_provenance": None,
            "horizons": list(horizons),
            "outcomes": None,
            "experiment_hash": None,
            "research_only": True,
            "trade_ready": False,
            "trade_signal": False,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    # 2. #1272 Event provenance check: missing event archive fails closed
    if event is None:
        return {
            "consumer": "ashare_rdi_readiness",
            "status": "blocked",
            "reason": (
                "blocked_event_pit_coverage: No verified PIT risk event bound (#1272). "
                "Archived event coverage for required event families is incomplete; "
                "missing events cannot be scored as zero or substituted with arbitrary dates."
            ),
            "data_slice_receipt": receipt,
            "decision_session": decision_session,
            "event_provenance": None,
            "horizons": list(horizons),
            "outcomes": None,
            "experiment_hash": None,
            "research_only": True,
            "trade_ready": False,
            "trade_signal": False,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    # 3. Validate event PIT availability against request cutoff
    event_avail_date = event.available_at.date().isoformat()
    if event_avail_date > request.as_of_cutoff:
        return {
            "consumer": "ashare_rdi_readiness",
            "status": "blocked",
            "reason": (
                f"Event available_at '{event.available_at.isoformat()}' is after as_of_cutoff "
                f"'{request.as_of_cutoff}'; lookahead event evaluation is strictly forbidden."
            ),
            "data_slice_receipt": receipt,
            "decision_session": event.active_from.isoformat(),
            "event_provenance": {
                "event_id": event.event_id,
                "story_id": event.story_id,
                "family": event.family,
                "stage": event.stage,
                "announced_at": event.announced_at.isoformat(),
                "available_at": event.available_at.isoformat(),
                "source_id": event.source_id,
                "source_hash": event.source_hash,
            },
            "horizons": list(horizons),
            "outcomes": None,
            "experiment_hash": None,
            "research_only": True,
            "trade_ready": False,
            "trade_signal": False,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    effective_session = decision_session or event.active_from.isoformat()

    df = slice_res.data
    price_bars = [
        PriceBar(
            session=date.fromisoformat(row["time"]),
            open=float(row["open"]),
            low=float(row["low"]),
            close=float(row["close"]),
        )
        for _, row in df.iterrows()
    ]

    try:
        outcomes = forward_outcomes(
            price_bars,
            decision_session=date.fromisoformat(effective_session),
            horizons=horizons,
            instrument_kind="index",
        )
    except ValueError as exc:
        return {
            "consumer": "ashare_rdi_readiness",
            "status": "blocked",
            "reason": f"Forward outcomes evaluation failed: {exc}",
            "data_slice_receipt": receipt,
            "decision_session": effective_session,
            "event_provenance": {
                "event_id": event.event_id,
                "story_id": event.story_id,
                "source_id": event.source_id,
                "source_hash": event.source_hash,
            },
            "horizons": list(horizons),
            "outcomes": None,
            "experiment_hash": None,
            "research_only": True,
            "trade_ready": False,
            "trade_signal": False,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    # Fail closed if any declared horizon lacks sufficient future bars
    insufficient = [o for o in outcomes if o.get("status") == "insufficient_future_bars"]
    if insufficient:
        missing_horizons = [o["horizon_sessions"] for o in insufficient]
        return {
            "consumer": "ashare_rdi_readiness",
            "status": "blocked",
            "reason": (
                f"Insufficient realized forward sessions before cutoff for horizons {missing_horizons}; "
                "tail observations strictly cannot be fabricated or forward-filled."
            ),
            "data_slice_receipt": receipt,
            "decision_session": effective_session,
            "event_provenance": {
                "event_id": event.event_id,
                "story_id": event.story_id,
                "family": event.family,
                "stage": event.stage,
                "announced_at": event.announced_at.isoformat(),
                "available_at": event.available_at.isoformat(),
                "source_id": event.source_id,
                "source_hash": event.source_hash,
            },
            "horizons": list(horizons),
            "outcomes": outcomes,
            "experiment_hash": None,
            "research_only": True,
            "trade_ready": False,
            "trade_signal": False,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    event_prov = {
        "event_id": event.event_id,
        "story_id": event.story_id,
        "family": event.family,
        "direction": event.direction,
        "stage": event.stage,
        "announced_at": event.announced_at.isoformat(),
        "available_at": event.available_at.isoformat(),
        "source_id": event.source_id,
        "source_hash": event.source_hash,
    }

    experiment_payload = {
        "consumer": "ashare_rdi_readiness",
        "decision_session": effective_session,
        "as_of_cutoff": request.as_of_cutoff,
        "horizons": list(horizons),
        "outcomes": outcomes,
        "data_hash": receipt["data_hash"],
        "event_provenance": event_prov,
    }
    raw_bytes = json.dumps(experiment_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    experiment_hash = hashlib.sha256(raw_bytes).hexdigest()

    return {
        "consumer": "ashare_rdi_readiness",
        "status": "ready",
        "decision_session": effective_session,
        "data_slice_receipt": receipt,
        "event_provenance": event_prov,
        "horizons": list(horizons),
        "outcomes": outcomes,
        "experiment_hash": experiment_hash,
        "research_only": True,
        "trade_ready": False,
        "trade_signal": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
