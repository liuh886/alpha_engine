from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RuntimeSettings:
    """Filesystem settings shared by framework-neutral research workflows."""

    project_root: Path = PROJECT_ROOT
    env: str = "development"
    config_dir: Path = PROJECT_ROOT / "configs"
    data_dir: Path = PROJECT_ROOT / "data"
    reports_dir: Path = PROJECT_ROOT / "reports"
    scripts_dir: Path = PROJECT_ROOT / "scripts"
    artifacts_dir: Path = PROJECT_ROOT / "artifacts"

    @classmethod
    def from_env(cls, *, project_root: str | Path | None = None) -> RuntimeSettings:
        root = Path(project_root) if project_root is not None else PROJECT_ROOT
        env = os.getenv("ALPHA_ENGINE_ENV", "development").strip() or "development"

        return cls(
            project_root=root,
            env=env,
            config_dir=_env_path("TRADING_CONFIG_DIR", root / "configs", root),
            data_dir=_env_path("TRADING_DATA_DIR", root / "data", root),
            reports_dir=_env_path("TRADING_REPORTS_DIR", root / "reports", root),
            scripts_dir=_env_path("TRADING_SCRIPTS_DIR", root / "scripts", root),
            artifacts_dir=_env_path("TRADING_ARTIFACTS_DIR", root / "artifacts", root),
        )

    @property
    def mlruns_dir(self) -> Path:
        return self.artifacts_dir / "mlruns"

    @property
    def models_dir(self) -> Path:
        return self.artifacts_dir / "models"

    @property
    def runs_dir(self) -> Path:
        return self.artifacts_dir / "runs"

    @property
    def archives_dir(self) -> Path:
        return self.artifacts_dir / "archives"

    @property
    def qlib_demo_data_dir(self) -> Path:
        return self.archives_dir / "qlib_demo_data"

    @property
    def dashboard_dir(self) -> Path:
        return self.artifacts_dir / "dashboard"

    @property
    def dashboard_db_path(self) -> Path:
        return self.dashboard_dir / "dashboard_db.json"

    @property
    def pytest_cache_dir(self) -> Path:
        return self.artifacts_dir / ".pytest_cache"


def get_runtime_settings() -> RuntimeSettings:
    return RuntimeSettings.from_env()


def _env_path(name: str, default: Path, project_root: Path) -> Path:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    path = Path(value)
    return path if path.is_absolute() else project_root / path
