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
    frame.to_csv(path, index=False)


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
    return pool


def test_incremental_refresh_fetches_only_invalid_or_outdated_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_contract(tmp_path, monkeypatch)
    source = tmp_path / "source"
    current = _frame(dates=("2021-01-04", "2021-01-05", "2021-01-06"))
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


def test_full_refresh_fetches_every_candidate_and_benchmark(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_contract(tmp_path, monkeypatch)
    source = tmp_path / "source"
    for symbol in ("000001", "000002", "000300"):
        _write_csv(source / f"{symbol}.csv", _frame())
    router = FakeRouter(
        {symbol: _frame(2.0) for symbol in ("000001", "000002", "000300")}
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


def test_full_refresh_retains_validated_source_when_fetch_is_transiently_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_contract(tmp_path, monkeypatch)
    source = tmp_path / "source"
    for symbol in ("000001", "000002", "000300"):
        _write_csv(source / f"{symbol}.csv", _frame())
    original = (source / "000002.csv").read_bytes()
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
    assert (output / "data" / "csv_source" / "000002.csv").read_bytes() == original


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
