"""Replay adapter for All Weather Multi Asset Alpha Rotation.

This module deliberately keeps the strategy research-only. It provides a governed
entry point for future Bundle v2 publication after exact data/evaluator wiring.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

MODEL_ID = "all_weather_alpha_rotation_v1"
REPLAY_ID = "all_weather_alpha_rotation_v1"


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


def replay_all_weather_alpha_rotation_v1(*, root: str | Path) -> dict[str, Any]:
    """Return a governed replay status.

    The first implementation establishes the replay identity boundary. The
    numerical evaluator must only be enabled after exact provider data,
    corporate-action handling, and transaction-cost contracts are bound.
    """
    normalized_root = Path(root).resolve()
    contract = normalized_root / "configs/models/all_weather_alpha_rotation_v1.yaml"
    if not contract.exists():
        return _receipt(
            decision="invalid_evidence",
            reason=f"missing model contract: {contract}",
        )

    return _receipt(
        decision="adapter_ready_pending_exact_evaluator",
        reason="portfolio evaluator and governed data recipe require explicit binding before formal replay",
    )
