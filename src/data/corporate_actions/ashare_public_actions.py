from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import pandas as pd

from src.data.corporate_actions.event_store import (
    CorporateActionEvent,
    normalize_corporate_action,
)

CST = timezone(timedelta(hours=8))


class AsharePublicActionError(ValueError):
    pass


def _hash(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(dict(payload), sort_keys=True, default=str, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _first(row: Mapping[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = row.get(name)
        if value is not None and not pd.isna(value) and str(value).strip() not in {"", "--"}:
            return value
    return None


def _date(row: Mapping[str, Any], names: tuple[str, ...]) -> str:
    value = _first(row, names)
    if value is None:
        return ""
    parsed = pd.to_datetime(value, errors="coerce")
    return "" if pd.isna(parsed) else parsed.date().isoformat()


def _timestamp(date_text: str) -> str:
    if not date_text:
        return ""
    return datetime.strptime(date_text, "%Y-%m-%d").replace(tzinfo=CST).isoformat()


def _float(row: Mapping[str, Any], names: tuple[str, ...]) -> float | None:
    value = _first(row, names)
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if pd.notna(parsed) else None


def eastmoney_dividend_to_events(
    frame: pd.DataFrame,
    *,
    symbol: str,
    exchange: str,
    retrieved_at: str,
) -> list[CorporateActionEvent]:
    """Normalize explicit Eastmoney dividend fields; never infer from prices."""

    if frame is None or frame.empty:
        return []
    events: list[CorporateActionEvent] = []
    for raw in frame.to_dict(orient="records"):
        ex_date = _date(raw, ("除权除息日", "除权日", "A股除权除息日"))
        announced = _date(raw, ("最新公告日期", "实施公告日", "业绩披露日期"))
        report_period = str(_first(raw, ("报告期", "报告时间")) or "")
        if not ex_date:
            continue
        document_id = f"eastmoney:{symbol}:{report_period}:{announced}:{ex_date}"
        cash_per_10 = _float(
            raw,
            (
                "现金分红-现金分红比例",
                "每10股派息(元)",
                "派息比例",
                "税前每10股派息",
            ),
        )
        stock_per_10 = _float(
            raw,
            (
                "送转股份-送转总比例",
                "每10股送转股",
                "送股比例",
                "转增比例",
            ),
        )
        common = {
            "market": "cn",
            "symbol": symbol,
            "exchange": exchange,
            "entity_id": f"CN:{exchange}:{symbol}",
            "announced_at": _timestamp(announced),
            "ex_date": ex_date,
            "record_date": _date(raw, ("股权登记日", "A股股权登记日")),
            "pay_date": _date(raw, ("现金红利发放日", "派息日")),
            "effective_date": ex_date,
            "currency": "CNY",
            "old_symbol": "",
            "new_symbol": "",
            "source_provider": "akshare_eastmoney_dividend",
            "source_document_id": document_id,
            "source_endpoint": "stock_fhps_detail_em",
            "retrieved_at": retrieved_at,
            "revision_sequence": 0,
            "supersedes_event_id": "",
            "confidence": 0.85,
            "reconciliation_status": "source_only",
        }
        if cash_per_10 is not None and cash_per_10 >= 0:
            payload = {
                **common,
                "event_type": "cash_dividend",
                "cash_amount": cash_per_10 / 10.0,
                "split_ratio": None,
                "stock_dividend_ratio": None,
                "rights_ratio": None,
                "rights_price": None,
                "shares_before": None,
                "shares_after": None,
            }
            payload["source_hash"] = _hash({"row": raw, "kind": "cash_dividend"})
            events.append(normalize_corporate_action(payload))
        if stock_per_10 is not None and stock_per_10 > 0:
            payload = {
                **common,
                "event_type": "stock_dividend",
                "cash_amount": None,
                "split_ratio": None,
                "stock_dividend_ratio": stock_per_10 / 10.0,
                "rights_ratio": None,
                "rights_price": None,
                "shares_before": None,
                "shares_after": None,
            }
            payload["source_hash"] = _hash({"row": raw, "kind": "stock_dividend"})
            events.append(normalize_corporate_action(payload))
    unique = {event.event_id: event for event in events}
    return sorted(unique.values(), key=lambda event: (event.effective_date, event.event_type))


@dataclass
class AsharePublicActionClient:
    """Credential-free AKShare transport for Eastmoney and CNINFO actions."""

    def _akshare(self) -> Any:
        try:
            import akshare as ak
        except Exception as exc:
            raise AsharePublicActionError(f"akshare import failed: {exc}") from exc
        return ak

    def fetch_dividends(self, *, symbol: str) -> pd.DataFrame:
        return self._akshare().stock_fhps_detail_em(symbol=symbol)

    def fetch_share_changes(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        return self._akshare().stock_share_change_cninfo(
            symbol=symbol, start_date=start_date, end_date=end_date
        )

    def fetch_allotments(
        self,
        *,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        return self._akshare().stock_allotment_cninfo(
            symbol=symbol, start_date=start_date, end_date=end_date
        )
