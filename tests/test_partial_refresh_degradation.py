"""Degradation gates: quarantine one symbol, keep producing the rest.

Phase 2 contract:
- v1 ``allow_partial`` quarantines fetch failures (benchmark quarantine
  still fails closed) instead of melting the market build.
- v2 decorates partial manifests with eligible sets; the market clock still
  requires the benchmark row.
- Strategy adapters exit 10 (data_blocked, retain) only for
  quarantine-caused blocks; everything else stays fatal.
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml

import scripts.data.refresh_selected_pool_prices as v1
from scripts.data.refresh_selected_pool_prices_v2 import _decorate_manifest
from src.artifacts.formal_provider_cache import verify_partial_provider_cache
from src.artifacts.formal_refresh import FormalRefreshError, market_provider_cutoff
from src.artifacts.strategy_refresh_exit import (
    DATA_BLOCKED_EXIT_CODE,
    DataBlockedError,
    assert_shared_provider_coverage,
    read_unavailable_symbols,
)
from src.data.adapters.base import FetchResult
from src.data.router import RouterAttempt, RouterResponse


def _frame(dates=("2021-01-04", "2021-01-05", "2021-01-06")) -> pd.DataFrame:
    opens = [10.0 + index for index in range(len(dates))]
    return pd.DataFrame(
        {
            "date": list(dates),
            "open": opens,
            "high": [value + 1.0 for value in opens],
            "low": [value - 1.0 for value in opens],
            "close": [value + 0.5 for value in opens],
            "volume": [100.0] * len(dates),
            "amount": [1000.0] * len(dates),
            "factor": [1.0] * len(dates),
        }
    )


class FakeRouter:
    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames

    def fetch_daily_bars(
        self,
        *,
        symbol: str,
        market: str,
        start: str,
        end: str | None = None,
        validate: bool = False,
    ) -> RouterResponse:
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


def _prepare_pool(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, symbols=("000001", "000002")
) -> None:
    pool = tmp_path / "pool.yaml"
    pool.write_text(
        yaml.safe_dump(
            {"market": "cn", "candidate_count": len(symbols), "symbols": list(symbols)}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        v1,
        "resolve_selected_pool",
        lambda *args, **kwargs: SimpleNamespace(
            pool_id="test_cn_pool", pool_spec=pool
        ),
    )
    monkeypatch.setattr(
        v1,
        "build_market_provider",
        lambda **kwargs: {"provider_identity_sha256": "c" * 64},
    )
    monkeypatch.setattr(v1, "_terminal_listing_contracts", lambda *args: {})


def _run_v1(tmp_path, monkeypatch, frames, **kwargs):
    _prepare_pool(tmp_path, monkeypatch)
    return v1.refresh_selected_pool_prices(
        root=tmp_path,
        market="cn",
        source_csv_dir=tmp_path / "source",
        output_root=tmp_path / "output",
        start="2021-01-01",
        cutoff="2021-01-06",
        router=FakeRouter(frames),  # type: ignore[arg-type]
        max_rounds=1,
        full_refresh=True,
        **kwargs,
    )


def test_partial_quarantines_failed_symbol_and_builds_rest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served = _frame()
    payload = _run_v1(
        tmp_path,
        monkeypatch,
        {"000001": served, "000300": served},
        allow_partial=True,
    )

    assert payload["status"] == "selected_pool_price_refresh_partial"
    assert payload["quarantined_symbols"] == ["000002"]
    assert payload["all_sources_ready"] is False
    required = (
        payload["candidate_symbols"]
        + [payload["benchmark"]]
        + payload["auxiliary_symbols"]
    )
    materialized = [s for s in required if s not in set(payload["quarantined_symbols"])]
    assert sorted(materialized) == ["000001", "000300"]
    output_csvs = {
        path.name for path in (tmp_path / "output" / "data" / "csv_source").glob("*.csv")
    }
    assert output_csvs == {"000001.csv", "000300.csv"}


def test_partial_still_fails_closed_without_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served = _frame()
    with pytest.raises(RuntimeError, match="selected-pool refresh failed"):
        _run_v1(tmp_path, monkeypatch, {"000001": served, "000300": served})


def test_partial_fails_closed_when_nothing_materializes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(RuntimeError, match="selected-pool refresh failed"):
        _run_v1(tmp_path, monkeypatch, {}, allow_partial=True)


def test_partial_fails_closed_when_benchmark_is_quarantined(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    served = _frame()
    with pytest.raises(RuntimeError, match="selected-pool refresh failed"):
        _run_v1(
            tmp_path, monkeypatch, {"000001": served, "000002": served}, allow_partial=True
        )


def _partial_manifest(**overrides):
    manifest = {
        "market": "cn",
        "cutoff": "2026-09-08",
        "start": "2021-01-01",
        "status": "selected_pool_price_refresh_partial",
        "promotion_eligible": False,
        "quarantined_symbols": ["000002"],
        "candidate_symbols": ["000001", "000002"],
        "benchmark": "000300",
        "auxiliary_symbols": [],
        "comparison_reference_symbols": [],
        "after": {
            "000001": {"status": "ready", "last_date": "2026-09-08"},
            "000300": {"status": "ready", "last_date": "2026-09-08"},
        },
        "records": [
            {"symbol": "000001", "last_date": "2026-09-08", "attempts": []},
            {"symbol": "000300", "last_date": "2026-09-08", "attempts": []},
            {"symbol": "000002", "last_date": "2026-09-01", "attempts": []},
        ],
        "research_only": True,
        "trade_ready": False,
    }
    manifest.update(overrides)
    return manifest


def test_cutoff_accepts_partial_with_benchmark_clock() -> None:
    assert (
        market_provider_cutoff(_partial_manifest(), market="cn") == "2026-09-08"
    )


def test_cutoff_rejects_partial_without_eligible_symbols() -> None:
    manifest = _partial_manifest(
        after={},
        candidate_symbols=["000001"],
        quarantined_symbols=["000001", "000300"],
    )
    with pytest.raises(FormalRefreshError, match="no eligible symbols"):
        market_provider_cutoff(manifest, market="cn")


def test_cutoff_rejects_partial_with_missing_benchmark_clock() -> None:
    manifest = _partial_manifest(
        after={"000001": {"status": "ready", "last_date": "2026-09-08"}},
        quarantined_symbols=["000002", "000300"],
        records=[
            {"symbol": "000001", "last_date": "2026-09-08"},
            {"symbol": "000002", "last_date": "2026-09-01"},
        ],
    )
    with pytest.raises(FormalRefreshError, match="exactly one market clock"):
        market_provider_cutoff(manifest, market="cn")


def test_decorate_partial_computes_eligible_set(tmp_path: Path) -> None:
    from src.data.selected_pool_price_publication import (
        is_partial_eligible,
        partial_eligible_symbols,
    )

    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "market": "cn",
                "cutoff": "2026-09-08",
                "status": "selected_pool_price_refresh_partial",
                "quarantined_symbols": ["000002"],
                "auxiliary_symbols": [],
                "records": [],
                "after": {
                    "000001": {"status": "ready", "last_date": "2026-09-08"},
                    "000300": {"status": "ready", "last_date": "2026-09-08"},
                },
            }
        ),
        encoding="utf-8",
    )
    from scripts.data.refresh_selected_pool_prices_v2 import build_hardened_router

    payload = _decorate_manifest(path, build_hardened_router("cn"))

    assert payload["promotion_eligible"] is False
    assert is_partial_eligible(payload) is True
    assert partial_eligible_symbols(payload) == ["000001", "000300"]
    assert "000002" in payload["promotion_blocker"]


def test_coverage_precheck_raises_only_for_quarantined_gaps(
    tmp_path: Path,
) -> None:
    provider_dir = tmp_path / "provider" / "data" / "providers" / "cn"
    instruments = provider_dir / "instruments"
    instruments.mkdir(parents=True)
    (instruments / "cn.txt").write_text(
        "000001\t2021-01-04\t2026-09-08\n", encoding="utf-8"
    )
    manifest_dir = tmp_path / "provider" / "artifacts"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "selected_pool_price_refresh_manifest.json").write_text(
        json.dumps(
            {
                "status": "selected_pool_price_refresh_partial",
                "quarantined_symbols": ["000002"],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(DataBlockedError, match="000002"):
        assert_shared_provider_coverage(
            provider_dir, ["000001", "000002"], label="probe"
        )
    # Complete coverage returns the quarantine set for receipt binding.
    assert assert_shared_provider_coverage(
        provider_dir, ["000001"], label="probe"
    ) == frozenset({"000002"})


def test_coverage_precheck_ignores_genuinely_missing_symbols(
    tmp_path: Path,
) -> None:
    provider_dir = tmp_path / "provider" / "data" / "providers" / "cn"
    instruments = provider_dir / "instruments"
    instruments.mkdir(parents=True)
    (instruments / "cn.txt").write_text(
        "000001\t2021-01-04\t2026-09-08\n", encoding="utf-8"
    )
    manifest_dir = tmp_path / "provider" / "artifacts"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "selected_pool_price_refresh_manifest.json").write_text(
        json.dumps(
            {
                "status": "selected_pool_price_refresh_partial",
                "quarantined_symbols": ["000002"],
            }
        ),
        encoding="utf-8",
    )

    # 000003 is missing but NOT quarantined: silent passthrough, the
    # adapter's own fail-closed error stays fatal.
    assert_shared_provider_coverage(
        provider_dir, ["000001", "000003"], label="probe"
    )


def test_coverage_precheck_is_noop_without_manifest(tmp_path: Path) -> None:
    provider_dir = tmp_path / "provider" / "data" / "providers" / "cn"
    (provider_dir / "instruments").mkdir(parents=True)
    assert (
        assert_shared_provider_coverage(provider_dir, ["ANY"], label="probe")
        == frozenset()
    )


def test_read_unavailable_symbols_merges_flag_fields() -> None:
    assert read_unavailable_symbols(
        {
            "quarantined_symbols": ["a"],
            "legacy_copied_symbols": ["b"],
            "unresolved_stale_symbols": ["c"],
        }
    ) == frozenset({"A", "B", "C"})


def _partial_provider_tree(tmp_path: Path) -> Path:
    root = tmp_path / "provider-cn"
    (root / "data" / "csv_source").mkdir(parents=True)
    manifest = {
        "market": "cn",
        "cutoff": "2026-09-08",
        "start": "2021-01-01",
        "status": "selected_pool_price_refresh_partial",
        "promotion_eligible": False,
        "quarantined_symbols": ["000002"],
        "candidate_symbols": ["000001"],
        "benchmark": "000300",
        "auxiliary_symbols": ["000002"],
        "comparison_reference_symbols": [],
        "after": {
            "000001": {"status": "ready", "last_date": "2026-09-08"},
        },
        "records": [{"symbol": "000001"}, {"symbol": "000002"}],
        "research_only": True,
        "trade_ready": False,
    }
    (root / "artifacts").mkdir(parents=True)
    (root / "artifacts" / "selected_pool_price_refresh_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return root


def test_verify_partial_accepts_governed_quarantine(tmp_path: Path) -> None:
    root = _partial_provider_tree(tmp_path)
    contract = {"market": "cn", "requested_cutoff": "2026-09-08", "auxiliary_symbols": ["000002"]}
    report = verify_partial_provider_cache(provider_root=root, contract=contract)
    assert report["evidence_type"] == "formal_provider_cache_partial_report"
    assert report["quarantined_symbols"] == ["000002"]
    assert report["eligible_count"] == 1


def test_verify_partial_rejects_quarantine_outside_contract(
    tmp_path: Path,
) -> None:
    root = _partial_provider_tree(tmp_path)
    contract = {"market": "cn", "requested_cutoff": "2026-09-08", "auxiliary_symbols": []}
    with pytest.raises(
        Exception, match="quarantines symbols outside the contract"
    ):
        verify_partial_provider_cache(provider_root=root, contract=contract)


def test_runner_maps_data_blocked_exit_to_retain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    import scripts.run_formal_strategy_refresh as runner

    assert runner.DATA_BLOCKED_EXIT_CODE == 10
    task = {
        "strategy_id": "probe",
        "model_family_id": "probe_family",
        "model_version_id": "probe_v1",
        "model_kind": "probe_kind",
        "market": "cn",
        "planned_provider_cutoff": "2026-09-08",
        "publication_input": "native_bundle_v2",
        "formal_refresh_required": True,
        "mtm_refresh_required": False,
        "formal_refresh_capability_status": "available",
        "formal_refresh_adapter_id": "probe_adapter",
        "formal_refresh_block_reason": None,
    }
    monkeypatch.setattr(runner, "_task", lambda plan, strategy_id: task)

    def run_main(returncode: int) -> dict:
        def _raise(**kwargs):
            raise subprocess.CalledProcessError(returncode, ["probe-adapter"])

        monkeypatch.setattr(runner, "execute_strategy", _raise)
        output_root = tmp_path / f"out-{returncode}"
        argv = [
            "run_formal_strategy_refresh.py",
            "--strategy-id",
            "probe",
            "--plan",
            str(tmp_path / "plan.json"),
            "--provider-root",
            str(tmp_path),
            "--formal-v2-root",
            str(tmp_path),
            "--current-preview-root",
            str(tmp_path),
            "--generated-at",
            "2026-09-09T00:00:00Z",
            "--output-root",
            str(output_root),
        ]
        monkeypatch.setattr(sys, "argv", argv)
        assert runner.main() == 1
        return json.loads(
            (output_root / "probe" / "receipt.json").read_text(encoding="utf-8")
        )

    blocked = run_main(10)
    assert blocked["execution_status"] == "data_blocked"
    failed = run_main(1)
    assert failed["execution_status"] == "execution_failed"


def test_workflow_wires_partial_degradation() -> None:
    workflow = Path(".github/workflows/formal-backtest-refresh.yml")
    text = workflow.read_text(encoding="utf-8")
    assert "--allow-partial" in text
    assert "verify-partial" in text
    assert "selected_pool_price_refresh_partial" in text
    # Governance: the automatic path never carries a full rebuild flag.
    assert "full_refresh" not in text
    # A governed full refresh must bypass the cache restore so vendors are
    # actually refetched; otherwise the flag is a no-op on cache hit.
    restore_block = text.split("Restore requested governed provider cache")[1]
    assert "uses: actions/cache/restore" in restore_block.split("Install locked")[0]
    # The publish job uses the composite python setup: its sparse checkout
    # must include the action directory.
    publish_block = text.split("publish:")[1]
    assert ".github/actions/setup-python-uv" in publish_block


def test_governed_reseed_lives_outside_incremental_workflow() -> None:
    main = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    assert "--full-refresh" not in main
    reseed = Path(".github/workflows/formal-provider-reseed.yml").read_text(
        encoding="utf-8"
    )
    assert "workflow_dispatch" in reseed
    assert "\n  schedule:" not in reseed
    assert "\n  push:" not in reseed
    assert "--full-refresh" in reseed
    assert "--allow-partial" in reseed
    # Sparse-checkout closure: everything the jobs read at runtime must be
    # checked out. Two incidents in two days (vendor pins unreadable, composite
    # action missing) came from adding a file dependency without auditing
    # sparse sets.
    assert "configs" in reseed  # vendor pins live under configs/data/
    assert "reviewed-formal-backtest-refresh-live" in reseed  # no cache races


def test_provider_sparse_sets_cover_runtime_dependencies() -> None:
    text = Path(".github/workflows/formal-backtest-refresh.yml").read_text(
        encoding="utf-8"
    )
    providers = text.split("providers:")[1]
    assert "configs" in providers  # universes, pools, pins, registries
    assert "scripts" in providers and "src" in providers


def test_cn27_data_stage_maps_to_data_blocked_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    import scripts.refresh_cn_27_v1_3_formal as cn27

    def _blocked(**kwargs):
        from src.artifacts.strategy_refresh_exit import DataBlockedError

        raise DataBlockedError("provider restated frozen history for 002463.open")

    monkeypatch.setattr(cn27, "refresh_cn_27_v1_3", _blocked)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "refresh_cn_27_v1_3_formal.py",
            "--current-package",
            str(tmp_path / "current.json"),
            "--provider-dir",
            str(tmp_path / "provider"),
            "--provider-manifest",
            str(tmp_path / "manifest.json"),
            "--cutoff",
            "2026-09-08",
            "--generated-at",
            "2026-09-09T00:00:00Z",
            "--output",
            str(tmp_path / "candidate.json"),
        ],
    )
    assert cn27.main() == DATA_BLOCKED_EXIT_CODE


def test_cn27_contract_errors_stay_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sys

    import scripts.refresh_cn_27_v1_3_formal as cn27

    def _broken(**kwargs):
        raise cn27.Cn27V13RefreshError("frozen k2 recipe identity drifted")

    monkeypatch.setattr(cn27, "refresh_cn_27_v1_3", _broken)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "refresh_cn_27_v1_3_formal.py",
            "--current-package",
            str(tmp_path / "current.json"),
            "--provider-dir",
            str(tmp_path / "provider"),
            "--provider-manifest",
            str(tmp_path / "manifest.json"),
            "--cutoff",
            "2026-09-08",
            "--generated-at",
            "2026-09-09T00:00:00Z",
            "--output",
            str(tmp_path / "candidate.json"),
        ],
    )
    with pytest.raises(cn27.Cn27V13RefreshError, match="recipe identity drifted"):
        cn27.main()


def test_cn27_requires_evidence_completeness_from_incumbent(
    tmp_path: Path,
) -> None:
    import json

    import scripts.refresh_cn_27_v1_3_formal as cn27

    current = tmp_path / "current.json"
    current.write_text(
        json.dumps(
            {
                "model_id": "cn_27_v1_3",
                "evidence_cutoff": "2026-09-04",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(
        cn27.Cn27V13RefreshError, match="evidence completeness is missing"
    ):
        cn27.refresh_cn_27_v1_3(
            current_package=current,
            provider_dir=tmp_path / "provider",
            provider_manifest=tmp_path / "manifest.json",
            cutoff="2026-09-08",
            generated_at="2026-09-09T00:00:00Z",
            output=tmp_path / "candidate.json",
        )


def test_overlap_clears_half_cent_vendor_rounding() -> None:
    import scripts.refresh_cn_27_v1_3_formal as cn27

    assert cn27.VERIFY_FIELDS == ("open", "high", "low", "close")
    expected = pd.Series([4031.095, 3965.516, 3851.405])
    observed = pd.Series([4031.09, 3965.52, 3851.41])
    assert cn27._overlap_matches(expected, observed) is True


def test_overlap_still_catches_adjustment_flips() -> None:
    import scripts.refresh_cn_27_v1_3_formal as cn27

    expected = pd.Series([17.465, 18.565, 17.565])
    observed = pd.Series([17.57, 18.66, 17.67])
    assert cn27._overlap_matches(expected, observed) is False
