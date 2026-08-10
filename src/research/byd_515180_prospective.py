"""Append-only prospective evidence for the BYD/515180 defensive sleeve."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from src.research.byd_prospective_shadow import (
    ChainLinkedExtension,
    IndependentAudit,
    file_sha256,
)

SCHEMA_VERSION = "byd_515180_prospective_v1"
ETF_ARTIFACT_SHA256 = "7e077664516b74546ec118f2bf0484ee650577a0898623f3f0cb8623397e061f"
ETF_ADJUSTED_SHA256 = "2173afbe2fcbc8875de55ce0ff9bcb25b1c9f184c5cd273ade682244393c67a5"
ETF_MANIFEST_SHA256 = "7f19639e6540ebb71eac7e52dab270df4b20b59bcf764c2dc6843045de21e4ec"
ETF_CUTOFF = "2026-08-03"
HORIZONS = (5, 10, 20)
COST_SCENARIOS_BPS = (20.0, 40.0)
STRATEGIES = ("byd_v1_cash", "v1_dividend_75_25", "fixed_75_25")


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


def _read_json_records(directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    records = [
        json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))
    ]
    return sorted(
        records,
        key=lambda row: (row.get("signal_date", ""), row.get("kind", "")),
    )


def _normalise_dates(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy(deep=True)
    out["date"] = pd.to_datetime(out["date"], errors="raise").dt.tz_localize(None).dt.normalize()
    return out.sort_values("date").drop_duplicates("date", keep="last")


def read_paired_observations(store_root: str | Path) -> list[dict[str, Any]]:
    return _read_json_records(Path(store_root) / "observations")


def load_byd_observations(store_root: str | Path) -> list[dict[str, Any]]:
    root = Path(store_root)
    observation_dir = root / "observations"
    records = _read_json_records(observation_dir)
    for row in records:
        path = observation_dir / f"{row['signal_date']}.json"
        row["observation_sha256"] = file_sha256(path)
    return records


def build_paired_observations(
    *,
    byd_observations: Iterable[dict[str, Any]],
    extension: ChainLinkedExtension,
    audit: IndependentAudit,
    provider_history: pd.DataFrame,
    existing_dates: set[str],
    observed_at_utc: str,
    primary_provider: str,
    provider_parameters: dict[str, Any],
    secondary_attempts: list[dict[str, Any]],
    extended_adjusted_sha256: str,
) -> list[dict[str, Any]]:
    adjusted = _normalise_dates(extension.adjusted_new).set_index("date")
    primary_raw = _normalise_dates(extension.primary_raw_new).set_index("date")
    audit_rows = _normalise_dates(audit.row_audit).set_index("date")
    provider = _normalise_dates(provider_history).set_index("date")
    new_rows: list[dict[str, Any]] = []
    observed_date = pd.Timestamp(observed_at_utc).tz_convert(None).normalize()

    for byd in sorted(byd_observations, key=lambda row: row["signal_date"]):
        signal_date = str(byd["signal_date"])
        if signal_date in existing_dates:
            continue
        date = pd.Timestamp(signal_date)
        if date <= pd.Timestamp(ETF_CUTOFF) or date not in adjusted.index:
            continue

        etf_audit = audit_rows.loc[date]
        base_target = float(byd["base_target_position"])
        if not np.isclose(base_target, 0.75) and not np.isclose(
            base_target,
            1.0,
        ):
            raise RuntimeError(f"unexpected BYD V1.0 target on {signal_date}: {base_target}")

        same_session = date == observed_date
        observation_mode = "same_session_post_close" if same_session else "catch_up"
        common_eligible = bool(byd["open_research_eligible"]) and bool(
            etf_audit["open_research_eligible"]
        )
        prospective_eligible = (
            bool(byd.get("prospective_eligible", False)) and same_session and common_eligible
        )
        etf_raw = primary_raw.loc[date]
        etf_adjusted = adjusted.loc[date]
        provider_row = provider.loc[date]
        candidate_etf_weight = 1.0 - base_target

        observation = {
            "schema_version": SCHEMA_VERSION,
            "kind": "paired_observation",
            "signal_date": signal_date,
            "observed_at_utc": observed_at_utc,
            "observation_mode": observation_mode,
            "prospective_eligible": prospective_eligible,
            "common_open_eligible": common_eligible,
            "research_only": True,
            "trade_ready": False,
            "shadow_only": True,
            "byd": {
                "observation_sha256": byd["observation_sha256"],
                "data_version": byd["data_version"],
                "observation_mode": byd["observation_mode"],
                "prospective_eligible": bool(byd.get("prospective_eligible", False)),
                "open_research_eligible": bool(byd["open_research_eligible"]),
                "base_target_position": base_target,
                "primary_raw_ohlcv": byd["primary_raw_ohlcv"],
                "chain_linked_adjusted_ohlcv": byd["chain_linked_adjusted_ohlcv"],
                "company_actions": byd["company_actions"],
                "market_state": byd["factors"]["market_state"],
                "vol_state": byd["factors"]["vol_state"],
            },
            "etf": {
                "symbol": "515180.SH",
                "artifact_sha256": ETF_ARTIFACT_SHA256,
                "base_adjusted_sha256": ETF_ADJUSTED_SHA256,
                "base_manifest_sha256": ETF_MANIFEST_SHA256,
                "provider_payload_sha256": extension.provider_payload_sha256,
                "secondary_payload_sha256": audit.secondary_payload_sha256,
                "extended_adjusted_sha256": extended_adjusted_sha256,
                "primary_provider": primary_provider,
                "secondary_provider": audit.secondary_provider,
                "provider_parameters": provider_parameters,
                "secondary_attempts": secondary_attempts,
                "chain_scale": extension.chain_scale,
                "anchor_provider_adjusted_close": (extension.anchor_provider_adjusted_close),
                "anchor_canonical_adjusted_close": (extension.anchor_canonical_adjusted_close),
                "open_research_eligible": bool(etf_audit["open_research_eligible"]),
                "independent_raw_confirmed": bool(etf_audit["independent_raw_confirmed"]),
                "primary_raw_ohlcv": {
                    column: float(etf_raw[column])
                    for column in ("open", "high", "low", "close", "volume")
                },
                "chain_linked_adjusted_ohlcv": {
                    column: float(etf_adjusted[column])
                    for column in ("open", "high", "low", "close", "volume")
                },
                "company_actions": {
                    "dividend": float(provider_row.get("dividends", 0.0)),
                    "stock_split": float(provider_row.get("stock_splits", 0.0)),
                },
                "independent_audit": {
                    "confirmed": bool(etf_audit["independent_raw_confirmed"]),
                    "open_level_abs_pct_difference": float(
                        etf_audit["open_level_abs_pct_difference"]
                    ),
                    "close_level_abs_pct_difference": float(
                        etf_audit["close_level_abs_pct_difference"]
                    ),
                },
            },
            "targets": {
                "byd_v1_cash": {
                    "byd_weight": base_target,
                    "etf_weight": 0.0,
                    "cash_weight": 1.0 - base_target,
                },
                "v1_dividend_75_25": {
                    "byd_weight": base_target,
                    "etf_weight": candidate_etf_weight,
                    "cash_weight": 0.0,
                },
                "fixed_75_25": {
                    "byd_weight": 0.75,
                    "etf_weight": 0.25,
                    "cash_weight": 0.0,
                },
            },
            "status": (
                "prospective_paired_observation"
                if common_eligible
                else "prospective_paired_open_quarantined"
            ),
        }
        observation["data_version"] = (
            f"byd-515180-paired-{signal_date}-"
            f"{byd['observation_sha256'][:8]}-"
            f"{extension.provider_payload_sha256[:8]}"
        )
        new_rows.append(observation)
    return new_rows


def _observation_frame(records: Iterable[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in sorted(records, key=lambda value: value["signal_date"]):
        item: dict[str, Any] = {
            "date": pd.Timestamp(row["signal_date"]),
            "common_open_eligible": bool(row["common_open_eligible"]),
            "prospective_eligible": bool(row["prospective_eligible"]),
            "byd_open": float(row["byd"]["chain_linked_adjusted_ohlcv"]["open"]),
            "etf_open": float(row["etf"]["chain_linked_adjusted_ohlcv"]["open"]),
            "market_state": str(row["byd"]["market_state"]),
            "vol_state": str(row["byd"]["vol_state"]),
        }
        for strategy in STRATEGIES:
            for asset in ("byd", "etf", "cash"):
                item[f"{strategy}_{asset}_weight"] = float(
                    row["targets"][strategy][f"{asset}_weight"]
                )
        rows.append(item)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index("date").sort_index()


def execute_next_common_open(
    frame: pd.DataFrame,
    strategy: str,
) -> pd.DataFrame:
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown strategy: {strategy}")
    current = pd.Series({"byd": 0.0, "etf": 0.0, "cash": 1.0})
    rows: list[dict[str, float]] = []
    for index, (_, row) in enumerate(frame.iterrows()):
        if index > 0 and bool(row["common_open_eligible"]):
            previous = frame.iloc[index - 1]
            current = pd.Series(
                {
                    asset: float(previous[f"{strategy}_{asset}_weight"])
                    for asset in ("byd", "etf", "cash")
                }
            )
        rows.append({f"position_{asset}_weight": float(current[asset]) for asset in current.index})
    return pd.DataFrame(rows, index=frame.index)


def strategy_daily(
    frame: pd.DataFrame,
    strategy: str,
    *,
    cost_bps: float,
) -> pd.DataFrame:
    if len(frame) < 2:
        return pd.DataFrame()
    executed = execute_next_common_open(frame, strategy)
    byd_return = frame["byd_open"].shift(-1) / frame["byd_open"] - 1.0
    etf_return = frame["etf_open"].shift(-1) / frame["etf_open"] - 1.0
    gross = (
        executed["position_byd_weight"] * byd_return + executed["position_etf_weight"] * etf_return
    )
    turnover = executed.diff().abs().sum(axis=1)
    initial_cash = pd.Series(
        {
            "position_byd_weight": 0.0,
            "position_etf_weight": 0.0,
            "position_cash_weight": 1.0,
        }
    )
    turnover.iloc[0] = executed.iloc[0].sub(initial_cash).abs().sum()
    result = executed.copy()
    result["common_open_eligible"] = frame["common_open_eligible"]
    result["byd_open_return"] = byd_return
    result["etf_open_return"] = etf_return
    result["gross_return"] = gross
    result["turnover_units"] = turnover
    result["cost"] = turnover * float(cost_bps) / 10_000.0
    result["net_return"] = result["gross_return"] - result["cost"]
    return result.iloc[:-1].copy()


def _period_return(
    daily: pd.DataFrame,
    entry: pd.Timestamp,
    exit_: pd.Timestamp,
) -> float:
    block = daily.loc[(daily.index >= entry) & (daily.index < exit_)]
    return float((1.0 + block["net_return"]).prod() - 1.0)


def mature_horizon_outcomes(
    records: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    ordered = sorted(records, key=lambda row: row["signal_date"])
    frame = _observation_frame(ordered)
    if frame.empty:
        return []
    daily = {
        str(int(cost)): {
            strategy: strategy_daily(frame, strategy, cost_bps=cost) for strategy in STRATEGIES
        }
        for cost in COST_SCENARIOS_BPS
    }
    outcomes: list[dict[str, Any]] = []
    for observation in ordered:
        signal_date = pd.Timestamp(observation["signal_date"])
        eligible = list(
            frame.index[(frame.index > signal_date) & frame["common_open_eligible"].astype(bool)]
        )
        for horizon in HORIZONS:
            if len(eligible) <= horizon:
                continue
            entry = eligible[0]
            exit_ = eligible[horizon]
            scenarios: dict[str, dict[str, Any]] = {}
            for cost in COST_SCENARIOS_BPS:
                cost_key = str(int(cost))
                returns = {
                    strategy: _period_return(
                        daily[cost_key][strategy],
                        entry,
                        exit_,
                    )
                    for strategy in STRATEGIES
                }
                baseline = returns["byd_v1_cash"]
                candidate = returns["v1_dividend_75_25"]
                scenarios[cost_key] = {
                    "strategy_returns": returns,
                    "candidate_incremental_return": ((1.0 + candidate) / (1.0 + baseline) - 1.0),
                }
            settlement = [
                row for row in ordered if signal_date <= pd.Timestamp(row["signal_date"]) <= exit_
            ]
            outcomes.append(
                {
                    "schema_version": SCHEMA_VERSION,
                    "kind": "horizon_outcome",
                    "signal_date": observation["signal_date"],
                    "horizon_common_eligible_opens": horizon,
                    "entry_open_date": entry.strftime("%Y-%m-%d"),
                    "exit_open_date": exit_.strftime("%Y-%m-%d"),
                    "cost_scenarios_bps": scenarios,
                    "settlement_source": ("immutable_paired_observations_only"),
                    "settlement_input_sha256": hashlib.sha256(
                        b"".join(_json_bytes(row) + b"\n" for row in settlement)
                    ).hexdigest(),
                    "prospective_eligible": bool(observation["prospective_eligible"]),
                    "research_only": True,
                    "trade_ready": False,
                    "shadow_only": True,
                }
            )
    return outcomes


def mature_defense_episodes(
    records: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    ordered = sorted(records, key=lambda row: row["signal_date"])
    frame = _observation_frame(ordered)
    if frame.empty:
        return []
    targets = pd.Series(
        [float(row["byd"]["base_target_position"]) for row in ordered],
        index=frame.index,
    )
    starts = frame.index[targets.eq(0.75) & targets.shift(1).eq(1.0)]
    outcomes: list[dict[str, Any]] = []
    for start in starts:
        later = targets.loc[targets.index > start]
        ends = later.index[later.eq(1.0)]
        if len(ends) == 0:
            continue
        end_signal = ends[0]
        eligible_after_start = list(
            frame.index[(frame.index > start) & frame["common_open_eligible"].astype(bool)]
        )
        eligible_after_end = list(
            frame.index[(frame.index > end_signal) & frame["common_open_eligible"].astype(bool)]
        )
        if not eligible_after_start or not eligible_after_end:
            continue
        entry = eligible_after_start[0]
        exit_ = eligible_after_end[0]
        scenarios: dict[str, dict[str, Any]] = {}
        for cost in COST_SCENARIOS_BPS:
            returns = {
                strategy: _period_return(
                    strategy_daily(frame, strategy, cost_bps=cost),
                    entry,
                    exit_,
                )
                for strategy in STRATEGIES
            }
            scenarios[str(int(cost))] = {
                "strategy_returns": returns,
                "candidate_incremental_return": (
                    (1.0 + returns["v1_dividend_75_25"]) / (1.0 + returns["byd_v1_cash"]) - 1.0
                ),
            }
        outcomes.append(
            {
                "schema_version": SCHEMA_VERSION,
                "kind": "defense_episode_outcome",
                "signal_date": start.strftime("%Y-%m-%d"),
                "defense_end_signal_date": end_signal.strftime("%Y-%m-%d"),
                "entry_open_date": entry.strftime("%Y-%m-%d"),
                "exit_open_date": exit_.strftime("%Y-%m-%d"),
                "cost_scenarios_bps": scenarios,
                "research_only": True,
                "trade_ready": False,
                "shadow_only": True,
            }
        )
    return outcomes


def _derived_ledger(
    observations: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
    observation_hashes: dict[str, str],
) -> pd.DataFrame:
    outcome_lookup = {
        (
            row["signal_date"],
            int(row["horizon_common_eligible_opens"]),
        ): row
        for row in outcomes
        if row["kind"] == "horizon_outcome"
    }
    rows: list[dict[str, Any]] = []
    for observation in observations:
        row: dict[str, Any] = {
            "signal_date": observation["signal_date"],
            "observed_at_utc": observation["observed_at_utc"],
            "observation_sha256": observation_hashes[observation["signal_date"]],
            "data_version": observation["data_version"],
            "observation_mode": observation["observation_mode"],
            "prospective_eligible": observation["prospective_eligible"],
            "common_open_eligible": observation["common_open_eligible"],
            "base_target_position": observation["byd"]["base_target_position"],
            "candidate_etf_weight": observation["targets"]["v1_dividend_75_25"]["etf_weight"],
            "market_state": observation["byd"]["market_state"],
            "vol_state": observation["byd"]["vol_state"],
        }
        for horizon in HORIZONS:
            outcome = outcome_lookup.get((observation["signal_date"], horizon))
            row[f"incremental_return_{horizon}_20bps"] = (
                outcome["cost_scenarios_bps"]["20"]["candidate_incremental_return"]
                if outcome
                else np.nan
            )
            row[f"incremental_return_{horizon}_40bps"] = (
                outcome["cost_scenarios_bps"]["40"]["candidate_incremental_return"]
                if outcome
                else np.nan
            )
        rows.append(row)
    return pd.DataFrame(rows)


def _scorecard(
    observations: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    frame = _observation_frame(observations)
    cumulative: dict[str, Any] = {}
    for cost in COST_SCENARIOS_BPS:
        strategy_returns: dict[str, float] = {}
        for strategy in STRATEGIES:
            daily = strategy_daily(frame, strategy, cost_bps=cost)
            strategy_returns[strategy] = (
                float((1.0 + daily["net_return"]).prod() - 1.0) if not daily.empty else 0.0
            )
        baseline = strategy_returns["byd_v1_cash"]
        candidate = strategy_returns["v1_dividend_75_25"]
        cumulative[str(int(cost))] = {
            "strategy_returns": strategy_returns,
            "candidate_incremental_return": ((1.0 + candidate) / (1.0 + baseline) - 1.0),
        }
    eligible = [row for row in observations if row["prospective_eligible"]]
    dates = [pd.Timestamp(row["signal_date"]) for row in eligible]
    prospective_days = (max(dates) - min(dates)).days if len(dates) >= 2 else 0
    episode_count = sum(row["kind"] == "defense_episode_outcome" for row in outcomes)
    states = sorted({row["byd"]["market_state"] for row in eligible})
    dividend_count = sum(float(row["etf"]["company_actions"]["dividend"]) > 0.0 for row in eligible)
    return {
        "schema_version": SCHEMA_VERSION,
        "research_only": True,
        "trade_ready": False,
        "shadow_only": True,
        "observation_count": len(observations),
        "prospective_eligible_observation_count": len(eligible),
        "prospective_days": prospective_days,
        "completed_defense_episode_count": episode_count,
        "market_states": states,
        "etf_dividend_observation_count": dividend_count,
        "cumulative_cost_scenarios_bps": cumulative,
        "re_evaluation_gate": {
            "at_least_12_months": prospective_days >= 365,
            "at_least_6_completed_defense_episodes": episode_count >= 6,
            "at_least_2_market_states": len(states) >= 2,
            "at_least_1_etf_dividend_cycle": dividend_count >= 1,
        },
    }


def persist_store(
    store_root: str | Path,
    new_observations: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    root = Path(store_root)
    observation_dir = root / "observations"
    outcome_dir = root / "outcomes"
    observation_dir.mkdir(parents=True, exist_ok=True)
    outcome_dir.mkdir(parents=True, exist_ok=True)

    for observation in new_observations:
        _atomic_json(
            observation_dir / f"{observation['signal_date']}.json",
            observation,
        )

    observations = _read_json_records(observation_dir)
    if any(row.get("schema_version") != SCHEMA_VERSION for row in observations):
        raise RuntimeError("paired store contains an incompatible observation")

    outcomes = [
        *mature_horizon_outcomes(observations),
        *mature_defense_episodes(observations),
    ]
    for outcome in outcomes:
        if outcome["kind"] == "horizon_outcome":
            filename = (
                f"{outcome['signal_date']}-"
                f"h{int(outcome['horizon_common_eligible_opens']):02d}.json"
            )
        else:
            filename = f"episode-{outcome['signal_date']}-{outcome['defense_end_signal_date']}.json"
        _atomic_json(outcome_dir / filename, outcome)

    stored_outcomes = _read_json_records(outcome_dir)
    observation_hashes = {
        row["signal_date"]: file_sha256(observation_dir / f"{row['signal_date']}.json")
        for row in observations
    }
    ledger = _derived_ledger(
        observations,
        stored_outcomes,
        observation_hashes,
    )
    ledger_path = root / "ledger.csv"
    ledger.to_csv(
        ledger_path,
        index=False,
        float_format="%.12f",
        lineterminator="\n",
    )
    scorecard = _scorecard(observations, stored_outcomes)
    scorecard_path = root / "scorecard.json"
    scorecard_path.write_text(
        json.dumps(
            scorecard,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "research_only": True,
        "trade_ready": False,
        "shadow_only": True,
        "append_only": True,
        "etf_artifact_sha256": ETF_ARTIFACT_SHA256,
        "etf_adjusted_sha256": ETF_ADJUSTED_SHA256,
        "etf_manifest_sha256": ETF_MANIFEST_SHA256,
        "baseline_cutoff": ETF_CUTOFF,
        "observation_count": len(observations),
        "prospective_eligible_observation_count": sum(
            bool(row["prospective_eligible"]) for row in observations
        ),
        "outcome_count": len(stored_outcomes),
        "completed_defense_episode_count": sum(
            row["kind"] == "defense_episode_outcome" for row in stored_outcomes
        ),
        "first_signal_date": (observations[0]["signal_date"] if observations else None),
        "last_signal_date": (observations[-1]["signal_date"] if observations else None),
        "observation_sha256": observation_hashes,
        "ledger_sha256": file_sha256(ledger_path),
        "scorecard_sha256": file_sha256(scorecard_path),
        "cost_scenarios_bps": list(COST_SCENARIOS_BPS),
        "horizons_common_eligible_opens": list(HORIZONS),
        "provider_history_may_not_overwrite_existing_observations": True,
        "byd_observations_are_referenced_not_recomputed": True,
    }
    (root / "manifest.json").write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest
