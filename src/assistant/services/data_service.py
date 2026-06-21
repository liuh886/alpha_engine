import datetime
import json
from pathlib import Path

import numpy as np

from src.common.logging import get_logger
from src.dashboard.data_update_job import create_data_update_job

logger = get_logger(__name__)

# Features available in the Qlib binary store (data/watchlist/features/{symbol}/)
AVAILABLE_FEATURES = [
    "close",
    "open",
    "high",
    "low",
    "volume",
    "amount",
    "vwap",
    "money",
    "factor",
    "mkt_us_ma20_dev",
    "mkt_us_ma60_dev",
    "mkt_cn_ma20_dev",
    "mkt_cn_ma60_dev",
]


class DataService:
    def __init__(self, *, project_root: str | Path, python_exe: str):
        self._project_root = Path(project_root)
        self._python_exe = str(python_exe)

    def create_update_job_from_payload(self, payload: dict) -> dict:
        payload = payload or {}
        full = bool(payload.get("full") or False)
        market = str(payload.get("market") or "all").strip().lower() or "all"
        start = str(payload.get("start") or "2020-01-01").strip() or "2020-01-01"
        lookback_days = payload.get("lookback_days")
        try:
            lookback_days = int(lookback_days) if lookback_days is not None else 30
        except Exception:
            logger.debug(
                "Failed to parse lookback_days, using default",
                raw_value=lookback_days,
                exc_info=True,
            )
            lookback_days = 30
        if lookback_days < 0:
            lookback_days = 0

        return create_data_update_job(
            project_root=self._project_root,
            python_exe=self._python_exe,
            full=full,
            market=market,
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
                logger.debug(
                    "Failed to read dashboard DB", path=str(dashboard_db_path), exc_info=True
                )

        latest_snapshot_id = None
        snapshot_status = "unknown"
        snapshot_error = ""
        try:
            snap = snapshot_index.get_latest_manifest(dataset_key="watchlist", freq="day")
            if snap:
                latest_snapshot_id = snap.get("snapshot_id")
                manifest = snap.get("manifest")
                if (
                    not isinstance(manifest, dict)
                    or manifest.get("snapshot_id") != latest_snapshot_id
                ):
                    snapshot_status = "failed"
                    snapshot_error = "indexed snapshot manifest is missing or mismatched"
                else:
                    snapshot_status = "ready"
        except Exception as exc:
            snapshot_status = "failed"
            snapshot_error = str(exc)
            logger.debug("Failed to query latest snapshot", exc_info=True)

        quality_warnings = []
        quality_status = "unknown"
        quality_error = ""
        detailed_issues = {}
        try:
            q = quality_index.get_latest(dataset_key="watchlist", freq="day", market="all")
            if q:
                summary = q.get("summary")
                if not isinstance(summary, dict):
                    quality_status = "failed"
                    quality_error = "quality summary is missing"
                elif not latest_snapshot_id or q.get("snapshot_id") != latest_snapshot_id:
                    quality_status = "failed"
                    quality_error = "quality snapshot mismatch"
                elif not summary.get("ok"):
                    quality_status = "failed"
                    quality_error = str(summary.get("error") or "quality validation failed")
                else:
                    quality_warnings = summary.get("warnings") or []
                    quality_status = "warning" if quality_warnings else "ok"
                    detailed_issues = summary.get("markets") or {}
        except Exception as exc:
            quality_status = "failed"
            quality_error = str(exc)
            logger.debug("Failed to query quality index", exc_info=True)

        # Calculate readiness
        readiness = self._calculate_readiness(latest_cal)
        if "failed" in {snapshot_status, quality_status}:
            status = "failed"
        elif "unknown" in {snapshot_status, quality_status}:
            status = "unknown"
        elif quality_status == "warning":
            status = "warning"
        else:
            status = "ok"

        return {
            "latest_calendar_day": latest_cal,
            "dashboard_db_generated_at": dashboard_generated_at,
            "latest_snapshot_id": latest_snapshot_id,
            "snapshot_status": snapshot_status,
            "snapshot_error": snapshot_error,
            "quality_status": quality_status,
            "quality_error": quality_error,
            "quality_warnings": quality_warnings,
            "detailed_issues": detailed_issues,
            "readiness": readiness,
            "status": status,
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
            line.strip()
            for line in cal_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
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
                raw = np.fromfile(str(bin_path), dtype="<f4")
                # Qlib binary format: 4-byte int32 header (start_index) + float32 data
                # The header is written as int32(0) but read as float32(0.0)
                # Skip the first element (header) to get actual data
                if len(raw) > 1:
                    arr = raw[1:]  # skip the 4-byte header misinterpreted as float
                else:
                    arr = raw
            except Exception:
                logger.debug("Failed to read binary file", path=str(bin_path), exc_info=True)
                continue

            # Pad or truncate to match calendar length
            if len(arr) < n_days:
                logger.debug(
                    "binary_array_short",
                    symbol=sym,
                    feature=feature,
                    expected=n_days,
                    actual=len(arr),
                )
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

    def validate_data_integrity(self, market: str = "us") -> dict:
        """Run data integrity checks and return a report.

        Checks:
        1. Instrument/feature sync — ghosts and missing entries
        2. Binary array length consistency
        3. Temporal gap detection (missing trading days)
        4. Value anomalies (NaN ratio, zero clusters)
        """
        features_dir = self._project_root / "data" / "watchlist" / "features"
        cal_path = self._project_root / "data" / "watchlist" / "calendars" / "day.txt"
        inst_path = self._project_root / "data" / "watchlist" / "instruments" / f"{market}.txt"

        report: dict = {
            "ok": True,
            "market": market,
            "checks": {},
            "warnings": [],
            "errors": [],
        }

        # 1. Instrument/feature sync
        feature_syms = set()
        if features_dir.exists():
            feature_syms = set(d.name for d in features_dir.iterdir() if d.is_dir())

        inst_syms = set()
        if inst_path.exists():
            for line in inst_path.read_text(encoding="utf-8").splitlines():
                parts = line.strip().split("\t")
                if parts and parts[0]:
                    inst_syms.add(parts[0])

        ghosts = inst_syms - feature_syms
        missing = feature_syms - inst_syms
        report["checks"]["instrument_sync"] = {
            "instruments": len(inst_syms),
            "feature_dirs": len(feature_syms),
            "ghosts": sorted(ghosts),
            "missing": sorted(missing),
        }
        if ghosts:
            report["warnings"].append(
                f"{len(ghosts)} symbols in instruments but no features: {sorted(ghosts)[:5]}"
            )
        if missing:
            report["warnings"].append(
                f"{len(missing)} symbols with features but not in instruments: {sorted(missing)[:5]}"
            )

        # 2. Binary array length consistency
        if not cal_path.exists():
            report["errors"].append("Calendar file not found")
            return report

        dates = [
            line.strip()
            for line in cal_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        n_days = len(dates)
        (n_days + 1) * 4  # +1 for int32 header

        length_issues = []
        for sym in sorted(inst_syms):
            close_path = features_dir / sym / "close.day.bin"
            if not close_path.exists():
                continue
            actual_bytes = close_path.stat().st_size
            actual_floats = (actual_bytes - 4) // 4  # subtract header
            if abs(actual_floats - n_days) > 1:
                length_issues.append({"symbol": sym, "expected": n_days, "actual": actual_floats})

        report["checks"]["binary_lengths"] = {
            "expected_floats": n_days,
            "issues": length_issues[:20],  # cap output
        }
        if length_issues:
            report["warnings"].append(
                f"{len(length_issues)} symbols have mismatched binary lengths"
            )

        # 3. Temporal gap detection — check close feature for NaN gaps
        gap_symbols = []
        nan_heavy = []
        for sym in sorted(inst_syms)[:100]:  # sample first 100 for performance
            close_path = features_dir / sym / "close.day.bin"
            if not close_path.exists():
                continue
            try:
                raw = np.fromfile(str(close_path), dtype="<f4")
                arr = raw[1:] if len(raw) > 1 else raw  # skip header
                if len(arr) < n_days:
                    arr = np.concatenate([arr, np.full(n_days - len(arr), np.nan)])

                # Count NaN ratio
                nan_count = int(np.sum(np.isnan(arr)))
                nan_ratio = nan_count / n_days
                if nan_ratio > 0.5:
                    nan_heavy.append({"symbol": sym, "nan_ratio": round(nan_ratio, 3)})

                # Find gaps in valid data (consecutive NaN runs > 5 days)
                is_nan = np.isnan(arr)
                gap_start = None
                for i, v in enumerate(is_nan):
                    if v and gap_start is None:
                        gap_start = i
                    elif not v and gap_start is not None:
                        gap_len = i - gap_start
                        if gap_len > 5:
                            gap_symbols.append(
                                {
                                    "symbol": sym,
                                    "gap_start": dates[gap_start]
                                    if gap_start < len(dates)
                                    else str(gap_start),
                                    "gap_end": dates[i] if i < len(dates) else str(i),
                                    "gap_days": gap_len,
                                }
                            )
                        gap_start = None
            except Exception:
                continue

        report["checks"]["temporal_gaps"] = {
            "gaps_found": len(gap_symbols),
            "gaps": gap_symbols[:20],
            "nan_heavy_symbols": nan_heavy[:10],
        }
        if gap_symbols:
            report["warnings"].append(f"{len(gap_symbols)} temporal gaps (>5 days) detected")
        if nan_heavy:
            report["warnings"].append(f"{len(nan_heavy)} symbols have >50% NaN values")

        # Overall status
        if report["errors"]:
            report["ok"] = False
        return report

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
            logger.debug(
                "Failed to parse calendar date for readiness check",
                latest_cal=latest_cal,
                exc_info=True,
            )
            return "UNKNOWN"
