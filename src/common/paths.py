
from src.common.runtime_settings import get_runtime_settings


def get_config_dir():
    return get_runtime_settings().config_dir


def get_data_dir():
    return get_runtime_settings().data_dir


def get_reports_dir():
    return get_runtime_settings().reports_dir


def get_scripts_dir():
    return get_runtime_settings().scripts_dir


def get_artifacts_dir():
    return get_runtime_settings().artifacts_dir


# Static directories (initial values)
CONFIG_DIR = get_config_dir()
DATA_DIR = get_data_dir()
REPORTS_DIR = get_reports_dir()
SCRIPTS_DIR = get_scripts_dir()
ARTIFACTS_DIR = get_artifacts_dir()


def __getattr__(name):
    if name == "CONFIG_DIR":
        return get_config_dir()
    if name == "DATA_DIR":
        return get_data_dir()
    if name == "REPORTS_DIR":
        return get_reports_dir()
    if name == "SCRIPTS_DIR":
        return get_scripts_dir()
    if name == "ARTIFACTS_DIR":
        return get_artifacts_dir()

    if name == "MLRUNS_DIR":
        return get_artifacts_dir() / "mlruns"
    if name == "MODELS_DIR":
        return get_artifacts_dir() / "models"
    if name == "RUNS_DIR":
        return get_artifacts_dir() / "runs"
    if name == "PYTEST_CACHE_DIR":
        return get_artifacts_dir() / ".pytest_cache"

    if name == "ARCHIVES_DIR":
        return get_artifacts_dir() / "archives"
    if name == "QLIB_DEMO_DATA_DIR":
        return (get_artifacts_dir() / "archives") / "qlib_demo_data"

    if name == "DASHBOARD_DIR":
        return get_artifacts_dir() / "dashboard"
    if name == "DASHBOARD_DB_PATH":
        return get_artifacts_dir() / "dashboard" / "dashboard_db.json"

    raise AttributeError(f"module {__name__} has no attribute {name}")


# Still define them for static analysis / IDEs (though they will be overridden by __getattr__ at runtime if accessed as module.NAME)
MLRUNS_DIR = ARTIFACTS_DIR / "mlruns"
MODELS_DIR = ARTIFACTS_DIR / "models"
RUNS_DIR = ARTIFACTS_DIR / "runs"
PYTEST_CACHE_DIR = ARTIFACTS_DIR / ".pytest_cache"
ARCHIVES_DIR = ARTIFACTS_DIR / "archives"
QLIB_DEMO_DATA_DIR = ARCHIVES_DIR / "qlib_demo_data"
DASHBOARD_DIR = ARTIFACTS_DIR / "dashboard"
DASHBOARD_DB_PATH = DASHBOARD_DIR / "dashboard_db.json"
