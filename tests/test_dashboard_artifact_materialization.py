"""Tests for dashboard artifact materialization.

Covers:
- artifact bundle discovery under artifacts/artifacts/<run_id>
- load_artifact_bundle_run_data() with metrics.json + predictions.csv + labels.csv
- has_full_data=false when report_normal is absent
- placeholder registry entries (empty run_id/path/metrics) are skipped
- normal mlruns layout still works
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# load_artifact_bundle_run_data tests
# ---------------------------------------------------------------------------

class TestLoadArtifactBundleRunData:
    """Test the bundle loader for artifacts/artifacts/<run_id>/ directories."""

    def test_loads_metrics_json_as_indicators(self, tmp_path):
        """Indicators are mapped from metrics.json keys to dashboard keys."""
        from scripts.build_dashboard_db import load_artifact_bundle_run_data

        bundle = tmp_path / "test_run"
        bundle.mkdir()
        metrics = {
            "total_return": 0.9568,
            "annual_return": 0.5608,
            "sharpe_ratio": 1.527,
            "ic_ir": 0.0915,
            "max_drawdown": -0.2782,
            "volatility": 0.3287,
            "mean_ic": 0.0074,
        }
        (bundle / "metrics.json").write_text(json.dumps(metrics))

        result = load_artifact_bundle_run_data(bundle)

        assert result["report_normal"] is None
        assert result["positions_normal"] == []
        assert result["indicators"]["total_return"] == 0.9568
        assert result["indicators"]["sharpe"] == 1.527
        assert result["indicators"]["information_ratio"] == 0.0915
        assert result["indicators"]["max_drawdown"] == -0.2782
        assert result["indicators"]["annual_volatility"] == 0.3287
        assert result["sig_analysis"]["ic"]["ic"] == 0.0074

    def test_handles_missing_metrics_json(self, tmp_path):
        """Returns empty dicts when metrics.json does not exist."""
        from scripts.build_dashboard_db import load_artifact_bundle_run_data

        bundle = tmp_path / "empty_run"
        bundle.mkdir()

        result = load_artifact_bundle_run_data(bundle)

        assert result["report_normal"] is None
        assert result["positions_normal"] == []
        assert result["indicators"] == {}
        assert result["sig_analysis"] == {}

    def test_handles_corrupt_metrics_json(self, tmp_path):
        """Gracefully handles invalid JSON in metrics.json."""
        from scripts.build_dashboard_db import load_artifact_bundle_run_data

        bundle = tmp_path / "corrupt_run"
        bundle.mkdir()
        (bundle / "metrics.json").write_text("not valid json {{{")

        result = load_artifact_bundle_run_data(bundle)
        # Should not raise; should return empty dicts
        assert result["indicators"] == {}
        assert result["sig_analysis"] == {}

    def test_with_predictions_and_labels_present(self, tmp_path):
        """Bundle with predictions.csv + labels.csv + metrics.json loads correctly."""
        from scripts.build_dashboard_db import load_artifact_bundle_run_data

        bundle = tmp_path / "full_bundle"
        bundle.mkdir()
        metrics = {"total_return": 0.3123, "sharpe_ratio": 1.22, "mean_ic": 0.02}
        (bundle / "metrics.json").write_text(json.dumps(metrics))
        (bundle / "predictions.csv").write_text("datetime,instrument,prediction\n")
        (bundle / "labels.csv").write_text("datetime,instrument,return\n")

        result = load_artifact_bundle_run_data(bundle)

        # Still no report_normal (full backtest not run)
        assert result["report_normal"] is None
        assert result["indicators"]["total_return"] == 0.3123

    def test_nested_vectorized_backtest_priority(self, tmp_path):
        """vectorized_backtest takes priority over grade_regime and flat keys."""
        from scripts.build_dashboard_db import load_artifact_bundle_run_data

        bundle = tmp_path / "nested_run"
        bundle.mkdir()
        metrics = {
            "total_return": 0.1,  # flat, should be ignored
            "vectorized_backtest": {
                "total_return": 0.9568,
                "sharpe_ratio": 1.527,
                "max_drawdown": -0.2782,
                "annual_return": 0.5608,
                "volatility": 0.3287,
                "mean_ic": 0.0074,
                "ic_ir": 0.0915,
            },
            "grade_regime_backtest": {
                "total_return": 0.4,
                "sharpe_ratio": 0.8,
            },
        }
        (bundle / "metrics.json").write_text(json.dumps(metrics))

        result = load_artifact_bundle_run_data(bundle)

        # Should use vectorized_backtest values, not flat or grade_regime
        assert result["indicators"]["total_return"] == 0.9568
        assert result["indicators"]["sharpe"] == 1.527
        assert result["indicators"]["max_drawdown"] == -0.2782
        assert result["indicators"]["annual_return"] == 0.5608
        assert result["sig_analysis"]["ic"]["ic"] == 0.0074

    def test_nested_grade_regime_fallback(self, tmp_path):
        """grade_regime_backtest is used when vectorized_backtest is missing."""
        from scripts.build_dashboard_db import load_artifact_bundle_run_data

        bundle = tmp_path / "grade_only_run"
        bundle.mkdir()
        metrics = {
            "grade_regime_backtest": {
                "total_return": 0.3928,
                "sharpe_ratio": 1.9496,
                "max_drawdown": -0.0311,
                "annual_return": 0.2457,
                "volatility": 0.117,
                "mean_ic": 0.0226,
                "ic_ir": 0.1663,
            },
        }
        (bundle / "metrics.json").write_text(json.dumps(metrics))

        result = load_artifact_bundle_run_data(bundle)

        assert result["indicators"]["total_return"] == 0.3928
        assert result["indicators"]["sharpe"] == 1.9496
        assert result["indicators"]["max_drawdown"] == -0.0311

    def test_nested_string_values_coerced(self, tmp_path):
        """String metric values are coerced to float."""
        from scripts.build_dashboard_db import load_artifact_bundle_run_data

        bundle = tmp_path / "string_metrics_run"
        bundle.mkdir()
        metrics = {
            "grade_regime_backtest": {
                "total_return": "0.4012",
                "excess_return": "0.3051",
                "sharpe_ratio": 1.6454,
            },
        }
        (bundle / "metrics.json").write_text(json.dumps(metrics))

        result = load_artifact_bundle_run_data(bundle)

        assert result["indicators"]["total_return"] == 0.4012
        assert result["indicators"]["sharpe"] == 1.6454

    def test_empty_nested_section_falls_back_to_flat(self, tmp_path):
        """Empty nested section is skipped; flat keys are used instead."""
        from scripts.build_dashboard_db import load_artifact_bundle_run_data

        bundle = tmp_path / "empty_nested_run"
        bundle.mkdir()
        metrics = {
            "vectorized_backtest": {},  # empty, skipped
            "grade_regime_backtest": {},  # empty, skipped
            "total_return": 0.25,
            "sharpe_ratio": 0.9,
        }
        (bundle / "metrics.json").write_text(json.dumps(metrics))

        result = load_artifact_bundle_run_data(bundle)

        assert result["indicators"]["total_return"] == 0.25
        assert result["indicators"]["sharpe"] == 0.9


class TestResolveBestMetricsSection:
    """Test the nested metrics priority resolver."""

    def test_priority_vectorized_over_grade_regime(self):
        from scripts.build_dashboard_db import _resolve_best_metrics_section

        raw = {
            "vectorized_backtest": {"total_return": 0.9},
            "grade_regime_backtest": {"total_return": 0.5},
        }
        result = _resolve_best_metrics_section(raw)
        assert result["total_return"] == 0.9

    def test_fallback_to_grade_regime(self):
        from scripts.build_dashboard_db import _resolve_best_metrics_section

        raw = {
            "grade_regime_backtest": {"total_return": 0.5},
        }
        result = _resolve_best_metrics_section(raw)
        assert result["total_return"] == 0.5

    def test_fallback_to_flat(self):
        from scripts.build_dashboard_db import _resolve_best_metrics_section

        raw = {"total_return": 0.3, "sharpe_ratio": 1.0}
        result = _resolve_best_metrics_section(raw)
        assert result["total_return"] == 0.3

    def test_skips_empty_nested(self):
        from scripts.build_dashboard_db import _resolve_best_metrics_section

        raw = {
            "vectorized_backtest": {},
            "grade_regime_backtest": None,
            "total_return": 0.42,
        }
        result = _resolve_best_metrics_section(raw)
        assert result["total_return"] == 0.42


class TestToFloat:
    """Test the value coercion helper."""

    def test_int(self):
        from scripts.build_dashboard_db import _to_float
        assert _to_float(42) == 42.0

    def test_float(self):
        from scripts.build_dashboard_db import _to_float
        assert _to_float(3.14) == 3.14

    def test_string_number(self):
        from scripts.build_dashboard_db import _to_float
        assert _to_float("0.9568") == 0.9568

    def test_invalid_string(self):
        from scripts.build_dashboard_db import _to_float
        assert _to_float("not_a_number") == 0.0

    def test_none(self):
        from scripts.build_dashboard_db import _to_float
        assert _to_float(None) == 0.0


# ---------------------------------------------------------------------------
# _is_placeholder_entry tests
# ---------------------------------------------------------------------------

class TestIsPlaceholderEntry:
    """Test the placeholder detection logic."""

    def test_detects_empty_entry(self):
        """Entry with no run_id, no path, empty metrics is a placeholder."""
        from scripts.build_dashboard_db import _is_placeholder_entry

        entry = {
            "id": "cn_model_cn_best_v2_20260621",
            "run_id": "",
            "path": "",
            "metrics_json": "{}",
        }
        assert _is_placeholder_entry(entry) is True

    def test_rejects_entry_with_run_id(self):
        """Entry with run_id is NOT a placeholder."""
        from scripts.build_dashboard_db import _is_placeholder_entry

        entry = {
            "id": "us_model_us_absret_20260621",
            "run_id": "a8a1b3b618ef4a80920bc22c6a8973f7",
            "path": "",
            "metrics_json": "{}",
        }
        assert _is_placeholder_entry(entry) is False

    def test_rejects_entry_with_path(self):
        """Entry with path is NOT a placeholder even without run_id."""
        from scripts.build_dashboard_db import _is_placeholder_entry

        entry = {
            "id": "some_model",
            "run_id": "",
            "path": "/some/path/model.pkl",
            "metrics_json": "{}",
        }
        assert _is_placeholder_entry(entry) is False

    def test_rejects_entry_with_metrics(self):
        """Entry with non-empty metrics is NOT a placeholder."""
        from scripts.build_dashboard_db import _is_placeholder_entry

        entry = {
            "id": "some_model",
            "run_id": "",
            "path": "",
            "metrics_json": '{"total_return": 0.3}',
        }
        assert _is_placeholder_entry(entry) is False

    def test_rejects_none_metrics(self):
        """Entry with no metrics_json at all is a placeholder (if other fields empty too)."""
        from scripts.build_dashboard_db import _is_placeholder_entry

        entry = {
            "id": "some_model",
            "run_id": "",
            "path": "",
        }
        assert _is_placeholder_entry(entry) is True


# ---------------------------------------------------------------------------
# build_db integration tests
# ---------------------------------------------------------------------------

class TestBuildDbWithArtifactBundle:
    """Test build_db with artifact bundle discovery."""

    def test_bundle_discovery(self, tmp_path, monkeypatch):
        """build_db finds artifact bundle under ARTIFACTS_DIR/artifacts/<run_id>."""


        from scripts import build_dashboard_db as bdd

        # Create a minimal artifact bundle
        artifacts_dir = tmp_path / "artifacts" / "artifacts"
        run_dir = artifacts_dir / "a8a1b3b618ef4a80920bc22c6a8973f7"
        run_dir.mkdir(parents=True)
        metrics = {
            "total_return": 0.9568,
            "annual_return": 0.5608,
            "sharpe_ratio": 1.527,
            "ic_ir": 0.0915,
            "max_drawdown": -0.2782,
            "volatility": 0.3287,
            "mean_ic": 0.0074,
        }
        (run_dir / "metrics.json").write_text(json.dumps(metrics))
        (run_dir / "predictions.csv").write_text("d,h,p\n")
        (run_dir / "labels.csv").write_text("d,h,r\n")

        # Stub ARTIFACTS_DIR to point to our tmp dir
        monkeypatch.setattr(bdd, "ARTIFACTS_DIR", tmp_path / "artifacts")
        # Stub MLRUNS_DIR and other search dirs to non-existent paths
        monkeypatch.setattr(bdd, "MLRUNS_DIR", tmp_path / "mlruns")
        monkeypatch.setattr(bdd, "PROJECT_ROOT", tmp_path)

        # Stub resolve_metadata_db_path to return a temp db
        db_path = tmp_path / "metadata.db"
        monkeypatch.setattr(
            bdd, "resolve_metadata_db_path", lambda _: db_path
        )

        # Create a minimal SQLite metadata DB with the model version
        _seed_metadata_db(db_path, model_id="us_model_us_absret_20260621",
                          run_id="a8a1b3b618ef4a80920bc22c6a8973f7",
                          market="us", created_at="2026-06-21")

        # Stub DASHBOARD_DB_PATH
        dash_path = tmp_path / "dashboard" / "dashboard_db.json"
        monkeypatch.setattr(bdd, "DASHBOARD_DB_PATH", dash_path)

        # Stub CONFIG_DIR for name_map
        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        (config_dir / "name_map.yaml").write_text("{}")
        monkeypatch.setattr(bdd, "CONFIG_DIR", config_dir)

        # Patch qlib to avoid real init
        import qlib
        monkeypatch.setattr(qlib, "init", lambda **kw: None)

        # Also patch qlib.data.D to avoid real data access
        monkeypatch.setattr(qlib.data.D, "features", lambda *a, **kw: _empty_qlib_df(), raising=False)

        # Run build_db
        bdd.build_db()

        # Verify dashboard JSON was written
        assert dash_path.exists(), "dashboard_db.json should exist"
        dashboard = json.loads(dash_path.read_text())
        models = dashboard.get("models", [])
        assert len(models) >= 1, "Should have at least one model"

        # Find our model
        model = next((m for m in models if m["id"] == "us_model_us_absret_20260621"), None)
        assert model is not None, "Model should be in dashboard"
        assert model["has_full_data"] is False, "has_full_data=false (no report_normal)"
        assert model["source_layout"] == "artifact_bundle"
        assert model["data"]["indicators"]["total_return"] == 0.9568
        assert model["data"]["indicators"]["sharpe"] == 1.527

    def test_placeholder_entry_skipped(self, tmp_path, monkeypatch):
        """Placeholder entries are skipped during build_db."""
        from scripts import build_dashboard_db as bdd

        # Stub paths
        monkeypatch.setattr(bdd, "ARTIFACTS_DIR", tmp_path / "artifacts")
        monkeypatch.setattr(bdd, "MLRUNS_DIR", tmp_path / "mlruns")
        monkeypatch.setattr(bdd, "PROJECT_ROOT", tmp_path)

        db_path = tmp_path / "metadata.db"
        monkeypatch.setattr(bdd, "resolve_metadata_db_path", lambda _: db_path)

        # Create placeholder entry in DB
        _seed_metadata_db(db_path, model_id="cn_model_cn_best_v2_20260621",
                          run_id="", market="cn", created_at="",
                          metrics_json="{}")

        dash_path = tmp_path / "dashboard" / "dashboard_db.json"
        monkeypatch.setattr(bdd, "DASHBOARD_DB_PATH", dash_path)

        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        (config_dir / "name_map.yaml").write_text("{}")
        monkeypatch.setattr(bdd, "CONFIG_DIR", config_dir)

        import qlib
        monkeypatch.setattr(qlib, "init", lambda **kw: None)

        bdd.build_db()

        dashboard = json.loads(dash_path.read_text())
        models = dashboard.get("models", [])
        ids = [m["id"] for m in models]
        assert "cn_model_cn_best_v2_20260621" not in ids, "Placeholder should be skipped"

    def test_normal_mlruns_layout_still_works(self, tmp_path, monkeypatch):
        """Standard mlruns layout is still discovered correctly."""
        from scripts import build_dashboard_db as bdd

        # Create standard mlruns layout
        mlruns_dir = tmp_path / "mlruns" / "1"
        run_dir = mlruns_dir / "a1cc0264861a4c898cc047c6002a6d4d"
        run_dir.mkdir(parents=True)
        art_dir = run_dir / "artifacts"
        art_dir.mkdir()
        # Write report_normal_1day as pickle — use a simple dict since
        # pd.DataFrame pickle would require pandas at read time
        import pandas as pd

        # Create a simple report_normal as a DataFrame pickle
        df = pd.DataFrame({
            "account": [10000.0, 10100.0, 10200.0, 10150.0, 10300.0],
            "return": [0.0, 0.01, 0.0099, -0.0049, 0.0148],
            "total_turnover": [0, 5000, 0, 3000, 0],
            "turnover": [0, 5000, 0, 3000, 0],
            "total_cost": [0, 10, 0, 6, 0],
            "cost": [0, 10, 0, 6, 0],
            "value": [10000, 10100, 10200, 10150, 10300],
            "cash": [0, 0, 0, 0, 0],
            "bench": [10000, 10050, 10100, 10080, 10120],
        })
        df.to_pickle(art_dir / "report_normal_1day.pkl")
        df.to_pickle(art_dir / "positions_normal_1day.pkl")

        # Set up paths
        monkeypatch.setattr(bdd, "ARTIFACTS_DIR", tmp_path / "artifacts")
        monkeypatch.setattr(bdd, "MLRUNS_DIR", mlruns_dir.parent)
        monkeypatch.setattr(bdd, "PROJECT_ROOT", tmp_path)

        db_path = tmp_path / "metadata.db"
        monkeypatch.setattr(bdd, "resolve_metadata_db_path", lambda _: db_path)

        _seed_metadata_db(db_path, model_id="us_model_20260205_144902",
                          run_id="a1cc0264861a4c898cc047c6002a6d4d",
                          market="us", created_at="2026-02-05")

        dash_path = tmp_path / "dashboard" / "dashboard_db.json"
        monkeypatch.setattr(bdd, "DASHBOARD_DB_PATH", dash_path)

        config_dir = tmp_path / "configs"
        config_dir.mkdir()
        (config_dir / "name_map.yaml").write_text("{}")
        monkeypatch.setattr(bdd, "CONFIG_DIR", config_dir)

        import qlib
        monkeypatch.setattr(qlib, "init", lambda **kw: None)
        monkeypatch.setattr(qlib.data.D, "features", lambda *a, **kw: _empty_qlib_df(), raising=False)

        bdd.build_db()

        dashboard = json.loads(dash_path.read_text())
        models = dashboard.get("models", [])
        assert len(models) >= 1
        model = next((m for m in models if m["id"] == "us_model_20260205_144902"), None)
        assert model is not None
        assert model["has_full_data"] is True
        assert model["source_layout"] == "mlruns"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_metadata_db(db_path: Path, model_id: str, run_id: str,
                      market: str, created_at: str, metrics_json: str = "{}"):
    """Create a minimal SQLite metadata DB matching the real model_versions schema."""
    import sqlite3
    import time

    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE IF NOT EXISTS model_versions (
        id TEXT PRIMARY KEY,
        tag TEXT,
        name TEXT,
        market TEXT,
        model_type TEXT,
        path TEXT,
        run_id TEXT,
        created_at TEXT,
        stage TEXT DEFAULT 'STAGING',
        description TEXT,
        params_json TEXT,
        metrics_json TEXT,
        feature_importance_json TEXT,
        payload_json TEXT,
        created_ts REAL
    )""")
    conn.execute(
        """INSERT OR REPLACE INTO model_versions
           (id, tag, name, market, model_type, path, run_id, created_at,
            stage, description, params_json, metrics_json,
            feature_importance_json, payload_json, created_ts)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            model_id,
            f"[{market.upper()}] {model_id}",
            f"[{market.upper()}] {model_id}",
            market,
            "LightGBM",
            "",
            run_id,
            created_at,
            "STAGING",
            "",
            '{"learning_rate": 0.05}',
            metrics_json,
            "{}",
            json.dumps({"id": model_id, "run_id": run_id}),
            time.time(),
        ),
    )
    conn.commit()
    conn.close()


def _empty_qlib_df():
    """Return an empty DataFrame with the expected MultiIndex structure."""
    import pandas as pd
    idx = pd.MultiIndex.from_tuples([], names=["instrument", "datetime"])
    return pd.DataFrame(index=idx)
