from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from src.data.adapters.base import FetchRequest, FetchResult
from src.data.data_recipe import (
    DataRecipeError,
    data_recipe_catalog,
    data_recipe_status,
    prepare_data_recipe,
)
from src.data.strategy_data_bundle import load_strategy_data_bundle
from tests.selected_pool_price_fixtures import selected_pool_price_source


@dataclass
class CountingAdapter:
    name: str
    calls: list[str] = field(default_factory=list)

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        self.calls.append(req.symbol)
        start = "2024-01-30" if req.symbol == "QQQI" else "2024-01-02"
        dates = pd.bdate_range(start, periods=35)
        base = 20.0 + (sum(ord(value) for value in req.symbol) % 15)
        values = pd.Series(range(len(dates)), dtype=float) * 0.1 + base
        frame = pd.DataFrame(
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


def _copy(root: Path, *paths: str) -> None:
    for value in paths:
        source = Path(value)
        destination = root / source
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)


def test_registry_discovers_all_governed_recipes() -> None:
    catalog = data_recipe_catalog(Path.cwd())
    identities = {row["recipe_id"] for row in catalog["recipes"]}
    assert identities == {
        "qqq-rotation",
        "qqq-rotation-sgov",
        "us87-prices",
        "cn130-prices",
    }
    assert catalog["trade_ready"] is False


def test_sgov_recipe_binds_six_symbols_and_roles(tmp_path: Path) -> None:
    _copy(
        tmp_path,
        "configs/data_recipes/registry_v1.yaml",
        "configs/data_recipes/qqq_rotation_sgov_v1.yaml",
        "configs/data_contracts/qqq_rotation_sgov_model_data_v1.yaml",
        "configs/data/qqqi_qqq_tqqq_reference_bundle_v1.yaml",
    )
    primary = CountingAdapter("tiingo")
    fallback = CountingAdapter("yfinance")
    supplemental = CountingAdapter("yfinance")

    result = prepare_data_recipe(
        "qqq-rotation-sgov",
        root=tmp_path,
        cutoff="2024-03-15",
        refresh=True,
        primary_adapter=primary,
        fallback_adapter=fallback,
        reference_adapter=supplemental,
    )

    bars, coverage, manifest = load_strategy_data_bundle(
        Path(result["strategy_bundle_root"])
    )
    assert set(bars) == {"QQQ", "QQQI", "TQQQ", "SGOV", "^VIX", "^VXN"}
    assert manifest["roles"]["SGOV"] == "tradable"
    assert manifest["roles"]["^VIX"] == "signal_reference"
    assert set(supplemental.calls) == {"SGOV", "^VIX", "^VXN"}
    assert set(coverage["status"]) == {"ready"}
    assert result["profile_gate"]["status"] == "ready"


def test_selected_pool_recipe_builds_and_reuses_provider_snapshot(
    tmp_path: Path,
) -> None:
    _copy(
        tmp_path,
        "configs/data_recipes/registry_v1.yaml",
        "configs/data_recipes/us87_prices_v1.yaml",
        "configs/data_contracts/model_data_bundle_v1.yaml",
        "configs/research_universes/us_selected_equities_v2.yaml",
        "configs/research_universes/cn_selected_equities_v3.yaml",
    )
    calls: list[str] = []

    def fake_refresh(**kwargs: Any) -> dict[str, Any]:
        calls.append(str(kwargs["cutoff"]))
        output = Path(kwargs["output_root"])
        provider = output / "data/providers/us"
        provider.mkdir(parents=True, exist_ok=True)
        (provider / "provider_manifest.json").write_text(
            json.dumps({"provider_id": "fixture-us87"}) + "\n",
            encoding="utf-8",
        )
        manifest = selected_pool_price_source("us")
        manifest["cutoff"] = str(kwargs["cutoff"])
        for record in manifest["records"]:
            if record.get("symbol") != "EA":
                record["last_date"] = str(kwargs["cutoff"])
        path = output / "artifacts/selected_pool_price_refresh_manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        return manifest

    built = prepare_data_recipe(
        "us87-prices",
        root=tmp_path,
        cutoff="2026-08-21",
        refresh=True,
        selected_pool_refresher=fake_refresh,
    )
    assert built["profile_gate"]["status"] == "ready"
    assert Path(built["selected_pool_provider_root"]).is_dir()
    assert calls == ["2026-08-21"]
    assert Path(built["product_manifest_path"]).name == (
        "selected_pool_price_publication_manifest.json"
    )

    reused = prepare_data_recipe(
        "us87-prices",
        root=tmp_path,
        cutoff="2026-08-21",
        selected_pool_refresher=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError(kwargs)
        ),
    )
    assert reused["status"] == "reused"
    assert data_recipe_status(
        "us87-prices", root=tmp_path, cutoff="2026-08-21"
    )["status"] == "reused"

    def changed_refresh(**kwargs: Any) -> dict[str, Any]:
        manifest = fake_refresh(**kwargs)
        manifest["records"][0]["output_sha256"] = "0" * 64
        path = Path(kwargs["output_root"]) / (
            "artifacts/selected_pool_price_refresh_manifest.json"
        )
        path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        return manifest

    with pytest.raises(DataRecipeError, match="projection mismatch"):
        prepare_data_recipe(
            "us87-prices",
            root=tmp_path,
            cutoff="2026-08-21",
            refresh=True,
            selected_pool_refresher=changed_refresh,
        )
