"""Fail closed when a published formal backtest is older than its market cutoff."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import exchange_calendars as xcals  # type: ignore[import-untyped]
import pandas as pd


class FormalBacktestFreshnessError(ValueError):
    """Raised when the formal publication set is stale or internally inconsistent."""


def _object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalBacktestFreshnessError(f"invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise FormalBacktestFreshnessError(f"JSON root must be an object: {path}")
    return payload


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _string_set(
    payload: dict[str, Any], key: str, *, allow_empty: bool = False
) -> set[str]:
    values = payload.get(key)
    if not isinstance(values, list) or (not values and not allow_empty):
        raise FormalBacktestFreshnessError(f"{key} is missing")
    result = {str(value) for value in values}
    if len(result) != len(values):
        raise FormalBacktestFreshnessError(f"{key} contains duplicates")
    return result


def _as_of(value: str | None) -> pd.Timestamp | None:
    if value is None:
        return None
    if value == "now":
        return pd.Timestamp(datetime.now(timezone.utc))
    try:
        parsed = pd.Timestamp(value)
    except ValueError as exc:
        raise FormalBacktestFreshnessError(f"invalid as-of timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise FormalBacktestFreshnessError("as-of timestamp must include a timezone")
    return parsed.tz_convert("UTC")


def latest_completed_session(calendar_name: str, as_of: pd.Timestamp) -> str:
    try:
        calendar = xcals.get_calendar(calendar_name)
    except (KeyError, ValueError) as exc:
        raise FormalBacktestFreshnessError(
            f"unknown exchange calendar: {calendar_name}"
        ) from exc
    start = (as_of - pd.Timedelta(days=21)).tz_localize(None).normalize()
    end = (as_of + pd.Timedelta(days=1)).tz_localize(None).normalize()
    try:
        sessions = calendar.sessions_in_range(start, end)
        closes = calendar.schedule.loc[sessions, "close"]
    except (KeyError, ValueError) as exc:
        raise FormalBacktestFreshnessError(
            f"unable to resolve calendar {calendar_name} around {as_of.isoformat()}"
        ) from exc
    completed = sessions[closes <= as_of]
    if completed.empty:
        raise FormalBacktestFreshnessError(
            f"calendar {calendar_name} has no completed session near {as_of.isoformat()}"
        )
    return pd.Timestamp(completed[-1]).strftime("%Y-%m-%d")


def verify(root: Path, *, as_of: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    policy = _object(root / "freshness.json")
    catalog = _object(root / "catalog.json")
    if policy.get("cutoff_policy") != "latest_completed_trading_session":
        raise FormalBacktestFreshnessError("unsupported cutoff policy")
    if policy.get("research_only") is not True or policy.get("trade_ready") is not False:
        raise FormalBacktestFreshnessError("freshness policy weakens research boundary")

    markets = policy.get("markets")
    calendar_names = policy.get("market_calendars")
    records = catalog.get("records")
    if not isinstance(markets, dict) or not markets:
        raise FormalBacktestFreshnessError("market cutoffs are missing")
    if not isinstance(calendar_names, dict) or set(calendar_names) != set(markets):
        raise FormalBacktestFreshnessError("market calendar bindings are incomplete")
    if not isinstance(records, list):
        raise FormalBacktestFreshnessError("formal catalog records are missing")
    required = _string_set(policy, "required_models")
    receipt_required = _string_set(
        policy, "freshness_receipt_required_models", allow_empty=True
    )
    end_required = _string_set(
        policy, "date_range_end_required_models", allow_empty=True
    )
    if not receipt_required.issubset(required) or not end_required.issubset(required):
        raise FormalBacktestFreshnessError(
            "freshness receipt/date-end requirements exceed required_models"
        )

    parsed_as_of = _as_of(as_of)
    resolved_sessions: dict[str, str] = {}
    if parsed_as_of is not None:
        for market, calendar_name in calendar_names.items():
            resolved = latest_completed_session(str(calendar_name), parsed_as_of)
            declared = str(markets.get(market) or "")
            resolved_sessions[str(market)] = resolved
            if declared != resolved:
                raise FormalBacktestFreshnessError(
                    f"{market}: declared cutoff {declared!r} is stale; "
                    f"latest completed {calendar_name} session is {resolved}"
                )

    by_id = {
        str(row.get("model_id")): row
        for row in records
        if isinstance(row, dict) and row.get("model_id")
    }
    if set(by_id) != required:
        raise FormalBacktestFreshnessError(
            "formal catalog does not exactly match freshness required_models"
        )

    verified: list[dict[str, Any]] = []
    for model_id in sorted(required):
        record = by_id[model_id]
        package_path = root / str(record.get("path") or "")
        if not package_path.is_file():
            raise FormalBacktestFreshnessError(f"{model_id}: package is missing")
        observed_hash = _sha256(package_path)
        if observed_hash != record.get("sha256"):
            raise FormalBacktestFreshnessError(f"{model_id}: catalog SHA-256 mismatch")

        package = _object(package_path)
        if package.get("model_id") != model_id:
            raise FormalBacktestFreshnessError(f"{model_id}: package identity mismatch")
        if package.get("publication_status") != "accepted_formal_baseline":
            raise FormalBacktestFreshnessError(f"{model_id}: not an accepted baseline")
        if package.get("research_only") is not True or package.get("trade_ready") is not False:
            raise FormalBacktestFreshnessError(f"{model_id}: research boundary mismatch")

        market = str(package.get("market") or "")
        expected = str(markets.get(market) or "")
        if not expected:
            raise FormalBacktestFreshnessError(
                f"{model_id}: no cutoff for market {market!r}"
            )
        actual = str(package.get("evidence_cutoff") or "")
        if actual != expected:
            raise FormalBacktestFreshnessError(
                f"{model_id}: stale formal package; expected evidence_cutoff "
                f"{expected}, found {actual!r}"
            )

        date_range = package.get("date_range")
        end = str(date_range.get("end") or "") if isinstance(date_range, dict) else ""
        if not end or end > expected:
            raise FormalBacktestFreshnessError(
                f"{model_id}: invalid date_range.end={end!r} for cutoff {expected}"
            )
        if model_id in end_required and end != expected:
            raise FormalBacktestFreshnessError(
                f"{model_id}: stale reporting range; expected {expected}, found {end!r}"
            )

        if model_id in receipt_required:
            freshness = package.get("freshness")
            if not isinstance(freshness, dict):
                raise FormalBacktestFreshnessError(
                    f"{model_id}: freshness receipt is missing"
                )
            if freshness.get("status") != "current":
                raise FormalBacktestFreshnessError(
                    f"{model_id}: freshness status is not current"
                )
            if freshness.get("required_cutoff") != expected:
                raise FormalBacktestFreshnessError(
                    f"{model_id}: freshness cutoff mismatch"
                )
            if freshness.get("latest_completed_session") != expected:
                raise FormalBacktestFreshnessError(
                    f"{model_id}: latest session mismatch"
                )
            realized_end = str(freshness.get("latest_realized_holding_end") or "")
            if not realized_end or realized_end > expected:
                raise FormalBacktestFreshnessError(
                    f"{model_id}: invalid realized holding end {realized_end!r}"
                )
            if freshness.get("model_selection_reopened") is not False:
                raise FormalBacktestFreshnessError(
                    f"{model_id}: freshness update reopened model selection"
                )

        verified.append(
            {
                "model_id": model_id,
                "market": market,
                "required_cutoff": expected,
                "date_range_end": end,
                "package_sha256": observed_hash,
                "freshness_receipt_required": model_id in receipt_required,
            }
        )

    return {
        "schema_version": "1.0.0",
        "status": "current",
        "cutoff_policy": policy["cutoff_policy"],
        "as_of": parsed_as_of.isoformat() if parsed_as_of is not None else None,
        "resolved_latest_sessions": resolved_sessions,
        "verified_models": verified,
        "research_only": True,
        "trade_ready": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("data/research/formal_backtests"),
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="Timezone-aware timestamp or 'now'; when supplied, verify exchange calendars.",
    )
    parser.add_argument("--receipt", type=Path, default=None)
    args = parser.parse_args()
    receipt = verify(args.root, as_of=args.as_of)
    encoded = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.receipt is not None:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(encoded, encoding="utf-8")
    print(encoded, end="")


if __name__ == "__main__":
    main()
