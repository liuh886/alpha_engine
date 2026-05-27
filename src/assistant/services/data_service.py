import datetime
import json
from pathlib import Path

from src.dashboard.data_update_job import create_data_update_job


class DataService:
    def __init__(self, *, project_root: str | Path, python_exe: str):
        self._project_root = Path(project_root)
        self._python_exe = str(python_exe)

    def create_update_job_from_payload(self, payload: dict) -> dict:
        payload = payload or {}
        full = bool(payload.get("full") or False)
        start = str(payload.get("start") or "2020-01-01").strip() or "2020-01-01"
        lookback_days = payload.get("lookback_days")
        try:
            lookback_days = int(lookback_days) if lookback_days is not None else 30
        except Exception:
            lookback_days = 30
        if lookback_days < 0:
            lookback_days = 0

        return create_data_update_job(
            project_root=self._project_root,
            python_exe=self._python_exe,
            full=full,
            start=start,
            lookback_days=lookback_days,
        )

    def get_instruments(self, market: str = "us") -> list[str]:
        inst_path = self._project_root / "data" / "watchlist" / "instruments" / f"{market}.txt"
        if not inst_path.exists():
            return []
        try:
            lines = inst_path.read_text(encoding="utf-8").splitlines()
            return [line.split("\t")[0] for line in lines if line.strip()]
        except Exception:
            return []

    def get_data_status(self, dashboard_db_path: Path, snapshot_index, quality_index) -> dict:
        latest_cal = None
        cal_path = self._project_root / "data" / "watchlist" / "calendars" / "day.txt"
        if cal_path.exists():
            try:
                lines = cal_path.read_text(encoding="utf-8", errors="replace").splitlines()
                for line in reversed(lines):
                    line = str(line).strip()
                    if line:
                        latest_cal = line
                        break
            except Exception:
                pass

        dashboard_generated_at = None
        if dashboard_db_path.exists():
            try:
                db = json.loads(dashboard_db_path.read_text(encoding="utf-8"))
                dashboard_generated_at = db.get("generated_at")
            except Exception:
                pass

        latest_snapshot_id = None
        try:
            snap = snapshot_index.get_latest(dataset_key="watchlist", freq="day")
            if snap:
                latest_snapshot_id = snap.get("snapshot_id")
        except Exception:
            pass

        quality_warnings = []
        quality_status = "ok"
        detailed_issues = {}
        try:
            q = quality_index.get_latest(dataset_key="watchlist", freq="day", market="all")
            if q and isinstance(q.get("summary"), dict):
                quality_warnings = q["summary"].get("warnings") or []
                if quality_warnings:
                    quality_status = "warning"
                detailed_issues = q["summary"].get("markets") or {}
        except Exception:
            pass

        # Calculate readiness
        readiness = self._calculate_readiness(latest_cal)

        return {
            "latest_calendar_day": latest_cal,
            "dashboard_db_generated_at": dashboard_generated_at,
            "latest_snapshot_id": latest_snapshot_id,
            "quality_status": quality_status,
            "quality_warnings": quality_warnings,
            "detailed_issues": detailed_issues,
            "readiness": readiness,
            "updated_at": datetime.datetime.now().isoformat(),
        }

    def _calculate_readiness(self, latest_cal: str | None) -> str:
        if not latest_cal:
            return "NOT_INITIALIZED"
        try:
            latest_dt = datetime.datetime.strptime(latest_cal, "%Y-%m-%d").date()
            today = datetime.date.today()
            diff = (today - latest_dt).days
            if diff > 4:
                return "STALE"
            if today.weekday() in [1, 2, 3, 4] and diff > 1:
                return "STALE"
            if today.weekday() == 0 and diff > 3:
                return "STALE"
            return "READY"
        except Exception:
            return "UNKNOWN"
