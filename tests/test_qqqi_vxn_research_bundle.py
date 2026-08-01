from __future__ import annotations

from pathlib import Path

import nbformat
import pytest

from scripts.refresh_qqqi_vxn_current_notebook import (
    validate_executed_notebook,
)
from scripts.validate_qqqi_vxn_research_bundle import validate_bundle


def test_repository_research_bundle_source_is_consistent() -> None:
    root = Path(__file__).resolve().parents[1]
    validate_bundle(root, require_executed=False)


def test_executed_notebook_validator_accepts_saved_output() -> None:
    notebook = nbformat.v4.new_notebook(
        cells=[
            nbformat.v4.new_code_cell(
                "print('ok')",
                execution_count=1,
                outputs=[
                    nbformat.v4.new_output(
                        output_type="stream",
                        name="stdout",
                        text="ok\n",
                    )
                ],
            )
        ]
    )
    validate_executed_notebook(notebook)


def test_executed_notebook_validator_rejects_unexecuted_cell() -> None:
    notebook = nbformat.v4.new_notebook(
        cells=[nbformat.v4.new_code_cell("print('not run')")]
    )
    with pytest.raises(ValueError, match="unexecuted"):
        validate_executed_notebook(notebook)


def test_executed_notebook_validator_rejects_error_output() -> None:
    notebook = nbformat.v4.new_notebook(
        cells=[
            nbformat.v4.new_code_cell(
                "raise RuntimeError('boom')",
                execution_count=1,
                outputs=[
                    nbformat.v4.new_output(
                        output_type="error",
                        ename="RuntimeError",
                        evalue="boom",
                        traceback=[],
                    )
                ],
            )
        ]
    )
    with pytest.raises(ValueError, match="error outputs"):
        validate_executed_notebook(notebook)
