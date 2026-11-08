from pathlib import Path
import json
import ast
import hashlib
from types import SimpleNamespace

import numpy as np
import pytest

from src.research.c0_resource_benchmark import digest, retained_stage, validate_spec, verify


def test_c0_refuses_a_consumed_window_claimed_as_new_holdout():
    with pytest.raises(ValueError, match="Owner-authorized"):
        validate_spec(
            {
                "schema_version": "c0_resource_benchmark_v1",
                "research_only": True,
                "trade_ready": False,
                "window_classification": "UNTOUCHED_HOLDOUT",
            }
        )


def test_independent_audit_detects_numeric_difference_and_trace_tampering(tmp_path):
    tasks = [{"id": f"t{i}"} for i in range(6)]
    (tmp_path / "spec.json").write_text(json.dumps({"tasks": tasks}))
    for name in ("r1-cache-off", "cpu-2"):
        folder = tmp_path / name
        measurements = []
        for task in tasks:
            part = folder / "worker-0" / "off" / task["id"]
            part.mkdir(parents=True)
            value = 1.01 if name == "cpu-2" and task["id"] == "t0" else 1.0
            np.savez_compressed(part / "trace.npz", net=np.array([value]))
            row = {
                "task_id": task["id"],
                "phase": "off",
                "trace_identity": {"sessions": ["2025-01-02"]},
            }
            (part / "measurement.json").write_text(json.dumps(row))
            measurements.append(row)
        files = {
            p.relative_to(folder).as_posix(): digest(p) for p in folder.rglob("*") if p.is_file()
        }
        (folder / "stage.json").write_text(
            json.dumps(
                {
                    "files": files,
                    "tasks": measurements,
                    "wall_seconds": 1.0,
                    "sampled_tree_peak_rss_bytes": 100,
                }
            )
        )
    result = verify(tmp_path)
    assert result["cpu_exact"] is False
    assert result["observed_completed_fits"] == 12
    assert result["financial_independent_samples_added"] == 0
    (tmp_path / "cpu-2/worker-0/off/t0/trace.npz").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="hash mismatch"):
        retained_stage(tmp_path / "cpu-2")


def test_no_incomplete_stage_is_accepted_as_six_paired_tasks(tmp_path):
    (tmp_path / "spec.json").write_text(json.dumps({"tasks": [{"id": f"t{i}"} for i in range(6)]}))
    folder = tmp_path / "r1-cache-off"
    folder.mkdir()
    (folder / "stage.json").write_text(json.dumps({"files": {}, "tasks": []}))
    with pytest.raises(ValueError, match="logical task/phase coverage"):
        verify(tmp_path)


def test_owner_notebook_and_six_task_contract_pin_the_same_runner():
    root = Path(__file__).resolve().parents[1]
    cfg = json.loads(
        (root / "configs/research_experiments/c0_us73_resources_20261108_v3.json").read_bytes()
    )
    validate_spec(cfg)
    notebook = json.loads((root / "notebooks/C0_resource_benchmark.ipynb").read_bytes())
    assert notebook["metadata"]["alpha_engine"]["runner_sha"] == cfg["runner_git_sha"]
    assert {t["study"]["study_id"] for t in cfg["tasks"]} == {"cross_sectional_xgb_v1"}
    for i, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] == "code":
            ast.parse("".join(cell["source"]), filename=f"notebook-cell-{i}")


def test_colab_bootstrap_restores_exact_frozen_lock_before_install(tmp_path):
    root = Path(__file__).resolve().parents[1]
    spec = json.loads(
        (root / "configs/research_experiments/c0_us73_resources_20261108_v3.json").read_bytes()
    )
    notebook = json.loads((root / "notebooks/C0_resource_benchmark.ipynb").read_bytes())
    source = next(
        "".join(c["source"]) for c in notebook["cells"] if "git_lock =" in "".join(c["source"])
    )
    block = source[source.index("    # Preserve"):source.index("    command(['uv','python'")]
    assert source.index("    # Preserve") < source.index("    command(['uv','sync'")
    code, job = tmp_path / "code", tmp_path / "job"
    code.mkdir()
    job.mkdir()
    for relative in spec["code_sha256"]:
        target = code / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / relative).read_bytes())
    git_lock = (root / "uv.lock").read_bytes().replace(b"\r\n", b"\n")
    (code / "uv.lock").write_bytes(git_lock)  # Linux checkout representation
    (job / "uv.lock.frozen").write_bytes(git_lock.replace(b"\n", b"\r\n"))
    (job / "c0-spec-v3.json").write_text(json.dumps(spec))
    scope = {
        "CODE": code, "JOB": job, "RUNNER_SHA": spec["runner_git_sha"],
        "hashlib": hashlib, "json": json, "sha": digest,
        "subprocess": SimpleNamespace(check_output=lambda *a, **kw: git_lock),
    }
    exec("if True:\n" + block, scope)
    assert digest(code / "uv.lock") == spec["code_sha256"]["uv.lock"]
    (job / "uv.lock.frozen").write_bytes(b"changed dependency")
    with pytest.raises(AssertionError):
        exec("if True:\n" + block, scope)


def test_notebook_completed_resume_preserves_logs_and_does_not_fit(tmp_path):
    import subprocess
    import uuid

    root = Path(__file__).resolve().parents[1]
    notebook = json.loads((root / "notebooks/C0_resource_benchmark.ipynb").read_bytes())
    definitions = []
    for cell in notebook["cells"]:
        if cell["cell_type"] == "code":
            definitions.extend(n for n in ast.parse("".join(cell["source"])).body
                               if isinstance(n, ast.FunctionDef) and n.name in {"command", "measure"})
    calls, checkpoints = [], []
    scope = {
        "Path": Path, "CODE": tmp_path, "OUTPUT": tmp_path, "IN_COLAB": True,
        "json": json, "uuid": uuid, "os": __import__("os"),
        "BASE_COMMAND": ["do-not-fit"], "PY": "python",
        "checkpoint": checkpoints.append,
    }

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout="{}")

    scope["subprocess"] = SimpleNamespace(run=run, PIPE=subprocess.PIPE, STDOUT=subprocess.STDOUT)
    (tmp_path / "completed-audit.json").write_text(json.dumps({"status": "PARTIAL"}))
    (tmp_path / "cpu-and-gpu.log").write_text("original log")
    (tmp_path / "cpu-and-gpu-execution-status.json").write_text("original status")
    exec(compile(ast.Module(body=definitions, type_ignores=[]), "notebook-helpers", "exec"), scope)
    scope["measure"]("cpu-and-gpu", ["--gpu"])
    assert len(calls) == 1 and "verify" in calls[0] and "do-not-fit" not in calls[0]
    assert (tmp_path / "cpu-and-gpu.log").read_text() == "original log"
    assert (tmp_path / "cpu-and-gpu-execution-status.json").read_text() == "original status"
    assert len(list(tmp_path.glob("cpu-and-gpu-attempt-*.log"))) == 1
    assert len(list(tmp_path.glob("cpu-and-gpu-execution-status-attempt-*.json"))) == 1
    assert checkpoints == ["cpu-and-gpu"]
