from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import qlib

from src.common.future_calendar import ensure_calendar_future_file
from src.common.logging import get_logger
from src.common.qlib_init import build_qlib_init_cfg


class EnvironmentManager:
    """
    Manages the Qlib runtime environment, initialization, and process isolation.
    """

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self._initialized_market = None

    def ensure_qlib(self, market: str, config: dict):
        """
        Initialize Qlib for a specific market.
        Handles future calendar files and provider URI resolution.
        """
        market = market.lower()
        qlib_init_cfg = build_qlib_init_cfg(config.get("qlib_init", {}) or {}, market=market)

        # Ensure future calendar file exists (required for Qlib backtest endpoints)
        try:
            provider_uri = qlib_init_cfg.get("provider_uri")
            if provider_uri:
                p_path = Path(provider_uri)
                if not p_path.is_absolute():
                    p_path = self.project_root / p_path
                ensure_calendar_future_file(p_path, freq="day", extra_days=1)
        except Exception as e:
            get_logger(__name__).warning(f"Could not ensure future calendar: {e}")

        # Initialize
        try:
            qlib.init(**qlib_init_cfg)
            self._initialized_market = market
        except Exception:
            if self._initialized_market and self._initialized_market != market:
                raise RuntimeError(
                    f"Qlib already initialized for {self._initialized_market}. "
                    f"Cannot switch to {market} in the same process. Use subprocess isolation."
                )
            # If same market, Qlib usually handles re-init gracefully or we can ignore
            pass

    @staticmethod
    def run_in_isolation(module: str, args: list[str], cwd: Path | None = None):
        """
        Run a command in a fresh python process to avoid Qlib singleton pollution.
        """
        cmd = [sys.executable, "-m", module] + args
        return subprocess.run(cmd, cwd=str(cwd or Path(".")), check=True)

    def check_directories(self, dirs: list[str | Path]):
        """Verify essential directories exist."""
        for d in dirs:
            p = self.project_root / d if not isinstance(d, Path) else d
            p.mkdir(parents=True, exist_ok=True)
