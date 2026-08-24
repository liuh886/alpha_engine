"""Guards for integration tests that consume workflow-materialized data.

Some contract tests verify consistency between committed catalogs and
formal-refresh artifacts that are materialized by governed workflows rather
than stored in Git. On clean checkouts those inputs are absent; such tests
must skip with an approved reason instead of failing the full-suite health
gate.
"""

from __future__ import annotations

import pytest

from src.common.runtime_settings import PROJECT_ROOT


def require_workflow_fixture(*relative_paths: str) -> None:
    """Skip via pytest.skip unless every given fixture path exists."""

    missing = [
        relative for relative in relative_paths
        if not (PROJECT_ROOT / relative).exists()
    ]
    if missing:
        pytest.skip(
            "workflow-materialized fixture data absent from this checkout: "
            + ", ".join(missing)
        )
