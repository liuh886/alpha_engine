"""Prospective shadow evidence for the frozen BYD recovery event lifecycle.

The module consumes only the existing immutable BYD and BYD/515180 paired
stores. It does not fetch market data. The accepted V1.2 convex-momentum path
is the Champion; the frozen recovery event lifecycle is shadow-only.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from src.research.byd_prospective_shadow import file_sha256
from src.research.byd_v1_2_convex_momentum import (
    CANDIDATE as CHAMPION_MODEL_ID,
    MAX_FINANCED_INCREMENT,
    momentum_scale,
)
from src.research.byd_v1_2_recovery_state import build_v1_0_decision_position
from src.research.byd_v1_2_trend_expansion import (
    FINANCING_DAY_COUNT,
    PRIMARY_FINANCING_RATE,
    STRESS_FINANCING_RATE,
    build_expansion_state,
)
from src.research.byd_v1_2_trend_expansion_prospective import (
    rebuild_byd_dataset,
    source_records,
)

SCHEMA_VERSION = "byd_recovery_event_prospective_v1"
CANDIDATE_MODEL_ID = "byd_recovery_event_hold20_v1"
LAUNCH_AFTER = pd.Timestamp("2026-08-10")
RECOVERY_THRESHOLD = 0.026937
HOLD_ELIGIBLE_SESSIONS = 20
ASSETS = ("byd", "etf", "cash")
STRATEGIES = (CHAMPION_MODEL_ID, CANDIDATE_MODEL_ID)
SCENARIOS: dict[str, dict[str, float]] = {
    "primary": {
        "cost_bps": 20.0,
        "annual_financing_rate": PRIMARY_FINANCING_RATE,
    },
    "stress": {
        "cost_bps": 40.0,
        "annual_financing_rate": STRESS_FINANCING_RATE,
    },
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
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
    ]


def build_champion_targets(
    dataset: pd.DataFrame,
    base_target: pd.Series,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Reproduce the accepted V1.2 convex-momentum decision path."""

    if not dataset.index.equals(base_target.index):
        raise ValueError("dataset and base target indices must match")
    signals = pd.DataFrame(
        {"base_byd_weight": base_target.astype(float)},
        index=dataset.index,
    )
    expansion = build_expansion_state(dataset, signals)
    active = expansion["trend_expansion_active"].astype(bool)
    raw_scale = momentum_scale(dataset["mom_20"])
    if raw_scale.loc[active].isna().any():
        raise AssertionError("active V1.2 expansion is missing its momentum scale")
    scale = raw_scale.fillna(0.0)
    increment = active.astype(float) * MAX_FINANCED_INCREMENT * scale
    byd = base_target.astype(float) + increment
    etf = (1.0 - base_target.astype(float)).where(increment.eq(0.0), 0.0)
    cash = 1.0 - byd - etf
    targets = pd.DataFrame(
        {"byd_weight": byd, "etf_weight": etf, "cash_weight": cash},
        index=dataset.index,
    )
    if (targets["byd_weight"] < -EPS).any() or (targets["etf_weight"] < -EPS).any():
        raise AssertionError("V1.2 Champion target has negative risky-asset weight")
    if not np.allclose(targets.sum(axis=1), 1.0, atol=1e-12):
        raise AssertionError("V1.2 Champion weights do not sum to one")
    diagnostics = expansion.copy()
    diagnostics["momentum_scale"] = scale
    diagnostics["financed_increment"] = increment
    return targets, diagnostics


def build_event_lifecycle_schedule(
    *,
    index: pd.DatetimeIndex,
    base_target: pd.Series,
    detector: pd.Series,
    common_open_eligible: pd.Series,
    prospective_eligible: pd.Series,
) -> pd.DataFrame:
    """Build the frozen event clock using only information known by each close.

    The remaining-session counter advances at the current open when the prior
    decision carried the overlay and that open was common-eligible. Therefore
    an immutable decision record never changes when a future row arrives.
    """

    for series in (
        base_target,
        detector,
        common_open_eligible,
        prospective_eligible,
    ):
        if not series.index.equals(index):
            raise ValueError("event lifecycle inputs must share one index")

    edge = detector.astype(bool) & ~detector.astype(bool).shift(1, fill_value=False)
    active = False
    remaining = 0
    lifecycle_id = 0
    prior_overlay_decision = False
    rows: list[dict[str, Any]] = []

    for date in index:
        termination = ""
        if prior_overlay_decision and bool(common_open_eligible.loc[date]):
            remaining -= 1
            if remaining <= 0:
                active = False
                remaining = 0
                termination = "max_hold"

        if active and float(base_target.loc[date]) >= 1.0 - EPS:
            active = False
            remaining = 0
            termination = "core_recovered"

        started = False
        launch_eligible = date > LAUNCH_AFTER
        if (
            not active
            and launch_eligible
            and bool(edge.loc[date])
            and bool(prospective_eligible.loc[date])
            and np.isclose(float(base_target.loc[date]), 0.75)
        ):
            active = True
            remaining = HOLD_ELIGIBLE_SESSIONS
            lifecycle_id += 1
            started = True

        overlay = active and np.isclose(float(base_target.loc[date]), 0.75)
        rows.append(
            {
                "detector": bool(detector.loc[date]),
                "event_edge": bool(edge.loc[date]),
                "launch_eligible": launch_eligible,
                "lifecycle_started": started,
                "lifecycle_id": lifecycle_id if overlay else 0,
                "overlay_decision_active": overlay,
                "remaining_eligible_sessions": remaining if overlay else 0,
                "termination_on_decision": termination,
            }
        )
        prior_overlay_decision = overlay

    return pd.DataFrame(rows, index=index)


def _candidate_target(
    champion_target: pd.Series,
    overlay_active: bool,
) -> dict[str, float]:
    if overlay_active:
        return {"byd_weight": 1.0, "etf_weight": 0.0, "cash_weight": 0.0}
    return {
        f"{asset}_weight": float(champion_target[f"{asset}_weight"])
        for asset in ASSETS
    }


def build_observations(
    *,
    baseline_dir: str | Path,
    byd_store: str | Path,
    paired_store: str | Path,
    existing_records: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Rebuild the complete frozen path and append only unseen source dates."""

    byd = source_records(byd_store)
    paired = source_records(paired_store)
    byd_by_date = {str(row["signal_date"]): row for row in byd}
    paired_by_date = {str(row["signal_date"]): row for row in paired}
    common_dates = sorted(set(byd_by_date) & set(paired_by_date))
    dataset = rebuild_byd_dataset(baseline_dir, byd)
    base = build_v1_0_decision_position(dataset)
    champion_targets, champion_diag = build_champion_targets(dataset, base)
    detector = (
        base.eq(0.75)
        & dataset["drawdown252_x_rebound60"].ge(RECOVERY_THRESHOLD)
    ).astype(bool)

    eligible_dates = [
        date for date in common_dates if pd.Timestamp(date) >= LAUNCH_AFTER
    ]
    if not eligible_dates:
        return []
    index = pd.DatetimeIndex(pd.to_datetime(eligible_dates)).normalize()
    common_eligible = pd.Series(
        [bool(paired_by_date[date]["common_open_eligible"]) for date in eligible_dates],
        index=index,
        dtype=bool,
    )
    prospective = pd.Series(
        [
            bool(byd_by_date[date].get("prospective_eligible", False))
            and bool(paired_by_date[date].get("prospective_eligible", False))
            and pd.Timestamp(date) > LAUNCH_AFTER
            for date in eligible_dates
        ],
        index=index,
        dtype=bool,
    )
    lifecycle = build_event_lifecycle_schedule(
        index=index,
        base_target=base.reindex(index),
        detector=detector.reindex(index),
        common_open_eligible=common_eligible,
        prospective_eligible=prospective,
    )
    existing = {
        str(row["signal_date"]): row
        for row in sorted(existing_records, key=lambda value: value["signal_date"])
    }
    output: list[dict[str, Any]] = []

    for date in index:
        signal_date = date.strftime("%Y-%m-%d")
        source = byd_by_date[signal_date]
        pair = paired_by_date[signal_date]
        base_target = float(base.loc[date])
        source_base = float(source["base_target_position"])
        if not np.isclose(base_target, source_base):
            raise RuntimeError(f"base-target reproduction mismatch: {signal_date}")
        champion = champion_targets.loc[date]
        candidate = _candidate_target(
            champion,
            bool(lifecycle.loc[date, "overlay_decision_active"]),
        )
        factor = float(dataset.loc[date, "drawdown252_x_rebound60"])
        record: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "kind": "recovery_event_observation",
            "signal_date": signal_date,
            "observed_at_utc": pair["observed_at_utc"],
            "source": {
                "byd_observation_sha256": source["source_sha256"],
                "paired_observation_sha256": pair["source_sha256"],
                "byd_data_version": source["data_version"],
                "paired_data_version": pair["data_version"],
            },
            "launch_after": LAUNCH_AFTER.strftime("%Y-%m-%d"),
            "prelaunch_seed": date == LAUNCH_AFTER,
            "common_open_eligible": bool(pair["common_open_eligible"]),
            "prospective_eligible": bool(prospective.loc[date]),
            "detector": {
                "threshold": RECOVERY_THRESHOLD,
                "drawdown252_x_rebound60": factor,
                "active": bool(detector.loc[date]),
                "event_edge": bool(lifecycle.loc[date, "event_edge"]),
            },
            "lifecycle": {
                "hold_eligible_sessions": HOLD_ELIGIBLE_SESSIONS,
                "started": bool(lifecycle.loc[date, "lifecycle_started"]),
                "id": int(lifecycle.loc[date, "lifecycle_id"]),
                "overlay_decision_active": bool(
                    lifecycle.loc[date, "overlay_decision_active"]
                ),
                "remaining_eligible_sessions": int(
                    lifecycle.loc[date, "remaining_eligible_sessions"]
                ),
                "termination_on_decision": str(
                    lifecycle.loc[date, "termination_on_decision"]
                ),
            },
            "champion": {
                "model_id": CHAMPION_MODEL_ID,
                "base_byd_weight": base_target,
                "trend_expansion_active": bool(
                    champion_diag.loc[date, "trend_expansion_active"]
                ),
                "momentum_scale": float(champion_diag.loc[date, "momentum_scale"]),
                "financed_increment": float(
                    champion_diag.loc[date, "financed_increment"]
                ),
            },
            "factors": {
                "market_state": str(dataset.loc[date, "market_state"]),
                "vol_state": str(dataset.loc[date, "vol_state"]),
                "mom_20": float(dataset.loc[date, "mom_20"]),
                "mom_60": float(dataset.loc[date, "mom_60"]),
                "drawdown_252": float(dataset.loc[date, "drawdown_252"]),
                "distance_from_low_60": float(
                    dataset.loc[date, "distance_from_low_60"]
                ),
            },
            "prices": {
                "byd_open": float(
                    pair["byd"]["chain_linked_adjusted_ohlcv"]["open"]
                ),
                "etf_open": float(
                    pair["etf"]["chain_linked_adjusted_ohlcv"]["open"]
                ),
            },
            "targets": {
                CHAMPION_MODEL_ID: {
                    f"{asset}_weight": float(champion[f"{asset}_weight"])
                    for asset in ASSETS
                },
                CANDIDATE_MODEL_ID: candidate,
            },
            "cost_contract": SCENARIOS,
            "research_only": True,
            "trade_ready": False,
            "shadow_only": True,
            "automatic_promotion_allowed": False,
            "status": (
                "prelaunch_seed"
                if date == LAUNCH_AFTER
                else "prospective_recovery_lifecycle_active"
                if bool(prospective.loc[date])
                and bool(lifecycle.loc[date, "overlay_decision_active"])
                else "prospective_observation"
                if bool(prospective.loc[date])
                else "non_prospective_source_observation"
            ),
        }
        record["data_version"] = (
            f"byd-recovery-event-{signal_date}-"
            f"{source['source_sha256'][:8]}-{pair['source_sha256'][:8]}"
        )
        if signal_date in existing:
            if _json_bytes(existing[signal_date]) != _json_bytes(record):
                raise RuntimeError(
                    f"existing recovery event observation drifted: {signal_date}"
                )
            continue
        output.append(record)
    return output


def _frame(records: Iterable[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for record in sorted(records, key=lambda value: value["signal_date"]):
        item: dict[str, Any] = {
            "date": pd.Timestamp(record["signal_date"]),
            "common_open_eligible": bool(record["common_open_eligible"]),
            "prospective_eligible": bool(record["prospective_eligible"]),
            "event_edge": bool(record["detector"]["event_edge"]),
            "lifecycle_started": bool(record["lifecycle"]["started"]),
            "overlay_decision_active": bool(
                record["lifecycle"]["overlay_decision_active"]
            ),
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
    current = pd.Series({"byd": 0.0, "etf": 0.0, "cash": 1.0})
    rows: list[dict[str, float]] = []
    for position, (_, row) in enumerate(frame.iterrows()):
        if position > 0 and bool(row["common_open_eligible"]):
            previous = frame.iloc[position - 1]
            current = pd.Series(
                {
                    asset: float(previous[f"{strategy}_{asset}_weight"])
                    for asset in ASSETS
                }
            )
        rows.append(
            {
                f"position_{asset}_weight": float(current[asset])
                for asset in ASSETS
            }
        )
    return pd.DataFrame(rows, index=frame.index)


def strategy_daily(
    frame: pd.DataFrame,
    strategy: str,
    *,
    cost_bps: float,
    annual_financing_rate: float,
) -> pd.DataFrame:
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy}")
    if len(frame) < 2:
        return pd.DataFrame()
    executed = _execute(frame, strategy)
    byd_return = frame["byd_open"].shift(-1) / frame["byd_open"] - 1.0
    etf_return = frame["etf_open"].shift(-1) / frame["etf_open"] - 1.0
    gross = (
        executed["position_byd_weight"] * byd_return
        + executed["position_etf_weight"] * etf_return
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


def mature_lifecycle_outcomes(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
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
            champion_block = daily[scenario][CHAMPION_MODEL_ID].loc[
                episode.start : episode.end
            ]
            candidate_block = daily[scenario][CANDIDATE_MODEL_ID].reindex(
                champion_block.index
            )
            champion_wealth = float((1.0 + champion_block["net_return"]).prod())
            candidate_wealth = float((1.0 + candidate_block["net_return"]).prod())
            scenarios[scenario] = {
                "relative_terminal_wealth": candidate_wealth / champion_wealth - 1.0,
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
                "kind": "recovery_lifecycle_outcome",
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


def _relative_daily(
    candidate: pd.DataFrame,
    champion: pd.DataFrame,
) -> pd.Series:
    common = candidate.index.intersection(champion.index)
    return (
        (1.0 + candidate.loc[common, "net_return"])
        / (1.0 + champion.loc[common, "net_return"])
        - 1.0
    )


def _positive_concentration(values: Iterable[float]) -> float:
    positive = [max(float(value), 0.0) for value in values]
    total = sum(positive)
    return max(positive) / total if positive and total > 0.0 else 0.0


def build_scorecard(
    records: Iterable[dict[str, Any]],
    outcomes: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(records, key=lambda row: row["signal_date"])
    outcome_rows = list(outcomes)
    frame = _frame(ordered)
    prospective = [row for row in ordered if bool(row["prospective_eligible"])]
    first = pd.Timestamp(prospective[0]["signal_date"]) if prospective else None
    last = pd.Timestamp(prospective[-1]["signal_date"]) if prospective else None
    prospective_days = int((last - first).days) if first is not None and last is not None else 0

    scenario_summary: dict[str, Any] = {}
    primary_daily: dict[str, pd.DataFrame] | None = None
    for scenario, contract in SCENARIOS.items():
        if len(frame) < 2:
            scenario_summary[scenario] = {
                "champion_return": 0.0,
                "candidate_return": 0.0,
                "relative_terminal_wealth": 0.0,
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
        start = frame.index[frame.index > LAUNCH_AFTER]
        if len(start) == 0:
            champion_wealth = candidate_wealth = 1.0
        else:
            eval_index = daily[CHAMPION_MODEL_ID].index.intersection(start)
            champion_wealth = float(
                (1.0 + daily[CHAMPION_MODEL_ID].loc[eval_index, "net_return"]).prod()
            )
            candidate_wealth = float(
                (1.0 + daily[CANDIDATE_MODEL_ID].loc[eval_index, "net_return"]).prod()
            )
        scenario_summary[scenario] = {
            "champion_return": champion_wealth - 1.0,
            "candidate_return": candidate_wealth - 1.0,
            "relative_terminal_wealth": candidate_wealth / champion_wealth - 1.0,
            **contract,
        }
        if scenario == "primary":
            primary_daily = daily

    completed = [row for row in outcome_rows if row["kind"] == "recovery_lifecycle_outcome"]
    primary_episode_returns = [
        float(row["scenarios"]["primary"]["relative_terminal_wealth"])
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
        relative = _relative_daily(
            primary_daily[CANDIDATE_MODEL_ID],
            primary_daily[CHAMPION_MODEL_ID],
        )
        relative = relative.loc[relative.index > LAUNCH_AFTER]
        if not relative.empty:
            quarter_values = [
                float((1.0 + block).prod() - 1.0)
                for _, block in relative.groupby(relative.index.to_period("Q"))
            ]

    gates = {
        "forward_time_12_months": prospective_days >= 365,
        "completed_10_recovery_lifecycles": len(completed) >= 10,
        "at_least_2_event_market_states": len(event_states) >= 2,
        "primary_relative_wealth_positive": scenario_summary["primary"][
            "relative_terminal_wealth"
        ]
        > 0.0,
        "stress_relative_wealth_nonnegative": scenario_summary["stress"][
            "relative_terminal_wealth"
        ]
        >= 0.0,
        "largest_positive_lifecycle_share_le_40pct": (
            _positive_concentration(primary_episode_returns) <= 0.40
            and len(completed) > 0
        ),
        "largest_positive_quarter_share_le_60pct": (
            _positive_concentration(quarter_values) <= 0.60
            and len(quarter_values) > 0
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "prospective_monitoring" if prospective else "awaiting_first_prospective_observation",
        "launch_after": LAUNCH_AFTER.strftime("%Y-%m-%d"),
        "first_prospective_signal_date": first.strftime("%Y-%m-%d") if first is not None else None,
        "last_prospective_signal_date": last.strftime("%Y-%m-%d") if last is not None else None,
        "prospective_days": prospective_days,
        "observation_count": len(ordered),
        "prospective_observation_count": len(prospective),
        "completed_recovery_lifecycle_count": len(completed),
        "event_market_states": event_states,
        "scenarios": scenario_summary,
        "largest_positive_lifecycle_share": _positive_concentration(primary_episode_returns),
        "largest_positive_quarter_share": _positive_concentration(quarter_values),
        "gates": gates,
        "all_observation_gates_passed": all(gates.values()),
        "automatic_promotion_allowed": False,
        "research_only": True,
        "trade_ready": False,
        "shadow_only": True,
    }


def persist_store(
    store_root: str | Path,
    new_observations: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    root = Path(store_root)
    observation_dir = root / "observations"
    outcome_dir = root / "outcomes"
    for record in new_observations:
        _atomic_json(observation_dir / f"{record['signal_date']}.json", record)
    observations = _read_records(observation_dir)
    if any(row.get("schema_version") != SCHEMA_VERSION for row in observations):
        raise RuntimeError("recovery event store contains an incompatible observation")
    for record in observations:
        record["observation_sha256"] = file_sha256(
            observation_dir / f"{record['signal_date']}.json"
        )

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
                "prelaunch_seed": record["prelaunch_seed"],
                "prospective_eligible": record["prospective_eligible"],
                "common_open_eligible": record["common_open_eligible"],
                "detector_active": record["detector"]["active"],
                "event_edge": record["detector"]["event_edge"],
                "lifecycle_started": record["lifecycle"]["started"],
                "lifecycle_id": record["lifecycle"]["id"],
                "overlay_decision_active": record["lifecycle"]["overlay_decision_active"],
                "remaining_eligible_sessions": record["lifecycle"]["remaining_eligible_sessions"],
                "champion_expansion_active": record["champion"]["trend_expansion_active"],
                "champion_financed_increment": record["champion"]["financed_increment"],
                "market_state": record["factors"]["market_state"],
                "vol_state": record["factors"]["vol_state"],
                "drawdown252_x_rebound60": record["detector"]["drawdown252_x_rebound60"],
            }
        )
    ledger = pd.DataFrame(ledger_rows)
    ledger_path = root / "ledger.csv"
    root.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(ledger_path, index=False, float_format="%.12f", lineterminator="\n")
    scorecard_path = root / "scorecard.json"
    scorecard_path.write_text(
        json.dumps(scorecard, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    observation_hashes = {
        row["signal_date"]: file_sha256(
            observation_dir / f"{row['signal_date']}.json"
        )
        for row in observations
    }
    outcome_hashes = {
        path.name: file_sha256(path)
        for path in sorted(outcome_dir.glob("*.json"))
    } if outcome_dir.exists() else {}
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "candidate_model_id": CANDIDATE_MODEL_ID,
        "champion_model_id": CHAMPION_MODEL_ID,
        "launch_after": LAUNCH_AFTER.strftime("%Y-%m-%d"),
        "detector_threshold": RECOVERY_THRESHOLD,
        "hold_common_open_eligible_sessions": HOLD_ELIGIBLE_SESSIONS,
        "research_only": True,
        "trade_ready": False,
        "shadow_only": True,
        "append_only": True,
        "automatic_promotion_allowed": False,
        "observation_count": len(observations),
        "prospective_observation_count": sum(
            bool(row["prospective_eligible"]) for row in observations
        ),
        "outcome_count": len(persisted_outcomes),
        "first_signal_date": observations[0]["signal_date"] if observations else None,
        "last_signal_date": observations[-1]["signal_date"] if observations else None,
        "observation_sha256": observation_hashes,
        "outcome_sha256": outcome_hashes,
        "ledger_sha256": file_sha256(ledger_path),
        "scorecard_sha256": file_sha256(scorecard_path),
        "source_stores": [
            "data/research/byd_prospective_shadow",
            "data/research/byd_515180_prospective",
        ],
        "provider_fallback": False,
        "historical_retuning_allowed": False,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest
