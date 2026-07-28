"""Tests for spec-bound execution identity and evidence acceptance."""

from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
import pytest

from src.research.paradigm import ResearchParadigmSpec
from src.research.spec_bound_execution import (
    DECLARED_EXECUTION_CONTRACT_FILENAME,
    EFFECTIVE_EXECUTION_CONTRACT_FILENAME,
    EXECUTION_IDENTITY_FILENAME,
    SpecBoundExecutionResult,
    build_declared_execution_contract,
    build_spec_bound_execution_plan,
    contract_sha256,
    execute_spec_bound_research,
)

CN_SPEC = Path("configs/research_paradigms/cn_10d_csi300_baseline.yaml")


def _load_cn_spec() -> ResearchParadigmSpec:
    if not CN_SPEC.is_file():
        pytest.skip("CN structured research contract is unavailable")
    return ResearchParadigmSpec.from_yaml(CN_SPEC)


def test_declared_contract_is_deterministic() -> None:
    spec = _load_cn_spec()
    first = build_declared_execution_contract(spec)
    second = build_declared_execution_contract(spec)
    assert first == second
    assert contract_sha256(first) == contract_sha256(second)
    assert first["experiment_id"] == spec.experiment_id
    assert first["universe"]["requested_symbols"]
    assert first["factors"]["candidates"]
    assert first["factors"]["baseline_factors"]


def test_plan_contains_exact_declared_candidates() -> None:
    spec = _load_cn_spec()
    plan = build_spec_bound_execution_plan(spec)
    declared = plan.declared_contract
    assert list(plan.candidates) == declared["factors"]["candidates"]
    assert plan.baseline_factors == declared["factors"]["baseline_factors"]
    assert plan.declared_contract_sha256 == contract_sha256(declared)


def test_matching_effective_contract_accepts_evidence() -> None:
    spec = _load_cn_spec()

    def executor(plan, run_dir: Path) -> SpecBoundExecutionResult:
        evidence = run_dir / "adapter_evidence.json"
        evidence.write_text('{"status":"ok"}', encoding="utf-8")
        return SpecBoundExecutionResult(
            status="passed",
            effective_contract=copy.deepcopy(plan.declared_contract),
            runtime_metadata={"retained_symbol_count": 50},
            evidence_paths={"adapter_evidence": "adapter_evidence.json"},
        )

    with tempfile.TemporaryDirectory() as output_dir:
        result = execute_spec_bound_research(
            spec,
            executor,
            output_dir=output_dir,
        )
        run_dir = Path(result["run_dir"])
        assert result["status"] == "passed"
        assert result["contract_identity_verified"] is True
        assert result["declared_contract_sha256"] == result["effective_contract_sha256"]
        assert (run_dir / DECLARED_EXECUTION_CONTRACT_FILENAME).is_file()
        assert (run_dir / EFFECTIVE_EXECUTION_CONTRACT_FILENAME).is_file()
        identity = json.loads(
            (run_dir / EXECUTION_IDENTITY_FILENAME).read_text(encoding="utf-8")
        )
        assert identity["matched"] is True
        assert identity["differences"] == []
        status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
        assert status["status"] == "passed"
        assert status["failed_stage"] == ""
        assert status["research_only"] is True
        assert status["trade_ready"] is False


def test_contract_mismatch_fails_before_evidence_acceptance() -> None:
    spec = _load_cn_spec()

    def executor(plan, run_dir: Path) -> SpecBoundExecutionResult:
        effective = copy.deepcopy(plan.declared_contract)
        effective["strategy"]["top_n"] = int(effective["strategy"]["top_n"]) + 1
        evidence = run_dir / "must_not_be_accepted.json"
        evidence.write_text('{"status":"should_not_attach"}', encoding="utf-8")
        return SpecBoundExecutionResult(
            status="passed",
            effective_contract=effective,
            evidence_paths={"invalid": str(evidence)},
        )

    with tempfile.TemporaryDirectory() as output_dir:
        with pytest.raises(ValueError, match="execution contract mismatch"):
            execute_spec_bound_research(spec, executor, output_dir=output_dir)
        run_dir = Path(output_dir) / spec.experiment_id
        identity = json.loads(
            (run_dir / EXECUTION_IDENTITY_FILENAME).read_text(encoding="utf-8")
        )
        assert identity["matched"] is False
        assert any("strategy.top_n" in item for item in identity["differences"])
        status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
        assert status["status"] == "failed"
        assert status["failed_stage"] == "execution_identity"
        assert status["trade_ready"] is False


def test_missing_declared_evidence_file_fails_closed() -> None:
    spec = _load_cn_spec()

    def executor(plan, run_dir: Path) -> SpecBoundExecutionResult:
        return SpecBoundExecutionResult(
            status="passed",
            effective_contract=copy.deepcopy(plan.declared_contract),
            evidence_paths={"missing": "missing.json"},
        )

    with tempfile.TemporaryDirectory() as output_dir:
        with pytest.raises(FileNotFoundError, match="missing evidence file"):
            execute_spec_bound_research(spec, executor, output_dir=output_dir)


# ── PIT (point-in-time) contract identity tests ───────────────────────────

PIT_SPEC = Path(
    "configs/research_paradigms/us_10d_lgbm_xgb_ranker_pit_robustness.yaml"
)


def _load_pit_spec() -> ResearchParadigmSpec:
    if not PIT_SPEC.is_file():
        pytest.skip("PIT robustness spec unavailable")
    return ResearchParadigmSpec.from_yaml(PIT_SPEC)


def test_pit_contract_includes_snapshot_identity() -> None:
    """PIT contract identity covers snapshot hash, per-date memberships,
    and per-window OOS membership mapping."""
    spec = _load_pit_spec()
    contract = build_declared_execution_contract(spec)

    u = contract["universe"]
    assert u["membership_mode"] == "window_start_point_in_time"
    assert u["oos_membership_point_in_time"] is True
    assert u["full_daily_point_in_time"] is False

    dates = u["pit_snapshot_dates"]
    assert isinstance(dates, list)
    assert len(dates) == 11

    for entry in dates:
        assert "date" in entry
        assert "count" in entry
        assert "sha256_membership_hash" in entry
        assert isinstance(entry["count"], int)
        assert len(entry["sha256_membership_hash"]) == 64

    # Per-window OOS membership mapping
    wm = u["pit_window_membership"]
    assert isinstance(wm, dict)
    assert len(wm) == 4  # 2024H1, 2024H2, 2025H1, 2025H2
    nominal_starts = {
        "2024H1": "2024-01-01",
        "2024H2": "2024-07-01",
        "2025H1": "2025-01-01",
        "2025H2": "2025-07-01",
    }
    for label in ("2024H1", "2024H2", "2025H1", "2025H2"):
        win = wm[label]
        assert win["nominal_test_start"] == nominal_starts[label]
        assert len(win["sha256_membership_hash"]) == 64
        assert win["count"] == len(win["symbols"])
        assert win["count"] >= 100

    # Deterministic
    contract2 = build_declared_execution_contract(spec)
    assert contract_sha256(contract) == contract_sha256(contract2)


def test_pit_contract_different_windows_different_symbol_sets() -> None:
    """At least two snapshot dates have distinct membership hashes."""
    spec = _load_pit_spec()
    contract = build_declared_execution_contract(spec)

    hashes = {
        entry["date"]: entry["sha256_membership_hash"]
        for entry in contract["universe"]["pit_snapshot_dates"]
    }
    unique_hashes = set(hashes.values())
    assert len(unique_hashes) >= 2, (
        "Expected at least two distinct membership hashes across snapshot dates"
    )
    # 2021-01-04 and 2021-07-01 legitimately share one hash; all other dates differ
    assert len(unique_hashes) >= 10, (
        f"Expected 10+ unique hashes, got {len(unique_hashes)}"
    )


def test_static_spec_unchanged_by_pit_infrastructure() -> None:
    """Static-curated universe specs are byte/behavior compatible — no PIT
    fields leak into their contracts."""
    spec = _load_cn_spec()
    contract = build_declared_execution_contract(spec)

    u = contract["universe"]
    # Backward-compatible key set: no membership_mode or PIT fields.
    assert "membership_mode" not in u, (
        "Static spec must not contain membership_mode"
    )
    assert "oos_membership_point_in_time" not in u
    assert "full_daily_point_in_time" not in u
    assert "pit_snapshot_dates" not in u

    # Exact prior static universe contract key set regression.
    _STATIC_UNIVERSE_KEYS = frozenset({
        "source", "source_sha256", "market_key",
        "requested_symbols", "min_symbols", "alignment_mode",
    })
    assert frozenset(u) == _STATIC_UNIVERSE_KEYS, (
        f"Static universe keys changed: expected {_STATIC_UNIVERSE_KEYS}, "
        f"got {frozenset(u)}"
    )


def test_pit_benchmark_not_in_requested_symbols() -> None:
    """QQQ benchmark is never in the PIT tradable universe."""
    spec = _load_pit_spec()
    contract = build_declared_execution_contract(spec)

    benchmark = contract["benchmark"].upper()
    requested = {s.upper() for s in contract["universe"]["requested_symbols"]}
    assert benchmark not in requested, (
        f"Benchmark {benchmark} must not leak into tradable PIT symbols"
    )


def test_pit_contract_identity_changes_with_different_snapshot_hash(
    tmp_path: Path,
) -> None:
    """Altering a snapshot date's membership hash changes the contract identity.

    This uses a valid recomputed hash — the modified snapshot passes hash
    validation so the contract builder does not reject it.
    """
    from dataclasses import replace

    from src.research.ndx_window_start_universe import compute_membership_hash
    from src.research.spec_bound_execution import _source_path

    spec = _load_pit_spec()
    first = build_declared_execution_contract(spec)
    first_sha = contract_sha256(first)

    # Resolve the snapshot path and create a modified copy.
    snapshot_path = _source_path(spec, str(spec.universe["source"]))
    original_raw = json.loads(snapshot_path.read_text(encoding="utf-8"))

    modified_raw = copy.deepcopy(original_raw)
    # Alter a symbol in the first snapshot date and recompute its hash.
    modified_raw["snapshot_dates"][0]["symbols"][0] = "ZZZZ_MODIFIED"
    modified_raw["snapshot_dates"][0]["count"] = len(
        modified_raw["snapshot_dates"][0]["symbols"]
    )
    modified_raw["snapshot_dates"][0]["sha256_membership_hash"] = (
        compute_membership_hash(modified_raw["snapshot_dates"][0]["symbols"])
    )

    modified_path = tmp_path / "ndx_modified.json"
    modified_path.write_text(json.dumps(modified_raw), encoding="utf-8")

    modified_universe = dict(spec.universe)
    modified_universe["source"] = str(modified_path)
    modified_spec = replace(spec, universe=modified_universe)

    second = build_declared_execution_contract(modified_spec)
    second_sha = contract_sha256(second)

    assert first_sha != second_sha, (
        "Modifying a snapshot symbol must change the contract identity"
    )


# ── Compact PIT executor behavior tests ──────────────────────────────


def test_pit_executor_two_windows_different_symbol_sets(
    tmp_path: Path,
) -> None:
    """Two windows call runtime.features with different declared PIT symbol sets
    and the benchmark remains a separate one-symbol features call.

    Uses compact mocks for fit/run/summary so the test exercises PIT-specific
    behavior (universe planning, feature loading, window iteration, benchmark
    separation) without real model fitting.
    """
    from unittest.mock import patch

    from src.research.qlib_execution_common import (
        execute_qlib_plan,
    )
    from src.research.ndx_window_start_universe import (
        load_snapshot,
        resolve_latest_snapshot_on_or_before,
    )

    spec = _load_pit_spec()
    plan = build_spec_bound_execution_plan(spec)

    features_call_args: list[dict[str, Any]] = []
    all_syms: set[str] = set(
        plan.declared_contract["universe"]["requested_symbols"]
    )
    all_syms.add("QQQ")

    class _PITMockRuntime:
        def initialize(self, root: Path) -> None:
            pass

        def available_symbols(self) -> set[str]:
            return all_syms

        def date_coverage(
            self,
            symbols: Sequence[str],
            start: str,
            end: str,
        ) -> dict[str, dict[str, Any]]:
            return {
                s: {
                    "first_valid_date": start,
                    "last_valid_date": end,
                    "observations": 500,
                    "covers_train_start": True,
                    "covers_test_end": True,
                    "sufficient_coverage": True,
                }
                for s in symbols
            }

        def calendar(self, start: str, end: str) -> pd.DatetimeIndex:
            return pd.date_range(start, end, freq="B")

        def features(
            self,
            symbols: Sequence[str],
            expressions: Sequence[str],
            start: str,
            end: str,
        ) -> pd.DataFrame:
            features_call_args.append({
                "symbols": sorted(symbols),
                "n_expressions": len(expressions),
                "start": start,
                "end": end,
            })
            cal = self.calendar(start, end)
            instruments = sorted(symbols)
            idx = pd.MultiIndex.from_product(
                [cal, instruments],
                names=["datetime", "instrument"],
            )
            rng = np.random.default_rng(42)
            return pd.DataFrame(
                rng.normal(0, 1, (len(idx), len(expressions))),
                index=idx,
                columns=list(expressions),
            )

        def metadata(self) -> dict[str, Any]:
            return {"provider": "pit_mock"}

    # ── Compact mocks for fit/run/summary ──────────────────────────────
    fit_train_indices: list[pd.MultiIndex] = []

    def _fake_fit_ranker_scores(
        candidate: Any,
        features_train: pd.DataFrame,
        returns_train: pd.DataFrame,
        features_test: pd.DataFrame,
        expression_columns: dict[str, str],
    ) -> pd.DataFrame:
        del candidate, returns_train, expression_columns
        fit_train_indices.append(features_train.index.copy())
        return pd.DataFrame(
            {"score": np.arange(len(features_test), dtype=float)},
            index=features_test.index,
        )

    mock_report = {
        "candidates": {},
        "n_reports": 1,
        "n_candidates": 2,
        "best_candidate": "lgbm:momentum_volatility_volume:gain5_round100...",
        "stability": {"mean_icir": 0.3, "icir_std": 0.05},
        "survived_windows": 3,
        "compounded_relative_excess": 0.30,
        "passed": True,
        "summary": {"survived": 3, "total": 3},
    }

    mock_stability = {
        "n_reports": 3,
        "n_candidates": 2,
        "best_candidate": mock_report["best_candidate"],
        "stability": mock_report["stability"],
        "reports": [],
    }

    with (
        patch(
            "src.research.qlib_execution_common.fit_ranker_scores",
            side_effect=_fake_fit_ranker_scores,
        ),
        patch(
            "src.research.qlib_execution_common.run_10d_experiment",
            return_value=mock_report,
        ),
        patch(
            "src.research.qlib_execution_common.summarize_walk_forward_reports",
            return_value=mock_stability,
        ),
    ):
        runtime = _PITMockRuntime()
        result = execute_qlib_plan(
            plan,
            tmp_path / plan.spec.experiment_id,
            market="us",
            runtime=runtime,
        )

    # 1. Execution passes with synthetic data
    assert result.status == "passed", (
        f"PIT executor should pass; got status={result.status!r}"
    )

    # 2. PIT provenance in runtime metadata
    pit_prov = result.runtime_metadata.get("pit_window_provenance", {})
    assert pit_prov, "PIT provenance must be present in runtime metadata"

    # 3. At least two distinct snapshot dates across windows
    snap_dates = set()
    for prov in pit_prov.values():
        if not prov.get("skipped"):
            snap_dates.add(prov.get("snapshot_date"))
    assert len(snap_dates) >= 2, (
        f"Expected at least 2 distinct PIT snapshot dates across windows, "
        f"got {len(snap_dates)}: {snap_dates}"
    )

    # 4. Separate benchmark features call (one symbol = QQQ)
    bench_calls = [
        c for c in features_call_args
        if len(c["symbols"]) == 1 and c["symbols"][0] == "QQQ"
    ]
    assert len(bench_calls) >= 1, (
        "Benchmark must be loaded via separate one-symbol features call"
    )

    # 5. Window features calls have different symbol sets when PIT
    #    snapshots differ across windows.
    win_calls = [
        c for c in features_call_args
        if len(c["symbols"]) > 1
    ]
    win_sym_sets = {frozenset(c["symbols"]) for c in win_calls}
    assert len(win_sym_sets) >= 2, (
        f"Expected at least 2 distinct PIT symbol sets in features calls, "
        f"got {len(win_sym_sets)}"
    )

    # 6. Every retained training row belongs to the latest membership snapshot
    #    known on that row's date; no future OOS membership leaks backward.
    snapshot = load_snapshot(
        Path(spec.universe["source"]),
        validate_hashes=True,
        validate_source=True,
    )
    assert fit_train_indices
    for index in fit_train_indices:
        dates = index.get_level_values("datetime")
        instruments = index.get_level_values("instrument")
        for date in dates.unique():
            actual = set(instruments[dates == date])
            declared = set(
                resolve_latest_snapshot_on_or_before(
                    snapshot,
                    pd.Timestamp(date).strftime("%Y-%m-%d"),
                ).symbols
            )
            assert actual <= declared

    # 7. Static contract exact keys unchanged by PIT infrastructure.
    _STATIC_UNIVERSE_KEYS = frozenset({
        "source", "source_sha256", "market_key",
        "requested_symbols", "min_symbols", "alignment_mode",
    })
    cn_spec = _load_cn_spec()
    cn_contract = build_declared_execution_contract(cn_spec)
    assert frozenset(cn_contract["universe"]) == _STATIC_UNIVERSE_KEYS, (
        f"Static universe keys changed: {frozenset(cn_contract['universe'])}"
    )

    # 8. aligned_train_start_by_window present in runtime_metadata
    assert "aligned_train_start_by_window" in result.runtime_metadata, (
        "PIT runtime_metadata must contain aligned_train_start_by_window"
    )
    by_window = result.runtime_metadata["aligned_train_start_by_window"]
    assert len(by_window) >= 1
    for label, date_str in by_window.items():
        assert isinstance(date_str, str) and len(date_str) == 10, (
            f"aligned_train_start for {label} must be ISO date, got {date_str!r}"
        )

    # 9. Scalar aligned_train_start matches by-window values and is documented
    pit_aligned = result.runtime_metadata["aligned_train_start"]
    by_window_values = list(by_window.values())
    assert pit_aligned in by_window_values, (
        f"scalar aligned_train_start {pit_aligned!r} must appear in "
        f"per-window values: {by_window_values}"
    )
    assert "aligned_train_start_note" in result.runtime_metadata

    # 10. On-disk readiness and universe artifacts are corrected
    readiness_path = tmp_path / plan.spec.experiment_id / "data_readiness.json"
    assert readiness_path.is_file()
    on_disk_readiness = json.loads(readiness_path.read_text(encoding="utf-8"))
    assert on_disk_readiness.get("aligned_train_start") == pit_aligned
    assert on_disk_readiness.get("aligned_train_start_by_window") == by_window
    assert "aligned_train_start_note" in on_disk_readiness

    universe_path = tmp_path / plan.spec.experiment_id / "universe_report.json"
    assert universe_path.is_file()
    on_disk_universe = json.loads(universe_path.read_text(encoding="utf-8"))
    assert on_disk_universe.get("aligned_train_start") == pit_aligned
    assert on_disk_universe.get("aligned_train_start_by_window") == by_window
