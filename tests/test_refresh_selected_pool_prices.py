import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml

import scripts.data.refresh_selected_pool_prices as module
from src.data.adapters.base import FetchResult
from src.data.router import RouterAttempt, RouterResponse


def _frame(multiplier: float = 1.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": ["2021-01-04", "2021-01-05"],
            "open": [10.0, 11.0],
            "high": [11.0, 12.0],
            "low": [9.0, 10.0],
            "close": [10.5, 11.5],
            "volume": [100.0, 120.0],
            "amount": [1000.0, 1320.0],
            "factor": [multiplier, multiplier],
        }
    )


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False)


class FakeRouter:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames
        self.calls: list[str] = []

    def fetch_daily_bars(
        self,
        *,
        symbol: str,
        market: str,
        start: str,
        end: str | None = None,
        validate: bool = False,
    ) -> RouterResponse:
        del start, end, validate
        self.calls.append(symbol)
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
                start="2021-01-01",
                end="2026-06-18",
                df=frame.copy(),
                provider_symbol=symbol,
            ),
            attempts=[
                RouterAttempt(
                    provider="fake",
                    ok=True,
                    provider_symbol=symbol,
                    rows=len(frame),
                    first_date="2021-01-04",
                    last_date="2021-01-05",
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


def test_refresh_fetches_only_missing_or_invalid_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_contract(tmp_path, monkeypatch)
    source = tmp_path / "source"
    _write_csv(source / "000001.csv", _frame())
    _write_csv(source / "000002.csv", _frame().assign(high=[1.0, 1.0]))
    _write_csv(source / "000300.csv", _frame())
    router = FakeRouter({"000002": _frame(2.0)})
    output = tmp_path / "output"

    payload = module.refresh_selected_pool_prices(
        root=tmp_path,
        market="cn",
        source_csv_dir=source,
        output_root=output,
        start="2021-01-01",
        cutoff="2026-06-18",
        router=router,  # type: ignore[arg-type]
        max_rounds=1,
    )

    assert payload["refresh_mode"] == "repair_only"
    assert payload["target_count"] == 1
    assert payload["targets"] == ["000002"]
    assert payload["candidate_symbols"] == ["000001", "000002"]
    assert payload["auxiliary_symbols"] == []
    assert router.calls == ["000002"]
    assert payload["status"] == "selected_pool_price_refresh_ready"
    assert payload["all_sources_ready"] is True


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
        cutoff="2026-06-18",
        router=router,  # type: ignore[arg-type]
        max_rounds=1,
        full_refresh=True,
    )

    assert payload["refresh_mode"] == "full"
    assert payload["targets"] == ["000001", "000002", "000300"]
    assert router.calls == ["000001", "000002", "000300"]
    assert {row["action"] for row in payload["records"]} == {
        "fetched_full_refresh"
    }


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
        cutoff="2026-06-18",
        router=router,  # type: ignore[arg-type]
        max_rounds=1,
        auxiliary_symbols=["515180"],
    )

    assert payload["candidate_count"] == 2
    assert payload["candidate_symbols"] == ["000001", "000002"]
    assert payload["benchmark"] == "000300"
    assert payload["auxiliary_symbols"] == ["515180"]
    assert payload["targets"] == ["515180"]
    assert router.calls == ["515180"]
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
            cutoff="2026-06-18",
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
            cutoff="2026-06-18",
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
