"""Bounded resource metrology around canonical Study Workspace; no new simulator.

Six logical retrospective tasks repeated only to measure cache/CPU/GPU effects.
Receipts and numerical traces stay private. Completed stages resume by hash;
an interrupted incomplete stage is preserved and requires a NEW output root.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from contextlib import nullcontext
from dataclasses import asdict, dataclass
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import platform
import subprocess
import threading
import time

import psutil

from src.research.study_workspace import save_receipt_exclusive
from src.research.v5_isolated_staging import verify_stage


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_identity() -> dict:
    root = Path(__file__).resolve().parents[2]
    paths = (
        "src/research/c0_resource_benchmark.py",
        "src/research/study_workspace.py",
        "src/research/studies/xgb_study.py",
        "src/research/xgb_native_calibration.py",
        "src/research/walkforward/pipeline.py",
        "src/research/e2_feature_cache.py",
        "src/data/research_slice.py",
        "uv.lock",
    )
    return {p: digest(root / p) for p in paths}


class RssSampler:
    """Sample process-tree RSS; includes interpreter/IPC, not a CUDA memory claim."""

    def __init__(self):
        self.stop = threading.Event()
        self.peak = 0

    def sample(self):
        proc = psutil.Process()
        while not self.stop.is_set():
            total = 0
            for p in [proc, *proc.children(recursive=True)]:
                try:
                    total += p.memory_info().rss
                except psutil.Error:
                    pass
            self.peak = max(self.peak, total)
            self.stop.wait(0.02)

    def __enter__(self):
        self.started = time.perf_counter()
        self.thread = threading.Thread(target=self.sample, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop.set()
        self.thread.join()
        self.wall_seconds = time.perf_counter() - self.started


def validate_spec(cfg: dict) -> None:
    if (
        cfg.get("schema_version") != "c0_resource_benchmark_v1"
        or cfg.get("research_only") is not True
        or cfg.get("trade_ready") is not False
        or cfg.get("window_classification") != "RETROSPECTIVE_ALREADY_CONSUMED"
        or cfg.get("owner_internal_research_authorized") is not True
        or cfg.get("vendor_document_review_required") is not False
        or not 6 <= len(cfg.get("tasks", [])) <= 12
        or len({t["id"] for t in cfg["tasks"]}) != len(cfg["tasks"])
        or cfg.get("worker_threads") != 1
        or cfg.get("cpu_workers") != [1, 2, 4]
        or cfg.get("max_model_fits") != len(cfg["tasks"]) * 6
    ):
        raise ValueError("invalid bounded, Owner-authorized C0 contract")


def worker(args: tuple) -> list[dict]:
    cfg, tasks, data_root, destination, cache_enabled, phases, device = args
    os.environ["OMP_NUM_THREADS"] = "1"
    os.environ["OPENBLAS_NUM_THREADS"] = "1"
    os.environ["MKL_NUM_THREADS"] = "1"
    import numpy as np
    import xgboost as xgb
    from src.research.e2_feature_cache import feature_cache_scope
    from src.research import study_workspace as workspace
    from src.research.studies import xgb_study as study
    from src.research.xgb_native_calibration import XGBNativeCalibration

    @dataclass(frozen=True)
    class RuntimeCalibration(XGBNativeCalibration):
        execution_device: str = "cpu"

        def declared_parameters(self):
            return super().declared_parameters() | {"device": self.execution_device, "nthread": 1}

        def effective_model_parameters(self):
            return super().effective_model_parameters() | {
                "device": self.execution_device,
                "nthread": 1,
            }

    original_fit = study.fit_xgb_native_daily_ranker
    original_sim = study._simulate_portfolio
    scope = (
        feature_cache_scope(batch_spec_sha256=cfg["spec_sha256"], max_entries=16)
        if cache_enabled
        else nullcontext(None)
    )
    rows = []
    with scope as cache:
        for phase in phases:
            for task in tasks:
                folder = Path(destination) / phase / task["id"]
                folder.mkdir(parents=True, exist_ok=False)
                state = {}

                def measured_fit(*a, calibration, **kw):
                    effective = RuntimeCalibration(**asdict(calibration), execution_device=device)
                    started = time.perf_counter()
                    fitted = original_fit(*a, calibration=effective, **kw)
                    state["fit_seconds"] = time.perf_counter() - started
                    actual = json.loads(fitted.model.save_config())["learner"]["generic_param"]
                    if device == "cuda" and not actual["device"].startswith("cuda"):
                        raise ValueError("CUDA requested but trainer fell back to CPU")
                    if int(actual["nthread"]) != 1:
                        raise ValueError("worker exceeded frozen native thread budget")
                    fitted.model.save_model(folder / "model.ubj")
                    state["effective_device"] = actual["device"]
                    state["native_threads"] = int(actual["nthread"])
                    state["calibration"] = fitted.identity_manifest
                    return fitted

                def measured_sim(*a, **kw):
                    # Observe existing scores/ledger/returns without changing math.
                    observed = []
                    values = original_sim(*a, **kw, ledger=observed)
                    scores = kw["scores"]
                    arrays = {
                        "scores": scores.to_numpy(dtype="float64"),
                        **{
                            k: np.asarray(v, dtype="float64")
                            for k, v in zip(("gross", "net", "turnover", "benchmark"), values)
                        },
                        "held_weights": np.asarray(
                            [r["target_and_held_weight"] for r in observed], dtype="float64"
                        ),
                    }
                    identity = {
                        "score_sessions": list(map(str, scores.index)),
                        "symbols": list(scores.columns),
                    }
                    semantic = hashlib.sha256(json.dumps(identity, sort_keys=True).encode())
                    for k, v in sorted(arrays.items()):
                        semantic.update(
                            k.encode() + str(v.shape).encode() + v.astype("<f8").tobytes()
                        )
                    np.savez_compressed(folder / "trace.npz", **arrays)
                    state["numerical_sha256"] = semantic.hexdigest()
                    state["trace_identity"] = identity
                    return values

                study.fit_xgb_native_daily_ranker = measured_fit
                study._simulate_portfolio = measured_sim
                before = cache.summary() if cache else {"hits": 0, "misses": 0}
                save_receipt_exclusive(folder / "study-spec.json", task["study"])
                try:
                    with RssSampler() as measurement, xgb.config_context(nthread=1):
                        result = workspace.run_study(
                            folder / "study-spec.json",
                            Path(data_root),
                            output=folder / "study-receipt.json",
                        )
                    if result["status"] != "ready" or "numerical_sha256" not in state:
                        raise ValueError(
                            "canonical task did not produce a complete numerical trace"
                        )
                finally:
                    study.fit_xgb_native_daily_ranker = original_fit
                    study._simulate_portfolio = original_sim
                after = cache.summary() if cache else {"hits": 0, "misses": 0}
                row = {
                    "task_id": task["id"],
                    "phase": phase,
                    "status": "ready",
                    "wall_seconds": measurement.wall_seconds,
                    "sampled_peak_rss_bytes": measurement.peak,
                    "cache_hits": after["hits"] - before["hits"],
                    "cache_misses": after["misses"] - before["misses"],
                    **state,
                    "research_only": True,
                    "trade_ready": False,
                }
                save_receipt_exclusive(folder / "measurement.json", row)
                rows.append(row)
    return rows


def retained_stage(folder: Path) -> dict:
    receipt = json.loads((folder / "stage.json").read_bytes())
    for name, h in receipt["files"].items():
        target = (folder / name).resolve()
        if not target.is_relative_to(folder.resolve()) or digest(target) != h:
            raise ValueError("retained stage file path/hash mismatch")
    return receipt


def execute_stage(
    cfg: dict,
    data_root: Path,
    output: Path,
    name: str,
    workers: int,
    cache: bool,
    phases: tuple,
    device: str = "cpu",
) -> dict:
    folder = output / name
    if (folder / "stage.json").exists():
        return retained_stage(folder)
    if folder.exists():
        raise ValueError(
            "incomplete stage preserved: inspect it and use a NEW output root; no silent overwrite"
        )
    folder.mkdir()
    groups = [cfg["tasks"][i::workers] for i in range(workers)]
    args = [
        (cfg, group, str(data_root), str(folder / f"worker-{i}"), cache, phases, device)
        for i, group in enumerate(groups)
        if group
    ]
    with (
        RssSampler() as sampled,
        ProcessPoolExecutor(
            max_workers=workers, mp_context=multiprocessing.get_context("spawn")
        ) as pool,
    ):
        rows = sum(list(pool.map(worker, args)), [])
    result = {
        "stage": name,
        "workers": workers,
        "worker_threads": 1,
        "wall_seconds": sampled.wall_seconds,
        "sampled_tree_peak_rss_bytes": sampled.peak,
        "rss_sampling_interval_seconds": 0.02,
        "tasks": rows,
        "files": {
            p.relative_to(folder).as_posix(): digest(p) for p in folder.rglob("*") if p.is_file()
        },
        "research_only": True,
        "trade_ready": False,
    }
    save_receipt_exclusive(folder / "stage.json", result)
    return result


def verify(output: Path) -> dict:
    """Independent persisted-array comparison, never fit a model here."""
    import numpy as np

    cfg = json.loads((output / "spec.json").read_bytes())
    stages = {p.parent.name: retained_stage(p.parent) for p in output.glob("*/stage.json")}
    tasks = {t["id"] for t in cfg["tasks"]}
    for name, stage in stages.items():
        phases = ("cold", "warm") if name == "r2-cache-cold-warm" else ("off",)
        expected = {(t, p) for t in tasks for p in phases}
        actual = [(r["task_id"], r["phase"]) for r in stage["tasks"]]
        if set(actual) != expected or len(actual) != len(expected):
            raise ValueError("incomplete or duplicate logical task/phase coverage")
        measured = list((output / name).rglob("measurement.json"))
        if len(measured) != len(expected):
            raise ValueError("missing persisted task measurements")
    reference = stages.get("r1-cache-off")
    if reference is None:
        raise ValueError("no complete R1 reference")

    def traces(stage):
        return {
            json.loads(p.read_bytes())["task_id"]
            + ":"
            + json.loads(p.read_bytes())["phase"]: p.parent / "trace.npz"
            for p in (output / stage).rglob("measurement.json")
        }

    off = traces("r1-cache-off")
    comparisons = []
    reference_identity = {
        p.parent.name: json.loads(p.read_bytes())["trace_identity"]
        for p in (output / "r1-cache-off").rglob("measurement.json")
    }
    for name in stages:
        for key, path in traces(name).items():
            task, phase = key.rsplit(":", 1)
            row = json.loads((path.parent / "measurement.json").read_bytes())
            if row["trace_identity"] != reference_identity[task]:
                raise ValueError("task score calendar/symbol identity mismatch")
            with (
                np.load(off[task + ":off"], allow_pickle=False) as a,
                np.load(path, allow_pickle=False) as b,
            ):
                if set(a.files) != set(b.files):
                    raise ValueError("incomplete numerical trace")
                exact = all(np.array_equal(a[k], b[k], equal_nan=False) for k in a.files)
                error = max(
                    float(np.max(np.abs(a[k] - b[k]))) if a[k].size else 0.0 for k in a.files
                )
            comparisons.append(
                {
                    "stage": name,
                    "task_id": task,
                    "phase": phase,
                    "exact": exact,
                    "max_absolute_error": error,
                }
            )
    cpu_exact = all(c["exact"] for c in comparisons if c["stage"] != "gpu-cuda")
    r2 = stages.get("r2-cache-cold-warm")
    r2_ready = (
        r2 is not None
        and cpu_exact
        and all(
            r["cache_hits"] > 0 and r["cache_misses"] == 0
            for r in r2["tasks"]
            if r["phase"] == "warm"
        )
    )
    return {
        "schema_version": "c0_independent_numerical_audit_v1",
        "spec_sha256": digest(output / "spec.json"),
        "cpu_exact": cpu_exact,
        "r2_cache_reproducible": r2_ready,
        "logical_tasks": len(cfg["tasks"]),
        "observed_completed_fits": sum(len(s["tasks"]) for s in stages.values()),
        "comparisons": comparisons,
        "stages": {
            k: {
                "wall_seconds": v["wall_seconds"],
                "sampled_tree_peak_rss_bytes": v["sampled_tree_peak_rss_bytes"],
            }
            for k, v in stages.items()
        },
        "compute_units": None,
        "compute_units_status": "NOT_MEASURED_OWNER_COLAB_UI_REQUIRED",
        "financial_independent_samples_added": 0,
        "window_classification": "RETROSPECTIVE_ALREADY_CONSUMED",
        "research_only": True,
        "trade_ready": False,
        "pit_certified": False,
    }


def run(spec: Path, data_root: Path, output: Path, stop_after: str | None, gpu: bool) -> dict:
    cfg = json.loads(spec.read_bytes())
    validate_spec(cfg)
    code_root = Path(__file__).resolve().parents[2]
    if output.resolve().is_relative_to(code_root) or data_root.resolve().is_relative_to(code_root):
        raise ValueError("C0 source and results must stay outside checkout")
    actual_git = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=code_root, text=True
    ).strip()
    if actual_git != cfg["runner_git_sha"] or code_identity() != cfg["code_sha256"]:
        raise ValueError("frozen C0 runner/source identity changed")
    source = verify_stage(data_root)
    if (
        source["history_archive_sha256"] != cfg["source_archive_sha256"]
        or source["bundle_manifest_sha256"] != cfg["source_manifest_sha256"]
    ):
        raise ValueError("C0 source identity mismatch")
    output.mkdir(parents=True, exist_ok=True)
    frozen = output / "spec.json"
    if frozen.exists() and frozen.read_bytes() != spec.read_bytes():
        raise ValueError("existing C0 output belongs to another contract")
    if not frozen.exists():
        with frozen.open("xb") as f:
            f.write(spec.read_bytes())
    cfg["spec_sha256"] = digest(spec)
    execute_stage(cfg, data_root, output, "r1-cache-off", 1, False, ("off",))
    if stop_after == "r1":
        return {"status": "R1_CHECKPOINT_COMPLETE", "new_stage": "r1"}
    execute_stage(cfg, data_root, output, "r2-cache-cold-warm", 1, True, ("cold", "warm"))
    audit = verify(output)
    if not audit["r2_cache_reproducible"]:
        raise ValueError("R2 numerical/cache parity failed; concurrency forbidden")
    if stop_after == "r2":
        return audit
    peak = retained_stage(output / "r1-cache-off")["sampled_tree_peak_rss_bytes"]
    for n in (2, 4):
        if psutil.cpu_count() < n or psutil.virtual_memory().available < n * peak + 1024**3:
            raise ValueError(f"insufficient measured CPU/RAM budget for {n} workers")
        execute_stage(cfg, data_root, output, f"cpu-{n}", n, False, ("off",))
        if not verify(output)["cpu_exact"]:
            raise ValueError("parallel numerical mismatch; stop expansion")
    if gpu:
        execute_stage(cfg, data_root, output, "gpu-cuda", 1, False, ("off",), "cuda")
    final = verify(output)
    final["gpu_status"] = "MEASURED_SEE_NUMERICAL_PARITY" if gpu else "NOT_TESTED_NO_CUDA_REQUEST"
    final["environment"] = {
        "python": platform.python_version(),
        "os": platform.system(),
        "logical_cpu_count": psutil.cpu_count(),
    }
    final["source_after"] = verify_stage(data_root)["history_archive_sha256"]
    save_receipt_exclusive(output / "completed-audit.json", final)
    return final


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("run", "verify"))
    p.add_argument("--spec", type=Path)
    p.add_argument("--data-root", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--stop-after", choices=("r1", "r2"))
    p.add_argument("--gpu", action="store_true")
    a = p.parse_args(argv)
    result = (
        verify(a.output)
        if a.action == "verify"
        else run(a.spec, a.data_root, a.output, a.stop_after, a.gpu)
    )
    print(json.dumps(result, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
