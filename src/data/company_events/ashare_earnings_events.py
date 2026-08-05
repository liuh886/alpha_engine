"""A-share earnings forecast and preliminary earnings PIT event adapters."""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from src.data.company_events.event_store import (
    CompanyInformationEvent,
    normalize_company_information_event,
)

CST = timezone(timedelta(hours=8))


class AshareEarningsEventError(ValueError):
    """Raised when a structured earnings event cannot be normalized."""


def _json_value(value: Any) -> Any:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (TypeError, ValueError):
            pass
    if isinstance(value, float) and not pd.notna(value):
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload), ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _first(row: Mapping[str, Any], names: Sequence[str]) -> Any:
    for name in names:
        value = row.get(name)
        if value is not None and not pd.isna(value) and str(value).strip() not in {"", "--"}:
            return value
    return None


def _date_text(row: Mapping[str, Any], names: Sequence[str]) -> str:
    value = _first(row, names)
    if value is None:
        return ""
    parsed = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(parsed) else parsed.date().isoformat()


def _exchange(symbol: str) -> str:
    if symbol.startswith(("4", "8", "9")):
        return "BSE"
    return "SSE" if symbol.startswith(("5", "6")) else "SZSE"


def _timestamp(date_text: str) -> str:
    return datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=CST).isoformat()


def first_session_strictly_after(announced_date: str, sessions: Sequence[str]) -> str:
    """Map a date-only announcement to the first strictly later trading session."""

    normalized = sorted({str(value)[:10] for value in sessions if str(value).strip()})
    position = bisect_right(normalized, announced_date)
    return normalized[position] if position < len(normalized) else ""


def _title_stage(title: str, family: str, revision_sequence: int = 0) -> str:
    text = str(title or "")
    revised = revision_sequence > 0 or any(token in text for token in ("修正", "更正", "补充"))
    if family == "earnings_forecast":
        return "forecast_revision" if revised else "forecast_initial"
    return "flash_revision" if revised else "flash_initial"


def cninfo_disclosure_index(
    frame: pd.DataFrame,
    *,
    family: str,
) -> dict[tuple[str, str], dict[str, str]]:
    """Index primary CNINFO documents by symbol and announcement date."""

    if frame is None or frame.empty:
        return {}
    expected = "业绩预告" if family == "earnings_forecast" else "业绩快报"
    candidates: list[dict[str, str]] = []
    for raw in frame.to_dict(orient="records"):
        symbol = str(_first(raw, ("代码", "股票代码", "symbol")) or "").zfill(6)
        title = str(_first(raw, ("公告标题", "title")) or "").strip()
        announced = _date_text(raw, ("公告时间", "公告日期", "date"))
        link = str(_first(raw, ("公告链接", "网址", "link")) or "").strip()
        if len(symbol) != 6 or expected not in title or not announced or not link:
            continue
        candidates.append(
            {
                "symbol": symbol,
                "announced_date": announced,
                "title": title,
                "link": link,
                "is_summary": str("摘要" in title).lower(),
            }
        )
    candidates.sort(
        key=lambda row: (
            row["symbol"],
            row["announced_date"],
            row["is_summary"] == "true",
            row["title"],
            row["link"],
        )
    )
    indexed: dict[tuple[str, str], dict[str, str]] = {}
    for row in candidates:
        indexed.setdefault((row["symbol"], row["announced_date"]), row)
    return indexed


def _structured_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    columns = [str(value) for value in frame.columns]
    rows: list[dict[str, Any]] = []
    for raw in frame.to_dict(orient="records"):
        rows.append({column: _json_value(raw.get(column)) for column in columns})
    return rows


def _base_records(
    frame: pd.DataFrame,
    *,
    family: str,
    fiscal_period_end: str,
    disclosures: Mapping[tuple[str, str], Mapping[str, str]],
    sessions: Sequence[str],
    retrieved_at: str,
    allowed_symbols: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    allowed = {str(value).zfill(6) for value in allowed_symbols} if allowed_symbols else None
    symbol_column = "股票代码" if "股票代码" in frame.columns else "代码"
    date_column = "公告日期" if "公告日期" in frame.columns else "最新公告日期"
    if symbol_column not in frame.columns or date_column not in frame.columns:
        raise AshareEarningsEventError(
            f"{family} frame missing symbol/date columns: {list(frame.columns)}"
        )
    working = frame.copy()
    working[symbol_column] = working[symbol_column].astype(str).str.zfill(6)
    working[date_column] = pd.to_datetime(working[date_column], errors="coerce")
    working = working.dropna(subset=[date_column])
    if allowed is not None:
        working = working.loc[working[symbol_column].isin(allowed)]

    records: list[dict[str, Any]] = []
    for (symbol, announced_ts), group in working.groupby(
        [symbol_column, date_column], sort=True, dropna=False
    ):
        announced_date = pd.Timestamp(announced_ts).date().isoformat()
        primary = disclosures.get((str(symbol), announced_date))
        reconciled = primary is not None
        document_id = (
            str(primary["link"])
            if primary is not None
            else f"eastmoney:{family}:{symbol}:{fiscal_period_end}:{announced_date}"
        )
        payload = {
            "family": family,
            "fiscal_period_end": fiscal_period_end,
            "structured_rows": _structured_rows(group),
            "primary_title": str(primary.get("title", "")) if primary else "",
            "primary_link": str(primary.get("link", "")) if primary else "",
        }
        records.append(
            {
                "market": "cn",
                "symbol": str(symbol),
                "exchange": _exchange(str(symbol)),
                "entity_id": f"CN:{_exchange(str(symbol))}:{str(symbol)}",
                "event_family": family,
                "event_stage": _title_stage(
                    str(primary.get("title", "")) if primary else "",
                    family,
                ),
                "fiscal_period_end": fiscal_period_end,
                "announced_at": _timestamp(announced_date),
                "first_eligible_session": first_session_strictly_after(
                    announced_date, sessions
                ),
                "effective_date": "",
                "payload_schema": f"cn_{family}_eastmoney_cninfo_v1",
                "payload": payload,
                "source_provider": (
                    f"akshare_eastmoney_{family}+cninfo"
                    if reconciled
                    else f"akshare_eastmoney_{family}"
                ),
                "source_document_id": document_id,
                "source_endpoint": (
                    ("stock_yjyg_em" if family == "earnings_forecast" else "stock_yjkb_em")
                    + ("+stock_zh_a_disclosure_report_cninfo" if reconciled else "")
                ),
                "retrieved_at": retrieved_at,
                "source_hash": _hash(
                    {
                        "family": family,
                        "period": fiscal_period_end,
                        "rows": payload["structured_rows"],
                        "primary": dict(primary) if primary else None,
                    }
                ),
                "revision_sequence": 0,
                "supersedes_event_id": "",
                "confidence": 0.90 if reconciled else 0.60,
                "reconciliation_status": "reconciled" if reconciled else "missing_primary",
                "availability_status": "usable" if reconciled else "partial",
                "event_id": "",
            }
        )
    return records


def _chain_revisions(records: Sequence[Mapping[str, Any]]) -> list[CompanyInformationEvent]:
    ordered_records = sorted(
        (dict(record) for record in records),
        key=lambda row: (
            str(row["symbol"]),
            str(row["event_family"]),
            str(row.get("fiscal_period_end", "")),
            str(row["announced_at"]),
            str(row["source_document_id"]),
        ),
    )
    output: list[CompanyInformationEvent] = []
    previous: dict[tuple[str, str, str], CompanyInformationEvent] = {}
    for record in ordered_records:
        key = (
            str(record["symbol"]),
            str(record["event_family"]),
            str(record.get("fiscal_period_end", "")),
        )
        prior = previous.get(key)
        sequence = 0 if prior is None else prior.revision_sequence + 1
        record["revision_sequence"] = sequence
        record["supersedes_event_id"] = "" if prior is None else prior.event_id
        record["event_stage"] = _title_stage(
            str(record.get("payload", {}).get("primary_title", "")),
            str(record["event_family"]),
            revision_sequence=sequence,
        )
        event = normalize_company_information_event(record)
        output.append(event)
        previous[key] = event
    return sorted(output, key=lambda event: (event.announced_at, event.symbol, event.event_id))


def eastmoney_earnings_forecast_to_events(
    frame: pd.DataFrame,
    *,
    fiscal_period_end: str,
    disclosures: Mapping[tuple[str, str], Mapping[str, str]],
    sessions: Sequence[str],
    retrieved_at: str,
    allowed_symbols: Iterable[str] | None = None,
) -> list[CompanyInformationEvent]:
    return _chain_revisions(
        _base_records(
            frame,
            family="earnings_forecast",
            fiscal_period_end=fiscal_period_end,
            disclosures=disclosures,
            sessions=sessions,
            retrieved_at=retrieved_at,
            allowed_symbols=allowed_symbols,
        )
    )


def eastmoney_preliminary_earnings_to_events(
    frame: pd.DataFrame,
    *,
    fiscal_period_end: str,
    disclosures: Mapping[tuple[str, str], Mapping[str, str]],
    sessions: Sequence[str],
    retrieved_at: str,
    allowed_symbols: Iterable[str] | None = None,
) -> list[CompanyInformationEvent]:
    return _chain_revisions(
        _base_records(
            frame,
            family="preliminary_earnings",
            fiscal_period_end=fiscal_period_end,
            disclosures=disclosures,
            sessions=sessions,
            retrieved_at=retrieved_at,
            allowed_symbols=allowed_symbols,
        )
    )


class AshareEarningsEventClient:
    """Credential-free AKShare transport for structured and primary disclosures."""

    def _akshare(self) -> Any:
        try:
            import akshare as ak
        except Exception as exc:
            raise AshareEarningsEventError(f"akshare import failed: {exc}") from exc
        return ak

    def fetch_forecast(self, *, period: str) -> pd.DataFrame:
        return self._akshare().stock_yjyg_em(date=period.replace("-", ""))

    def fetch_preliminary(self, *, period: str) -> pd.DataFrame:
        return self._akshare().stock_yjkb_em(date=period.replace("-", ""))

    def fetch_cninfo_forecasts(
        self, *, symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        return self._akshare().stock_zh_a_disclosure_report_cninfo(
            symbol=symbol,
            market="沪深京",
            keyword="",
            category="业绩预告",
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
        )

    def fetch_cninfo_preliminary(
        self, *, symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        return self._akshare().stock_zh_a_disclosure_report_cninfo(
            symbol=symbol,
            market="沪深京",
            keyword="业绩快报",
            category="",
            start_date=start_date.replace("-", ""),
            end_date=end_date.replace("-", ""),
        )
