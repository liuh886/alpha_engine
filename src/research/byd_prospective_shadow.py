"""Append-only prospective shadow evidence for BYD recovery factors.

This module extends the immutable canonical v1 snapshot without rewriting any
sealed historical row. Provider-adjusted history is chain-linked at the frozen
2026-08-03 anchor, and every signal observation and matured outcome is stored as
an immutable JSON record. The CSV ledger is a derived index only.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from src.research.byd_v1_2_recovery_state import (
    CANONICAL_ADJUSTED_SHA256,
    CANONICAL_CUTOFF,
    CANONICAL_MANIFEST_SHA256,
    build_research_dataset,
    build_v1_0_decision_position,
    dataframe_sha256,
    run_strategy,
)
from src.research.byd_v1_3_recovery_overlay import (
    SNAPSHOT_SHA256,
    branch_conditions,
    build_overlay_schedule,
)

SHADOW_SCHEMA = "byd_prospective_shadow_v1"
BASELINE_DATE = pd.Timestamp(CANONICAL_CUTOFF)
PRICE_COLUMNS = ("open", "high", "low", "close")
HORIZONS = (5, 10, 20)
LEDGER_COLUMNS = (
    "signal_date",
    "observed_at_utc",
    "observation_sha256",
    "data_version",
    "provider_payload_sha256",
    "secondary_payload_sha256",
    "extended_adjusted_sha256",
    "primary_provider",
    "secondary_provider",
    "open_research_eligible",
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
    "base_return_5",
    "shadow_return_5",
    "incremental_return_5",
    "exit_open_date_10",
    "base_return_10",
    "shadow_return_10",
    "incremental_return_10",
    "exit_open_date_20",
    "base_return_20",
    "shadow_return_20",
    "incremental_return_20",
)


@dataclass(frozen=True)
class ChainLinkedExtension:
    adjusted_new: pd.DataFrame
    primary_raw_new: pd.DataFrame
    provider_payload_sha256: str
    chain_scale: float
    anchor_provider_adjusted_close: float
    anchor_canonical_adjusted_close: float


@dataclass(frozen=True)
class IndependentAudit:
    row_audit: pd.DataFrame
    secondary_payload_sha256: str
    secondary_provider: str


def _normalise_dates(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy(deep=True)
    out["date"] = (
        pd.to_datetime(out["date"], errors="raise")
        .dt.tz_localize(None)
        .dt.normalize()
    )
    return out.sort_values("date").drop_duplicates("date", keep="last")


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def json_sha256(value: Any) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def chain_link_provider_history(
    baseline_adjusted: pd.DataFrame,
    provider_history: pd.DataFrame,
) -> ChainLinkedExtension:
    """Append provider data on the frozen adjusted-price basis.

    The provider may retrospectively rewrite its adjusted history. Only its
    relative post-anchor path is used: the response is rescaled so its adjusted
    close at 2026-08-03 exactly equals the immutable canonical close. Historical
    canonical rows are never replaced.
    """

    required = {"date", *PRICE_COLUMNS, "volume", "adj_close"}
    missing = sorted(required - set(provider_history.columns))
    if missing:
        raise ValueError(f"provider history missing columns: {missing}")
    baseline = _normalise_dates(baseline_adjusted)
    provider = _normalise_dates(provider_history)
    for column in (*PRICE_COLUMNS, "volume", "adj_close"):
        provider[column] = pd.to_numeric(provider[column], errors="raise").astype(float)
    provider_payload_sha = dataframe_sha256(
        provider[["date", *PRICE_COLUMNS, "volume", "adj_close"]]
    )

    baseline_anchor = baseline.loc[baseline["date"].eq(BASELINE_DATE)]
    provider_anchor = provider.loc[provider["date"].eq(BASELINE_DATE)]
    if len(baseline_anchor) != 1 or len(provider_anchor) != 1:
        raise RuntimeError("baseline and provider must each contain the frozen anchor")
    canonical_anchor_close = float(baseline_anchor.iloc[0]["close"])
    provider_anchor_adj = float(provider_anchor.iloc[0]["adj_close"])
    if canonical_anchor_close <= 0.0 or provider_anchor_adj <= 0.0:
        raise RuntimeError("invalid anchor adjusted close")
    chain_scale = canonical_anchor_close / provider_anchor_adj

    factor = provider["adj_close"] / provider["close"]
    if (~np.isfinite(factor) | factor.le(0.0)).any():
        raise RuntimeError("provider response contains invalid adjustment factors")
    adjusted = provider[["date", "volume"]].copy()
    for column in PRICE_COLUMNS:
        adjusted[column] = provider[column] * factor * chain_scale
    adjusted = adjusted[["date", *PRICE_COLUMNS, "volume"]]
    adjusted_new = adjusted.loc[adjusted["date"].gt(BASELINE_DATE)].copy()
    primary_raw_new = provider.loc[
        provider["date"].gt(BASELINE_DATE),
        ["date", *PRICE_COLUMNS, "volume"],
    ].copy()
    if not adjusted_new["date"].equals(primary_raw_new["date"]):
        raise AssertionError("raw and adjusted prospective rows are not aligned")
    return ChainLinkedExtension(
        adjusted_new=adjusted_new.reset_index(drop=True),
        primary_raw_new=primary_raw_new.reset_index(drop=True),
        provider_payload_sha256=provider_payload_sha,
        chain_scale=float(chain_scale),
        anchor_provider_adjusted_close=provider_anchor_adj,
        anchor_canonical_adjusted_close=canonical_anchor_close,
    )


def audit_independent_raw(
    primary_raw_new: pd.DataFrame,
    secondary_raw: pd.DataFrame,
    *,
    secondary_provider: str,
) -> IndependentAudit:
    """Confirm new raw rows without copying secondary values into primary data."""

    primary = _normalise_dates(primary_raw_new)
    secondary = _normalise_dates(secondary_raw)
    for frame in (primary, secondary):
        for column in (*PRICE_COLUMNS, "volume"):
            frame[column] = pd.to_numeric(frame[column], errors="raise").astype(float)
    secondary_sha = dataframe_sha256(
        secondary[["date", *PRICE_COLUMNS, "volume"]]
    )
    merged = primary.merge(
        secondary,
        on="date",
        how="left",
        suffixes=("_primary", "_secondary"),
        validate="one_to_one",
    )
    merged["open_level_abs_pct_difference"] = (
        merged["open_primary"] / merged["open_secondary"] - 1.0
    ).abs()
    merged["close_level_abs_pct_difference"] = (
        merged["close_primary"] / merged["close_secondary"] - 1.0
    ).abs()
    merged["independent_raw_confirmed"] = (
        merged["open_secondary"].notna()
        & merged["close_secondary"].notna()
        & merged["open_level_abs_pct_difference"].le(0.01)
        & merged["close_level_abs_pct_difference"].le(0.005)
    )
    merged["open_research_eligible"] = (
        merged["independent_raw_confirmed"]
        & merged["volume_primary"].gt(0.0)
        & merged["volume_secondary"].gt(0.0)
    )
    return IndependentAudit(
        row_audit=merged,
        secondary_payload_sha256=secondary_sha,
        secondary_provider=secondary_provider,
    )


def build_extended_inputs(
    baseline_adjusted: pd.DataFrame,
    baseline_sessions: pd.DataFrame,
    extension: ChainLinkedExtension,
    audit: IndependentAudit,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    baseline = _normalise_dates(baseline_adjusted)
    sessions = _normalise_dates(baseline_sessions)
    new_sessions = audit.row_audit[
        ["date", "open_research_eligible", "independent_raw_confirmed"]
    ].copy()
    new_sessions["volume"] = extension.primary_raw_new["volume"].to_numpy()
    extended = pd.concat(
        [baseline, extension.adjusted_new],
        ignore_index=True,
    ).sort_values("date")
    if extended["date"].duplicated().any():
        raise RuntimeError("prospective extension would overwrite a historical date")
    extended_sessions = pd.concat(
        [sessions, new_sessions],
        ignore_index=True,
        sort=False,
    ).sort_values("date")
    extended_sessions = extended_sessions.drop_duplicates("date", keep="first")
    if len(extended_sessions) != len(extended):
        raise RuntimeError("extended session audit does not align with adjusted rows")
    return extended.reset_index(drop=True), extended_sessions.reset_index(drop=True)


def _record_float(value: Any) -> float | None:
    number = float(value)
    return number if np.isfinite(number) else None


def make_signal_observations(
    extended_adjusted: pd.DataFrame,
    extended_sessions: pd.DataFrame,
    extension: ChainLinkedExtension,
    audit: IndependentAudit,
    *,
    observed_at_utc: str | None = None,
    primary_provider: str = "yfinance_unadjusted_plus_adj_close",
) -> tuple[list[dict[str, Any]], pd.DataFrame, pd.DataFrame]:
    dataset = build_research_dataset(extended_adjusted, extended_sessions)
    base_decision = build_v1_0_decision_position(dataset)
    conditions = branch_conditions(dataset)
    schedule = build_overlay_schedule(dataset, base_decision)
    extended_sha = dataframe_sha256(_normalise_dates(extended_adjusted))
    observed_at = observed_at_utc or datetime.now(timezone.utc).isoformat()
    audit_by_date = audit.row_audit.set_index("date")
    observations: list[dict[str, Any]] = []
    for date in extension.adjusted_new["date"]:
        timestamp = pd.Timestamp(date)
        row = dataset.loc[timestamp]
        audit_row = audit_by_date.loc[timestamp]
        observation: dict[str, Any] = {
            "schema_version": SHADOW_SCHEMA,
            "signal_date": timestamp.strftime("%Y-%m-%d"),
            "observed_at_utc": observed_at,
            "research_only": True,
            "trade_ready": False,
            "shadow_only": True,
            "base_snapshot_sha256": SNAPSHOT_SHA256,
            "base_adjusted_sha256": CANONICAL_ADJUSTED_SHA256,
            "base_manifest_sha256": CANONICAL_MANIFEST_SHA256,
            "provider_payload_sha256": extension.provider_payload_sha256,
            "secondary_payload_sha256": audit.secondary_payload_sha256,
            "extended_adjusted_sha256": extended_sha,
            "primary_provider": primary_provider,
            "secondary_provider": audit.secondary_provider,
            "chain_scale": extension.chain_scale,
            "anchor_provider_adjusted_close": (
                extension.anchor_provider_adjusted_close
            ),
            "anchor_canonical_adjusted_close": (
                extension.anchor_canonical_adjusted_close
            ),
            "open_research_eligible": bool(
                audit_row["open_research_eligible"]
            ),
            "independent_raw_confirmed": bool(
                audit_row["independent_raw_confirmed"]
            ),
            "base_target_position": float(base_decision.loc[timestamp]),
            "shadow_overlay_active": bool(
                schedule.overlay_active.loc[timestamp]
            ),
            "shadow_overlay_branch": str(
                schedule.overlay_branch.loc[timestamp]
            ),
            "shadow_target_position": float(
                schedule.final_decision_position.loc[timestamp]
            ),
            "branch_a_condition": bool(
                conditions.loc[timestamp, "bear_sideways_low_vol"]
            ),
            "branch_b_condition": bool(
                conditions.loc[timestamp, "bull_high_vol"]
            ),
            "factors": {
                "drawdown_252": _record_float(row["drawdown_252"]),
                "distance_from_low_20": _record_float(
                    row["distance_from_low_20"]
                ),
                "momentum_accel_20_60": _record_float(
                    row["momentum_accel_20_60"]
                ),
                "open_return_autocorr_20": _record_float(
                    row["open_return_autocorr_20"]
                ),
                "market_state": str(row["market_state"]),
                "vol_state": str(row["vol_state"]),
            },
            "status": (
                "prospective_shadow_observation"
                if bool(audit_row["open_research_eligible"])
                else "prospective_observation_open_quarantined"
            ),
        }
        observation["data_version"] = (
            f"byd-shadow-{observation['signal_date']}-"
            f"{extended_sha[:12]}"
        )
        observations.append(observation)
    return observations, dataset, schedule.final_decision_position


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


def _eligible_dates_after(dataset: pd.DataFrame, signal_date: pd.Timestamp) -> list[pd.Timestamp]:
    mask = (dataset.index > signal_date) & dataset["open_research_eligible"].astype(bool)
    return list(dataset.index[mask])


def mature_outcomes(
    observations: Iterable[dict[str, Any]],
    dataset: pd.DataFrame,
    shadow_decision: pd.Series,
    *,
    primary_cost_bps: float = 20.0,
) -> list[dict[str, Any]]:
    base_decision = build_v1_0_decision_position(dataset)
    base_result = run_strategy(
        dataset,
        base_decision,
        name="canonical_v1_0_prospective",
        cost_bps_per_turnover_unit=primary_cost_bps,
    )
    shadow_result = run_strategy(
        dataset,
        shadow_decision,
        name="rejected_v1_3_shadow",
        cost_bps_per_turnover_unit=primary_cost_bps,
    )
    outcomes: list[dict[str, Any]] = []
    for observation in observations:
        signal_date = pd.Timestamp(observation["signal_date"])
        eligible = _eligible_dates_after(dataset, signal_date)
        for horizon in HORIZONS:
            if len(eligible) <= horizon:
                continue
            entry = eligible[0]
            exit_ = eligible[horizon]
            base_block = base_result.daily.loc[
                (base_result.daily.index >= entry)
                & (base_result.daily.index < exit_)
            ]
            shadow_block = shadow_result.daily.reindex(base_block.index)
            base_return = float((1.0 + base_block["net_return"]).prod() - 1.0)
            shadow_return = float(
                (1.0 + shadow_block["net_return"]).prod() - 1.0
            )
            outcome = {
                "schema_version": SHADOW_SCHEMA,
                "signal_date": observation["signal_date"],
                "horizon_eligible_opens": horizon,
                "entry_open_date": entry.strftime("%Y-%m-%d"),
                "exit_open_date": exit_.strftime("%Y-%m-%d"),
                "base_return": base_return,
                "shadow_return": shadow_return,
                "incremental_return": (
                    (1.0 + shadow_return) / (1.0 + base_return) - 1.0
                ),
                "cost_bps_per_turnover_unit": primary_cost_bps,
                "base_snapshot_sha256": SNAPSHOT_SHA256,
                "observation_data_version": observation["data_version"],
                "research_only": True,
                "shadow_only": True,
            }
            outcomes.append(outcome)
    return outcomes


def _read_records(directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        records.append(json.loads(path.read_text(encoding="utf-8")))
    return records


def _derived_ledger(
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
        factors = observation["factors"]
        row: dict[str, Any] = {
            "signal_date": signal_date,
            "observed_at_utc": observation["observed_at_utc"],
            "observation_sha256": observation_hashes[signal_date],
            "data_version": observation["data_version"],
            "provider_payload_sha256": observation["provider_payload_sha256"],
            "secondary_payload_sha256": observation["secondary_payload_sha256"],
            "extended_adjusted_sha256": observation["extended_adjusted_sha256"],
            "primary_provider": observation["primary_provider"],
            "secondary_provider": observation["secondary_provider"],
            "open_research_eligible": observation["open_research_eligible"],
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
            row[f"base_return_{horizon}"] = (
                outcome["base_return"] if outcome else np.nan
            )
            row[f"shadow_return_{horizon}"] = (
                outcome["shadow_return"] if outcome else np.nan
            )
            row[f"incremental_return_{horizon}"] = (
                outcome["incremental_return"] if outcome else np.nan
            )
            if outcome and not row["entry_open_date"]:
                row["entry_open_date"] = outcome["entry_open_date"]
        rows.append(row)
    return pd.DataFrame(rows, columns=LEDGER_COLUMNS)


def persist_shadow_store(
    store_root: str | Path,
    new_observations: Iterable[dict[str, Any]],
    dataset: pd.DataFrame,
    shadow_decision: pd.Series,
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
    matured = mature_outcomes(observations, dataset, shadow_decision)
    for outcome in matured:
        path = outcome_dir / (
            f"{outcome['signal_date']}-h{int(outcome['horizon_eligible_opens']):02d}.json"
        )
        _atomic_json_record(path, outcome)

    observations = _read_records(observation_dir)
    outcomes = _read_records(outcome_dir)
    observation_hashes = {
        row["signal_date"]: file_sha256(
            observation_dir / f"{row['signal_date']}.json"
        )
        for row in observations
    }
    ledger = _derived_ledger(observations, outcomes, observation_hashes)
    ledger_path = root / "ledger.csv"
    ledger.to_csv(
        ledger_path,
        index=False,
        float_format="%.12f",
        lineterminator="\n",
    )
    manifest = {
        "schema_version": SHADOW_SCHEMA,
        "research_only": True,
        "trade_ready": False,
        "shadow_only": True,
        "base_snapshot_sha256": SNAPSHOT_SHA256,
        "base_adjusted_sha256": CANONICAL_ADJUSTED_SHA256,
        "base_manifest_sha256": CANONICAL_MANIFEST_SHA256,
        "baseline_cutoff": CANONICAL_CUTOFF,
        "observation_count": len(observations),
        "outcome_count": len(outcomes),
        "first_signal_date": (
            observations[0]["signal_date"] if observations else None
        ),
        "last_signal_date": (
            observations[-1]["signal_date"] if observations else None
        ),
        "observation_sha256": observation_hashes,
        "ledger_sha256": file_sha256(ledger_path),
        "append_only": True,
        "provider_history_may_not_overwrite_existing_observations": True,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
