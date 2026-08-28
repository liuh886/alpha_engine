import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml

import scripts.data.refresh_selected_pool_prices as module
from src.data.adapters.base import FetchResult
from src.data.router import RouterAttempt, RouterResponse


def _frame(
    multiplier: float = 1.0,
    dates: tuple[str, ...] = ("2021-01-04", "2021-01-05"),
) -> pd.DataFrame:
    size = len(dates)
    opens = [10.0 + index for index in range(size)]
    return pd.DataFrame(
        {
            "date": list(dates),
            "open": opens,
            "high": [value + 1.0 for value in opens],
            "low": [value - 1.0 for value in opens],
            "close": [value + 0.5 for value in opens],
            "volume": [100.0 + 20.0 * index for index in range(size)],
            "amount": [1000.0 + 320.0 * index for index in range(size)],
            "factor": [multiplier] * size,
        }
    )


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, lineterminator="\n")


class FakeRouter:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames
        self.calls: list[tuple[str, str, str | None]] = []

    def fetch_daily_bars(
        self,
        *,
        symbol: str,
        market: str,
        start: str,
        end: str | None = None,
        validate: bool = False,
    ) -> RouterResponse:
        del validate
        self.calls.append((symbol, start, end))
        frame = self.frames.get(symbol)
        if frame is None:
            return RouterResponse(
                result=None,
                attempts=[
                    RouterAttempt(
                        provider="fake",
                        ok=False,
                        provider_symbol=symbol,
                        error="missing fixture",
                    )
                ],
            )
        return RouterResponse(
            result=FetchResult(
                provider="fake",
                symbol=symbol,
                market=market,
                start=start,
                end=end,
                df=frame.copy(),
                provider_symbol=symbol,
            ),
            attempts=[
                RouterAttempt(
                    provider="fake",
                    ok=True,
                    provider_symbol=symbol,
                    rows=len(frame),
                    first_date=str(frame["date"].iloc[0]),
                    last_date=str(frame["date"].iloc[-1]),
                )
            ],
        )


class SequenceRouter:
    def __init__(self, frames: list[pd.DataFrame]) -> None:
        self.frames = list(frames)
        self.calls = 0

    def fetch_daily_bars(
        self,
        *,
        symbol: str,
        market: str,
        start: str,
        end: str | None = None,
        validate: bool = False,
    ) -> RouterResponse:
        del validate
        frame = self.frames[min(self.calls, len(self.frames) - 1)].copy()
        self.calls += 1
        return RouterResponse(
            result=FetchResult(
                provider="fake",
                symbol=symbol,
                market=market,
                start=start,
                end=end,
                df=frame,
                provider_symbol=symbol,
            ),
            attempts=[
                RouterAttempt(
                    provider="fake",
                    ok=True,
                    provider_symbol=symbol,
                    rows=len(frame),
                    first_date=str(frame["date"].iloc[0]),
                    last_date=str(frame["date"].iloc[-1]),
                )
            ],
        )


def _prepare_contract(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    pool = tmp_path / "pool.yaml"
    pool.write_text(
        yaml.safe_dump(
            {
                "market": "cn",
                "candidate_count": 2,
                "symbols": ["000001", "000002"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module,
        "resolve_selected_pool",
        lambda *args, **kwargs: SimpleNamespace(
            pool_id="test_cn_pool",
            pool_spec=pool,
        ),
    )
    monkeypatch.setattr(
        module,
        "build_market_provider",
        lambda **kwargs: {"provider_identity_sha256": "c" * 64},
    )
    monkeypatch.setattr(module, "_terminal_listing_contracts", lambda *args: {})
    return pool


def test_normalize_frame_converts_intraday_timestamps_to_session_dates() -> None:
    frame = _frame(
        dates=("2021-01-04 09:30:00+08:00", "2021-01-05 15:00:00+08:00")
    )

    normalized = module._normalize_frame(frame, symbol="000300")

    assert normalized["date"].tolist() == [
        pd.Timestamp("2021-01-04"),
        pd.Timestamp("2021-01-05"),
    ]


def test_copy_requested_window_fails_closed_when_window_is_empty(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.csv"
    output = tmp_path / "output.csv"
    _write_csv(source, _frame(dates=("2020-12-30", "2020-12-31")))

    with pytest.raises(ValueError, match="has no governed history"):
        module._copy_requested_window(
            source_path=source,
            output_path=output,
            symbol="000300",
            start="2021-01-01",
            cutoff="2021-01-05",
        )

    assert not output.exists()


def test_refresh_rejects_inverted_window_before_loading_contract(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="requested date window is invalid"):
        module.refresh_selected_pool_prices(
            root=tmp_path,
            market="cn",
            source_csv_dir=tmp_path / "source",
            output_root=tmp_path / "output",
            start="2021-01-06",
            cutoff="2021-01-05",
            router=FakeRouter({}),  # type: ignore[arg-type]
            max_rounds=1,
        )


def test_successful_but_incomplete_response_retries_until_cutoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = SequenceRouter(
        [
            _frame(dates=("2026-08-20",)),
            _frame(dates=("2026-08-20", "2026-08-21")),
        ]
    )
    delays: list[float] = []
    monkeypatch.setattr(module.time, "sleep", delays.append)

    response, attempts = module._fetch_with_retries(
        router,  # type: ignore[arg-type]
        symbol="FN",
        market="us",
        start="2026-08-20",
        cutoff="2026-08-21",
        max_rounds=3,
    )

    assert response.ok is True
    assert router.calls == 2
    assert delays == [module.INCOMPLETE_CUTOFF_RETRY_SECONDS]
    assert attempts[0]["ok"] is False
    assert attempts[0]["cutoff_complete"] is False
    assert attempts[0]["observed_last_date"] == "2026-08-20"
    assert attempts[0]["error"] == (
        "provider response ended before requested cutoff"
    )
    assert attempts[1]["ok"] is True
    assert attempts[1]["cutoff_complete"] is True
    assert attempts[1]["observed_last_date"] == "2026-08-21"


def test_incomplete_response_remains_fail_closed_after_bounded_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    router = SequenceRouter([_frame(dates=("2026-08-20",))])
    delays: list[float] = []
    monkeypatch.setattr(module.time, "sleep", delays.append)

    response, attempts = module._fetch_with_retries(
        router,  # type: ignore[arg-type]
        symbol="FN",
        market="us",
        start="2026-08-20",
        cutoff="2026-08-21",
        max_rounds=3,
    )

    assert response.ok is True
    assert router.calls == 3
    assert delays == [
        module.INCOMPLETE_CUTOFF_RETRY_SECONDS,
        module.INCOMPLETE_CUTOFF_RETRY_SECONDS * 2,
    ]
    assert [attempt["ok"] for attempt in attempts] == [False, False, False]
    assert {attempt["observed_last_date"] for attempt in attempts} == {
        "2026-08-20"
    }


def test_timezone_aware_response_is_normalized_before_cutoff_comparison() -> None:
    router = FakeRouter(
        {
            "000300": _frame(
                dates=(
                    "2021-01-04 09:30:00+08:00",
                    "2021-01-05 15:00:00+08:00",
                )
            )
        }
    )

    response, attempts = module._fetch_with_retries(
        router,  # type: ignore[arg-type]
        symbol="000300",
        market="cn",
        start="2021-01-01",
        cutoff="2021-01-05",
        max_rounds=1,
    )

    assert response.ok is True
    assert attempts[0]["ok"] is True
    assert attempts[0]["observed_last_date"] == "2021-01-05"
    assert attempts[0]["cutoff_complete"] is True


def test_terminal_history_is_retained_without_refetching(tmp_path: Path) -> None:
    source = tmp_path / "EA.csv"
    frame = _frame(
        dates=("2002-01-04", "2021-01-04", "2026-08-04", "2026-08-10")
    )
    _write_csv(source, frame)

    retained = module._retained_terminal_history(
        source,
        symbol="EA",
        start="2021-01-01",
        contract={"terminal_date": "2026-08-04"},
    )

    assert retained["date"].min() == pd.Timestamp("2021-01-04")
    assert retained["date"].max() == pd.Timestamp("2026-08-04")
    assert "2026-08-10" not in retained["date"].dt.strftime("%Y-%m-%d").tolist()


def test_full_refresh_routes_around_governed_terminal_listing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool = tmp_path / "pool.yaml"
    pool.write_text(
        yaml.safe_dump({"market": "us", "candidate_count": 1, "symbols": ["EA"]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        module,
        "resolve_selected_pool",
        lambda *args, **kwargs: SimpleNamespace(pool_id="test_us_pool", pool_spec=pool),
    )
    monkeypatch.setattr(
        module,
        "_terminal_listing_contracts",
        lambda *args: {
            "EA": {
                "market": "us",
                "terminal_date": "2026-08-04",
                "active_universe_after_terminal_date_allowed": False,
                "historical_rows_retained": True,
            }
        },
    )
    monkeypatch.setattr(
        module,
        "build_market_provider",
        lambda **kwargs: {"provider_identity_sha256": "c" * 64},
    )
    source = tmp_path / "source"
    _write_csv(
        source / "EA.csv",
        _frame(dates=("2021-01-04", "2026-08-04", "2026-08-10")),
    )
    _write_csv(source / "QQQ.csv", _frame(dates=("2021-01-04", "2026-08-14")))
    router = FakeRouter({"QQQ": _frame(2.0, dates=("2026-08-14",))})

    payload = module.refresh_selected_pool_prices(
        root=tmp_path,
        market="us",
        source_csv_dir=source,
        output_root=tmp_path / "output",
        start="2021-01-01",
        cutoff="2026-08-14",
        router=router,  # type: ignore[arg-type]
        max_rounds=1,
        full_refresh=True,
    )

    assert [call[0] for call in router.calls] == ["QQQ"]
    ea_record = next(row for row in payload["records"] if row["symbol"] == "EA")
    assert ea_record["action"] == "retained_governed_terminal_history"
    assert ea_record["last_date"] == "2026-08-04"


def test_incremental_refresh_fetches_only_invalid_or_outdated_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_contract(tmp_path, monkeypatch)
    source = tmp_path / "source"
    current = _frame(
        dates=("2002-01-04", "2021-01-04", "2021-01-05", "2021-01-06")
    )
    _write_csv(source / "000001.csv", current)
    _write_csv(source / "000002.csv", _frame().assign(high=[1.0, 1.0]))
    _write_csv(source / "000300.csv", current)
    replacement = _frame(2.0, dates=("2021-01-04", "2021-01-05", "2021-01-06"))
    router = FakeRouter({"000002": replacement})
    output = tmp_path / "output"

    payload = module.refresh_selected_pool_prices(
        root=tmp_path,
        market="cn",
        source_csv_dir=source,
        output_root=output,
        start="2021-01-01",
        cutoff="2021-01-06",
        router=router,  # type: ignore[arg-type]
        max_rounds=1,
    )

    assert payload["refresh_mode"] == "repair_only"
    assert payload["targets"] == ["000002"]
    assert [call[0] for call in router.calls] == ["000002"]
    assert payload["status"] == "selected_pool_price_refresh_ready"
    assert payload["stale_symbols"] == []
    assert payload["all_sources_current"] is True
    assert {row["first_date"] for row in payload["records"]} == {"2021-01-04"}


def test_incremental_refresh_extends_governed_history_to_cutoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_contract(tmp_path, monkeypatch)
    source = tmp_path / "source"
    governed = _frame()
    for symbol in ("000001", "000002", "000300"):
        _write_csv(source / f"{symbol}.csv", governed)
    update = _frame(
        2.0,
        dates=("2021-01-05", "2021-01-06"),
    )
    router = FakeRouter({symbol: update for symbol in ("000001", "000002", "000300")})
    output = tmp_path / "output"

    payload = module.refresh_selected_pool_prices(
        root=tmp_path,
        market="cn",
        source_csv_dir=source,
        output_root=output,
        start="2021-01-01",
        cutoff="2021-01-06",
        router=router,  # type: ignore[arg-type]
        max_rounds=1,
    )

    assert payload["targets"] == ["000001", "000002", "000300"]
    assert all(call[1] == "2021-01-05" for call in router.calls)
    assert {row["action"] for row in payload["records"]} == {
        "fetched_incremental_update"
    }
    merged = pd.read_csv(output / "data" / "csv_source" / "000001.csv")
    assert merged["date"].tolist() == ["2021-01-04", "2021-01-05", "2021-01-06"]
    assert float(merged.loc[merged["date"] == "2021-01-05", "factor"].iloc[0]) == 2.0
    assert payload["stale_symbols"] == []
    assert payload["all_sources_current"] is True


def test_incremental_refresh_clips_repository_bootstrap_to_declared_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_contract(tmp_path, monkeypatch)
    source = tmp_path / "source"
    governed = _frame(dates=("2002-01-04", "2021-01-04", "2021-01-05"))
    for symbol in ("000001", "000002", "000300"):
        _write_csv(source / f"{symbol}.csv", governed)
    update = _frame(2.0, dates=("2021-01-05", "2021-01-06"))
    router = FakeRouter({symbol: update for symbol in ("000001", "000002", "000300")})
    output = tmp_path / "output"

    payload = module.refresh_selected_pool_prices(
        root=tmp_path,
        market="cn",
        source_csv_dir=source,
        output_root=output,
        start="2021-01-01",
        cutoff="2021-01-06",
        router=router,  # type: ignore[arg-type]
        max_rounds=1,
    )

    assert {record["first_date"] for record in payload["records"]} == {
        "2021-01-04"
    }
    for symbol in ("000001", "000002", "000300"):
        frame = pd.read_csv(output / "data" / "csv_source" / f"{symbol}.csv")
        assert frame["date"].tolist() == [
            "2021-01-04",
            "2021-01-05",
            "2021-01-06",
        ]


def test_full_refresh_fetches_every_candidate_and_benchmark(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_contract(tmp_path, monkeypatch)
    source = tmp_path / "source"
    for symbol in ("000001", "000002", "000300"):
        _write_csv(source / f"{symbol}.csv", _frame())
    refreshed = _frame(2.0, dates=("2002-01-04", "2021-01-04", "2021-01-05"))
    router = FakeRouter(
        {symbol: refreshed for symbol in ("000001", "000002", "000300")}
    )
    output = tmp_path / "output"

    payload = module.refresh_selected_pool_prices(
        root=tmp_path,
        market="cn",
        source_csv_dir=source,
        output_root=output,
        start="2021-01-01",
        cutoff="2021-01-05",
        router=router,  # type: ignore[arg-type]
        max_rounds=1,
        full_refresh=True,
    )

    assert payload["refresh_mode"] == "full"
    assert payload["targets"] == ["000001", "000002", "000300"]
    assert {row["action"] for row in payload["records"]} == {
        "fetched_full_refresh"
    }
    assert payload["stale_symbols"] == []
    assert payload["all_sources_current"] is True
    assert {row["first_date"] for row in payload["records"]} == {"2021-01-04"}


def test_full_refresh_retains_validated_source_when_fetch_is_transiently_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_contract(tmp_path, monkeypatch)
    source = tmp_path / "source"
    governed = _frame(dates=("2002-01-04", "2021-01-04", "2021-01-05"))
    for symbol in ("000001", "000002", "000300"):
        _write_csv(source / f"{symbol}.csv", governed)
    router = FakeRouter({"000001": _frame(2.0), "000300": _frame(2.0)})
    output = tmp_path / "output"

    payload = module.refresh_selected_pool_prices(
        root=tmp_path,
        market="cn",
        source_csv_dir=source,
        output_root=output,
        start="2021-01-01",
        cutoff="2021-01-05",
        router=router,  # type: ignore[arg-type]
        max_rounds=1,
        full_refresh=True,
    )

    assert payload["status"] == "selected_pool_price_refresh_ready"
    assert payload["failed_symbols"] == []
    assert payload["stale_symbols"] == []
    assert payload["all_sources_ready"] is True
    assert payload["all_sources_current"] is True
    retained = next(row for row in payload["records"] if row["symbol"] == "000002")
    assert retained["action"] == "retained_stale_source"
    retained_frame = pd.read_csv(output / "data" / "csv_source" / "000002.csv")
    assert retained_frame["date"].tolist() == ["2021-01-04", "2021-01-05"]


def test_incremental_refresh_marks_retained_old_source_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_contract(tmp_path, monkeypatch)
    source = tmp_path / "source"
    for symbol in ("000001", "000002", "000300"):
        _write_csv(source / f"{symbol}.csv", _frame())
    update = _frame(dates=("2021-01-05", "2021-01-06"))
    router = FakeRouter({"000001": update, "000300": update})
    output = tmp_path / "output"

    payload = module.refresh_selected_pool_prices(
        root=tmp_path,
        market="cn",
        source_csv_dir=source,
        output_root=output,
        start="2021-01-01",
        cutoff="2021-01-06",
        router=router,  # type: ignore[arg-type]
        max_rounds=1,
    )

    assert payload["status"] == "selected_pool_price_refresh_ready"
    assert payload["stale_symbols"] == ["000002"]
    assert payload["all_sources_current"] is False
    retained = pd.read_csv(output / "data" / "csv_source" / "000002.csv")
    assert retained["date"].max() == "2021-01-05"
    assert payload["before"]["000002"]["last_date"] == "2021-01-05"
    assert payload["after"]["000002"]["last_date"] == "2021-01-05"


def test_auxiliary_symbols_share_provider_without_entering_candidate_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_contract(tmp_path, monkeypatch)
    source = tmp_path / "source"
    for symbol in ("000001", "000002", "000300"):
        _write_csv(source / f"{symbol}.csv", _frame())
    router = FakeRouter({"515180": _frame(3.0)})
    output = tmp_path / "output"

    payload = module.refresh_selected_pool_prices(
        root=tmp_path,
        market="cn",
        source_csv_dir=source,
        output_root=output,
        start="2021-01-01",
        cutoff="2021-01-05",
        router=router,  # type: ignore[arg-type]
        max_rounds=1,
        auxiliary_symbols=["515180"],
    )

    assert payload["candidate_count"] == 2
    assert payload["candidate_symbols"] == ["000001", "000002"]
    assert payload["benchmark"] == "000300"
    assert payload["auxiliary_symbols"] == ["515180"]
    assert payload["targets"] == ["515180"]
    assert [call[0] for call in router.calls] == ["515180"]
    assert (output / "data" / "csv_source" / "515180.csv").is_file()


def test_refresh_publishes_diagnostics_without_partial_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_contract(tmp_path, monkeypatch)
    source = tmp_path / "source"
    _write_csv(source / "000001.csv", _frame())
    _write_csv(source / "000300.csv", _frame())
    output = tmp_path / "output"

    with pytest.raises(RuntimeError, match="refresh failed for symbols"):
        module.refresh_selected_pool_prices(
            root=tmp_path,
            market="cn",
            source_csv_dir=source,
            output_root=output,
            start="2021-01-01",
            cutoff="2021-01-05",
            router=FakeRouter({}),  # type: ignore[arg-type]
            max_rounds=1,
        )

    manifest_path = output / "artifacts/selected_pool_price_refresh_manifest.json"
    assert manifest_path.is_file()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["status"] == "selected_pool_price_refresh_blocked"
    assert payload["failed_symbols"] == ["000002"]
    assert payload["failure_count"] == 1
    assert payload["all_sources_ready"] is False
    assert payload["all_sources_current"] is False
    assert not (output / "data").exists()


def test_refresh_refuses_nonempty_destination(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_contract(tmp_path, monkeypatch)
    output = tmp_path / "output"
    output.mkdir()
    (output / "existing.txt").write_text("do not overwrite", encoding="utf-8")

    with pytest.raises(FileExistsError, match="not empty"):
        module.refresh_selected_pool_prices(
            root=tmp_path,
            market="cn",
            source_csv_dir=tmp_path / "source",
            output_root=output,
            start="2021-01-01",
            cutoff="2021-01-05",
            router=FakeRouter({}),  # type: ignore[arg-type]
            max_rounds=1,
        )


def test_default_cn_router_prioritizes_yfinance() -> None:
    router = module._default_router("cn")
    assert router.providers_for_market("cn") == [
        "yfinance",
        "efinance",
        "akshare",
        "baostock",
    ]


def test_tigo_identity_contract_rejects_tygo() -> None:
    contract = module._validate_provider_identity(
        market="us", symbol="TIGO", provider_symbol="TIGO"
    )
    assert contract is not None
    assert contract["expected_issuer"] == "Millicom International Cellular S.A."
    with pytest.raises(ValueError, match="forbidden identity substitution"):
        module._validate_provider_identity(
            market="us", symbol="TIGO", provider_symbol="TYGO"
        )
