from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.research.paradigm import load_research_paradigm_spec
from src.research.real_market_acceptance import evaluate_real_market_acceptance


def _write_factor_library(path: Path) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "1.0",
                "groups": {
                    "test_group": {
                        "description": "test",
                        "factors": [
                            {
                                "id": "test:momentum",
                                "expression": "$close/Ref($close,5)-1",
                                "family": "momentum",
                            }
                        ],
                    },
                    "factor_baselines": {
                        "description": "test baseline",
                        "factors": [
                            {
                                "id": "factor:test_momentum",
                                "expression": "$close/Ref($close,10)-1",
                                "family": "baseline",
                            }
                        ],
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _write_spec(
    root: Path,
    *,
    symbols: list[object],
    include_metadata: bool = True,
) -> Path:
    universe_path = root / "universe.yaml"
    universe_path.write_text(yaml.safe_dump({"us": symbols}, sort_keys=False), encoding="utf-8")
    factor_path = root / "factors.yaml"
    _write_factor_library(factor_path)

    universe = {
        "source": str(universe_path),
        "market_key": "us",
        "min_symbols": 2,
        "alignment_mode": "strict",
    }
    if include_metadata:
        universe.update(
            {
                "universe_id": "test_us_equities_v1",
                "membership_mode": "static_curated",
                "membership_as_of": "2026-06-18",
                "asset_type": "equity",
                "survivorship_bias": True,
            }
        )

    payload = {
        "schema_version": "1.0",
        "experiment_id": "test_real_market_acceptance",
        "market": "us",
        "benchmark": "QQQ",
        "universe": universe,
        "factor_library": {"source": str(factor_path), "groups": ["test_group"]},
        "candidate_grid": {
            "ranker": {
                "calibrations": [
                    {
                        "n_gain_bins": 3,
                        "num_boost_round": 10,
                        "num_leaves": 7,
                        "min_data_in_leaf": 2,
                        "learning_rate": 0.05,
                    }
                ]
            },
            "factor_baselines": ["factor:test_momentum"],
        },
        "strategy": {
            "horizon_days": 10,
            "holding_days": 10,
            "rebalance_days": 10,
            "top_n": 1,
            "bottom_n": 1,
            "return_expression": "Ref($close, -10) / $close - 1",
            "return_provenance": "raw_forward_return",
            "research_only": True,
        },
        "walk_forward": {
            "requested_train_start": "2021-01-01",
            "test_end": "2026-06-18",
            "first_test_year": 2024,
            "last_test_year": 2026,
            "min_windows": 3,
            "train_embargo_sessions": 10,
        },
        "evaluation": {
            "benchmark_mode": "reference_only",
            "metrics": [
                "mean_icir",
                "mean_rank_ic",
                "mean_spread",
                "worst_drawdown",
                "ready_ratio",
                "positive_icir_ratio",
                "positive_spread_ratio",
            ],
            "gate_profile": "ten_day_model_gates_v1",
        },
        "outputs": {"artifact_profile": "research_run_v1"},
    }
    spec_path = root / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return spec_path


def _write_market_data(root: Path, symbols: list[str]) -> tuple[Path, Path]:
    provider = root / "data" / "watchlist"
    csv_dir = root / "data" / "csv_source"
    (provider / "calendars").mkdir(parents=True)
    (provider / "instruments").mkdir(parents=True)
    csv_dir.mkdir(parents=True)

    dates = pd.bdate_range("2021-01-01", "2026-06-18")
    (provider / "calendars" / "day.txt").write_text(
        "\n".join(date.strftime("%Y-%m-%d") for date in dates) + "\n",
        encoding="utf-8",
    )
    (provider / "instruments" / "us.txt").write_text(
        "\n".join(f"{symbol}\t2021-01-01\t2026-06-18" for symbol in symbols) + "\n",
        encoding="utf-8",
    )

    for offset, symbol in enumerate(symbols):
        close = 100.0 + offset + np.linspace(0.0, 20.0, len(dates))
        frame = pd.DataFrame(
            {
                "date": dates,
                "open": close - 0.5,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": 1_000_000 + offset,
            }
        )
        frame.to_csv(csv_dir / f"{symbol}.csv", index=False)
    return provider, csv_dir


def _statuses(report: dict) -> dict[str, str]:
    return {item["name"]: item["status"] for item in report["checks"]}


def test_real_market_acceptance_passes_complete_non_synthetic_data(tmp_path: Path) -> None:
    spec_path = _write_spec(tmp_path, symbols=["AAPL", "MSFT", "NVDA"])
    provider, csv_dir = _write_market_data(tmp_path, ["AAPL", "MSFT", "NVDA", "QQQ"])
    spec = load_research_paradigm_spec(spec_path)

    report = evaluate_real_market_acceptance(
        spec,
        root=tmp_path,
        provider_dir=provider,
        csv_dir=csv_dir,
    )

    assert report["accepted"] is True
    assert report["summary"]["failed"] == 0
    assert _statuses(report)["survivorship_bias"] == "warn"


def test_acceptance_rejects_synthetic_fixture_and_benchmark_in_universe(tmp_path: Path) -> None:
    spec_path = _write_spec(tmp_path, symbols=["AAPL", "MSFT", "QQQ"])
    provider, csv_dir = _write_market_data(tmp_path, ["AAPL", "MSFT", "QQQ"])
    (provider / "fixture_manifest.json").write_text("{}", encoding="utf-8")
    spec = load_research_paradigm_spec(spec_path)

    report = evaluate_real_market_acceptance(
        spec,
        root=tmp_path,
        provider_dir=provider,
        csv_dir=csv_dir,
    )

    statuses = _statuses(report)
    assert report["accepted"] is False
    assert statuses["real_provider_scope"] == "fail"
    assert statuses["benchmark_exclusion"] == "fail"


def test_acceptance_rejects_numeric_yaml_symbol_identity(tmp_path: Path) -> None:
    spec_path = _write_spec(tmp_path, symbols=[1, "MSFT", "NVDA"])
    provider, csv_dir = _write_market_data(tmp_path, ["000001", "MSFT", "NVDA", "QQQ"])
    spec = load_research_paradigm_spec(spec_path)

    report = evaluate_real_market_acceptance(
        spec,
        root=tmp_path,
        provider_dir=provider,
        csv_dir=csv_dir,
    )

    assert report["accepted"] is False
    assert _statuses(report)["source_symbol_types"] == "fail"


def test_acceptance_rejects_fabricated_or_invalid_ohlcv(tmp_path: Path) -> None:
    spec_path = _write_spec(tmp_path, symbols=["AAPL", "MSFT", "NVDA"])
    provider, csv_dir = _write_market_data(tmp_path, ["AAPL", "MSFT", "NVDA", "QQQ"])
    bad = pd.read_csv(csv_dir / "MSFT.csv")
    bad.loc[10, "close"] = 0.0
    bad.loc[20, "high"] = bad.loc[20, "low"] - 1.0
    bad.to_csv(csv_dir / "MSFT.csv", index=False)
    spec = load_research_paradigm_spec(spec_path)

    report = evaluate_real_market_acceptance(
        spec,
        root=tmp_path,
        provider_dir=provider,
        csv_dir=csv_dir,
    )

    integrity = next(item for item in report["checks"] if item["name"] == "source_csv_integrity")
    assert report["accepted"] is False
    assert integrity["status"] == "fail"
    assert "MSFT" in integrity["details"]["invalid"]
