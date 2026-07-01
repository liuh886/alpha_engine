"""Tests for scripts/generate_release_candidate.py.

All tests use temporary directories so they never write to production
artifact paths.  Since real Qlib data is not available in CI or in a
fresh checkout, the tests verify failure-report behaviour and manifest
structure rather than successful pipeline execution.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helper: import the module once (avoid repeated sys.path setup)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gen_module():
    """Import generate_release_candidate once per module."""
    from scripts import generate_release_candidate as _gen

    return _gen


@pytest.fixture
def minimal_config_dict() -> dict[str, Any]:
    """Return a minimal workflow config dict for testing."""
    return {
        "qlib_init": {
            "provider_uri": "data/watchlist",
            "region": "us",
        },
        "market": "us",
        "start_time": "2018-01-01",
        "end_time": "2024-12-31",
        "fit_start_time": "2018-01-01",
        "fit_end_time": "2023-12-31",
        "task": {
            "model": {
                "class": "LGBMRegressor",
                "module_path": "lightgbm",
                "kwargs": {"objective": "regression", "n_estimators": 100},
            },
            "dataset": {
                "class": "DatasetH",
                "module_path": "qlib.data.dataset",
                "kwargs": {
                    "handler": {
                        "class": "Alpha158",
                        "module_path": "qlib.contrib.data.handler",
                        "kwargs": {
                            "start_time": "2018-01-01",
                            "end_time": "2024-12-31",
                            "fit_start_time": "2018-01-01",
                            "fit_end_time": "2023-12-31",
                            "infer_processors": [
                                {
                                    "class": "RobustZScoreNorm",
                                    "kwargs": {"fields_group": "feature", "clip_outlier": True},
                                },
                                {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
                            ],
                            "learn_processors": [
                                {"class": "DropnaLabel"},
                                {"class": "CSRankNorm", "kwargs": {"fields_group": "label"}},
                            ],
                            "label": ["Ref($close, -10) / $close - 1"],
                        },
                    },
                    "segments": {
                        "train": ["2018-01-01", "2023-12-31"],
                        "valid": ["2024-01-01", "2024-06-30"],
                        "test": ["2024-07-01", "2024-12-31"],
                    },
                },
            },
        },
    }


@pytest.fixture
def tmp_with_config(tmp_path: Path, minimal_config_dict: dict[str, Any]) -> Path:
    """Create a tmp_path with a minimal config file."""
    import yaml

    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "us_lgbm_regressor_10d_workflow.yaml").write_text(
        yaml.dump(minimal_config_dict, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Failure-report tests
# ---------------------------------------------------------------------------


def test_failure_report_when_not_in_git_repo(
    tmp_with_config: Path, gen_module: Any
) -> None:
    """When tmp_path is not a git repository, identity stage fails and a
    failure report is written."""
    result, code = gen_module.generate_release_candidate(
        candidate="v0.1.0-rc1",
        market="us",
        project_root=tmp_with_config,
    )

    assert code == 1
    assert result.get("status") == "fail"

    report_path = (
        tmp_with_config
        / "artifacts"
        / "release_candidate"
        / "v0.1.0-rc1"
        / "release_failure_report.json"
    )
    assert report_path.is_file(), f"Failure report not found at {report_path}"

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["candidate"] == "v0.1.0-rc1"
    assert report["market"] == "us"
    assert report["stage_failed"] == "identity"
    assert report["error_type"] == "GitRevisionUnavailable"
    assert isinstance(report["timestamp"], str)
    assert isinstance(report["missing_files"], list)
    assert isinstance(report["suggested_fix"], str)


def test_failure_report_when_missing_uv_lock(
    tmp_with_config: Path, gen_module: Any
) -> None:
    """When uv.lock is missing, identity stage fails."""
    _init_git_repo(tmp_with_config)
    # Ensure uv.lock does NOT exist
    lock = tmp_with_config / "uv.lock"
    if lock.exists():
        lock.unlink()

    result, code = gen_module.generate_release_candidate(
        candidate="v0.1.0-rc1",
        market="us",
        project_root=tmp_with_config,
    )

    assert code == 1
    report_path = (
        tmp_with_config
        / "artifacts"
        / "release_candidate"
        / "v0.1.0-rc1"
        / "release_failure_report.json"
    )
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["stage_failed"] == "identity"
    assert report["error_type"] == "LockfileMissing"
    assert "uv.lock" in report["error_message"]


def test_unrecognised_market_fails(gen_module: Any) -> None:
    """An unsupported market returns exit code 1 without writing a failure
    report."""
    result, code = gen_module.generate_release_candidate(
        candidate="v0.1.0-rc1",
        market="hk",
        project_root=Path("/nonexistent"),
    )
    assert code == 1
    assert "error" in result
    assert "hk" in result["error"]


def test_failure_report_has_required_schema(
    tmp_with_config: Path, gen_module: Any
) -> None:
    """The failure report JSON includes all required fields."""
    result, code = gen_module.generate_release_candidate(
        candidate="v0.1.0-rc1",
        market="us",
        project_root=tmp_with_config,
    )
    assert code == 1

    report_path = (
        tmp_with_config
        / "artifacts"
        / "release_candidate"
        / "v0.1.0-rc1"
        / "release_failure_report.json"
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    required_fields = {
        "candidate",
        "market",
        "stage_failed",
        "error_type",
        "error_message",
        "missing_files",
        "suggested_fix",
        "timestamp",
    }
    assert required_fields.issubset(set(report)), (
        f"Missing fields: {required_fields - set(report)}"
    )


# ---------------------------------------------------------------------------
# BacktestResult turnover/costs tests
# ---------------------------------------------------------------------------


def test_backtest_result_has_turnover_costs(gen_module: Any) -> None:
    """BacktestResult now exposes turnover, costs, net_return, and
    information_ratio fields with defaults."""
    from src.research.vectorized_backtest import BacktestResult

    br = BacktestResult(
        total_return=0.1,
        benchmark_return=0.02,
        excess_return=0.08,
        max_drawdown=-0.05,
        sharpe_ratio=1.0,
        annual_return=0.12,
        volatility=0.1,
        mean_ic=0.05,
        ic_ir=0.4,
        positive_ic_ratio=0.6,
    )
    d = br.to_dict()

    assert "turnover" in d
    assert "costs" in d
    assert "net_return" in d
    assert "information_ratio" in d
    # Defaults are zero (not fabricated)
    assert d["turnover"] == 0.0
    assert d["costs"] == 0.0
    assert d["net_return"] == br.total_return  # net == total when costs already subtracted
    assert d["information_ratio"] == 0.0


# ---------------------------------------------------------------------------
# _build_artifacts signature tests
# ---------------------------------------------------------------------------


def test_build_artifacts_rejects_frontend_evidence(gen_module: Any) -> None:
    """_build_artifacts must NOT accept a frontend_evidence parameter."""
    import inspect

    sig = inspect.signature(gen_module._build_artifacts)
    params = list(sig.parameters.keys())
    assert "frontend_evidence" not in params, (
        f"_build_artifacts must not accept frontend_evidence. Got params: {params}"
    )


def test_manifest_structure_with_fixture_git_repo(
    tmp_path: Path, gen_module: Any
) -> None:
    """With a git repo and uv.lock, but no Qlib data, the script produces a
    failure report at the qlib_init stage (not identity)."""
    _init_git_repo(tmp_path)
    _write_file(tmp_path / "uv.lock", b"fixture-lock-content\n")

    # Create a minimal config so config loading doesn't fail
    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    config = _minimal_config()
    (config_dir / "us_lgbm_regressor_10d_workflow.yaml").write_text(
        _dict_to_yaml(config), encoding="utf-8"
    )

    result, code = gen_module.generate_release_candidate(
        candidate="v0.1.0-rc1",
        market="us",
        project_root=tmp_path,
    )

    # Should fail at qlib_init because no Qlib data exists
    assert code == 1

    report_path = (
        tmp_path
        / "artifacts"
        / "release_candidate"
        / "v0.1.0-rc1"
        / "release_failure_report.json"
    )
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["stage_failed"] in ("qlib_init", "snapshot_discovery", "load_config")
    assert isinstance(report["missing_files"], list)


# ---------------------------------------------------------------------------
# Snapshot discovery tests
# ---------------------------------------------------------------------------


def test_snapshot_discovery_fails_when_no_latest(
    tmp_path: Path, gen_module: Any
) -> None:
    """Without a published latest snapshot, _find_data_snapshot raises
    StageFailure with stage='snapshot_discovery'."""
    import unittest.mock as mock

    _init_git_repo(tmp_path)
    _write_file(tmp_path / "uv.lock", b"fixture-lock\n")

    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "us_lgbm_regressor_10d_workflow.yaml").write_text(
        _dict_to_yaml(_minimal_config()), encoding="utf-8"
    )

    # Mock qlib_init to succeed so we reach snapshot_discovery
    with mock.patch.object(gen_module, "_stage_qlib_init", return_value=None):
        result, code = gen_module.generate_release_candidate(
            candidate="v0.1.0-rc1",
            market="us",
            project_root=tmp_path,
        )

    # Should fail at snapshot_discovery stage
    assert code == 1

    report_path = (
        tmp_path
        / "artifacts"
        / "release_candidate"
        / "v0.1.0-rc1"
        / "release_failure_report.json"
    )
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["stage_failed"] == "snapshot_discovery"
    assert report["error_type"] == "NoValidSnapshot"


def test_snapshot_discovery_uses_project_local_canonical_store(
    tmp_path: Path, gen_module: Any
) -> None:
    """Snapshot discovery resolves a verified manifest below project_root."""
    from src.data.snapshot import DataSnapshot

    provider = tmp_path / "provider"
    _write_file(provider / "calendars" / "day.txt", b"2024-01-02\n")
    store = tmp_path / "artifacts" / "snapshots"
    snapshot = DataSnapshot.create_snapshot(
        provider,
        store=store,
        source_adapter="test",
        universe="us",
        date_range={"start": "2024-01-01", "end": "2024-12-31"},
        quality_verdict="pass",
    )
    DataSnapshot.publish_snapshot(snapshot.snapshot_id, store=store)

    reference = gen_module._find_data_snapshot(tmp_path, "us")

    assert reference["id"] == snapshot.snapshot_id
    manifest = tmp_path / reference["manifest"]
    assert manifest.is_file()
    assert reference["sha256"] == gen_module._sha256(manifest)


def test_snapshot_discovery_rejects_empty_date_range(
    tmp_path: Path, gen_module: Any
) -> None:
    """A published snapshot with empty date_range is rejected by _find_data_snapshot."""
    from src.data.snapshot import DataSnapshot

    provider = tmp_path / "provider"
    _write_file(provider / "calendars" / "day.txt", b"2024-01-02\n")
    store = tmp_path / "artifacts" / "snapshots"
    # No date_range → manifest has date_range={}
    snapshot = DataSnapshot.create_snapshot(
        provider,
        store=store,
        source_adapter="test",
        universe="us",
        quality_verdict="pass",
    )
    DataSnapshot.publish_snapshot(snapshot.snapshot_id, store=store)

    with pytest.raises(gen_module.StageFailure) as exc_info:
        gen_module._find_data_snapshot(tmp_path, "us")

    assert exc_info.value.error_type == "SnapshotMissingDateRange"
    assert exc_info.value.stage == "snapshot_discovery"


# ---------------------------------------------------------------------------
# Spread computation tests
# ---------------------------------------------------------------------------


def test_spread_computation_raises_on_empty_data(gen_module: Any) -> None:
    """_compute_spread_evidence raises StageFailure when predictions are empty
    (bottom backtest fails)."""
    from src.research.vectorized_backtest import BacktestResult

    bt_top = BacktestResult(
        total_return=0.1,
        benchmark_return=0.0,
        excess_return=0.1,
        max_drawdown=-0.05,
        sharpe_ratio=1.0,
        annual_return=0.15,
        volatility=0.1,
        mean_ic=0.05,
        ic_ir=0.5,
        positive_ic_ratio=0.6,
        n_periods=3,
    )
    empty_pred = pd.DataFrame()
    empty_labels = pd.DataFrame()

    with pytest.raises(gen_module.StageFailure) as exc_info:
        gen_module._compute_spread_evidence(
            bt_top, empty_pred, empty_labels, topk=5, rebalance_days=5, cost_bps=20
        )
    assert exc_info.value.error_type == "SpreadComputationFailed"


# ---------------------------------------------------------------------------
# Direct validation tests
# ---------------------------------------------------------------------------


def test_empty_predictions_rejected(gen_module: Any) -> None:
    """_validate_predictions_labels rejects empty predictions."""
    empty_pred = pd.DataFrame()
    labels = pd.DataFrame({"return": [0.1]})
    with pytest.raises(gen_module.StageFailure) as exc_info:
        gen_module._validate_predictions_labels(empty_pred, labels, "train")
    assert exc_info.value.error_type == "EmptyPredictions"


def test_empty_labels_rejected(gen_module: Any) -> None:
    """_validate_predictions_labels rejects empty labels."""
    pred = pd.DataFrame({"score": [0.2]})
    empty_labels = pd.DataFrame()
    with pytest.raises(gen_module.StageFailure) as exc_info:
        gen_module._validate_predictions_labels(pred, empty_labels, "train")
    assert exc_info.value.error_type == "EmptyLabels"


def test_misaligned_predictions_labels_rejected(gen_module: Any) -> None:
    """_validate_predictions_labels rejects misaligned indices."""
    index_a = pd.MultiIndex.from_tuples(
        [("2024-01-01", "AAPL")], names=["datetime", "instrument"]
    )
    index_b = pd.MultiIndex.from_tuples(
        [("2024-01-02", "MSFT")], names=["datetime", "instrument"]
    )
    pred = pd.DataFrame({"score": [0.2]}, index=index_a)
    labels = pd.DataFrame({"return": [0.1]}, index=index_b)
    with pytest.raises(gen_module.StageFailure) as exc_info:
        gen_module._validate_predictions_labels(pred, labels, "train")
    assert exc_info.value.error_type == "MisalignedData"


def test_non_finite_predictions_rejected(gen_module: Any) -> None:
    """_validate_predictions_labels rejects predictions with NaN/Inf."""
    idx = pd.MultiIndex.from_tuples(
        [("2024-01-01", "AAPL")], names=["datetime", "instrument"]
    )
    pred = pd.DataFrame({"score": [float("nan")]}, index=idx)
    labels = pd.DataFrame({"return": [0.1]}, index=idx)
    with pytest.raises(gen_module.StageFailure) as exc_info:
        gen_module._validate_predictions_labels(pred, labels, "train")
    assert "NonFinite" in exc_info.value.error_type


def test_valid_predictions_labels_accepted(gen_module: Any) -> None:
    """_validate_predictions_labels accepts valid data."""
    idx = pd.MultiIndex.from_tuples(
        [("2024-01-01", "AAPL"), ("2024-01-01", "MSFT")],
        names=["datetime", "instrument"],
    )
    pred = pd.DataFrame({"score": [0.2, 0.3]}, index=idx)
    labels = pd.DataFrame({"return": [0.1, 0.05]}, index=idx)
    # Should not raise
    gen_module._validate_predictions_labels(pred, labels, "train")


# ---------------------------------------------------------------------------
# Backtest failure test
# ---------------------------------------------------------------------------


def test_backtest_failure_cannot_produce_manifest(
    tmp_path: Path, gen_module: Any
) -> None:
    """When the backtest stage raises, a failure report is written and no
    manifest is produced."""
    _init_git_repo(tmp_path)
    _write_file(tmp_path / "uv.lock", b"fixture-lock\n")
    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "us_lgbm_regressor_10d_workflow.yaml").write_text(
        _dict_to_yaml(_minimal_config()), encoding="utf-8"
    )

    # Mock Qlib-dependent stages to succeed, then make backtest fail
    import unittest.mock as mock

    wf_meta = {
        "mean_ic": 0.05,
        "ic_ir": 0.45,
        "consistency_score": 0.6,
        "n_success": 12,
        "n_failed": 0,
        "n_skipped": 0,
        "n_splits": 3,
        "splits": [
            {
                "split_id": 0,
                "train_start": "2018-01-01",
                "train_end": "2020-12-31",
                "test_start": "2021-01-01",
                "test_end": "2021-06-30",
                "ic": 0.05,
                "rank_ic": 0.04,
                "status": "success",
            }
        ],
    }

    idx = pd.MultiIndex.from_tuples(
        [("2024-07-01", "AAPL"), ("2024-07-01", "MSFT")],
        names=["datetime", "instrument"],
    )
    pred_df = pd.DataFrame({"score": [0.2, 0.3]}, index=idx)
    labels_df = pd.DataFrame({"return": [0.1, 0.05]}, index=idx)

    snapshot_ref = {
        "id": "test-snapshot-id",
        "manifest": "artifacts/snapshots/test/manifest.json",
        "sha256": "a" * 64,
    }

    with (
        mock.patch.object(gen_module, "_stage_qlib_init", return_value=None),
        mock.patch.object(gen_module, "_find_data_snapshot", return_value=snapshot_ref),
        mock.patch.object(gen_module, "_stage_walk_forward", return_value=wf_meta),
        mock.patch.object(gen_module, "_stage_train", return_value=(object(), pred_df, labels_df)),
        mock.patch.object(
            gen_module,
            "_stage_backtest",
            side_effect=gen_module.StageFailure(
                stage="backtest",
                error_type="BacktestError",
                message="Simulated backtest failure",
                suggested_fix="Check data",
            ),
        ),
    ):
        result, code = gen_module.generate_release_candidate(
            candidate="v0.1.0-rc1",
            market="us",
            project_root=tmp_path,
        )

    assert code == 1
    assert result.get("status") == "fail"

    # Verify failure report was written
    report_path = (
        tmp_path
        / "artifacts"
        / "release_candidate"
        / "v0.1.0-rc1"
        / "release_failure_report.json"
    )
    assert report_path.is_file()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["stage_failed"] == "backtest"
    assert report["error_type"] == "BacktestError"

    # Verify no success manifest was produced
    manifest_path = (
        tmp_path
        / "artifacts"
        / "release_candidate"
        / "v0.1.0-rc1"
        / "release_manifest.json"
    )
    assert not manifest_path.is_file(), "Success manifest should not exist after backtest failure"


# ---------------------------------------------------------------------------
# Metrics imports from canonical source
# ---------------------------------------------------------------------------


def test_metrics_imported_from_canonical_source(gen_module: Any) -> None:
    """REQUIRED_RELEASE_METRICS must be the canonical tuple, not redefined."""
    from src.release.candidate import REQUIRED_RELEASE_METRICS as CANONICAL

    assert gen_module.REQUIRED_RELEASE_METRICS is CANONICAL, (
        "Generator must import REQUIRED_RELEASE_METRICS from src.release.candidate, "
        "not redefine it"
    )


def test_policy_imported_from_canonical_source(gen_module: Any) -> None:
    """POLICY must be the canonical dict, not redefined."""
    from src.release.candidate import POLICY as CANONICAL_POLICY

    assert gen_module.POLICY is CANONICAL_POLICY, (
        "Generator must import POLICY from src.release.candidate, "
        "not redefine it"
    )


def test_stale_failure_report_removed_on_success(
    tmp_path: Path, gen_module: Any
) -> None:
    """A stale release_failure_report.json from a prior failed run is
    removed when generation succeeds."""
    import unittest.mock as mock

    _init_git_repo(tmp_path)
    _write_file(tmp_path / "uv.lock", b"fixture-lock\n")
    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "us_lgbm_regressor_10d_workflow.yaml").write_text(
        _dict_to_yaml(_minimal_config()), encoding="utf-8"
    )

    wf_meta = {
        "mean_ic": 0.05,
        "ic_ir": 0.45,
        "consistency_score": 0.6,
        "n_success": 12,
        "n_failed": 0,
        "n_skipped": 0,
        "n_splits": 3,
        "splits": [
            {
                "split_id": 0,
                "train_start": "2018-01-01",
                "train_end": "2020-12-31",
                "test_start": "2021-01-01",
                "test_end": "2021-06-30",
                "ic": 0.05,
                "rank_ic": 0.04,
                "status": "success",
            }
        ],
    }

    idx = pd.MultiIndex.from_tuples(
        [("2024-07-01", "AAPL"), ("2024-07-01", "MSFT")],
        names=["datetime", "instrument"],
    )
    pred_df = pd.DataFrame({"score": [0.2, 0.3]}, index=idx)
    labels_df = pd.DataFrame({"return": [0.1, 0.05]}, index=idx)

    snapshot_ref = {
        "id": "test-snapshot-id",
        "manifest": "artifacts/snapshots/test/manifest.json",
        "sha256": "a" * 64,
    }

    bt_metrics = {
        "metrics": {
            "annualized_return": 0.15,
            "total_return": 0.30,
            "sharpe": 1.5,
            "max_drawdown": -0.1,
            "mean_ic": 0.05,
            "ic_ir": 0.4,
            "positive_ic_ratio": 0.6,
            "top_bottom_spread": 0.25,
        },
        "raw": {},
        "spread": {"status": "ok", "total_spread": 0.25},
    }

    # Create a stale failure report from a prior run
    stale_dir = tmp_path / "artifacts" / "release_candidate" / "v0.1.0-rc1"
    stale_dir.mkdir(parents=True, exist_ok=True)
    stale_report = stale_dir / "release_failure_report.json"
    stale_report.write_text(json.dumps({"stale": True}), encoding="utf-8")
    assert stale_report.is_file(), "Precondition: stale failure report must exist"

    with (
        mock.patch.object(gen_module, "_stage_qlib_init", return_value=None),
        mock.patch.object(gen_module, "_find_data_snapshot", return_value=snapshot_ref),
        mock.patch.object(gen_module, "_stage_walk_forward", return_value=wf_meta),
        mock.patch.object(gen_module, "_stage_train", return_value=(object(), pred_df, labels_df)),
        mock.patch.object(gen_module, "_stage_backtest", return_value=bt_metrics),
        mock.patch.object(
            gen_module,
            "_load_frontend_evidence",
            return_value={"id": "test", "path": "test.json", "sha256": "a" * 64},
        ),
    ):
        result, code = gen_module.generate_release_candidate(
            candidate="v0.1.0-rc1",
            market="us",
            project_root=tmp_path,
        )

    assert code == 0, f"Expected success exit code, got {code}: {result}"
    assert result.get("status") == "pass"
    # Stale failure report must be removed on success
    assert not stale_report.is_file(), (
        "Stale failure report should have been removed on successful generation"
    )
    # Success manifest must exist
    manifest_path = (
        tmp_path
        / "artifacts"
        / "release_candidate"
        / "v0.1.0-rc1"
        / "release_manifest.json"
    )
    assert manifest_path.is_file(), "Release manifest should exist on success"


def test_frontend_build_generates_current_revision_evidence(
    tmp_path: Path, gen_module: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without an external evidence path, generation runs and records a real build."""
    from types import SimpleNamespace

    _write_file(tmp_path / "qlib-dashboard" / "package.json", b"{}\n")
    _write_file(tmp_path / "qlib-dashboard" / "dist" / "index.html", b"built\n")
    monkeypatch.setattr(gen_module.shutil, "which", lambda _name: "npm.cmd")
    monkeypatch.setattr(
        gen_module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="built", stderr=""),
    )

    reference = gen_module._load_frontend_evidence(
        None, "v0.1.0-rc1", "a" * 40, tmp_path
    )

    evidence_path = tmp_path / reference["path"]
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert payload["status"] == "pass"
    assert payload["candidate"] == "v0.1.0-rc1"
    assert payload["code_revision"] == "a" * 40
    assert payload["dist_file_count"] == 1


def test_us_workflow_binds_alpha158_to_us_universe() -> None:
    """The US release workflow must not fall back to Alpha158's CSI500 default."""
    import yaml

    config_path = Path(__file__).parents[1] / "configs" / "us_lgbm_regressor_10d_workflow.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    handler_kwargs = config["task"]["dataset"]["kwargs"]["handler"]["kwargs"]

    assert config["market"] == "us"
    assert handler_kwargs["instruments"] == "us"
    assert config["start_time"] == "2021-04-05"
    assert config["fit_start_time"] == "2021-04-05"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _init_git_repo(path: Path) -> None:
    """Initialise a minimal git repository at *path*."""
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Alpha Engine Tests"], cwd=path, check=True)
    marker = path / ".test-revision"
    marker.write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", marker.name], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "test fixture"], cwd=path, check=True)


def _write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _minimal_config() -> dict[str, Any]:
    """Return a minimal workflow config for testing."""
    return {
        "qlib_init": {
            "provider_uri": "data/watchlist",
            "region": "us",
        },
        "market": "us",
        "start_time": "2018-01-01",
        "end_time": "2024-12-31",
        "fit_start_time": "2018-01-01",
        "fit_end_time": "2023-12-31",
        "task": {
            "model": {
                "class": "LGBMRegressor",
                "module_path": "lightgbm",
                "kwargs": {"objective": "regression", "n_estimators": 100},
            },
            "dataset": {
                "class": "DatasetH",
                "module_path": "qlib.data.dataset",
                "kwargs": {
                    "handler": {
                        "class": "Alpha158",
                        "module_path": "qlib.contrib.data.handler",
                        "kwargs": {
                            "start_time": "2018-01-01",
                            "end_time": "2024-12-31",
                            "fit_start_time": "2018-01-01",
                            "fit_end_time": "2023-12-31",
                            "infer_processors": [
                                {
                                    "class": "RobustZScoreNorm",
                                    "kwargs": {"fields_group": "feature", "clip_outlier": True},
                                },
                                {"class": "Fillna", "kwargs": {"fields_group": "feature"}},
                            ],
                            "learn_processors": [
                                {"class": "DropnaLabel"},
                                {"class": "CSRankNorm", "kwargs": {"fields_group": "label"}},
                            ],
                            "label": ["Ref($close, -10) / $close - 1"],
                        },
                    },
                    "segments": {
                        "train": ["2018-01-01", "2023-12-31"],
                        "valid": ["2024-01-01", "2024-06-30"],
                        "test": ["2024-07-01", "2024-12-31"],
                    },
                },
            },
        },
    }


def _dict_to_yaml(data: dict[str, Any]) -> str:
    """Convert a dict to YAML string."""
    import yaml

    return yaml.dump(data, default_flow_style=False, sort_keys=False)
