"""Append-only prospective evidence for the frozen BYD v1.2 trend expansion."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from src.research.byd_prospective_shadow import file_sha256
from src.research.byd_v1_2_recovery_state import (
    build_research_dataset,
    build_v1_0_decision_position,
)
from src.research.byd_v1_2_trend_expansion import (
    FINANCING_DAY_COUNT,
    PRIMARY_FINANCING_RATE,
    RULES,
    STRESS_FINANCING_RATE,
)

SCHEMA_VERSION = "byd_v1_2_trend_expansion_prospective_v1"
LAUNCH_AFTER = pd.Timestamp("2026-08-05")
HORIZONS = (5, 10, 20)
SCENARIOS = {
    "primary": {"cost_bps": 20.0, "annual_financing_rate": PRIMARY_FINANCING_RATE},
    "stress": {"cost_bps": 40.0, "annual_financing_rate": STRESS_FINANCING_RATE},
}
STRATEGIES = ("byd_v1_1", "byd_v1_2_trend_expansion_1125")
ASSETS = ("byd", "etf", "cash")


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


def _normalise(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy(deep=True)
    output["date"] = (
        pd.to_datetime(output["date"], errors="raise")
        .dt.tz_localize(None)
        .dt.normalize()
    )
    return output.sort_values("date").drop_duplicates("date", keep="last")


def source_records(store_root: str | Path) -> list[dict[str, Any]]:
    root = Path(store_root) / "observations"
    records = _read_records(root)
    for record in records:
        record["source_sha256"] = file_sha256(
            root / f"{record['signal_date']}.json"
        )
    return records


def rebuild_byd_dataset(
    baseline_dir: str | Path,
    byd_records: Iterable[dict[str, Any]],
) -> pd.DataFrame:
    baseline = Path(baseline_dir)
    adjusted = _normalise(
        pd.read_csv(baseline / "adjusted_ohlcv.csv", parse_dates=["date"])
    )
    sessions = _normalise(
        pd.read_csv(baseline / "session_audit.csv", parse_dates=["date"])
    )
    new_prices: list[dict[str, Any]] = []
    new_sessions: list[dict[str, Any]] = []
    for record in sorted(byd_records, key=lambda row: row["signal_date"]):
        date = pd.Timestamp(record["signal_date"])
        if date <= adjusted["date"].max():
            continue
        ohlcv = record.get("chain_linked_adjusted_ohlcv")
        if not isinstance(ohlcv, dict):
            continue
        new_prices.append(
            {
                "date": date,
                **{
                    column: float(ohlcv[column])
                    for column in ("open", "high", "low", "close", "volume")
                },
            }
        )
        new_sessions.append(
            {
                "date": date,
                "open_research_eligible": bool(
                    record["open_research_eligible"]
                ),
                "independent_raw_confirmed": bool(
                    record.get("independent_raw_confirmed", False)
                ),
                "volume": float(ohlcv["volume"]),
            }
        )
    if new_prices:
        adjusted = pd.concat(
            [adjusted, pd.DataFrame(new_prices)], ignore_index=True
        ).sort_values("date")
        sessions = pd.concat(
            [sessions, pd.DataFrame(new_sessions)], ignore_index=True, sort=False
        ).sort_values("date")
    if adjusted["date"].duplicated().any() or sessions["date"].duplicated().any():
        raise RuntimeError("prospective source would rewrite an existing date")
    return build_research_dataset(adjusted, sessions)


def _entry(row: pd.Series, base_target: float) -> bool:
    return bool(
        np.isclose(base_target, RULES["entry_base_byd_weight"])
        and row["market_state"] == RULES["entry_market_state"]
        and row["vol_state"] == RULES["entry_vol_state"]
        and float(row["mom_20"]) > float(RULES["entry_mom_20_floor"])
        and float(row["mom_60"]) > float(RULES["entry_mom_60_floor"])
        and float(row["drawdown_252"])
        > float(RULES["entry_drawdown_252_floor"])
    )


def _exit(row: pd.Series, base_target: float) -> bool:
    return bool(
        np.isclose(base_target, RULES["exit_base_byd_weight"])
        or row["market_state"] != RULES["exit_market_state_not"]
        or row["vol_state"] == RULES["exit_vol_state"]
        or float(row["mom_20"]) <= float(RULES["exit_mom_20_ceiling"])
    )


def build_observations(
    *,
    baseline_dir: str | Path,
    byd_store: str | Path,
    paired_store: str | Path,
    existing_records: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    byd = source_records(byd_store)
    paired = source_records(paired_store)
    byd_by_date = {str(row["signal_date"]): row for row in byd}
    paired_by_date = {str(row["signal_date"]): row for row in paired}
    common_dates = sorted(set(byd_by_date) & set(paired_by_date))
    dataset = rebuild_byd_dataset(baseline_dir, byd)
    computed_base = build_v1_0_decision_position(dataset)
    existing = {
        str(row["signal_date"]): row
        for row in sorted(existing_records, key=lambda value: value["signal_date"])
    }
    active = bool(existing[sorted(existing)[-1]]["trend_expansion_active"]) if existing else False
    output: list[dict[str, Any]] = []

    for signal_date in common_dates:
        date = pd.Timestamp(signal_date)
        if date <= LAUNCH_AFTER or date not in dataset.index:
            continue
        source = byd_by_date[signal_date]
        pair = paired_by_date[signal_date]
        base_target = float(source["base_target_position"])
        if not np.isclose(base_target, float(computed_base.loc[date])):
            raise RuntimeError(f"base-target reproduction mismatch: {signal_date}")
        row = dataset.loc[date]
        entry = _entry(row, base_target)
        exit_ = _exit(row, base_target)
        if active and exit_:
            active = False
        elif not active and entry:
            active = True

        baseline_target = {
            "byd_weight": base_target,
            "etf_weight": 1.0 - base_target,
            "cash_weight": 0.0,
        }
        candidate_target = (
            {
                "byd_weight": 1.125,
                "etf_weight": 0.0,
                "cash_weight": -0.125,
            }
            if active
            else dict(baseline_target)
        )
        record = {
            "schema_version": SCHEMA_VERSION,
            "kind": "trend_expansion_observation",
            "signal_date": signal_date,
            "observed_at_utc": pair["observed_at_utc"],
            "source": {
                "byd_observation_sha256": source["source_sha256"],
                "paired_observation_sha256": pair["source_sha256"],
                "byd_data_version": source["data_version"],
                "paired_data_version": pair["data_version"],
            },
            "common_open_eligible": bool(pair["common_open_eligible"]),
            "prospective_eligible": bool(pair["prospective_eligible"]),
            "entry_condition": entry,
            "exit_condition": exit_,
            "trend_expansion_active": active,
            "factors": {
                "base_target_position": base_target,
                "market_state": str(row["market_state"]),
                "vol_state": str(row["vol_state"]),
                "mom_20": float(row["mom_20"]),
                "mom_60": float(row["mom_60"]),
                "drawdown_252": float(row["drawdown_252"]),
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
                "byd_v1_1": baseline_target,
                "byd_v1_2_trend_expansion_1125": candidate_target,
            },
            "cost_contract": {
                "primary": SCENARIOS["primary"],
                "stress": SCENARIOS["stress"],
            },
            "status": (
                "prospective_trend_expansion_active"
                if active and bool(pair["prospective_eligible"])
                else "prospective_observation"
                if bool(pair["prospective_eligible"])
                else "non_prospective_source_observation"
            ),
            "research_only": True,
            "trade_ready": False,
            "shadow_only": True,
        }
        record["data_version"] = (
            f"byd-v1-2-trend-{signal_date}-"
            f"{source['source_sha256'][:8]}-{pair['source_sha256'][:8]}"
        )
        if signal_date in existing:
            expected = _json_bytes(record) + b"\n"
            path = Path("unused")
            if _json_bytes(existing[signal_date]) + b"\n" != expected:
                raise RuntimeError(
                    f"existing trend observation no longer reproduces: {signal_date}"
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
            "trend_expansion_active": bool(record["trend_expansion_active"]),
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
    for index, (_, row) in enumerate(frame.iterrows()):
        if index > 0 and bool(row["common_open_eligible"]):
            previous = frame.iloc[index - 1]
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


def _period_return(
    daily: pd.DataFrame,
    entry: pd.Timestamp,
    exit_: pd.Timestamp,
) -> float:
    block = daily.loc[(daily.index >= entry) & (daily.index < exit_)]
    return float((1.0 + block["net_return"]).prod() - 1.0)


def mature_outcomes(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(records, key=lambda row: row["signal_date"])
    frame = _frame(ordered)
    if frame.empty:
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
    outcomes: list[dict[str, Any]] = []
    for observation in ordered:
        if not bool(observation["prospective_eligible"]):
            continue
        if not bool(observation["trend_expansion_active"]):
            continue
        signal_date = pd.Timestamp(observation["signal_date"])
        eligible = list(
            frame.index[
                (frame.index > signal_date)
                & frame["common_open_eligible"].astype(bool)
            ]
        )
        for horizon in HORIZONS:
            if len(eligible) <= horizon:
                continue
            entry = eligible[0]
            exit_ = eligible[horizon]
            scenario_rows: dict[str, Any] = {}
            for scenario in SCENARIOS:
                baseline_return = _period_return(
                    daily[scenario]["byd_v1_1"], entry, exit_
                )
                candidate_return = _period_return(
                    daily[scenario]["byd_v1_2_trend_expansion_1125"],
                    entry,
                    exit_,
                )
                scenario_rows[scenario] = {
                    "baseline_return": baseline_return,
                    "candidate_return": candidate_return,
                    "relative_terminal_wealth": (
                        (1.0 + candidate_return) / (1.0 + baseline_return) - 1.0
                    ),
                    **SCENARIOS[scenario],
                }
            outcomes.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "kind": "trend_expansion_horizon_outcome",
                    "signal_date": observation["signal_date"],
                    "observation_sha256": observation["observation_sha256"],
                    "horizon_common_eligible_opens": horizon,
                    "entry_open_date": entry.strftime("%Y-%m-%d"),
                    "exit_open_date": exit_.strftime("%Y-%m-%d"),
                    "scenarios": scenario_rows,
                    "research_only": True,
                    "trade_ready": False,
                    "shadow_only": True,
                }
            )
    return outcomes


def _episode_stats(frame: pd.DataFrame, primary_daily: pd.DataFrame, baseline_daily: pd.DataFrame) -> dict[str, Any]:
    active = primary_daily["borrowed_weight"].gt(0.0)
    starts = active & ~active.shift(1, fill_value=False)
    episode_id = starts.cumsum().where(active)
    relative: list[float] = []
    completed = 0
    for raw_id, block in primary_daily.groupby(episode_id):
        if pd.isna(raw_id):
            continue
        last_date = block.index.max()
        is_completed = bool(
            (primary_daily.index > last_date).any()
            and not active.loc[primary_daily.index[primary_daily.index > last_date][0]]
        )
        if not is_completed:
            continue
        completed += 1
        base = baseline_daily.loc[block.index]
        candidate_wealth = float((1.0 + block["net_return"]).prod())
        baseline_wealth = float((1.0 + base["net_return"]).prod())
        relative.append(candidate_wealth / baseline_wealth - 1.0)
    positive = [max(value, 0.0) for value in relative]
    positive_total = sum(positive)
    max_share = max(positive) / positive_total if positive_total > 0.0 else 0.0
    return {
        "completed_expansion_episodes": completed,
        "episode_relative_terminal_wealth": relative,
        "maximum_positive_episode_share": max_share,
        "financed_sessions": int(active.sum()),
    }


def build_scorecard(records: Iterable[dict[str, Any]], outcomes: Iterable[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(records, key=lambda row: row["signal_date"])
    frame = _frame(ordered)
    outcome_rows = list(outcomes)
    if frame.empty:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "awaiting_first_observation",
            "research_only": True,
            "trade_ready": False,
        }
    scenario_summary: dict[str, Any] = {}
    primary_daily: pd.DataFrame | None = None
    baseline_daily: pd.DataFrame | None = None
    for scenario, contract in SCENARIOS.items():
        baseline = strategy_daily(
            frame,
            "byd_v1_1",
            cost_bps=float(contract["cost_bps"]),
            annual_financing_rate=float(contract["annual_financing_rate"]),
        )
        candidate = strategy_daily(
            frame,
            "byd_v1_2_trend_expansion_1125",
            cost_bps=float(contract["cost_bps"]),
            annual_financing_rate=float(contract["annual_financing_rate"]),
        )
        baseline_wealth = float((1.0 + baseline["net_return"]).prod())
        candidate_wealth = float((1.0 + candidate["net_return"]).prod())
        scenario_summary[scenario] = {
            "baseline_return": baseline_wealth - 1.0,
            "candidate_return": candidate_wealth - 1.0,
            "relative_terminal_wealth": candidate_wealth / baseline_wealth - 1.0,
            **contract,
        }
        if scenario == "primary":
            primary_daily = candidate
            baseline_daily = baseline
    assert primary_daily is not None and baseline_daily is not None
    episodes = _episode_stats(frame, primary_daily, baseline_daily)
    first = pd.Timestamp(ordered[0]["signal_date"])
    last = pd.Timestamp(ordered[-1]["signal_date"])
    prospective_active = [
        row
        for row in ordered
        if row["prospective_eligible"] and row["trend_expansion_active"]
    ]
    gates = {
        "forward_time_12_months": int((last - first).days) >= 365,
        "completed_10_expansion_episodes": episodes[
            "completed_expansion_episodes"
        ]
        >= 10,
        "financed_126_sessions": episodes["financed_sessions"] >= 126,
        "primary_relative_wealth_positive": scenario_summary["primary"][
            "relative_terminal_wealth"
        ]
        > 0.0,
        "stress_relative_wealth_positive": scenario_summary["stress"][
            "relative_terminal_wealth"
        ]
        > 0.0,
        "positive_episode_not_concentrated": episodes[
            "maximum_positive_episode_share"
        ]
        <= 0.60
        and episodes["completed_expansion_episodes"] > 0,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "prospective_monitoring",
        "first_signal_date": first.strftime("%Y-%m-%d"),
        "last_signal_date": last.strftime("%Y-%m-%d"),
        "observation_count": len(ordered),
        "prospective_active_observation_count": len(prospective_active),
        "outcome_count": len(outcome_rows),
        "scenarios": scenario_summary,
        "episodes": episodes,
        "gates": gates,
        "all_gates_passed": all(gates.values()),
        "automatic_promotion_allowed": False,
        "research_only": True,
        "trade_ready": False,
    }


def persist_store(
    store_root: str | Path,
    new_observations: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    root = Path(store_root)
    observation_dir = root / "observations"
    outcome_dir = root / "outcomes"
    for record in new_observations:
        digest = _atomic_json(
            observation_dir / f"{record['signal_date']}.json", record
        )
        record["observation_sha256"] = digest
    observations = _read_records(observation_dir)
    for record in observations:
        record["observation_sha256"] = file_sha256(
            observation_dir / f"{record['signal_date']}.json"
        )
    outcomes = mature_outcomes(observations)
    for outcome in outcomes:
        name = (
            f"{outcome['signal_date']}__"
            f"{int(outcome['horizon_common_eligible_opens']):02d}.json"
        )
        _atomic_json(outcome_dir / name, outcome)
    persisted_outcomes = _read_records(outcome_dir)
    scorecard = build_scorecard(observations, persisted_outcomes)

    rows: list[dict[str, Any]] = []
    outcome_map = {
        (row["signal_date"], int(row["horizon_common_eligible_opens"])): row
        for row in persisted_outcomes
    }
    for record in observations:
        row: dict[str, Any] = {
            "signal_date": record["signal_date"],
            "observation_sha256": file_sha256(
                observation_dir / f"{record['signal_date']}.json"
            ),
            "prospective_eligible": record["prospective_eligible"],
            "common_open_eligible": record["common_open_eligible"],
            "trend_expansion_active": record["trend_expansion_active"],
            "base_target_position": record["factors"]["base_target_position"],
            "market_state": record["factors"]["market_state"],
            "vol_state": record["factors"]["vol_state"],
            "mom_20": record["factors"]["mom_20"],
            "mom_60": record["factors"]["mom_60"],
            "drawdown_252": record["factors"]["drawdown_252"],
        }
        for horizon in HORIZONS:
            outcome = outcome_map.get((record["signal_date"], horizon))
            row[f"relative_wealth_{horizon}_primary"] = (
                outcome["scenarios"]["primary"]["relative_terminal_wealth"]
                if outcome
                else None
            )
            row[f"relative_wealth_{horizon}_stress"] = (
                outcome["scenarios"]["stress"]["relative_terminal_wealth"]
                if outcome
                else None
            )
        rows.append(row)
    ledger = pd.DataFrame(rows)
    root.mkdir(parents=True, exist_ok=True)
    ledger.to_csv(root / "ledger.csv", index=False, lineterminator="\n")
    (root / "scorecard.json").write_bytes(_json_bytes(scorecard) + b"\n")
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "append_only": True,
        "launch_after": LAUNCH_AFTER.strftime("%Y-%m-%d"),
        "observation_count": len(observations),
        "outcome_count": len(persisted_outcomes),
        "first_signal_date": observations[0]["signal_date"] if observations else None,
        "last_signal_date": observations[-1]["signal_date"] if observations else None,
        "observation_sha256": {
            row["signal_date"]: file_sha256(
                observation_dir / f"{row['signal_date']}.json"
            )
            for row in observations
        },
        "ledger_sha256": file_sha256(root / "ledger.csv"),
        "scorecard_sha256": file_sha256(root / "scorecard.json"),
        "research_only": True,
        "trade_ready": False,
    }
    (root / "manifest.json").write_bytes(_json_bytes(manifest) + b"\n")
    readme = [
        "# BYD v1.2 trend-expansion prospective ledger",
        "",
        "- Candidate: `112.5% BYD / -12.5% financing` in the frozen trend state",
        "- Baseline: `BYD v1.1`",
        f"- Observations: `{manifest['observation_count']}`",
        f"- Outcomes: `{manifest['outcome_count']}`",
        "- Execution: prior close target, next independently confirmed common open",
        "- Primary costs: 20 bps + 6% annual financing",
        "- Stress costs: 40 bps + 10% annual financing",
        "- Append only: `true`",
        "- Research only: `true`",
        "- Trade ready: `false`",
    ]
    (root / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")
    return manifest
