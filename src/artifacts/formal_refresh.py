"""Catalog-driven formal backtest refresh transaction contracts.

The refresh system never edits accepted evidence in place. It builds a complete
candidate publication tree, verifies immutable historical prefixes and model
contracts, then opens a review pull request. The accepted formal catalog is the
only source of model membership; a second workflow allow-list is rejected.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


class FormalRefreshError(ValueError):
    """Raised when a refresh candidate violates the publication contract."""


@dataclass(frozen=True)
class FormalModelRecord:
    model_id: str
    display_name: str
    display_order: int
    path: str
    market: str
    current_cutoff: str


@dataclass(frozen=True)
class FormalRefreshPlan:
    generated_at: str
    target_cutoffs: dict[str, str]
    models: tuple[FormalModelRecord, ...]
    stale_model_ids: tuple[str, ...]

    @property
    def refresh_required(self) -> bool:
        return bool(self.stale_model_ids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "formal_refresh_plan_v1",
            "generated_at": self.generated_at,
            "target_cutoffs": dict(sorted(self.target_cutoffs.items())),
            "accepted_model_ids": [record.model_id for record in self.models],
            "stale_model_ids": list(self.stale_model_ids),
            "refresh_required": self.refresh_required,
            "research_only": True,
            "trade_ready": False,
        }


def load_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FormalRefreshError(f"invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise FormalRefreshError(f"JSON root must be an object: {path}")
    return payload


def _jsonable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Path):
        return value.as_posix()
    item = getattr(value, "item", None)
    if callable(item):
        return _jsonable(item())
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise FormalRefreshError(f"unsupported JSON value: {type(value)!r}")


def canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            _jsonable(payload),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def write_object(path: Path, payload: Mapping[str, Any]) -> str:
    encoded = canonical_json_bytes(payload)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _date(value: object, *, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise FormalRefreshError(f"invalid {label}: {value!r}") from exc


def accepted_records(root: Path) -> tuple[FormalModelRecord, ...]:
    catalog = load_object(root / "catalog.json")
    if (
        catalog.get("schema_version") != "1.0.0"
        or catalog.get("research_only") is not True
        or catalog.get("trade_ready") is not False
    ):
        raise FormalRefreshError("formal catalog boundary is invalid")
    rows = catalog.get("records")
    if not isinstance(rows, list) or not rows:
        raise FormalRefreshError("formal catalog records are missing")

    records: list[FormalModelRecord] = []
    observed: set[str] = set()
    for index, value in enumerate(rows):
        if not isinstance(value, Mapping):
            raise FormalRefreshError(f"formal catalog record {index} is invalid")
        model_id = str(value.get("model_id") or "")
        if not model_id or model_id in observed:
            raise FormalRefreshError(f"duplicate or empty formal model id: {model_id!r}")
        observed.add(model_id)
        if value.get("publication_status") != "accepted_formal_baseline":
            raise FormalRefreshError(f"non-accepted record in formal catalog: {model_id}")
        relative = str(value.get("path") or "")
        package_path = root / relative
        if not package_path.is_file():
            raise FormalRefreshError(f"formal package is missing: {relative}")
        if sha256(package_path) != value.get("sha256"):
            raise FormalRefreshError(f"formal package digest mismatch: {model_id}")
        package = load_object(package_path)
        if (
            package.get("model_id") != model_id
            or package.get("publication_status") != "accepted_formal_baseline"
            or package.get("research_only") is not True
            or package.get("trade_ready") is not False
        ):
            raise FormalRefreshError(f"formal package boundary mismatch: {model_id}")
        market = str(package.get("market") or "")
        if not market:
            raise FormalRefreshError(f"formal package market is missing: {model_id}")
        cutoff = str(package.get("evidence_cutoff") or "")
        _date(cutoff, label=f"{model_id}.evidence_cutoff")
        display_name = str(value.get("display_name") or package.get("display_name") or model_id)
        records.append(
            FormalModelRecord(
                model_id=model_id,
                display_name=display_name,
                display_order=int(value.get("display_order", index + 1)),
                path=relative,
                market=market,
                current_cutoff=cutoff,
            )
        )
    records.sort(key=lambda record: (record.display_order, record.model_id))
    return tuple(records)


MARKET_CLOCK_SYMBOLS = {"us": "QQQ", "cn": "000300"}


def market_provider_cutoff(manifest: Mapping[str, Any], *, market: str) -> str:
    """Return the governed market-session watermark from its benchmark clock.

    Per-symbol coverage remains quality evidence for the model that consumes the
    symbol. A lagging stock must never rewind the market clock for every active
    strategy in that market.
    """

    if manifest.get("market") != market:
        raise FormalRefreshError(f"provider manifest market mismatch: expected {market}")
    if manifest.get("status") != "selected_pool_price_refresh_ready":
        raise FormalRefreshError(f"{market} provider refresh is not ready")
    if manifest.get("promotion_eligible") is not True:
        raise FormalRefreshError(f"{market} provider refresh is not promotion eligible")
    if manifest.get("research_only") is not True or manifest.get("trade_ready") is not False:
        raise FormalRefreshError(f"{market} provider refresh boundary is invalid")
    rows = manifest.get("records")
    if not isinstance(rows, list) or not rows:
        raise FormalRefreshError(f"{market} provider records are missing")

    clock_symbol = MARKET_CLOCK_SYMBOLS.get(market)
    if clock_symbol is None:
        raise FormalRefreshError(f"unsupported market clock: {market}")
    matches = [
        row
        for row in rows
        if isinstance(row, Mapping)
        and str(row.get("symbol") or "").strip().upper() == clock_symbol
    ]
    if len(matches) != 1:
        raise FormalRefreshError(
            f"{market} provider must contain exactly one market clock {clock_symbol}"
        )
    last_date = matches[0].get("last_date")
    if last_date is None:
        raise FormalRefreshError(f"{market} market clock {clock_symbol} lacks last_date")
    return _date(last_date, label=f"{market} market clock last_date").isoformat()


def build_plan(
    root: Path,
    *,
    target_cutoffs: Mapping[str, str],
    generated_at: str | None = None,
) -> FormalRefreshPlan:
    records = accepted_records(root)
    parsed_targets = {
        str(market): _date(value, label=f"{market} target cutoff").isoformat()
        for market, value in target_cutoffs.items()
    }
    expected_markets = {record.market for record in records}
    if set(parsed_targets) != expected_markets:
        raise FormalRefreshError(
            "target cutoff markets do not match accepted formal packages: "
            f"expected={sorted(expected_markets)}, "
            f"observed={sorted(parsed_targets)}"
        )

    stale: list[str] = []
    for record in records:
        target = _date(
            parsed_targets[record.market],
            label=f"{record.market} target",
        )
        current = _date(
            record.current_cutoff,
            label=f"{record.model_id} current cutoff",
        )
        if target < current:
            raise FormalRefreshError(
                f"target cutoff regresses {record.model_id}: {target} < {current}"
            )
        if target > current:
            stale.append(record.model_id)
    timestamp = generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return FormalRefreshPlan(
        generated_at=timestamp,
        target_cutoffs=parsed_targets,
        models=records,
        stale_model_ids=tuple(stale),
    )


def _stable_prefix(
    old: Sequence[object],
    new: Sequence[object],
    *,
    model_id: str,
    field: str,
) -> None:
    if len(new) < len(old) or list(new[: len(old)]) != list(old):
        raise FormalRefreshError(f"{model_id}: historical {field} is not an immutable prefix")


def verify_append_only_package(
    current: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    target_cutoff: str,
) -> dict[str, Any]:
    model_id = str(current.get("model_id") or "")
    if candidate.get("model_id") != model_id:
        raise FormalRefreshError(f"{model_id}: candidate model identity changed")
    immutable_scalars = (
        "schema_version",
        "record_type",
        "display_name",
        "market",
        "benchmark",
        "publication_status",
        "trace_frequency",
    )
    for key in immutable_scalars:
        if candidate.get(key) != current.get(key):
            raise FormalRefreshError(f"{model_id}: immutable field changed: {key}")
    if candidate.get("portfolio_contract") != current.get("portfolio_contract"):
        raise FormalRefreshError(f"{model_id}: portfolio contract changed")
    if candidate.get("research_only") is not True or candidate.get("trade_ready") is not False:
        raise FormalRefreshError(f"{model_id}: research boundary changed")

    current_cutoff = _date(
        current.get("evidence_cutoff"),
        label=f"{model_id} current cutoff",
    )
    candidate_cutoff = _date(
        candidate.get("evidence_cutoff"),
        label=f"{model_id} candidate cutoff",
    )
    target = _date(target_cutoff, label=f"{model_id} target cutoff")
    if candidate_cutoff != target or candidate_cutoff < current_cutoff:
        raise FormalRefreshError(
            f"{model_id}: candidate cutoff {candidate_cutoff} does not match target {target}"
        )

    for field in ("report", "positions", "trades"):
        old_rows = current.get(field)
        new_rows = candidate.get(field)
        if not isinstance(old_rows, list) or not isinstance(new_rows, list):
            raise FormalRefreshError(f"{model_id}: {field} must be retained as a list")
        _stable_prefix(old_rows, new_rows, model_id=model_id, field=field)

    current_range = current.get("date_range")
    candidate_range = candidate.get("date_range")
    if not isinstance(current_range, Mapping) or not isinstance(candidate_range, Mapping):
        raise FormalRefreshError(f"{model_id}: date_range is invalid")
    if candidate_range.get("start") != current_range.get("start"):
        raise FormalRefreshError(f"{model_id}: historical start changed")
    old_end = _date(current_range.get("end"), label=f"{model_id} old end")
    new_end = _date(candidate_range.get("end"), label=f"{model_id} new end")
    if new_end < old_end or new_end > target:
        raise FormalRefreshError(f"{model_id}: candidate date_range.end is invalid")

    freshness = candidate.get("freshness")
    if not isinstance(freshness, Mapping):
        raise FormalRefreshError(f"{model_id}: freshness receipt is missing")
    if (
        freshness.get("status") != "current"
        or freshness.get("required_cutoff") != target.isoformat()
        or freshness.get("latest_completed_session") != target.isoformat()
        or freshness.get("model_selection_reopened") is not False
    ):
        raise FormalRefreshError(f"{model_id}: freshness receipt is invalid")

    return {
        "model_id": model_id,
        "old_cutoff": current_cutoff.isoformat(),
        "new_cutoff": candidate_cutoff.isoformat(),
        "report_rows_before": len(current["report"]),
        "report_rows_after": len(candidate["report"]),
        "positions_before": len(current["positions"]),
        "positions_after": len(candidate["positions"]),
        "trades_before": len(current["trades"]),
        "trades_after": len(candidate["trades"]),
    }


def next_weekday_refresh_deadline(cutoff: str, *, market: str) -> str:
    """Return the next bounded refresh check after a published market session.

    This is an operational deadline, not a claim that the following weekday is
    necessarily an exchange session. The live refresh resolver remains the
    source of truth and naturally no-ops on holidays.
    """

    day = _date(cutoff, label=f"{market} cutoff") + timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    hour = 8 if market == "cn" else 23
    return datetime(
        day.year,
        day.month,
        day.day,
        hour,
        30,
        tzinfo=timezone.utc,
    ).isoformat()


def finalize_candidate_tree(
    current_root: Path,
    candidate_root: Path,
    *,
    target_cutoffs: Mapping[str, str],
    generated_at: str,
    receipt_path: Path,
) -> dict[str, Any]:
    current_records = accepted_records(current_root)
    current_ids = [record.model_id for record in current_records]
    catalog = load_object(candidate_root / "catalog.json")
    raw_rows = catalog.get("records")
    if not isinstance(raw_rows, list):
        raise FormalRefreshError("candidate catalog records are missing")
    candidate_ids = [str(row.get("model_id")) for row in raw_rows if isinstance(row, dict)]
    if candidate_ids != current_ids:
        raise FormalRefreshError(
            f"candidate catalog changed accepted model membership: {candidate_ids} != {current_ids}"
        )

    rows_by_id = {str(row.get("model_id")): row for row in raw_rows if isinstance(row, dict)}
    verification: list[dict[str, Any]] = []
    for record in current_records:
        current_package = load_object(current_root / record.path)
        candidate_package = load_object(candidate_root / record.path)
        target = str(target_cutoffs[record.market])
        verification.append(
            verify_append_only_package(
                current_package,
                candidate_package,
                target_cutoff=target,
            )
        )
        rows_by_id[record.model_id]["sha256"] = sha256(candidate_root / record.path)
    catalog["records"] = [rows_by_id[record.model_id] for record in current_records]
    catalog["published_at"] = generated_at
    catalog["research_only"] = True
    catalog["trade_ready"] = False
    catalog_sha = write_object(candidate_root / "catalog.json", catalog)

    freshness = load_object(candidate_root / "freshness.json")
    freshness["markets"] = dict(sorted(target_cutoffs.items()))
    freshness["next_session_close_utc"] = {
        market: next_weekday_refresh_deadline(cutoff, market=market)
        for market, cutoff in sorted(target_cutoffs.items())
    }
    freshness["declared_at"] = generated_at
    freshness["required_models"] = current_ids
    freshness["research_only"] = True
    freshness["trade_ready"] = False
    freshness_sha = write_object(candidate_root / "freshness.json", freshness)

    receipt = {
        "schema_version": "formal_refresh_receipt_v1",
        "status": "candidate_ready_for_review",
        "generated_at": generated_at,
        "target_cutoffs": dict(sorted(target_cutoffs.items())),
        "accepted_model_ids": current_ids,
        "model_verification": verification,
        "catalog_sha256": catalog_sha,
        "freshness_sha256": freshness_sha,
        "model_selection_reopened": False,
        "automatic_merge": False,
        "research_only": True,
        "trade_ready": False,
    }
    write_object(receipt_path, receipt)
    return receipt
