"""Primary CNINFO shareholder and insider holding-change event adapter."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from html import unescape
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from src.data.company_events.ashare_earnings_events import first_session_strictly_after
from src.data.company_events.event_store import (
    CompanyInformationEvent,
    normalize_company_information_event,
)

CST = timezone(timedelta(hours=8))
_SUMMARY_TOKENS = ("摘要", "英文版")


class AshareHoldingChangeError(ValueError):
    """Raised when a holding-change announcement cannot be normalized safely."""


def _first(row: Mapping[str, Any], names: Sequence[str]) -> Any:
    for name in names:
        value = row.get(name)
        if value is not None and not pd.isna(value) and str(value).strip() not in {"", "--"}:
            return value
    return None


def _clean_title(title: str) -> str:
    text = unescape(re.sub(r"<[^>]+>", "", str(title or "")))
    return re.sub(r"\s+", "", text).strip()


def _canonical_title(title: str) -> str:
    text = _clean_title(title)
    for token in _SUMMARY_TOKENS:
        text = text.replace(token, "")
    return re.sub(r"[：:，,。．（）()【】\[\]《》<>·—_-]", "", text)


def classify_holding_change_title(title: str) -> str | None:
    """Classify discretionary increase/decrease plan and execution announcements."""

    text = _clean_title(title)
    direction = "increase" if "增持" in text else "decrease" if "减持" in text else ""
    if not direction:
        return None

    excluded = (
        "回购",
        "限制性股票",
        "股票期权",
        "股权激励",
        "员工持股计划",
        "司法拍卖",
        "司法划转",
        "继承",
        "离婚",
        "财产分割",
        "强制执行",
        "质押",
        "解除质押",
        "转融通",
        "融券",
        "被动稀释",
        "被动减持",
        "持股比例被动",
        "可转债转股",
        "非公开发行",
        "向特定对象发行",
        "法律意见",
        "核查意见",
        "问询函回复",
        "权益变动报告书",
    )
    if any(token in text for token in excluded):
        return None

    execution_tokens = (
        "首次增持",
        "首次减持",
        "进展",
        "累计增持",
        "累计减持",
        "完成",
        "实施完毕",
        "实施结果",
        "计划届满",
        "期限届满",
        "时间过半",
        "数量过半",
        "减持过半",
        "提前终止",
        "终止实施",
        "增持股份达到",
        "减持股份达到",
    )
    if any(token in text for token in execution_tokens):
        return f"{direction}_execution"

    plan_tokens = (
        "增持计划",
        "减持计划",
        "拟增持",
        "拟减持",
        "提议增持",
        "承诺增持",
        "计划增持",
        "计划减持",
        "调整增持计划",
        "调整减持计划",
        "延长增持计划",
        "延长减持计划",
    )
    if any(token in text for token in plan_tokens):
        return f"{direction}_plan"
    return None


def _date_text(row: Mapping[str, Any]) -> str:
    value = _first(row, ("公告时间", "公告日期", "date"))
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


def _document_id(row: Mapping[str, Any]) -> str:
    value = _first(row, ("announcementId", "公告链接", "网址", "link"))
    return str(value or "").strip()


def _source_hash(row: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {str(key): None if pd.isna(value) else str(value) for key, value in row.items()},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def cninfo_holding_change_to_events(
    frames: Sequence[pd.DataFrame],
    *,
    sessions: Sequence[str],
    retrieved_at: str,
    allowed_symbols: Iterable[str] | None = None,
) -> list[CompanyInformationEvent]:
    """Normalize increase/decrease CNINFO query results into one event family."""

    allowed = {str(value).zfill(6) for value in allowed_symbols} if allowed_symbols else None
    candidates: list[dict[str, Any]] = []
    for frame in frames:
        if frame is None or frame.empty:
            continue
        for raw in frame.to_dict(orient="records"):
            symbol = str(_first(raw, ("代码", "股票代码", "symbol")) or "").zfill(6)
            title = _clean_title(_first(raw, ("公告标题", "title")) or "")
            announced_date = _date_text(raw)
            document_id = _document_id(raw)
            stage = classify_holding_change_title(title)
            if (
                len(symbol) != 6
                or not symbol.isdigit()
                or (allowed is not None and symbol not in allowed)
                or not title
                or not announced_date
                or not document_id
                or stage is None
            ):
                continue
            candidates.append(
                {
                    "raw": raw,
                    "symbol": symbol,
                    "title": title,
                    "title_stem": _canonical_title(title),
                    "announced_date": announced_date,
                    "document_id": document_id,
                    "stage": stage,
                    "is_summary": any(token in title for token in _SUMMARY_TOKENS),
                }
            )

    candidates.sort(
        key=lambda row: (
            row["symbol"],
            row["announced_date"],
            row["stage"],
            row["title_stem"],
            row["is_summary"],
            row["document_id"],
        )
    )
    deduplicated: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    seen_documents: set[str] = set()
    for row in candidates:
        if row["document_id"] in seen_documents:
            continue
        seen_documents.add(row["document_id"])
        key = (row["symbol"], row["announced_date"], row["stage"], row["title_stem"])
        deduplicated.setdefault(key, row)

    events: list[CompanyInformationEvent] = []
    for row in deduplicated.values():
        symbol = str(row["symbol"])
        announced_date = str(row["announced_date"])
        exchange = _exchange(symbol)
        payload = {
            "title": row["title"],
            "title_stem": row["title_stem"],
            "announcement_id": str(_first(row["raw"], ("announcementId",)) or ""),
            "org_id": str(_first(row["raw"], ("orgId",)) or ""),
            "primary_link": str(_first(row["raw"], ("公告链接", "网址", "link")) or ""),
        }
        events.append(
            normalize_company_information_event(
                {
                    "market": "cn",
                    "symbol": symbol,
                    "exchange": exchange,
                    "entity_id": f"CN:{exchange}:{symbol}",
                    "event_family": "holding_change",
                    "event_stage": row["stage"],
                    "fiscal_period_end": "",
                    "announced_at": _timestamp(announced_date),
                    "first_eligible_session": first_session_strictly_after(
                        announced_date, sessions
                    ),
                    "effective_date": "",
                    "payload_schema": "cninfo_holding_change_announcement_v1",
                    "payload": payload,
                    "source_provider": "cninfo_via_akshare",
                    "source_document_id": row["document_id"],
                    "source_endpoint": "stock_zh_a_disclosure_report_cninfo",
                    "retrieved_at": retrieved_at,
                    "source_hash": _source_hash(row["raw"]),
                    "revision_sequence": 0,
                    "supersedes_event_id": "",
                    "confidence": 1.0,
                    "reconciliation_status": "reconciled",
                    "availability_status": "usable",
                    "event_id": "",
                }
            )
        )
    return sorted(events, key=lambda event: (event.announced_at, event.symbol, event.event_id))


class AshareHoldingChangeClient:
    """Credential-free CNINFO transport for increase/decrease announcements."""

    def _akshare(self) -> Any:
        try:
            import akshare as ak
        except Exception as exc:
            raise AshareHoldingChangeError(f"akshare import failed: {exc}") from exc
        return ak

    def fetch(
        self,
        *,
        symbol: str,
        keyword: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        try:
            return self._akshare().stock_zh_a_disclosure_report_cninfo(
                symbol=symbol,
                market="沪深京",
                keyword=keyword,
                category="",
                start_date=start_date.replace("-", ""),
                end_date=end_date.replace("-", ""),
            )
        except KeyError as exc:
            message = str(exc)
            expected_columns = ("代码", "简称", "公告标题", "公告时间")
            if "None of [Index" in message and all(
                column in message for column in expected_columns
            ):
                return pd.DataFrame()
            raise
