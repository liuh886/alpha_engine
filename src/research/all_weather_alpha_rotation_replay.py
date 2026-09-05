"""Replay adapter for All Weather Multi Asset Alpha Rotation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

MODEL_ID = "all_weather_alpha_rotation_v1"
REPLAY_ID = "all_weather_alpha_rotation_v1"

from src.research.all_weather_portfolio_engine import (
    build_target_weights,
    simulate_portfolio,
)


class AllWeatherReplayError(ValueError):
    pass


def _receipt(*, decision: str, reason: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "2.0",
        "replay_id": REPLAY_ID,
        "model_version_id": MODEL_ID,
        "decision": decision,
        "research_only": True,
        "trade_ready": False,
        "promotion_authorized": False,
    }
    if reason:
        payload["reason"] = reason
    return payload


def replay_all_weather_alpha_rotation_v1(
    *, root: str | Path, prices=None
) -> dict[str, Any]:
    """Execute the first portfolio-level replay path.

    When market data is supplied, this runs the portfolio simulator. The adapter
    intentionally does not claim formal validation until governed data recipes
    are connected.
    """
    normalized_root = Path(root).resolve()
    contract = normalized_root / "configs/models/all_weather_alpha_rotation_v1.yaml"
    if not contract.exists():
        return _receipt(
            decision="invalid_evidence",
            reason=f"missing model contract: {contract}",
        )

    if prices is None:
        return _receipt(
            decision="evaluator_ready_pending_data",
            reason="portfolio engine connected; governed market data binding remains required",
        )

    target = build_target_weights(prices)
    result = simulate_portfolio(prices, target.to_frame().T.reindex(prices.index).ffill())
    return _receipt(decision="portfolio_simulation_completed") | {
        "metrics": result["metrics"]
    }
