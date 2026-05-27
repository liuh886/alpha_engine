from pathlib import Path

from src.common.runtime_settings import RuntimeSettings


def test_runtime_settings_reads_port_cors_and_auth(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("API_PORT", "9001")
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:9001, https://alpha.example")
    monkeypatch.setenv("TRADING_UI_USER", "operator")
    monkeypatch.setenv("TRADING_UI_PASSWORD", "secret")
    monkeypatch.setenv("TRADING_ARTIFACTS_DIR", str(tmp_path / "artifacts"))

    settings = RuntimeSettings.from_env(project_root=tmp_path)

    assert settings.api_port == 9001
    assert settings.cors_origins == ("http://localhost:9001", "https://alpha.example")
    assert settings.trading_ui_user == "operator"
    assert settings.trading_ui_password == "secret"
    assert settings.artifacts_dir == tmp_path / "artifacts"
    assert settings.dashboard_db_path == tmp_path / "artifacts" / "dashboard" / "dashboard_db.json"


def test_runtime_settings_keeps_legacy_port_env(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("API_PORT", raising=False)
    monkeypatch.setenv("PORT", "8100")

    settings = RuntimeSettings.from_env(project_root=tmp_path)

    assert settings.api_port == 8100
