"""Tests for research artifacts (paths, schemas, safe writers) — exact contract."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.research.research_artifacts import (
    ARTIFACT_PATH_KEYS,
    EXPERIMENT_SPEC_FILENAME,
    FRONTEND_PAYLOAD_FILENAME,
    RUN_STATUS_FILENAME,
    SIGNALS_LATEST_COLUMNS,
    SIGNALS_LATEST_FILENAME,
    TOP_BOTTOM_SIGNALS_CSV_FILENAME,
    VALID_SIDES,
    ResearchRunPaths,
    build_frontend_payload,
    build_research_run_paths,
    build_research_signals_payload,
    research_run_dir,
    resolve_run_dir,
    write_frontend_payload,
    write_json,
    write_json_safe,
    write_run_status,
    write_skipped_run,
    write_top_bottom_csv,
    write_top_bottom_signals_csv,
)


# ── Standard filenames (exact contract) ───────────────────────────────────────


class TestStandardFilenames:
    def test_experiment_spec_filename(self) -> None:
        assert EXPERIMENT_SPEC_FILENAME == "experiment_spec.json"

    def test_run_status_filename(self) -> None:
        assert RUN_STATUS_FILENAME == "run_status.json"

    def test_frontend_payload_filename(self) -> None:
        assert FRONTEND_PAYLOAD_FILENAME == "frontend_payload.json"

    def test_signals_latest_filename(self) -> None:
        assert SIGNALS_LATEST_FILENAME == "signals_latest.json"

    def test_top_bottom_signals_csv_filename(self) -> None:
        assert TOP_BOTTOM_SIGNALS_CSV_FILENAME == "top_bottom_signals.csv"


# ── ARTIFACT_PATH_KEYS (exact contract) ──────────────────────────────────────


class TestArtifactPathKeys:
    def test_all_14_standard_keys(self) -> None:
        expected = (
            "experiment_spec",
            "run_status",
            "data_readiness",
            "universe_report",
            "factor_manifest",
            "candidate_manifest",
            "walk_forward_windows",
            "walk_forward_stability",
            "model_decision_pack",
            "model_decision_markdown",
            "signals_latest",
            "top_bottom_signals_csv",
            "metrics_summary",
            "frontend_payload",
        )
        assert ARTIFACT_PATH_KEYS == expected

    def test_no_old_keys(self) -> None:
        """Old keys like spec_copy, research_signals, top_bottom must NOT exist."""
        assert "spec_copy" not in ARTIFACT_PATH_KEYS
        assert "research_signals" not in ARTIFACT_PATH_KEYS
        assert "top_bottom" not in ARTIFACT_PATH_KEYS


# ── VALID_SIDES ──────────────────────────────────────────────────────────────


class TestValidSides:
    def test_only_top_and_bottom(self) -> None:
        assert VALID_SIDES == {"top", "bottom"}


# ── SIGNALS_LATEST_COLUMNS (exact contract) ──────────────────────────────────


class TestSignalsLatestColumns:
    def test_exact_columns(self) -> None:
        expected = (
            "as_of_date",
            "market",
            "experiment_id",
            "symbol",
            "side",
            "rank",
            "score",
            "candidate_name",
            "orientation",
            "holding_horizon_days",
            "research_only",
            "trade_ready",
        )
        assert SIGNALS_LATEST_COLUMNS == expected

    def test_no_forbidden_columns(self) -> None:
        forbidden = {"buy", "sell", "order", "execution", "trade_signal", "position"}
        assert set(SIGNALS_LATEST_COLUMNS).isdisjoint(forbidden)


# ── ResearchRunPaths ─────────────────────────────────────────────────────────


class TestResearchRunPaths:
    def test_construction_root(self) -> None:
        paths = ResearchRunPaths(Path("/tmp/runs/exp123"))
        assert paths.root == Path("/tmp/runs/exp123")
        assert paths.run_dir == Path("/tmp/runs/exp123")  # compatibility

    def test_all_property_paths(self) -> None:
        paths = ResearchRunPaths(Path("/tmp/runs/exp"))
        assert paths.experiment_spec == Path("/tmp/runs/exp/experiment_spec.json")
        assert paths.run_status == Path("/tmp/runs/exp/run_status.json")
        assert paths.data_readiness == Path("/tmp/runs/exp/data_readiness.json")
        assert paths.universe_report == Path("/tmp/runs/exp/universe_report.json")
        assert paths.factor_manifest == Path("/tmp/runs/exp/factor_manifest.json")
        assert paths.candidate_manifest == Path("/tmp/runs/exp/candidate_manifest.json")
        assert paths.walk_forward_windows == Path("/tmp/runs/exp/walk_forward_windows.json")
        assert paths.walk_forward_stability == Path("/tmp/runs/exp/walk_forward_stability.json")
        assert paths.model_decision_pack == Path("/tmp/runs/exp/model_decision_pack.json")
        assert paths.model_decision_markdown == Path("/tmp/runs/exp/model_decision_pack.md")
        assert paths.signals_latest == Path("/tmp/runs/exp/signals_latest.json")
        assert paths.top_bottom_signals_csv == Path("/tmp/runs/exp/top_bottom_signals.csv")
        assert paths.metrics_summary == Path("/tmp/runs/exp/metrics_summary.json")
        assert paths.frontend_payload == Path("/tmp/runs/exp/frontend_payload.json")

    def test_frozen(self) -> None:
        paths = ResearchRunPaths(Path("/tmp"))
        with pytest.raises(Exception):
            paths.root = Path("/other")  # type: ignore[misc]

    def test_ensure_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ResearchRunPaths(Path(tmp) / "subdir")
            assert not paths.root.exists()
            paths.ensure_dir()
            assert paths.root.is_dir()

    def test_artifact_paths_all_keys(self) -> None:
        paths = ResearchRunPaths(Path("/tmp/runs/exp"))
        ap = paths.artifact_paths()
        for key in ARTIFACT_PATH_KEYS:
            assert key in ap, f"Missing artifact path key: {key}"

    def test_artifact_paths_are_strings(self) -> None:
        """artifact_paths() must return serializable strings, not Path objects."""
        paths = ResearchRunPaths(Path("/tmp/runs/exp"))
        ap = paths.artifact_paths()
        for key, val in ap.items():
            assert isinstance(val, str), (
                f"artifact_paths['{key}'] is {type(val).__name__}, expected str"
            )

    def test_no_old_property_names(self) -> None:
        """Old property names (spec_copy, research_signals, top_bottom) must not exist."""
        paths = ResearchRunPaths(Path("/tmp/runs/exp"))
        assert not hasattr(paths, "spec_copy") or not callable(
            getattr(type(paths), "spec_copy", None)
        )
        # signals_latest replaces research_signals
        # top_bottom_signals_csv replaces top_bottom


# ── Path resolution ──────────────────────────────────────────────────────────


class TestResearchRunDir:
    def test_root_based(self) -> None:
        result = research_run_dir(Path("/root"), "exp1")
        assert result == Path("/root/artifacts/research_runs/exp1")

    def test_none_root_falls_back_to_cwd(self) -> None:
        result = research_run_dir(None, "exp1")
        assert result == Path.cwd() / "artifacts" / "research_runs" / "exp1"


class TestBuildResearchRunPaths:
    def test_build(self) -> None:
        paths = build_research_run_paths(Path("/root"), "exp1")
        assert isinstance(paths, ResearchRunPaths)
        assert paths.root == Path("/root/artifacts/research_runs/exp1")
        assert paths.run_status.name == "run_status.json"
        assert paths.frontend_payload.name == "frontend_payload.json"
        assert paths.experiment_spec.name == "experiment_spec.json"

    def test_build_with_output_dir(self) -> None:
        paths = build_research_run_paths(None, "exp1", output_dir="/custom")
        assert isinstance(paths, ResearchRunPaths)
        assert paths.root == Path("/custom/exp1")
        assert paths.run_status.name == "run_status.json"


class TestResolveRunDir:
    def test_explicit_output_dir(self) -> None:
        result = resolve_run_dir("exp1", root="/root", output_dir="/custom")
        assert result == Path("/custom/exp1")

    def test_root_based(self) -> None:
        result = resolve_run_dir("exp1", root="/root")
        assert result == Path("/root/artifacts/research_runs/exp1")

    def test_cwd_fallback(self) -> None:
        result = resolve_run_dir("exp1")
        assert result == Path.cwd() / "artifacts" / "research_runs" / "exp1"


# ── Safe JSON writer ─────────────────────────────────────────────────────────


class TestWriteJson:
    def test_writes_and_reads_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "test.json"
            write_json(p, {"a": 1, "b": [2, 3]})
            assert p.exists()
            data = json.loads(p.read_text(encoding="utf-8"))
            assert data == {"a": 1, "b": [2, 3]}

    def test_creates_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "deep" / "nested" / "test.json"
            write_json(p, {"x": "y"})
            assert p.exists()

    def test_compat_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "compat.json"
            write_json_safe(p, {"k": "v"})
            assert p.exists()
            data = json.loads(p.read_text(encoding="utf-8"))
            assert data == {"k": "v"}


# ── Run status (exact contract) ──────────────────────────────────────────────


class TestWriteRunStatus:
    def test_writes_status_exact_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ResearchRunPaths(Path(tmp))
            payload = write_run_status(paths, experiment_id="exp1", status="running")
            assert payload["schema_version"] == "1.0"
            assert payload["experiment_id"] == "exp1"
            assert payload["status"] == "running"
            assert payload["failed_stage"] == ""
            assert payload["reason"] == ""
            assert payload["research_only"] is True
            assert payload["trade_ready"] is False
            # On disk
            saved = json.loads(paths.run_status.read_text(encoding="utf-8"))
            assert saved["experiment_id"] == "exp1"
            assert saved["research_only"] is True
            assert saved["trade_ready"] is False

    def test_writes_failed_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ResearchRunPaths(Path(tmp))
            payload = write_run_status(
                paths, experiment_id="e", status="failed",
                failed_stage="data_readiness", reason="no data",
            )
            assert payload["failed_stage"] == "data_readiness"
            assert payload["reason"] == "no data"

    def test_trade_ready_defaults_false(self) -> None:
        """Status writer defaults trade_ready to False unless explicitly supplied."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = ResearchRunPaths(Path(tmp))
            payload = write_run_status(paths, experiment_id="e", status="ok")
            assert payload["trade_ready"] is False

    def test_trade_ready_explicit_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ResearchRunPaths(Path(tmp))
            payload = write_run_status(
                paths, experiment_id="e", status="ok", trade_ready=True,
            )
            assert payload["trade_ready"] is True

    def test_extra_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ResearchRunPaths(Path(tmp))
            payload = write_run_status(
                paths, experiment_id="e", status="ok", extra={"custom": 42}
            )
            assert payload["custom"] == 42


# ── Frontend payload (exact contract) ────────────────────────────────────────


class TestBuildFrontendPayload:
    def test_exact_minimum_keys(self) -> None:
        payload = build_frontend_payload(
            "exp1", market="cn", benchmark="000300",
        )
        expected_keys = {
            "schema_version", "experiment_id", "market", "benchmark",
            "run_status", "decision_status", "trade_ready", "research_only",
            "metrics", "gates", "readiness",
            "top_signals", "bottom_signals", "windows",
            "artifact_paths",
        }
        assert set(payload.keys()) == expected_keys

    def test_basic_values(self) -> None:
        payload = build_frontend_payload(
            "exp1", market="cn", benchmark="000300",
            run_status="ok",
        )
        assert payload["schema_version"] == "1.0"
        assert payload["experiment_id"] == "exp1"
        assert payload["market"] == "cn"
        assert payload["benchmark"] == "000300"
        assert payload["run_status"] == "ok"
        assert payload["decision_status"] == ""
        assert payload["trade_ready"] is False
        assert payload["research_only"] is True

    def test_research_only_always_true(self) -> None:
        """research_only must always be True regardless of inputs."""
        payload = build_frontend_payload("e", market="cn", benchmark="b")
        assert payload["research_only"] is True

    def test_trade_ready_defaults_false(self) -> None:
        payload = build_frontend_payload("e", market="cn", benchmark="b")
        assert payload["trade_ready"] is False

    def test_trade_ready_explicit_true(self) -> None:
        payload = build_frontend_payload(
            "e", market="cn", benchmark="b", trade_ready=True,
        )
        assert payload["trade_ready"] is True

    def test_default_empty_collections(self) -> None:
        payload = build_frontend_payload("e", market="cn", benchmark="b")
        assert payload["metrics"] == {}
        assert payload["gates"] == {}
        assert payload["readiness"] == {}
        assert payload["top_signals"] == []
        assert payload["bottom_signals"] == []
        assert payload["windows"] == []
        assert payload["artifact_paths"] == {}

    def test_artifact_paths_as_strings(self) -> None:
        paths = ResearchRunPaths(Path("/tmp/runs/exp"))
        payload = build_frontend_payload(
            "exp1", market="cn", benchmark="b",
            artifact_paths=paths.artifact_paths(),
        )
        ap = payload["artifact_paths"]
        for key in ARTIFACT_PATH_KEYS:
            assert key in ap, f"Missing artifact_paths key: {key}"
            assert isinstance(ap[key], str), (
                f"artifact_paths['{key}'] is {type(ap[key]).__name__}, expected str"
            )

    def test_metadata_nested_not_flat(self) -> None:
        """Extra metadata must be nested under 'metadata', not top-level."""
        payload = build_frontend_payload(
            "e", market="cn", benchmark="b",
            metadata={"dry_run": True, "runner": "test"},
        )
        assert "metadata" in payload
        assert payload["metadata"] == {"dry_run": True, "runner": "test"}
        # Must NOT be at top level
        assert "dry_run" not in payload or "dry_run" not in {
            k for k in payload if payload.get("dry_run")
        }
        # Verify these are NOT top-level keys
        assert "runner" not in payload

    def test_no_forbidden_keys(self) -> None:
        """Frontend payload must not contain buy/sell/order/execution keys."""
        payload = build_frontend_payload(
            "exp1", market="us", benchmark="QQQ",
        )
        forbidden = {"buy", "sell", "order", "execution", "trade_signal", "position"}
        keys = set(payload.keys())
        assert keys.isdisjoint(forbidden), f"Forbidden keys found: {keys & forbidden}"


class TestWriteFrontendPayload:
    def test_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ResearchRunPaths(Path(tmp))
            payload = build_frontend_payload("e", market="cn", benchmark="000300")
            write_frontend_payload(paths, payload)
            assert paths.frontend_payload.exists()


# ── Skipped run ──────────────────────────────────────────────────────────────


class TestWriteSkippedRun:
    def test_writes_both_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ResearchRunPaths(Path(tmp))
            result = write_skipped_run(
                paths, experiment_id="skip1", reason="no data",
                market="cn", benchmark="000300",
            )
            assert paths.run_status.exists()
            assert paths.frontend_payload.exists()
            assert result["status"] == "skipped"
            assert result["research_only"] is True

            frontend = json.loads(paths.frontend_payload.read_text(encoding="utf-8"))
            assert frontend["run_status"] == "skipped"
            assert frontend["metadata"]["skip_reason"] == "no data"

    def test_run_status_has_required_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ResearchRunPaths(Path(tmp))
            write_skipped_run(
                paths, experiment_id="skip1", reason="no data",
            )
            status = json.loads(paths.run_status.read_text(encoding="utf-8"))
            assert "schema_version" in status
            assert "experiment_id" in status
            assert "failed_stage" in status
            assert "research_only" in status
            assert "trade_ready" in status


# ── Top-bottom signals CSV (exact contract) ──────────────────────────────────


class TestTopBottomSignalsCSV:
    def test_writes_standard_columns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ResearchRunPaths(Path(tmp))
            rows = [
                {
                    "as_of_date": "2024-01-01",
                    "market": "cn",
                    "experiment_id": "exp1",
                    "symbol": "000001",
                    "side": "top",
                    "rank": 1,
                    "score": 0.95,
                    "candidate_name": "test",
                    "orientation": "long",
                    "holding_horizon_days": 10,
                    "research_only": True,
                    "trade_ready": False,
                }
            ]
            write_top_bottom_signals_csv(paths, rows)
            assert paths.top_bottom_signals_csv.exists()
            content = paths.top_bottom_signals_csv.read_text(encoding="utf-8")
            for col in SIGNALS_LATEST_COLUMNS:
                assert col in content, f"Missing column '{col}' in CSV header"

    def test_writes_header_when_empty(self) -> None:
        """Must write header even when rows is empty."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = ResearchRunPaths(Path(tmp))
            write_top_bottom_signals_csv(paths, [])
            assert paths.top_bottom_signals_csv.exists()
            content = paths.top_bottom_signals_csv.read_text(encoding="utf-8")
            assert "as_of_date" in content
            assert "side" in content
            assert "research_only" in content

    def test_rejects_invalid_side(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ResearchRunPaths(Path(tmp))
            rows = [{"side": "buy", "symbol": "X"}]
            with pytest.raises(ValueError, match="Invalid side"):
                write_top_bottom_signals_csv(paths, rows)

    def test_forces_research_only_true(self) -> None:
        """research_only must be True in output regardless of input."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = ResearchRunPaths(Path(tmp))
            rows = [{"side": "top", "symbol": "X", "research_only": False}]
            write_top_bottom_signals_csv(paths, rows)
            content = paths.top_bottom_signals_csv.read_text(encoding="utf-8").splitlines()
            # Find the row after header
            assert len(content) >= 2
            values = content[1].split(",")
            # research_only is the 11th column (0-indexed: 10)
            assert values[10] == "True"

    def test_no_forbidden_columns(self) -> None:
        forbidden = {"buy", "sell", "order", "execution", "position", "trade_signal"}
        assert set(SIGNALS_LATEST_COLUMNS).isdisjoint(forbidden)

    def test_compat_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ResearchRunPaths(Path(tmp))
            rows = [{"side": "top", "symbol": "X"}]
            write_top_bottom_csv(paths, rows)
            assert paths.top_bottom_signals_csv.exists()


# ── Research signals payload builder (exact contract) ────────────────────────


class TestBuildResearchSignalsPayload:
    def test_builds_with_exact_columns(self) -> None:
        rows = [
            {
                "date": "2024-01-01",
                "symbol": "A",
                "score": 0.9,
                "rank": 1,
                "side": "top",
                "candidate_name": "c1",
                "extra": "drop",
            }
        ]
        result = build_research_signals_payload(rows, market="cn", experiment_id="exp1")
        assert len(result) == 1
        assert set(result[0].keys()) == set(SIGNALS_LATEST_COLUMNS)
        assert "extra" not in result[0]

    def test_forces_research_only_true(self) -> None:
        rows = [{"side": "top", "symbol": "A"}]
        result = build_research_signals_payload(rows)
        assert result[0]["research_only"] is True

    def test_trade_ready_defaults_false(self) -> None:
        rows = [{"side": "top", "symbol": "A"}]
        result = build_research_signals_payload(rows)
        assert result[0]["trade_ready"] is False

    def test_trade_ready_from_decision_pack(self) -> None:
        rows = [{"side": "top", "symbol": "A", "trade_ready": True}]
        result = build_research_signals_payload(rows, trade_ready=True)
        assert result[0]["trade_ready"] is True

    def test_maps_date_to_as_of_date(self) -> None:
        rows = [{"date": "2025-07-01", "side": "top", "symbol": "A"}]
        result = build_research_signals_payload(rows)
        assert result[0]["as_of_date"] == "2025-07-01"

    def test_rejects_invalid_side(self) -> None:
        rows = [{"side": "buy", "symbol": "A"}]
        with pytest.raises(ValueError, match="Invalid side"):
            build_research_signals_payload(rows)

    def test_fills_missing_fields(self) -> None:
        rows = [{"side": "top", "symbol": "A"}]
        result = build_research_signals_payload(
            rows, market="cn", experiment_id="e1",
            candidate_name="c1", orientation="long",
            holding_horizon_days=10,
        )
        r = result[0]
        assert r["market"] == "cn"
        assert r["experiment_id"] == "e1"
        assert r["candidate_name"] == "c1"
        assert r["orientation"] == "long"
        assert r["holding_horizon_days"] == 10
        assert r["rank"] == 0
        assert r["score"] == 0.0

    def test_no_forbidden_columns(self) -> None:
        forbidden = {"buy", "sell", "order", "execution", "position", "trade_signal"}
        assert set(SIGNALS_LATEST_COLUMNS).isdisjoint(forbidden)
