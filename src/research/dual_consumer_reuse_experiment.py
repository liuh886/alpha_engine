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
    decision_session: str,
    horizons: tuple[int, ...] = (7, 14, 28),
    root: Path | None = None,
) -> dict[str, Any]:
    """Consumer 2: A-Share RDI Event Horizon Readiness using shared data slice.

    Evaluates realized 7/14/28-session forward outcomes for CSI300 (000300)
    or reference ETFs following a macro risk decision session.
    If tail sessions are insufficient before cutoff, honestly reports blocked
    without fabricating or forward-filling missing sessions (#1272).
    """
    slice_res = get_research_data_slice(request, root=root)
    receipt = slice_res.receipt

    if receipt.get("status") != "ready" or slice_res.data is None:
        return {
            "consumer": "ashare_rdi_readiness",
            "status": "blocked",
            "reason": "Underlying research data slice is blocked fail-closed",
            "data_slice_receipt": receipt,
            "decision_session": decision_session,
            "horizons": list(horizons),
            "outcomes": None,
            "experiment_hash": None,
            "research_only": True,
            "trade_ready": False,
            "trade_signal": False,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }

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
            decision_session=date.fromisoformat(decision_session),
            horizons=horizons,
            instrument_kind="index",
        )
    except ValueError as exc:
        return {
            "consumer": "ashare_rdi_readiness",
            "status": "blocked",
            "reason": f"Forward outcomes evaluation failed: {exc}",
            "data_slice_receipt": receipt,
            "decision_session": decision_session,
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
            "decision_session": decision_session,
            "horizons": list(horizons),
            "outcomes": outcomes,
            "experiment_hash": None,
            "research_only": True,
            "trade_ready": False,
            "trade_signal": False,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        }

    experiment_payload = {
        "consumer": "ashare_rdi_readiness",
        "decision_session": decision_session,
        "as_of_cutoff": request.as_of_cutoff,
        "horizons": list(horizons),
        "outcomes": outcomes,
        "data_hash": receipt["data_hash"],
    }
    raw_bytes = json.dumps(experiment_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    experiment_hash = hashlib.sha256(raw_bytes).hexdigest()

    return {
        "consumer": "ashare_rdi_readiness",
        "status": "ready",
        "decision_session": decision_session,
        "data_slice_receipt": receipt,
        "horizons": list(horizons),
        "outcomes": outcomes,
        "experiment_hash": experiment_hash,
        "research_only": True,
        "trade_ready": False,
        "trade_signal": False,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
