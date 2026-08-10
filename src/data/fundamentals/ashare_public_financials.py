from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import pandas as pd

from src.data.fundamentals.event_store import FundamentalEvent, normalize_event_record

CST = timezone(timedelta(hours=8))
_YEAR = re.compile(r"(20\d{2})")


class AsharePublicFinancialError(ValueError):
    pass


def _hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(payload), sort_keys=True, default=str, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _period_from_title(title: str) -> str | None:
    text = str(title or "").strip()
    year_match = _YEAR.search(text)
    if year_match is None:
        return None
    year = int(year_match.group(1))
    if any(token in text for token in ("第一季度", "一季度", "一季报")):
        return f"{year:04d}-03-31"
    if any(token in text for token in ("半年度", "半年度报告", "中期报告", "中报")):
        return f"{year:04d}-06-30"
    if any(token in text for token in ("第三季度", "三季度", "三季报")):
        return f"{year:04d}-09-30"
    if any(token in text for token in ("年度报告", "年报")):
        return f"{year:04d}-12-31"
    return None


def cninfo_period_disclosures(frame: pd.DataFrame) -> dict[str, dict[str, str]]:
    """Index CNINFO periodic-report announcements by fiscal period.

    Only report announcements with an identifiable period and announcement date
    are retained. The earliest non-summary announcement is preferred for the
    initial PIT availability boundary; later corrections remain separate source
    documents for a future revision pass.
    """

    if frame is None or frame.empty:
        return {}
    aliases = {
        "title": ("公告标题", "title"),
        "date": ("公告时间", "公告日期", "date"),
        "link": ("公告链接", "网址", "link"),
    }

    def value(row: Mapping[str, Any], key: str) -> str:
        for column in aliases[key]:
            raw = row.get(column)
            if raw is not None and str(raw).strip():
                return str(raw).strip()
        return ""

    candidates: list[dict[str, str]] = []
    for raw in frame.to_dict(orient="records"):
        title = value(raw, "title")
        period = _period_from_title(title)
        date_text = value(raw, "date")
        if period is None or not date_text:
            continue
        parsed = pd.to_datetime(date_text, errors="coerce")
        if pd.isna(parsed):
            continue
        candidates.append(
            {
                "period_end": period,
                "announced_date": parsed.date().isoformat(),
                "title": title,
                "link": value(raw, "link"),
                "is_summary": str("摘要" in title).lower(),
            }
        )
    candidates.sort(
        key=lambda row: (
            row["period_end"],
            row["is_summary"] == "true",
            row["announced_date"],
            row["title"],
        )
    )
    indexed: dict[str, dict[str, str]] = {}
    for row in candidates:
        indexed.setdefault(row["period_end"], row)
    return indexed


def _period_meta(period_end: str) -> tuple[int, str, bool]:
    value = datetime.strptime(period_end, "%Y-%m-%d").date()
    fiscal_period = {3: "Q1", 6: "Q2", 9: "Q3", 12: "FY"}.get(value.month)
    if fiscal_period is None:
        raise AsharePublicFinancialError(f"unsupported fiscal period: {period_end}")
    return value.year, fiscal_period, fiscal_period != "FY"


def _announced_times(date_text: str) -> tuple[str, str]:
    announced = datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=CST)
    return announced.isoformat(), (announced + timedelta(days=1)).isoformat()


def sina_statement_to_events(
    frame: pd.DataFrame,
    *,
    disclosures: Mapping[str, Mapping[str, str]],
    symbol: str,
    exchange: str,
    statement: str,
    field_map: Mapping[str, Mapping[str, str]],
    retrieved_at: str,
) -> list[FundamentalEvent]:
    """Convert Sina statements only when a CNINFO PIT timestamp is available."""

    if frame is None or frame.empty:
        return []
    events: list[FundamentalEvent] = []
    for raw in frame.to_dict(orient="records"):
        report_value = raw.get("报告日", raw.get("报告日期", raw.get("date")))
        parsed = pd.to_datetime(report_value, errors="coerce")
        if pd.isna(parsed):
            continue
        period_end = parsed.date().isoformat()
        disclosure = disclosures.get(period_end)
        if not disclosure:
            continue
        announced_date = str(disclosure.get("announced_date", ""))
        if not announced_date:
            continue
        try:
            reported_at, available_at = _announced_times(announced_date)
            fiscal_year, fiscal_period, quarterly = _period_meta(period_end)
        except (ValueError, AsharePublicFinancialError):
            continue
        row_type = str(raw.get("类型", "")).strip()
        if row_type and "合并" not in row_type:
            continue
        for source_field, definition in field_map.items():
            value = raw.get(source_field)
            if value is None or pd.isna(value):
                continue
            source_document = str(disclosure.get("link") or disclosure.get("title") or "")
            if not source_document:
                continue
            source_payload = {
                "statement": statement,
                "row": raw,
                "disclosure": dict(disclosure),
                "field": source_field,
            }
            try:
                event = normalize_event_record(
                    {
                        "market": "cn",
                        "symbol": symbol,
                        "exchange": exchange,
                        "entity_id": f"CN:{exchange}:{symbol}",
                        "fiscal_period_end": period_end,
                        "fiscal_year": fiscal_year,
                        "fiscal_period": fiscal_period,
                        "reported_at": reported_at,
                        "available_at": available_at,
                        "filing_type": "PERIODIC_REPORT",
                        "source_provider": "akshare_sina_financial_report_cninfo_time",
                        "source_document_id": source_document,
                        "source_endpoint": (
                            "stock_financial_report_sina+stock_zh_a_disclosure_report_cninfo"
                        ),
                        "field": str(definition["field"]),
                        "value": float(value),
                        "unit": str(definition["unit"]),
                        "currency": str(definition.get("currency", "CNY")),
                        "is_quarterly": quarterly,
                        "is_derived": False,
                        "derivation_rule": "",
                        "revision_sequence": 0,
                        "supersedes_event_id": "",
                        "retrieved_at": retrieved_at,
                        "source_hash": _hash(source_payload),
                    }
                )
            except (TypeError, ValueError):
                continue
            events.append(event)
    unique = {event.event_id: event for event in events}
    return sorted(
        unique.values(),
        key=lambda event: (
            event.available_at,
            event.symbol,
            event.field,
            event.fiscal_period_end,
        ),
    )


@dataclass
class AsharePublicFinancialClient:
    """Credential-free AKShare transport over distinct Sina and CNINFO sources."""

    def _akshare(self) -> Any:
        try:
            import akshare as ak
        except Exception as exc:
            raise AsharePublicFinancialError(f"akshare import failed: {exc}") from exc
        return ak

    def fetch_statement(self, *, symbol: str, exchange: str, statement: str) -> pd.DataFrame:
        prefix = "sh" if exchange.upper() in {"SSE", "SHSE"} else "sz"
        return self._akshare().stock_financial_report_sina(
            stock=f"{prefix}{symbol}", symbol=statement
        )

    def fetch_disclosures(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        frames: list[pd.DataFrame] = []
        ak = self._akshare()
        for category in ("年报", "半年报", "一季报", "三季报"):
            frame = ak.stock_zh_a_disclosure_report_cninfo(
                symbol=symbol,
                market="沪深京",
                category=category,
                start_date=start_date,
                end_date=end_date,
            )
            if frame is not None and not frame.empty:
                frames.append(frame)
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
