"""Append-only canonical input extension for the active BYD formal model."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from src.artifacts.formal_refresh import FormalRefreshError, load_object, sha256, write_object
from src.research.byd_v1_2_recovery_state import load_canonical_snapshot


class BYDFormalRefreshError(FormalRefreshError):
    """Raised when governed BYD formal inputs or prefixes cannot be extended."""


def _manifest_digest(payload: Mapping[str, Any]) -> str:
    body = dict(payload)
    body.pop("manifest_sha256", None)
    return hashlib.sha256(
        json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _append_rows_preserving_csv_prefix(
    path: Path,
    frame: pd.DataFrame,
    rows: list[dict[str, Any]],
) -> pd.DataFrame:
    if not rows:
        return frame
    extension = pd.DataFrame(rows)
    extension["date"] = pd.to_datetime(extension["date"], errors="raise")
    if extension["date"].duplicated().any():
        raise BYDFormalRefreshError(f"duplicate extension dates for {path.name}")
    if extension["date"].min() <= pd.to_datetime(frame["date"]).max():
        raise BYDFormalRefreshError(f"{path.name} extension must be strictly append-only")
    unknown = sorted(set(extension.columns) - set(frame.columns))
    if unknown:
        raise BYDFormalRefreshError(f"{path.name} extension has unknown columns: {unknown}")
    extension = extension.reindex(columns=frame.columns).sort_values("date")
    persisted = extension.copy()
    persisted["date"] = persisted["date"].dt.strftime("%Y-%m-%d")
    persisted.to_csv(
        path,
        mode="a",
        header=False,
        index=False,
        lineterminator="\n",
        float_format="%.12g",
    )
    return pd.concat([frame, extension], ignore_index=True)


def preserve_verified_prefix(
    field: str,
    current_rows: object,
    candidate_rows: object,
) -> list[dict[str, Any]]:
    """Verify replayed history numerically, then retain accepted rows unchanged."""
    if not isinstance(current_rows, list) or not isinstance(candidate_rows, list):
        raise BYDFormalRefreshError(f"BYD historical {field} is not a row list")
    if len(candidate_rows) < len(current_rows):
        raise BYDFormalRefreshError(f"BYD historical {field} was truncated")
    for index, (current, candidate) in enumerate(zip(current_rows, candidate_rows, strict=False)):
        if not isinstance(current, Mapping) or not isinstance(candidate, Mapping):
            raise BYDFormalRefreshError(f"BYD historical {field}[{index}] is invalid")
        if set(current) != set(candidate):
            raise BYDFormalRefreshError(f"BYD historical {field}[{index}] fields changed")
        for key, expected in current.items():
            actual = candidate[key]
            numeric = (
                isinstance(expected, (int, float))
                and not isinstance(expected, bool)
                and isinstance(actual, (int, float))
                and not isinstance(actual, bool)
            )
            matches = (
                math.isclose(float(expected), float(actual), rel_tol=1e-12, abs_tol=1e-12)
                if numeric
                else expected == actual
            )
            if not matches:
                identity = current.get("date", index)
                raise BYDFormalRefreshError(
                    f"BYD historical {field} changed at {identity}: {key}"
                )
    return [dict(row) for row in current_rows] + [
        dict(row) for row in candidate_rows[len(current_rows) :]
    ]


def extend_byd_input(
    *,
    base_dir: Path,
    shadow_store: Path,
    cutoff: str,
    output_dir: Path,
    validate_base: bool = True,
) -> dict[str, Any]:
    if validate_base:
        load_canonical_snapshot(base_dir)
    shutil.copytree(base_dir, output_dir)
    adjusted_path = output_dir / "adjusted_ohlcv.csv"
    session_path = output_dir / "session_audit.csv"
    manifest_path = output_dir / "manifest.json"
    adjusted = pd.read_csv(adjusted_path, parse_dates=["date"])
    sessions = pd.read_csv(session_path, parse_dates=["date"])
    manifest = load_object(manifest_path)
    base_session_audit_sha256 = sha256(session_path)
    frozen_cutoff = pd.Timestamp(manifest["cutoff"])
    rows: list[dict[str, Any]] = []
    session_rows: list[dict[str, Any]] = []
    observation_hashes: dict[str, str] = {}
    for path in sorted((shadow_store / "observations").glob("*.json")):
        observation = load_object(path)
        signal_date = str(observation.get("signal_date") or path.stem)
        timestamp = pd.Timestamp(signal_date)
        if timestamp <= frozen_cutoff or signal_date > cutoff:
            continue
        chain = observation.get("chain_linked_adjusted_ohlcv")
        if not isinstance(chain, Mapping):
            raise BYDFormalRefreshError(f"BYD adjusted observation is missing: {signal_date}")
        required = ("open", "high", "low", "close", "volume")
        if any(value not in chain for value in required):
            raise BYDFormalRefreshError(f"BYD observation is incomplete: {signal_date}")
        rows.append({"date": signal_date, **{key: float(chain[key]) for key in required}})
        session_rows.append(
            {
                "date": signal_date,
                "open_research_eligible": bool(observation.get("open_research_eligible", False)),
            }
        )
        observation_hashes[signal_date] = sha256(path)
    if not rows or max(row["date"] for row in rows) != cutoff:
        raise BYDFormalRefreshError("BYD prospective observations do not reach target cutoff")
    adjusted = _append_rows_preserving_csv_prefix(adjusted_path, adjusted, rows)
    sessions = _append_rows_preserving_csv_prefix(session_path, sessions, session_rows)
    manifest.update(
        {
            "schema_version": "byd_canonical_adjusted_ohlcv_v2",
            "base_schema_version": str(manifest["schema_version"]),
            "base_adjusted_sha256": str(manifest["adjusted_sha256"]),
            "base_session_audit_sha256": base_session_audit_sha256,
            "base_manifest_sha256": str(manifest["manifest_sha256"]),
            "base_cutoff": str(manifest["cutoff"]),
            "cutoff": cutoff,
            "last_date": cutoff,
            "rows": int(len(adjusted)),
            "adjusted_sha256": sha256(adjusted_path),
            "session_audit_sha256": sha256(session_path),
            "observation_sha256": observation_hashes,
            "source_shadow_manifest_sha256": sha256(shadow_store / "manifest.json"),
        }
    )
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    write_object(manifest_path, manifest)
    return manifest


def extend_etf_input(
    *,
    base_dir: Path,
    paired_store: Path,
    cutoff: str,
    output_dir: Path,
) -> dict[str, Any]:
    shutil.copytree(base_dir, output_dir)
    raw_path = output_dir / "raw_ohlcv.csv"
    adjusted_path = output_dir / "adjusted_ohlcv.csv"
    session_path = output_dir / "session_audit.csv"
    actions_path = output_dir / "corporate_actions.csv"
    manifest_path = output_dir / "manifest.json"
    raw = pd.read_csv(raw_path, parse_dates=["date"])
    adjusted = pd.read_csv(adjusted_path, parse_dates=["date"])
    sessions = pd.read_csv(session_path, parse_dates=["date"])
    actions = pd.read_csv(actions_path, parse_dates=["date"])
    manifest = load_object(manifest_path)
    frozen_cutoff = pd.Timestamp(manifest["cutoff"])
    raw_rows: list[dict[str, Any]] = []
    adjusted_rows: list[dict[str, Any]] = []
    session_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    observation_hashes: dict[str, str] = {}
    for path in sorted((paired_store / "observations").glob("*.json")):
        observation = load_object(path)
        signal_date = str(observation.get("signal_date") or path.stem)
        timestamp = pd.Timestamp(signal_date)
        if timestamp <= frozen_cutoff or signal_date > cutoff:
            continue
        etf = observation.get("etf")
        if not isinstance(etf, Mapping):
            raise BYDFormalRefreshError(f"ETF observation is missing: {signal_date}")
        raw_row = etf.get("primary_raw_ohlcv")
        adjusted_row = etf.get("chain_linked_adjusted_ohlcv")
        if not isinstance(raw_row, Mapping) or not isinstance(adjusted_row, Mapping):
            raise BYDFormalRefreshError(f"ETF observation is incomplete: {signal_date}")
        required = ("open", "high", "low", "close", "volume")
        if any(key not in raw_row or key not in adjusted_row for key in required):
            raise BYDFormalRefreshError(f"ETF OHLCV is incomplete: {signal_date}")
        raw_values = {key: float(raw_row[key]) for key in required}
        adjusted_values = {key: float(adjusted_row[key]) for key in required}
        raw_rows.append({"date": signal_date, **raw_values})
        factor = adjusted_values["close"] / raw_values["close"]
        extension = {column: None for column in adjusted.columns}
        extension.update(
            {
                "date": signal_date,
                **adjusted_values,
                "factor": factor,
                "adjustment_anchor_date": adjusted.iloc[-1].get("adjustment_anchor_date"),
                "adjustment_anchor_factor": adjusted.iloc[-1].get("adjustment_anchor_factor"),
                "price_role": "adjusted_feature_and_label",
            }
        )
        adjusted_rows.append(extension)
        session_rows.append(
            {
                "date": signal_date,
                "open_research_eligible": bool(etf.get("open_research_eligible", False)),
            }
        )
        company_actions = etf.get("company_actions")
        if isinstance(company_actions, Mapping):
            dividend = float(company_actions.get("dividend", 0.0))
            split = float(company_actions.get("stock_split", 0.0))
            if dividend or split:
                action = {column: None for column in actions.columns}
                action.update(
                    {"date": signal_date, "dividend": dividend, "stock_split": split}
                )
                action_rows.append(action)
        observation_hashes[signal_date] = sha256(path)
    if not raw_rows or max(row["date"] for row in raw_rows) != cutoff:
        raise BYDFormalRefreshError("ETF paired observations do not reach target cutoff")
    raw = _append_rows_preserving_csv_prefix(raw_path, raw, raw_rows)
    adjusted = _append_rows_preserving_csv_prefix(adjusted_path, adjusted, adjusted_rows)
    sessions = _append_rows_preserving_csv_prefix(session_path, sessions, session_rows)
    actions = _append_rows_preserving_csv_prefix(actions_path, actions, action_rows)
    manifest.update(
        {
            "schema_version": "cn_etf_canonical_total_return_v2",
            "cutoff": cutoff,
            "last_date": cutoff,
            "rows": int(len(adjusted)),
            "raw_sha256": sha256(raw_path),
            "adjusted_sha256": sha256(adjusted_path),
            "session_audit_sha256": sha256(session_path),
            "corporate_actions_sha256": sha256(actions_path),
            "observation_sha256": observation_hashes,
            "source_paired_manifest_sha256": sha256(paired_store / "manifest.json"),
        }
    )
    manifest["manifest_sha256"] = _manifest_digest(manifest)
    write_object(manifest_path, manifest)
    return manifest
