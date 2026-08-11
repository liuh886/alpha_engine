"""Append-only prospective shadow for the frozen BYD v1.3 low-vol recovery route.

This layer consumes the immutable recovery-event prospective stream. It does
not fetch data or recompute the recovery detector. Its only new mechanism is
same-edge low-vol confirmation plus its own frozen 20-session lifecycle.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from src.research.byd_prospective_shadow import file_sha256
from src.research.byd_v1_2_trend_expansion import FINANCING_DAY_COUNT

SCHEMA_VERSION = "byd_v1_3_low_vol_prospective_v1"
SOURCE_SCHEMA_VERSION = "byd_recovery_event_prospective_v1"
CANDIDATE_MODEL_ID = "byd_v1_3_recovery_event_low_vol_confirmation_v1"
CHAMPION_MODEL_ID = "byd_v1_2_convex_momentum_budget_v1"
EVENT_MODEL_ID = "byd_recovery_event_hold20_v1"
LAUNCH_AFTER = pd.Timestamp("2026-08-10")
RECOVERY_THRESHOLD = 0.026937
HOLD_ELIGIBLE_SESSIONS = 20
ASSETS = ("byd", "etf", "cash")
STRATEGIES = (CHAMPION_MODEL_ID, EVENT_MODEL_ID, CANDIDATE_MODEL_ID)
SCENARIOS: dict[str, dict[str, float]] = {
    "primary": {"cost_bps": 20.0, "annual_financing_rate": 0.06},
    "stress": {"cost_bps": 40.0, "annual_financing_rate": 0.10},
}
EPS = 1e-12


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _atomic_json(path: Path, value: dict[str, Any]) -> str:
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
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))
    ]


def source_records(store_root: str | Path) -> list[dict[str, Any]]:
    root = Path(store_root) / "observations"
    records = _read_records(root)
    for record in records:
        if record.get("schema_version") != SOURCE_SCHEMA_VERSION:
            raise RuntimeError("low-vol shadow source schema changed")
        path = root / f"{record['signal_date']}.json"
        record["source_sha256"] = file_sha256(path)
    return sorted(records, key=lambda row: str(row["signal_date"]))


def build_lifecycle(source: Iterable[dict[str, Any]]) -> pd.DataFrame:
    """Build the frozen low-vol lifecycle from immutable event observations."""

    ordered = sorted(source, key=lambda row: str(row["signal_date"]))
    active = False
    remaining = 0
    lifecycle_id = 0
    prior_overlay = False
    rows: list[dict[str, Any]] = []

    for record in ordered:
        date = pd.Timestamp(str(record["signal_date"])).normalize()
        common_eligible = bool(record["common_open_eligible"])
        base_target = float(record["champion"]["base_byd_weight"])
        vol_state = str(record["factors"]["vol_state"])
        edge = bool(record["detector"]["event_edge"])
        prospective = bool(record.get("prospective_eligible", False))

        termination = ""
        if prior_overlay and common_eligible:
            remaining -= 1
            if remaining <= 0:
                active = False
                remaining = 0
                termination = "max_hold"

        if active and base_target >= 1.0 - EPS:
            active = False
            remaining = 0
            termination = "core_recovered"

        low_vol_edge = edge and vol_state == "low"
        started = False
        if (
            not active
            and date > LAUNCH_AFTER
            and prospective
            and low_vol_edge
            and np.isclose(base_target, 0.75)
        ):
            active = True
            remaining = HOLD_ELIGIBLE_SESSIONS
            lifecycle_id += 1
            started = True

        overlay = active and np.isclose(base_target, 0.75)
        rows.append(
            {
                "date": date,
                "event_edge": edge,
                "low_vol_confirmed_edge": low_vol_edge,
                "entry_vol_state": vol_state,
                "lifecycle_started": started,
                "lifecycle_id": lifecycle_id if overlay else 0,
                "overlay_decision_active": overlay,
                "remaining_eligible_sessions": remaining if overlay else 0,
                "termination_on_decision": termination,
            }
        )
        prior_overlay = overlay

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("date").sort_index()


def _candidate_target(champion: dict[str, Any], overlay: bool) -> dict[str, float]:
    if overlay:
        return {"byd_weight": 1.0, "etf_weight": 0.0, "cash_weight": 0.0}
    return {f"{asset}_weight": float(champion[f"{asset}_weight"]) for asset in ASSETS}


def build_observations(
    *,
    source_store: str | Path,
    existing_records: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    source = source_records(source_store)
    lifecycle = build_lifecycle(source)
    existing = {
        str(row["signal_date"]): row
        for row in sorted(existing_records, key=lambda value: value["signal_date"])
    }
    output: list[dict[str, Any]] = []

    for source_row in source:
        signal_date = str(source_row["signal_date"])
        date = pd.Timestamp(signal_date).normalize()
        if date < LAUNCH_AFTER:
            continue
        state = lifecycle.loc[date]
        champion_target = source_row["targets"][CHAMPION_MODEL_ID]
        event_target = source_row["targets"][EVENT_MODEL_ID]
        candidate_target = _candidate_target(
            champion_target,
            bool(state["overlay_decision_active"]),
        )
        prospective = bool(source_row.get("prospective_eligible", False)) and (date > LAUNCH_AFTER)
        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "kind": "v1_3_low_vol_recovery_observation",
            "signal_date": signal_date,
            "observed_at_utc": source_row["observed_at_utc"],
            "launch_after": LAUNCH_AFTER.strftime("%Y-%m-%d"),
            "prelaunch_seed": date == LAUNCH_AFTER,
            "common_open_eligible": bool(source_row["common_open_eligible"]),
            "prospective_eligible": prospective,
            "source": {
                "recovery_event_observation_sha256": source_row["source_sha256"],
                "recovery_event_data_version": source_row["data_version"],
                "recovery_event_schema_version": source_row["schema_version"],
            },
            "detector": {
                "threshold": float(source_row["detector"]["threshold"]),
                "drawdown252_x_rebound60": float(source_row["detector"]["drawdown252_x_rebound60"]),
                "active": bool(source_row["detector"]["active"]),
                "event_edge": bool(source_row["detector"]["event_edge"]),
            },
            "entry_confirmation": {
                "required_vol_state": "low",
                "observed_vol_state": str(source_row["factors"]["vol_state"]),
                "passed_on_edge": bool(state["low_vol_confirmed_edge"]),
                "catch_up_allowed": False,
            },
            "lifecycle": {
                "hold_eligible_sessions": HOLD_ELIGIBLE_SESSIONS,
                "started": bool(state["lifecycle_started"]),
                "id": int(state["lifecycle_id"]),
                "overlay_decision_active": bool(state["overlay_decision_active"]),
                "remaining_eligible_sessions": int(state["remaining_eligible_sessions"]),
                "termination_on_decision": str(state["termination_on_decision"]),
            },
            "champion": dict(source_row["champion"]),
            "factors": dict(source_row["factors"]),
            "prices": dict(source_row["prices"]),
            "targets": {
                CHAMPION_MODEL_ID: {key: float(value) for key, value in champion_target.items()},
                EVENT_MODEL_ID: {key: float(value) for key, value in event_target.items()},
                CANDIDATE_MODEL_ID: candidate_target,
            },
            "cost_contract": SCENARIOS,
            "research_only": True,
            "trade_ready": False,
            "shadow_only": True,
            "automatic_promotion_allowed": False,
            "status": (
                "prelaunch_seed"
                if date == LAUNCH_AFTER
                else "prospective_low_vol_lifecycle_active"
                if prospective and bool(state["overlay_decision_active"])
                else "prospective_observation"
                if prospective
                else "non_prospective_source_observation"
            ),
        }
        record["data_version"] = f"byd-v1-3-low-vol-{signal_date}-{source_row['source_sha256'][:8]}"
        if signal_date in existing:
            if _json_bytes(existing[signal_date]) != _json_bytes(record):
                raise RuntimeError(f"existing low-vol observation drifted: {signal_date}")
            continue
        output.append(record)
    return output


def _frame(records: Iterable[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in sorted(records, key=lambda row: row["signal_date"]):
        item: dict[str, Any] = {
            "date": pd.Timestamp(record["signal_date"]),
            "common_open_eligible": bool(record["common_open_eligible"]),
            "prospective_eligible": bool(record["prospective_eligible"]),
            "lifecycle_started": bool(record["lifecycle"]["started"]),
            "overlay_decision_active": bool(record["lifecycle"]["overlay_decision_active"]),
            "market_state": str(record["factors"]["market_state"]),
            "byd_open": float(record["prices"]["byd_open"]),
            "etf_open": float(record["prices"]["etf_open"]),
        }
        for strategy in STRATEGIES:
            for asset in ASSETS:
                item[f"{strategy}_{asset}_weight"] = float(
                    record["targets"][strategy][f"{asset}_weight"]
                )
        rows.append(item)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("date").sort_index()


def _execute(frame: pd.DataFrame, strategy: str) -> pd.DataFrame:
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy}")
    current = pd.Series({"byd": 0.0, "etf": 0.0, "cash": 1.0})
    rows: list[dict[str, float]] = []
    for position, (_, row) in enumerate(frame.iterrows()):
        if position > 0 and bool(row["common_open_eligible"]):
            previous = frame.iloc[position - 1]
            current = pd.Series(
                {asset: float(previous[f"{strategy}_{asset}_weight"]) for asset in ASSETS}
            )
        rows.append({f"position_{asset}_weight": float(current[asset]) for asset in ASSETS})
    return pd.DataFrame(rows, index=frame.index)


def strategy_daily(
    frame: pd.DataFrame,
    strategy: str,
    *,
    cost_bps: float,
    annual_financing_rate: float,
) -> pd.DataFrame:
    if len(frame) < 2:
        return pd.DataFrame()
    executed = _execute(frame, strategy)
    byd_return = frame["byd_open"].shift(-1) / frame["byd_open"] - 1.0
    etf_return = frame["etf_open"].shift(-1) / frame["etf_open"] - 1.0
    gross = (
        executed["position_byd_weight"] * byd_return + executed["position_etf_weight"] * etf_return
    )
    turnover = executed.diff().abs().sum(axis=1)
    turnover.iloc[0] = 0.0
    transaction_cost = turnover * float(cost_bps) / 10_000.0
    borrowed = (-executed["position_cash_weight"]).clip(lower=0.0)
    financing = borrowed * float(annual_financing_rate) / FINANCING_DAY_COUNT
    output = executed.copy()
    output["gross_return"] = gross
    output["turnover_units"] = turnover
    output["transaction_cost"] = transaction_cost
    output["borrowed_weight"] = borrowed
    output["financing_cost"] = financing
    output["net_return"] = gross - transaction_cost - financing
    return output.iloc[:-1].copy()


def _episode_table(active: pd.Series) -> pd.DataFrame:
    state = active.fillna(False).astype(bool)
    starts = state & ~state.shift(1, fill_value=False)
    ids = starts.cumsum().where(state)
    rows: list[dict[str, Any]] = []
    for raw_id, block in state.groupby(ids):
        if pd.isna(raw_id):
            continue
        rows.append(
            {
                "episode_id": int(raw_id),
                "start": block.index.min(),
                "end": block.index.max(),
                "sessions": int(len(block)),
            }
        )
    return pd.DataFrame(rows)


def _relative_wealth(candidate: pd.DataFrame, baseline: pd.DataFrame) -> float:
    if candidate.empty or baseline.empty:
        return 0.0
    common = candidate.index.intersection(baseline.index)
    candidate_wealth = float((1.0 + candidate.loc[common, "net_return"]).prod())
    baseline_wealth = float((1.0 + baseline.loc[common, "net_return"]).prod())
    return candidate_wealth / baseline_wealth - 1.0


def mature_lifecycle_outcomes(
    records: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    ordered = sorted(records, key=lambda row: row["signal_date"])
    frame = _frame(ordered)
    if len(frame) < 2:
        return []
    daily = {
        scenario: {
            strategy: strategy_daily(
                frame,
                strategy,
                cost_bps=float(contract["cost_bps"]),
                annual_financing_rate=float(contract["annual_financing_rate"]),
            )
            for strategy in STRATEGIES
        }
        for scenario, contract in SCENARIOS.items()
    }
    primary = daily["primary"]
    executed_overlay = primary[CANDIDATE_MODEL_ID]["position_byd_weight"].gt(
        primary[CHAMPION_MODEL_ID]["position_byd_weight"] + EPS
    )
    episodes = _episode_table(executed_overlay)
    outcomes: list[dict[str, Any]] = []
    for episode in episodes.itertuples(index=False):
        later = executed_overlay.index[executed_overlay.index > episode.end]
        if len(later) == 0 or bool(executed_overlay.loc[later[0]]):
            continue
        scenarios: dict[str, Any] = {}
        for scenario in SCENARIOS:
            blocks = {
                strategy: daily[scenario][strategy].loc[episode.start : episode.end]
                for strategy in STRATEGIES
            }
            scenarios[scenario] = {
                "candidate_vs_champion_relative_terminal_wealth": _relative_wealth(
                    blocks[CANDIDATE_MODEL_ID], blocks[CHAMPION_MODEL_ID]
                ),
                "candidate_vs_event_relative_terminal_wealth": _relative_wealth(
                    blocks[CANDIDATE_MODEL_ID], blocks[EVENT_MODEL_ID]
                ),
                **SCENARIOS[scenario],
            }
        source_rows = [
            record
            for record in ordered
            if pd.Timestamp(episode.start)
            <= pd.Timestamp(record["signal_date"])
            <= pd.Timestamp(episode.end)
        ]
        outcomes.append(
            {
                "schema_version": SCHEMA_VERSION,
                "kind": "v1_3_low_vol_lifecycle_outcome",
                "episode_id": int(episode.episode_id),
                "start_open_date": pd.Timestamp(episode.start).strftime("%Y-%m-%d"),
                "end_open_date": pd.Timestamp(episode.end).strftime("%Y-%m-%d"),
                "executed_sessions": int(episode.sessions),
                "scenarios": scenarios,
                "settlement_input_sha256": hashlib.sha256(
                    b"".join(_json_bytes(row) + b"\n" for row in source_rows)
                ).hexdigest(),
                "research_only": True,
                "trade_ready": False,
                "shadow_only": True,
            }
        )
    return outcomes


def _positive_concentration(values: Iterable[float]) -> float:
    positive = [max(float(value), 0.0) for value in values]
    total = sum(positive)
    return max(positive) / total if positive and total > 0.0 else 0.0


def build_scorecard(
    records: Iterable[dict[str, Any]], outcomes: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    ordered = sorted(records, key=lambda row: row["signal_date"])
    outcome_rows = list(outcomes)
    frame = _frame(ordered)
    prospective = [row for row in ordered if bool(row["prospective_eligible"])]
    first = pd.Timestamp(prospective[0]["signal_date"]) if prospective else None
    last = pd.Timestamp(prospective[-1]["signal_date"]) if prospective else None
    prospective_days = int((last - first).days) if first is not None else 0

    scenario_summary: dict[str, Any] = {}
    primary_daily: dict[str, pd.DataFrame] | None = None
    for scenario, contract in SCENARIOS.items():
        if len(frame) < 2:
            scenario_summary[scenario] = {
                "candidate_vs_champion_relative_terminal_wealth": 0.0,
                "candidate_vs_event_relative_terminal_wealth": 0.0,
                **contract,
            }
            continue
        daily = {
            strategy: strategy_daily(
                frame,
                strategy,
                cost_bps=float(contract["cost_bps"]),
                annual_financing_rate=float(contract["annual_financing_rate"]),
            )
            for strategy in STRATEGIES
        }
        after_launch = daily[CANDIDATE_MODEL_ID].index[
            daily[CANDIDATE_MODEL_ID].index > LAUNCH_AFTER
        ]
        blocks = {strategy: daily[strategy].loc[after_launch] for strategy in STRATEGIES}
        scenario_summary[scenario] = {
            "candidate_vs_champion_relative_terminal_wealth": _relative_wealth(
                blocks[CANDIDATE_MODEL_ID], blocks[CHAMPION_MODEL_ID]
            ),
            "candidate_vs_event_relative_terminal_wealth": _relative_wealth(
                blocks[CANDIDATE_MODEL_ID], blocks[EVENT_MODEL_ID]
            ),
            **contract,
        }
        if scenario == "primary":
            primary_daily = daily

    completed = [row for row in outcome_rows if row["kind"] == "v1_3_low_vol_lifecycle_outcome"]
    lifecycle_returns = [
        float(row["scenarios"]["primary"]["candidate_vs_champion_relative_terminal_wealth"])
        for row in completed
    ]
    event_states = sorted(
        {
            str(row["factors"]["market_state"])
            for row in prospective
            if bool(row["lifecycle"]["started"])
        }
    )
    quarter_values: list[float] = []
    if primary_daily is not None and len(frame) >= 2:
        candidate = primary_daily[CANDIDATE_MODEL_ID]
        champion = primary_daily[CHAMPION_MODEL_ID]
        common = candidate.index.intersection(champion.index)
        relative = (1.0 + candidate.loc[common, "net_return"]) / (
            1.0 + champion.loc[common, "net_return"]
        ) - 1.0
        relative = relative.loc[relative.index > LAUNCH_AFTER]
        if not relative.empty:
            quarter_values = [
                float((1.0 + block).prod() - 1.0)
                for _, block in relative.groupby(relative.index.to_period("Q"))
            ]

    gates = {
        "forward_time_12_months": prospective_days >= 365,
        "completed_10_low_vol_lifecycles": len(completed) >= 10,
        "at_least_2_event_market_states": len(event_states) >= 2,
        "primary_relative_wealth_vs_champion_positive": scenario_summary["primary"][
            "candidate_vs_champion_relative_terminal_wealth"
        ]
        > 0.0,
        "primary_relative_wealth_vs_event_nonnegative": scenario_summary["primary"][
            "candidate_vs_event_relative_terminal_wealth"
        ]
        >= 0.0,
        "stress_relative_wealth_vs_champion_nonnegative": scenario_summary["stress"][
            "candidate_vs_champion_relative_terminal_wealth"
        ]
        >= 0.0,
        "largest_positive_lifecycle_share_le_40pct": (
            _positive_concentration(lifecycle_returns) <= 0.40 and len(completed) > 0
        ),
        "largest_positive_quarter_share_le_60pct": (
            _positive_concentration(quarter_values) <= 0.60 and len(quarter_values) > 0
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": (
            "prospective_monitoring" if prospective else "awaiting_first_prospective_observation"
        ),
        "launch_after": LAUNCH_AFTER.strftime("%Y-%m-%d"),
        "first_prospective_signal_date": (
            first.strftime("%Y-%m-%d") if first is not None else None
        ),
        "last_prospective_signal_date": (last.strftime("%Y-%m-%d") if last is not None else None),
        "prospective_days": prospective_days,
        "observation_count": len(ordered),
        "prospective_observation_count": len(prospective),
        "completed_low_vol_lifecycle_count": len(completed),
        "event_market_states": event_states,
        "scenarios": scenario_summary,
        "largest_positive_lifecycle_share": _positive_concentration(lifecycle_returns),
        "largest_positive_quarter_share": _positive_concentration(quarter_values),
        "gates": gates,
        "all_observation_gates_passed": all(gates.values()),
        "automatic_promotion_allowed": False,
        "research_only": True,
        "trade_ready": False,
        "shadow_only": True,
    }


def persist_store(
    store_root: str | Path, new_observations: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    root = Path(store_root)
    observation_dir = root / "observations"
    outcome_dir = root / "outcomes"
    for record in new_observations:
        _atomic_json(observation_dir / f"{record['signal_date']}.json", record)
    observations = _read_records(observation_dir)
    if any(row.get("schema_version") != SCHEMA_VERSION for row in observations):
        raise RuntimeError("low-vol store contains an incompatible observation")

    outcomes = mature_lifecycle_outcomes(observations)
    for outcome in outcomes:
        name = f"episode-{outcome['start_open_date']}-{outcome['end_open_date']}.json"
        _atomic_json(outcome_dir / name, outcome)
    persisted_outcomes = _read_records(outcome_dir)
    scorecard = build_scorecard(observations, persisted_outcomes)

    ledger_rows: list[dict[str, Any]] = []
    for record in observations:
        ledger_rows.append(
            {
                "signal_date": record["signal_date"],
                "observation_sha256": file_sha256(
                    observation_dir / f"{record['signal_date']}.json"
                ),
                "source_observation_sha256": record["source"]["recovery_event_observation_sha256"],
                "prelaunch_seed": record["prelaunch_seed"],
                "prospective_eligible": record["prospective_eligible"],
                "common_open_eligible": record["common_open_eligible"],
                "event_edge": record["detector"]["event_edge"],
                "vol_state": record["entry_confirmation"]["observed_vol_state"],
                "low_vol_confirmed_edge": record["entry_confirmation"]["passed_on_edge"],
                "lifecycle_started": record["lifecycle"]["started"],
                "lifecycle_id": record["lifecycle"]["id"],
                "overlay_decision_active": record["lifecycle"]["overlay_decision_active"],
                "remaining_eligible_sessions": record["lifecycle"]["remaining_eligible_sessions"],
                "market_state": record["factors"]["market_state"],
            }
        )
    ledger = pd.DataFrame(ledger_rows)
    root.mkdir(parents=True, exist_ok=True)
    ledger_path = root / "ledger.csv"
    ledger.to_csv(
        ledger_path,
        index=False,
        float_format="%.12f",
        lineterminator="\n",
    )
    scorecard_path = root / "scorecard.json"
    scorecard_path.write_text(
        json.dumps(scorecard, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    observation_hashes = {
        row["signal_date"]: file_sha256(observation_dir / f"{row['signal_date']}.json")
        for row in observations
    }
    source_hashes = {
        row["signal_date"]: row["source"]["recovery_event_observation_sha256"]
        for row in observations
    }
    outcome_hashes = (
        {path.name: file_sha256(path) for path in sorted(outcome_dir.glob("*.json"))}
        if outcome_dir.exists()
        else {}
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "candidate_model_id": CANDIDATE_MODEL_ID,
        "champion_model_id": CHAMPION_MODEL_ID,
        "event_comparator_model_id": EVENT_MODEL_ID,
        "launch_after": LAUNCH_AFTER.strftime("%Y-%m-%d"),
        "detector_threshold": RECOVERY_THRESHOLD,
        "required_entry_vol_state": "low",
        "hold_common_open_eligible_sessions": HOLD_ELIGIBLE_SESSIONS,
        "research_only": True,
        "trade_ready": False,
        "shadow_only": True,
        "append_only": True,
        "automatic_promotion_allowed": False,
        "historical_retuning_allowed": False,
        "provider_fallback": False,
        "observation_count": len(observations),
        "prospective_observation_count": sum(
            bool(row["prospective_eligible"]) for row in observations
        ),
        "outcome_count": len(persisted_outcomes),
        "first_signal_date": observations[0]["signal_date"] if observations else None,
        "last_signal_date": observations[-1]["signal_date"] if observations else None,
        "observation_sha256": observation_hashes,
        "source_observation_sha256": source_hashes,
        "outcome_sha256": outcome_hashes,
        "ledger_sha256": file_sha256(ledger_path),
        "scorecard_sha256": file_sha256(scorecard_path),
        "source_store": "data/research/byd_recovery_event_prospective",
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
