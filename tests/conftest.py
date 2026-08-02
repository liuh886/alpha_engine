"""Root conftest for Alpha Engine test isolation and mutation safety."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ARTIFACTS = ROOT / "artifacts"
PRODUCTION_MLRUNS = ROOT / "mlruns"
PRODUCTION_DATA = ROOT / "data"
PRODUCTION_PATHS = {PRODUCTION_ARTIFACTS, PRODUCTION_MLRUNS, PRODUCTION_DATA}


@pytest.fixture(autouse=True)
def _isolate_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect artifact writes to a test-local directory."""

    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TRADING_ARTIFACTS_DIR", str(artifact_root))

    try:
        import src.common.paths as _paths

        monkeypatch.setattr(_paths, "ARTIFACTS_DIR", artifact_root)
        monkeypatch.setattr(_paths, "MODELS_DIR", artifact_root / "models")
        monkeypatch.setattr(_paths, "MLRUNS_DIR", artifact_root / "mlruns")
        monkeypatch.setattr(_paths, "RUNS_DIR", artifact_root / "runs")
        monkeypatch.setattr(_paths, "DASHBOARD_DIR", artifact_root / "dashboard")
        monkeypatch.setattr(
            _paths,
            "DASHBOARD_DB_PATH",
            artifact_root / "dashboard" / "dashboard_db.json",
        )
        monkeypatch.setattr(_paths, "ARCHIVES_DIR", artifact_root / "archives")
    except ImportError:
        pass

    _patch_consumer_paths(monkeypatch, artifact_root)
    yield


@pytest.fixture(autouse=True)
def _mutation_guard(monkeypatch: pytest.MonkeyPatch):
    """Fail tests that write to production artifact, MLflow or data paths."""

    import builtins

    real_open = builtins.open

    def guarded_open(file, mode="r", *args, **kwargs):
        if isinstance(mode, str) and any(character in mode for character in ("w", "a", "x")):
            try:
                resolved = Path(file).resolve()
            except (TypeError, OSError):
                return real_open(file, mode, *args, **kwargs)

            for production_path in PRODUCTION_PATHS:
                if resolved == production_path or _is_relative(resolved, production_path):
                    raise PermissionError(
                        f"[mutation-guard] Test attempted to write to production path: {resolved}"
                    )

        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", guarded_open)
    yield


def _is_relative(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _patch_consumer_paths(monkeypatch: pytest.MonkeyPatch, artifact_root: Path) -> None:
    consumer_patches: list[tuple[str, str, Path]] = [
        ("src.research.registry", "MODELS_DIR", artifact_root / "models"),
    ]
    for module_path, attribute_name, new_value in consumer_patches:
        try:
            module = __import__(module_path, fromlist=[attribute_name])
            monkeypatch.setattr(module, attribute_name, new_value)
        except (ImportError, AttributeError):
            pass


def _enforce_approved_skip(item: pytest.Item, phase: str) -> None:
    if not item.get_closest_marker("approved_skip"):
        raise pytest.fail(
            f"Test {item.nodeid} was skipped ({phase}) without "
            "@pytest.mark.approved_skip. Add the marker with a reason or fix the test.",
            pytrace=False,
        )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item: pytest.Item):
    outcome = yield
    try:
        outcome.get_result()
    except pytest.skip.Exception:
        _enforce_approved_skip(item, "fixture/setup")
        raise
    except Exception:
        pass


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item: pytest.Item):
    outcome = yield
    try:
        outcome.get_result()
    except pytest.skip.Exception:
        _enforce_approved_skip(item, "test body")
        raise
    except Exception:
        pass
