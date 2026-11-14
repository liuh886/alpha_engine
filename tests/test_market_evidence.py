from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

from src.artifacts.model_run_exporter import (
    RunExportPlan,
    SectionPlan,
    export_model_run,
    update_catalog,
)
from src.dashboard.formal_bundle_market_events import load_formal_market_runs
from src.dashboard.market_evidence import (
    MarketEvidenceError,
    _bars,
    _chart_studies,
    _filter_factor_frame,
    _factor_stats,
    _market_evidence_input_identity,
    _provider_symbol_for_formal_instrument,
    _reuse_market_evidence_tree,
    _trade_events,
    build_market_evidence,
)
from src.data.selected_pool_price_publication import (
    PUBLICATION_MANIFEST_NAME,
    write_selected_pool_price_publication_manifest,
)
from src.factors.library import load_factor_library
from tests.selected_pool_price_fixtures import selected_pool_price_source


def _price_frame(rows: int = 80) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=rows, freq="D")
    close = pd.Series([100.0 + index * 0.4 + math.sin(index / 4) for index in range(rows)])
    return pd.DataFrame(
        {
            "date": dates,
            "open": close - 0.2,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": [1_000_000 + index * 100 for index in range(rows)],
        }
    )


def _monotonic_frame(direction: int, rows: int = 40) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=rows, freq="D")
    close = pd.Series([100.0 + direction * index for index in range(rows)])
    return pd.DataFrame(
        {
            "date": dates,
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": [1_000_000] * rows,
        }
    )


def test_chart_studies_share_the_same_ohlcv_clock() -> None:
    frame = _price_frame()
    studies = _chart_studies(frame)
    assert studies["boll20"]
    assert studies["macd_12_26_9"]
    assert studies["rsi14"]
    assert studies["boll20"][-1]["time"] == frame.iloc[-1]["date"].date().isoformat()
    assert 0.0 <= studies["rsi14"][-1]["value"] <= 100.0


def test_rsi_handles_zero_loss_zero_gain_and_flat_boundaries() -> None:
    rising = _chart_studies(_monotonic_frame(1))["rsi14"]
    falling = _chart_studies(_monotonic_frame(-1))["rsi14"]
    flat = _chart_studies(_monotonic_frame(0))["rsi14"]
    assert rising[-1]["value"] == 100.0
    assert falling[-1]["value"] == 0.0
    assert flat[-1]["value"] == 50.0


def test_bars_retain_real_ohlcv_and_reject_invalid_rows() -> None:
    frame = _price_frame(3)
    frame.loc[1, "high"] = frame.loc[1, "low"] - 1.0
    rows = _bars(frame)
    assert len(rows) == 2
    assert rows[0]["open"] != rows[0]["close"]
    assert rows[0]["volume"] > 0


def test_formal_instrument_identity_maps_to_provider_without_browser_aliases() -> None:
    assert _provider_symbol_for_formal_instrument("cn", "BYD") == "002594"
    assert _provider_symbol_for_formal_instrument("cn", "515180.SH") == "515180"
    assert _provider_symbol_for_formal_instrument("cn", "600519.SH") == "600519"
    assert _provider_symbol_for_formal_instrument("us", "QQQI") == "QQQI"
    assert _provider_symbol_for_formal_instrument("us", "CASH") is None


def test_trade_events_keep_model_and_canonical_instrument_identity() -> None:
    packages = [
        {
            "model_id": "byd_v1_2",
            "display_name": "BYD v1.2",
            "backtest_id": "run-a",
            "positions": [
                {
                    "instrument": "BYD",
                    "name": "比亚迪",
                    "date": "2026-01-02",
                    "weight": 0.75,
                }
            ],
            "trades": [
                {
                    "date": "2026-01-02",
                    "instrument": "BYD",
                    "action": "BUY",
                    "previous_weight": 0.0,
                    "target_weight": 0.75,
                    "weight_delta": 0.75,
                    "reason": "allocation_change",
                },
                {
                    "date": "2026-01-02",
                    "instrument": "515180.SH",
                    "action": "BUY",
                    "previous_weight": 0.0,
                    "target_weight": 0.25,
                    "weight_delta": 0.25,
                },
                {
                    "date": "2026-01-02",
                    "instrument": "CASH",
                    "action": "SELL",
                    "previous_weight": 1.0,
                    "target_weight": 0.0,
                    "weight_delta": -1.0,
                },
            ],
        },
        {
            "model_id": "cn_x1_1",
            "display_name": "CN x1.1",
            "backtest_id": "run-b",
            "positions": [],
            "trades": [
                {
                    "date": "2026-01-02",
                    "instrument": "002594",
                    "action": "DECREASE",
                    "previous_weight": 0.1,
                    "target_weight": 0.05,
                    "weight_delta": -0.05,
                }
            ],
        },
    ]
    events, labels = _trade_events(packages, "cn")
    assert labels["002594"] == "比亚迪"
    assert [row["model_id"] for row in events["002594"]] == ["byd_v1_2", "cn_x1_1"]
    assert events["002594"][0]["source_instrument"] == "BYD"
    assert events["002594"][0]["instrument_id"] == "cn:002594"
    assert events["515180"][0]["source_instrument"] == "515180.SH"
    assert "CASH" not in events
    assert all(row["research_only"] is True for row in events["002594"])
    assert all(row["trade_ready"] is False for row in events["002594"])


def test_factor_statistics_are_distribution_evidence_not_importance() -> None:
    library = load_factor_library("configs/factor_libraries/ohlcv.yaml")
    factor_id = "ohlcv.momentum.ret_10d"
    values = pd.DataFrame({factor_id: [float(value) / 100 for value in range(-50, 51)]})
    rows = _factor_stats(
        values,
        library,
        [factor_id],
        market="us",
        pool_id="test_pool",
        start="2026-01-01",
        cutoff="2026-06-30",
    )
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == "ready"
    assert row["sample_count"] == 101
    assert row["median"] == 0.0
    assert len(row["histogram"]) == 24
    assert "importance" not in row


def test_candidate_factor_filter_is_vectorized_and_case_normalized() -> None:
    index = pd.MultiIndex.from_tuples(
        [
            ("2026-01-02", "aaa"),
            ("2026-01-02", "BBB"),
            ("2026-01-03", "AAA"),
        ],
        names=["datetime", "instrument"],
    )
    evaluated = pd.DataFrame({"factor": [1.0, 2.0, 3.0]}, index=index)

    filtered = _filter_factor_frame(evaluated, ["AaA"])

    assert filtered["factor"].tolist() == [1.0, 3.0]
    assert filtered.index.tolist() == [
        ("2026-01-02", "aaa"),
        ("2026-01-03", "AAA"),
    ]


def _write_json(path: Path, payload: dict[str, object]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def test_content_addressed_market_evidence_reuse_verifies_every_file(
    tmp_path: Path,
) -> None:
    source = tmp_path / "accepted" / "us"
    factor_sha = _write_json(
        source / "factor-diagnostics.json",
        {"factors": [], "research_only": True, "trade_ready": False},
    )
    symbol_sha = _write_json(
        source / "symbols/AAA.json",
        {"symbol": "AAA", "research_only": True, "trade_ready": False},
    )
    identity = "a" * 64
    _write_json(
        source / "catalog.json",
        {
            "input_identity_sha256": identity,
            "factor_diagnostics_path": "factor-diagnostics.json",
            "factor_diagnostics_sha256": factor_sha,
            "symbol_count": 1,
            "symbols": [
                {
                    "path": "symbols/AAA.json",
                    "sha256": symbol_sha,
                    "formal_event_count": 0,
                }
            ],
            "research_only": True,
            "trade_ready": False,
        },
    )
    destination = tmp_path / "candidate" / "us"
    catalog = _reuse_market_evidence_tree(
        source_root=source,
        destination_root=destination,
        expected_input_identity=identity,
    )
    assert catalog is not None
    assert (destination / "symbols/AAA.json").read_bytes() == (
        source / "symbols/AAA.json"
    ).read_bytes()

    (source / "symbols/AAA.json").write_text("tampered", encoding="utf-8")
    with pytest.raises(MarketEvidenceError, match="hash mismatch"):
        _reuse_market_evidence_tree(
            source_root=source,
            destination_root=tmp_path / "rejected" / "us",
            expected_input_identity=identity,
        )


def test_market_evidence_identity_ignores_only_transient_provider_error(
    tmp_path: Path,
) -> None:
    source = selected_pool_price_source("cn")
    changed = copy.deepcopy(source)
    changed["records"][-1]["attempts"][0]["error"] = "new transient error"
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    write_selected_pool_price_publication_manifest(first, source)
    write_selected_pool_price_publication_manifest(second, changed)
    library = load_factor_library("configs/factor_libraries/ohlcv.yaml")

    assert first.read_bytes() == second.read_bytes()
    assert _market_evidence_input_identity(
        market="cn", manifest_path=first, packages=[], factor_library=library
    ) == _market_evidence_input_identity(
        market="cn", manifest_path=second, packages=[], factor_library=library
    )


def _formal_fixture_plan(model_id: str = "us_x9") -> RunExportPlan:
    return RunExportPlan(
        model_family_id="us_ranker",
        model_version_id=model_id,
        run_id=f"{model_id}-through-2026_08_11",
        model_kind="cross_sectional_ranker",
        publication_channel="formal",
        publication_status="accepted_formal_baseline",
        generated_at="2026-08-12T00:00:00Z",
        evidence_cutoff="2026-08-11",
        comparability_key={
            "market": "us",
            "universe_id": "us_selected_equities_v2",
            "benchmark_id": "qqq",
            "start": "2026-01-02",
            "end": "2026-08-11",
            "trace_frequency": "10_session",
            "horizon": "10_sessions",
            "rebalance_contract_id": "top15_sector4_10_sessions",
            "cost_contract_id": "cost_20_bps",
        },
        sections=(
            SectionPlan(
                section_id="summary",
                availability_status="available",
                required_for_model_kind=True,
                payload={
                    "display_name": "US x9",
                    "research_only": True,
                    "trade_ready": False,
                },
            ),
            SectionPlan(
                section_id="portfolio",
                availability_status="available",
                required_for_model_kind=True,
                payload={
                    "positions": [
                        {
                            "date": "2026-08-01",
                            "instrument": "BE",
                            "weight": 1.0,
                        }
                    ],
                    "research_only": True,
                    "trade_ready": False,
                },
            ),
            SectionPlan(
                section_id="trades",
                availability_status="available",
                required_for_model_kind=True,
                payload=[
                    {
                        "date": "2026-08-01",
                        "instrument": "BE",
                        "action": "BUY",
                        "previous_weight": 0.0,
                        "target_weight": 1.0,
                        "weight_delta": 1.0,
                    }
                ],
            ),
        ),
    )


def test_formal_market_runs_follow_catalog_and_ignore_stray_files(tmp_path: Path) -> None:
    root = tmp_path / "formal-v2"
    manifest = export_model_run(_formal_fixture_plan(), output_root=root)
    update_catalog([manifest], catalog_path=root / "catalog.json", channel="formal")
    (root / "stale_superseded.json").write_text(
        json.dumps({"model_id": "stale_model", "trades": [{"instrument": "BE"}]}),
        encoding="utf-8",
    )

    runs = load_formal_market_runs(root, "us")
    assert [row["model_id"] for row in runs] == ["us_x9"]
    assert runs[0]["trades"][0]["instrument"] == "BE"
    events, _ = _trade_events(runs, "us")
    assert [row["model_id"] for row in events["BE"]] == ["us_x9"]


def test_repository_formal_bundle_v2_projects_current_market_models() -> None:
    root = Path("data/research/formal_model_runs")
    us = load_formal_market_runs(root, "us")
    cn = load_formal_market_runs(root, "cn")

    assert {row["model_id"] for row in us} == {
        "qqqi_qqq_tqqq_v4_3",
        "us_x1_3",
    }
    assert {row["model_id"] for row in cn} == {
        "byd_v1_3_recovery_event_low_vol_confirmation_v1",
        "cn_27_v1_3",
    }

    events, _ = _trade_events(us, "us")
    assert "BE" in events
    assert any(row["model_id"] == "us_x1_3" for row in events["BE"])


def _us_provider_root_with_sp500(tmp_path: Path) -> Path:
    source = selected_pool_price_source("us")
    source["candidate_symbols"] = ["QQQ"]
    source["candidate_count"] = 1
    source["benchmark"] = "QQQ"
    source["selected_providers"] = {"QQQ": "yfinance", "SPX": "yfinance"}
    source["targets"] = ["QQQ", "SPX"]
    source["target_count"] = 2
    source["auxiliary_symbols"] = ["SPX"]
    source["stale_symbols"] = []
    source["unresolved_stale_symbols"] = []
    source["lifecycle_declared_terminal_symbols"] = []
    source["terminal_history_symbols"] = []
    source["terminal_listing_evidence"] = {}
    source["all_sources_current"] = True

    provider_root = tmp_path / "provider-us"
    records: list[dict[str, object]] = []
    for symbol, provider_symbol in (("QQQ", "QQQ"), ("SPX", "^GSPC")):
        csv_path = provider_root / "data/csv_source" / f"{symbol}.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        _price_frame().to_csv(csv_path, index=False, lineterminator="\n")
        record = copy.deepcopy(source["records"][0])
        record["symbol"] = symbol
        record["provider_symbol"] = provider_symbol
        record["output_sha256"] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        record["attempts"][0]["provider_symbol"] = provider_symbol
        records.append(record)
    source["records"] = records
    write_selected_pool_price_publication_manifest(
        provider_root / "artifacts" / PUBLICATION_MANIFEST_NAME, source
    )
    return provider_root


def _formal_root_without_trades(tmp_path: Path) -> Path:
    plan = _formal_fixture_plan()
    plan = replace(
        plan,
        sections=(
            plan.sections[0],
            SectionPlan(
                section_id="portfolio",
                availability_status="available",
                required_for_model_kind=True,
                payload={
                    "positions": [],
                    "research_only": True,
                    "trade_ready": False,
                },
            ),
            SectionPlan(
                section_id="trades",
                availability_status="available",
                required_for_model_kind=True,
                payload=[],
            ),
        ),
    )
    root = tmp_path / "formal-v2"
    manifest = export_model_run(plan, output_root=root)
    update_catalog([manifest], catalog_path=root / "catalog.json", channel="formal")
    return root


class _StubFactorEvaluator:
    def __init__(self, *, provider_uri: Path, market: str) -> None:
        self.provider_uri = provider_uri
        self.market = market

    def evaluate(
        self,
        *,
        symbols: list[str],
        expressions: list[str],
        start: str,
        end: str,
    ) -> pd.DataFrame:
        dates = pd.to_datetime(["2026-01-02", "2026-01-05"])
        index = pd.MultiIndex.from_product(
            [dates, list(symbols)], names=["datetime", "instrument"]
        )
        return pd.DataFrame(
            0.0,
            index=index,
            columns=list(range(len(expressions))),
        )


def test_market_evidence_publishes_governed_sp500_auxiliary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider_root = _us_provider_root_with_sp500(tmp_path)
    formal_root = _formal_root_without_trades(tmp_path)
    monkeypatch.setattr(
        "src.dashboard.market_evidence.QlibFactorEvaluator",
        _StubFactorEvaluator,
    )

    result = build_market_evidence(
        market="us",
        provider_root=provider_root,
        formal_root=formal_root,
        output_root=tmp_path / "market-evidence",
    )
    assert result["reused"] is False

    market_root = tmp_path / "market-evidence" / "us"
    catalog = json.loads((market_root / "catalog.json").read_text(encoding="utf-8"))
    rows = {row["symbol"]: row for row in catalog["symbols"]}

    spx = rows["SPX"]
    assert spx["provider_symbol"] == "SPX"
    assert spx["symbol"] == "SPX"
    assert spx["instrument_id"] == "us:SPX"
    assert spx["path"] == "symbols/SPX.json"
    assert spx["roles"] == ["formal_auxiliary"]
    # Dashboard loader identity contract:
    # qlib-dashboard/src/lib/security-evidence.ts.
    assert re.fullmatch(r"[A-Za-z0-9._-]+", str(spx["symbol"]))
    assert spx["path"] == f"symbols/{spx['symbol']}.json"
    assert spx["instrument_id"] == f"us:{spx['symbol']}"
    assert catalog["auxiliary_symbols"] == ["SPX"]

    payload = json.loads(
        (market_root / "symbols/SPX.json").read_text(encoding="utf-8")
    )
    assert payload["symbol"] == "SPX"
    assert payload["provider_symbol"] == "SPX"
    assert payload["instrument_id"] == "us:SPX"
    assert payload["roles"] == ["formal_auxiliary"]
    assert payload["research_only"] is True
    assert payload["trade_ready"] is False
    assert payload["bars"]

    # The QQQ benchmark identity is unchanged by adding the index auxiliary.
    qqq = rows["QQQ"]
    assert qqq["instrument_id"] == "us:QQQ"
    assert qqq["path"] == "symbols/QQQ.json"
    assert qqq["roles"] == ["selected_pool_candidate", "benchmark"]
    assert catalog["benchmark"] == "QQQ"
