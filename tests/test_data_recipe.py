from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from src.data.adapters.base import FetchRequest, FetchResult
from src.data.data_recipe import data_recipe_status, prepare_data_recipe


CONFIG_PATHS = (
    Path("configs/data_recipes/registry_v1.yaml"),
    Path("configs/data_recipes/qqq_rotation_v1.yaml"),
    Path("configs/data_contracts/qqq_rotation_model_data_v1.yaml"),
    Path("configs/data/qqqi_qqq_tqqq_reference_bundle_v1.yaml"),
)


def _copy_configs(root: Path) -> None:
    for relative in CONFIG_PATHS:
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(relative, destination)


def _bars(symbol: str) -> pd.DataFrame:
    start = "2024-01-30" if symbol == "QQQI" else "2024-01-02"
    dates = pd.bdate_range(start, periods=35)
    base = 20.0 + (sum(ord(value) for value in symbol) % 15)
    values = pd.Series(range(len(dates)), dtype=float) * 0.1 + base
    return pd.DataFrame(
        {
            "date": dates,
            "open": values,
            "high": values + 0.4,
            "low": values - 0.4,
            "close": values + 0.1,
            "volume": 1000.0,
            "amount": (values + 0.1) * 1000.0,
            "factor": 1.0,
            "cash_distribution": 0.0,
            "split_factor": 1.0,
        }
    )


@dataclass
class CountingAdapter:
    name: str
    calls: list[str] = field(default_factory=list)

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        self.calls.append(req.symbol)
        frame = _bars(req.symbol)
        if req.end:
            frame = frame.loc[frame["date"] <= pd.Timestamp(req.end)].copy()
        return FetchResult(
            provider=self.name,
            symbol=req.symbol,
            market=req.market,
            start=req.start,
            end=req.end,
            df=frame,
            provider_symbol=req.symbol,
        )


class ForbiddenAdapter:
    name = "forbidden"

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        raise AssertionError(f"cache reuse unexpectedly fetched {req.symbol}")


def test_prepare_recipe_builds_profile_and_reuses_hash_verified_cache(
    tmp_path: Path,
) -> None:
    _copy_configs(tmp_path)
    tiingo = CountingAdapter("tiingo")
    yahoo = CountingAdapter("yfinance")
    references = CountingAdapter("yfinance")

    built = prepare_data_recipe(
        "qqq-rotation",
        root=tmp_path,
        cutoff="2024-03-15",
        refresh=True,
        primary_adapter=tiingo,
        fallback_adapter=yahoo,
        reference_adapter=references,
    )
    assert built["status"] == "built"
    assert built["profile_gate"]["status"] == "ready"
    assert built["profile_gate"]["references"] == ["^VIX", "^VXN"]
    assert set(tiingo.calls) == {"QQQ", "QQQI", "TQQQ"}
    assert set(references.calls) == {"^VIX", "^VXN"}

    reused = prepare_data_recipe(
        "qqq-rotation",
        root=tmp_path,
        cutoff="2024-03-15",
        primary_adapter=ForbiddenAdapter(),
        fallback_adapter=ForbiddenAdapter(),
        reference_adapter=ForbiddenAdapter(),
    )
    assert reused["status"] == "reused"
    assert reused["profile_gate"]["status"] == "ready"

    status = data_recipe_status(
        "qqq-rotation",
        root=tmp_path,
        cutoff="2024-03-15",
    )
    assert status["status"] == "reused"


def test_recipe_status_fails_closed_after_strategy_data_tampering(
    tmp_path: Path,
) -> None:
    _copy_configs(tmp_path)
    adapter = CountingAdapter("yfinance")
    built = prepare_data_recipe(
        "qqq-rotation",
        root=tmp_path,
        cutoff="2024-03-15",
        refresh=True,
        primary_adapter=CountingAdapter("tiingo"),
        fallback_adapter=adapter,
        reference_adapter=adapter,
    )
    strategy_root = Path(built["strategy_bundle_root"])
    path = strategy_root / "canonical" / "INDEX_VXN.csv"
    path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    status = data_recipe_status(
        "qqq-rotation",
        root=tmp_path,
        cutoff="2024-03-15",
    )
    assert status["status"] == "stale_or_blocked"
