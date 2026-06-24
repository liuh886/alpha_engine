from __future__ import annotations

import time
import uuid
from datetime import datetime
from pathlib import Path

from src.common.paths import RUNS_DIR
from src.dashboard.run_lookup import get_run_model_path, get_run_profile_path
from src.workflows.commands import build_backtest_command_envelopes, build_workflow_commands


class BacktestService:
    def __init__(self, *, project_root: str | Path, python_exe: str, dashboard_db_path: str | Path):
        self._project_root = Path(project_root)
        self._python_exe = str(python_exe)
        self._dashboard_db_path = Path(dashboard_db_path)

    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def python_exe(self) -> str:
        return self._python_exe

    @property
    def dashboard_db_path(self) -> Path:
        return self._dashboard_db_path

    def create_job_from_payload(self, payload: dict) -> dict:
        payload = payload or {}
        market = str(payload.get("market") or "").lower().strip()
        model_type = str(payload.get("model_type") or "lgbm").lower().strip() or "lgbm"
        mode = str(payload.get("mode") or "").lower().strip()
        run_id = str(payload.get("run_id") or "").strip()
        start = str(payload.get("start") or "2025-01-01").strip() or "2025-01-01"
        end = str(payload.get("end") or "latest").strip() or "latest"
        tag = str(payload.get("tag") or "").strip() or None
        snapshot_id = str(payload.get("snapshot_id") or "").strip() or None

        strategy_template = payload.get("strategy_template")
        cost_params = payload.get("cost_params")

        profile_path = (
            str(payload.get("profile_path") or "configs/strategy_profile.json").strip()
            or "configs/strategy_profile.json"
        )

        resolved_mode = mode or ("rebacktest" if run_id else "train")

        model_path = str(payload.get("model_path") or "").strip() or None
        if resolved_mode == "rebacktest":
            if not model_path and run_id:
                model_path = get_run_model_path(run_id, dashboard_db_path=self._dashboard_db_path)
            if not model_path:
                raise ValueError(
                    "Could not resolve model_path for selected run_id; missing params.model_path?"
                )

            if run_id:
                # Prefer the exact strategy profile snapshot stored with the run artifacts.
                prof_snapshot = self._find_mlruns_profile_snapshot(run_id)
                if prof_snapshot:
                    profile_path = str(prof_snapshot)
                else:
                    prof = get_run_profile_path(run_id, dashboard_db_path=self._dashboard_db_path)
                    if prof:
                        profile_path = str(prof)

        if market not in {"cn", "us"}:
            raise ValueError("market must be 'cn' or 'us'")
        if resolved_mode not in {"train", "rebacktest"}:
            raise ValueError("mode must be 'train' or 'rebacktest'")
        if not tag:
            tag = f"DB_{resolved_mode.upper()}_{datetime.now().strftime('%Y%m%d_%H%M')}"

        job_id = uuid.uuid4().hex
        log_path = RUNS_DIR / f"dashboard_backtest_{market}_{job_id}.log"
        command_envelopes = build_backtest_command_envelopes(
            market=market,
            model_type=model_type,
            profile_path=profile_path,
            mode=resolved_mode,
            model_path=model_path,
            start=start,
            end=end,
            tag=tag,
            strategy_template=strategy_template,
            cost_params=cost_params,
            snapshot_id=snapshot_id,
        )
        commands = build_workflow_commands(python_exe=self._python_exe, envelopes=command_envelopes)

        return {
            "id": job_id,
            "type": "backtest",
            "market": market,
            "model_type": model_type,
            "mode": resolved_mode,
            "tag": tag,
            "strategy_template": strategy_template,
            "cost_params": cost_params,
            "status": "queued",
            "created_at": time.time(),
            "log_path": str(log_path),
            "command_envelopes": [envelope.to_dict() for envelope in command_envelopes],
            "commands": commands,
        }

    def _find_mlruns_profile_snapshot(self, run_id: str) -> Path | None:
        """
        Locate `mlruns/<exp>/<run_id>/artifacts/strategy_profile.json` if present.
        """
        run_path = self.get_run_path(run_id)
        if not run_path:
            return None
        snap = run_path / "artifacts" / "strategy_profile.json"
        return snap if snap.exists() else None

    def get_run_path(self, run_id: str) -> Path | None:
        """
        Resolves the physical directory path for a specific MLflow run ID.
        Checks all possible mlruns locations (MLRUNS_DIR, project_root/mlruns, artifacts/mlruns).
        """
        from src.common.paths import MLRUNS_DIR

        run_id = str(run_id or "").strip()
        if not run_id:
            return None

        mlruns_dirs = [
            MLRUNS_DIR,
            self._project_root / "mlruns",
            self._project_root / "artifacts" / "mlruns",
        ]
        for m_dir in mlruns_dirs:
            if not m_dir.exists():
                continue
            for exp_dir in m_dir.iterdir():
                # Skip .trash only
                if not exp_dir.is_dir() or exp_dir.name == ".trash":
                    continue
                cand = exp_dir / run_id
                if cand.exists():
                    return cand
        return None

    def get_profit_attribution(self, run_id: str) -> dict:
        """
        Retrieves real profit attribution data from Qlib artifacts via the dashboard parser.
        """
        from src.dashboard.artifact_parser import parse_profit_attribution

        run_path = self.get_run_path(run_id)
        if not run_path:
            raise ValueError(f"Run artifacts not found for {run_id}")

        return parse_profit_attribution(run_path)

    def get_trading_ledger(self, run_id: str) -> dict:
        """
        Retrieves the real execution ledger (Holdings & Trades) from Qlib artifacts.
        """
        from src.dashboard.artifact_parser import parse_detailed_ledger

        run_path = self.get_run_path(run_id)
        if not run_path:
            raise ValueError(f"Run artifacts not found for {run_id}")

        return parse_detailed_ledger(run_path)

    def get_alpha_decomposition(self, run_id: str) -> dict:
        """
        Computes alpha decomposition: selection, timing, sizing, cost, beta.
        """
        from src.dashboard.artifact_parser import compute_alpha_decomposition

        run_path = self.get_run_path(run_id)
        if not run_path:
            raise ValueError(f"Run artifacts not found for {run_id}")

        return compute_alpha_decomposition(run_path)

    def delete_run(self, run_id: str) -> bool:
        """
        Hard-deletes a backtest run from the filesystem, metadata database, and dashboard index.
        """
        from src.common.paths import MLRUNS_DIR
        from src.dashboard.run_deletion import delete_backtest_run

        ok = delete_backtest_run(
            run_id,
            mlruns_root=MLRUNS_DIR,
            dashboard_json_path=self._dashboard_db_path,
            model_list_path=self._project_root / "models" / "model_list.yaml",
            project_root=self._project_root,
        )
        if ok:
            # Rebuild dashboard cache if needed
            try:
                import subprocess
                import sys

                subprocess.run(
                    [sys.executable, "scripts/build_dashboard_db.py"],
                    cwd=str(self._project_root),
                    check=False,
                )
            except Exception:
                pass
        return ok
