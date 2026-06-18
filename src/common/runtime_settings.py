from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class RuntimeSettings:
    project_root: Path = PROJECT_ROOT
    env: str = "development"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: tuple[str, ...] = (
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    )
    trading_ui_user: str | None = None
    trading_ui_password: str | None = None
    config_dir: Path = PROJECT_ROOT / "configs"
    data_dir: Path = PROJECT_ROOT / "data"
    reports_dir: Path = PROJECT_ROOT / "reports"
    scripts_dir: Path = PROJECT_ROOT / "scripts"
    artifacts_dir: Path = PROJECT_ROOT / "artifacts"
    static_site_dir: Path = PROJECT_ROOT / "qlib-dashboard" / "dist"

    @classmethod
    def from_env(cls, *, project_root: str | Path | None = None) -> RuntimeSettings:
        root = Path(project_root) if project_root is not None else PROJECT_ROOT
        env = os.getenv("ALPHA_ENGINE_ENV", "development").strip() or "development"
        api_port = _env_int("API_PORT", _env_int("PORT", 8000))
        cors_raw = os.getenv("CORS_ORIGINS") or os.getenv("ALLOWED_ORIGINS") or ""

        return cls(
            project_root=root,
            env=env,
            api_host=os.getenv("API_HOST", "0.0.0.0").strip() or "0.0.0.0",
            api_port=api_port,
            cors_origins=_parse_csv(cors_raw) or cls.cors_origins,
            trading_ui_user=_env_optional("TRADING_UI_USER"),
            trading_ui_password=_env_optional("TRADING_UI_PASSWORD"),
            config_dir=_env_path("TRADING_CONFIG_DIR", root / "configs"),
            data_dir=_env_path("TRADING_DATA_DIR", root / "data"),
            reports_dir=_env_path("TRADING_REPORTS_DIR", root / "reports"),
            scripts_dir=_env_path("TRADING_SCRIPTS_DIR", root / "scripts"),
            artifacts_dir=_env_path("TRADING_ARTIFACTS_DIR", root / "artifacts"),
            static_site_dir=_env_path("TRADING_STATIC_SITE_DIR", root / "qlib-dashboard" / "dist"),
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


def _env_optional(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def _parse_csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in value.split(",") if item.strip())
