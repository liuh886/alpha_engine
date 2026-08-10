"""Final append-only storage and settlement for BYD prospective evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from src.research.byd_prospective_evidence_v2 import (
    COST_SCENARIOS_BPS,
    SHADOW_SCHEMA_V2,
    _atomic_json_record,
    _derived_ledger_v2,
    _json_bytes,
    _observation_frame,
    _read_records,
    _stored_strategy_daily,
)
from src.research.byd_prospective_shadow import HORIZONS, file_sha256
from src.research.byd_v1_2_recovery_state import (
    CANONICAL_ADJUSTED_SHA256,
    CANONICAL_CUTOFF,
    CANONICAL_MANIFEST_SHA256,
    build_v1_0_decision_position,
)
from src.research.byd_v1_3_recovery_overlay import (
    SNAPSHOT_SHA256,
    build_overlay_schedule,
)


def read_observations(store_root: str | Path) -> list[dict[str, Any]]:
    return _read_records(Path(store_root) / "observations")


def apply_immutable_shadow_schedule(
    new_observations: Iterable[dict[str, Any]],
    existing_observations: Iterable[dict[str, Any]],
    baseline_dataset: pd.DataFrame,
) -> list[dict[str, Any]]:
    """Continue the event clock using sealed post-cutoff factors and positions."""

    new_records = [dict(row) for row in new_observations]
    existing_records = [dict(row) for row in existing_observations]
    if not new_records:
        return []

    required = [
        "market_state",
        "vol_state",
        "drawdown_252",
        "distance_from_low_20",
        "open_return_autocorr_20",
        "momentum_accel_20_60",
        "open_research_eligible",
    ]
    historical = baseline_dataset.loc[:CANONICAL_CUTOFF, required].copy()
    historical_base = build_v1_0_decision_position(baseline_dataset).loc[:CANONICAL_CUTOFF]

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for observation in sorted(
        [*existing_records, *new_records],
        key=lambda row: row["signal_date"],
    ):
        signal_date = str(observation["signal_date"])
        if signal_date in seen:
            raise RuntimeError(f"duplicate prospective signal date: {signal_date}")
        seen.add(signal_date)
        factors = observation["factors"]
        rows.append(
            {
                "date": pd.Timestamp(signal_date),
                "market_state": str(factors["market_state"]),
                "vol_state": str(factors["vol_state"]),
                "drawdown_252": float(factors["drawdown_252"]),
                "distance_from_low_20": float(factors["distance_from_low_20"]),
                "open_return_autocorr_20": float(factors["open_return_autocorr_20"]),
                "momentum_accel_20_60": float(factors["momentum_accel_20_60"]),
                "open_research_eligible": bool(observation["open_research_eligible"]),
                "base_target_position": float(observation["base_target_position"]),
            }
        )
    post = pd.DataFrame(rows).set_index("date").sort_index()
    combined_dataset = pd.concat([historical, post[required]], axis=0)
    combined_base = pd.concat(
        [historical_base, post["base_target_position"]],
        axis=0,
    )
    schedule = build_overlay_schedule(combined_dataset, combined_base)

    for observation in existing_records:
        date = pd.Timestamp(observation["signal_date"])
        expected_target = float(schedule.final_decision_position.loc[date])
        expected_active = bool(schedule.overlay_active.loc[date])
        expected_branch = str(schedule.overlay_branch.loc[date])
        if not np.isclose(
            float(observation["shadow_target_position"]),
            expected_target,
        ):
            raise RuntimeError(f"immutable shadow target drift on {observation['signal_date']}")
        if bool(observation["shadow_overlay_active"]) != expected_active:
            raise RuntimeError(
                f"immutable shadow active-state drift on {observation['signal_date']}"
            )
        if str(observation["shadow_overlay_branch"]) != expected_branch:
            raise RuntimeError(f"immutable shadow branch drift on {observation['signal_date']}")

    for observation in new_records:
        date = pd.Timestamp(observation["signal_date"])
        observation["shadow_target_position"] = float(schedule.final_decision_position.loc[date])
        observation["shadow_overlay_active"] = bool(schedule.overlay_active.loc[date])
        observation["shadow_overlay_branch"] = str(schedule.overlay_branch.loc[date])
    return new_records


def mature_outcomes_from_immutable_observations(
    observations: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    records = sorted(observations, key=lambda row: row["signal_date"])
    frame = _observation_frame(records)
    if frame.empty:
        return []
    strategies = {
        cost: {
            "base": _stored_strategy_daily(
                frame,
                "base_target_position",
                cost_bps=float(cost),
            ),
            "shadow": _stored_strategy_daily(
                frame,
                "shadow_target_position",
                cost_bps=float(cost),
            ),
        }
        for cost in COST_SCENARIOS_BPS
    }
    outcomes: list[dict[str, Any]] = []
    for observation in records:
        signal_date = pd.Timestamp(observation["signal_date"])
        eligible = list(
            frame.index[(frame.index > signal_date) & frame["open_research_eligible"].astype(bool)]
        )
        for horizon in HORIZONS:
            if len(eligible) <= horizon:
                continue
            entry = eligible[0]
            exit_ = eligible[horizon]
            scenarios: dict[str, dict[str, float]] = {}
            for cost, results in strategies.items():
                base_block = results["base"].loc[
                    (results["base"].index >= entry) & (results["base"].index < exit_)
                ]
                shadow_block = results["shadow"].reindex(base_block.index)
                base_return = float((1.0 + base_block["net_return"]).prod() - 1.0)
                shadow_return = float((1.0 + shadow_block["net_return"]).prod() - 1.0)
                scenarios[str(cost)] = {
                    "base_return": base_return,
                    "shadow_return": shadow_return,
                    "incremental_return": ((1.0 + shadow_return) / (1.0 + base_return) - 1.0),
                }
            settlement_records = [
                row for row in records if signal_date <= pd.Timestamp(row["signal_date"]) <= exit_
            ]
            settlement_payload = b"".join(_json_bytes(row) + b"\n" for row in settlement_records)
            outcomes.append(
                {
                    "schema_version": SHADOW_SCHEMA_V2,
                    "signal_date": observation["signal_date"],
                    "horizon_eligible_opens": horizon,
                    "entry_open_date": entry.strftime("%Y-%m-%d"),
                    "exit_open_date": exit_.strftime("%Y-%m-%d"),
                    "cost_scenarios_bps": scenarios,
                    "base_snapshot_sha256": SNAPSHOT_SHA256,
                    "observation_data_version": observation["data_version"],
                    "settlement_source": "immutable_daily_observations_only",
                    "settlement_input_sha256": hashlib.sha256(settlement_payload).hexdigest(),
                    "settlement_last_observation_date": exit_.strftime("%Y-%m-%d"),
                    "prospective_eligible": bool(observation["prospective_eligible"]),
                    "research_only": True,
                    "shadow_only": True,
                }
            )
    return outcomes


def persist_immutable_shadow_store(
    store_root: str | Path,
    new_observations: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    root = Path(store_root)
    observation_dir = root / "observations"
    outcome_dir = root / "outcomes"
    observation_dir.mkdir(parents=True, exist_ok=True)
    outcome_dir.mkdir(parents=True, exist_ok=True)

    for observation in new_observations:
        _atomic_json_record(
            observation_dir / f"{observation['signal_date']}.json",
            observation,
        )

    observations = _read_records(observation_dir)
    if any(row.get("schema_version") != SHADOW_SCHEMA_V2 for row in observations):
        raise RuntimeError("prospective store contains a non-v2 observation")
    matured = mature_outcomes_from_immutable_observations(observations)
    for outcome in matured:
        _atomic_json_record(
            outcome_dir
            / (f"{outcome['signal_date']}-h{int(outcome['horizon_eligible_opens']):02d}.json"),
            outcome,
        )

    outcomes = _read_records(outcome_dir)
    observation_hashes = {
        row["signal_date"]: file_sha256(observation_dir / f"{row['signal_date']}.json")
        for row in observations
    }
    ledger = _derived_ledger_v2(observations, outcomes, observation_hashes)
    ledger_path = root / "ledger.csv"
    ledger.to_csv(
        ledger_path,
        index=False,
        float_format="%.12f",
        lineterminator="\n",
    )
    manifest = {
        "schema_version": SHADOW_SCHEMA_V2,
        "research_only": True,
        "trade_ready": False,
        "shadow_only": True,
        "base_snapshot_sha256": SNAPSHOT_SHA256,
        "base_adjusted_sha256": CANONICAL_ADJUSTED_SHA256,
        "base_manifest_sha256": CANONICAL_MANIFEST_SHA256,
        "baseline_cutoff": CANONICAL_CUTOFF,
        "observation_count": len(observations),
        "prospective_eligible_observation_count": sum(
            bool(row["prospective_eligible"]) for row in observations
        ),
        "outcome_count": len(outcomes),
        "prospective_eligible_outcome_count": sum(
            bool(row.get("prospective_eligible")) for row in outcomes
        ),
        "first_signal_date": observations[0]["signal_date"] if observations else None,
        "last_signal_date": observations[-1]["signal_date"] if observations else None,
        "observation_sha256": observation_hashes,
        "ledger_sha256": file_sha256(ledger_path),
        "append_only": True,
        "outcome_settlement": "immutable_daily_observations_only",
        "cost_scenarios_bps": list(COST_SCENARIOS_BPS),
        "provider_history_may_not_overwrite_existing_observations": True,
        "last_updated_at_utc": (observations[-1]["observed_at_utc"] if observations else None),
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
