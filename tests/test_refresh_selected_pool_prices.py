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
    )

    assert payload["pool_id"] == "test_cn_pool"
    assert payload["target_count"] == 1
    assert payload["targets"] == ["000002"]
    assert router.calls == ["000002"]
    assert payload["all_sources_ready"] is True
    assert (output / "data/csv_source/000001.csv").is_file()
    assert (output / "data/csv_source/000002.csv").is_file()
    assert (output / "data/csv_source/000300.csv").is_file()
    assert (
        output / "artifacts/selected_pool_price_refresh_manifest.json"
    ).is_file()


def test_refresh_fails_without_partially_publishing_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_contract(tmp_path, monkeypatch)
    source = tmp_path / "source"
    _write_csv(source / "000001.csv", _frame())
    _write_csv(source / "000300.csv", _frame())
    output = tmp_path / "output"

    with pytest.raises(RuntimeError, match="all providers failed"):
        module.refresh_selected_pool_prices(
            root=tmp_path,
            market="cn",
            source_csv_dir=source,
            output_root=output,
            start="2021-01-01",
            cutoff="2026-06-18",
            router=FakeRouter({}),  # type: ignore[arg-type]
        )

    assert not output.exists()


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
        )
