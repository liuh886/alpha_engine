from __future__ import annotations

from pathlib import Path
import json

import pandas as pd
import pytest

from src.research import cn27_v1_3_prospective as prospective
from src.research.cn27_v1_3_prospective import load_prospective_contract
from src.research.cn27_v1_3_prospective import load_source_package
from src.research.cn27_v1_3_prospective import validate_source_package
from src.research.cn27_v1_3_prospective import evaluate_observation_readiness
from src.research.cn27_v1_3_prospective import build_forward_runtime_contract
from src.research.cn27_v1_3_prospective import prospective_gate_failures
from src.research.cn27_v1_3_prospective import run_prospective_validation
from src.research.all_weather_alpha_rotation import sha256_file
from src.research.cn27_v1_3_formalize import (
    formalize_v1_3,
    load_passed_prospective_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "configs/research_experiments/cn_27_v1_3_prospective_validation_v1.yaml"
FORMALIZATION = ROOT / "configs/research_experiments/cn_27_v1_3_formalization_v1.yaml"


def _write_source_package(
    path: Path,
    contract_sha256: str,
    symbols: list[str] | None = None,
    dates: list[str] | None = None,
) -> Path:
    path.mkdir()
    symbols = symbols or ["000300", "515180", *[f"{value:06d}" for value in range(1, 28)]]
    dates = dates or ["2026-09-07"]
    bars = pd.MultiIndex.from_product([dates, symbols], names=["date", "symbol"]).to_frame(
        index=False
    )
    bars = bars.assign(open=10.0, high=10.2, low=9.8, close=10.1, volume=1000.0)
    bars.to_csv(path / "adjusted_ohlcv.csv", index=False)
    bars.to_csv(path / "raw_ohlcv.csv", index=False)
    tradability = pd.MultiIndex.from_product(
        [dates, symbols], names=["date", "symbol"]
    ).to_frame(index=False)
    extraction_day = (pd.Timestamp(max(dates)) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    tradability = tradability.assign(
        listed=True,
        suspended=False,
        one_price=False,
        tradable=True,
    )
    tradability["available_at"] = pd.to_datetime(tradability["date"]).map(
        lambda value: (value + pd.Timedelta(days=1)).strftime("%Y-%m-%dT16:00:00+08:00")
    )
    tradability.to_csv(path / "tradability.csv", index=False)
    pd.DataFrame(
        columns=[
            "event_id",
            "symbol",
            "effective_date",
            "available_at",
            "event_type",
            "adjustment_factor",
        ]
    ).to_csv(path / "corporate_actions.csv", index=False)
    filenames = [
        "adjusted_ohlcv.csv",
        "raw_ohlcv.csv",
        "tradability.csv",
        "corporate_actions.csv",
    ]
    manifest = {
        "schema_version": "cn27_v1_3_prospective_source_v1",
        "candidate_id": "cn_27_v1_3_projected_k2_prospective_challenger",
        "validation_contract_sha256": contract_sha256,
        "provider_name": "test-provider",
        "query_identity": "immutable-test-query",
        "extracted_at": f"{extraction_day}T18:00:00+08:00",
        "revision_policy": "append-only",
        "files": {name: sha256_file(path / name) for name in filenames},
        "research_only": True,
        "trade_ready": False,
    }
    manifest_path = path / "source_manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return manifest_path


def _passing_metrics(gate: dict[str, float]) -> dict[str, float]:
    return {
        "sharpe_log_excess": gate["minimum_sharpe_log_excess"],
        "double_cost_sharpe_log_excess": gate["minimum_double_cost_sharpe_log_excess"],
        "positive_fold_share": gate["minimum_positive_fold_share"],
        "fold_sharpe_25th_percentile": gate["minimum_fold_sharpe_25th_percentile"],
        "worst_timing_perturbation_sharpe": gate["minimum_worst_timing_perturbation_sharpe"],
        "bootstrap_sharpe_percentile_05": gate["minimum_bootstrap_sharpe_percentile_05"],
        "bootstrap_probability_sharpe_above_zero": gate["minimum_bootstrap_probability_sharpe_above_zero"],
        "bootstrap_probability_sharpe_above_one": gate["minimum_bootstrap_probability_sharpe_above_one"],
        "parameter_neighborhood_minimum_sharpe": gate["minimum_parameter_neighborhood_sharpe"],
        "post_drift_effective_names_median": gate["minimum_post_drift_effective_names_median"],
        "post_drift_effective_names_p05": gate["minimum_post_drift_effective_names_p05"],
        "leave_one_sector_out_minimum_sharpe": gate["minimum_leave_one_sector_out_sharpe"],
        "leave_one_sector_out_median_sharpe": gate["minimum_leave_one_sector_out_median_sharpe"],
        "annual_one_way_turnover": gate["maximum_annual_one_way_turnover"],
        "maximum_drawdown_magnitude": gate["maximum_drawdown_magnitude"],
        "parameter_neighborhood_maximum_drawdown_magnitude": gate["maximum_parameter_neighborhood_drawdown_magnitude"],
        "maximum_post_drift_single_equity_sleeve_share": gate["maximum_post_drift_single_equity_sleeve_share"],
        "maximum_post_drift_sector_equity_sleeve_share": gate["maximum_post_drift_sector_equity_sleeve_share"],
        "post_drift_sector_share_p95": gate["maximum_post_drift_sector_share_p95"],
        "maximum_single_name_positive_contribution_share": gate["maximum_single_name_positive_contribution_share"],
        "maximum_single_sector_positive_contribution_share": gate["maximum_single_sector_positive_contribution_share"],
    }


def test_prospective_contract_binds_failed_history_without_promoting() -> None:
    contract = load_prospective_contract(CONTRACT)

    assert contract.spec["research_only"] is True
    assert contract.spec["trade_ready"] is False
    assert contract.spec["automatic_promotion_allowed"] is False
    assert contract.challenger["decision"]["formal_v1_3_created"] is False
    assert contract.spec["observation_contract"]["minimum_sessions"] == 240
    assert contract.spec["observation_contract"]["minimum_calendar_months"] == 12
    assert not (ROOT / "configs/research_paradigms/cn_27_v1_3.yaml").exists()


def test_prospective_contract_fails_closed_on_challenger_hash_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    actual = prospective.sha256_file

    def changed_hash(path: Path) -> str:
        if path.name == "cn_27_v1_3_prospective_challenger.yaml":
            return "0" * 64
        return actual(path)

    monkeypatch.setattr(prospective, "sha256_file", changed_hash)

    with pytest.raises(ValueError, match="challenger contract hash mismatch"):
        load_prospective_contract(CONTRACT)


def test_source_package_requires_declared_files_and_hashes(tmp_path: Path) -> None:
    contract = load_prospective_contract(CONTRACT)
    manifest_path = _write_source_package(tmp_path / "package", sha256_file(CONTRACT))
    package = load_source_package(contract, manifest_path)

    assert set(package.tables) == set(contract.spec["required_input_files"])
    (manifest_path.parent / "adjusted_ohlcv.csv").write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="file hash mismatch: adjusted_ohlcv.csv"):
        load_source_package(contract, manifest_path)


def test_source_package_semantics_cover_frozen_roles_and_tradability(tmp_path: Path) -> None:
    contract = load_prospective_contract(CONTRACT)
    symbols = [
        contract.reference_symbol,
        contract.defensive_symbol,
        *contract.candidate_symbols,
    ]
    manifest_path = _write_source_package(
        tmp_path / "package",
        sha256_file(CONTRACT),
        symbols,
    )
    package = load_source_package(contract, manifest_path)

    sessions = validate_source_package(contract, package)

    assert sessions.strftime("%Y-%m-%d").tolist() == ["2026-09-07"]


def test_observation_gate_requires_both_240_sessions_and_twelve_months() -> None:
    contract = load_prospective_contract(CONTRACT)
    too_short = pd.bdate_range("2026-09-07", periods=239)
    compressed = pd.bdate_range("2026-09-07", periods=240)
    complete = compressed[:-1].append(pd.DatetimeIndex(["2027-09-07"]))

    assert evaluate_observation_readiness(contract, too_short)["ready"] is False
    compressed_result = evaluate_observation_readiness(contract, compressed)
    assert compressed_result["ready"] is False
    assert any(
        reason.startswith("minimum_calendar_months")
        for reason in compressed_result["reasons"]
    )
    assert evaluate_observation_readiness(contract, complete)["ready"] is True

    runtime = build_forward_runtime_contract(contract, complete)
    folds = runtime.spec["evaluation"]["chronological_folds"]
    assert len(folds) == 6
    assert sum(int(fold["sessions"]) for fold in folds) == 240
    assert runtime.spec["windows"]["development"]["start"] == "2026-09-07"
    assert runtime.spec["windows"]["development"]["end"] == "2027-09-07"
    assert runtime.spec["evaluation"]["full_window"]["start"] == "2023-09-01"


def test_prospective_gate_covers_every_frozen_threshold() -> None:
    contract = load_prospective_contract(CONTRACT)
    gate = contract.spec["prospective_gate"]
    passing = _passing_metrics(gate)

    assert prospective_gate_failures(passing, gate) == []
    passing["worst_timing_perturbation_sharpe"] -= 0.01
    passing["maximum_post_drift_sector_equity_sleeve_share"] += 0.01
    assert prospective_gate_failures(passing, gate) == [
        "timing_perturbation_sharpe",
        "post_drift_sector_share",
    ]
    passing["worst_timing_perturbation_sharpe"] = float("nan")
    assert "timing_perturbation_sharpe" in prospective_gate_failures(passing, gate)


def test_incomplete_observation_writes_idempotent_fail_closed_evidence(
    tmp_path: Path,
) -> None:
    contract = load_prospective_contract(CONTRACT)
    symbols = [
        contract.reference_symbol,
        contract.defensive_symbol,
        *contract.candidate_symbols,
    ]
    source = _write_source_package(
        tmp_path / "package",
        sha256_file(CONTRACT),
        symbols,
    )
    output = tmp_path / "evidence"

    first = run_prospective_validation(CONTRACT, source, output_root=output)
    second = run_prospective_validation(CONTRACT, source, output_root=output)

    assert first == second
    assert first["decision"] == "insufficient_prospective_observation"
    assert first["trade_ready"] is False
    assert len(list(output.glob("*/evidence_manifest.json"))) == 1


def test_ready_result_authorizes_packaging_without_automatic_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = load_prospective_contract(CONTRACT)
    symbols = [
        contract.reference_symbol,
        contract.defensive_symbol,
        *contract.candidate_symbols,
    ]
    dates = [
        *pd.bdate_range("2026-09-07", periods=239).strftime("%Y-%m-%d"),
        "2027-09-07",
    ]
    source = _write_source_package(
        tmp_path / "package",
        sha256_file(CONTRACT),
        symbols,
        dates,
    )
    metrics = _passing_metrics(contract.spec["prospective_gate"])
    evaluation = {
        "daily_variants": pd.DataFrame({"date": ["2026-09-07"], "variant_id": ["base"]}),
        "metrics": metrics,
        "concentration": pd.DataFrame({"date": ["2026-09-07"]}),
        "attribution": pd.DataFrame({"date": ["2026-09-07"]}),
        "attribution_summary": {"available": True},
        "failures": [],
    }
    monkeypatch.setattr(prospective, "_evaluate_ready_package", lambda *_: evaluation)

    result = run_prospective_validation(
        CONTRACT,
        source,
        output_root=tmp_path / "evidence",
    )

    assert result["formal_v1_3_packaging_authorized"] is True
    assert result["automatic_promotion_allowed"] is False
    assert result["trade_ready"] is False
    manifest = next((tmp_path / "evidence").glob("*/evidence_manifest.json"))
    formal_path = tmp_path / "formal" / "cn_27_v1_3.yaml"
    formal = formalize_v1_3(FORMALIZATION, manifest, output_path=formal_path)
    assert formal["status"] == "frozen_formal_research_candidate"
    assert formal["promotion_authorized"] is False
    assert formal["trade_ready"] is False
    assert formal_path.is_file()


def test_later_package_must_preserve_every_prior_source_row(tmp_path: Path) -> None:
    contract = load_prospective_contract(CONTRACT)
    symbols = [
        contract.reference_symbol,
        contract.defensive_symbol,
        *contract.candidate_symbols,
    ]
    output = tmp_path / "evidence"
    first = _write_source_package(
        tmp_path / "package1",
        sha256_file(CONTRACT),
        symbols,
        ["2026-09-07"],
    )
    second = _write_source_package(
        tmp_path / "package2",
        sha256_file(CONTRACT),
        symbols,
        ["2026-09-07", "2026-09-08"],
    )
    run_prospective_validation(CONTRACT, first, output_root=output)
    run_prospective_validation(CONTRACT, second, output_root=output)

    third = _write_source_package(
        tmp_path / "package3",
        sha256_file(CONTRACT),
        symbols,
        ["2026-09-07", "2026-09-08", "2026-09-09"],
    )
    adjusted = pd.read_csv(third.parent / "adjusted_ohlcv.csv", dtype={"symbol": str})
    adjusted.loc[0, "close"] = 10.05
    adjusted.to_csv(third.parent / "adjusted_ohlcv.csv", index=False)
    source_manifest = json.loads(third.read_text(encoding="utf-8"))
    source_manifest["files"]["adjusted_ohlcv.csv"] = sha256_file(
        third.parent / "adjusted_ohlcv.csv"
    )
    third.write_text(json.dumps(source_manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="append-only source prefix changed"):
        run_prospective_validation(CONTRACT, third, output_root=output)


def test_formalization_rejects_insufficient_prospective_evidence(tmp_path: Path) -> None:
    contract = load_prospective_contract(CONTRACT)
    symbols = [
        contract.reference_symbol,
        contract.defensive_symbol,
        *contract.candidate_symbols,
    ]
    source = _write_source_package(
        tmp_path / "package",
        sha256_file(CONTRACT),
        symbols,
    )
    output = tmp_path / "evidence"
    run_prospective_validation(CONTRACT, source, output_root=output)
    manifest = next(output.glob("*/evidence_manifest.json"))

    with pytest.raises(ValueError, match="did not pass the frozen gate"):
        load_passed_prospective_evidence(FORMALIZATION, manifest)
