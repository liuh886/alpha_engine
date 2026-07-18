"""Architecture guard: adapters emit evidence, never lifecycle decisions."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "path",
    [
        Path("src/research/cn_qlib_execution_adapter.py"),
        Path("src/research/us_qlib_execution_adapter.py"),
    ],
)
def test_qlib_adapters_do_not_build_decision_surfaces(path: Path) -> None:
    source = path.read_text(encoding="utf-8")

    assert "build_model_decision_pack" not in source
    assert "render_model_decision_markdown" not in source
    assert "decision_status" not in source
    assert '"model_decision_pack":' not in source
    assert '"model_decision_markdown":' not in source
    # Evidence-path strings now live in the shared execution engine.
    common_source = Path(
        "src/research/qlib_execution_common.py"
    ).read_text(encoding="utf-8")
    assert '"walk_forward_stability":' in common_source
    assert '"metrics_summary":' in common_source
