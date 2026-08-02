from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml

from src.data.adapters.base import FetchRequest, FetchResult
from src.data.us87_professional_prices import (
    build_professional_price_shard,
    finalize_professional_price_bundle,
    shard_count,
    shard_symbols,
)


def _bars(symbol: str, offset: float = 0.0) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=25)
    base = 20.0 + len(symbol) + offset
    values = pd.Series(range(len(dates)), dtype=float) * 0.1 + base
    return pd.DataFrame(
        {
            "date": dates,
            "open": values,
            "high": values + 0.3,
            "low": values - 0.3,
            "close": values + 0.1,
            "volume": 1000.0,
            "amount": (values + 0.1) * 1000.0,
            "factor": 1.0,
            "cash_distribution": 0.0,
            "split_factor": 1.0,
        }
    )


@dataclass
class FakeAdapter:
    name: str
    offset: float = 0.0

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        return FetchResult(
            provider=self.name,
            symbol=req.symbol,
            market=req.market,
            start=req.start,
            end=req.end,
            df=_bars(req.symbol, self.offset),
            provider_symbol=req.symbol,
        )


class RateLimitError(RuntimeError):
    error_class = "rate_limited"
    status_code = 429
    retry_after_seconds = None


@dataclass
class RateLimitedAdapter:
    name: str
    calls: int = 0

    def fetch_daily_bars(self, req: FetchRequest) -> FetchResult:
        self.calls += 1
        raise RateLimitError("quota window exhausted")


def _contract(tmp_path: Path) -> Path:
    pool = tmp_path / "pool.yaml"
    pool.write_text(
        yaml.safe_dump(
            {
                "pool_id": "test_us_pool",
                "candidate_count": 3,
                "symbols": ["AAPL", "MSFT", "TIGO"],
            }
        ),
        encoding="utf-8",
    )
    contract = tmp_path / "contract.yaml"
    contract.write_text(
        yaml.safe_dump(
            {
                "contract_id": "test_governed_prices",
                "pool": {
                    "pool_id": "test_us_pool",
                    "spec": str(pool),
                    "candidate_count": 3,
                    "references": ["QQQ"],
                },
                "history": {"requested_start": "2024-01-01"},
                "sharding": {"shard_size": 2},
                "reconciliation": {
                    "minimum_overlap_sessions": 20,
                    "consensus_p99_adjusted_close_return_diff": 0.001,
                    "consensus_max_adjusted_close_return_diff": 0.01,
                    "consensus_p99_adjusted_open_return_diff": 0.002,
                    "consensus_max_adjusted_open_return_diff": 0.01,
                    "consensus_max_annual_compounded_open_return_drift": 0.002,
                    "consensus_max_full_period_compounded_open_return_drift": 0.002,
                },
            }
        ),
        encoding="utf-8",
    )
    return contract


def test_shard_helpers_are_deterministic():
    symbols = ["A", "B", "C", "D", "E"]
    assert shard_count(symbols, shard_size=2) == 3
    assert shard_symbols(symbols, shard_size=2, shard_index=1) == ["C", "D"]


def test_shards_finalize_exact_canonical_pool(tmp_path: Path):
    contract = _contract(tmp_path)
    output = tmp_path / "output"
    for index in range(2):
        shard = build_professional_price_shard(
            root=tmp_path,
            contract_path=contract,
            output_root=output,
            cutoff="2024-03-15",
            shard_index=index,
            canonical_adapter=FakeAdapter("yfinance"),
            validation_adapters={
                "tiingo": FakeAdapter("tiingo"),
                "polygon": FakeAdapter("polygon"),
            },
        )
        assert shard["complete"] is True
        assert {row["status"] for row in shard["records"]} == {
            "canonical_ready_validated"
        }
    manifest = finalize_professional_price_bundle(
        root=tmp_path,
        contract_path=contract,
        output_root=output,
        cutoff="2024-03-15",
    )
    assert manifest["status"] == "ready"
    assert manifest["expected_symbol_count"] == 4
    assert manifest["canonical_provider"] == "yfinance"
    assert manifest["professional_sources_validation_only"] is True
    assert manifest["professional_source_ready"] is False
    assert set(manifest["symbol_statuses"]) == {"AAPL", "MSFT", "TIGO", "QQQ"}
    persisted = json.loads(
        (output / "professional_price_manifest.json").read_text(encoding="utf-8")
    )
    assert persisted["pool_id"] == "test_us_pool"


def test_missing_validators_do_not_replace_or_block_canonical(tmp_path: Path):
    contract = _contract(tmp_path)
    shard = build_professional_price_shard(
        root=tmp_path,
        contract_path=contract,
        output_root=tmp_path / "output",
        cutoff="2024-03-15",
        shard_index=0,
        canonical_adapter=FakeAdapter("yfinance"),
        validation_adapters={"tiingo": None, "polygon": None},
    )
    assert shard["complete"] is True
    assert {row["status"] for row in shard["records"]} == {
        "canonical_ready_unvalidated"
    }
    assert all(row["canonical_path"] for row in shard["records"])


def test_validator_rate_limit_opens_circuit_without_losing_canonical(tmp_path: Path):
    contract = _contract(tmp_path)
    validator = RateLimitedAdapter("tiingo")
    shard = build_professional_price_shard(
        root=tmp_path,
        contract_path=contract,
        output_root=tmp_path / "output",
        cutoff="2024-03-15",
        shard_index=0,
        canonical_adapter=FakeAdapter("yfinance"),
        validation_adapters={"tiingo": validator, "polygon": None},
    )
    assert shard["complete"] is True
    assert validator.calls == 1
    attempts = [row["validator_attempts"]["tiingo"] for row in shard["records"]]
    assert attempts[0]["error_class"] == "rate_limited"
    assert attempts[1]["error_class"] == "provider_circuit_open"
    assert all(row["canonical_path"] for row in shard["records"])
