import datetime
import json
from pathlib import Path

import numpy as np

from src.common.logging import get_logger
from src.dashboard.data_update_job import create_data_update_job

logger = get_logger(__name__)

# Features available in the Qlib binary store (data/watchlist/features/{symbol}/)
AVAILABLE_FEATURES = [
    "close", "open", "high", "low", "volume", "amount", "vwap", "money", "factor",
    "mkt_us_ma20_dev", "mkt_us_ma60_dev", "mkt_cn_ma20_dev", "mkt_cn_ma60_dev",
]


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
            logger.debug("Failed to parse lookback_days, using default", raw_value=lookback_days, exc_info=True)
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
            logger.debug("Failed to read instruments file", path=str(inst_path), exc_info=True)
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
                logger.debug("Failed to read calendar file", path=str(cal_path), exc_info=True)

        dashboard_generated_at = None
        if dashboard_db_path.exists():
            try:
                db = json.loads(dashboard_db_path.read_text(encoding="utf-8"))
                dashboard_generated_at = db.get("generated_at")
            except Exception:
                logger.debug("Failed to read dashboard DB", path=str(dashboard_db_path), exc_info=True)

        latest_snapshot_id = None
        try:
            snap = snapshot_index.get_latest(dataset_key="watchlist", freq="day")
            if snap:
                latest_snapshot_id = snap.get("snapshot_id")
        except Exception:
            logger.debug("Failed to query latest snapshot", exc_info=True)

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
            logger.debug("Failed to query quality index", exc_info=True)

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

    def get_completeness_matrix(self, market: str = "us", feature: str = "close") -> dict:
        """Read Qlib binary files directly and return a completeness/value matrix.

        Returns {symbols: [...], dates: [...], values: [[float|null]]}
        For coverage mode (feature=close), values are 1.0 (present) or null (missing).
        For value mode (feature=volume/amount/etc), values are the actual feature values or null.
        """
        features_dir = self._project_root / "data" / "watchlist" / "features"
        cal_path = self._project_root / "data" / "watchlist" / "calendars" / "day.txt"
        inst_path = self._project_root / "data" / "watchlist" / "instruments" / f"{market}.txt"

        if not cal_path.exists() or not inst_path.exists():
            return {"symbols": [], "dates": [], "values": []}

        # Read calendar dates
        dates = [
            line.strip() for line in cal_path.read_text(encoding="utf-8").splitlines() if line.strip()
        ]
        n_days = len(dates)

        # Read instruments for this market
        raw_lines = inst_path.read_text(encoding="utf-8").splitlines()
        symbols = [line.split("\t")[0] for line in raw_lines if line.strip()]

        # Determine the binary filename
        # Market-specific features use mkt_{market}_ prefix
        if feature.startswith("mkt_"):
            bin_name = f"{feature}.day.bin"
        else:
            bin_name = f"{feature}.day.bin"

        is_coverage = feature == "close"
        values = []
        valid_symbols = []

        for sym in symbols:
            bin_path = features_dir / sym / bin_name
            if not bin_path.exists():
                continue

            try:
                arr = np.fromfile(str(bin_path), dtype="<f4")
            except Exception:
                logger.debug("Failed to read binary file", path=str(bin_path), exc_info=True)
                continue

            # Pad or truncate to match calendar length
            if len(arr) < n_days:
                arr = np.concatenate([arr, np.full(n_days - len(arr), np.nan)])
            elif len(arr) > n_days:
                arr = arr[:n_days]

            if is_coverage:
                row = [1.0 if not np.isnan(v) else None for v in arr]
            else:
                row = [round(float(v), 6) if not np.isnan(v) else None for v in arr]

            values.append(row)
            valid_symbols.append(sym)

        return {"symbols": valid_symbols, "dates": dates, "values": values}

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
            logger.debug("Failed to parse calendar date for readiness check", latest_cal=latest_cal, exc_info=True)
            return "UNKNOWN"
