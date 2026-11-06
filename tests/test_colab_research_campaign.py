"""Multi-family compiler keeps holdout, source, task and selection boundaries."""
import copy
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.research.cloud_exchange import ExchangeError
from src.research.colab_experiment_batch import plan, execute
from src.research.colab_research_campaign import comparison_report


def spec():
    root = Path(__file__).resolve().parents[1]
    value = json.loads((root / "docs/product/examples/p2_e2_colab_us87_model_search.example.json").read_text())
    value["runner_git_sha"] = "1" * 40
    return value


def test_reproducible_search_keeps_all_declared_models_and_heldout_prices_out():
    result = plan(spec())
    assert result == plan(spec())
    assert result["configuration_count"] == 29 and result["trial_count"] == 261
    assert {c["model_family"] for c in result["configurations"]} == {"xgboost", "lightgbm", "momentum_20d"}
    assert len({t["trial_id"] for t in result["trials"]}) == 261
    assert all(t["study"]["test_end"] < "2026-07-01" for t in result["trials"])
    assert not result["holdout_evaluated"]
    assert {t["seed"] for t in result["trials"]} == {17, 42, 123}


@pytest.mark.parametrize("kind", ["holdout", "embargo", "feature", "configuration", "task_budget", "family"])
def test_invalid_campaign_refuses_before_model_execution(kind):
    value = spec()
    if kind == "holdout":
        value["final_holdout"]["start_date"] = "2026-06-01"
    elif kind == "embargo":
        value["validation_folds"][0]["train_end"] = "2025-12-31"
    elif kind == "feature":
        value["feature_sets"]["full"].append("US_ALPHA158_SYNTHETIC_VWAP")
    elif kind == "configuration":
        value["optimization"]["max_configurations"] = 20
    elif kind == "task_budget":
        value["max_trials"] = 260
    else:
        value["candidates"][1]["model_family"] = "unregistered_neural_model"
    with patch("src.research.study_workspace.run_study", side_effect=AssertionError), pytest.raises(ExchangeError):
        plan(value)


def test_seed_changes_only_predeclared_search_and_cannot_reuse_run_identity():
    first = plan(spec())
    second_spec = spec()
    second_spec["optimization"]["seed"] += 1
    second = plan(second_spec)
    assert first["run_id"] != second["run_id"]
    assert first["configurations"] != second["configurations"]
    assert first["final_holdout"] == second["final_holdout"]


def test_incomplete_configs_cannot_enter_validation_ranking(tmp_path):
    value = spec()
    value["validation_folds"] = value["validation_folds"][:2]
    value["seeds"] = [17, 42]
    value["candidates"] = copy.deepcopy(value["candidates"][:2])
    value["candidates"][1]["configuration_budget"] = 1
    data = tmp_path / "data"
    pool = data / "configs/research_universes/us_selected_equities_v2.yaml"
    pool.parent.mkdir(parents=True)
    pool.write_text("symbols:\n" + "".join(f"  - S{i:03}\n" for i in range(87)))
    batch_file = tmp_path / "batch.json"
    batch_file.write_text(json.dumps(value))
    outputs = tmp_path / "outputs"

    def fake_run(path, root, output):
        raw = {"status": "ready", "research_only": True, "trade_ready": False, "pit_certified": False,
            "git_commit": "1" * 40, "experiment_receipt": json.loads(path.read_text()),
            "overall_oos_net_excess_return": 0.01, "overall_oos_max_drawdown": -0.02, "rank_ic": 0.03}
        raw["study_hash"] = hashlib.sha256(json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        output.write_text(json.dumps(raw))
        return {"status": "ready"}

    with patch("src.research.colab_experiment_batch.verify_stage", return_value={
        "bundle_manifest_sha256": value["v5_bundle_manifest_sha256"], "history_archive_sha256": value["history_archive_sha256"]}), patch(
        "src.research.colab_research_campaign._common_history", return_value={"common_sessions": 292}), patch(
        "src.research.colab_experiment_batch._git_head", return_value="1" * 40), patch(
        "src.research.study_workspace.run_study", side_effect=fake_run):
        # This test exercises result coverage, not the separately audited real
        # common-history parser; avoid inventing fake 87-symbol source prices.
        execute(batch_spec=batch_file, data_root=data, output_root=outputs, max_new_trials=1)
        report = comparison_report(batch_file, data, outputs)
        assert report["validation_ranking"] == []
        assert not any(c["complete"] for c in report["configurations"])
        execute(batch_spec=batch_file, data_root=data, output_root=outputs, max_new_trials=7, resume=True)
        report = comparison_report(batch_file, data, outputs)
        assert len(report["validation_ranking"]) == 1
        assert not report["model_promoted"] and not report["holdout_evaluated"]
