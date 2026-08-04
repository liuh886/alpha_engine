"""Immutable v2 evidence layer for the BYD prospective shadow ledger.

Signals are calculated from the chain-linked as-of dataset, but every future
return is settled only from previously sealed daily observations. A later
provider response can add a new observation; it cannot alter the prices,
positions, company actions, or outcomes already recorded.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from src.research.byd_prospective_shadow import (
    HORIZONS,
    IndependentAudit,
    ChainLinkedExtension,
    _normalise_dates,
    file_sha256,
)
from src.research.byd_v1_2_recovery_state import (
    CANONICAL_ADJUSTED_SHA256,
    CANONICAL_CUTOFF,
    CANONICAL_MANIFEST_SHA256,
    dataframe_sha256,
    execute_next_eligible_open,
)
from src.research.byd_v1_3_recovery_overlay import SNAPSHOT_SHA256

SHADOW_SCHEMA_V2 = "byd_prospective_shadow_v2"
COST_SCENARIOS_BPS = (20, 40)
PRICE_COLUMNS = ("open", "high", "low", "close")

LEDGER_COLUMNS_V2 = (
    "signal_date",
    "observed_at_utc",
    "observation_mode",
    "prospective_eligible",
    "observation_sha256",
    "data_version",
    "provider_payload_sha256",
    "secondary_payload_sha256",
    "extended_adjusted_sha256",
    "primary_provider",
    "secondary_provider",
    "open_research_eligible",
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "raw_volume",
    "provider_adjusted_close",
    "adjusted_open",
    "adjusted_high",
    "adjusted_low",
    "adjusted_close",
    "independent_raw_open",
    "independent_raw_close",
    "dividend",
    "stock_split",
    "base_target_position",
    "shadow_overlay_active",
    "shadow_overlay_branch",
    "shadow_target_position",
    "branch_a_condition",
    "branch_b_condition",
    "drawdown_252",
    "distance_from_low_20",
    "momentum_accel_20_60",
    "open_return_autocorr_20",
    "market_state",
    "vol_state",
    "status",
    "entry_open_date",
    "exit_open_date_5",
    "base_return_5_20bps",
    "shadow_return_5_20bps",
    "incremental_return_5_20bps",
    "base_return_5_40bps",
    "shadow_return_5_40bps",
    "incremental_return_5_40bps",
    "exit_open_date_10",
    "base_return_10_20bps",
    "shadow_return_10_20bps",
    "incremental_return_10_20bps",
    "base_return_10_40bps",
    "shadow_return_10_40bps",
    "incremental_return_10_40bps",
    "exit_open_date_20",
    "base_return_20_20bps",
    "shadow_return_20_20bps",
    "incremental_return_20_20bps",
    "base_return_20_40bps",
    "shadow_return_20_40bps",
    "incremental_return_20_40bps",
)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _atomic_json_record(path: Path, value: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _json_bytes(value) + b"\n"
    digest = hashlib.sha256(payload).hexdigest()
    if path.exists():
        existing = path.read_bytes()
        if existing != payload:
            raise RuntimeError(f"append-only record drift detected: {path}")
        return hashlib.sha256(existing).hexdigest()
    path.write_bytes(payload)
    return digest


def _read_records(directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    ]


def _float(value: Any) -> float:
    result = float(value)
    if not np.isfinite(result):
        raise ValueError("immutable market observation contains a non-finite value")
    return result


def _observation_mode(signal_date: str, observed_at_utc: str) -> str:
    observed = pd.Timestamp(observed_at_utc)
    if observed.tzinfo is None:
        observed = observed.tz_localize("UTC")
    observed_china_date = observed.tz_convert("Asia/Shanghai").date()
    return (
        "same_session_post_close"
        if observed_china_date == pd.Timestamp(signal_date).date()
        else "catch_up_backfill"
    )


def enrich_observations(
    observations: Iterable[dict[str, Any]],
    extension: ChainLinkedExtension,
    audit: IndependentAudit,
    provider_history: pd.DataFrame,
    *,
    primary_provider: str,
) -> list[dict[str, Any]]:
    """Attach exact as-observed market facts to each signal record."""

    provider = _normalise_dates(provider_history)
    for column in (*PRICE_COLUMNS, "volume", "adj_close"):
        provider[column] = pd.to_numeric(provider[column], errors="raise").astype(float)
    for column in ("dividends", "stock_splits"):
        if column not in provider:
            provider[column] = 0.0
        provider[column] = pd.to_numeric(provider[column], errors="coerce").fillna(0.0)
    provider_columns = [
        "date",
        *PRICE_COLUMNS,
        "volume",
        "adj_close",
        "dividends",
        "stock_splits",
    ]
    full_payload_sha = dataframe_sha256(provider[provider_columns])
    provider_by_date = provider.set_index("date")
    raw_by_date = _normalise_dates(extension.primary_raw_new).set_index("date")
    adjusted_by_date = _normalise_dates(extension.adjusted_new).set_index("date")
    audit_by_date = _normalise_dates(audit.row_audit).set_index("date")

    enriched: list[dict[str, Any]] = []
    for original in observations:
        row = dict(original)
        date = pd.Timestamp(row["signal_date"])
        provider_row = provider_by_date.loc[date]
        raw_row = raw_by_date.loc[date]
        adjusted_row = adjusted_by_date.loc[date]
        audit_row = audit_by_date.loc[date]
        mode = _observation_mode(row["signal_date"], row["observed_at_utc"])
        row.update(
            {
                "schema_version": SHADOW_SCHEMA_V2,
                "provider_payload_sha256": full_payload_sha,
                "primary_provider": primary_provider,
                "observation_mode": mode,
                "prospective_eligible": mode == "same_session_post_close",
                "primary_raw_ohlcv": {
                    column: _float(raw_row[column])
                    for column in (*PRICE_COLUMNS, "volume")
                },
                "provider_adjusted_close": _float(provider_row["adj_close"]),
                "chain_linked_adjusted_ohlcv": {
                    column: _float(adjusted_row[column])
                    for column in (*PRICE_COLUMNS, "volume")
                },
                "company_actions": {
                    "dividend": _float(provider_row["dividends"]),
                    "stock_split": _float(provider_row["stock_splits"]),
                },
                "independent_raw_ohlcv": {
                    column: (
                        _float(audit_row[f"{column}_secondary"])
                        if pd.notna(audit_row.get(f"{column}_secondary"))
                        else None
                    )
                    for column in (*PRICE_COLUMNS, "volume")
                },
                "independent_audit": {
                    "confirmed": bool(audit_row["independent_raw_confirmed"]),
                    "open_research_eligible": bool(
                        audit_row["open_research_eligible"]
                    ),
                    "open_level_abs_pct_difference": (
                        _float(audit_row["open_level_abs_pct_difference"])
                        if pd.notna(audit_row["open_level_abs_pct_difference"])
                        else None
                    ),
                    "close_level_abs_pct_difference": (
                        _float(audit_row["close_level_abs_pct_difference"])
                        if pd.notna(audit_row["close_level_abs_pct_difference"])
                        else None
                    ),
                },
            }
        )
        row["data_version"] = (
            f"byd-shadow-v2-{row['signal_date']}-{full_payload_sha[:12]}"
        )
        enriched.append(row)
    return enriched


def _observation_frame(observations: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for observation in observations:
        adjusted = observation["chain_linked_adjusted_ohlcv"]
        rows.append(
            {
                "date": pd.Timestamp(observation["signal_date"]),
                "open": _float(adjusted["open"]),
                "open_research_eligible": bool(
                    observation["open_research_eligible"]
                ),
                "base_target_position": _float(
                    observation["base_target_position"]
                ),
                "shadow_target_position": _float(
                    observation["shadow_target_position"]
                ),
            }
        )
    if not rows:
        return pd.DataFrame(
            columns=[
                "open",
                "open_research_eligible",
                "base_target_position",
                "shadow_target_position",
            ]
        )
    frame = pd.DataFrame(rows).sort_values("date").drop_duplicates("date", keep="last")
    return frame.set_index("date")


def _stored_strategy_daily(
    frame: pd.DataFrame,
    decision_column: str,
    *,
    cost_bps: float,
) -> pd.DataFrame:
    decision = frame[decision_column].astype(float)
    position = execute_next_eligible_open(
        decision,
        frame["open_research_eligible"].astype(bool),
        initial_position=0.75,
    )
    open_to_next = frame["open"].shift(-1) / frame["open"] - 1.0
    turnover = position.diff().abs().fillna(0.0)
    daily = pd.DataFrame(
        {
            "position_at_open": position,
            "turnover_units": turnover,
            "net_return": position * open_to_next - turnover * cost_bps / 10_000.0,
        },
        index=frame.index,
    )
    return daily.iloc[:-1].copy()


def mature_outcomes_from_observations(
    observations: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Settle 5/10/20-open outcomes only from immutable observations."""

    records = sorted(observations, key=lambda row: row["signal_date"])
    frame = _observation_frame(records)
    if frame.empty:
        return []
    strategies = {
        cost: {
            "base": _stored_strategy_daily(
                frame, "base_target_position", cost_bps=float(cost)
            ),
            "shadow": _stored_strategy_daily(
                frame, "shadow_target_position", cost_bps=float(cost)
            ),
        }
        for cost in COST_SCENARIOS_BPS
    }
    outcomes: list[dict[str, Any]] = []
    for observation in records:
        signal_date = pd.Timestamp(observation["signal_date"])
        eligible = list(
            frame.index[
                (frame.index > signal_date)
                & frame["open_research_eligible"].astype(bool)
            ]
        )
        for horizon in HORIZONS:
            if len(eligible) <= horizon:
                continue
            entry = eligible[0]
            exit_ = eligible[horizon]
            scenarios: dict[str, dict[str, float]] = {}
            for cost, results in strategies.items():
                base_block = results["base"].loc[
                    (results["base"].index >= entry)
                    & (results["base"].index < exit_)
                ]
                shadow_block = results["shadow"].reindex(base_block.index)
                base_return = float(
                    (1.0 + base_block["net_return"]).prod() - 1.0
                )
                shadow_return = float(
                    (1.0 + shadow_block["net_return"]).prod() - 1.0
                )
                scenarios[str(cost)] = {
                    "base_return": base_return,
                    "shadow_return": shadow_return,
                    "incremental_return": (
                        (1.0 + shadow_return) / (1.0 + base_return) - 1.0
                    ),
                }
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
                    "research_only": True,
                    "shadow_only": True,
                }
            )
    return outcomes


def _derived_ledger_v2(
    observations: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    observation_hashes: dict[str, str],
) -> pd.DataFrame:
    outcome_map = {
        (row["signal_date"], int(row["horizon_eligible_opens"])): row
        for row in outcomes
    }
    rows: list[dict[str, Any]] = []
    for observation in observations:
        signal_date = observation["signal_date"]
        raw = observation["primary_raw_ohlcv"]
        adjusted = observation["chain_linked_adjusted_ohlcv"]
        independent = observation["independent_raw_ohlcv"]
        actions = observation["company_actions"]
        factors = observation["factors"]
        row: dict[str, Any] = {
            "signal_date": signal_date,
            "observed_at_utc": observation["observed_at_utc"],
            "observation_mode": observation["observation_mode"],
            "prospective_eligible": observation["prospective_eligible"],
            "observation_sha256": observation_hashes[signal_date],
            "data_version": observation["data_version"],
            "provider_payload_sha256": observation["provider_payload_sha256"],
            "secondary_payload_sha256": observation["secondary_payload_sha256"],
            "extended_adjusted_sha256": observation["extended_adjusted_sha256"],
            "primary_provider": observation["primary_provider"],
            "secondary_provider": observation["secondary_provider"],
            "open_research_eligible": observation["open_research_eligible"],
            "raw_open": raw["open"],
            "raw_high": raw["high"],
            "raw_low": raw["low"],
            "raw_close": raw["close"],
            "raw_volume": raw["volume"],
            "provider_adjusted_close": observation["provider_adjusted_close"],
            "adjusted_open": adjusted["open"],
            "adjusted_high": adjusted["high"],
            "adjusted_low": adjusted["low"],
            "adjusted_close": adjusted["close"],
            "independent_raw_open": independent["open"],
            "independent_raw_close": independent["close"],
            "dividend": actions["dividend"],
            "stock_split": actions["stock_split"],
            "base_target_position": observation["base_target_position"],
            "shadow_overlay_active": observation["shadow_overlay_active"],
            "shadow_overlay_branch": observation["shadow_overlay_branch"],
            "shadow_target_position": observation["shadow_target_position"],
            "branch_a_condition": observation["branch_a_condition"],
            "branch_b_condition": observation["branch_b_condition"],
            "drawdown_252": factors["drawdown_252"],
            "distance_from_low_20": factors["distance_from_low_20"],
            "momentum_accel_20_60": factors["momentum_accel_20_60"],
            "open_return_autocorr_20": factors["open_return_autocorr_20"],
            "market_state": factors["market_state"],
            "vol_state": factors["vol_state"],
            "status": observation["status"],
            "entry_open_date": "",
        }
        for horizon in HORIZONS:
            outcome = outcome_map.get((signal_date, horizon))
            row[f"exit_open_date_{horizon}"] = (
                outcome["exit_open_date"] if outcome else ""
            )
            if outcome and not row["entry_open_date"]:
                row["entry_open_date"] = outcome["entry_open_date"]
            for cost in COST_SCENARIOS_BPS:
                scenario = (
                    outcome["cost_scenarios_bps"][str(cost)] if outcome else None
                )
                for metric in ("base_return", "shadow_return", "incremental_return"):
                    row[f"{metric}_{horizon}_{cost}bps"] = (
                        scenario[metric] if scenario else np.nan
                    )
        rows.append(row)
    return pd.DataFrame(rows, columns=LEDGER_COLUMNS_V2)


def persist_shadow_store_v2(
    store_root: str | Path,
    new_observations: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    root = Path(store_root)
    observation_dir = root / "observations"
    outcome_dir = root / "outcomes"
    observation_dir.mkdir(parents=True, exist_ok=True)
    outcome_dir.mkdir(parents=True, exist_ok=True)

    for observation in new_observations:
        date = observation["signal_date"]
        _atomic_json_record(observation_dir / f"{date}.json", observation)

    observations = _read_records(observation_dir)
    if any(row.get("schema_version") != SHADOW_SCHEMA_V2 for row in observations):
        raise RuntimeError("prospective store contains a non-v2 observation")
    matured = mature_outcomes_from_observations(observations)
    for outcome in matured:
        path = outcome_dir / (
            f"{outcome['signal_date']}-h{int(outcome['horizon_eligible_opens']):02d}.json"
        )
        _atomic_json_record(path, outcome)

    outcomes = _read_records(outcome_dir)
    observation_hashes = {
        row["signal_date"]: file_sha256(
            observation_dir / f"{row['signal_date']}.json"
        )
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
        "first_signal_date": observations[0]["signal_date"] if observations else None,
        "last_signal_date": observations[-1]["signal_date"] if observations else None,
        "observation_sha256": observation_hashes,
        "ledger_sha256": file_sha256(ledger_path),
        "append_only": True,
        "outcome_settlement": "immutable_daily_observations_only",
        "cost_scenarios_bps": list(COST_SCENARIOS_BPS),
        "provider_history_may_not_overwrite_existing_observations": True,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
