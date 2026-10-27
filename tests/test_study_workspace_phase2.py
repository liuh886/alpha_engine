"""Test suite for Phase 2: Multi-Domain Research Study Workspace Integration.

Verifies that Walk-Forward, Cross-Sectional XGBoost, Factor Exploration,
and A-Share RDI risk events share the unified research workspace entry point,
governed data slice plane, and cryptographic receipts without duplicate data cleaning.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.cli.main import main
from src.research.study_workspace import (
    AShareRDIConfig,
    CrossSectionalXGBConfig,
    FactorExplorationConfig,
    ResearchStudyError,
    compare_studies,
    initialize_study,
    inspect_study,
    load_study_spec,
    run_study,
    study_catalog,
)
from src.research.walkforward.contracts import WalkForwardConfig

ROOT = Path(__file__).resolve().parents[1]


def test_phase2_catalog_lists_all_four_study_families() -> None:
    catalog = study_catalog(root=ROOT)
    assert catalog["research_only"] is True
    assert catalog["trade_ready"] is False
    studies = catalog["studies"]
    assert len(studies) == 4

    study_ids = {s["id"] for s in studies}
    assert study_ids == {
        "us_tech_vol_reversal_v1",
        "cross_sectional_xgb_v1",
        "factor_exploration_v1",
        "ashare_rdi_v1",
    }

    engines = {s["engine"] for s in studies}
    assert engines == {
        "walkforward_volatility_reversal",
        "cross_sectional_xgb",
        "factor_exploration",
        "ashare_rdi",
    }

    for s in studies:
        assert isinstance(s["editable"], list) and len(s["editable"]) > 0
        assert "limitation" in s and len(s["limitation"]) > 10


def test_phase2_init_and_load_all_templates(tmp_path: Path) -> None:
    templates = [
        ("us_tech_vol_reversal_v1", WalkForwardConfig),
        ("cross_sectional_xgb_v1", CrossSectionalXGBConfig),
        ("factor_exploration_v1", FactorExplorationConfig),
        ("ashare_rdi_v1", AShareRDIConfig),
    ]

    for tmpl_id, expected_cls in templates:
        target = tmp_path / f"{tmpl_id}.json"
        res = initialize_study(target, template=tmpl_id)
        assert res["status"] == "ready"
        assert res["template"] == tmpl_id

        cfg = load_study_spec(target)
        assert isinstance(cfg, expected_cls)
        assert cfg.study_id == tmpl_id

    # Unknown template rejects cleanly
    with pytest.raises(ResearchStudyError, match="unknown study template"):
        initialize_study(tmp_path / "unknown.json", template="non_existent")


def test_phase2_xgb_study_run_and_inspect(tmp_path: Path) -> None:
    spec_path = tmp_path / "xgb_spec.json"
    initialize_study(spec_path, template="cross_sectional_xgb_v1")

    out_receipt = tmp_path / "receipt_xgb.json"
    res = run_study(spec_path, root=ROOT, output=out_receipt)

    assert res["status"] == "ready"
    assert res["study_id"] == "cross_sectional_xgb_v1"
    assert res["oos_net_return"] is not None
    assert res["benchmark_return"] is not None
    assert res["pit_certified"] is False
    assert res["trade_ready"] is False
    assert out_receipt.exists()

    inspected = inspect_study(out_receipt)
    assert inspected["status"] == "ready"
    assert inspected["study_id"] == "cross_sectional_xgb_v1"
    assert inspected["rank_ic"] is not None
    assert inspected["ic_ir"] is not None
    assert isinstance(inspected["feature_importance"], dict)
    assert len(inspected["feature_importance"]) > 0
    assert inspected["oos_sessions_count"] > 0


def test_phase2_factor_exploration_run_and_inspect(tmp_path: Path) -> None:
    spec_path = tmp_path / "factor_spec.json"
    initialize_study(spec_path, template="factor_exploration_v1")

    out_receipt = tmp_path / "receipt_factor.json"
    res = run_study(spec_path, root=ROOT, output=out_receipt)

    assert res["status"] == "ready"
    assert res["study_id"] == "factor_exploration_v1"
    assert res["pit_certified"] is False
    assert out_receipt.exists()

    inspected = inspect_study(out_receipt)
    assert inspected["status"] == "ready"
    assert inspected["mean_rank_ic"] is not None
    assert inspected["ic_ir"] is not None
    assert "factor_summaries" in inspected
    assert "momentum_20" in inspected["factor_summaries"]
    assert "volatility_20" in inspected["factor_summaries"]
    assert "volume_ratio_20" in inspected["factor_summaries"]
    assert isinstance(inspected["latest_rankings"], dict)
    assert len(inspected["latest_rankings"]) == 4


def test_phase2_ashare_rdi_run_and_inspect(tmp_path: Path) -> None:
    spec_path = tmp_path / "rdi_spec.json"
    initialize_study(spec_path, template="ashare_rdi_v1")

    out_receipt = tmp_path / "receipt_rdi.json"
    res = run_study(spec_path, root=ROOT, output=out_receipt)

    assert res["status"] == "ready"
    assert res["study_id"] == "ashare_rdi_v1"
    assert res["pit_certified"] is False
    assert out_receipt.exists()

    inspected = inspect_study(out_receipt)
    assert inspected["status"] == "ready"
    assert inspected["decision_session"] == "2024-05-10"
    assert inspected["horizons"] == [7, 14, 28]
    assert "7" in inspected["outcomes"]
    assert "14" in inspected["outcomes"]
    assert "28" in inspected["outcomes"]
    assert "forward_return" in inspected["outcomes"]["7"]
    assert "worst_intrahorizon_return" in inspected["outcomes"]["7"]


def test_phase2_fail_closed_missing_rdi_event(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec_path = tmp_path / "rdi_no_event.json"
    initialize_study(spec_path, template="ashare_rdi_v1")

    # Tamper spec to have no event
    data = json.loads(spec_path.read_text(encoding="utf-8"))
    data["event"] = None
    spec_path.write_text(json.dumps(data), encoding="utf-8")

    out_receipt = tmp_path / "receipt_rdi_blocked.json"
    code = main([
        "--root", str(ROOT),
        "research", "study", "run",
        "--spec", str(spec_path),
        "--output", str(out_receipt),
    ])

    payload = json.loads(capsys.readouterr().out)
    assert code == 10
    assert payload["status"] == "blocked"
    assert "blocked_event_pit_coverage" in payload["blocked_reasons"]
    assert out_receipt.exists()


def test_phase2_fail_closed_future_rdi_event_lookahead(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec_path = tmp_path / "rdi_lookahead.json"
    initialize_study(spec_path, template="ashare_rdi_v1")

    # Set event available_at in the future beyond cutoff (2026-09-04)
    data = json.loads(spec_path.read_text(encoding="utf-8"))
    data["event"]["available_at"] = "2026-09-20T08:00:00Z"
    spec_path.write_text(json.dumps(data), encoding="utf-8")

    out_receipt = tmp_path / "receipt_rdi_lookahead.json"
    code = main([
        "--root", str(ROOT),
        "research", "study", "run",
        "--spec", str(spec_path),
        "--output", str(out_receipt),
    ])

    payload = json.loads(capsys.readouterr().out)
    assert code == 10
    assert payload["status"] == "blocked"
    assert "lookahead_event_available_after_cutoff" in payload["blocked_reasons"]
    assert out_receipt.exists()


def test_phase2_fail_closed_xgb_unlisted_symbol(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    spec_path = tmp_path / "xgb_unlisted.json"
    initialize_study(spec_path, template="cross_sectional_xgb_v1")

    # Substitute an unlisted symbol
    data = json.loads(spec_path.read_text(encoding="utf-8"))
    data["symbols"] = ["AAPL", "MSFT", "NONEXISTENT_TICKER"]
    spec_path.write_text(json.dumps(data), encoding="utf-8")

    out_receipt = tmp_path / "receipt_xgb_blocked.json"
    code = main([
        "--root", str(ROOT),
        "research", "study", "run",
        "--spec", str(spec_path),
        "--output", str(out_receipt),
    ])

    payload = json.loads(capsys.readouterr().out)
    assert code == 10
    assert payload["status"] == "blocked"
    assert out_receipt.exists()


def test_phase2_compare_studies_within_and_across_families(tmp_path: Path) -> None:
    # 1. Compare two XGB studies
    xgb_spec1 = tmp_path / "xgb1.json"
    xgb_spec2 = tmp_path / "xgb2.json"
    initialize_study(xgb_spec1, template="cross_sectional_xgb_v1")
    initialize_study(xgb_spec2, template="cross_sectional_xgb_v1")

    # Change hyperparameter in second study
    data2 = json.loads(xgb_spec2.read_text(encoding="utf-8"))
    data2["top_k"] = 2
    data2["xgb_params"]["num_boost_round"] = 15
    xgb_spec2.write_text(json.dumps(data2), encoding="utf-8")

    rec_xgb1 = tmp_path / "rec_xgb1.json"
    rec_xgb2 = tmp_path / "rec_xgb2.json"
    run_study(xgb_spec1, root=ROOT, output=rec_xgb1)
    run_study(xgb_spec2, root=ROOT, output=rec_xgb2)

    comp_xgb = compare_studies(rec_xgb1, rec_xgb2)
    assert comp_xgb["status"] == "comparable"
    assert comp_xgb["study_id"] == "cross_sectional_xgb_v1"
    assert "overall_oos_net_return" in comp_xgb["right_minus_left"]
    assert "rank_ic" in comp_xgb["right_minus_left"]

    # 2. Compare across different families should raise ResearchStudyError
    rec_factor = tmp_path / "rec_factor.json"
    factor_spec = tmp_path / "factor.json"
    initialize_study(factor_spec, template="factor_exploration_v1")
    run_study(factor_spec, root=ROOT, output=rec_factor)

    with pytest.raises(ResearchStudyError, match="cannot compare different study families"):
        compare_studies(rec_xgb1, rec_factor)


def test_phase2_cli_init_with_template_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    target = tmp_path / "my_factor_study.json"
    code = main([
        "--root", str(ROOT),
        "research", "study", "init",
        "--template", "factor_exploration_v1",
        "--output", str(target),
    ])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ready"
    assert payload["template"] == "factor_exploration_v1"

    saved = json.loads(target.read_text(encoding="utf-8"))
    assert saved["study_id"] == "factor_exploration_v1"
    assert "momentum_20" in saved["factors"]
