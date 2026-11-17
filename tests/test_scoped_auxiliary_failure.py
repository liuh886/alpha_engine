from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml

import scripts.data.refresh_selected_pool_prices as v1
from scripts.data.refresh_selected_pool_prices_v2 import (
    refresh_selected_pool_prices_v2,
)
from src.data.adapters.base import FetchResult
from src.data.router import RouterAttempt, RouterResponse
from src.data.selected_pool_price_publication import (
    PUBLICATION_MANIFEST_NAME,
    load_selected_pool_price_publication_manifest,
)

DATES = ("2021-01-04", "2021-01-05", "2021-01-06")
CUTOFF = DATES[-1]


def _frame(dates: tuple[str, ...] = DATES, level: float = 10.0) -> pd.DataFrame:
    opens = [level + index for index in range(len(dates))]
    return pd.DataFrame(
        {
            "date": list(dates),
            "open": opens,
            "high": [value + 1.0 for value in opens],
            "low": [value - 1.0 for value in opens],
            "close": [value + 0.5 for value in opens],
            "volume": [100.0] * len(dates),
            "amount": [1000.0] * len(dates),
            "factor": [1.0] * len(dates),
        }
    )


class FakeUsRouter:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames

    def providers_for_market(self, market: str) -> list[str]:
        return ["yfinance"]

    def providers_for_request(self, market: str, symbol: str) -> list[str]:
        return ["yfinance"]

    def provider_health_snapshot(self) -> dict[str, object]:
        return {"failure_threshold": None, "source_family_failures": {}, "open_source_families": []}

    def fetch_daily_bars(
        self,
        *,
        symbol: str,
        market: str,
        start: str,
        end: str | None = None,
        validate: bool = False,
        prefer_complete_end: bool = False,
    ) -> RouterResponse:
        assert prefer_complete_end is True
        frame = self.frames.get(symbol)
        if frame is None:
            return RouterResponse(
                result=None,
                attempts=[
                    RouterAttempt(
                        provider="yfinance",
                        ok=False,
                        provider_symbol=symbol,
                        error="provider unavailable fixture",
                    )
                ],
            )
        return RouterResponse(
            result=FetchResult(
                provider="yfinance",
                symbol=symbol,
                market=market,
                start=start,
                end=end,
                df=frame.copy(),
                provider_symbol=symbol,
            ),
            attempts=[
                RouterAttempt(
                    provider="yfinance",
                    ok=True,
                    provider_symbol=symbol,
                    rows=len(frame),
                    first_date=str(frame["date"].iloc[0]),
                    last_date=str(frame["date"].iloc[-1]),
                )
            ],
        )


def _prepare(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pool = tmp_path / "us_pool.yaml"
    pool.write_text(
        yaml.safe_dump(
            {"market": "us", "candidate_count": 1, "symbols": ["AAA"]}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        v1,
        "resolve_selected_pool",
        lambda *args, **kwargs: SimpleNamespace(
            pool_id="us_selected_equities_v2", pool_spec=pool
        ),
    )
    monkeypatch.setattr(
        v1,
        "build_market_provider",
        lambda **kwargs: {"provider_identity_sha256": "c" * 64},
    )
    monkeypatch.setattr(v1, "_terminal_listing_contracts", lambda *args: {})


def _write_seed(source_dir: Path, symbol: str, frame: pd.DataFrame) -> None:
    source_dir.mkdir(parents=True, exist_ok=True)
    target = source_dir / f"{symbol}.csv"
    output = frame.copy()
    output["date"] = pd.to_datetime(output["date"]).dt.strftime("%Y-%m-%d")
    output.to_csv(target, index=False, lineterminator="\n")


def _run_v2(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    frames: dict[str, pd.DataFrame],
    *,
    source_csv_dir: Path | None = None,
    full_refresh: bool = True,
    allow_partial: bool = True,
    auxiliary_symbols: list[str] | None = None,
) -> tuple[dict[str, object], Path]:
    _prepare(tmp_path, monkeypatch)
    source = source_csv_dir or (tmp_path / "seed")
    output = tmp_path / "provider-us"
    result = refresh_selected_pool_prices_v2(
        root=tmp_path,
        market="us",
        source_csv_dir=source,
        output_root=output,
        start="2021-01-01",
        cutoff=CUTOFF,
        max_rounds=1,
        full_refresh=full_refresh,
        auxiliary_symbols=auxiliary_symbols,
        router=FakeUsRouter(frames),  # type: ignore[arg-type]
        allow_partial=allow_partial,
    )
    return result, output


def test_missing_optional_vix_publishes_ready_with_a_scoped_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames = {"AAA": _frame(), "QQQ": _frame(), "QQQI": _frame()}
    result, output = _run_v2(
        tmp_path,
        monkeypatch,
        frames,
        auxiliary_symbols=["QQQI", "VIX"],
    )

    assert result["status"] == "selected_pool_price_refresh_ready"
    assert result["failure_count"] == 0
    assert result["quarantined_symbols"] == []
    assert result["auxiliary_symbols"] == ["QQQI"]
    assert [gap["symbol"] for gap in result["optional_auxiliary_gaps"]] == ["VIX"]
    gap = result["optional_auxiliary_gaps"][0]
    assert gap["role"] == "optional_reference"
    assert gap["market"] == "us"
    assert gap["status"] == "missing"
    assert "provider unavailable fixture" in gap["reason"]
    assert gap["attempted_providers"] == ["yfinance"]

    assert not (output / "data/csv_source/VIX.csv").exists()
    # Required symbols and the benchmark survive untouched.
    assert {record["symbol"] for record in result["records"]} == {"AAA", "QQQ", "QQQI"}

    publication = load_selected_pool_price_publication_manifest(
        output / "artifacts" / PUBLICATION_MANIFEST_NAME
    )
    assert publication["promotion_eligible"] is True
    assert publication["auxiliary_symbols"] == ["QQQI"]
    assert "VIX" not in {record["symbol"] for record in publication["records"]}
    assert publication["optional_auxiliary_gaps"] == [gap]


def test_missing_required_formal_auxiliary_still_blocks_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames = {"AAA": _frame(), "QQQ": _frame(), "VIX": _frame()}
    result, output = _run_v2(
        tmp_path,
        monkeypatch,
        frames,
        auxiliary_symbols=["QQQI", "VIX"],
    )

    assert result["status"] == "selected_pool_price_refresh_partial"
    assert "QQQI" in result["quarantined_symbols"]
    assert "VIX" not in result["quarantined_symbols"]
    assert not (output / "artifacts" / PUBLICATION_MANIFEST_NAME).exists()


def test_missing_benchmark_still_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    frames = {"AAA": _frame(), "QQQI": _frame(), "VIX": _frame()}
    with pytest.raises(RuntimeError, match="selected-pool refresh failed"):
        _run_v2(
            tmp_path,
            monkeypatch,
            frames,
            auxiliary_symbols=["QQQI", "VIX"],
        )
    assert not (
        tmp_path / "provider-us" / "artifacts" / PUBLICATION_MANIFEST_NAME
    ).exists()


def test_stale_optional_reference_becomes_a_scoped_gap_and_is_not_republished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "seed"
    stale_dates = ("2021-01-04", "2021-01-05")
    for symbol in ("AAA", "QQQ", "QQQI", "VIX"):
        _write_seed(source, symbol, _frame(stale_dates))
    frames = {"AAA": _frame(), "QQQ": _frame(), "QQQI": _frame()}
    result, output = _run_v2(
        tmp_path,
        monkeypatch,
        frames,
        source_csv_dir=source,
        full_refresh=False,
        auxiliary_symbols=["QQQI", "VIX"],
    )

    assert result["status"] == "selected_pool_price_refresh_ready"
    assert result["auxiliary_symbols"] == ["QQQI"]
    gap = result["optional_auxiliary_gaps"][0]
    assert gap["symbol"] == "VIX"
    assert gap["reason"] == "stale_before_cutoff"
    assert not (output / "data/csv_source/VIX.csv").exists()
    assert "VIX" not in {record["symbol"] for record in result["records"]}


def test_undeclared_optional_reference_failure_keeps_existing_partial_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prepare(tmp_path, monkeypatch)
    frames = {"AAA": _frame(), "QQQ": _frame(), "QQQI": _frame()}
    payload = v1.refresh_selected_pool_prices(
        root=tmp_path,
        market="us",
        source_csv_dir=tmp_path / "seed",
        output_root=tmp_path / "provider-us",
        start="2021-01-01",
        cutoff=CUTOFF,
        router=FakeUsRouter(frames),  # type: ignore[arg-type]
        max_rounds=1,
        full_refresh=True,
        auxiliary_symbols=["QQQI", "VIX"],
        allow_partial=True,
    )
    # Without the optional declaration, a failed auxiliary remains a partial
    # quarantine and no publication manifest is written.
    assert payload["status"] == "selected_pool_price_refresh_partial"
    assert "VIX" in payload["quarantined_symbols"]


def _vix_provenance() -> dict[str, object]:
    return {
        "provider": "cboe_public",
        "provider_symbol": "VIX",
        "source_url": (
            "https://cdn-api.cboe.com/api/global/us_indices/daily_prices/"
            "VIX_History.csv"
        ),
        "response_sha256": "a" * 64,
        "response_bytes": 1234,
        "fetched_at_utc": "2026-11-17T12:30:00+00:00",
        "source_schema": "cboe_vix_history_csv_v1",
        "source_date_format": "%m/%d/%Y",
        "price_basis": "index_level_unadjusted",
        "volume_basis": "not_applicable_index",
        "amount_basis": "not_applicable_index",
        "requested_start": "2021-01-01",
        "requested_end": CUTOFF,
        "first_date": "2021-01-04",
        "last_date": CUTOFF,
        "rows": 3,
        "terms_caveat": "compiled-for-convenience caveat",
        "research_only": True,
        "trade_ready": False,
    }


class CboeVixFakeRouter(FakeUsRouter):
    def providers_for_request(self, market: str, symbol: str) -> list[str]:
        return ["cboe_public"] if symbol.upper() == "VIX" else ["yfinance"]

    def fetch_daily_bars(self, *, symbol: str, **kwargs):  # type: ignore[override]
        if symbol.upper() != "VIX":
            return super().fetch_daily_bars(symbol=symbol, **kwargs)
        frame = self.frames[symbol]
        return RouterResponse(
            result=FetchResult(
                provider="cboe_public",
                symbol=symbol,
                market=kwargs.get("market", "us"),
                start=kwargs["start"],
                end=kwargs.get("end"),
                df=frame.copy(),
                provider_symbol="VIX",
                provenance=_vix_provenance(),
            ),
            attempts=[
                RouterAttempt(
                    provider="cboe_public",
                    ok=True,
                    provider_symbol="VIX",
                    rows=len(frame),
                    first_date=str(frame["date"].iloc[0]),
                    last_date=str(frame["date"].iloc[-1]),
                    source_provenance=_vix_provenance(),
                )
            ],
        )


def test_materialized_cboe_vix_publishes_provenance_and_provider_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prepare(tmp_path, monkeypatch)
    frames = {"AAA": _frame(), "QQQ": _frame(), "QQQI": _frame(), "VIX": _frame()}
    output = tmp_path / "provider-us"
    result = refresh_selected_pool_prices_v2(
        root=tmp_path,
        market="us",
        source_csv_dir=tmp_path / "seed",
        output_root=output,
        start="2021-01-01",
        cutoff=CUTOFF,
        max_rounds=1,
        full_refresh=True,
        auxiliary_symbols=["QQQI", "VIX"],
        router=CboeVixFakeRouter(frames),  # type: ignore[arg-type]
        allow_partial=True,
    )

    assert result["status"] == "selected_pool_price_refresh_ready"
    assert result["optional_auxiliary_gaps"] == []
    assert result["auxiliary_symbols"] == ["QQQI", "VIX"]

    publication = load_selected_pool_price_publication_manifest(
        output / "artifacts" / PUBLICATION_MANIFEST_NAME
    )
    vix = next(record for record in publication["records"] if record["symbol"] == "VIX")
    assert vix["provider"] == "cboe_public"
    assert vix["source_provenance"] == _vix_provenance()
    contracts = publication["provider_architecture"]["selected_provider_contracts"]
    assert contracts["cboe_public"]["markets"] == ["us"]
    assert contracts["cboe_public"]["volume_unit"] == "not_applicable_index"
