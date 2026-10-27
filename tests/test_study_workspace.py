"""CLI-level product journey for the single-operator Investment Research Workspace."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.cli.main import main
from src.research.study_workspace import (
    ResearchStudyError,
    compare_studies,
    initialize_study,
    load_study_spec,
    run_study,
    save_receipt_exclusive,
    study_catalog,
)


def _receipt(*, key: str = "a" * 64, net: float = 0.1, status: str = "ready") -> dict:
    return {
        "study_hash": key,
        "status": status,
        "research_only": True,
        "trade_ready": False,
        "study_id": "us_tech_vol_reversal_v1",
        "experiment_receipt": {
            "study_id": "us_tech_vol_reversal_v1",
            "market": "us",
            "pool_id": "us_selected_equities_v2",
            "symbols": ["AAPL", "MSFT"],
            "benchmark": "QQQ",
            "price_mode": "anchored_adjusted",
            "folds": [{"fold_id": "fold1", "test_start": "2025-01-02"}],
            "cost_bps": 3.0,
        },
        "code_source_sha256": {"pipeline": "b" * 64},
        "folds": [{"fold_id": "fold1", "train_data_hash": "c" * 64,
                   "test_data_hash": "d" * 64}],
        "overall_oos_net_return": net,
        "overall_benchmark_cumulative_return": 0.08,
        "overall_oos_net_excess_return": net - 0.08,
        "overall_oos_sharpe_ratio": 0.9,
        "overall_oos_max_drawdown": -0.1,
        "blocked_reasons": [],
        "generated_at_utc": "2026-10-27T09:00:00Z",
    }


def test_study_catalog_and_editable_spec_are_one_entry(tmp_path: Path) -> None:
    entries = study_catalog()
    assert len(entries["studies"]) == 1
    assert entries["studies"][0]["engine"] == "walkforward_volatility_reversal"
    target = tmp_path / "hypothesis.json"
    assert initialize_study(target)["status"] == "ready"
    cfg = load_study_spec(target)
    assert cfg.study_id == "us_tech_vol_reversal_v1"
    assert len(cfg.folds) == 3
    with pytest.raises(ResearchStudyError, match="already exists"):
        initialize_study(target)


def test_study_spec_refuses_other_engines_duplicate_symbols_and_overlapping_folds(tmp_path: Path) -> None:
    target = tmp_path / "study.json"
    initialize_study(target)
    obj = json.loads(target.read_text())
    obj["study_id"] = "unimplemented_family"
    target.write_text(json.dumps(obj))
    with pytest.raises(ResearchStudyError, match="unsupported study evaluator"):
        load_study_spec(target)
    obj["study_id"] = "us_tech_vol_reversal_v1"
    obj["symbols"] = ["AAPL", "AAPL"]
    target.write_text(json.dumps(obj))
    with pytest.raises(ResearchStudyError, match="unique"):
        load_study_spec(target)
    obj["symbols"] = ["AAPL", "MSFT"]
    obj["folds"][1]["test_start"] = obj["folds"][0]["test_start"]
    target.write_text(json.dumps(obj))
    with pytest.raises(ResearchStudyError, match="overlap"):
        load_study_spec(target)


def test_study_run_persists_single_research_receipt_without_refetching(tmp_path: Path) -> None:
    out = tmp_path / "frozen.json"
    result = _receipt()
    with patch("src.research.walkforward.pipeline.run_walkforward_study",
               return_value=SimpleNamespace(to_dict=lambda: result)) as mock_run:
        first = run_study(None, tmp_path, output=out)
    assert mock_run.call_count == 1
    assert first["status"] == "ready"
    assert first["receipt_path"] == str(out)
    assert first["oos_net_return"] == pytest.approx(0.1)
    assert first["pit_certified"] is False
    assert json.loads(out.read_text())["study_hash"] == result["study_hash"]
    # The second run has identical economics but a later wall-clock timestamp.
    later = {**result, "generated_at_utc": "2026-10-27T12:00:00Z"}
    with patch("src.research.walkforward.pipeline.run_walkforward_study",
               return_value=SimpleNamespace(to_dict=lambda: later)):
        run_study(None, tmp_path, output=out)
    assert json.loads(out.read_text())["generated_at_utc"] == "2026-10-27T09:00:00Z"
    # Distinct evidence can never replace the first sealed result.
    with pytest.raises(ResearchStudyError, match="overwrite"):
        save_receipt_exclusive(out, {**result, "overall_oos_net_return": 0.9})


def test_blocked_study_receipt_is_retained_and_cli_returns_10(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    blocked = {**_receipt(), "status": "blocked", "blocked_reasons": ["bad_data"],
               "overall_oos_net_return": 0.0}
    path = tmp_path / "blocked.json"
    with patch("src.research.walkforward.pipeline.run_walkforward_study",
               return_value=SimpleNamespace(to_dict=lambda: blocked)):
        code = main(["--root", str(tmp_path), "research", "study", "run", "--output", str(path)])
    payload = json.loads(capsys.readouterr().out)
    assert code == 10
    assert payload["status"] == "blocked"
    assert payload["oos_net_return"] is None
    assert path.exists()


def test_compare_is_descriptive_and_refuses_different_sources(tmp_path: Path) -> None:
    left, right = tmp_path / "left.json", tmp_path / "right.json"
    left.write_text(json.dumps(_receipt()))
    right.write_text(json.dumps(_receipt(key="b" * 64, net=0.14)))
    comparison = compare_studies(left, right)
    assert comparison["status"] == "comparable"
    assert comparison["right_minus_left"]["overall_oos_net_return"] == pytest.approx(0.04)
    assert comparison["trade_ready"] is False
    altered = _receipt(key="b" * 64, net=0.14)
    altered["folds"][0]["test_data_hash"] = "e" * 64
    right.write_text(json.dumps(altered))
    with pytest.raises(ResearchStudyError, match="non-comparable source"):
        compare_studies(left, right)


def test_compare_rejects_different_universe_or_incomplete_study(tmp_path: Path) -> None:
    left, right = tmp_path / "a.json", tmp_path / "b.json"
    left.write_text(json.dumps(_receipt()))
    mismatched = _receipt()
    mismatched["experiment_receipt"]["symbols"] = ["AAPL", "META"]
    right.write_text(json.dumps(mismatched))
    with pytest.raises(ResearchStudyError, match="non-comparable study definitions"):
        compare_studies(left, right)
    blocked = _receipt(status="blocked")
    right.write_text(json.dumps(blocked))
    with pytest.raises(ResearchStudyError, match="must be ready"):
        compare_studies(left, right)


def test_cli_study_journey_list_init_compare(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--root", str(tmp_path), "research", "study", "list"]) == 0
    assert json.loads(capsys.readouterr().out)["studies"][0]["id"] == "us_tech_vol_reversal_v1"
    spec = tmp_path / "new_study.json"
    assert main(["--root", str(tmp_path), "research", "study", "init", "--output", str(spec)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "ready"
    left, right = tmp_path / "left.json", tmp_path / "right.json"
    left.write_text(json.dumps(_receipt()))
    right.write_text(json.dumps(_receipt(key="d" * 64, net=0.2)))
    assert main(["--root", str(tmp_path), "research", "study", "compare",
                 str(left), str(right)]) == 0
    assert json.loads(capsys.readouterr().out)["right_minus_left"]["overall_oos_net_return"] == pytest.approx(0.1)
