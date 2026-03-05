import sys
from pathlib import Path

from src.assistant.arena_index import ArenaIndex
from src.assistant.backtest_equity_curve_index import BacktestEquityCurveIndex
from src.assistant.data_quality_index import DataQualityIndex
from src.assistant.data_snapshot_index import DataSnapshotIndex
from src.assistant.job_service import JobService
from src.assistant.metadata_db import resolve_metadata_db_path
from src.assistant.model_registry_index import ModelRegistryIndex
from src.assistant.report_index import ReportIndex
from src.assistant.run_index import RunIndex
from src.assistant.services.backtest_service import BacktestService
from src.assistant.services.data_service import DataService
from src.assistant.services.model_service import ModelService
from src.assistant.services.training_service import TrainingService
from src.common.paths import DASHBOARD_DB_PATH

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_JOB_SERVICE = None
_BACKTEST_SERVICE = None
_TRAINING_SERVICE = None
_DATA_SERVICE = None
_MODEL_SERVICE = None
_RUN_INDEX = None
_SNAPSHOT_INDEX = None
_QUALITY_INDEX = None
_MODEL_INDEX = None
_REPORT_INDEX = None
_CURVE_INDEX = None
_ARENA_INDEX = None


def get_job_service() -> JobService:
    global _JOB_SERVICE
    if _JOB_SERVICE is None:
        _JOB_SERVICE = JobService(db_path=resolve_metadata_db_path(PROJECT_ROOT), project_root=PROJECT_ROOT)
    return _JOB_SERVICE


def get_backtest_service() -> BacktestService:
    global _BACKTEST_SERVICE
    if _BACKTEST_SERVICE is None:
        _BACKTEST_SERVICE = BacktestService(
            project_root=PROJECT_ROOT,
            python_exe=sys.executable,
            dashboard_db_path=DASHBOARD_DB_PATH,
        )
    return _BACKTEST_SERVICE


def get_training_service() -> TrainingService:
    global _TRAINING_SERVICE
    if _TRAINING_SERVICE is None:
        _TRAINING_SERVICE = TrainingService(
            project_root=PROJECT_ROOT,
            python_exe=sys.executable,
        )
    return _TRAINING_SERVICE


def get_model_index() -> ModelRegistryIndex:
    global _MODEL_INDEX
    if _MODEL_INDEX is None:
        _MODEL_INDEX = ModelRegistryIndex(db_path=resolve_metadata_db_path(PROJECT_ROOT))
    return _MODEL_INDEX


def get_model_service() -> ModelService:
    global _MODEL_SERVICE
    if _MODEL_SERVICE is None:
        _MODEL_SERVICE = ModelService(
            project_root=PROJECT_ROOT,
            model_index=get_model_index(),
        )
    return _MODEL_SERVICE


def get_data_service() -> DataService:
    global _DATA_SERVICE
    if _DATA_SERVICE is None:
        _DATA_SERVICE = DataService(project_root=PROJECT_ROOT, python_exe=sys.executable)
    return _DATA_SERVICE


def get_run_index() -> RunIndex:
    global _RUN_INDEX
    if _RUN_INDEX is None:
        _RUN_INDEX = RunIndex(db_path=resolve_metadata_db_path(PROJECT_ROOT))
    return _RUN_INDEX


def get_snapshot_index() -> DataSnapshotIndex:
    global _SNAPSHOT_INDEX
    if _SNAPSHOT_INDEX is None:
        _SNAPSHOT_INDEX = DataSnapshotIndex(db_path=resolve_metadata_db_path(PROJECT_ROOT))
    return _SNAPSHOT_INDEX


def get_quality_index() -> DataQualityIndex:
    global _QUALITY_INDEX
    if _QUALITY_INDEX is None:
        _QUALITY_INDEX = DataQualityIndex(db_path=resolve_metadata_db_path(PROJECT_ROOT))
    return _QUALITY_INDEX


def get_report_index() -> ReportIndex:
    global _REPORT_INDEX
    if _REPORT_INDEX is None:
        _REPORT_INDEX = ReportIndex(db_path=resolve_metadata_db_path(PROJECT_ROOT))
    return _REPORT_INDEX


def get_curve_index() -> BacktestEquityCurveIndex:
    global _CURVE_INDEX
    if _CURVE_INDEX is None:
        _CURVE_INDEX = BacktestEquityCurveIndex(db_path=resolve_metadata_db_path(PROJECT_ROOT))
    return _CURVE_INDEX


def get_arena_index() -> ArenaIndex:
    global _ARENA_INDEX
    if _ARENA_INDEX is None:
        _ARENA_INDEX = ArenaIndex(db_path=resolve_metadata_db_path(PROJECT_ROOT))
    return _ARENA_INDEX
