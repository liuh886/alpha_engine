from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import yaml

import src.research.minimal_fundamental_validation as validation

CONTRACT = Path("configs/factors/us_fundamental_acceleration_v1.yaml")
POOL = Path("configs/pools/us_small_pool_v1.yaml")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _pool() -> tuple[dict[str, str], list[str]]:
    payload = yaml.safe_load(POOL.read_text(encoding="utf-8"))
    candidates = {
        str(symbol): str(basket)
        for basket, meta in payload["baskets"].items()
        for symbol in meta["symbols"]
    }
    references = list(payload["references"])
    return candidates, references


def _prices(path: Path, *, selected_outperform: bool) -> pd.DatetimeIndex:
    candidates, references = _pool()
    dates = pd.bdate_range("2020-01-02", "2026-07-02")
    top_by_basket: dict[str, str] = {}
    for symbol, basket in candidates.items():
        top_by_basket.setdefault(basket, symbol)
    rows: list[dict] = []
    for symbol in [*candidates, *references]:
        if symbol in top_by_basket.values():
            daily = 0.00075 if selected_outperform else 0.00010
        elif symbol == "QQQ":
            daily = 0.00030
        elif symbol in references:
            daily = 0.00028
        else:
            daily = 0.00020
        price = 50.0
        for date in dates:
            rows.append(
                {
                    "date": date.date().isoformat(),
                    "symbol": symbol,
                    "open": price,
                    "high": price * 1.001,
                    "low": price * 0.999,
                    "close": price,
                    "volume": 1_000_000,
                }
            )
            price *= 1.0 + daily
    pd.DataFrame(rows).to_csv(path, index=False)
    return dates


def _fake_factor_run_factory(dates: pd.DatetimeIndex):
    candidates, _ = _pool()
    top_by_basket: dict[str, str] = {}
    for symbol, basket in candidates.items():
        top_by_basket.setdefault(basket, symbol)
    evaluation_dates = list(dates[100::20])
    if evaluation_dates[-1] != dates[-1]:
        evaluation_dates.append(dates[-1])

    def fake_run(**kwargs):
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        score_rows: list[dict] = []
        selection_rows: list[dict] = []
        for date in evaluation_dates:
            for basket in sorted(set(candidates.values())):
                selected = [top_by_basket[basket]]
                selection_rows.append(
                    {
                        "date": date.date().isoformat(),
                        "basket": basket,
                        "selected_symbols": selected,
                        "kept_symbols": selected,
                        "added_symbols": [],
                        "removed_symbols": [],
                        "target_weight_per_symbol": 1.0 / len(top_by_basket),
                    }
                )
            for symbol, basket in candidates.items():
                basket_symbols = [name for name, group in candidates.items() if group == basket]
                rank = basket_symbols.index(symbol) + 1
                score_rows.append(
                    {
                        "date": date.date().isoformat(),
                        "symbol": symbol,
                        "basket": basket,
                        "stable_factor_key": "fundamental_acceleration_equal_weight",
                        "revenue_growth_acceleration": float(len(basket_symbols) - rank + 1),
                        "gross_margin_yoy_change": float(len(basket_symbols) - rank + 1),
                        "score": 1.0 if symbol == top_by_basket[basket] else 0.25,
                        "percentile": 1.0 if symbol == top_by_basket[basket] else 0.25,
                        "eligible": True,
                        "selected": symbol == top_by_basket[basket],
                    }
                )
        payloads = {
            "factor_scores.json": {
                "schema_version": "1.0",
                "factor_contract_id": "us_fundamental_acceleration_v1",
                "rows": score_rows,
            },
            "selection_history.json": {
                "schema_version": "1.0",
                "factor_contract_id": "us_fundamental_acceleration_v1",
                "rows": selection_rows,
            },
            "decision.json": {
                "decision": "fundamental_acceleration_scores_ready",
                "trade_ready": False,
            },
        }
        for filename, payload in payloads.items():
            _write_json(output / filename, payload)
        manifest = {
            "outputs": {
                filename: _sha(output / filename) for filename in payloads
            }
        }
        _write_json(output / "evidence_manifest.json", manifest)
        return payloads["decision.json"]

    return fake_run


def _run(tmp_path: Path, monkeypatch, *, selected_outperform: bool) -> dict:
    prices = tmp_path / "prices.csv"
    dates = _prices(prices, selected_outperform=selected_outperform)
    fundamentals = tmp_path / "fundamentals.csv"
    fundamentals.write_text("source-bound fixture\n", encoding="utf-8")
    monkeypatch.setattr(
        validation,
        "run_fundamental_acceleration",
        _fake_factor_run_factory(dates),
    )
    return validation.run_minimal_fundamental_validation(
        contract_path=CONTRACT,
        fundamentals_csv=fundamentals,
        prices_csv=prices,
        output_dir=tmp_path / "output",
        registry_db=None,
    )


def test_supported_fixture_requires_independent_validation(tmp_path: Path, monkeypatch) -> None:
    result = _run(tmp_path, monkeypatch, selected_outperform=True)

    assert result["decision"] == "simple_fundamental_factor_independent_validation_required"
    assert result["failed_gates"] == []
    assert result["trade_ready"] is False
    assert result["performance_evaluated"] is True
    assert result["average_holding_sessions"] >= 40
    assert (
        result["metrics"]["candidate_with_sma100"]["falsification"]["total_return"]
        > result["metrics"]["qqq"]["falsification"]["total_return"]
    )


def test_weak_fixture_is_rejected_without_tuning(tmp_path: Path, monkeypatch) -> None:
    result = _run(tmp_path, monkeypatch, selected_outperform=False)

    assert result["decision"] == "simple_fundamental_factor_not_supported"
    assert "development_qqq_relative_return" in result["failed_gates"]
    assert "falsification_qqq_relative_return" in result["failed_gates"]


def test_outputs_are_manifest_bound(tmp_path: Path, monkeypatch) -> None:
    _run(tmp_path, monkeypatch, selected_outperform=True)
    output = tmp_path / "output"
    manifest = json.loads((output / "evidence_manifest.json").read_text(encoding="utf-8"))

    assert manifest["outputs"]["decision.json"] == _sha(output / "decision.json")
    assert manifest["outputs"]["report.md"] == _sha(output / "report.md")
    assert len(manifest["manifest_identity_sha256"]) == 64
