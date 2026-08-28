from __future__ import annotations

import json
from pathlib import Path
from threading import Barrier, Lock

import pandas as pd
import yaml

from src.data import cn_selected_pool_event_sources as sources
from src.data.exact_frame_cache import write_exact_frame_snapshot
from src.data.fundamentals.event_store import FundamentalEvent


RETRIEVED = "2026-08-20T00:00:00+00:00"


def test_provider_lanes_overlap_but_symbols_remain_sequential(monkeypatch) -> None:
    symbols = ["000425", "600000"]
    barriers = {symbol: Barrier(3) for symbol in symbols}
    progress_order: list[str] = []
    statement_started: set[str] = set()
    lock = Lock()

    def enter_lane(symbol: str) -> None:
        if symbol == symbols[1]:
            assert progress_order == [symbols[0]]
        barriers[symbol].wait(timeout=2)

    class FinancialClient:
        def fetch_disclosures(self, *, symbol: str, **_kwargs):
            enter_lane(symbol)
            return pd.DataFrame()

        def fetch_statement(self, *, symbol: str, **_kwargs):
            with lock:
                first_statement = symbol not in statement_started
                statement_started.add(symbol)
            if first_statement:
                enter_lane(symbol)
            return pd.DataFrame()

    class ActionClient:
        def fetch_dividends(self, *, symbol: str):
            enter_lane(symbol)
            return pd.DataFrame()

    client = FinancialClient()
    monkeypatch.setattr(sources, "AsharePublicFinancialClient", lambda: client)
    monkeypatch.setattr(sources, "AsharePublicActionClient", lambda: ActionClient())

    result = sources.populate_cn_selected_pool_event_sources(
        symbols,
        {},
        RETRIEVED,
        start_date="2021-01-01",
        end_date="2026-07-31",
        progress=lambda message: progress_order.append(json.loads(message)["symbol"]),
    )

    assert progress_order == symbols
    assert result.source_reuse["execution"] == {
        "symbol_order": "selected_pool_order",
        "cross_symbol_concurrency": 1,
        "provider_lane_count": 3,
        "max_concurrency_per_provider": 1,
        "elapsed_ms": result.source_reuse["execution"]["elapsed_ms"],
    }
    assert all(result.fundamentals[symbol].status == "partial" for symbol in symbols)
    assert all(
        result.corporate_actions[symbol].status == "no_event_observed"
        for symbol in symbols
    )


def test_successful_lanes_are_reused_after_sibling_failure(monkeypatch, tmp_path: Path) -> None:
    class DisclosureClient:
        def fetch_disclosures(self, **_kwargs):
            return pd.DataFrame()

    class FailingStatementClient:
        def __init__(self):
            self.calls = 0

        def fetch_statement(self, **_kwargs):
            self.calls += 1
            if self.calls == 3:
                raise RuntimeError("statement lane failed")
            return pd.DataFrame()

    class ActionClient:
        def fetch_dividends(self, **_kwargs):
            return pd.DataFrame()

    first_clients = iter([DisclosureClient(), FailingStatementClient()])
    monkeypatch.setattr(
        sources,
        "AsharePublicFinancialClient",
        lambda: next(first_clients),
    )
    monkeypatch.setattr(sources, "AsharePublicActionClient", lambda: ActionClient())

    first = sources.populate_cn_selected_pool_event_sources(
        ["000425"],
        {},
        RETRIEVED,
        start_date="2021-01-01",
        end_date="2026-07-31",
        source_cache_root=tmp_path,
        progress=lambda _message: None,
    )

    assert first.fundamentals["000425"].status == "provider_missing"
    assert (tmp_path / "fundamentals/000425/cninfo/metadata.json").is_file()
    assert not (tmp_path / "fundamentals/000425/sina/metadata.json").exists()
    assert (tmp_path / "corporate_actions/000425/metadata.json").is_file()

    class NoDisclosureFetch:
        def fetch_disclosures(self, **_kwargs):
            raise AssertionError("CNINFO lane should be reused")

    class HealthyStatementClient:
        def fetch_statement(self, **_kwargs):
            return pd.DataFrame()

    class NoActionFetch:
        def fetch_dividends(self, **_kwargs):
            raise AssertionError("Eastmoney lane should be reused")

    second_clients = iter([NoDisclosureFetch(), HealthyStatementClient()])
    monkeypatch.setattr(
        sources,
        "AsharePublicFinancialClient",
        lambda: next(second_clients),
    )
    monkeypatch.setattr(sources, "AsharePublicActionClient", lambda: NoActionFetch())

    second = sources.populate_cn_selected_pool_event_sources(
        ["000425"],
        {},
        "2026-08-21T00:00:00+00:00",
        start_date="2021-01-01",
        end_date="2026-07-31",
        source_cache_root=tmp_path,
        progress=lambda _message: None,
    )

    lanes = second.source_reuse["provider_lanes"]
    assert lanes["cninfo_disclosures"]["exact_cutoff_reuse_count"] == 1
    assert lanes["sina_statements"]["source_fetch_count"] == 1
    assert lanes["eastmoney_dividends"]["exact_cutoff_reuse_count"] == 1
    assert second.source_reuse["fundamentals"]["mixed_source_reuse_count"] == 1
    assert second.fundamentals["000425"].status == "partial"


def test_legacy_combined_fundamental_cache_is_migrated_without_network(
    monkeypatch,
    tmp_path: Path,
) -> None:
    symbol = "000425"
    base_identity = {
        "market": "cn",
        "symbol": symbol,
        "exchange": "SZSE",
        "start": "2021-01-01",
        "cutoff": "2026-07-31",
    }
    empty = pd.DataFrame()
    write_exact_frame_snapshot(
        tmp_path / "fundamentals" / symbol,
        identity={
            **base_identity,
            "source_provider": "akshare_sina_financial_report_cninfo_time",
        },
        retrieved_at=RETRIEVED,
        frames={
            "disclosures": empty,
            "balance_sheet": empty,
            "income_statement": empty,
            "cash_flow_statement": empty,
        },
    )
    write_exact_frame_snapshot(
        tmp_path / "corporate_actions" / symbol,
        identity={**base_identity, "source_provider": "akshare_eastmoney_dividend"},
        retrieved_at=RETRIEVED,
        frames={"dividends": empty},
    )

    class NoFinancialFetch:
        def fetch_disclosures(self, **_kwargs):
            raise AssertionError("legacy CNINFO cache should be reused")

        def fetch_statement(self, **_kwargs):
            raise AssertionError("legacy Sina cache should be reused")

    class NoActionFetch:
        def fetch_dividends(self, **_kwargs):
            raise AssertionError("Eastmoney cache should be reused")

    monkeypatch.setattr(
        sources,
        "AsharePublicFinancialClient",
        lambda: NoFinancialFetch(),
    )
    monkeypatch.setattr(sources, "AsharePublicActionClient", lambda: NoActionFetch())

    result = sources.populate_cn_selected_pool_event_sources(
        [symbol],
        {},
        "2026-08-21T00:00:00+00:00",
        start_date="2021-01-01",
        end_date="2026-07-31",
        source_cache_root=tmp_path,
        progress=lambda _message: None,
    )

    lanes = result.source_reuse["provider_lanes"]
    assert lanes["cninfo_disclosures"]["legacy_exact_cutoff_reuse_count"] == 1
    assert lanes["sina_statements"]["legacy_exact_cutoff_reuse_count"] == 1
    assert lanes["eastmoney_dividends"]["exact_cutoff_reuse_count"] == 1
    assert (tmp_path / "fundamentals/000425/cninfo/metadata.json").is_file()
    assert (tmp_path / "fundamentals/000425/sina/metadata.json").is_file()


def test_cold_and_warm_fundamentals_are_byte_identical_and_progress_uses_stderr(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    class FinancialClient:
        def fetch_disclosures(self, **_kwargs):
            return pd.DataFrame()

        def fetch_statement(self, **_kwargs):
            return pd.DataFrame()

    class ActionClient:
        def fetch_dividends(self, **_kwargs):
            return pd.DataFrame()

    def events(*_args, symbol: str, exchange: str, retrieved_at: str, **_kwargs):
        return [
            FundamentalEvent(
                market="cn",
                symbol=symbol,
                exchange=exchange,
                entity_id=symbol,
                fiscal_period_end="2025-12-31",
                fiscal_year=2025,
                fiscal_period="FY",
                reported_at="2026-03-31",
                available_at="2026-03-31T00:00:00+00:00",
                filing_type="annual_report",
                source_provider="fixture",
                source_document_id="fixture-2025",
                source_endpoint="fixture://financials",
                field="revenue",
                value=1.0,
                unit="CNY",
                currency="CNY",
                is_quarterly=False,
                is_derived=False,
                derivation_rule="none",
                revision_sequence=0,
                supersedes_event_id="",
                retrieved_at=retrieved_at,
                source_hash="a" * 64,
                event_id="fixture-event-1",
            )
        ]

    monkeypatch.setattr(sources, "AsharePublicFinancialClient", lambda: FinancialClient())
    monkeypatch.setattr(sources, "AsharePublicActionClient", lambda: ActionClient())
    monkeypatch.setattr(sources, "cninfo_period_disclosures", lambda _frame: {})
    monkeypatch.setattr(sources, "sina_statement_to_events", events)

    cold = sources.populate_cn_selected_pool_event_sources(
        ["000425"],
        {},
        RETRIEVED,
        start_date="2021-01-01",
        end_date="2026-07-31",
        source_cache_root=tmp_path,
    )
    warm = sources.populate_cn_selected_pool_event_sources(
        ["000425"],
        {},
        "2026-08-21T00:00:00+00:00",
        start_date="2021-01-01",
        end_date="2026-07-31",
        source_cache_root=tmp_path,
    )

    assert [event.to_dict() for event in warm.fundamentals["000425"].events] == [
        event.to_dict() for event in cold.fundamentals["000425"].events
    ]
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cn_selected_pool_symbol_complete" in captured.err


def test_workflow_restores_only_the_latest_rolling_cache_generation() -> None:
    workflow = yaml.safe_load(
        Path(".github/workflows/selected-pool-event-population-ci.yml").read_text(
            encoding="utf-8"
        )
    )
    steps = workflow["jobs"]["live-population"]["steps"]
    restore = next(
        step
        for step in steps
        if step.get("name") == "Restore exact-cutoff event source snapshots"
    )
    populate = next(
        step for step in steps if step.get("name") == "Populate public primary event stores"
    )

    assert restore["uses"] == "actions/cache/restore@v6"
    assert "matrix.market == 'cn'" in restore["if"]
    assert "run" not in restore
    assert "env" not in restore
    assert "selected-pool-events-cn-v2-generation-" in restore["with"]["key"]
    assert restore["with"]["key"].endswith("-${{ github.run_id }}")
    restore_keys = restore["with"]["restore-keys"].splitlines()
    assert len(restore_keys) == 1
    assert "selected-pool-events-cn-v2-generation-" in restore_keys[0]
    assert restore_keys[0].endswith("-")
    assert "${{ github.run_id }}" not in restore_keys[0]
    assert "selected-pool-events-cn-v2-${{ hashFiles(" not in restore["with"][
        "restore-keys"
    ]
    assert "selected-pool-events-cn-${{ hashFiles(" not in restore["with"][
        "restore-keys"
    ]
    assert "uses" not in populate
    assert "populate_selected_pool_events.py" in populate["run"]
