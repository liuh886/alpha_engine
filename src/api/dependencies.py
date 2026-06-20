import sys
from pathlib import Path

from src.assistant.arena_index import ArenaIndex
from src.assistant.backtest_equity_curve_index import BacktestEquityCurveIndex
from src.assistant.data_quality_index import DataQualityIndex
from src.assistant.data_snapshot_index import DataSnapshotIndex
from src.assistant.job_coordinator import JobCoordinator
from src.assistant.job_service import JobService
from src.assistant.metadata_db import resolve_metadata_db_path
from src.assistant.model_registry_index import ModelRegistryIndex
from src.assistant.report_index import ReportIndex
from src.assistant.run_index import RunIndex
from src.assistant.services.artifact_gateway import ArtifactGateway
from src.assistant.services.asset_inspection_service import AssetInspectionService
from src.assistant.services.backtest_service import BacktestService
from src.assistant.services.data_service import DataService
from src.assistant.services.model_service import ModelService
from src.assistant.services.report_service import ReportService
from src.assistant.services.training_service import TrainingService
from src.common.paths import DASHBOARD_DB_PATH
from src.research.evidence import EvidenceLedger

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_job_service() -> JobService:
    # Always fresh to respect environment changes in tests
    return JobService(db_path=resolve_metadata_db_path(PROJECT_ROOT), project_root=PROJECT_ROOT)


def get_job_coordinator() -> JobCoordinator:
    return JobCoordinator(get_job_service())


def get_backtest_service() -> BacktestService:
    return BacktestService(
        project_root=PROJECT_ROOT,
        python_exe=sys.executable,
        dashboard_db_path=DASHBOARD_DB_PATH,
    )


def get_training_service() -> TrainingService:
    return TrainingService(
        project_root=PROJECT_ROOT,
        python_exe=sys.executable,
    )


def get_model_index() -> ModelRegistryIndex:
    return ModelRegistryIndex(db_path=resolve_metadata_db_path(PROJECT_ROOT))


def get_model_service() -> ModelService:
    return ModelService(
        project_root=PROJECT_ROOT,
        model_index=get_model_index(),
    )


def get_data_service() -> DataService:
    return DataService(project_root=PROJECT_ROOT, python_exe=sys.executable)


def get_asset_inspection_service() -> AssetInspectionService:
    return AssetInspectionService(project_root=PROJECT_ROOT, model_index=get_model_index())


def get_artifact_gateway() -> ArtifactGateway:
    from src.common.paths import ARTIFACTS_DIR

    return ArtifactGateway(artifacts_dir=ARTIFACTS_DIR)


def get_evidence_ledger() -> EvidenceLedger:
    return EvidenceLedger()


def get_report_service() -> ReportService:
    return ReportService(
        project_root=PROJECT_ROOT, report_index=get_report_index(), job_service=get_job_service()
    )


def get_run_index() -> RunIndex:
    return RunIndex(db_path=resolve_metadata_db_path(PROJECT_ROOT))


def get_snapshot_index() -> DataSnapshotIndex:
    return DataSnapshotIndex(db_path=resolve_metadata_db_path(PROJECT_ROOT))


def get_quality_index() -> DataQualityIndex:
    return DataQualityIndex(db_path=resolve_metadata_db_path(PROJECT_ROOT))


def get_report_index() -> ReportIndex:
    return ReportIndex(db_path=resolve_metadata_db_path(PROJECT_ROOT))


def get_curve_index() -> BacktestEquityCurveIndex:
    return BacktestEquityCurveIndex(db_path=resolve_metadata_db_path(PROJECT_ROOT))


def get_arena_index() -> ArenaIndex:
    return ArenaIndex(db_path=resolve_metadata_db_path(PROJECT_ROOT))


def get_stock_decision_engine():
    from src.strategies.stock_decision_engine import StockDecisionEngine

    return StockDecisionEngine()
