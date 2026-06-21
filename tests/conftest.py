"""Root conftest for Alpha Engine test suite.

Provides two safety guarantees:

1. **Artifact isolation**: every test automatically gets a temporary artifact
   directory via ``TRADING_ARTIFACTS_DIR``, so no test can accidentally write
   to the production ``artifacts/``, ``mlruns/``, or ``data/`` trees.

2. **Mutation guard**: a session-scoped audit hook fails the test suite if any
   code opens a production artifact path for writing during tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Production paths that tests must never write to
ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ARTIFACTS = ROOT / "artifacts"
PRODUCTION_MLRUNS = ROOT / "mlruns"
PRODUCTION_DATA = ROOT / "data"
PRODUCTION_PATHS = {PRODUCTION_ARTIFACTS, PRODUCTION_MLRUNS, PRODUCTION_DATA}


# ---------------------------------------------------------------------------
# Fixture: per-test artifact isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect ``TRADING_ARTIFACTS_DIR`` to a temp directory for every test.

    This ensures that any code reading ``TRADING_ARTIFACTS_DIR`` (e.g.
    ``RuntimeSettings.from_env``, ``FactorRegistry()`` without explicit
    ``db_path``, ``ArtifactGateway``, etc.) writes into the test-local
    temp directory instead of the real ``artifacts/`` tree.

    Also patches the stale module-level statics in ``src.common.paths`` so
    that code using ``from src.common.paths import MODELS_DIR`` (which
    captures the value at import time) gets redirected too.
    """
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TRADING_ARTIFACTS_DIR", str(artifact_root))

    # Patch module-level static path variables that were evaluated at import
    # time and may still point to the production tree.
    try:
        import src.common.paths as _paths

        monkeypatch.setattr(_paths, "ARTIFACTS_DIR", artifact_root)
        monkeypatch.setattr(_paths, "MODELS_DIR", artifact_root / "models")
        monkeypatch.setattr(_paths, "MLRUNS_DIR", artifact_root / "mlruns")
        monkeypatch.setattr(_paths, "RUNS_DIR", artifact_root / "runs")
        monkeypatch.setattr(_paths, "DASHBOARD_DIR", artifact_root / "dashboard")
        monkeypatch.setattr(
            _paths, "DASHBOARD_DB_PATH", artifact_root / "dashboard" / "dashboard_db.json"
        )
        monkeypatch.setattr(_paths, "ARCHIVES_DIR", artifact_root / "archives")
    except ImportError:
        pass  # Module not yet imported; env var is sufficient

    # Also patch stale references in consumer modules that captured the value
    # of MODELS_DIR / ARTIFACTS_DIR at import time via ``from X import Y``.
    _patch_consumer_paths(monkeypatch, artifact_root)

    yield


# ---------------------------------------------------------------------------
# Fixture: mutation guard (per-test)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mutation_guard(monkeypatch: pytest.MonkeyPatch):
    """Detect and fail if any code opens a production artifact path for writing.

    Patches ``builtins.open`` so that writes to paths under the production
    ``artifacts/``, ``mlruns/``, or ``data/`` directories raise
    ``PermissionError``.
    """
    import builtins

    _real_open = builtins.open

    def _guarded_open(file, mode="r", *args, **kwargs):
        # Only intercept write modes
        if isinstance(mode, str) and any(c in mode for c in ("w", "a", "x")):
            try:
                resolved = Path(file).resolve()
            except (TypeError, OSError):
                return _real_open(file, mode, *args, **kwargs)

            for prod_path in PRODUCTION_PATHS:
                if resolved == prod_path or _is_relative(resolved, prod_path):
                    raise PermissionError(
                        f"[mutation-guard] Test attempted to write to production path: {resolved}"
                    )

        return _real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _guarded_open)
    yield


def _is_relative(child: Path, parent: Path) -> bool:
    """Return True if *child* is inside *parent*."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _patch_consumer_paths(monkeypatch: pytest.MonkeyPatch, artifact_root: Path) -> None:
    """Patch stale path references in modules that did ``from X import MODELS_DIR`` etc.

    When a module does ``from src.common.paths import MODELS_DIR``, it captures
    the value at import time.  Patching ``src.common.paths.MODELS_DIR`` via
    ``monkeypatch.setattr`` updates the source module, but consumer modules
    still hold the old value.  This function patches those consumer modules
    directly.
    """
    _CONSUMER_PATCHES: list[tuple[str, str, Path]] = [
        ("src.research.registry", "MODELS_DIR", artifact_root / "models"),
    ]
    for module_path, attr_name, new_value in _CONSUMER_PATCHES:
        try:
            mod = __import__(module_path, fromlist=[attr_name])
            monkeypatch.setattr(mod, attr_name, new_value)
        except (ImportError, AttributeError):
            pass


# ---------------------------------------------------------------------------
# Hook: zero-unapproved-skip policy
# ---------------------------------------------------------------------------
# Any test that calls pytest.skip() (whether in a fixture or in the test body)
# must carry the ``approved_skip`` marker.  Unapproved skips are converted to
# failures so that CI blocks on them.


def _enforce_approved_skip(item: pytest.Item, phase: str) -> None:
    """Check that a skipped test has the ``approved_skip`` marker."""
    if not item.get_closest_marker("approved_skip"):
        raise pytest.fail(
            f"Test {item.nodeid} was skipped ({phase}) without "
            f"@pytest.mark.approved_skip.  Add the marker with a reason "
            f"or fix the test.",
            pytrace=False,
        )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_setup(item: pytest.Item):
    """Catch skips raised during fixture setup."""
    outcome = yield
    try:
        outcome.get_result()
    except pytest.skip.Exception:
        _enforce_approved_skip(item, "fixture/setup")
        raise  # re-raise if approved
    except Exception:
        pass  # do not re-raise non-skip exceptions from hookwrapper teardown


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item: pytest.Item):
    """Catch skips raised during test body."""
    outcome = yield
    try:
        outcome.get_result()
    except pytest.skip.Exception:
        _enforce_approved_skip(item, "test body")
        raise  # re-raise if approved
    except Exception:
        pass  # do not re-raise non-skip exceptions from hookwrapper teardown
