import json
import sys
import warnings
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime

# Suppress annoying Gym/Gymnasium warnings from Qlib
warnings.filterwarnings("ignore", category=UserWarning, module="gym")
warnings.filterwarnings("ignore", message=".*Gymnasium.*")

import qlib
from src.assistant.services.artifact_refresh_service import ArtifactRefreshService
from src.common.env_manager import EnvironmentManager
from src.common.paths import MODELS_DIR, PROJECT_ROOT, RUNS_DIR, ARTIFACTS_DIR, REPORTS_DIR
from src.reliability.classifier import classify_failure
from src.workflows.profile_compiler import compile_strategy_profile
from src.governance.service import GovernanceService
from src.research.service import ResearchService
from src.research.registry import register_model

from src.data.quality import generate_data_quality_summary
from src.assistant.data_quality_index import DataQualityIndex
from src.assistant.metadata_db import resolve_metadata_db_path

def get_task_slug(operation: str, market: str) -> str:
    return f"workflow.{operation}.{str(market).lower()}"

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
            markets=markets
        )
        if q.get("ok"):
            idx = DataQualityIndex(db_path=resolve_metadata_db_path(PROJECT_ROOT))
            idx.upsert(
                snapshot_id=str(q.get("snapshot_id")),
                dataset_key="watchlist",
                freq="day",
                market=market,
                latest_calendar_day=str(q.get("latest_calendar_day")),
                summary=q
            )
            return q
    except Exception as e:
        print(f"Failed to generate quality report: {e}")
    return None

def _repair_data(market: str, lookback_days: int = 60) -> bool:
    """
    Attempt to repair market data by running update_data script.
    """
    print(f"--- Attempting Data Repair for {market.upper()} (lookback={lookback_days}d) ---")
    try:
        cmd = [
            sys.executable, "scripts/update_data.py",
            "--market", market,
            "--lookback-days", str(lookback_days)
        ]
        subprocess.run(cmd, check=True, cwd=str(PROJECT_ROOT))
        print(f"--- Data Repair Successful for {market.upper()} ---")
        return True
    except Exception as e:
        print(f"--- Data Repair Failed for {market.upper()}: {e} ---")
        return False

def on_pipeline_start(gov: GovernanceService, market: str, action: str, task_slug: str, details: Optional[Dict[str, Any]] = None) -> None:
    """
    Log start and enforce mutex using workflows table.
    """
    # Enforce mutex using workflows table
    active = [
        w for w in gov.query_workflows(status="RUNNING")
        if w["market"] == str(market).upper() and action in str(w["name"])
    ]
    if active:
        # Check if it's been running for more than 4 hours - consider it stale
        updated_at_str = active[0].get("updated_at")
        if updated_at_str:
            try:
                updated_at = datetime.fromisoformat(updated_at_str)
                now = datetime.now(updated_at.tzinfo)
                if (now - updated_at).total_seconds() > 14400: # 4 hours
                     print(f"[!] Warning: Workflow {active[0]['workflow_id']} is RUNNING but stale. Overriding lock.")
                else:
                    raise RuntimeError(f"Workflow lock active: {active[0]['name']} for {market} is already in status RUNNING (ID: {active[0]['workflow_id']}).")
            except Exception as e:
                if isinstance(e, RuntimeError): raise e
                pass

    gov.update_workflow_status(
        task_slug, # Using task_slug as workflow_id for simplicity in hooks
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

def on_pipeline_success(gov: GovernanceService, market: str, action: str, task_slug: str, details: Optional[Dict[str, Any]] = None) -> None:
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
    exc: Optional[Exception] = None,
    returncode: Optional[int] = None,
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

def on_pipeline_retry(gov: GovernanceService, market: str, action: str, task_slug: str, attempt: int, reason: str, details: Optional[Dict[str, Any]] = None) -> None:
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
    details: Optional[Dict[str, Any]] = None,
):
    """
    Orchestrated training pipeline hook.
    """
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
            details={**(details or {}), "model_type": model_type, "tag": str(tag or "")},
        )
    except RuntimeError as e:
        print(f"[!] {e}")
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
                for m in ["cn", "us"]:
                    args = ["run", "--market", m, "--model_type", str(model_type), "--tag", str(tag)]
                    if profile: args += ["--profile", str(profile)]
                    if strategy_template: args += ["--strategy_template", str(strategy_template)]
                    if cost_params: args += ["--cost_params", str(cost_params)]
                    env.run_in_isolation("src.orchestrator", args)
                on_pipeline_success(gov, market=market, action="Pipeline Run", task_slug=task_slug)
                return {"status": "SUCCESS", "market": "all"}

            # 1. Initialize
            compile_strategy_profile(market=market, profile_path=(profile or "configs/strategy_profile.json"))
            config = research.load_config(market, model_type)
            env.ensure_qlib(market, config)
            env.check_directories([MODELS_DIR, ARTIFACTS_DIR, REPORTS_DIR, RUNS_DIR])

            # 2. Data Preparation
            start_time = config["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["start_time"]
            try:
                config = research.prepare_experiment(market, config, start_time)
            except RuntimeError as e:
                if "No valid tickers found" in str(e) and attempt < max_retries:
                    print(f"Data issue detected: {e}")
                    if _repair_data(market):
                        attempt += 1
                        on_pipeline_retry(gov, market=market, action="Pipeline Run", task_slug=task_slug, attempt=attempt, reason="Data repair triggered")
                        continue
                raise

            # Generate Data Quality Report after prep
            generate_quality_report(market=market)

            # 3. Execution
            results = research.run_training_pipeline(market, config, tag)

            # 4. Finalize
            register_model(market, results["model_path"], config, run_id=results["run_id"], model_tag=tag)
            artifact_refresh.refresh_training_artifacts(market=market)
            
            on_pipeline_success(
                gov,
                market=market,
                action="Pipeline Run",
                task_slug=task_slug,
                details={"model_type": model_type, "tag": str(tag or ""), "run_id": results["run_id"]},
            )
            return {"status": "SUCCESS", "market": market, "run_id": results["run_id"]}
        except Exception as exc:
            if attempt < max_retries:
                attempt += 1
                on_pipeline_retry(gov, market=market, action="Pipeline Run", task_slug=task_slug, attempt=attempt, reason=str(exc))
                print(f"Retrying pipeline (attempt {attempt}/{max_retries})...")
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
    details: Optional[Dict[str, Any]] = None,
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
            details={**(details or {}), "model_type": model_type, "model_path": str(model_path or "")},
        )
    except RuntimeError as e:
        print(f"[!] {e}")
        raise e

    try:
        if market == "all":
            if update_data:
                _repair_data(market="all", lookback_days=30)
            for m in ["cn", "us"]:
                args = ["rebacktest", "--market", m, "--model_type", str(model_type), "--start", str(start), "--end", str(end)]
                if profile: args += ["--profile", str(profile)]
                if tag: args += ["--tag", str(tag)]
                if strategy_template: args += ["--strategy_template", str(strategy_template)]
                if cost_params: args += ["--cost_params", str(cost_params)]
                if not refresh_dashboard_db: args += ["--refresh_dashboard_db", "False"]
                env.run_in_isolation("src.orchestrator", args)
            on_pipeline_success(gov, market=market, action="Rebacktest", task_slug=task_slug)
            return {"status": "SUCCESS", "market": "all"}

        if update_data:
            _repair_data(market=market, lookback_days=30)

        # 1. Initialize
        compile_strategy_profile(market=market, profile_path=(profile or "configs/strategy_profile.json"))
        config = research.load_config(market, model_type)
        
        # Qlib init
        from src.common.qlib_init import build_qlib_init_cfg
        qlib_init_cfg = build_qlib_init_cfg(config.get("qlib_init", {}) or {}, market=market)
        qlib.init(**qlib_init_cfg)

        # 2. Data Preparation
        profile_data = {}
        profile_p = Path(profile or "configs/strategy_profile.json")
        if profile_p.exists():
            with open(profile_p) as f: profile_data = json.load(f)

        config = research.prepare_experiment(market, config, start, end_time=end, profile_data=profile_data)

        # Generate Data Quality Report after prep
        generate_quality_report(market=market)

        # 3. Execution
        m_path = Path(model_path) if model_path else MODELS_DIR / f"{market}_model.pkl"
        results = research.perform_rebacktest(market, m_path, config, profile_data=profile_data, tag=tag)

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
            details={"model_type": model_type, "model_path": str(model_path), "run_id": results["run_id"]},
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
