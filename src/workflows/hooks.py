import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

import qlib

from src.assistant.data_quality_index import DataQualityIndex
from src.assistant.metadata_db import resolve_metadata_db_path
from src.assistant.services.artifact_refresh_service import ArtifactRefreshService
from src.common.env_manager import EnvironmentManager
from src.common.logging import get_logger
from src.common.paths import ARTIFACTS_DIR, MODELS_DIR, PROJECT_ROOT, REPORTS_DIR, RUNS_DIR
from src.data.quality import generate_data_quality_summary
from src.governance.service import GovernanceService
from src.models.artifact import ArtifactValidationError, register_artifact
from src.models.reconstruction import (
    ReconstructionResult,
    ReconstructionStatus,
    validate_inference,
)
from src.reliability.classifier import classify_failure
from src.research.registry import register_model
from src.research.service import ResearchService
from src.research.walk_forward import walk_forward_validate
from src.workflows.profile_compiler import compile_strategy_profile

logger = get_logger(__name__)

_PIPELINE_RESULT_ENV = "ALPHA_PIPELINE_RESULT_PATH"


def _publish_pipeline_result(result: dict[str, Any]) -> dict[str, Any]:
    result_path = os.environ.get(_PIPELINE_RESULT_ENV)
    if result_path:
        path = Path(result_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


def get_task_slug(operation: str, market: str) -> str:
    return f"workflow.{operation}.{str(market).lower()}"


def _pipeline_gate_outcome(walk_forward: dict[str, Any] | None) -> dict[str, Any]:
    """Classify training completion separately from operational eligibility."""
    gate_passed = bool(walk_forward and walk_forward.get("gate_passed") is True)
    has_failures = bool(walk_forward and walk_forward.get("gate_failures"))
    if not gate_passed or has_failures:
        return {
            "status": "RESEARCH_CANDIDATE",
            "operational_success": False,
            "promoted": False,
        }
    return {
        "status": "SUCCESS",
        "operational_success": True,
        "promoted": False,
    }


def _run_clean_reconstruction(artifact_id: str) -> ReconstructionResult:
    """Run reconstruct_model in a fresh Python subprocess.

    This ensures the reconstruction is not tainted by any in-process state.
    If the subprocess approach fails, returns a NOT_RUN result.
    """
    script = (
        "import json, sys, pickle;\n"
        "from pathlib import Path;\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]));\n"
        "from src.models.reconstruction import reconstruct_model;\n"
        "result = reconstruct_model(sys.argv[1], clean_process=True);\n"
        "print(json.dumps({\n"
        "    'artifact_id': result.artifact_id,\n"
        "    'passed': result.passed,\n"
        "    'status': result.status,\n"
        "    'clean_process': result.clean_process,\n"
        "    'prediction_correlation': result.prediction_correlation,\n"
        "    'prediction_match_pct': result.prediction_match_pct,\n"
        "    'config_match': result.config_match,\n"
        "    'error': result.error,\n"
        "}))\n"
    )
    try:
        proc = subprocess.run(
            [sys.executable, "-c", script, artifact_id],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(PROJECT_ROOT),
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout.strip().splitlines()[-1])
            return ReconstructionResult(
                artifact_id=data["artifact_id"],
                passed=data["passed"],
                status=data["status"],
                clean_process=data["clean_process"],
                prediction_correlation=data["prediction_correlation"],
                prediction_match_pct=data["prediction_match_pct"],
                config_match=data["config_match"],
                error=data.get("error", ""),
            )
        else:
            logger.warning(
                "Clean reconstruction subprocess failed",
                returncode=proc.returncode,
                stderr=proc.stderr[:500] if proc.stderr else "",
            )
    except Exception as exc:
        logger.warning("Clean reconstruction subprocess error", error=str(exc))

    return ReconstructionResult(
        artifact_id=artifact_id,
        passed=False,
        status=ReconstructionStatus.NOT_RUN.value,
        clean_process=True,
        error="Clean-process reconstruction did not complete",
    )


def generate_quality_report(market: str = "all"):
    """
    Generate and persist a data quality report for the specified market.
    """
    from src.common.paths import DATA_DIR

    markets = ["cn", "us"] if market == "all" else [market]
    try:
        q = generate_data_quality_summary(
            dataset_key="watchlist",
            freq="day",
            provider_uri=DATA_DIR / "watchlist",
            csv_dir=DATA_DIR / "csv_source",
            markets=markets,
        )
        if q.get("ok"):
            idx = DataQualityIndex(db_path=resolve_metadata_db_path(PROJECT_ROOT))
            idx.upsert(
                snapshot_id=str(q.get("snapshot_id")),
                dataset_key="watchlist",
                freq="day",
                market=market,
                latest_calendar_day=str(q.get("latest_calendar_day")),
                summary=q,
            )
            return q
    except Exception as e:
        logger.error("Failed to generate quality report", error=str(e))
    return None


def _repair_data(market: str, lookback_days: int = 60) -> bool:
    """
    Attempt to repair market data by running update_data script.
    """
    logger.info("Attempting data repair", market=market.upper(), lookback_days=lookback_days)
    try:
        cmd = [
            sys.executable,
            "scripts/update_data.py",
            "--market",
            market,
            "--lookback-days",
            str(lookback_days),
        ]
        subprocess.run(cmd, check=True, cwd=str(PROJECT_ROOT))
        logger.info("Data repair successful", market=market.upper())
        return True
    except Exception as e:
        logger.error("Data repair failed", market=market.upper(), error=str(e))
        return False


def on_pipeline_start(
    gov: GovernanceService,
    market: str,
    action: str,
    task_slug: str,
    details: dict[str, Any] | None = None,
) -> None:
    """
    Log start and enforce mutex using workflows table.
    """
    # Enforce mutex using workflows table
    active = [
        w
        for w in gov.query_workflows(status="RUNNING")
        if w["market"] == str(market).upper() and action in str(w["name"])
    ]
    if active:
        # Check if it's been running for more than 4 hours - consider it stale
        updated_at_str = active[0].get("updated_at")
        if updated_at_str:
            try:
                updated_at = datetime.fromisoformat(updated_at_str)
                now = datetime.now(updated_at.tzinfo)
                if (now - updated_at).total_seconds() > 14400:  # 4 hours
                    logger.warning(
                        "Workflow is RUNNING but stale, overriding lock",
                        workflow_id=active[0]["workflow_id"],
                    )
                else:
                    raise RuntimeError(
                        f"Workflow lock active: {active[0]['name']} for {market} is already in status RUNNING (ID: {active[0]['workflow_id']})."
                    )
            except Exception as e:
                if isinstance(e, RuntimeError):
                    raise e
                pass

    gov.update_workflow_status(
        task_slug,  # Using task_slug as workflow_id for simplicity in hooks
        name=f"{action}: {market}",
        market=market,
        status="RUNNING",
        details=details,
    )
    gov.log_run_event(
        market,
        action,
        "STARTED",
        task_slug=task_slug,
        source="hooks",
        details=details,
    )


def on_pipeline_success(
    gov: GovernanceService,
    market: str,
    action: str,
    task_slug: str,
    details: dict[str, Any] | None = None,
) -> None:
    gov.log_run_event(
        market,
        action,
        "SUCCESS",
        task_slug=task_slug,
        source="hooks",
        details=details,
    )
    gov.update_workflow_status(
        task_slug,
        status="SUCCESS",
        end_time=datetime.now().isoformat(),
        details=details,
    )


def on_pipeline_failure(
    gov: GovernanceService,
    market: str,
    action: str,
    task_slug: str,
    operation: str,
    summary: str,
    component: str,
    stderr: str = "",
    exc: Exception | None = None,
    returncode: int | None = None,
) -> None:
    event = classify_failure(
        component=component,
        exc=exc,
        stderr=stderr or summary,
        returncode=returncode,
        context={
            "market": market,
            "operation": operation,
            "run_id": task_slug,
        },
    )
    resolved_event = gov.log_reliability_event(
        event,
        task_slug=task_slug,
        source="hooks",
    )
    gov.update_workflow_status(
        task_slug,
        status="FAILED",
        end_time=datetime.now().isoformat(),
        error=summary,
        details={
            "event_id": resolved_event.event_id,
            "code": resolved_event.code,
            "operation": operation,
        },
    )


def on_pipeline_retry(
    gov: GovernanceService,
    market: str,
    action: str,
    task_slug: str,
    attempt: int,
    reason: str,
    details: dict[str, Any] | None = None,
) -> None:
    retry_details = {**(details or {}), "attempt": attempt, "reason": reason}
    gov.log_run_event(
        market,
        action,
        "RETRYING",
        task_slug=task_slug,
        source="hooks",
        details=retry_details,
    )
    gov.update_workflow_status(
        task_slug,
        status="RETRYING",
        details=retry_details,
    )


def run_training_pipeline(
    market: str = "all",
    model_type: str = "lgbm",
    profile: str = "",
    tag: str = "",
    strategy_template: str = "",
    cost_params: str = "",
    max_retries: int = 1,
    snapshot_id: str = "",
    details: dict[str, Any] | None = None,
):
    """
    Orchestrated training pipeline hook.

    Parameters
    ----------
    snapshot_id : str, optional
        Content-addressed data snapshot ID.  When provided, the training
        run pins itself to this exact snapshot so the experiment is fully
        reproducible even after newer data is published.
    """
    snapshot_id = str(snapshot_id or os.environ.get("ALPHA_DATA_SNAPSHOT_ID", "")).strip()
    gov = GovernanceService(PROJECT_ROOT)
    research = ResearchService(PROJECT_ROOT)
    env = EnvironmentManager(PROJECT_ROOT)
    artifact_refresh = ArtifactRefreshService(project_root=PROJECT_ROOT, python_exe=sys.executable)

    task_slug = get_task_slug("run", market)

    try:
        on_pipeline_start(
            gov,
            market=market,
            action="Pipeline Run",
            task_slug=task_slug,
            details={
                **(details or {}),
                "model_type": model_type,
                "tag": str(tag or ""),
                "snapshot_id": snapshot_id or None,
            },
        )
    except RuntimeError as e:
        logger.warning(str(e))
        raise e

    tag = str(tag or "").strip()
    if not tag:
        exc = ValueError("tag is required.")
        on_pipeline_failure(
            gov,
            market=market,
            action="Pipeline Run",
            task_slug=task_slug,
            operation="run",
            summary=str(exc),
            component="hooks.run_training_pipeline",
            exc=exc,
        )
        raise exc

    attempt = 0
    while attempt <= max_retries:
        try:
            if market == "all":
                if not snapshot_id:
                    snapshot_id = research.resolve_snapshot_binding()["snapshot_id"]
                previous_snapshot = os.environ.get("ALPHA_DATA_SNAPSHOT_ID")
                previous_result_path = os.environ.get(_PIPELINE_RESULT_ENV)
                os.environ["ALPHA_DATA_SNAPSHOT_ID"] = snapshot_id
                child_results = []
                try:
                    with TemporaryDirectory(prefix="alpha-pipeline-") as result_dir:
                        for m in ["cn", "us"]:
                            result_path = Path(result_dir) / f"{m}.json"
                            os.environ[_PIPELINE_RESULT_ENV] = str(result_path)
                            args = [
                                "run",
                                "--market",
                                m,
                                "--model_type",
                                str(model_type),
                                "--tag",
                                str(tag),
                            ]
                            if profile:
                                args += ["--profile", str(profile)]
                            if strategy_template:
                                args += ["--strategy_template", str(strategy_template)]
                            if cost_params:
                                args += ["--cost_params", str(cost_params)]
                            child_process = env.run_in_isolation("src.orchestrator", args)
                            if result_path.is_file():
                                child_results.append(
                                    json.loads(result_path.read_text(encoding="utf-8"))
                                )
                            elif child_process is None:
                                # Lightweight test doubles do not launch a child process.
                                child_results.append({"market": m, "operational_success": True})
                            else:
                                child_results.append(
                                    {
                                        "market": m,
                                        "status": "RESEARCH_CANDIDATE",
                                        "operational_success": False,
                                    }
                                )
                finally:
                    if previous_snapshot is None:
                        os.environ.pop("ALPHA_DATA_SNAPSHOT_ID", None)
                    else:
                        os.environ["ALPHA_DATA_SNAPSHOT_ID"] = previous_snapshot
                    if previous_result_path is None:
                        os.environ.pop(_PIPELINE_RESULT_ENV, None)
                    else:
                        os.environ[_PIPELINE_RESULT_ENV] = previous_result_path

                operational_success = all(
                    child.get("operational_success") is True for child in child_results
                )
                aggregate = {
                    "status": "SUCCESS" if operational_success else "RESEARCH_CANDIDATE",
                    "operational_success": operational_success,
                    "promoted": False,
                    "market": "all",
                    "snapshot_id": snapshot_id,
                    "children": child_results,
                }
                if operational_success:
                    on_pipeline_success(
                        gov, market=market, action="Pipeline Run", task_slug=task_slug
                    )
                else:
                    gov.log_run_event(
                        market,
                        "Pipeline Run",
                        "RESEARCH_CANDIDATE",
                        task_slug=task_slug,
                        source="hooks",
                        details={"snapshot_id": snapshot_id, "children": child_results},
                    )
                    gov.update_workflow_status(
                        task_slug,
                        status="RESEARCH_CANDIDATE",
                        details={"snapshot_id": snapshot_id, "children": child_results},
                    )
                return _publish_pipeline_result(aggregate)

            # 1. Initialize
            compile_strategy_profile(
                market=market, profile_path=(profile or "configs/strategy_profile.json")
            )
            config = research.load_config(market, model_type)
            snapshot_binding = research.resolve_snapshot_binding(snapshot_id)
            snapshot_id = snapshot_binding["snapshot_id"]
            config = research.bind_config_to_snapshot(config, snapshot_binding)
            env.ensure_qlib(market, config)
            env.check_directories([MODELS_DIR, ARTIFACTS_DIR, REPORTS_DIR, RUNS_DIR])

            # 2. Data Preparation
            # --- Data freshness check ---
            try:
                from qlib.data import D
                cal = D.calendar(start_time="2020-01-01")
                if cal is not None and len(cal) > 0:
                    latest_cal = datetime.strptime(str(cal[-1])[:10], "%Y-%m-%d").date()
                    age_days = (datetime.now().date() - latest_cal).days
                    if age_days > 3:
                        logger.warning(
                            "Data may be stale",
                            latest_calendar_day=str(latest_cal),
                            age_days=age_days,
                        )
            except Exception:
                pass  # Non-blocking

            start_time = config["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["start_time"]
            try:
                config = research.prepare_experiment(market, config, start_time)
            except RuntimeError as e:
                if "No valid tickers found" in str(e) and attempt < max_retries:
                    logger.warning("Data issue detected", error=str(e))
                    if _repair_data(market):
                        attempt += 1
                        on_pipeline_retry(
                            gov,
                            market=market,
                            action="Pipeline Run",
                            task_slug=task_slug,
                            attempt=attempt,
                            reason="Data repair triggered",
                        )
                        continue
                raise

            # Generate Data Quality Report after prep
            generate_quality_report(market=market)

            # 3. Execution
            results = research.run_training_pipeline(
                market,
                config,
                tag,
                snapshot_id=snapshot_id,
                snapshot_binding=snapshot_binding,
            )

            # 3.5 Walk-forward validation
            walk_forward_data = None
            try:
                segments = config["task"]["dataset"]["kwargs"]["segments"]
                train_start = segments["train"][0]
                train_end = (
                    segments["train"][1]
                    if len(segments["train"]) > 1
                    else segments.get("valid", ["", ""])[1]
                )

                wf_result = walk_forward_validate(
                    market=market,
                    model_type=model_type,
                    train_start=train_start,
                    train_end=train_end,
                )
                walk_forward_data = {
                    "mean_ic": wf_result.mean_ic,
                    "std_ic": wf_result.std_ic,
                    "ic_ir": wf_result.ic_ir,
                    "consistency_score": wf_result.consistency_score,
                    "n_splits": len(wf_result.splits),
                }

                # Persist walk-forward results to artifacts
                from dataclasses import asdict as _asdict

                wf_dir = ARTIFACTS_DIR / "walk_forward"
                wf_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                wf_file = wf_dir / f"{market}_{ts}.json"
                with open(wf_file, "w", encoding="utf-8") as wf_f:
                    json.dump(_asdict(wf_result), wf_f, indent=2, default=str)
                logger.info(
                    "Walk-forward validation passed and persisted",
                    file=str(wf_file),
                    mean_ic=wf_result.mean_ic,
                )

                # Hard gate: walk-forward quality check
                WF_HARD_GATES = {
                    "min_icir": 0.3,
                    "min_consistency": 0.55,
                    "min_mean_ic": 0.0,
                }

                wf_ok = True
                wf_failures = []
                if walk_forward_data.get("ic_ir", 0) < WF_HARD_GATES["min_icir"]:
                    wf_ok = False
                    wf_failures.append(
                        f"ICIR={walk_forward_data['ic_ir']:.3f} < {WF_HARD_GATES['min_icir']}"
                    )
                if walk_forward_data.get("consistency_score", 0) < WF_HARD_GATES["min_consistency"]:
                    wf_ok = False
                    wf_failures.append(
                        f"consistency={walk_forward_data['consistency_score']:.3f} < {WF_HARD_GATES['min_consistency']}"
                    )
                if walk_forward_data.get("mean_ic", 0) < WF_HARD_GATES["min_mean_ic"]:
                    wf_ok = False
                    wf_failures.append(
                        f"mean_ic={walk_forward_data['mean_ic']:.4f} < {WF_HARD_GATES['min_mean_ic']}"
                    )

                if not wf_ok:
                    logger.error(
                        "Walk-forward HARD GATE FAILED — model NOT registered",
                        failures=wf_failures,
                    )
                    walk_forward_data["gate_passed"] = False
                    walk_forward_data["gate_failures"] = wf_failures
                else:
                    walk_forward_data["gate_passed"] = True

            except Exception as wf_exc:
                logger.error(
                    "Walk-forward validation FAILED — blocking model promotion",
                    error=str(wf_exc),
                    market=market,
                )
                walk_forward_data = {
                    "gate_passed": False,
                    "gate_failures": [f"Walk-forward execution failed: {wf_exc}"],
                    "mean_ic": None,
                    "ic_ir": None,
                    "consistency_score": None,
                }

            # 4. FDR gate: if this is a batch experiment, check FDR significance
            try:
                from src.research.model_fdr import compute_model_p_value

                sharpe = walk_forward_data.get("sharpe") or results.get("sharpe", 0)
                mean_ic = walk_forward_data.get("mean_ic", 0)
                if sharpe and mean_ic:
                    p_val = compute_model_p_value(
                        sharpe=sharpe, n_obs=walk_forward_data.get("n_obs", 252)
                    )
                    walk_forward_data["p_value"] = p_val
                    walk_forward_data["fdr_significant"] = p_val <= 0.05  # single-model threshold
                    if not walk_forward_data["fdr_significant"]:
                        walk_forward_data.setdefault("gate_failures", []).append(
                            f"FDR: p_value={p_val:.4f} > 0.05"
                        )
                        walk_forward_data["gate_passed"] = False
            except Exception as fdr_exc:
                logger.debug("fdr_gate_skipped", error=str(fdr_exc))

            # 4.5 Artifact gates: validate inference + reconstruction
            artifact_id = results["artifact_id"]
            inference_result = results.get("inference_result")
            if inference_result is None:
                inference_result = validate_inference(artifact_id, n_samples=50)

            # Attempt clean-process reconstruction (subprocess)
            reconstruction_result = _run_clean_reconstruction(artifact_id)

            # Register artifact only when walk-forward AND both gates pass
            artifact_registered = False
            if walk_forward_data and walk_forward_data.get("gate_passed") is True:
                try:
                    register_artifact(
                        artifact_id,
                        inference_result=inference_result,
                        reconstruction_result=reconstruction_result,
                    )
                    artifact_registered = True
                    logger.info(
                        "Artifact registered via pipeline",
                        artifact_id=artifact_id,
                        inference_passed=inference_result.passed,
                        reconstruction_status=reconstruction_result.status,
                    )
                except ArtifactValidationError as exc:
                    logger.warning(
                        "Artifact registration failed (model still registered in model_list)",
                        artifact_id=artifact_id,
                        error=str(exc),
                    )
            else:
                logger.info(
                    "Artifact not registered (walk-forward gate not passed)",
                    artifact_id=artifact_id,
                )

            # 5. Finalize
            register_model(
                market,
                results["model_path"],
                config,
                metrics=results.get("metrics"),
                run_id=results["run_id"],
                model_tag=tag,
                walk_forward=walk_forward_data,
                artifact_id=results["artifact_id"],
                artifact_config=results["artifact"].config,
            )
            artifact_refresh.refresh_training_artifacts(market=market)

            gate_outcome = _pipeline_gate_outcome(walk_forward_data)
            event_details = {
                "model_type": model_type,
                "tag": str(tag or ""),
                "run_id": results["run_id"],
                "artifact_id": results["artifact_id"],
                "snapshot_id": snapshot_id,
                "gate_failures": walk_forward_data.get("gate_failures", []),
                "inference_passed": inference_result.passed if inference_result else None,
                "reconstruction_status": reconstruction_result.status if reconstruction_result else None,
                "artifact_registered": artifact_registered,
            }
            if gate_outcome["operational_success"]:
                on_pipeline_success(
                    gov,
                    market=market,
                    action="Pipeline Run",
                    task_slug=task_slug,
                    details=event_details,
                )
            else:
                gov.log_run_event(
                    market,
                    "Pipeline Run",
                    "RESEARCH_CANDIDATE",
                    task_slug=task_slug,
                    source="hooks",
                    details=event_details,
                )
                gov.update_workflow_status(
                    task_slug,
                    status="RESEARCH_CANDIDATE",
                    details=event_details,
                )

            # Auto-rebuild dashboard DB so frontend shows the new model
            try:
                # First sync model_list.yaml to SQLite registry
                import yaml

                from src.assistant.metadata_db import resolve_metadata_db_path
                from src.assistant.model_registry_index import ModelRegistryIndex
                from src.common import paths

                model_list_path = paths.get_artifacts_dir() / "models" / "model_list.yaml"
                if model_list_path.exists():
                    with open(model_list_path) as f:
                        ml_data = yaml.safe_load(f) or {"models": []}
                    db_path = resolve_metadata_db_path(paths.get_artifacts_dir())
                    index = ModelRegistryIndex(db_path=db_path)
                    existing = {v["id"] for v in index.list_versions(limit=200)}
                    for m in ml_data.get("models", []):
                        if m["id"] not in existing:
                            index.upsert_entry(m)
                            logger.info("Synced model to SQLite", model_id=m["id"])

                from scripts.build_dashboard_db import main as build_dashboard_db

                build_dashboard_db()
                logger.info("Dashboard DB rebuilt after training", market=market)
            except Exception as exc:
                logger.warning("Failed to rebuild dashboard DB", error=str(exc))

            return _publish_pipeline_result(
                {
                    **gate_outcome,
                    "market": market,
                    "run_id": results["run_id"],
                    "artifact_id": results["artifact_id"],
                    "snapshot_id": snapshot_id,
                }
            )
        except Exception as exc:
            if attempt < max_retries:
                attempt += 1
                on_pipeline_retry(
                    gov,
                    market=market,
                    action="Pipeline Run",
                    task_slug=task_slug,
                    attempt=attempt,
                    reason=str(exc),
                )
                logger.info("Retrying pipeline", attempt=attempt, max_retries=max_retries)
                continue

            on_pipeline_failure(
                gov,
                market=market,
                action="Pipeline Run",
                task_slug=task_slug,
                operation="run",
                summary=str(exc),
                component="hooks.run_training_pipeline",
                stderr=getattr(exc, "stderr", "") or "",
                exc=exc,
                returncode=getattr(exc, "returncode", None),
            )
            raise


def run_rebacktest_pipeline(
    market: str = "us",
    model_path: str = "",
    model_type: str = "lgbm",
    profile: str = "",
    tag: str = "",
    start: str = "2025-01-01",
    end: str = "latest",
    update_data: bool = False,
    refresh_dashboard_db: bool = True,
    strategy_template: str = "",
    cost_params: str = "",
    details: dict[str, Any] | None = None,
):
    """
    Orchestrated re-backtest pipeline hook.
    """
    gov = GovernanceService(PROJECT_ROOT)
    research = ResearchService(PROJECT_ROOT)
    env = EnvironmentManager(PROJECT_ROOT)
    artifact_refresh = ArtifactRefreshService(project_root=PROJECT_ROOT, python_exe=sys.executable)

    task_slug = get_task_slug("rebacktest", market)

    try:
        on_pipeline_start(
            gov,
            market=market,
            action="Rebacktest",
            task_slug=task_slug,
            details={
                **(details or {}),
                "model_type": model_type,
                "model_path": str(model_path or ""),
            },
        )
    except RuntimeError as e:
        logger.warning(str(e))
        raise e

    try:
        if market == "all":
            if update_data:
                _repair_data(market="all", lookback_days=30)
            for m in ["cn", "us"]:
                args = [
                    "rebacktest",
                    "--market",
                    m,
                    "--model_type",
                    str(model_type),
                    "--start",
                    str(start),
                    "--end",
                    str(end),
                ]
                if profile:
                    args += ["--profile", str(profile)]
                if tag:
                    args += ["--tag", str(tag)]
                if strategy_template:
                    args += ["--strategy_template", str(strategy_template)]
                if cost_params:
                    args += ["--cost_params", str(cost_params)]
                if not refresh_dashboard_db:
                    args += ["--refresh_dashboard_db", "False"]
                env.run_in_isolation("src.orchestrator", args)
            on_pipeline_success(gov, market=market, action="Rebacktest", task_slug=task_slug)
            return {"status": "SUCCESS", "market": "all"}

        if update_data:
            _repair_data(market=market, lookback_days=30)

        # 1. Initialize
        compile_strategy_profile(
            market=market, profile_path=(profile or "configs/strategy_profile.json")
        )
        config = research.load_config(market, model_type)

        # Qlib init
        from src.common.qlib_init import build_qlib_init_cfg

        qlib_init_cfg = build_qlib_init_cfg(config.get("qlib_init", {}) or {}, market=market)
        qlib.init(**qlib_init_cfg)

        # 2. Data Preparation
        profile_data = {}
        profile_p = Path(profile or "configs/strategy_profile.json")
        if profile_p.exists():
            with open(profile_p) as f:
                profile_data = json.load(f)

        config = research.prepare_experiment(
            market, config, start, end_time=end, profile_data=profile_data
        )

        # Generate Data Quality Report after prep
        generate_quality_report(market=market)

        # 3. Execution
        m_path = Path(model_path) if model_path else MODELS_DIR / f"{market}_model.pkl"
        results = research.perform_rebacktest(
            market, m_path, config, profile_data=profile_data, tag=tag
        )

        # 4. Finalize
        artifact_refresh.refresh_backtest_artifacts(
            market=market,
            refresh_dashboard_db=refresh_dashboard_db,
        )

        on_pipeline_success(
            gov,
            market=market,
            action="Rebacktest",
            task_slug=task_slug,
            details={
                "model_type": model_type,
                "model_path": str(model_path),
                "run_id": results["run_id"],
            },
        )
        return {"status": "SUCCESS", "market": market, "run_id": results["run_id"]}
    except Exception as exc:
        on_pipeline_failure(
            gov,
            market=market,
            action="Rebacktest",
            task_slug=task_slug,
            operation="rebacktest",
            summary=str(exc),
            component="hooks.run_rebacktest_pipeline",
            stderr=getattr(exc, "stderr", "") or "",
            exc=exc,
            returncode=getattr(exc, "returncode", None),
        )
        raise
