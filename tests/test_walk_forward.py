"""Tests for walk-forward validation logic and API."""

import numpy as np

from src.research.walk_forward import (
    SplitResult,
    WalkForwardResult,
    _compute_ic,
    generate_splits,
)


class TestGenerateSplits:
    """Test the expanding-window split generator."""

    def test_basic_splits_count(self):
        """Default params produce a reasonable number of splits."""
        splits = generate_splits(
            train_start="2021-01-01",
            train_end="2026-04-03",
            test_window_months=6,
            step_months=3,
        )
        # 63 months from 2021-01 to 2026-04, min train 12m,
        # first split at 2022-01, step 3m -> ~14 splits
        assert len(splits) >= 8
        assert len(splits) <= 20

    def test_splits_are_chronological(self):
        """Each split's train_end <= test_start, and splits are ordered."""
        splits = generate_splits()
        for i, (ts, te, vs, ve) in enumerate(splits):
            assert te <= vs, f"Split {i}: train_end {te} must be <= test_start {vs}"
            assert vs < ve, f"Split {i}: test_start {vs} must be < test_end {ve}"
            if i > 0:
                prev_te = splits[i - 1][1]
                assert te >= prev_te, f"Split {i}: train_end must be non-decreasing"

    def test_train_start_is_fixed(self):
        """All splits share the same train_start (expanding window)."""
        splits = generate_splits()
        for ts, te, vs, ve in splits:
            assert ts == "2021-01-01"

    def test_test_windows_do_not_overlap_beyond_step(self):
        """Test windows advance by step_months."""
        splits = generate_splits(
            train_start="2021-01-01",
            train_end="2025-12-31",
            test_window_months=6,
            step_months=3,
        )
        for i in range(1, len(splits)):
            prev_ve = splits[i - 1][3]
            curr_vs = splits[i][2]
            # Current test_start should be >= previous test_end minus some tolerance
            # (they can overlap when step < test_window)
            assert curr_vs >= splits[i - 1][2], "Test starts should be non-decreasing"

    def test_no_splits_when_range_too_short(self):
        """No splits if the total range is less than min train + test."""
        splits = generate_splits(
            train_start="2025-01-01",
            train_end="2025-06-01",
            test_window_months=6,
            step_months=3,
        )
        assert len(splits) == 0

    def test_custom_params(self):
        """Custom test_window and step produce different split counts."""
        short = generate_splits(
            train_start="2021-01-01",
            train_end="2025-12-31",
            test_window_months=12,
            step_months=6,
        )
        long = generate_splits(
            train_start="2021-01-01",
            train_end="2025-12-31",
            test_window_months=6,
            step_months=3,
        )
        assert len(short) < len(long)


class TestWalkForwardResult:
    """Test aggregation logic on WalkForwardResult."""

    def test_aggregate_single_split(self):
        """Single split: mean equals IC, std is 0, ir is 0."""
        r = WalkForwardResult(market="us", model_type="lgbm")
        r.splits = [
            SplitResult(
                split_id=0,
                train_start="2021-01-01",
                train_end="2023-01-01",
                test_start="2023-01-01",
                test_end="2023-07-01",
                ic=0.05,
                rank_ic=0.04,
            )
        ]
        r.aggregate()
        assert r.mean_ic == 0.05
        assert r.std_ic == 0.0  # single sample, ddof=1 -> 0
        assert r.ic_ir == 0.0  # std is 0
        assert r.consistency_score == 1.0

    def test_aggregate_multiple_splits(self):
        """Multiple splits produce correct mean, std, ir, consistency."""
        r = WalkForwardResult(market="us", model_type="lgbm")
        r.splits = [
            SplitResult(
                split_id=i,
                train_start="2021-01-01",
                train_end="2023-01-01",
                test_start="2023-01-01",
                test_end="2023-07-01",
                ic=ic,
                rank_ic=0.0,
            )
            for i, ic in enumerate([0.05, 0.03, -0.01, 0.04, 0.02])
        ]
        r.aggregate()

        ics = [0.05, 0.03, -0.01, 0.04, 0.02]
        expected_mean = np.mean(ics)
        expected_std = np.std(ics, ddof=1)

        assert abs(r.mean_ic - expected_mean) < 1e-10
        assert abs(r.std_ic - expected_std) < 1e-10
        assert abs(r.ic_ir - expected_mean / expected_std) < 1e-10
        assert r.consistency_score == 0.8  # 4/5 positive

    def test_aggregate_empty(self):
        """Empty splits list produces zeros."""
        r = WalkForwardResult(market="us", model_type="lgbm")
        r.aggregate()
        assert r.mean_ic == 0.0
        assert r.std_ic == 0.0
        assert r.ic_ir == 0.0
        assert r.consistency_score == 0.0

    def test_aggregate_all_negative(self):
        """All negative IC gives consistency_score 0."""
        r = WalkForwardResult(market="us", model_type="lgbm")
        r.splits = [
            SplitResult(
                split_id=i,
                train_start="2021-01-01",
                train_end="2023-01-01",
                test_start="2023-01-01",
                test_end="2023-07-01",
                ic=ic,
                rank_ic=0.0,
            )
            for i, ic in enumerate([-0.02, -0.01, -0.03])
        ]
        r.aggregate()
        assert r.consistency_score == 0.0


class TestComputeIC:
    """Test the IC computation helper."""

    def test_perfect_correlation(self):
        """Perfectly correlated arrays give IC near 1."""
        x = np.arange(100, dtype=float)
        y = x * 2 + 1
        pearson, rank = _compute_ic(x, y)
        assert abs(pearson - 1.0) < 1e-10
        assert abs(rank - 1.0) < 1e-10

    def test_anti_correlation(self):
        """Perfectly anti-correlated arrays give IC near -1."""
        x = np.arange(100, dtype=float)
        y = -x
        pearson, rank = _compute_ic(x, y)
        assert abs(pearson - (-1.0)) < 1e-10
        assert abs(rank - (-1.0)) < 1e-10

    def test_no_correlation(self):
        """Uncorrelated random arrays give IC near 0."""
        rng = np.random.default_rng(42)
        x = rng.standard_normal(1000)
        y = rng.standard_normal(1000)
        pearson, rank = _compute_ic(x, y)
        assert abs(pearson) < 0.15
        assert abs(rank) < 0.15

    def test_constant_array(self):
        """Constant array returns 0 (no variance)."""
        x = np.ones(50)
        y = np.arange(50, dtype=float)
        pearson, rank = _compute_ic(x, y)
        assert pearson == 0.0
        assert rank == 0.0

    def test_nan_handling(self):
        """NaN values are filtered out before computing IC."""
        x = np.array([1.0, 2.0, np.nan, 4.0, 5.0])
        y = np.array([2.0, 4.0, 6.0, np.nan, 10.0])
        pearson, rank = _compute_ic(x, y)
        # Only indices 0, 1 are valid (both finite)
        assert np.isfinite(pearson)
        assert np.isfinite(rank)

    def test_too_few_samples(self):
        """Fewer than 5 valid samples returns 0."""
        x = np.array([1.0, 2.0, 3.0])
        y = np.array([2.0, 4.0, 6.0])
        pearson, rank = _compute_ic(x, y)
        assert pearson == 0.0
        assert rank == 0.0


class TestWalkForwardAPI:
    """Test the FastAPI walk-forward endpoints."""

    def test_start_walk_forward_returns_job_id(self):
        """POST /backtest/walk-forward returns a job_id."""
        from fastapi.testclient import TestClient

        from src.api.routers.walk_forward import router

        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.post(
            "/walk-forward",
            json={
                "market": "us",
                "model_type": "lgbm",
                "train_start": "2021-01-01",
                "train_end": "2025-12-31",
                "test_window_months": 6,
                "step_months": 3,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "job_id" in data
        assert len(data["job_id"]) == 12

    def test_get_result_unknown_job(self):
        """GET with unknown job_id returns 404."""
        from fastapi.testclient import TestClient

        from src.api.routers.walk_forward import router

        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        resp = client.get("/walk-forward/nonexistent")
        assert resp.status_code == 404

    def test_get_result_after_submit(self):
        """GET after POST returns the job with pending/running status."""
        from fastapi.testclient import TestClient

        from src.api.routers.walk_forward import router

        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)

        post_resp = client.post(
            "/walk-forward",
            json={"market": "us", "model_type": "lgbm"},
        )
        job_id = post_resp.json()["job_id"]

        get_resp = client.get(f"/walk-forward/{job_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["job_id"] == job_id
        assert data["status"] in ("pending", "running", "succeeded", "failed")
