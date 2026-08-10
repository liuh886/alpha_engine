"""Source-neutral quality gates for the frozen A-share structured pool."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd
import yaml

from src.research.focus_watchlist_signal import canonical_sha256, sha256_file
from src.research.research_artifacts import write_json

BAR_OUTPUT = "cn_pool_bars.csv"
STATUS_OUTPUT = "cn_pool_status.csv"
CALENDAR_OUTPUT = "cn_trading_calendar.csv"
MANIFEST_OUTPUT = "provider_manifest.json"
QUALITY_OUTPUT = "data_quality_report.json"
DECISION_OUTPUT = "decision.json"
BOOLEAN_STATUS_FIELDS = (
    "listed",
    "suspended",
    "st",
    "delisted",
    "limit_up_at_open",
    "limit_down_at_open",
    "tradable_at_open",
)


def _load_yaml(path: str | Path, *, label: str) -> dict[str, Any]:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a YAML mapping")
    return payload


def _repository_root(contract_path: Path) -> Path:
    resolved = contract_path.resolve()
    if len(resolved.parents) < 3:
        raise ValueError(f"cannot resolve repository root from {contract_path}")
    return resolved.parents[2]


def _candidate_symbols(pool: Mapping[str, Any]) -> list[str]:
    return [
        str(symbol)
        for basket in pool.get("baskets", {}).values()
        for symbol in basket.get("symbols", [])
    ]


def _reference_symbols(pool: Mapping[str, Any]) -> list[str]:
    return [str(symbol) for symbol in pool.get("references", {})]


def _alias_map(pool: Mapping[str, Any]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    metadata_rows: dict[str, Any] = {
        **dict(pool.get("references", {})),
        **dict(pool.get("symbol_metadata", {})),
    }
    for canonical, metadata in metadata_rows.items():
        canonical_key = str(canonical).strip().upper()
        aliases[canonical_key] = canonical_key
        provider_key = str(metadata.get("provider_symbol", canonical)).strip().upper()
        existing = aliases.get(provider_key)
        if existing is not None and existing != canonical_key:
            raise ValueError(
                f"provider alias collision for {provider_key}: {existing}, {canonical_key}"
            )
        aliases[provider_key] = canonical_key
    return aliases


def validate_cn_provider_contract(
    contract: Mapping[str, Any],
    pool: Mapping[str, Any],
    research: Mapping[str, Any],
) -> None:
    if str(contract.get("market")) != "cn" or str(pool.get("market")) != "cn":
        raise ValueError("CN provider contract and pool must use market=cn")
    if str(pool.get("status")) != "frozen":
        raise ValueError("CN provider requires a frozen pool")
    if pool.get("authoritative_for_performance") is not True:
        raise ValueError("CN provider requires an authoritative frozen pool")
    if research.get("authoritative_validation_allowed") is not True:
        raise ValueError("CN research spec must allow authoritative validation")
    if str(research.get("pool_spec")) != str(contract.get("pool_spec")):
        raise ValueError("provider and research spec must reference the same pool")
    if contract.get("performance_calculation_allowed") is not False:
        raise ValueError("provider stage cannot calculate strategy performance")

    candidates = _candidate_symbols(pool)
    references = _reference_symbols(pool)
    identity = contract.get("identity", {})
    if len(candidates) != int(identity.get("expected_candidate_count", -1)):
        raise ValueError("frozen candidate count does not match provider contract")
    if len(references) != int(identity.get("expected_reference_count", -1)):
        raise ValueError("reference count does not match provider contract")
    if len(candidates) != len(set(candidates)):
        raise ValueError("frozen candidate membership is not unique")
    if set(candidates).intersection(references):
        raise ValueError("references cannot be candidate securities")
    if str(identity.get("benchmark")) not in references:
        raise ValueError("provider benchmark is absent from frozen pool references")
    if str(identity.get("style_context")) not in references:
        raise ValueError("provider style context is absent from frozen pool references")


def load_cn_provider_contract(
    contract_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path, Path, Path]:
    resolved_contract = Path(contract_path).resolve()
    contract = _load_yaml(resolved_contract, label="CN provider contract")
    root = _repository_root(resolved_contract)
    pool_path = root / str(contract["pool_spec"])
    research_path = root / str(contract["research_spec"])
    pool = _load_yaml(pool_path, label="CN frozen pool")
    research = _load_yaml(research_path, label="CN rotation research spec")
    validate_cn_provider_contract(contract, pool, research)
    return contract, pool, research, resolved_contract, pool_path, research_path


def _normalise_columns(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    output.columns = [str(column).strip().lower() for column in output.columns]
    return output


def _normalise_symbols(frame: pd.DataFrame, aliases: Mapping[str, str]) -> pd.DataFrame:
    output = frame.copy()
    output["symbol"] = output["symbol"].astype("string").astype(str).str.strip().str.upper()
    output["symbol"] = output["symbol"].replace(dict(aliases))
    return output


def _parse_dates_and_cutoff(
    frame: pd.DataFrame,
    *,
    reserved_start: pd.Timestamp,
) -> tuple[pd.DataFrame, int]:
    output = frame.copy()
    output["date"] = pd.to_datetime(output["date"], errors="raise").dt.normalize()
    excluded = int((output["date"] >= reserved_start).sum())
    output = output.loc[output["date"] < reserved_start].copy()
    if output.empty:
        raise ValueError("input contains no rows before the reserved evidence boundary")
    return output, excluded


def _coerce_bool(value: Any, *, field: str) -> bool:
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, float, np.integer, np.floating)) and value in (0, 1):
        return bool(int(value))
    if pd.isna(value):
        raise ValueError(f"boolean field {field} contains missing values")
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y"}:
        return True
    if text in {"0", "false", "f", "no", "n"}:
        return False
    raise ValueError(f"boolean field {field} contains invalid value: {value!r}")


def _coerce_bool_columns(frame: pd.DataFrame, fields: tuple[str, ...]) -> pd.DataFrame:
    output = frame.copy()
    for field in fields:
        output[field] = [_coerce_bool(value, field=field) for value in output[field]]
    return output


def _validate_required_identities(
    frame: pd.DataFrame,
    required: set[str],
    *,
    label: str,
) -> None:
    available = set(frame["symbol"].unique())
    missing = sorted(required - available)
    extra = sorted(available - required)
    if missing:
        raise ValueError(f"{label} missing required identities: {missing}")
    if extra:
        raise ValueError(f"{label} contains unconfigured identities: {extra}")


def _required_columns(
    frame: pd.DataFrame,
    columns: list[str],
    *,
    label: str,
) -> pd.DataFrame:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"{label} missing columns: {missing}")
    return frame[columns].copy()


def _load_bars(
    path: str | Path,
    *,
    contract: Mapping[str, Any],
    pool: Mapping[str, Any],
    reserved_start: pd.Timestamp,
) -> tuple[pd.DataFrame, int]:
    frame = pd.read_csv(path, dtype={"symbol": "string"})
    frame = _normalise_columns(frame)
    columns = [str(value) for value in contract["required_bar_columns"]]
    frame = _required_columns(frame, columns, label="bar CSV")
    frame, excluded = _parse_dates_and_cutoff(frame, reserved_start=reserved_start)
    frame = _normalise_symbols(frame, _alias_map(pool))

    for column in ("open", "high", "low", "close", "volume", "amount"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    if frame[["open", "high", "low", "close", "volume"]].isna().any().any():
        raise ValueError("bar CSV contains missing or non-numeric required values")
    if frame.duplicated(["date", "symbol"]).any():
        raise ValueError("bar CSV contains duplicate date/symbol rows")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError("bar CSV contains non-positive prices")
    if (frame["volume"] < 0).any():
        raise ValueError("bar CSV contains negative volume")
    invalid_ohlc = (frame["high"] < frame[["open", "low", "close"]].max(axis=1)) | (
        frame["low"] > frame[["open", "high", "close"]].min(axis=1)
    )
    if invalid_ohlc.any():
        raise ValueError("bar CSV violates OHLC internal consistency")

    candidates = set(_candidate_symbols(pool))
    references = set(_reference_symbols(pool))
    _validate_required_identities(frame, candidates | references, label="bar CSV")

    frame["adjustment_convention"] = (
        frame["adjustment_convention"].astype(str).str.strip().str.lower()
    )
    frame["source_bar_provider"] = frame["source_bar_provider"].astype(str).str.strip().str.lower()
    if (frame["source_bar_provider"] == "").any():
        raise ValueError("bar CSV contains blank source_bar_provider")

    stock_rows = frame[frame["symbol"].isin(candidates)]
    reference_rows = frame[frame["symbol"].isin(references)]
    expected_stock = str(contract["source_roles"]["stock_bars"]["adjustment_convention"])
    expected_reference = str(contract["source_roles"]["reference_bars"]["adjustment_convention"])
    if set(stock_rows["adjustment_convention"].unique()) != {expected_stock}:
        raise ValueError("candidate bars must use one declared adjustment convention")
    if set(reference_rows["adjustment_convention"].unique()) != {expected_reference}:
        raise ValueError("reference bars must use the declared index convention")
    if stock_rows["source_bar_provider"].nunique() != 1:
        raise ValueError("candidate bars must use one provider identity")
    if reference_rows["source_bar_provider"].nunique() != 1:
        raise ValueError("reference bars must use one provider identity")
    return frame.sort_values(["symbol", "date"]).reset_index(drop=True), excluded


def _load_status(
    path: str | Path,
    *,
    contract: Mapping[str, Any],
    pool: Mapping[str, Any],
    reserved_start: pd.Timestamp,
) -> tuple[pd.DataFrame, int]:
    frame = pd.read_csv(path, dtype={"symbol": "string"})
    frame = _normalise_columns(frame)
    columns = [str(value) for value in contract["required_status_columns"]]
    frame = _required_columns(frame, columns, label="status CSV")
    frame, excluded = _parse_dates_and_cutoff(frame, reserved_start=reserved_start)
    frame = _normalise_symbols(frame, _alias_map(pool))
    frame = _coerce_bool_columns(frame, BOOLEAN_STATUS_FIELDS)
    frame["source_status_provider"] = (
        frame["source_status_provider"].astype(str).str.strip().str.lower()
    )
    if frame.duplicated(["date", "symbol"]).any():
        raise ValueError("status CSV contains duplicate date/symbol rows")
    if (frame["source_status_provider"] == "").any():
        raise ValueError("status CSV contains blank provider identity")
    if frame["source_status_provider"].nunique() != 1:
        raise ValueError("status CSV must use one point-in-time provider identity")

    required = set(_candidate_symbols(pool)) | set(_reference_symbols(pool))
    _validate_required_identities(frame, required, label="status CSV")
    if (frame["limit_up_at_open"] & frame["limit_down_at_open"]).any():
        raise ValueError("status CSV marks simultaneous limit-up and limit-down")
    contradictory = frame["tradable_at_open"] & (
        ~frame["listed"] | frame["suspended"] | frame["delisted"]
    )
    if contradictory.any():
        raise ValueError("status CSV contains logically impossible tradable rows")
    return frame.sort_values(["symbol", "date"]).reset_index(drop=True), excluded


def _load_calendar(
    path: str | Path,
    *,
    contract: Mapping[str, Any],
    reserved_start: pd.Timestamp,
) -> tuple[pd.DataFrame, int]:
    frame = _normalise_columns(pd.read_csv(path))
    columns = [str(value) for value in contract["required_calendar_columns"]]
    frame = _required_columns(frame, columns, label="calendar CSV")
    frame, excluded = _parse_dates_and_cutoff(frame, reserved_start=reserved_start)
    frame = _coerce_bool_columns(frame, ("is_open",))
    frame["source_calendar_provider"] = (
        frame["source_calendar_provider"].astype(str).str.strip().str.lower()
    )
    if frame.duplicated(["date"]).any():
        raise ValueError("calendar CSV contains duplicate dates")
    if (frame["source_calendar_provider"] == "").any():
        raise ValueError("calendar CSV contains blank provider identity")
    if frame["source_calendar_provider"].nunique() != 1:
        raise ValueError("calendar CSV must use one provider identity")
    if not frame["is_open"].any():
        raise ValueError("calendar CSV contains no open trading sessions")
    return frame.sort_values("date").reset_index(drop=True), excluded


def _validate_cross_file_consistency(
    bars: pd.DataFrame,
    status: pd.DataFrame,
    calendar: pd.DataFrame,
) -> None:
    open_dates = set(calendar.loc[calendar["is_open"], "date"])
    if not set(bars["date"]).issubset(open_dates):
        raise ValueError("bar CSV contains dates absent from the open trading calendar")
    if not set(status["date"]).issubset(open_dates):
        raise ValueError("status CSV contains dates absent from the open trading calendar")

    joined = bars.merge(
        status,
        on=["date", "symbol"],
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    if (joined["_merge"] != "both").any():
        raise ValueError("every bar row must have a point-in-time status row")
    if (joined["suspended"] | ~joined["listed"] | joined["delisted"]).any():
        raise ValueError("bar CSV contains a bar on an ineligible or suspended session")


def _date_range(frame: pd.DataFrame) -> dict[str, str | None]:
    if frame.empty:
        return {"first": None, "last": None}
    return {
        "first": pd.Timestamp(frame["date"].min()).date().isoformat(),
        "last": pd.Timestamp(frame["date"].max()).date().isoformat(),
    }


def _providers(
    bars: pd.DataFrame,
    status: pd.DataFrame,
    calendar: pd.DataFrame,
    *,
    candidates: list[str],
    references: list[str],
) -> dict[str, list[str]]:
    return {
        "stock_bars": sorted(
            bars.loc[bars["symbol"].isin(candidates), "source_bar_provider"].unique()
        ),
        "reference_bars": sorted(
            bars.loc[bars["symbol"].isin(references), "source_bar_provider"].unique()
        ),
        "status": sorted(status["source_status_provider"].unique()),
        "calendar": sorted(calendar["source_calendar_provider"].unique()),
    }


def build_cn_pool_provider(
    *,
    contract_path: str | Path,
    bars_csv: str | Path,
    status_csv: str | Path,
    calendar_csv: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    contract, pool, research, resolved_contract, pool_path, research_path = (
        load_cn_provider_contract(contract_path)
    )
    reserved_start = pd.Timestamp(contract["reserved_evidence"]["independent_reserved_start"])
    bars, excluded_bars = _load_bars(
        bars_csv,
        contract=contract,
        pool=pool,
        reserved_start=reserved_start,
    )
    status, excluded_status = _load_status(
        status_csv,
        contract=contract,
        pool=pool,
        reserved_start=reserved_start,
    )
    calendar, excluded_calendar = _load_calendar(
        calendar_csv,
        contract=contract,
        reserved_start=reserved_start,
    )
    _validate_cross_file_consistency(bars, status, calendar)

    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    bars_path = output / BAR_OUTPUT
    status_path = output / STATUS_OUTPUT
    calendar_path = output / CALENDAR_OUTPUT
    bars.to_csv(bars_path, index=False)
    status.to_csv(status_path, index=False)
    calendar.to_csv(calendar_path, index=False)

    candidates = _candidate_symbols(pool)
    references = _reference_symbols(pool)
    required = candidates + references
    first_eligible_dates: dict[str, str | None] = {}
    for symbol in required:
        eligible = status[(status["symbol"] == symbol) & status["listed"] & ~status["delisted"]]
        first_eligible_dates[symbol] = (
            None if eligible.empty else pd.Timestamp(eligible["date"].min()).date().isoformat()
        )

    quality = {
        "schema_version": "1.0",
        "provider_contract_id": contract["provider_contract_id"],
        "decision": "contract_input_pass",
        "market": "cn",
        "pool_id": pool["pool_id"],
        "candidate_count": len(candidates),
        "reference_count": len(references),
        "bar_row_count": int(len(bars)),
        "status_row_count": int(len(status)),
        "calendar_row_count": int(len(calendar)),
        "open_calendar_session_count": int(calendar["is_open"].sum()),
        "bar_date_range": _date_range(bars),
        "status_date_range": _date_range(status),
        "calendar_date_range": _date_range(calendar),
        "excluded_reserved_rows": {
            "bars": excluded_bars,
            "status": excluded_status,
            "calendar": excluded_calendar,
        },
        "providers": _providers(
            bars,
            status,
            calendar,
            candidates=candidates,
            references=references,
        ),
        "first_eligible_dates": first_eligible_dates,
        "missing_required_identities": [],
        "duplicate_rows": 0,
        "logical_status_violations": 0,
        "provider_contract_passed": True,
        "live_provider_run_completed": False,
        "source_attestation_verified": False,
        "performance_evaluated": False,
        "reserved_performance_opened": False,
    }
    write_json(output / QUALITY_OUTPUT, quality)

    decision = {
        "schema_version": "1.0",
        "provider_contract_id": contract["provider_contract_id"],
        "decision": contract["completion_decision"]["pass"],
        "market": "cn",
        "pool_id": pool["pool_id"],
        "research_experiment_id": research["experiment_id"],
        "candidate_count": len(candidates),
        "reference_count": len(references),
        "provider_contract_passed": True,
        "live_provider_run_completed": False,
        "source_attestation_verified": False,
        "authoritative_provider_artifact": False,
        "research_only": True,
        "trade_ready": False,
        "performance_evaluated": False,
        "reserved_performance_opened": False,
    }
    write_json(output / DECISION_OUTPUT, decision)

    output_hashes = {
        filename: sha256_file(output / filename)
        for filename in (
            BAR_OUTPUT,
            STATUS_OUTPUT,
            CALENDAR_OUTPUT,
            QUALITY_OUTPUT,
            DECISION_OUTPUT,
        )
    }
    membership_payload = {
        "pool_id": pool["pool_id"],
        "baskets": pool["baskets"],
        "references": pool["references"],
        "symbol_metadata": pool["symbol_metadata"],
    }
    input_hashes = {
        "bars_csv": {
            "path": str(Path(bars_csv).resolve()),
            "sha256": sha256_file(bars_csv),
        },
        "status_csv": {
            "path": str(Path(status_csv).resolve()),
            "sha256": sha256_file(status_csv),
        },
        "calendar_csv": {
            "path": str(Path(calendar_csv).resolve()),
            "sha256": sha256_file(calendar_csv),
        },
    }
    contract_hashes = {
        "provider_contract_sha256": sha256_file(resolved_contract),
        "pool_file_sha256": sha256_file(pool_path),
        "research_spec_sha256": sha256_file(research_path),
        "membership_identity_sha256": canonical_sha256(membership_payload),
    }
    manifest = {
        "schema_version": "1.0",
        "provider_contract_id": contract["provider_contract_id"],
        "market": "cn",
        "pool_id": pool["pool_id"],
        "research_experiment_id": research["experiment_id"],
        "reserved_start": reserved_start.date().isoformat(),
        "inputs": input_hashes,
        "contracts": contract_hashes,
        "outputs": output_hashes,
        "manifest_identity_sha256": canonical_sha256(
            {
                "inputs": input_hashes,
                "contracts": contract_hashes,
                "outputs": output_hashes,
            }
        ),
        "provider_contract_passed": True,
        "live_provider_run_completed": False,
        "source_attestation_verified": False,
        "performance_evaluated": False,
        "reserved_performance_opened": False,
    }
    write_json(output / MANIFEST_OUTPUT, manifest)
    return decision
