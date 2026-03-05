import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.append(str(ROOT))


def test_resolve_metadata_db_path_uses_env_var(tmp_path: Path, monkeypatch):
    try:
        from src.assistant.metadata_db import resolve_metadata_db_path
    except ModuleNotFoundError:
        pytest.fail("metadata_db module is not implemented yet")

    custom = tmp_path / "custom.db"
    monkeypatch.setenv("TRADING_ASSISTANT_METADATA_DB_PATH", str(custom))
    out = resolve_metadata_db_path(tmp_path)
    assert Path(out) == custom


def test_resolve_metadata_db_path_defaults_under_project_root(tmp_path: Path, monkeypatch):
    try:
        from src.assistant.metadata_db import resolve_metadata_db_path
    except ModuleNotFoundError:
        pytest.fail("metadata_db module is not implemented yet")

    monkeypatch.delenv("TRADING_ASSISTANT_METADATA_DB_PATH", raising=False)
    out = resolve_metadata_db_path(tmp_path)
    assert str(out).replace("\\", "/").endswith("/artifacts/metadata/metadata.db")

