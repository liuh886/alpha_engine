from pathlib import Path

from src.common.runtime_settings import RuntimeSettings


def test_runtime_settings_reads_research_directories(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("ALPHA_ENGINE_ENV", "research")
    monkeypatch.setenv("TRADING_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("TRADING_DATA_DIR", "market-data")

    settings = RuntimeSettings.from_env(project_root=tmp_path)

    assert settings.env == "research"
    assert settings.artifacts_dir == tmp_path / "artifacts"
    assert settings.data_dir == tmp_path / "market-data"
    assert settings.dashboard_db_path == tmp_path / "artifacts" / "dashboard" / "dashboard_db.json"


def test_runtime_settings_defaults_to_project_scoped_paths(monkeypatch, tmp_path: Path):
    for name in (
        "TRADING_CONFIG_DIR",
        "TRADING_DATA_DIR",
        "TRADING_REPORTS_DIR",
        "TRADING_SCRIPTS_DIR",
        "TRADING_ARTIFACTS_DIR",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = RuntimeSettings.from_env(project_root=tmp_path)

    assert settings.config_dir == tmp_path / "configs"
    assert settings.data_dir == tmp_path / "data"
    assert settings.reports_dir == tmp_path / "reports"
    assert settings.scripts_dir == tmp_path / "scripts"
    assert settings.artifacts_dir == tmp_path / "artifacts"
