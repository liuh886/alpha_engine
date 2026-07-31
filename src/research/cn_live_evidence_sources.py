"""BaoStock–Tushare live source layer for the frozen A-share pool.

The module stages source-bound bars, status, limits, calendar and listing data,
then feeds contract-compatible inputs into :mod:`cn_pool_provider`. Missing
credentials, permissions or coverage produce an explicit blocked artifact set.
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

import pandas as pd

from src.research.cn_pool_provider import build_cn_pool_provider, load_cn_provider_contract
from src.research.focus_watchlist_signal import canonical_sha256, sha256_file
from src.research.research_artifacts import write_json

CUTOFF = pd.Timestamp("2026-06-30")
RESERVED_START = pd.Timestamp("2026-07-01")
TUSHARE_URL = "https://api.tushare.pro"


class SourcePermissionError(RuntimeError):
    """A required provider endpoint is unavailable to the configured account."""


class SourceCoverageError(RuntimeError):
    """A required field, identity or date is missing from source output."""


class TushareClientProtocol(Protocol):
    def query(
        self,
        api_name: str,
        *,
        params: Mapping[str, Any],
        fields: list[str],
    ) -> pd.DataFrame: ...


class BaoStockClientProtocol(Protocol):
    def login(self) -> None: ...
    def logout(self) -> None: ...
    def history(
        self,
        code: str,
        *,
        start_date: str,
        end_date: str,
        adjustflag: str,
        fields: list[str],
    ) -> pd.DataFrame: ...
    def trade_dates(self, *, start_date: str, end_date: str) -> pd.DataFrame: ...
    def stock_basic(self, code: str) -> pd.DataFrame: ...


class TushareHttpClient:
    """Minimal HTTP client that never logs or persists the Tushare token."""

    def __init__(self, token: str, *, endpoint: str = TUSHARE_URL, timeout: int = 60) -> None:
        if not token.strip():
            raise ValueError("TUSHARE_TOKEN is empty")
        self._token = token.strip()
        self.endpoint = endpoint
        self.timeout = timeout

    def query(
        self,
        api_name: str,
        *,
        params: Mapping[str, Any],
        fields: list[str],
    ) -> pd.DataFrame:
        payload = json.dumps(
            {
                "api_name": api_name,
                "token": self._token,
                "params": dict(params),
                "fields": ",".join(fields),
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Tushare request failed for endpoint {api_name}") from exc
        code = int(result.get("code", -1))
        if code != 0:
            message = str(result.get("msg", "provider error"))
            if code == 2002 or "权限" in message or "permission" in message.lower():
                raise SourcePermissionError(f"Tushare endpoint unavailable: {api_name}: {message}")
            raise RuntimeError(f"Tushare endpoint failed: {api_name}: {message}")
        data = result.get("data") or {}
        columns = data.get("fields") or []
        items = data.get("items") or []
        return pd.DataFrame(items, columns=columns)


class BaoStockClient:
    """Lazy BaoStock adapter with explicit login state."""

    def __init__(self) -> None:
        self._bs: Any | None = None
        self._logged_in = False

    def login(self) -> None:
        import baostock as bs

        result = bs.login()
        if str(result.error_code) != "0":
            raise RuntimeError(f"BaoStock login failed: {result.error_msg}")
        self._bs = bs
        self._logged_in = True

    def logout(self) -> None:
        if self._logged_in and self._bs is not None:
            self._bs.logout()
        self._logged_in = False

    def _rows(self, result: Any, *, label: str) -> pd.DataFrame:
        if str(result.error_code) != "0":
            raise RuntimeError(f"BaoStock {label} failed: {result.error_msg}")
        rows: list[list[str]] = []
        while result.next():
            rows.append(result.get_row_data())
        return pd.DataFrame(rows, columns=list(result.fields))

    def history(
        self,
        code: str,
        *,
        start_date: str,
        end_date: str,
        adjustflag: str,
        fields: list[str],
    ) -> pd.DataFrame:
        if self._bs is None:
            raise RuntimeError("BaoStock client is not logged in")
        result = self._bs.query_history_k_data_plus(
            code,
            ",".join(fields),
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag=adjustflag,
        )
        return self._rows(result, label=f"history {code}")

    def trade_dates(self, *, start_date: str, end_date: str) -> pd.DataFrame:
        if self._bs is None:
            raise RuntimeError("BaoStock client is not logged in")
        return self._rows(
            self._bs.query_trade_dates(start_date=start_date, end_date=end_date),
            label="trade calendar",
        )

    def stock_basic(self, code: str) -> pd.DataFrame:
        if self._bs is None:
            raise RuntimeError("BaoStock client is not logged in")
        return self._rows(self._bs.query_stock_basic(code=code), label=f"stock basic {code}")


@dataclass(frozen=True)
class SourceRunConfig:
    start_date: str
    end_date: str
    fixture_mode: bool = False

    def validate(self) -> None:
        start = pd.Timestamp(self.start_date)
        end = pd.Timestamp(self.end_date)
        if end > CUTOFF:
            raise ValueError("live source end date cannot exceed 2026-06-30")
        if start > end:
            raise ValueError("source start date must not exceed end date")


def _canonical_to_baostock(symbol: str) -> str:
    code, exchange = symbol.split(".")
    return f"{'sh' if exchange == 'SH' else 'sz'}.{code}"


def _canonical_to_tushare(symbol: str) -> str:
    return symbol


def _normalise_ts_code(frame: pd.DataFrame) -> pd.DataFrame:
    output = frame.copy()
    if "ts_code" in output:
        output["symbol"] = output["ts_code"].astype(str).str.upper()
    return output


def _numeric(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    output = frame.copy()
    for column in columns:
        output[column] = pd.to_numeric(output[column], errors="coerce")
    return output


def _cutoff_anchored_adjusted(raw: pd.DataFrame, qfq: pd.DataFrame) -> pd.DataFrame:
    """Remove any moving qfq scale by anchoring the relative factor at cutoff."""

    keys = ["date", "symbol"]
    merged = raw.merge(
        qfq[keys + ["open", "high", "low", "close"]],
        on=keys,
        suffixes=("_raw", "_qfq"),
        how="inner",
        validate="one_to_one",
    )
    if merged.empty:
        raise SourceCoverageError("raw and qfq series have no overlapping rows")
    merged = merged.sort_values(keys)
    factor = merged["close_qfq"] / merged["close_raw"]
    if factor.isna().any() or (factor <= 0).any():
        raise SourceCoverageError("invalid derived adjustment factor")
    merged["relative_factor"] = factor
    anchor = merged.groupby("symbol")["relative_factor"].transform("last")
    merged["cutoff_factor"] = merged["relative_factor"] / anchor
    output = merged[keys].copy()
    for field in ("open", "high", "low", "close"):
        output[field] = merged[f"{field}_raw"] * merged["cutoff_factor"]
    for field in ("volume", "amount", "tradestatus", "isst"):
        output[field] = merged[field] if field in merged else pd.NA
    return output


def _query_baostock_symbol(
    client: BaoStockClientProtocol,
    symbol: str,
    config: SourceRunConfig,
    *,
    index: bool,
) -> tuple[pd.DataFrame, pd.DataFrame | None]:
    fields = ["date", "code", "open", "high", "low", "close", "volume", "amount"]
    if not index:
        fields += ["tradestatus", "isST"]
    code = _canonical_to_baostock(symbol)
    raw = client.history(
        code,
        start_date=config.start_date,
        end_date=config.end_date,
        adjustflag="3",
        fields=fields,
    )
    raw.columns = [str(column).lower() for column in raw.columns]
    raw["symbol"] = symbol
    raw = _numeric(raw, ["open", "high", "low", "close", "volume", "amount"])
    raw["date"] = pd.to_datetime(raw["date"], errors="coerce")
    raw = raw[raw["date"] < RESERVED_START].copy()
    if raw.empty:
        raise SourceCoverageError(f"BaoStock raw history is empty: {symbol}")
    if index:
        return raw, None
    qfq = client.history(
        code,
        start_date=config.start_date,
        end_date=config.end_date,
        adjustflag="2",
        fields=fields,
    )
    qfq.columns = [str(column).lower() for column in qfq.columns]
    qfq["symbol"] = symbol
    qfq = _numeric(qfq, ["open", "high", "low", "close", "volume", "amount"])
    qfq["date"] = pd.to_datetime(qfq["date"], errors="coerce")
    qfq = qfq[qfq["date"] < RESERVED_START].copy()
    return raw, qfq


def _calendar(
    bao: BaoStockClientProtocol,
    tushare: TushareClientProtocol,
    config: SourceRunConfig,
) -> pd.DataFrame:
    bao_frame = bao.trade_dates(start_date=config.start_date, end_date=config.end_date)
    bao_frame.columns = [str(column).lower() for column in bao_frame.columns]
    date_column = "calendar_date" if "calendar_date" in bao_frame else "date"
    status_column = "is_trading_day" if "is_trading_day" in bao_frame else "is_open"
    bao_frame["date"] = pd.to_datetime(bao_frame[date_column], errors="coerce")
    bao_frame["bao_open"] = bao_frame[status_column].astype(str).isin({"1", "true", "True"})

    ts_frame = tushare.query(
        "trade_cal",
        params={
            "exchange": "SSE",
            "start_date": config.start_date.replace("-", ""),
            "end_date": config.end_date.replace("-", ""),
        },
        fields=["exchange", "cal_date", "is_open", "pretrade_date"],
    )
    if ts_frame.empty:
        raise SourceCoverageError("Tushare trade_cal returned no rows")
    ts_frame["date"] = pd.to_datetime(ts_frame["cal_date"], errors="coerce")
    ts_frame["ts_open"] = pd.to_numeric(ts_frame["is_open"], errors="coerce").eq(1)
    merged = bao_frame[["date", "bao_open"]].merge(
        ts_frame[["date", "ts_open"]], on="date", how="outer", validate="one_to_one"
    )
    merged = merged[merged["date"] < RESERVED_START].sort_values("date")
    conflicts = merged[
        merged["bao_open"].isna()
        | merged["ts_open"].isna()
        | merged["bao_open"].ne(merged["ts_open"])
    ]
    if not conflicts.empty:
        sample = [value.date().isoformat() for value in conflicts["date"].head(5)]
        raise SourceCoverageError(f"BaoStock/Tushare calendar conflict: {sample}")
    return pd.DataFrame(
        {
            "date": merged["date"],
            "is_open": merged["bao_open"],
            "source_calendar_provider": "baostock+tushare_trade_cal_reconciled",
        }
    )


def _listing_metadata(
    bao: BaoStockClientProtocol,
    tushare: TushareClientProtocol,
    symbols: list[str],
) -> pd.DataFrame:
    ts_parts = []
    for status in ("L", "D", "P"):
        part = tushare.query(
            "stock_basic",
            params={"exchange": "", "list_status": status},
            fields=["ts_code", "symbol", "name", "exchange", "list_status", "list_date", "delist_date"],
        )
        if not part.empty:
            ts_parts.append(part)
    if not ts_parts:
        raise SourceCoverageError("Tushare stock_basic returned no rows")
    ts_frame = _normalise_ts_code(pd.concat(ts_parts, ignore_index=True))
    ts_frame = ts_frame[ts_frame["symbol"].isin(symbols)].copy()
    if set(ts_frame["symbol"]) != set(symbols):
        raise SourceCoverageError("Tushare stock_basic is missing frozen candidates")

    rows: list[dict[str, Any]] = []
    for symbol in symbols:
        bao_frame = bao.stock_basic(_canonical_to_baostock(symbol))
        if bao_frame.empty:
            raise SourceCoverageError(f"BaoStock stock_basic is empty: {symbol}")
        bao_frame.columns = [str(column).lower() for column in bao_frame.columns]
        ts_row = ts_frame[ts_frame["symbol"] == symbol].iloc[-1]
        bao_row = bao_frame.iloc[-1]
        bao_list = pd.to_datetime(
            bao_row.get("ipoDate", bao_row.get("ipodate")), errors="coerce"
        )
        ts_list = pd.to_datetime(ts_row.get("list_date"), errors="coerce")
        if pd.isna(bao_list) or pd.isna(ts_list) or bao_list.normalize() != ts_list.normalize():
            raise SourceCoverageError(f"listing-date conflict: {symbol}")
        ts_delist = pd.to_datetime(ts_row.get("delist_date"), errors="coerce")
        rows.append(
            {
                "symbol": symbol,
                "list_date": ts_list.date().isoformat(),
                "delist_date": None if pd.isna(ts_delist) else ts_delist.date().isoformat(),
                "list_status": str(ts_row.get("list_status", "")),
                "source_listing_provider": "baostock+tushare_stock_basic_reconciled",
            }
        )
    return pd.DataFrame(rows)


def _limits(
    tushare: TushareClientProtocol,
    symbols: list[str],
    config: SourceRunConfig,
) -> pd.DataFrame:
    rows = []
    for symbol in symbols:
        frame = tushare.query(
            "stk_limit",
            params={
                "ts_code": _canonical_to_tushare(symbol),
                "start_date": config.start_date.replace("-", ""),
                "end_date": config.end_date.replace("-", ""),
            },
            fields=["trade_date", "ts_code", "pre_close", "up_limit", "down_limit"],
        )
        if frame.empty:
            raise SourceCoverageError(f"Tushare stk_limit returned no rows: {symbol}")
        frame = _normalise_ts_code(frame)
        frame["date"] = pd.to_datetime(frame["trade_date"], errors="coerce")
        frame = _numeric(frame, ["pre_close", "up_limit", "down_limit"])
        rows.append(frame[["date", "symbol", "pre_close", "up_limit", "down_limit"]])
    output = pd.concat(rows, ignore_index=True)
    output = output[output["date"] < RESERVED_START].copy()
    if output.duplicated(["date", "symbol"]).any():
        raise SourceCoverageError("Tushare stk_limit contains duplicate identities")
    output["source_limit_provider"] = "tushare_stk_limit"
    return output.sort_values(["symbol", "date"]).reset_index(drop=True)


def _build_status(
    raw_by_symbol: Mapping[str, pd.DataFrame],
    reference_by_symbol: Mapping[str, pd.DataFrame],
    calendar: pd.DataFrame,
    listing: pd.DataFrame,
    limits: pd.DataFrame,
) -> pd.DataFrame:
    open_dates = calendar.loc[calendar["is_open"], ["date"]].copy()
    rows = []
    listing_by_symbol = listing.set_index("symbol")
    limit_index = limits.set_index(["date", "symbol"])
    for symbol, raw in raw_by_symbol.items():
        base = open_dates.copy()
        base["symbol"] = symbol
        raw_status = raw[["date", "symbol", "open", "tradestatus", "isst"]].copy()
        raw_status["tradestatus"] = pd.to_numeric(raw_status["tradestatus"], errors="coerce")
        raw_status["isst"] = pd.to_numeric(raw_status["isst"], errors="coerce")
        base = base.merge(raw_status, on=["date", "symbol"], how="left", validate="one_to_one")
        meta = listing_by_symbol.loc[symbol]
        list_date = pd.Timestamp(meta["list_date"])
        delist_date = pd.NaT if pd.isna(meta["delist_date"]) else pd.Timestamp(meta["delist_date"])
        base["listed"] = base["date"] >= list_date
        base["delisted"] = False if pd.isna(delist_date) else base["date"] > delist_date
        base["suspended"] = base["listed"] & ~base["delisted"] & base["tradestatus"].ne(1)
        base["st"] = base["isst"].ffill().fillna(0).eq(1)
        up_flags = []
        down_flags = []
        missing_limits = []
        for row in base.itertuples(index=False):
            key = (row.date, symbol)
            tradable_session = bool(row.listed and not row.delisted and not row.suspended)
            if key not in limit_index.index:
                up_flags.append(False)
                down_flags.append(False)
                if tradable_session:
                    missing_limits.append(row.date.date().isoformat())
                continue
            limit_row = limit_index.loc[key]
            opening = float(row.open)
            tolerance = max(1e-6, abs(opening) * 1e-6)
            up_flags.append(opening >= float(limit_row["up_limit"]) - tolerance)
            down_flags.append(opening <= float(limit_row["down_limit"]) + tolerance)
        if missing_limits:
            raise SourceCoverageError(
                f"missing stk_limit for tradable sessions {symbol}: {missing_limits[:5]}"
            )
        base["limit_up_at_open"] = up_flags
        base["limit_down_at_open"] = down_flags
        base["tradable_at_open"] = (
            base["listed"]
            & ~base["delisted"]
            & ~base["suspended"]
            & ~base["limit_up_at_open"]
            & ~base["limit_down_at_open"]
        )
        base["source_status_provider"] = "baostock_status+tushare_stk_limit"
        rows.append(base)

    for symbol, raw in reference_by_symbol.items():
        base = open_dates.copy()
        base["symbol"] = symbol
        observed = raw[["date"]].drop_duplicates()
        base = base.merge(observed.assign(observed=True), on="date", how="left")
        base["listed"] = True
        base["suspended"] = ~base["observed"].fillna(False)
        base["st"] = False
        base["delisted"] = False
        base["limit_up_at_open"] = False
        base["limit_down_at_open"] = False
        base["tradable_at_open"] = ~base["suspended"]
        base["source_status_provider"] = "baostock_index_presence"
        rows.append(base)

    columns = [
        "date",
        "symbol",
        "listed",
        "suspended",
        "st",
        "delisted",
        "limit_up_at_open",
        "limit_down_at_open",
        "tradable_at_open",
        "source_status_provider",
    ]
    return pd.concat(rows, ignore_index=True)[columns].sort_values(["symbol", "date"])


def _bars(
    raw_by_symbol: Mapping[str, pd.DataFrame],
    qfq_by_symbol: Mapping[str, pd.DataFrame],
    references: Mapping[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    adjusted_parts = []
    raw_parts = []
    for symbol, raw in raw_by_symbol.items():
        qfq = qfq_by_symbol[symbol]
        adjusted = _cutoff_anchored_adjusted(raw, qfq)
        adjusted = adjusted[pd.to_numeric(adjusted["tradestatus"], errors="coerce").eq(1)]
        adjusted["adjustment_convention"] = "qfq"
        adjusted["source_bar_provider"] = "baostock_raw+qfq_cutoff_anchor"
        adjusted_parts.append(adjusted)
        execution = raw[pd.to_numeric(raw["tradestatus"], errors="coerce").eq(1)].copy()
        execution["adjustment_convention"] = "unadjusted_execution"
        execution["source_bar_provider"] = "baostock_raw"
        raw_parts.append(execution)
    for symbol, frame in references.items():
        reference = frame.copy()
        reference["adjustment_convention"] = "unadjusted_index"
        reference["source_bar_provider"] = "baostock_index_raw"
        adjusted_parts.append(reference)
    columns = [
        "date",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "adjustment_convention",
        "source_bar_provider",
    ]
    adjusted_output = pd.concat(adjusted_parts, ignore_index=True)[columns]
    raw_output = pd.concat(raw_parts, ignore_index=True)[columns]
    return (
        adjusted_output.sort_values(["symbol", "date"]),
        raw_output.sort_values(["symbol", "date"]),
    )


def _blocked(
    output: Path,
    *,
    reason: str,
    config: SourceRunConfig,
    capabilities: Mapping[str, Any],
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    report = {
        "schema_version": "1.0",
        "decision": "cn_provider_contract_blocked",
        "reason": reason,
        "requested_range": {"start": config.start_date, "end": config.end_date},
        "live_provider_run_completed": False,
        "source_attestation_verified": False,
        "authoritative_provider_artifact": False,
        "research_only": True,
        "trade_ready": False,
        "capabilities": dict(capabilities),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json(output / "source_capability_report.json", report)
    write_json(output / "decision.json", report)
    return report


def _promote_live_contract(output: Path, source_manifest: Mapping[str, Any]) -> dict[str, Any]:
    decision_path = output / "decision.json"
    quality_path = output / "data_quality_report.json"
    manifest_path = output / "provider_manifest.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    quality = json.loads(quality_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for payload in (decision, quality, manifest):
        payload["live_provider_run_completed"] = True
        payload["source_attestation_verified"] = True
        payload["authoritative_provider_artifact"] = True
    decision["decision"] = "cn_provider_contract_ready"
    quality["decision"] = "live_source_contract_pass"
    manifest["source_manifest_identity_sha256"] = source_manifest[
        "source_manifest_identity_sha256"
    ]
    write_json(decision_path, decision)
    write_json(quality_path, quality)
    output_names = [
        "cn_pool_bars.csv",
        "cn_pool_status.csv",
        "cn_trading_calendar.csv",
        "data_quality_report.json",
        "decision.json",
    ]
    manifest["outputs"] = {
        name: sha256_file(output / name) for name in output_names
    }
    manifest["manifest_identity_sha256"] = canonical_sha256(
        {
            "inputs": manifest["inputs"],
            "contracts": manifest["contracts"],
            "outputs": manifest["outputs"],
            "source_manifest": manifest["source_manifest_identity_sha256"],
        }
    )
    write_json(manifest_path, manifest)
    return decision


def build_cn_live_evidence_sources(
    *,
    contract_path: str | Path,
    output_dir: str | Path,
    start_date: str,
    end_date: str = "2026-06-30",
    tushare_client: TushareClientProtocol | None = None,
    baostock_client: BaoStockClientProtocol | None = None,
    fixture_mode: bool = False,
) -> dict[str, Any]:
    """Build source-bound staging inputs and the final provider contract artifact."""

    config = SourceRunConfig(start_date, end_date, fixture_mode)
    config.validate()
    output = Path(output_dir).resolve()
    staging = output / "staging"
    capabilities: dict[str, Any] = {
        "baostock": "not_attempted",
        "tushare_trade_cal": "not_attempted",
        "tushare_stock_basic": "not_attempted",
        "tushare_stk_limit": "not_attempted",
        "tushare_token_present": False,
        "fixture_mode": fixture_mode,
    }
    token = os.environ.get("TUSHARE_TOKEN", "")
    if tushare_client is None:
        capabilities["tushare_token_present"] = bool(token.strip())
        if not token.strip():
            return _blocked(
                output,
                reason="TUSHARE_TOKEN is missing",
                config=config,
                capabilities=capabilities,
            )
        tushare_client = TushareHttpClient(token)
    else:
        capabilities["tushare_token_present"] = False
    bao = baostock_client or BaoStockClient()

    try:
        contract, pool, _, _, _, _ = load_cn_provider_contract(contract_path)
        candidates = [
            str(symbol)
            for basket in pool["baskets"].values()
            for symbol in basket["symbols"]
        ]
        references = [str(symbol) for symbol in pool["references"]]
        bao.login()
        capabilities["baostock"] = "available"
        calendar = _calendar(bao, tushare_client, config)
        capabilities["tushare_trade_cal"] = "available"
        listing = _listing_metadata(bao, tushare_client, candidates)
        capabilities["tushare_stock_basic"] = "available"
        limits = _limits(tushare_client, candidates, config)
        capabilities["tushare_stk_limit"] = "available"

        raw_by_symbol: dict[str, pd.DataFrame] = {}
        qfq_by_symbol: dict[str, pd.DataFrame] = {}
        reference_by_symbol: dict[str, pd.DataFrame] = {}
        for symbol in candidates:
            raw, qfq = _query_baostock_symbol(
                bao, symbol, config, index=False
            )
            assert qfq is not None
            raw_by_symbol[symbol] = raw
            qfq_by_symbol[symbol] = qfq
        for symbol in references:
            raw, _ = _query_baostock_symbol(bao, symbol, config, index=True)
            reference_by_symbol[symbol] = raw

        bars, raw_execution = _bars(raw_by_symbol, qfq_by_symbol, reference_by_symbol)
        status = _build_status(
            raw_by_symbol, reference_by_symbol, calendar, listing, limits
        )
        staging.mkdir(parents=True, exist_ok=True)
        paths = {
            "contract_bars": staging / "contract_bars.csv",
            "execution_bars_raw": staging / "execution_bars_raw.csv",
            "status": staging / "contract_status.csv",
            "calendar": staging / "contract_calendar.csv",
            "limits": staging / "daily_price_limits.csv",
            "listing": staging / "listing_metadata.csv",
        }
        bars.to_csv(paths["contract_bars"], index=False)
        raw_execution.to_csv(paths["execution_bars_raw"], index=False)
        status.to_csv(paths["status"], index=False)
        calendar.to_csv(paths["calendar"], index=False)
        limits.to_csv(paths["limits"], index=False)
        listing.to_csv(paths["listing"], index=False)
        source_manifest: dict[str, Any] = {
            "schema_version": "1.0",
            "market": "cn",
            "source_roles": {
                "bars": "BaoStock raw and qfq; relative factor anchored to 2026-06-30",
                "status": "BaoStock tradestatus/isST plus Tushare stk_limit",
                "calendar": "BaoStock and Tushare trade_cal reconciled",
                "listing": "BaoStock and Tushare stock_basic reconciled",
            },
            "request_range": {"start": start_date, "end": end_date},
            "cutoff": CUTOFF.date().isoformat(),
            "row_counts": {
                "bars": len(bars),
                "raw_execution_bars": len(raw_execution),
                "status": len(status),
                "calendar": len(calendar),
                "limits": len(limits),
                "listing": len(listing),
            },
            "files": {
                name: {"path": str(path), "sha256": sha256_file(path)}
                for name, path in paths.items()
            },
            "fixture_mode": fixture_mode,
            "token_persisted": False,
        }
        source_manifest["source_manifest_identity_sha256"] = canonical_sha256(
            source_manifest
        )
        write_json(staging / "source_manifest.json", source_manifest)
        write_json(
            staging / "source_capability_report.json",
            {
                "schema_version": "1.0",
                "decision": (
                    "fixture_sources_complete_not_authoritative"
                    if fixture_mode
                    else "live_sources_complete"
                ),
                "capabilities": capabilities,
                "live_provider_run_completed": not fixture_mode,
                "source_attestation_verified": not fixture_mode,
                "authoritative_provider_artifact": False,
                "token_persisted": False,
            },
        )
        build_cn_pool_provider(
            contract_path=contract_path,
            bars_csv=paths["contract_bars"],
            status_csv=paths["status"],
            calendar_csv=paths["calendar"],
            output_dir=output,
        )
        if fixture_mode:
            return json.loads((output / "decision.json").read_text(encoding="utf-8"))
        return _promote_live_contract(output, source_manifest)
    except Exception as exc:
        capabilities["failure_type"] = type(exc).__name__
        return _blocked(
            output,
            reason=str(exc),
            config=config,
            capabilities=capabilities,
        )
    finally:
        try:
            bao.logout()
        except Exception:
            pass
