"""Create immutable pre-outcome receipts for US x1.1 sector-cap shadow research."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.research.us87_sector_style import (
    load_pool_symbols,
    load_sector_classification,
    sha256_file,
)

SHADOW_CONTRACT_ID = "us_x1_1_sector_cap_shadow_v1"
PROSPECTIVE_BOUNDARY = date(2026, 8, 3)
TOP_N = 15
MAX_NAMES_PER_SECTOR = 4
REQUIRED_SCORE_COLUMNS = (
    "datetime",
    "instrument",
    "score",
    "listed",
    "tradable",
    "suspended",
    "price_available",
)
FORBIDDEN_COLUMN_TOKENS = (
    "return",
    "forward",
    "outcome",
    "pnl",
    "profit",
    "realized",
)


def _canonical_json(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    ).encode("utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            default=str,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    output = frame.copy()
    for column in output.columns:
        if "date" in column or column == "datetime":
            output[column] = pd.to_datetime(output[column]).dt.strftime("%Y-%m-%d")
    path.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(path, index=False, lineterminator="\n", float_format="%.17g")


def _parse_utc(value: str) -> datetime:
    normalized = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("receipt_created_at_utc must include a UTC offset")
    parsed = parsed.astimezone(timezone.utc)
    return parsed


def _parse_bool(series: pd.Series, column: str) -> pd.Series:
    if pd.api.types.is_bool_dtype(series):
        return series.astype(bool)
    mapping = {
        "true": True,
        "false": False,
        "1": True,
        "0": False,
    }
    normalized = series.astype(str).str.strip().str.lower()
    unknown = sorted(set(normalized) - set(mapping))
    if unknown:
        raise ValueError(f"{column} contains invalid boolean values: {unknown}")
    return normalized.map(mapping).astype(bool)


def load_contract(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("shadow contract must be a mapping")
    if payload.get("shadow_contract_id") != SHADOW_CONTRACT_ID:
        raise ValueError("unexpected shadow contract identity")
    boundary = date.fromisoformat(
        str(payload["prospective_boundary"]["first_signal_must_be_strictly_after"])
    )
    if boundary != PROSPECTIVE_BOUNDARY:
        raise ValueError("prospective boundary changed")
    if int(payload["candidate_domain"]["pool_count"]) != 87:
        raise ValueError("shadow contract must retain the exact US87 pool")
    if int(payload["challenger_portfolio"]["maximum_names_per_sector"]) != 4:
        raise ValueError("shadow sector ceiling changed")
    if bool(payload["governance"]["automatic_model_update"]):
        raise ValueError("shadow contract may not auto-update the model")
    return payload


def load_score_snapshot(path: Path, pool_symbols: list[str]) -> tuple[pd.DataFrame, date]:
    frame = pd.read_csv(path)
    if list(frame.columns) != list(REQUIRED_SCORE_COLUMNS):
        raise ValueError(f"score snapshot columns must be exactly {list(REQUIRED_SCORE_COLUMNS)}")
    for column in frame.columns:
        lowered = column.lower()
        if any(token in lowered for token in FORBIDDEN_COLUMN_TOKENS):
            raise ValueError(f"pre-outcome snapshot contains forbidden column: {column}")
    frame["datetime"] = pd.to_datetime(frame["datetime"], errors="raise").dt.normalize()
    dates = frame["datetime"].drop_duplicates().tolist()
    if len(dates) != 1:
        raise ValueError("score snapshot must contain exactly one signal session")
    signal_date = pd.Timestamp(dates[0]).date()
    if signal_date <= PROSPECTIVE_BOUNDARY:
        raise ValueError("signal session is not prospective")
    frame["instrument"] = frame["instrument"].astype(str).str.strip().str.upper()
    if frame.duplicated("instrument").any():
        raise ValueError("score snapshot contains duplicate instruments")
    actual = set(frame["instrument"])
    expected = set(pool_symbols)
    if actual != expected:
        raise ValueError(
            f"score snapshot must cover exact US87: missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )
    if len(frame) != 87:
        raise ValueError("score snapshot must contain exactly 87 rows")
    frame["score"] = pd.to_numeric(frame["score"], errors="raise")
    if not np.isfinite(frame["score"].to_numpy(dtype=float)).all():
        raise ValueError("score snapshot contains non-finite scores")
    for column in ("listed", "tradable", "suspended", "price_available"):
        frame[column] = _parse_bool(frame[column], column)
    frame["eligible"] = (
        frame["listed"] & frame["tradable"] & ~frame["suspended"] & frame["price_available"]
    )
    frame = frame.sort_values(
        ["score", "instrument"],
        ascending=[False, True],
        kind="mergesort",
    ).reset_index(drop=True)
    frame["rank"] = np.arange(1, len(frame) + 1, dtype=int)
    return frame, signal_date


def select_portfolios(
    ranked: pd.DataFrame,
    sector_by_symbol: dict[str, str],
) -> tuple[pd.DataFrame, list[str], list[str], pd.DataFrame]:
    eligible = ranked.loc[ranked["eligible"]].copy()
    if len(eligible) < TOP_N:
        raise ValueError("fewer than 15 eligible names in fixed US87 snapshot")
    baseline = eligible.head(TOP_N)["instrument"].astype(str).tolist()
    challenger: list[str] = []
    sector_counts: dict[str, int] = {}
    reasons: dict[str, str] = {}
    for row in ranked.itertuples(index=False):
        instrument = str(row.instrument)
        sector = sector_by_symbol.get(instrument, "")
        if not sector:
            raise ValueError(f"missing governed sector for {instrument}")
        if not bool(row.eligible):
            reasons[instrument] = "ineligible"
        elif len(challenger) >= TOP_N:
            reasons[instrument] = "after_portfolio_filled"
        elif sector_counts.get(sector, 0) >= MAX_NAMES_PER_SECTOR:
            reasons[instrument] = "sector_cap"
        else:
            challenger.append(instrument)
            sector_counts[sector] = sector_counts.get(sector, 0) + 1
            reasons[instrument] = "selected"
    if len(challenger) != TOP_N:
        raise ValueError("rank-aware sector cap could not fill exactly 15 names")
    if max(sector_counts.values()) > MAX_NAMES_PER_SECTOR:
        raise ValueError("challenger exceeds maximum names per sector")

    audit = ranked.copy()
    audit["sector"] = audit["instrument"].map(sector_by_symbol)
    audit["baseline_selected"] = audit["instrument"].isin(baseline)
    audit["challenger_selected"] = audit["instrument"].isin(challenger)
    audit["challenger_selection_reason"] = audit["instrument"].map(reasons)

    outgoing = audit.loc[audit["baseline_selected"] & ~audit["challenger_selected"]].sort_values(
        "rank"
    )
    incoming = audit.loc[audit["challenger_selected"] & ~audit["baseline_selected"]].sort_values(
        "rank"
    )
    if len(outgoing) != len(incoming):
        raise ValueError("replacement pairs do not balance")
    replacement_rows = []
    for index, (out_row, in_row) in enumerate(
        zip(outgoing.itertuples(index=False), incoming.itertuples(index=False), strict=True),
        start=1,
    ):
        replacement_rows.append(
            {
                "replacement_index": index,
                "out_instrument": str(out_row.instrument),
                "out_rank": int(out_row.rank),
                "out_sector": str(out_row.sector),
                "out_reason": str(out_row.challenger_selection_reason),
                "in_instrument": str(in_row.instrument),
                "in_rank": int(in_row.rank),
                "in_sector": str(in_row.sector),
                "rank_displacement": int(in_row.rank - out_row.rank),
            }
        )
    replacements = pd.DataFrame(
        replacement_rows,
        columns=[
            "replacement_index",
            "out_instrument",
            "out_rank",
            "out_sector",
            "out_reason",
            "in_instrument",
            "in_rank",
            "in_sector",
            "rank_displacement",
        ],
    )
    return audit, baseline, challenger, replacements


def _holdings(names: list[str], sector_by_symbol: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "instrument": names,
            "sector": [sector_by_symbol[name] for name in names],
            "target_weight": [1 / TOP_N] * TOP_N,
        }
    )


def _turnover(current: pd.DataFrame, previous_path: Path | None) -> float:
    current_weights = current.set_index("instrument")["target_weight"]
    if previous_path is None:
        previous_weights = pd.Series(dtype=float)
    else:
        previous = pd.read_csv(previous_path)
        required = {"instrument", "target_weight"}
        if not required.issubset(previous.columns):
            raise ValueError(f"previous holdings missing columns: {sorted(required)}")
        previous_weights = previous.set_index("instrument")["target_weight"].astype(float)
    names = current_weights.index.union(previous_weights.index)
    delta = current_weights.reindex(names, fill_value=0) - previous_weights.reindex(
        names, fill_value=0
    )
    return float(delta.abs().sum() / 2)


def _sector_diagnostics(holdings: pd.DataFrame) -> tuple[pd.DataFrame, float, float]:
    exposure = (
        holdings.groupby("sector", as_index=False)["target_weight"]
        .sum()
        .rename(columns={"target_weight": "sector_weight"})
        .sort_values("sector")
    )
    maximum = float(exposure["sector_weight"].max())
    hhi = float(np.square(exposure["sector_weight"]).sum())
    if maximum > MAX_NAMES_PER_SECTOR / TOP_N + 1e-12:
        raise ValueError("challenger sector exposure exceeds frozen ceiling")
    return exposure, maximum, hhi


def append_receipt_index(index_path: Path, entry: dict[str, Any]) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    if index_path.exists():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("shadow index contains a non-object row")
                existing.append(value)
    if any(row.get("receipt_id") == entry["receipt_id"] for row in existing):
        raise ValueError("receipt identity already exists in append-only index")
    if any(row.get("signal_session_date") == entry["signal_session_date"] for row in existing):
        raise ValueError("signal session already has a frozen receipt")
    with index_path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(_canonical_json(entry).decode("utf-8") + "\n")


def create_receipt(
    *,
    contract_path: Path,
    score_snapshot_path: Path,
    provider_snapshot_identity: str,
    source_data_cutoff: str,
    receipt_created_at_utc: str,
    repository_commit: str,
    workflow_run_id: str,
    output_root: Path,
    index_path: Path,
    previous_baseline_holdings: Path | None = None,
    previous_challenger_holdings: Path | None = None,
) -> dict[str, Any]:
    contract = load_contract(contract_path)
    pool_path = Path(str(contract["candidate_domain"]["pool_path"]))
    classification_path = Path(str(contract["candidate_domain"]["classification_path"]))
    pool = load_pool_symbols(pool_path)
    classification, classification_manifest = load_sector_classification(classification_path, pool)
    classification_sha = sha256_file(classification_path)
    expected_classification_sha = str(contract["candidate_domain"]["classification_file_sha256"])
    if classification_sha != expected_classification_sha:
        raise ValueError("governed classification file identity changed")
    records_sha = str(classification_manifest["records_sha256_verified"])
    if records_sha != str(contract["candidate_domain"]["classification_records_sha256"]):
        raise ValueError("governed classification record identity changed")

    ranked, signal_date = load_score_snapshot(score_snapshot_path, pool)
    cutoff = date.fromisoformat(source_data_cutoff)
    if cutoff > signal_date:
        raise ValueError("source data cutoff is after the signal session")
    created = _parse_utc(receipt_created_at_utc)
    if created.date() < signal_date or created.date() > signal_date + timedelta(days=1):
        raise ValueError("receipt must be created on the signal date or next UTC date")

    sectors = classification.set_index("symbol")["sector"].to_dict()
    audit, baseline_names, challenger_names, replacements = select_portfolios(ranked, sectors)
    baseline = _holdings(baseline_names, sectors)
    challenger = _holdings(challenger_names, sectors)
    sector_exposure, max_sector, sector_hhi = _sector_diagnostics(challenger)
    baseline_turnover = _turnover(baseline, previous_baseline_holdings)
    challenger_turnover = _turnover(challenger, previous_challenger_holdings)

    score_sha = sha256_file(score_snapshot_path)
    identity_payload = {
        "shadow_contract_id": SHADOW_CONTRACT_ID,
        "signal_session_date": signal_date.isoformat(),
        "source_data_cutoff": cutoff.isoformat(),
        "score_input_sha256": score_sha,
        "provider_snapshot_identity": provider_snapshot_identity,
        "repository_commit": repository_commit,
    }
    identity_sha = hashlib.sha256(_canonical_json(identity_payload)).hexdigest()
    receipt_id = f"{SHADOW_CONTRACT_ID}_{signal_date.isoformat()}_{identity_sha[:12]}"
    receipt_root = output_root / receipt_id
    if receipt_root.exists() and any(receipt_root.iterdir()):
        raise ValueError("receipt output already exists and is immutable")
    receipt_root.mkdir(parents=True, exist_ok=True)

    audit_path = receipt_root / "scores_and_selections.csv"
    baseline_path = receipt_root / "baseline_holdings.csv"
    challenger_path = receipt_root / "challenger_holdings.csv"
    replacements_path = receipt_root / "replacement_pairs.csv"
    exposure_path = receipt_root / "challenger_sector_exposure.csv"
    _write_csv(audit_path, audit)
    _write_csv(baseline_path, baseline)
    _write_csv(challenger_path, challenger)
    _write_csv(replacements_path, replacements)
    _write_csv(exposure_path, sector_exposure)

    evidence_paths = (
        audit_path,
        baseline_path,
        challenger_path,
        replacements_path,
        exposure_path,
    )
    files = [
        {
            "path": path.relative_to(receipt_root).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
        }
        for path in evidence_paths
    ]
    overlap = len(set(baseline_names) & set(challenger_names))
    receipt = {
        "schema_version": "1.0",
        "receipt_id": receipt_id,
        "shadow_contract_id": SHADOW_CONTRACT_ID,
        "signal_session_date": signal_date.isoformat(),
        "receipt_created_at_utc": created.isoformat().replace("+00:00", "Z"),
        "source_data_cutoff": cutoff.isoformat(),
        "outcomes_available": False,
        "research_only": True,
        "trade_ready": False,
        "identities": {
            "model_id": "us_x1_1",
            "pool_id": "us_selected_equities_v2",
            "pool_file_sha256": sha256_file(pool_path),
            "classification_file_sha256": classification_sha,
            "classification_records_sha256": records_sha,
            "shadow_contract_file_sha256": sha256_file(contract_path),
            "score_input_sha256": score_sha,
            "provider_snapshot_identity": provider_snapshot_identity,
            "repository_commit": repository_commit,
            "workflow_run_id": workflow_run_id,
        },
        "portfolio_contract": {
            "top_n": TOP_N,
            "equal_weight": True,
            "maximum_names_per_sector": MAX_NAMES_PER_SECTOR,
            "maximum_sector_weight": MAX_NAMES_PER_SECTOR / TOP_N,
            "holding_sessions": 10,
            "rebalance_sessions": 10,
        },
        "summary": {
            "score_rows": len(ranked),
            "eligible_score_rows": int(ranked["eligible"].sum()),
            "baseline_names": len(baseline_names),
            "challenger_names": len(challenger_names),
            "overlap_count": overlap,
            "replacement_count": len(replacements),
            "baseline_expected_turnover": baseline_turnover,
            "challenger_expected_turnover": challenger_turnover,
            "challenger_max_sector_weight": max_sector,
            "challenger_sector_hhi": sector_hhi,
        },
        "files": files,
    }
    receipt_path = receipt_root / "receipt.json"
    _write_json(receipt_path, receipt)
    manifest = {
        "schema_version": "1.0",
        "receipt_id": receipt_id,
        "receipt_sha256": sha256_file(receipt_path),
        "files": files,
    }
    manifest_path = receipt_root / "manifest.json"
    _write_json(manifest_path, manifest)
    index_entry = {
        "receipt_id": receipt_id,
        "signal_session_date": signal_date.isoformat(),
        "receipt_created_at_utc": receipt["receipt_created_at_utc"],
        "receipt_sha256": manifest["receipt_sha256"],
        "manifest_sha256": sha256_file(manifest_path),
        "relative_path": receipt_root.relative_to(output_root).as_posix(),
        "outcomes_available": False,
    }
    append_receipt_index(index_path, index_entry)
    return {
        "receipt": receipt,
        "manifest": manifest,
        "index_entry": index_entry,
        "receipt_root": str(receipt_root),
    }
