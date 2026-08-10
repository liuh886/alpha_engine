"""Outcome-free source admissibility audit for XGBoost v4.25 Phase 0."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class SourceProbe:
    source_id: str
    audit: dict[str, Any]
    availability: pd.DataFrame
    raw_sha256: str | None
    normalized_sha256: str | None


@dataclass(frozen=True)
class NewInformationPhase0Result:
    source_audit: pd.DataFrame
    family_audit: pd.DataFrame
    fold_coverage: pd.DataFrame
    normalized_availability: pd.DataFrame
    source_identity: pd.DataFrame
    decision: str
    admitted_families: tuple[str, ...]
    outcome_calculation_authorized: bool


def _download(url: str, *, timeout: int = 60) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": "AlphaEngine-Research/1.0 (+https://github.com/liuh886/alpha_engine)"
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _digest_frame(frame: pd.DataFrame) -> str:
    payload = frame.to_csv(index=False, date_format="%Y-%m-%d").encode("utf-8")
    return sha256(payload).hexdigest()


def _pick_date_column(frame: pd.DataFrame) -> str:
    normalized = {str(column).strip().upper(): str(column) for column in frame.columns}
    for candidate in ("DATE", "OBSERVATION_DATE", "OBSERVATION DATE"):
        if candidate in normalized:
            return normalized[candidate]
    return str(frame.columns[0])


def _pick_value_column(frame: pd.DataFrame, source: Mapping[str, Any]) -> str:
    series_id = source.get("series_id")
    if series_id and str(series_id) in frame.columns:
        return str(series_id)
    ratio_columns = [str(column) for column in frame.columns if "RATIO" in str(column).upper()]
    if ratio_columns:
        return ratio_columns[-1]
    candidates = [
        str(column) for column in frame.columns if str(column) != _pick_date_column(frame)
    ]
    if not candidates:
        raise ValueError("no numeric source column found")
    return candidates[-1]


def _numeric(series: pd.Series) -> pd.Series:
    clean = (
        series.astype("string")
        .str.strip()
        .str.replace(",", "", regex=False)
        .replace({".": pd.NA, "": pd.NA, "nan": pd.NA})
    )
    return pd.to_numeric(clean, errors="coerce")


def _cboe_computed_ratio(frame: pd.DataFrame) -> pd.Series:
    columns = [str(column) for column in frame.columns]
    call_candidates = [
        column for column in columns if "CALL" in column.upper() and "RATIO" not in column.upper()
    ]
    put_candidates = [
        column for column in columns if "PUT" in column.upper() and "RATIO" not in column.upper()
    ]
    if not call_candidates or not put_candidates:
        if len(columns) < 3:
            return pd.Series(np.nan, index=frame.index, dtype=float)
        call_column, put_column = columns[1], columns[2]
    else:
        call_column, put_column = call_candidates[0], put_candidates[0]
    calls = _numeric(frame[call_column])
    puts = _numeric(frame[put_column])
    return puts.div(calls.replace(0.0, np.nan))


def _parse_csv(raw: bytes, source: Mapping[str, Any]) -> pd.DataFrame:
    frame = pd.read_csv(BytesIO(raw))
    if frame.empty:
        raise ValueError("source CSV is empty")
    frame.columns = [str(column).strip() for column in frame.columns]
    date_column = _pick_date_column(frame)
    value_column = _pick_value_column(frame, source)
    dates = (
        pd.to_datetime(frame[date_column], format="mixed", errors="coerce")
        .dt.tz_localize(None)
        .dt.normalize()
    )
    values = _numeric(frame[value_column])
    if str(source.get("provider")) == "Cboe Exchange":
        values = values.fillna(_cboe_computed_ratio(frame))
    output = pd.DataFrame({"observation_date": dates, "value": values})
    output = output.dropna(subset=["observation_date"]).sort_values("observation_date")
    return output.reset_index(drop=True)


def _safe_decision_dates(
    observation_dates: pd.Series,
    qqq_calendar: pd.DatetimeIndex,
    safe_lag_sessions: int,
) -> pd.Series:
    calendar = pd.DatetimeIndex(qqq_calendar).tz_localize(None).normalize().sort_values()
    values: list[pd.Timestamp | pd.NaT] = []
    for raw in pd.to_datetime(observation_dates):
        date = pd.Timestamp(raw).normalize()
        location = int(calendar.searchsorted(date, side="right")) + max(safe_lag_sessions - 1, 0)
        values.append(calendar[location] if location < len(calendar) else pd.NaT)
    return pd.Series(values, index=observation_dates.index, dtype="datetime64[ns]")


def _maximum_gap_sessions(dates: pd.DatetimeIndex, reference: pd.DatetimeIndex) -> int | None:
    if len(reference) == 0:
        return None
    positions = np.unique(reference.get_indexer(dates))
    positions = positions[positions >= 0]
    boundaries = np.concatenate(
        [np.asarray([-1], dtype=int), positions, np.asarray([len(reference)], dtype=int)]
    )
    return int(np.maximum(np.diff(boundaries) - 1, 0).max())


def _numeric_probe(
    source_id: str,
    source: Mapping[str, Any],
    qqq_calendar: pd.DatetimeIndex,
    contract: Mapping[str, Any],
    fetcher: Callable[[str], bytes],
) -> SourceProbe:
    try:
        raw = fetcher(str(source["url"]))
        parsed = _parse_csv(raw, source)
        raw_hash = sha256(raw).hexdigest()
        duplicate_dates = bool(parsed["observation_date"].duplicated().any())
        availability = parsed[["observation_date"]].copy()
        availability["source_id"] = source_id
        availability["family"] = str(source["family"])
        availability["value_present"] = parsed["value"].notna()
        availability["published_at_class"] = str(source["nominal_timing"])
        availability["safe_lag_qqq_sessions"] = int(source["safe_lag_qqq_sessions"])
        availability["safe_decision_date"] = _safe_decision_dates(
            availability["observation_date"],
            qqq_calendar,
            int(source["safe_lag_qqq_sessions"]),
        )
        normalized_hash = _digest_frame(availability)
        required_start = pd.Timestamp(contract["boundaries"]["required_history_start"])
        required_calendar = qqq_calendar[qqq_calendar >= required_start]
        safe_dates = pd.DatetimeIndex(
            availability.loc[
                availability["value_present"] & availability["safe_decision_date"].notna(),
                "safe_decision_date",
            ].unique()
        ).sort_values()
        covered = safe_dates.intersection(required_calendar)
        coverage = len(covered) / len(required_calendar) if len(required_calendar) else 0.0
        gap = _maximum_gap_sessions(covered, required_calendar)
        valid = parsed.loc[parsed["value"].notna()]
        first = valid["observation_date"].min() if not valid.empty else pd.NaT
        last = valid["observation_date"].max() if not valid.empty else pd.NaT
        revision = str(source["revision_classification"])
        revision_safe = revision in {"non_revising_archive", "vintage_safe"}
        license_classification = str(source["license_classification"])
        license_safe = license_classification not in {
            "documentation_only",
            "unresolved",
        }
        start_pass = bool(pd.notna(first) and first <= required_start)
        coverage_pass = coverage >= float(contract["boundaries"]["minimum_decision_date_coverage"])
        gap_pass = gap is not None and gap <= int(
            contract["boundaries"]["maximum_unexplained_gap_sessions"]
        )
        reasons: list[str] = []
        if duplicate_dates:
            reasons.append("duplicate_observation_dates")
        if not start_pass:
            reasons.append("history_starts_after_required_date")
        if not coverage_pass:
            reasons.append("insufficient_decision_date_coverage")
        if not gap_pass:
            reasons.append("unexplained_gap_exceeds_limit")
        if not revision_safe:
            reasons.append("revision_or_vintage_safety_not_proven")
        if not license_safe:
            reasons.append("license_not_admissible")
        audit = {
            "source_id": source_id,
            "family": str(source["family"]),
            "provider": str(source["provider"]),
            "source_type": str(source["source_type"]),
            "url": str(source["url"]),
            "fetch_succeeded": True,
            "rows": int(len(parsed)),
            "usable_rows": int(parsed["value"].notna().sum()),
            "first_observation_date": first,
            "last_observation_date": last,
            "duplicate_observation_dates": duplicate_dates,
            "decision_date_coverage": float(coverage),
            "maximum_unexplained_gap_sessions": gap,
            "safe_lag_qqq_sessions": int(source["safe_lag_qqq_sessions"]),
            "revision_classification": revision,
            "license_classification": license_classification,
            "raw_sha256": raw_hash,
            "normalized_sha256": normalized_hash,
            "admissible": not reasons,
            "rejection_reason": ",".join(reasons) if reasons else None,
        }
        return SourceProbe(source_id, audit, availability, raw_hash, normalized_hash)
    except Exception as exc:
        audit = {
            "source_id": source_id,
            "family": str(source["family"]),
            "provider": str(source["provider"]),
            "source_type": str(source["source_type"]),
            "url": str(source.get("url", "")),
            "fetch_succeeded": False,
            "rows": 0,
            "usable_rows": 0,
            "first_observation_date": None,
            "last_observation_date": None,
            "duplicate_observation_dates": None,
            "decision_date_coverage": 0.0,
            "maximum_unexplained_gap_sessions": None,
            "safe_lag_qqq_sessions": int(source.get("safe_lag_qqq_sessions", 0)),
            "revision_classification": str(source["revision_classification"]),
            "license_classification": str(source["license_classification"]),
            "raw_sha256": None,
            "normalized_sha256": None,
            "admissible": False,
            "rejection_reason": f"fetch_or_parse_failed:{type(exc).__name__}:{exc}",
        }
        return SourceProbe(source_id, audit, pd.DataFrame(), None, None)


def _non_numeric_probe(source_id: str, source: Mapping[str, Any]) -> SourceProbe:
    source_type = str(source["source_type"])
    reason = (
        "documentation_only_no_numeric_history"
        if source_type == "documentation_only"
        else "canonical_source_unresolved"
    )
    audit = {
        "source_id": source_id,
        "family": str(source["family"]),
        "provider": str(source["provider"]),
        "source_type": source_type,
        "url": str(source.get("url", "")),
        "fetch_succeeded": source_type == "documentation_only",
        "rows": 0,
        "usable_rows": 0,
        "first_observation_date": None,
        "last_observation_date": None,
        "duplicate_observation_dates": None,
        "decision_date_coverage": 0.0,
        "maximum_unexplained_gap_sessions": None,
        "safe_lag_qqq_sessions": int(source.get("safe_lag_qqq_sessions", 0)),
        "revision_classification": str(source["revision_classification"]),
        "license_classification": str(source["license_classification"]),
        "raw_sha256": None,
        "normalized_sha256": None,
        "admissible": False,
        "rejection_reason": reason,
    }
    return SourceProbe(source_id, audit, pd.DataFrame(), None, None)


def run_new_information_phase0(
    qqq_calendar: pd.DatetimeIndex,
    contract: Mapping[str, Any],
    *,
    fetcher: Callable[[str], bytes] = _download,
) -> NewInformationPhase0Result:
    calendar = pd.DatetimeIndex(qqq_calendar).tz_localize(None).normalize().sort_values()
    probes: dict[str, SourceProbe] = {}
    for source_id, source in contract["sources"].items():
        probes[source_id] = (
            _numeric_probe(source_id, source, calendar, contract, fetcher)
            if str(source["source_type"]) == "csv"
            else _non_numeric_probe(source_id, source)
        )
    source_audit = pd.DataFrame([probe.audit for probe in probes.values()])
    availability_parts = [
        probe.availability for probe in probes.values() if not probe.availability.empty
    ]
    normalized_availability = (
        pd.concat(availability_parts, ignore_index=True)
        if availability_parts
        else pd.DataFrame(
            columns=[
                "observation_date",
                "source_id",
                "family",
                "value_present",
                "published_at_class",
                "safe_lag_qqq_sessions",
                "safe_decision_date",
            ]
        )
    )

    family_rows: list[dict[str, Any]] = []
    admitted: list[str] = []
    audit_lookup = source_audit.set_index("source_id")
    for family, specification in contract["families"].items():
        required = [str(value) for value in specification["required_sources"]]
        rejected = [
            source_id
            for source_id in required
            if source_id not in audit_lookup.index
            or not bool(audit_lookup.loc[source_id, "admissible"])
        ]
        passed = not rejected
        if passed:
            admitted.append(str(family))
        family_rows.append(
            {
                "family": str(family),
                "required_sources": ",".join(required),
                "rejected_sources": ",".join(rejected),
                "minimum_distinct_features": int(specification["minimum_distinct_features"]),
                "existing_feature_overlap_audit": (
                    "deferred_until_upstream_source_admissibility"
                    if rejected
                    else "required_before_phase1_contract"
                ),
                "admissible": passed,
                "rejection_reason": (
                    f"required_sources_inadmissible:{','.join(rejected)}" if rejected else None
                ),
            }
        )
    family_audit = pd.DataFrame(family_rows)

    fold_rows: list[dict[str, Any]] = []
    for source_id, probe in probes.items():
        source = contract["sources"][source_id]
        safe_dates = (
            pd.DatetimeIndex(
                probe.availability.loc[
                    probe.availability.get(
                        "value_present", pd.Series(False, index=probe.availability.index)
                    ).astype(bool)
                    & probe.availability.get(
                        "safe_decision_date", pd.Series(pd.NaT, index=probe.availability.index)
                    ).notna(),
                    "safe_decision_date",
                ].unique()
            )
            if not probe.availability.empty
            else pd.DatetimeIndex([])
        )
        for fold in contract["folds"]:
            start = pd.Timestamp(fold["start"])
            end = pd.Timestamp(fold["end"]) if fold.get("end") else calendar.max()
            reference = calendar[(calendar >= start) & (calendar <= end)]
            observed = safe_dates.intersection(reference)
            fold_rows.append(
                {
                    "source_id": source_id,
                    "family": str(source["family"]),
                    "fold": str(fold["fold"]),
                    "reference_sessions": int(len(reference)),
                    "covered_sessions": int(len(observed)),
                    "coverage": (float(len(observed) / len(reference)) if len(reference) else 0.0),
                    "non_empty": bool(len(observed)),
                }
            )
    fold_coverage = pd.DataFrame(fold_rows)

    identity = source_audit[
        [
            "source_id",
            "provider",
            "source_type",
            "url",
            "raw_sha256",
            "normalized_sha256",
            "license_classification",
            "revision_classification",
        ]
    ].copy()
    if not admitted:
        decision = str(contract["decision_taxonomy"]["none"])
    elif len(admitted) > 1:
        decision = str(contract["decision_taxonomy"]["multiple"])
    else:
        decision = str(contract["decision_taxonomy"][admitted[0]])
    return NewInformationPhase0Result(
        source_audit=source_audit,
        family_audit=family_audit,
        fold_coverage=fold_coverage,
        normalized_availability=normalized_availability,
        source_identity=identity,
        decision=decision,
        admitted_families=tuple(admitted),
        outcome_calculation_authorized=False,
    )
