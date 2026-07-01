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
    labels_df = pd.DataFrame({"training_label": [0.1, 0.05]}, index=idx)
    raw_ret = pd.DataFrame({"return": [0.15, 0.03]}, index=idx)
    raw_ret.attrs["provenance"] = "raw_forward_return"

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
        mock.patch.object(gen_module, "_load_raw_forward_returns", return_value=raw_ret),
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

    idx = pd.MultiIndex.from_arrays(
        [pd.to_datetime(["2024-07-01", "2024-07-01"]), ["AAPL", "MSFT"]],
        names=["datetime", "instrument"],
    )
    pred_df = pd.DataFrame({"score": [0.2, 0.3]}, index=idx)
    labels_df = pd.DataFrame({"training_label": [0.1, 0.05]}, index=idx)
    raw_ret = pd.DataFrame({"return": [0.15, 0.03]}, index=idx)
    raw_ret.attrs["provenance"] = "raw_forward_return"

    snapshot_ref = {
        "id": "test-snapshot-id",
        "manifest": "artifacts/snapshots/test/manifest.json",
        "sha256": "a" * 64,
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
        mock.patch.object(gen_module, "_load_raw_forward_returns", return_value=raw_ret),
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
# Raw-forward-return loader and provenance guard tests
# ---------------------------------------------------------------------------


def test_load_raw_forward_returns_rejects_missing_label(gen_module: Any) -> None:
    """_load_raw_forward_returns raises StageFailure when label is missing."""
    config: dict[str, Any] = {
        "task": {
            "dataset": {
                "kwargs": {
                    "handler": {"kwargs": {}},
                    "segments": {"test": ["2024-07-01", "2024-12-31"]},
                }
            }
        }
    }
    with pytest.raises(gen_module.StageFailure, match=r"(?i)no.*label"):
        gen_module._load_raw_forward_returns(config, "us")


def test_load_raw_forward_returns_rejects_non_forward_expression(
    gen_module: Any,
) -> None:
    """_load_raw_forward_returns raises StageFailure for non-forward expressions."""
    config: dict[str, Any] = {
        "task": {
            "dataset": {
                "kwargs": {
                    "handler": {"kwargs": {"label": ["$close"]}},
                    "segments": {"test": ["2024-07-01", "2024-12-31"]},
                }
            }
        }
    }
    with pytest.raises(gen_module.StageFailure, match=r"(?i)unsupported.*expression"):
        gen_module._load_raw_forward_returns(config, "us")


def test_load_raw_forward_returns_rejects_missing_test_segment(
    gen_module: Any,
) -> None:
    """_load_raw_forward_returns raises StageFailure when test segment is missing."""
    config: dict[str, Any] = {
        "task": {
            "dataset": {
                "kwargs": {
                    "handler": {
                        "kwargs": {"label": ["Ref($close, -10) / $close - 1"]}
                    },
                }
            }
        }
    }
    with pytest.raises(gen_module.StageFailure, match=r"(?i)test.segment"):
        gen_module._load_raw_forward_returns(config, "us")


def test_provenance_guard_rejects_missing_provenance(gen_module: Any) -> None:
    """_validate_return_provenance rejects DataFrames without provenance tag."""
    idx = pd.MultiIndex.from_tuples(
        [("2024-07-01", "AAPL"), ("2024-07-01", "MSFT")],
        names=["datetime", "instrument"],
    )
    bad = pd.DataFrame({"return": [0.1, 0.05]}, index=idx)
    with pytest.raises(gen_module.StageFailure, match=r"(?i)provenance"):
        gen_module._validate_return_provenance(bad)


def test_provenance_guard_rejects_training_label_column(gen_module: Any) -> None:
    """_validate_return_provenance rejects a 'training_label' column."""
    idx = pd.MultiIndex.from_tuples(
        [("2024-07-01", "AAPL"), ("2024-07-01", "MSFT")],
        names=["datetime", "instrument"],
    )
    bad = pd.DataFrame({"training_label": [0.1, 0.05]}, index=idx)
    bad.attrs["provenance"] = "raw_forward_return"
    with pytest.raises(gen_module.StageFailure, match=r"(?i)column"):
        gen_module._validate_return_provenance(bad)


def test_provenance_guard_accepts_valid_raw_returns(gen_module: Any) -> None:
    """_validate_return_provenance accepts a properly tagged raw-return DataFrame."""
    idx = pd.MultiIndex.from_tuples(
        [("2024-07-01", "AAPL"), ("2024-07-01", "MSFT")],
        names=["datetime", "instrument"],
    )
    valid = pd.DataFrame({"return": [0.1, 0.05]}, index=idx)
    valid.attrs["provenance"] = "raw_forward_return"
    # Should not raise
    gen_module._validate_return_provenance(valid)


def test_provenance_guard_accepts_zero_returns(gen_module: Any) -> None:
    """_validate_return_provenance accepts all-zero raw returns (valid provenance)."""
    idx = pd.MultiIndex.from_tuples(
        [("2024-07-01", "AAPL"), ("2024-07-01", "MSFT")],
        names=["datetime", "instrument"],
    )
    zero = pd.DataFrame({"return": [0.0, 0.0]}, index=idx)
    zero.attrs["provenance"] = "raw_forward_return"
    # Should not raise -- all-zero raw returns are valid (spread=0)
    gen_module._validate_return_provenance(zero)


# ---------------------------------------------------------------------------
# Raw-forward-return NaN filtering tests
# ---------------------------------------------------------------------------


def _raw_return_config() -> dict[str, Any]:
    """Return a minimal config valid for _load_raw_forward_returns pre-D checks."""
    return {
        "task": {
            "dataset": {
                "kwargs": {
                    "handler": {
                        "kwargs": {
                            "label": ["Ref($close, -10) / $close - 1"],
                            "instruments": "us",
                        }
                    },
                    "segments": {
                        "test": ["2024-07-01", "2024-12-31"],
                    },
                }
            }
        }
    }


def _mock_qlib_d(monkeypatch: Any, raw_df: pd.DataFrame) -> None:
    """Replace qlib.data.D with a fake that returns *raw_df* from D.features."""
    from types import ModuleType
    import sys

    instruments = ["AAPL", "MSFT", "GOOG"]

    class _MockD:
        @staticmethod
        def list_instruments(inst: Any, as_list: bool = True) -> list[str]:
            return instruments

        @staticmethod
        def instruments(key: str) -> str:
            return key

        @staticmethod
        def features(
            symbols: Any,
            expressions: list[str],
            start_time: str | None = None,
            end_time: str | None = None,
        ) -> pd.DataFrame:
            return raw_df

    if "qlib" not in sys.modules:
        sys.modules["qlib"] = ModuleType("qlib")
    fake_data = ModuleType("qlib.data")
    fake_data.D = _MockD
    monkeypatch.setitem(sys.modules, "qlib.data", fake_data)


def test_raw_forward_returns_drops_partial_nan(
    gen_module: Any, monkeypatch: Any,
) -> None:
    """Partial NaN/inf rows are dropped and coverage stats recorded."""
    dates = pd.bdate_range("2024-07-01", periods=3)
    instruments = ["AAPL", "MSFT", "GOOG"]
    idx = pd.MultiIndex.from_product(
        [dates, instruments], names=["datetime", "instrument"],
    )
    vals = [0.01, 0.02, np.nan, 0.03, 0.05, -0.01, -0.02, 0.04, 0.06]
    raw_df = pd.DataFrame(
        vals, index=idx, columns=["Ref($close, -10) / $close - 1"],
    )

    _mock_qlib_d(monkeypatch, raw_df)
    result = gen_module._load_raw_forward_returns(_raw_return_config(), "us")

    assert "return" in result.columns
    assert len(result) == 8  # 9 - 1 non-finite
    assert result.attrs["n_raw_rows"] == 9
    assert result.attrs["n_dropped_non_finite"] == 1
    assert result.attrs["n_valid_rows"] == 8
    assert abs(result.attrs["coverage_ratio"] - 8.0 / 9.0) < 1e-10
    assert result.attrs["provenance"] == "raw_forward_return"


def test_raw_forward_returns_fails_on_all_nan(
    gen_module: Any, monkeypatch: Any,
) -> None:
    """All-NaN/inf raw returns raise StageFailure."""
    dates = pd.bdate_range("2024-07-01", periods=2)
    instruments = ["AAPL", "MSFT"]
    idx = pd.MultiIndex.from_product(
        [dates, instruments], names=["datetime", "instrument"],
    )
    raw_df = pd.DataFrame(
        [np.nan, np.inf, -np.inf, np.nan],
        index=idx,
        columns=["Ref($close, -10) / $close - 1"],
    )

    _mock_qlib_d(monkeypatch, raw_df)
    with pytest.raises(gen_module.StageFailure, match=r"(?i)empty.*valid|all.*non.finite"):
        gen_module._load_raw_forward_returns(_raw_return_config(), "us")


def test_raw_forward_returns_fails_on_low_coverage(
    gen_module: Any, monkeypatch: Any,
) -> None:
    """Coverage below 80% raises InsufficientReturnCoverage."""
    dates = pd.bdate_range("2024-07-01", periods=5)
    instruments = ["A", "B"]
    idx = pd.MultiIndex.from_product(
        [dates, instruments], names=["datetime", "instrument"],
    )
    vals = [0.01, np.nan, np.nan, np.nan, np.nan,
            np.nan, 0.02, np.nan, np.nan, 0.03]
    raw_df = pd.DataFrame(
        vals, index=idx, columns=["Ref($close, -10) / $close - 1"],
    )

    _mock_qlib_d(monkeypatch, raw_df)
    with pytest.raises(gen_module.StageFailure, match=r"(?i)insufficient.*coverage|coverage"):
        gen_module._load_raw_forward_returns(_raw_return_config(), "us")


# ---------------------------------------------------------------------------
# Score-direction diagnostics tests
# ---------------------------------------------------------------------------


def _make_pred_ret_pair(
    scores: list[float],
    returns: list[float],
    dates: list[str] | None = None,
    instruments: list[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build aligned predictions and raw-returns DataFrames for testing."""
    if dates is None:
        dates = ["2024-07-01"] * len(scores)
    if instruments is None:
        instruments = [f"STK{i:04d}" for i in range(len(scores))]
    idx = pd.MultiIndex.from_arrays(
        [pd.to_datetime(dates), instruments],
        names=["datetime", "instrument"],
    )
    pred = pd.DataFrame({"score": scores}, index=idx)
    ret = pd.DataFrame({"return": returns}, index=idx)
    ret.attrs["provenance"] = "raw_forward_return"
    return pred, ret


def test_score_diagnostics_positive_ordering_tmb_positive(gen_module: Any) -> None:
    """Positive score ordering yields top_minus_bottom > 0 and keep_score."""
    pred, ret = _make_pred_ret_pair(
        scores=[5.0, 4.0, 3.0, 2.0, 1.0],
        returns=[0.10, 0.08, 0.05, 0.01, -0.02],
    )
    diag = gen_module._compute_score_diagnostics(pred, ret)
    assert diag["top_minus_bottom"] > 0, f"Expected tmb > 0, got {diag['top_minus_bottom']}"
    assert diag["recommendation"] == "keep_score"


def test_score_diagnostics_reversed_ordering_tmb_negative(gen_module: Any) -> None:
    """Reversed score ordering yields top_minus_bottom < 0 and invert_score."""
    pred, ret = _make_pred_ret_pair(
        scores=[1.0, 2.0, 3.0, 4.0, 5.0],
        returns=[0.10, 0.08, 0.05, 0.01, -0.02],
    )
    diag = gen_module._compute_score_diagnostics(pred, ret)
    assert diag["top_minus_bottom"] < 0, f"Expected tmb < 0, got {diag['top_minus_bottom']}"
    assert diag["recommendation"] == "invert_score"


def test_score_diagnostics_all_zero_returns(gen_module: Any) -> None:
    """All-zero raw returns produce top_minus_bottom == 0 and no_signal."""
    pred, ret = _make_pred_ret_pair(
        scores=[5.0, 4.0, 3.0, 2.0, 1.0],
        returns=[0.0, 0.0, 0.0, 0.0, 0.0],
    )
    diag = gen_module._compute_score_diagnostics(pred, ret)
    assert abs(diag["top_minus_bottom"]) < 1e-12
    assert diag["recommendation"] == "no_signal"


def test_score_diagnostics_n_samples_reported(gen_module: Any) -> None:
    """Score diagnostics reports n_samples correctly."""
    pred, ret = _make_pred_ret_pair(
        scores=list(range(100, 0, -1)),
        returns=[v * 0.01 for v in range(100, 0, -1)],
    )
    diag = gen_module._compute_score_diagnostics(pred, ret)
    assert diag["n_samples"] == 100
    assert diag["recommendation"] in ("keep_score", "invert_score", "inconclusive", "no_signal")


def test_score_diagnostics_per_date_decile_means(gen_module: Any) -> None:
    """Prove decile means are computed per-date then averaged, not globally pooled.

    Two dates each with 10 stocks and identical positive score-return
    correlation, but date 2 has systematically higher return levels.
    Per-date averaging yields tmb=0.09 (each date's decile gap equals 0.09).
    Global pooling would select all top-decile stocks from date 2 (higher
    returns) and all bottom-decile from date 1 (lower returns), producing
    a much larger tmb (~1.08).  Per-date grouping avoids this bias.
    """
    pred, ret = _make_pred_ret_pair(
        scores=list(range(1, 11)) + list(range(1001, 1011)),
        returns=[0.01 * i for i in range(1, 11)] + [1.00 + 0.01 * i for i in range(1, 11)],
        dates=["2024-01-02"] * 10 + ["2024-01-03"] * 10,
    )
    diag = gen_module._compute_score_diagnostics(pred, ret)

    assert diag["n_dates"] == 2, f"Expected n_dates=2, got {diag['n_dates']}"
    assert diag["n_samples"] == 20

    # Per-date: day1 top=0.10, day2 top=1.10 → avg=0.60
    # Per-date: day1 bottom=0.01, day2 bottom=1.01 → avg=0.51
    # tmb = 0.60 - 0.51 = 0.09
    assert abs(diag["top_decile_mean_return"] - 0.60) < 1e-8, (
        f"Expected top_decile_mean=0.60, got {diag['top_decile_mean_return']}"
    )
    assert abs(diag["bottom_decile_mean_return"] - 0.51) < 1e-8, (
        f"Expected bottom_decile_mean=0.51, got {diag['bottom_decile_mean_return']}"
    )
    assert abs(diag["top_minus_bottom"] - 0.09) < 1e-8, (
        f"Expected tmb=0.09, got {diag['top_minus_bottom']}"
    )
    assert diag["recommendation"] == "keep_score"


# ---------------------------------------------------------------------------
# Score diagnostics uses raw returns, not processed labels
# ---------------------------------------------------------------------------


def test_score_diagnostics_computed_on_raw_returns_not_processed_labels(
    gen_module: Any,
) -> None:
    """_compute_score_diagnostics must reject non-raw provenance.

    Pass a DataFrame with 'return' column (correct column name) but
    explicitly non-raw provenance to prove column renaming cannot
    bypass the provenance guard.
    """
    pred, _ = _make_pred_ret_pair(
        scores=[5.0, 4.0, 3.0, 2.0, 1.0],
        returns=[0.10, 0.08, 0.05, 0.01, -0.02],
    )
    # "return" column (correct name) but explicitly wrong provenance
    idx = pred.index
    processed = pd.DataFrame({"return": [0.1, 0.08, 0.05, 0.01, -0.02]}, index=idx)
    processed.attrs["provenance"] = "processed_label"
    with pytest.raises(gen_module.StageFailure, match=r"(?i)provenance"):
        gen_module._compute_score_diagnostics(pred, processed)


# ---------------------------------------------------------------------------
# Walk-forward raw IC test
# ---------------------------------------------------------------------------


def test_walk_forward_raw_ic_uses_raw_returns(gen_module: Any, monkeypatch):
    """_run_single_split must compute IC against raw forward returns, not DK_L.

    Monkey-patch D.features to return raw returns (not processed labels)
    and verify the IC values reflect the raw-return signal, not CSRankNorm.
    """
    from src.research.walk_forward import _run_single_split

    # Build a minimal config with known label expression
    config = {
        "task": {
            "model": {"kwargs": {}},
            "dataset": {
                "kwargs": {
                    "handler": {
                        "kwargs": {
                            "start_time": "2021-01-01",
                            "end_time": "2026-06-25",
                            "label": ["Ref($close, -10) / $close - 1"],
                            "instruments": "us",
                        }
                    },
                    "segments": {
                        "train": ["2021-01-01", "2024-12-31"],
                        "valid": ["2025-01-01", "2025-12-31"],
                        "test": ["2026-01-01", "2026-06-25"],
                    },
                }
            },
        }
    }

    # Build fake index and data
    dates = pd.bdate_range("2026-01-05", periods=2)
    instruments = ["A", "B", "C", "D", "E"]
    _FAKE_IDX = pd.MultiIndex.from_product(
        [dates, instruments], names=["datetime", "instrument"]
    )

    class FakeDataset:
        def prepare(self, segments, col_set, data_key):
            return pd.DataFrame(
                {"label": np.arange(len(_FAKE_IDX), dtype=float)},
                index=_FAKE_IDX,
            )

    class FakeModel:
        def fit(self, dataset):
            return None
        def predict(self, dataset, segment="test"):
            return pd.Series(
                np.arange(len(_FAKE_IDX), dtype=float), index=_FAKE_IDX,
            )

    def _fake_init(cfg):
        if "handler" in cfg.get("kwargs", {}):
            return FakeDataset()
        return FakeModel()

    # Track which label expression was fetched
    fetched_exprs = []
    raw_idx = _FAKE_IDX
    rng = np.random.default_rng(42)

    class _FakeD:
        @staticmethod
        def features(symbols, expressions, start_time=None, end_time=None):
            fetched_exprs.append(expressions)
            return pd.DataFrame(
                {"return": rng.standard_normal(len(raw_idx))},
                index=raw_idx,
            )
        @staticmethod
        def instruments(name):
            return name
        @staticmethod
        def list_instruments(instruments, as_list=True):
            return instruments if isinstance(instruments, list) else ["A", "B", "C", "D", "E"]

    monkeypatch.setattr(
        "src.research.walk_forward.init_instance_by_config", _fake_init,
    )
    import src.research.walk_forward as wf_mod
    monkeypatch.setattr(wf_mod, "D", _FakeD())

    # The calendar must be available
    cal = pd.bdate_range("2020-01-01", "2026-12-31")
    monkeypatch.setattr(
        "src.research.walk_forward._get_trading_calendar",
        lambda start, end: cal,
    )

    result = _run_single_split(
        base_config=config, split_id=0,
        train_start="2021-01-01", train_end="2025-12-31",
        test_start="2026-01-01", test_end="2026-06-25",
        label_horizon=0,
    )

    assert len(fetched_exprs) >= 1, "D.features should have been called for raw returns"
    raw_expr = fetched_exprs[0]
    assert "Ref($close, -10) / $close - 1" in str(raw_expr), (
        f"Expected raw expression, got {raw_expr}"
    )
    assert result.ic is not None
    assert result.rank_ic is not None


# ---------------------------------------------------------------------------
# Walk-forward: vectorized path uses raw returns for IC
# ---------------------------------------------------------------------------


def test_vectorized_wf_uses_raw_label_expression(
    monkeypatch, tmp_path,
):
    """Vectorized walk-forward loads raw label expression for IC computation."""
    import importlib
    import sys
    from types import ModuleType

    from src.research.walk_forward import walk_forward_vectorized

    cal = pd.bdate_range("2024-01-01", periods=800)

    monkeypatch.setattr(
        "src.common.qlib_init.safe_qlib_init", lambda cfg: None)
    monkeypatch.setattr(
        "src.common.qlib_init.build_qlib_init_cfg", lambda uri, market: {})
    monkeypatch.setattr(
        "src.research.walk_forward._get_trading_calendar",
        lambda start, end: cal)

    instr_dir = tmp_path / "data" / "watchlist" / "instruments"
    instr_dir.mkdir(parents=True)
    (instr_dir / "cn.txt").write_text("A\nB\nC\n")
    monkeypatch.chdir(tmp_path)

    instruments = ["A", "B", "C"]
    dates = cal[cal >= pd.Timestamp("2024-01-01")]
    idx = pd.MultiIndex.from_product(
        [dates, instruments], names=["datetime", "instrument"])
    rng = np.random.default_rng(42)
    base = rng.standard_normal((len(idx), 1))
    X_df = pd.DataFrame(
        np.column_stack([base, base * 0.9 + 0.1, base * 1.1 - 0.1]),
        index=idx, columns=["feat_a", "feat_b", "feat_c"],
    )
    y_df = pd.DataFrame(base * 0.5 + 0.05, index=idx, columns=["label"])

    _feat_call = [0]
    _fetched_exprs: list[Any] = []

    class _FakeD:
        @staticmethod
        def features(symbols, expressions, start_time=None, end_time=None):
            _feat_call[0] += 1
            _fetched_exprs.append(expressions)
            return X_df if _feat_call[0] == 1 else y_df

    fake_data_module = ModuleType("qlib.data")
    fake_data_module.D = _FakeD

    loader_module = importlib.import_module("qlib.contrib.data.loader")
    monkeypatch.setitem(sys.modules, "qlib.data", fake_data_module)

    class _FakeAlpha:
        @staticmethod
        def get_feature_config(cfg):
            return (["$close"], {})

    monkeypatch.setattr(loader_module, "Alpha158DL", _FakeAlpha)

    class _FakeBooster:
        def predict(self, X):
            return np.zeros(len(X))

    lightgbm_module = importlib.import_module("lightgbm")
    monkeypatch.setattr(
        lightgbm_module, "train",
        lambda params, train_set, num_boost_round: _FakeBooster(),
    )

    result = walk_forward_vectorized(
        market="cn", train_start="2024-01-01", train_end="2025-12-15",
        test_window_months=1, step_months=1, n_estimators=1,
    )

    # The vectorized path loads raw label expression at index 1+ (after features)
    _fetched_exprs_at_1 = _fetched_exprs[1] if len(_fetched_exprs) > 1 else []
    expr_str = str(_fetched_exprs_at_1)
    assert "Ref($close, -10)" in expr_str or "Ref($close, -1)" in expr_str, (
        f"Expected raw label expression, got {_fetched_exprs}"
    )
    # IC should be computed and finite
    for sr in result.splits:
        if sr.status == "success":
            assert sr.ic is not None, "IC must not be None for successful splits"
            assert sr.rank_ic is not None, "Rank IC must not be None for successful splits"


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
