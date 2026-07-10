"""Tests for research paradigm spec, validation, and Qlib-free dry-run."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR
from src.research.paradigm import (
    PARADIGM_SCHEMA_VERSION,
    ResearchParadigmSpec,
    build_factor_baselines_from_spec,
    build_ranker_candidates_from_spec,
    dry_run_paradigm,
    execute_paradigm,
    load_research_paradigm_spec,
    run_research_paradigm,
    validate_research_paradigm_spec,
    _resolve_relative_path,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

MINIMAL_PARADIGM_YAML = """\
schema_version: "1.0"
experiment_id: "test_minimal"
market: "cn"
benchmark: "000300"

universe:
  source: "configs/watchlist.yaml"
  market_key: "cn"
  min_symbols: 50
  alignment_mode: "auto"

factor_library:
  source: "configs/factor_libraries/cn_ohlcv.yaml"
  groups:
    - "cn_balanced_ohlcv"

candidate_grid:
  ranker:
    calibrations:
      - n_gain_bins: 3
        num_boost_round: 100
        num_leaves: 15
        min_data_in_leaf: 10
  factor_baselines:
    - "factor:cn_momentum_10d"

strategy:
  horizon_days: 10
  holding_days: 10
  rebalance_days: 10
  top_n: 15
  bottom_n: 15
  return_expression: "Ref($close, -10) / $close - 1"
  return_provenance: "raw_forward_return"
  research_only: true

walk_forward:
  first_test_year: 2024
  last_test_year: 2026
  min_windows: 3
  train_embargo_sessions: 10

evaluation:
  benchmark_mode: "reference_only"
  metrics:
    - "mean_icir"
    - "mean_rank_ic"
    - "mean_spread"
    - "worst_drawdown"
    - "ready_ratio"
    - "positive_icir_ratio"
    - "positive_spread_ratio"
  gates:
    mean_icir: 0.30
    worst_drawdown: -0.15
    ready_ratio: 0.75

outputs:
  write_readiness: true
  write_factor_manifest: true
  write_candidate_manifest: true
  write_walk_forward_stability: true
  write_decision_pack: true
  write_top_bottom_signals: true
  write_frontend_payload: true
"""


def _write_temp_yaml(content: str) -> Path:
    """Write YAML content to a temp file and return its path."""
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, dir=Path.cwd()
    )
    f.write(content)
    f.close()
    return Path(f.name)


# ── Validation function ──────────────────────────────────────────────────────


class TestValidateResearchParadigmSpec:
    def test_valid_minimal_passes(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        spec = ResearchParadigmSpec.from_dict(data, spec_path=str(Path.cwd()))
        validate_research_paradigm_spec(spec)

    def test_missing_schema_version_raises(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["schema_version"] = "99.0"
        spec = ResearchParadigmSpec.from_dict(data)
        with pytest.raises(ValueError, match="Unsupported paradigm schema_version"):
            validate_research_paradigm_spec(spec)

    def test_missing_experiment_id_raises(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["experiment_id"] = ""
        spec = ResearchParadigmSpec.from_dict(data)
        with pytest.raises(ValueError, match="experiment_id must be non-empty"):
            validate_research_paradigm_spec(spec)

    def test_missing_alignment_raises(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["universe"]["alignment_mode"] = "bad"
        spec = ResearchParadigmSpec.from_dict(data)
        with pytest.raises(ValueError, match="alignment_mode must be 'strict' or 'auto'"):
            validate_research_paradigm_spec(spec)

    def test_missing_source_raises(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["universe"]["source"] = "nonexistent/file.yaml"
        spec = ResearchParadigmSpec.from_dict(data, spec_path=str(Path.cwd()))
        with pytest.raises(FileNotFoundError, match="not found"):
            validate_research_paradigm_spec(spec)

    def test_missing_factor_library_source_raises(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["factor_library"]["source"] = "nonexistent/lib.yaml"
        spec = ResearchParadigmSpec.from_dict(data, spec_path=str(Path.cwd()))
        with pytest.raises(FileNotFoundError, match="not found"):
            validate_research_paradigm_spec(spec)

    def test_missing_group_rejected(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["factor_library"]["groups"] = []
        spec = ResearchParadigmSpec.from_dict(data)
        with pytest.raises(ValueError, match="factor_library.groups must be a non-empty list"):
            validate_research_paradigm_spec(spec)

    def test_horizon_not_10_raises(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["strategy"]["horizon_days"] = 5
        spec = ResearchParadigmSpec.from_dict(data)
        with pytest.raises(ValueError, match="horizon_days must be 10"):
            validate_research_paradigm_spec(spec)

    def test_holding_not_10_raises(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["strategy"]["holding_days"] = 5
        spec = ResearchParadigmSpec.from_dict(data)
        with pytest.raises(ValueError, match="holding_days must be 10"):
            validate_research_paradigm_spec(spec)

    def test_wrong_return_expression_raises(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["strategy"]["return_expression"] = "wrong"
        spec = ResearchParadigmSpec.from_dict(data)
        with pytest.raises(ValueError, match="return_expression must be canonical"):
            validate_research_paradigm_spec(spec)

    def test_wrong_provenance_raises(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["strategy"]["return_provenance"] = "other"
        spec = ResearchParadigmSpec.from_dict(data)
        with pytest.raises(ValueError, match="return_provenance must be 'raw_forward_return'"):
            validate_research_paradigm_spec(spec)

    def test_research_only_false_raises(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["strategy"]["research_only"] = False
        spec = ResearchParadigmSpec.from_dict(data)
        with pytest.raises(ValueError, match="research_only must be True"):
            validate_research_paradigm_spec(spec)

    def test_min_windows_below_3_raises(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["walk_forward"]["min_windows"] = 1
        spec = ResearchParadigmSpec.from_dict(data)
        with pytest.raises(ValueError, match="min_windows must be >= 3"):
            validate_research_paradigm_spec(spec)

    def test_embargo_not_10_raises(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["walk_forward"]["train_embargo_sessions"] = 5
        spec = ResearchParadigmSpec.from_dict(data)
        with pytest.raises(ValueError, match="train_embargo_sessions must be 10"):
            validate_research_paradigm_spec(spec)

    def test_lowered_icir_rejected(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["evaluation"]["gates"]["mean_icir"] = 0.10
        spec = ResearchParadigmSpec.from_dict(data)
        with pytest.raises(ValueError, match="mean_icir must be >= 0.30"):
            validate_research_paradigm_spec(spec)

    def test_lowered_drawdown_rejected(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["evaluation"]["gates"]["worst_drawdown"] = -0.20
        spec = ResearchParadigmSpec.from_dict(data)
        with pytest.raises(ValueError, match="worst_drawdown must be >= -0.15"):
            validate_research_paradigm_spec(spec)

    def test_stricter_drawdown_passes(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["evaluation"]["gates"]["worst_drawdown"] = -0.10
        spec = ResearchParadigmSpec.from_dict(data, spec_path=str(Path.cwd()))
        validate_research_paradigm_spec(spec)

    def test_lowered_ready_ratio_rejected(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["evaluation"]["gates"]["ready_ratio"] = 0.50
        spec = ResearchParadigmSpec.from_dict(data)
        with pytest.raises(ValueError, match="ready_ratio must be >= 0.75"):
            validate_research_paradigm_spec(spec)

    def test_stricter_ready_ratio_passes(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["evaluation"]["gates"]["ready_ratio"] = 0.85
        spec = ResearchParadigmSpec.from_dict(data, spec_path=str(Path.cwd()))
        validate_research_paradigm_spec(spec)

    def test_stricter_icir_passes(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["evaluation"]["gates"]["mean_icir"] = 0.35
        spec = ResearchParadigmSpec.from_dict(data, spec_path=str(Path.cwd()))
        validate_research_paradigm_spec(spec)

    def test_missing_write_frontend_payload_raises(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["outputs"]["write_frontend_payload"] = False
        spec = ResearchParadigmSpec.from_dict(data)
        with pytest.raises(ValueError, match="write_frontend_payload must be True"):
            validate_research_paradigm_spec(spec)

    def test_market_must_be_cn_or_us(self) -> None:
        import yaml
        data = yaml.safe_load(MINIMAL_PARADIGM_YAML)
        data["market"] = "hk"
        spec = ResearchParadigmSpec.from_dict(data)
        with pytest.raises(ValueError, match="market must be 'cn' or 'us'"):
            validate_research_paradigm_spec(spec)


# ── ResearchParadigmSpec ─────────────────────────────────────────────────────


class TestResearchParadigmSpecFromYaml:
    def test_load_minimal(self) -> None:
        tmp = _write_temp_yaml(MINIMAL_PARADIGM_YAML)
        try:
            spec = ResearchParadigmSpec.from_yaml(tmp)
            assert spec.schema_version == "1.0"
            assert spec.experiment_id == "test_minimal"
            assert spec.market == "cn"
            assert spec.benchmark == "000300"
            assert spec.universe["min_symbols"] == 50
            assert spec.universe["alignment_mode"] == "auto"
            assert spec.strategy["horizon_days"] == 10
            assert spec.strategy["top_n"] == 15
            assert spec.strategy["bottom_n"] == 15
            assert spec.strategy["return_provenance"] == "raw_forward_return"
            assert spec.strategy["research_only"] is True
            assert spec.walk_forward["min_windows"] == 3
            assert spec.walk_forward["train_embargo_sessions"] == 10
            assert len(spec.factor_library["groups"]) == 1
            assert spec.factor_library["groups"][0] == "cn_balanced_ohlcv"
            assert spec.outputs["write_frontend_payload"] is True
            assert spec.evaluation["benchmark_mode"] == "reference_only"
            assert len(spec.evaluation["metrics"]) == 7
        finally:
            tmp.unlink()

    def test_file_not_found(self) -> None:
        with pytest.raises(FileNotFoundError):
            ResearchParadigmSpec.from_yaml("/nonexistent/path.yaml")

    def test_invalid_schema_raises(self) -> None:
        yaml_content = MINIMAL_PARADIGM_YAML.replace(
            'schema_version: "1.0"', 'schema_version: "99.0"'
        )
        tmp = _write_temp_yaml(yaml_content)
        try:
            with pytest.raises(ValueError, match="Unsupported paradigm schema_version"):
                ResearchParadigmSpec.from_yaml(tmp)
        finally:
            tmp.unlink()

    def test_exact_top_level_keys_preserved(self) -> None:
        tmp = _write_temp_yaml(MINIMAL_PARADIGM_YAML)
        try:
            spec = ResearchParadigmSpec.from_yaml(tmp)
            d = spec.to_dict()
            expected_keys = {
                "schema_version", "experiment_id", "market", "benchmark",
                "universe", "factor_library", "candidate_grid",
                "strategy", "walk_forward", "evaluation", "outputs",
            }
            assert set(d.keys()) == expected_keys
        finally:
            tmp.unlink()


class TestResearchParadigmSpecToDict:
    def test_roundtrip_info(self) -> None:
        tmp = _write_temp_yaml(MINIMAL_PARADIGM_YAML)
        try:
            spec = ResearchParadigmSpec.from_yaml(tmp)
            d = spec.to_dict()
            assert d["schema_version"] == PARADIGM_SCHEMA_VERSION
            assert d["market"] == "cn"
            assert d["experiment_id"] == "test_minimal"
            assert d["strategy"]["research_only"] is True
            assert isinstance(d["candidate_grid"], dict)
            assert isinstance(d["evaluation"], dict)
            assert isinstance(d["outputs"], dict)
            assert d["universe"]["min_symbols"] == 50
            assert d["universe"]["alignment_mode"] == "auto"
            assert d["strategy"]["return_provenance"] == "raw_forward_return"
            assert d["strategy"]["return_expression"] == CANONICAL_10D_RETURN_EXPR
            assert d["evaluation"]["benchmark_mode"] == "reference_only"
            assert len(d["evaluation"]["metrics"]) == 7
        finally:
            tmp.unlink()


# ── Dry run (Qlib-free) ──────────────────────────────────────────────────────


class TestDryRunParadigm:
    def test_dry_run_succeeds(self) -> None:
        """Dry-run must not import or initialize Qlib."""
        tmp = _write_temp_yaml(MINIMAL_PARADIGM_YAML)
        try:
            spec = ResearchParadigmSpec.from_yaml(tmp)
            with tempfile.TemporaryDirectory() as out_dir:
                result = dry_run_paradigm(spec, output_dir=out_dir)
                assert result["status"] == "dry_run_complete"
                assert "n_factors" in result
                assert "n_groups" in result
                assert "n_candidates" in result

                run_dir = Path(result["run_dir"])
                assert run_dir.is_dir()
                assert run_dir.parent == Path(out_dir)
                assert run_dir.name == spec.experiment_id
                # Standard artifacts
                assert (run_dir / "experiment_spec.json").exists()
                assert (run_dir / "run_status.json").exists()
                assert (run_dir / "frontend_payload.json").exists()
                assert (run_dir / "factor_manifest.json").exists()
                assert (run_dir / "candidate_manifest.json").exists()
                assert (run_dir / "signals_latest.json").exists()
                assert (run_dir / "top_bottom_signals.csv").exists()
                # Old filename must not exist
                assert not (run_dir / "paradigm_spec.json").exists()
                # No fake readiness/stability/metrics evidence
                assert not (run_dir / "data_readiness.json").exists()
                assert not (run_dir / "walk_forward_stability.json").exists()
                assert not (run_dir / "walk_forward_windows.json").exists()
                assert not (run_dir / "metrics_summary.json").exists()
                assert not (run_dir / "model_decision_pack.json").exists()
        finally:
            tmp.unlink()

    def test_dry_run_writes_frontend_payload(self) -> None:
        tmp = _write_temp_yaml(MINIMAL_PARADIGM_YAML)
        try:
            spec = ResearchParadigmSpec.from_yaml(tmp)
            with tempfile.TemporaryDirectory() as out_dir:
                result = dry_run_paradigm(spec, output_dir=out_dir)
                run_dir = Path(result["run_dir"])
                frontend = json.loads((run_dir / "frontend_payload.json").read_text(encoding="utf-8"))
                # Exact minimum keys
                assert "schema_version" in frontend
                assert "experiment_id" in frontend
                assert "market" in frontend
                assert "benchmark" in frontend
                assert "run_status" in frontend
                assert "decision_status" in frontend
                assert "trade_ready" in frontend
                assert "research_only" in frontend
                assert "metrics" in frontend
                assert "gates" in frontend
                assert "readiness" in frontend
                assert "top_signals" in frontend
                assert "bottom_signals" in frontend
                assert "windows" in frontend
                assert "artifact_paths" in frontend
                # Values
                assert frontend["research_only"] is True
                assert frontend["trade_ready"] is False
                assert frontend["run_status"] == "dry_run_complete"
                # Metadata nested, not flat
                assert "metadata" in frontend
                assert frontend["metadata"]["dry_run"] is True
                # artifact_paths are strings
                ap = frontend["artifact_paths"]
                for key in ["experiment_spec", "run_status", "frontend_payload",
                            "factor_manifest", "candidate_manifest"]:
                    assert key in ap
                    assert isinstance(ap[key], str)
        finally:
            tmp.unlink()

    def test_dry_run_writes_experiment_spec(self) -> None:
        tmp = _write_temp_yaml(MINIMAL_PARADIGM_YAML)
        try:
            spec = ResearchParadigmSpec.from_yaml(tmp)
            with tempfile.TemporaryDirectory() as out_dir:
                result = dry_run_paradigm(spec, output_dir=out_dir)
                run_dir = Path(result["run_dir"])
                spec_data = json.loads((run_dir / "experiment_spec.json").read_text(encoding="utf-8"))
                assert spec_data["market"] == "cn"
                assert spec_data["experiment_id"] == spec.experiment_id
        finally:
            tmp.unlink()

    def test_dry_run_no_qlib_import(self) -> None:
        """Verify dry_run does not cause qlib to be imported."""
        tmp = _write_temp_yaml(MINIMAL_PARADIGM_YAML)
        try:
            spec = ResearchParadigmSpec.from_yaml(tmp)
            with tempfile.TemporaryDirectory() as out_dir:
                result = dry_run_paradigm(spec, output_dir=out_dir)
                assert result["status"] == "dry_run_complete"
                run_dir = Path(result["run_dir"])
                # Verify signals artifacts are written
                assert (run_dir / "signals_latest.json").exists()
                assert (run_dir / "top_bottom_signals.csv").exists()
                # CSV header exists even when empty
                csv_content = (run_dir / "top_bottom_signals.csv").read_text(encoding="utf-8")
                assert "as_of_date" in csv_content
        finally:
            tmp.unlink()


# ── Notebook API ─────────────────────────────────────────────────────────────


class TestNotebookAPI:
    def test_load_research_paradigm_spec(self) -> None:
        """load_research_paradigm_spec is the notebook-friendly loader."""
        tmp = _write_temp_yaml(MINIMAL_PARADIGM_YAML)
        try:
            spec = load_research_paradigm_spec(str(tmp))
            assert isinstance(spec, ResearchParadigmSpec)
            assert spec.market == "cn"
        finally:
            tmp.unlink()

    def test_run_research_paradigm_dry_run(self) -> None:
        """run_research_paradigm with dry_run=True works."""
        tmp = _write_temp_yaml(MINIMAL_PARADIGM_YAML)
        try:
            spec = load_research_paradigm_spec(str(tmp))
            with tempfile.TemporaryDirectory() as out_dir:
                result = run_research_paradigm(
                    spec, dry_run=True, output_dir=out_dir
                )
                assert result["status"] == "dry_run_complete"
        finally:
            tmp.unlink()

    def test_run_research_paradigm_no_mode_fails(self) -> None:
        """run_research_paradigm without dry_run or execution_mode fails closed."""
        tmp = _write_temp_yaml(MINIMAL_PARADIGM_YAML)
        try:
            spec = load_research_paradigm_spec(str(tmp))
            with pytest.raises(ValueError, match="requires dry_run=True"):
                run_research_paradigm(spec)
        finally:
            tmp.unlink()

    def test_run_research_paradigm_with_execution_mode(self) -> None:
        """run_research_paradigm with execution_mode works."""
        tmp = _write_temp_yaml(MINIMAL_PARADIGM_YAML)
        try:
            spec = load_research_paradigm_spec(str(tmp))
            with tempfile.TemporaryDirectory() as out_dir:
                result = run_research_paradigm(
                    spec, execution_mode="cn", output_dir=out_dir
                )
                # Will be "skipped" because the CN runner needs real data
                assert "status" in result
                assert "run_dir" in result
        finally:
            tmp.unlink()


# ── Execute paradigm fail-closed ─────────────────────────────────────────────


class TestExecuteParadigmFailClosed:
    def test_no_execution_mode_fails(self) -> None:
        tmp = _write_temp_yaml(MINIMAL_PARADIGM_YAML)
        try:
            spec = ResearchParadigmSpec.from_yaml(tmp)
            with pytest.raises(ValueError, match="requires an explicit execution_mode"):
                execute_paradigm(spec)
        finally:
            tmp.unlink()

    def test_unsupported_runner_fails(self) -> None:
        tmp = _write_temp_yaml(MINIMAL_PARADIGM_YAML)
        try:
            spec = ResearchParadigmSpec.from_yaml(tmp)
            with pytest.raises(ValueError, match="Unsupported execution_mode"):
                execute_paradigm(spec, execution_mode="us")
        finally:
            tmp.unlink()


# ── Build helpers ────────────────────────────────────────────────────────────


class TestBuildHelpers:
    def test_build_ranker_candidates_from_spec(self) -> None:
        tmp = _write_temp_yaml(MINIMAL_PARADIGM_YAML)
        try:
            spec = ResearchParadigmSpec.from_yaml(tmp)
            candidates = build_ranker_candidates_from_spec(spec)
            assert len(candidates) > 0
            # 1 group × 1 calibration = 1 candidate
            n_groups = len(spec.factor_library["groups"])
            n_cals = len(spec.candidate_grid["ranker"]["calibrations"])
            assert len(candidates) == n_groups * n_cals
        finally:
            tmp.unlink()

    def test_build_factor_baselines_from_spec(self) -> None:
        tmp = _write_temp_yaml(MINIMAL_PARADIGM_YAML)
        try:
            spec = ResearchParadigmSpec.from_yaml(tmp)
            baselines = build_factor_baselines_from_spec(spec)
            assert isinstance(baselines, dict)
            assert "factor:cn_momentum_10d" in baselines
            assert baselines["factor:cn_momentum_10d"] != ""
        finally:
            tmp.unlink()


# ── Integration: CN and US real specs ────────────────────────────────────────


class TestRealParadigmSpecs:
    def test_cn_spec_loads(self) -> None:
        path = Path("configs/research_paradigms/cn_10d_csi300_baseline.yaml")
        if not path.exists():
            pytest.skip("CN paradigm spec not found")
        spec = ResearchParadigmSpec.from_yaml(path)
        assert spec.market == "cn"
        assert spec.benchmark == "000300"
        assert spec.experiment_id == "cn_10d_csi300_baseline"
        assert spec.strategy["horizon_days"] == 10
        assert spec.strategy["top_n"] == 15
        assert spec.strategy["bottom_n"] == 15
        assert spec.strategy["return_provenance"] == "raw_forward_return"
        assert spec.strategy["research_only"] is True
        assert spec.strategy["return_expression"] == CANONICAL_10D_RETURN_EXPR
        assert spec.universe["min_symbols"] == 50
        assert spec.universe["alignment_mode"] == "auto"
        assert spec.walk_forward["train_embargo_sessions"] == 10
        assert spec.walk_forward["min_windows"] == 3
        assert len(spec.factor_library["groups"]) == 4
        assert spec.outputs["write_frontend_payload"] is True
        assert spec.evaluation["benchmark_mode"] == "reference_only"
        assert len(spec.evaluation["metrics"]) == 7
        assert spec.evaluation["gates"]["mean_icir"] >= 0.30
        assert spec.evaluation["gates"]["worst_drawdown"] >= -0.15
        assert spec.evaluation["gates"]["ready_ratio"] >= 0.75
        # Baseline ids match the factor:cn_ prefix
        assert "factor:cn_momentum_10d" in spec.candidate_grid["factor_baselines"]

    def test_us_spec_loads(self) -> None:
        path = Path("configs/research_paradigms/us_10d_qqq_baseline.yaml")
        if not path.exists():
            pytest.skip("US paradigm spec not found")
        spec = ResearchParadigmSpec.from_yaml(path)
        assert spec.market == "us"
        assert spec.benchmark == "QQQ"
        assert spec.experiment_id == "us_10d_qqq_baseline"
        assert spec.strategy["horizon_days"] == 10
        assert spec.strategy["top_n"] == 15
        assert spec.strategy["bottom_n"] == 15
        assert spec.strategy["return_provenance"] == "raw_forward_return"
        assert spec.strategy["research_only"] is True
        assert spec.strategy["return_expression"] == CANONICAL_10D_RETURN_EXPR
        assert spec.universe["alignment_mode"] == "strict"
        assert spec.walk_forward["train_embargo_sessions"] == 10
        assert spec.walk_forward["min_windows"] == 3
        assert len(spec.factor_library["groups"]) == 4
        assert spec.outputs["write_frontend_payload"] is True
        assert spec.evaluation["benchmark_mode"] == "reference_only"
        assert len(spec.evaluation["metrics"]) == 7
        assert spec.evaluation["gates"]["mean_icir"] >= 0.30
        assert spec.evaluation["gates"]["worst_drawdown"] >= -0.15
        assert spec.evaluation["gates"]["ready_ratio"] >= 0.75

    def test_cn_dry_run(self) -> None:
        path = Path("configs/research_paradigms/cn_10d_csi300_baseline.yaml")
        if not path.exists():
            pytest.skip("CN paradigm spec not found")
        spec = ResearchParadigmSpec.from_yaml(path)
        with tempfile.TemporaryDirectory() as out_dir:
            result = dry_run_paradigm(spec, output_dir=out_dir)
            assert result["status"] == "dry_run_complete"
            n_groups = len(spec.factor_library["groups"])
            n_cals = len(spec.candidate_grid["ranker"]["calibrations"])
            assert result["n_candidates"] == n_groups * n_cals
            run_dir = Path(result["run_dir"])
            assert run_dir.name == "cn_10d_csi300_baseline"
            assert run_dir.parent == Path(out_dir)
            # Check standard files
            assert (run_dir / "experiment_spec.json").exists()
            assert (run_dir / "frontend_payload.json").exists()
            assert (run_dir / "signals_latest.json").exists()
            assert (run_dir / "top_bottom_signals.csv").exists()

    def test_us_dry_run(self) -> None:
        path = Path("configs/research_paradigms/us_10d_qqq_baseline.yaml")
        if not path.exists():
            pytest.skip("US paradigm spec not found")
        spec = ResearchParadigmSpec.from_yaml(path)
        with tempfile.TemporaryDirectory() as out_dir:
            result = dry_run_paradigm(spec, output_dir=out_dir)
            assert result["status"] == "dry_run_complete"
            n_groups = len(spec.factor_library["groups"])
            n_cals = len(spec.candidate_grid["ranker"]["calibrations"])
            assert result["n_candidates"] == n_groups * n_cals
            run_dir = Path(result["run_dir"])
            assert run_dir.name == "us_10d_qqq_baseline"
            assert run_dir.parent == Path(out_dir)
            # Check standard files
            assert (run_dir / "experiment_spec.json").exists()
            assert (run_dir / "frontend_payload.json").exists()
            assert (run_dir / "signals_latest.json").exists()
            assert (run_dir / "top_bottom_signals.csv").exists()


# ── Canonical return ─────────────────────────────────────────────────────────


class TestCanonicalReturn:
    def test_canonical_10d_return_imported(self) -> None:
        """CANONICAL_10D_RETURN_EXPR is imported from notebook_lab_contracts."""
        assert CANONICAL_10D_RETURN_EXPR == "Ref($close, -10) / $close - 1"

    def test_canonical_in_spec(self) -> None:
        """The spec's return_expression matches the canonical."""
        tmp = _write_temp_yaml(MINIMAL_PARADIGM_YAML)
        try:
            spec = ResearchParadigmSpec.from_yaml(tmp)
            assert spec.strategy["return_expression"] == CANONICAL_10D_RETURN_EXPR
        finally:
            tmp.unlink()


# ── Path resolution ──────────────────────────────────────────────────────────


class TestResolveRelativePath:
    def test_resolves_relative_to_spec_dir(self) -> None:
        tmp = _write_temp_yaml(MINIMAL_PARADIGM_YAML)
        try:
            spec = ResearchParadigmSpec.from_yaml(tmp)
            resolved = _resolve_relative_path(spec, spec.factor_library["source"])
            assert resolved.exists()
        finally:
            tmp.unlink()
