"""Real-Qlib CI smoke test for the CN spec-bound execution adapter."""

from __future__ import annotations

import json
import subprocess
import sys
from functools import partial
from pathlib import Path

from src.research.cn_qlib_execution_adapter import (
    QlibCNExecutionRuntime,
    execute_cn_qlib_plan,
)
from src.research.paradigm import load_research_paradigm_spec
from src.research.spec_bound_execution import execute_spec_bound_research

FIXTURE_DIR = Path("tests/fixtures/cn_qlib_ci")


def test_cn_spec_bound_adapter_with_real_qlib_provider(tmp_path: Path) -> None:
    provider_dir = tmp_path / "qlib_data"
    subprocess.run(
        [
            sys.executable,
            str(FIXTURE_DIR / "build_fixture.py"),
            "--output",
            str(provider_dir),
        ],
        check=True,
    )

    spec = load_research_paradigm_spec(FIXTURE_DIR / "paradigm.yaml")
    runtime = QlibCNExecutionRuntime(provider_uri=provider_dir)
    result = execute_spec_bound_research(
        spec,
        partial(execute_cn_qlib_plan, runtime=runtime),
        output_dir=tmp_path / "research_runs",
    )

    assert result["status"] == "passed"
    assert result["contract_identity_verified"] is True

    run_dir = Path(result["run_dir"])
    identity = json.loads(
        (run_dir / "execution_identity.json").read_text(encoding="utf-8")
    )
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    readiness = json.loads(
        (run_dir / "data_readiness.json").read_text(encoding="utf-8")
    )
    windows = json.loads(
        (run_dir / "walk_forward_windows.json").read_text(encoding="utf-8")
    )

    assert identity["matched"] is True
    assert status["status"] == "passed"
    assert status["research_only"] is True
    assert status["trade_ready"] is False
    assert readiness["sufficient"] is True
    assert len(readiness["retained_symbols"]) >= 8
    assert len(windows["windows"]) >= 3
    assert (run_dir / "walk_forward_stability.json").is_file()
    assert (run_dir / "model_decision_pack.json").is_file()
    assert (run_dir / "metrics_summary.json").is_file()
    for path in status["evidence_paths"].values():
        assert Path(path).is_file()
