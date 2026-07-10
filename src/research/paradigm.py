"""Research Paradigm Spec and dry-run / execution dispatcher.

Loads a structured research paradigm from YAML, validates strictly,
and provides both a Qlib-free dry-run mode (manifests + small JSON
artifacts only) and a fail-closed execution dispatch that can invoke
the existing #91 CN feature-quality runner.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from src.research.factor_library import (
    FactorGroup,
    factor_groups_to_ranker_feature_groups,
    factor_library_manifest,
    load_factor_library,
    resolve_factor_expressions,
    select_factor_groups,
)
from src.research.notebook_lab_contracts import CANONICAL_10D_RETURN_EXPR
from src.research.ranker_calibration_grid import (
    RankerCalibration,
    RankerFeatureGroup,
    RankerGridCandidate,
    build_ranker_calibration_grid,
)
from src.research.research_artifacts import (
    build_frontend_payload,
    build_research_run_paths,
    build_research_signals_payload,
    write_frontend_payload,
    write_json,
    write_run_status,
    write_skipped_run,
    write_top_bottom_signals_csv,
)

PARADIGM_SCHEMA_VERSION = "1.0"


# ── Validation ────────────────────────────────────────────────────────────────


def _check_source_exists(source: str, spec_path: str) -> None:
    """Verify *source* exists relative to the spec dir or project root."""
    spec_dir = Path(spec_path).parent if spec_path else Path.cwd()
    candidate = spec_dir / source
    if candidate.exists():
        return
    cwd_candidate = Path.cwd() / source
    if cwd_candidate.exists():
        return
    raise FileNotFoundError(
        f"Source '{source}' not found relative to spec dir ({spec_dir}) or cwd"
    )


def validate_research_paradigm_spec(spec: ResearchParadigmSpec) -> None:
    """Validate a ``ResearchParadigmSpec`` against the exact contract.

    Raises ValueError or FileNotFoundError on any violation.

    Parameters
    ----------
    spec:
        A ``ResearchParadigmSpec`` instance (not a raw dict).
    """
    if spec.schema_version != PARADIGM_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported paradigm schema_version '{spec.schema_version}' "
            f"(expected '{PARADIGM_SCHEMA_VERSION}')"
        )

    if not spec.experiment_id:
        raise ValueError("experiment_id must be non-empty")

    if spec.market not in ("cn", "us"):
        raise ValueError(f"market must be 'cn' or 'us', got '{spec.market}'")

    if not spec.benchmark:
        raise ValueError("benchmark must be non-empty")

    # ── Universe ──────────────────────────────────────────────────────────
    universe = spec.universe
    uni_source = str(universe.get("source", ""))
    if not uni_source:
        raise ValueError("universe.source must be non-empty")
    _check_source_exists(uni_source, spec.spec_path)

    min_symbols = int(universe.get("min_symbols", 0))
    if min_symbols < 2:
        raise ValueError(f"universe.min_symbols must be >= 2, got {min_symbols}")

    alignment = str(universe.get("alignment_mode", ""))
    if alignment not in ("strict", "auto"):
        raise ValueError(
            f"universe.alignment_mode must be 'strict' or 'auto', got '{alignment}'"
        )

    # ── Factor library ────────────────────────────────────────────────────
    fl = spec.factor_library
    fl_source = str(fl.get("source", ""))
    if not fl_source:
        raise ValueError("factor_library.source must be non-empty")
    _check_source_exists(fl_source, spec.spec_path)

    fl_groups = fl.get("groups", [])
    if not isinstance(fl_groups, list) or len(fl_groups) == 0:
        raise ValueError("factor_library.groups must be a non-empty list")

    # ── Candidate grid ────────────────────────────────────────────────────
    cg = spec.candidate_grid
    ranker = cg.get("ranker")
    if not isinstance(ranker, dict):
        raise ValueError("candidate_grid.ranker must be a mapping")

    cals = ranker.get("calibrations", [])
    if not isinstance(cals, list) or len(cals) == 0:
        raise ValueError("candidate_grid.ranker.calibrations must be a non-empty list")

    baselines = cg.get("factor_baselines", [])
    if not isinstance(baselines, list):
        raise ValueError("candidate_grid.factor_baselines must be a list")

    # ── Strategy ──────────────────────────────────────────────────────────
    strategy = spec.strategy
    horizon = int(strategy.get("horizon_days", 0))
    if horizon != 10:
        raise ValueError(f"strategy.horizon_days must be 10, got {horizon}")

    holding = int(strategy.get("holding_days", 0))
    if holding != 10:
        raise ValueError(f"strategy.holding_days must be 10, got {holding}")

    rebalance = int(strategy.get("rebalance_days", 0))
    if rebalance != 10:
        raise ValueError(f"strategy.rebalance_days must be 10, got {rebalance}")

    ret_expr = str(strategy.get("return_expression", ""))
    if ret_expr != CANONICAL_10D_RETURN_EXPR:
        raise ValueError(
            f"strategy.return_expression must be canonical 10D expression, "
            f"got '{ret_expr}'"
        )

    provenance = str(strategy.get("return_provenance", ""))
    if provenance != "raw_forward_return":
        raise ValueError(
            f"strategy.return_provenance must be 'raw_forward_return', "
            f"got '{provenance}'"
        )

    research_only = strategy.get("research_only")
    if research_only is not True:
        raise ValueError("strategy.research_only must be True")

    # ── Walk-forward ──────────────────────────────────────────────────────
    wf = spec.walk_forward
    min_w = int(wf.get("min_windows", 0))
    if min_w < 3:
        raise ValueError(f"walk_forward.min_windows must be >= 3, got {min_w}")

    embargo = int(wf.get("train_embargo_sessions", 0))
    if embargo != 10:
        raise ValueError(
            f"walk_forward.train_embargo_sessions must be 10, got {embargo}"
        )

    # ── Evaluation / gates ────────────────────────────────────────────────
    evaluation = spec.evaluation
    gates = evaluation.get("gates")
    if not isinstance(gates, dict):
        raise ValueError("evaluation.gates must be a mapping")

    mean_icir = float(gates.get("mean_icir", 0.0))
    if mean_icir < 0.30:
        raise ValueError(
            f"evaluation.gates.mean_icir must be >= 0.30 (non-lowered), got {mean_icir}"
        )

    worst_dd = float(gates.get("worst_drawdown", -1.0))
    if worst_dd < -0.15:
        raise ValueError(
            f"evaluation.gates.worst_drawdown must be >= -0.15 (non-lowered), "
            f"got {worst_dd}"
        )

    ready_ratio = float(gates.get("ready_ratio", 0.0))
    if ready_ratio < 0.75:
        raise ValueError(
            f"evaluation.gates.ready_ratio must be >= 0.75 (non-lowered), "
            f"got {ready_ratio}"
        )

    # ── Outputs ───────────────────────────────────────────────────────────
    outputs = spec.outputs
    if not outputs.get("write_frontend_payload"):
        raise ValueError("outputs.write_frontend_payload must be True")


# ── Compatibility: old dict-based validation ───────────────────────────────────


def _validate_research_paradigm_dict(data: dict[str, Any], spec_path: str = "") -> None:
    """Validate a raw paradigm dict.  Compatibility wrapper."""
    spec = ResearchParadigmSpec.from_dict(data, spec_path=spec_path)
    validate_research_paradigm_spec(spec)


# ── Spec ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResearchParadigmSpec:
    """One validated research paradigm loaded from YAML.

    Frozen fields: schema_version, experiment_id, market, benchmark,
    and seven dict sections — universe, factor_library, candidate_grid,
    strategy, walk_forward, evaluation, outputs.
    """

    schema_version: str
    experiment_id: str
    market: str
    benchmark: str
    universe: dict[str, Any]
    factor_library: dict[str, Any]
    candidate_grid: dict[str, Any]
    strategy: dict[str, Any]
    walk_forward: dict[str, Any]
    evaluation: dict[str, Any]
    outputs: dict[str, Any]
    spec_path: str = ""

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ResearchParadigmSpec":
        """Load and validate a research paradigm spec from YAML."""
        yaml_path = Path(path).resolve()
        if not yaml_path.exists():
            raise FileNotFoundError(f"Research paradigm spec not found: {yaml_path}")

        with open(yaml_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh)

        # Validate before constructing
        _validate_research_paradigm_dict(data, str(yaml_path))

        return cls(
            schema_version=str(data["schema_version"]),
            experiment_id=str(data["experiment_id"]),
            market=str(data["market"]),
            benchmark=str(data["benchmark"]),
            universe=dict(data["universe"]),
            factor_library=dict(data["factor_library"]),
            candidate_grid=dict(data["candidate_grid"]),
            strategy=dict(data["strategy"]),
            walk_forward=dict(data["walk_forward"]),
            evaluation=dict(data["evaluation"]),
            outputs=dict(data["outputs"]),
            spec_path=str(yaml_path),
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any], spec_path: str = "") -> "ResearchParadigmSpec":
        """Construct from an already-loaded dict (used by compat validators)."""
        return cls(
            schema_version=str(data.get("schema_version", "")),
            experiment_id=str(data.get("experiment_id", "")),
            market=str(data.get("market", "")),
            benchmark=str(data.get("benchmark", "")),
            universe=dict(data.get("universe", {})),
            factor_library=dict(data.get("factor_library", {})),
            candidate_grid=dict(data.get("candidate_grid", {})),
            strategy=dict(data.get("strategy", {})),
            walk_forward=dict(data.get("walk_forward", {})),
            evaluation=dict(data.get("evaluation", {})),
            outputs=dict(data.get("outputs", {})),
            spec_path=spec_path,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "market": self.market,
            "benchmark": self.benchmark,
            "universe": dict(self.universe),
            "factor_library": dict(self.factor_library),
            "candidate_grid": dict(self.candidate_grid),
            "strategy": dict(self.strategy),
            "walk_forward": dict(self.walk_forward),
            "evaluation": dict(self.evaluation),
            "outputs": dict(self.outputs),
        }


# ── Notebook API ──────────────────────────────────────────────────────────────


def load_research_paradigm_spec(path: str | Path) -> ResearchParadigmSpec:
    """Notebook-friendly loader. Returns a validated ResearchParadigmSpec."""
    return ResearchParadigmSpec.from_yaml(path)


# ── Path resolution ────────────────────────────────────────────────────────────


def _resolve_relative_path(spec: ResearchParadigmSpec, rel: str) -> Path:
    """Resolve a config reference relative to the spec file or project root."""
    spec_dir = Path(spec.spec_path).parent if spec.spec_path else Path.cwd()
    candidate = spec_dir / rel
    if candidate.exists():
        return candidate.resolve()
    cwd_candidate = Path.cwd() / rel
    if cwd_candidate.exists():
        return cwd_candidate.resolve()
    raise FileNotFoundError(
        f"Cannot resolve '{rel}' from spec dir ({spec_dir}) or cwd"
    )


# ── Helpers: extract structured data from spec dicts ──────────────────────────


def _parse_calibrations(candidate_grid: dict[str, Any]) -> tuple[RankerCalibration, ...]:
    """Parse RankerCalibration list from candidate_grid.ranker.calibrations."""
    ranker = candidate_grid.get("ranker", {})
    cal_list: list[dict[str, Any]] = ranker.get("calibrations", [])
    return tuple(
        RankerCalibration(
            n_gain_bins=int(c["n_gain_bins"]),
            num_boost_round=int(c["num_boost_round"]),
            num_leaves=int(c["num_leaves"]),
            min_data_in_leaf=int(c["min_data_in_leaf"]),
            learning_rate=float(c.get("learning_rate", 0.05)),
        )
        for c in cal_list
    )


def _factor_baseline_ids(candidate_grid: dict[str, Any]) -> list[str]:
    """Extract factor_baselines from candidate_grid."""
    return [str(b) for b in candidate_grid.get("factor_baselines", [])]


def _group_names(factor_library: dict[str, Any]) -> list[str]:
    """Extract group names from factor_library.groups."""
    return [str(g) for g in factor_library.get("groups", [])]


def _min_symbols(universe: dict[str, Any]) -> int:
    return int(universe.get("min_symbols", 20))


# ── Build helpers (public API) ────────────────────────────────────────────────


def build_ranker_candidates_from_spec(
    spec: ResearchParadigmSpec, root: str | Path | None = None
) -> list[RankerGridCandidate]:
    """Build the ranker candidate grid from a validated spec.

    Loads the factor library, selects the configured groups, converts
    them to ``RankerFeatureGroup``, and builds the calibration grid.

    Parameters
    ----------
    spec:
        Validated research paradigm spec.
    root:
        Project root for resolving relative paths (auto-detected if omitted).

    Returns
    -------
    list[RankerGridCandidate]
    """
    lib_source = spec.factor_library["source"]
    lib_path = _resolve_relative_path(spec, lib_source)
    library = load_factor_library(lib_path)
    gnames = _group_names(spec.factor_library)
    groups = select_factor_groups(library, gnames)
    rfgroups = factor_groups_to_ranker_feature_groups(groups)
    calibrations = _parse_calibrations(spec.candidate_grid)
    return build_ranker_calibration_grid(
        feature_groups=rfgroups,
        calibrations=list(calibrations),
    )


def build_factor_baselines_from_spec(
    spec: ResearchParadigmSpec, root: str | Path | None = None
) -> dict[str, str]:
    """Resolve baseline factor ids to expressions from the factor library.

    Parameters
    ----------
    spec:
        Validated research paradigm spec.
    root:
        Project root for resolving relative paths (auto-detected if omitted).

    Returns
    -------
    dict[str, str]
        Mapping from baseline factor id to its expression.
    """
    baseline_ids = _factor_baseline_ids(spec.candidate_grid)
    if not baseline_ids:
        return {}

    lib_source = spec.factor_library["source"]
    lib_path = _resolve_relative_path(spec, lib_source)
    library = load_factor_library(lib_path)
    return {
        fid: resolve_factor_expressions([fid], library)[0]
        for fid in baseline_ids
    }


# ── Dry-run (Qlib-free) ──────────────────────────────────────────────────────


def dry_run_paradigm(
    spec: ResearchParadigmSpec,
    *,
    root: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Execute a Qlib-free dry run of the paradigm.

    Validates all configuration, builds factor/candidate manifests and
    the frontend payload, and writes small schema artifacts to the
    standard run directory.  Does **not** import or initialize Qlib.
    """
    if output_dir:
        paths = build_research_run_paths(None, spec.experiment_id, output_dir=output_dir)
    else:
        paths = build_research_run_paths(root, spec.experiment_id)
    run_dir = paths.run_dir

    # Resolve and load factor library
    lib_source = spec.factor_library["source"]
    lib_path = _resolve_relative_path(spec, lib_source)
    library = load_factor_library(lib_path)

    # Build factor manifest
    fmanifest = factor_library_manifest(list(library.values()))
    if spec.outputs.get("write_factor_manifest", True):
        paths.ensure_dir()
        write_json(paths.factor_manifest, fmanifest)

    # Build candidates
    calibrations = _parse_calibrations(spec.candidate_grid)
    gnames = _group_names(spec.factor_library)
    groups = select_factor_groups(library, gnames)
    rfgroups = factor_groups_to_ranker_feature_groups(groups)
    candidates = build_ranker_calibration_grid(
        feature_groups=rfgroups,
        calibrations=list(calibrations),
    )

    cmanifest: dict[str, object] = {
        "schema_version": "1.0",
        "n_candidates": len(candidates),
        "n_feature_groups": len(rfgroups),
        "n_calibrations": len(calibrations),
        "candidates": [c.to_dict() for c in candidates],
    }
    if spec.outputs.get("write_candidate_manifest", True):
        paths.ensure_dir()
        write_json(paths.candidate_manifest, cmanifest)

    # Resolve baseline factor expressions
    baseline_ids = _factor_baseline_ids(spec.candidate_grid)
    baseline_exprs: dict[str, str] = {}
    if baseline_ids:
        baseline_exprs = {
            fid: resolve_factor_expressions([fid], library)[0]
            for fid in baseline_ids
        }

    # Write run_status (always)
    write_run_status(
        paths,
        experiment_id=spec.experiment_id,
        status="dry_run_complete",
        reason="Qlib-free dry run — no model training or data loading performed",
        extra={
            "n_factors": fmanifest["n_factors"],
            "n_groups": fmanifest["n_groups"],
            "n_candidates": cmanifest["n_candidates"],
        },
    )

    # Write experiment spec (experiment_spec.json — NOT paradigm_spec.json)
    paths.ensure_dir()
    write_json(paths.experiment_spec, spec.to_dict())

    # Write empty signals_latest when requested
    if spec.outputs.get("write_top_bottom_signals", True):
        write_top_bottom_signals_csv(
            paths,
            [],
            market=spec.market,
            experiment_id=spec.experiment_id,
            holding_horizon_days=int(spec.strategy.get("holding_days", 10)),
        )
        # Write empty signals_latest.json
        paths.ensure_dir()
        write_json(paths.signals_latest, {"signals": [], "schema_version": "1.0"})

    # Build fixed frontend payload
    frontend = build_frontend_payload(
        experiment_id=spec.experiment_id,
        market=spec.market,
        benchmark=spec.benchmark,
        run_status="dry_run_complete",
        artifact_paths=paths.artifact_paths(),
        metadata={
            "n_factors": fmanifest["n_factors"],
            "n_groups": fmanifest["n_groups"],
            "n_candidates": cmanifest["n_candidates"],
            "n_feature_groups": len(rfgroups),
            "n_calibrations": len(calibrations),
            "n_baseline_factors": len(baseline_exprs),
            "baseline_factor_ids": list(baseline_ids),
            "group_names": list(gnames),
            "dry_run": True,
        },
    )
    if spec.outputs.get("write_frontend_payload", True):
        write_frontend_payload(paths, frontend)

    return {
        "status": "dry_run_complete",
        "run_dir": str(run_dir),
        "n_factors": fmanifest["n_factors"],
        "n_groups": fmanifest["n_groups"],
        "n_candidates": cmanifest["n_candidates"],
        "n_baseline_factors": len(baseline_exprs),
        "group_names": list(gnames),
    }


# ── Notebook execution entry point ───────────────────────────────────────────


def run_research_paradigm(
    spec: ResearchParadigmSpec,
    root: str | Path | None = None,
    *,
    dry_run: bool = False,
    execution_mode: str | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Notebook-friendly execution entry point.

    Parameters
    ----------
    spec:
        Validated research paradigm spec.
    root:
        Project root directory (auto-detected if omitted).
    dry_run:
        If True, run Qlib-free dry-run only.
    execution_mode:
        Named execution mode (currently supports ``"cn"`` for the #91 runner).
        Required when ``dry_run`` is False.
    output_dir:
        Override the standard run output directory.

    Returns
    -------
    dict
        Result with at least ``status`` and ``run_dir`` keys.

    Raises
    ------
    ValueError
        If ``dry_run=False`` and ``execution_mode`` is not provided.
    """
    if dry_run:
        return dry_run_paradigm(spec, root=root, output_dir=output_dir)
    if execution_mode:
        return execute_paradigm(
            spec, root=root, output_dir=output_dir, execution_mode=execution_mode
        )
    raise ValueError(
        "run_research_paradigm requires dry_run=True or an explicit execution_mode"
    )


# ── Execution dispatch ───────────────────────────────────────────────────────


def execute_paradigm(
    spec: ResearchParadigmSpec,
    *,
    root: str | Path | None = None,
    output_dir: str | Path | None = None,
    execution_mode: str = "",
) -> dict[str, Any]:
    """Execute a research paradigm.

    Requires an explicit execution mode.  Currently supports
    ``execution_mode="cn"`` which invokes the existing #91
    CN feature-quality flow and normalizes its outputs into the
    standard artifact schema.
    """
    if not execution_mode:
        raise ValueError(
            "execute_paradigm requires an explicit execution_mode. "
            "Use --execute-existing-runner or run with --dry-run first."
        )

    mode = execution_mode.lower()

    if mode == "cn":
        return _execute_cn_baseline(spec, root=root, output_dir=output_dir)
    else:
        raise ValueError(
            f"Unsupported execution_mode '{execution_mode}'. "
            f"Supported modes: cn"
        )


def _execute_cn_baseline(
    spec: ResearchParadigmSpec,
    *,
    root: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Reuse the existing #91 CN feature-quality runner and normalize artifacts.

    This calls ``scripts/run_cn_10d_validation.py`` (imported, not
    subprocessed) and copies/normalizes its outputs into the standard
    ``artifacts/research_runs/`` schema.
    """
    import shutil

    root_path = Path(root) if root else Path.cwd()

    if output_dir:
        paths = build_research_run_paths(None, spec.experiment_id, output_dir=output_dir)
    else:
        paths = build_research_run_paths(root, spec.experiment_id)
    paths.ensure_dir()

    # Run the existing #91 validation
    try:
        from scripts.run_cn_10d_validation import run as run_cn_10d
    except ImportError:
        raise RuntimeError(
            "Cannot import scripts.run_cn_10d_validation — ensure the module is on PYTHONPATH"
        )

    first_test_year = int(spec.walk_forward.get("first_test_year", 2024))
    last_test_year = int(spec.walk_forward.get("last_test_year", 2026))

    result = run_cn_10d(
        root_path,
        first_test_year=first_test_year,
        last_test_year=last_test_year,
        train_start="",
        test_end="",
    )

    # Normalize: copy/reference outputs from the existing evidence dir
    evidence_dir = root_path / "artifacts" / "evidence" / "cn_10d_validation"

    # Write experiment spec
    write_json(paths.experiment_spec, spec.to_dict())

    status = result.get("status", "unknown")

    if status == "skipped":
        write_skipped_run(
            paths,
            experiment_id=spec.experiment_id,
            reason=result.get("reason", "CN validation skipped"),
            market=spec.market,
            benchmark=spec.benchmark,
        )
        return {
            "status": "skipped",
            "run_dir": str(paths.run_dir),
            "reason": result.get("reason", ""),
        }

    # Copy stability summary
    stability_src = evidence_dir / "walk_forward_stability.json"
    if stability_src.exists():
        shutil.copy2(stability_src, paths.walk_forward_stability)

    # Copy decision pack
    pack_src = evidence_dir / "model_decision_pack.json"
    if pack_src.exists():
        shutil.copy2(pack_src, paths.model_decision_pack)
        pack_data = json.loads(pack_src.read_text(encoding="utf-8"))
        decision = pack_data.get("decision", {})
        trade_ready = bool(decision.get("trade_ready", False))
    else:
        trade_ready = False

    # Copy readiness
    readiness_src = evidence_dir / "readiness.json"
    if readiness_src.exists():
        shutil.copy2(readiness_src, paths.data_readiness)

    # Write run status
    write_run_status(
        paths,
        experiment_id=spec.experiment_id,
        status=status,
        reason=f"Executed via existing #91 CN runner; result={status}",
        trade_ready=trade_ready,
        extra={"evidence_dir": str(evidence_dir)},
    )

    # Write frontend payload with trade_ready from decision pack only
    frontend = build_frontend_payload(
        experiment_id=spec.experiment_id,
        market=spec.market,
        benchmark=spec.benchmark,
        run_status=status,
        trade_ready=trade_ready,
        artifact_paths=paths.artifact_paths(),
        metadata={
            "runner": "cn_10d_validation",
            "evidence_dir": str(evidence_dir),
        },
    )
    write_frontend_payload(paths, frontend)

    return {
        "status": status,
        "run_dir": str(paths.run_dir),
        "result": result,
        "trade_ready": trade_ready,
    }
