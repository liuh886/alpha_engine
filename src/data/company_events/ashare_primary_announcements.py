"""Primary CNINFO announcement adapters for buyback and restricted-unlock events."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd

from src.data.company_events.ashare_earnings_events import first_session_strictly_after
from src.data.company_events.event_store import (
    CompanyInformationEvent,
    normalize_company_information_event,
)

CST = timezone(timedelta(hours=8))
_SUMMARY_TOKENS = ("摘要", "英文版")
_EXPECTED_EMPTY_CNINFO_COLUMNS = ("代码", "简称", "公告标题", "公告时间")


class AsharePrimaryAnnouncementError(ValueError):
    """Raised when a primary announcement cannot be normalized safely."""


def _first(row: Mapping[str, Any], names: Sequence[str]) -> Any:
    for name in names:
        value = row.get(name)
        if value is not None and not pd.isna(value) and str(value).strip() not in {"", "--"}:
            return value
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


def _canonical_title(title: str) -> str:
    text = re.sub(r"\s+", "", str(title or ""))
    for token in _SUMMARY_TOKENS:
        text = text.replace(token, "")
    return re.sub(r"[：:，,。．（）()【】\[\]《》<>·—_-]", "", text)


def classify_buyback_title(title: str) -> str | None:
    """Classify a primary buyback announcement without using current-state snapshots."""

    text = str(title or "")
    if "回购" not in text:
        return None
    unrelated = (
        "限制性股票",
        "股票期权",
        "业绩补偿",
        "承诺回购",
        "质押式回购",
        "逆回购",
        "债券回购",
        "回购交易",
        "回购注销",
    )
    if any(token in text for token in unrelated):
        return None
    if any(token in text for token in ("回购完成", "实施完成", "实施完毕", "完成回购")):
        return "completion"
    if "首次回购" in text or "首次实施回购" in text:
        return "first_execution"
    if any(
        token in text
        for token in (
            "回购进展",
            "累计回购",
            "回购股份比例达到",
            "回购公司股份的进展",
            "回购公司股份进展",
            "回购股份进展",
        )
    ):
        return "progress"
    if "股东大会" in text and any(token in text for token in ("通过", "决议", "审议")):
        return "approval"
    if any(
        token in text
        for token in (
            "回购方案",
            "回购报告书",
            "回购股份预案",
            "董事会提议回购",
            "提议回购",
            "调整回购",
            "变更回购",
        )
    ):
        return "plan"
    return None


def classify_restricted_unlock_title(title: str) -> str | None:
    """Retain only announcements explicitly opening restricted shares for trading."""

    text = str(title or "")
    excluded = (
        "授予",
        "激励计划",
        "回购注销",
        "解除限售条件成就",
        "限售期",
        "锁定期",
        "非公开发行",
        "向特定对象发行",
    )
    if any(token in text for token in excluded):
        return None
    included = (
        "限售股份上市流通",
        "限售股上市流通",
        "解除限售股份上市流通",
        "解除限售股票上市流通",
        "限售股份解除限售",
    )
    return "scheduled" if any(token in text for token in included) else None


def _source_hash(row: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {str(key): None if pd.isna(value) else str(value) for key, value in row.items()},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _document_id(row: Mapping[str, Any]) -> str:
    value = _first(row, ("announcementId", "公告链接", "网址", "link"))
    return str(value or "").strip()


def cninfo_primary_announcements_to_events(
    frame: pd.DataFrame,
    *,
    family: str,
    sessions: Sequence[str],
    retrieved_at: str,
    allowed_symbols: Iterable[str] | None = None,
) -> list[CompanyInformationEvent]:
    """Normalize title-classified CNINFO documents into canonical PIT events."""

    if family not in {"buyback", "restricted_unlock"}:
        raise AsharePrimaryAnnouncementError(f"unsupported primary family: {family}")
    if frame is None or frame.empty:
        return []
    allowed = {str(value).zfill(6) for value in allowed_symbols} if allowed_symbols else None
    classifier = classify_buyback_title if family == "buyback" else classify_restricted_unlock_title
    candidates: list[dict[str, Any]] = []
    for raw in frame.to_dict(orient="records"):
        symbol = str(_first(raw, ("代码", "股票代码", "symbol")) or "").zfill(6)
        title = str(_first(raw, ("公告标题", "title")) or "").strip()
        announced_date = _date_text(raw)
        document_id = _document_id(raw)
        stage = classifier(title)
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
                    "event_family": family,
                    "event_stage": row["stage"],
                    "fiscal_period_end": "",
                    "announced_at": _timestamp(announced_date),
                    "first_eligible_session": first_session_strictly_after(
                        announced_date, sessions
                    ),
                    "effective_date": "",
                    "payload_schema": f"cninfo_{family}_announcement_v1",
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


def is_expected_empty_cninfo_error(exc: KeyError) -> bool:
    """Identify AKShare's known no-result column-selection KeyError narrowly."""

    message = str(exc)
    return "None of [Index" in message and all(
        column in message for column in _EXPECTED_EMPTY_CNINFO_COLUMNS
    )


class AsharePrimaryAnnouncementClient:
    """Credential-free CNINFO transport with narrow no-result handling."""

    def _akshare(self) -> Any:
        try:
            import akshare as ak
        except Exception as exc:
            raise AsharePrimaryAnnouncementError(f"akshare import failed: {exc}") from exc
        return ak

    def _fetch(
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
            if is_expected_empty_cninfo_error(exc):
                return pd.DataFrame()
            raise

    def fetch_buyback(self, *, symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
        return self._fetch(
            symbol=symbol,
            keyword="回购",
            start_date=start_date,
            end_date=end_date,
        )

    def fetch_restricted_unlock(
        self, *, symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        return self._fetch(
            symbol=symbol,
            keyword="限售",
            start_date=start_date,
            end_date=end_date,
        )
