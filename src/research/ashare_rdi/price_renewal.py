"""Read-only preflight for an append-only RDI price renewal, not admission."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from datetime import date
from importlib.metadata import version

from .phase2 import CSI300_INCEPTION

# Legacy float32/two-decimal observations versus three-decimal index points.
# This is an audit resolution, never authority to repair or overwrite a row.
PRICE_RESOLUTION = 0.01
FIELDS = ("open", "high", "low", "close")


def audit_price_renewal(
    legacy_bytes: bytes, catalog_bytes: bytes, security_bytes: bytes,
    *, completed_cutoff: date,
) -> dict[str, object]:
    """Verify source bindings, sessions and overlap; never write price evidence.

    Even a clean projection preflight still needs original provider bytes/basis
    verification before splice admission. A catalog hash is not that certificate.
    """
    import exchange_calendars as xcals

    catalog, security = json.loads(catalog_bytes), json.loads(security_bytes)
    legacy = list(csv.DictReader(io.StringIO(legacy_bytes.decode("utf-8-sig"))))
    old = [{"time": row["date"][:10], **{k: float(row[k]) for k in FIELDS}}
           for row in legacy if row["date"][:10] >= CSI300_INCEPTION.isoformat()]
    new = security["bars"]
    for rows in (old, new):
        dates = [r["time"] for r in rows]
        if not rows or dates != sorted(set(dates)):
            raise ValueError("price dates must be ordered and unique")
        for row in rows:
            date.fromisoformat(row["time"])
            if (not all(isinstance(row[k], (int, float)) and math.isfinite(row[k])
                        and row[k] > 0 for k in FIELDS)
                    or row["low"] > min(row["open"], row["close"])
                    or row["high"] < max(row["open"], row["close"])):
                raise ValueError("invalid OHLC bar")
    records = [r for r in catalog["symbols"] if r["instrument_id"] == "cn:000300"]
    if len(records) != 1:
        raise ValueError("CSI300 catalog identity must be unique")
    record = records[0]
    def digest(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()
    if not (catalog["market"] == security["market"] == "cn"
            and security["instrument_id"] == "cn:000300"
            and security["symbol"] == security["provider_symbol"] == "000300"
            and "benchmark" in security["roles"]
            and record["path"] == "symbols/000300.json"
            and record["sha256"] == digest(security_bytes)
            and catalog["provider_manifest_sha256"] == security["provider_manifest_sha256"]
            and record["cutoff"] == security["cutoff"] == catalog["cutoff"] == new[-1]["time"]
            and record["start"] == security["start"] == new[0]["time"]
            and all(x.get("research_only") is True and x.get("trade_ready") is False
                    for x in (catalog, security))):
        raise ValueError("governed CSI300 projection identity/hash mismatch")
    for key in ("provider_manifest_sha256", "source_csv_sha256"):
        value = security[key]
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("invalid candidate source digest")
    if date.fromisoformat(new[-1]["time"]) > completed_cutoff:
        raise ValueError("candidate exceeds completed-session cutoff")
    # Explicit bounds prevent the library's moving default history start from
    # dropping 2005; no weekday approximation or gap-filling is allowed.
    calendar = xcals.get_calendar("XSHG", start=old[0]["time"], end=new[-1]["time"])

    def session_audit(rows: list[dict]) -> dict[str, object]:
        expected = {s.date().isoformat() for s in calendar.sessions_in_range(
            rows[0]["time"], rows[-1]["time"])}
        actual = {r["time"] for r in rows}
        return {"missing_sessions": sorted(expected - actual),
                "non_session_bars": sorted(actual - expected)}

    old_sessions, new_sessions = session_audit(old), session_audit(new)
    by_date = {r["time"]: r for r in old}
    overlap = [r for r in new if r["time"] in by_date]
    if not overlap or new[0]["time"] > old[-1]["time"]:
        raise ValueError("candidate must overlap retained history")
    mismatches = []
    for row in overlap:
        differences = {k: abs(row[k] - by_date[row["time"]][k]) for k in FIELDS}
        if max(differences.values()) > PRICE_RESOLUTION:
            mismatches.append({"session": row["time"], "absolute_index_point_differences": differences})
    blockers = []
    if any(old_sessions.values()):
        blockers.append("retained_history_calendar_conflict")
    if any(new_sessions.values()):
        blockers.append("candidate_calendar_conflict")
    if mismatches:
        blockers.append("overlapping_ohlc_conflict")
    if new[-1]["time"] <= old[-1]["time"]:
        blockers.append("no_new_completed_prices")
    # Public chart evidence deliberately does not certify raw source bytes,
    # provider adjustment semantics or historical first availability.
    blockers.append("original_provider_bytes_and_index_price_basis_not_certified")
    return {
        "schema_version": "rdi_price_renewal_preflight_v1",
        "status": "blocked_price_renewal", "blockers": blockers,
        "reference": "CSI300 / 000300.SH", "benchmark_type": "nontraded_equity_index",
        "completed_cutoff": completed_cutoff.isoformat(),
        "calendar": {"id": "XSHG", "package": "exchange_calendars", "version": version("exchange_calendars")},
        "legacy_sha256": digest(legacy_bytes), "catalog_sha256": digest(catalog_bytes),
        "candidate_projection_sha256": digest(security_bytes),
        "provider_manifest_sha256": security["provider_manifest_sha256"],
        "source_csv_sha256_claim": security["source_csv_sha256"],
        "retained_history": {"first_session": old[0]["time"], "cutoff": old[-1]["time"],
                             "rows": len(old), **old_sessions},
        "candidate": {"first_session": new[0]["time"], "cutoff": new[-1]["time"],
                      "rows": len(new), **new_sessions},
        "overlap_rows": len(overlap), "ohlc_resolution_index_points": PRICE_RESOLUTION,
        "overlap_conflicts": mismatches,
        "append_candidate_rows": sum(r["time"] > old[-1]["time"] for r in new),
        "price_splice_written": False, "baseline_recomputed": False,
        "event_history_ready": False, "predictive_skill_established": False,
        "research_only": True, "trade_ready": False,
    }
