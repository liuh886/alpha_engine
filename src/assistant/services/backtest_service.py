from __future__ import annotations

from pathlib import Path

from src.common import paths
from src.dashboard.backtest_job import create_backtest_job
from src.dashboard.run_lookup import get_run_model_path, get_run_profile_path


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

        strategy_template = payload.get("strategy_template")
        cost_params = payload.get("cost_params")

        profile_path = str(payload.get("profile_path") or "configs/strategy_profile.json").strip() or "configs/strategy_profile.json"

        resolved_mode = mode or ("rebacktest" if run_id else "train")

        model_path = str(payload.get("model_path") or "").strip() or None
        if resolved_mode == "rebacktest":
            if not model_path and run_id:
                model_path = get_run_model_path(run_id, dashboard_db_path=self._dashboard_db_path)
            if not model_path:
                raise ValueError("Could not resolve model_path for selected run_id; missing params.model_path?")

            if run_id:
                # Prefer the exact strategy profile snapshot stored with the run artifacts.
                prof_snapshot = self._find_mlruns_profile_snapshot(run_id)
                if prof_snapshot:
                    profile_path = str(prof_snapshot)
                else:
                    prof = get_run_profile_path(run_id, dashboard_db_path=self._dashboard_db_path)
                    if prof:
                        profile_path = str(prof)

        return create_backtest_job(
            market=market,
            model_type=model_type,
            mode=resolved_mode,
            model_path=model_path,
            start=start,
            end=end,
            project_root=self._project_root,
            python_exe=self._python_exe,
            profile_path=profile_path,
            tag=tag,
            strategy_template=strategy_template,
            cost_params=cost_params,
        )

    def _find_mlruns_profile_snapshot(self, run_id: str) -> Path | None:
        """
        Locate `mlruns/<exp>/<run_id>/artifacts/strategy_profile.json` if present.
        """
        run_id = str(run_id or "").strip()
        if not run_id:
            return None

        mlruns_root = paths.MLRUNS_DIR
        if not mlruns_root.exists():
            return None

        for exp_dir in mlruns_root.iterdir():
            if not exp_dir.is_dir():
                continue
            snap = exp_dir / run_id / "artifacts" / "strategy_profile.json"
            if snap.exists():
                return snap
        return None
