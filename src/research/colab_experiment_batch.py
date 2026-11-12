"""P2-E2 bounded Colab/local experiment batch using the existing XGBoost study.

No new ranker, data provider, hosted scheduler, or trade output. The runner
iterates frozen validation folds × model hyperparameters × seeds, saves each
existing Study Workspace receipt, and can resume at completed trial boundaries.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any

from src.research.cloud_exchange import ExchangeError
from src.research.v5_isolated_staging import verify_stage

SHA = re.compile(r"[0-9a-f]{64}")
NAME = re.compile(r"[a-z][a-z0-9_-]{2,63}")
SCHEMA = "p2_e2_xgb_validation_batch_v1"
ALLOWED_PARAMS = {"max_depth", "learning_rate", "num_boost_round"}
CHECKPOINT_SCHEMA = "p2_e2_unreviewed_trial_checkpoint_v1"
MAX_CHECKPOINT_BYTES = 20 * 1024 * 1024


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _write_new(path: Path, data: dict) -> None:
    from src.research.study_workspace import save_receipt_exclusive
    save_receipt_exclusive(path, data)


def _git_head() -> str:
    root = Path(__file__).resolve().parents[2]
    if subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "src", "pyproject.toml", "uv.lock"],
                      cwd=root, check=False).returncode:
        raise ExchangeError("runner source/dependencies differ from committed revision")
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def _study_status(path: Path, run_spec: dict, runner_sha: str) -> str:
    raw = json.loads(path.read_text(encoding="utf-8"))
    content = {k: v for k, v in raw.items() if k not in ("study_hash", "generated_at_utc")}
    if (raw.get("status") not in ("ready", "blocked") or
            raw.get("experiment_receipt") != run_spec or raw.get("git_commit") != runner_sha or
            raw.get("research_only") is not True or raw.get("trade_ready") is not False or
            raw.get("pit_certified") is not False or raw.get("study_hash") != _digest(_canonical(content))):
        raise ExchangeError("retained study identity/hash mismatch")
    return str(raw["status"])


def _trial_status(directory: Path, entry: dict, batch: dict, run_spec: dict) -> str:
    out, frozen = directory / "study-receipt.json", directory / "study-spec.json"
    rec = json.loads((directory / "trial-result.json").read_text(encoding="utf-8"))
    if (rec.get("schema_version") != "p2_e2_batch_trial_receipt_v1" or
            rec.get("trial_id") != entry["trial_id"] or
            rec.get("batch_spec_sha256") != batch["batch_spec_sha256"] or
            rec.get("runner_git_sha") != batch["runner_git_sha"] or
            rec.get("study_spec_sha256") != _digest(_canonical(run_spec)) or
            not frozen.is_file() or json.loads(frozen.read_text(encoding="utf-8")) != run_spec or
            not out.is_file() or rec.get("receipt_sha256") != _digest(out.read_bytes()) or
            rec.get("research_only") is not True or rec.get("trade_ready") is not False or
            rec.get("pit_certified") is not False or rec.get("review_status") != "incoming_unreviewed"):
        raise ExchangeError("resume result identity mismatch")
    status = _study_status(out, run_spec, batch["runner_git_sha"])
    if rec.get("study_status") != status:
        raise ExchangeError("resume status differs from retained study")
    return status


def _inputs(batch_spec: Path, data_root: Path) -> tuple[dict, list[str]]:
    import yaml
    batch = plan(json.loads(batch_spec.read_text(encoding="utf-8")), data_root)
    pool = yaml.safe_load((data_root / "configs/research_universes/"
                           "us_selected_equities_v2.yaml").read_text(encoding="utf-8"))
    symbols = list(pool["symbols"])
    if len(symbols) != 87 or len(set(symbols)) != 87:
        raise ExchangeError("staged full US87 pool invalid")
    return batch, symbols


def _outside_checkout(path: Path) -> None:
    if path.is_symlink() or path.resolve().is_relative_to(Path(__file__).resolve().parents[2]):
        raise ExchangeError("research outputs must be nonsymlinked and outside the public Git repo")


def _output_files(batch: dict, symbols: list[str], root: Path, *, checkpoint_index=False) -> list[dict]:
    """Only frozen plans and verified Study Workspace receipts may travel."""
    from src.research.comprehensive_bundle import _privacy_bytes
    _outside_checkout(root)
    base = root / batch["batch_id"]
    allowed = {f'{batch["batch_id"]}/batch-plan.json'}
    for entry in batch["trials"]:
        allowed.update(f'{batch["batch_id"]}/trials/{entry["trial_id"]}/{name}' for name in
                       ("study-spec.json", "study-receipt.json", "trial-result.json"))
    files = []
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ExchangeError("symlinked research output")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if checkpoint_index and relative == "checkpoint-index.json":
            continue
        if relative not in allowed:
            raise ExchangeError("unexpected file in batch outputs")
        total += path.stat().st_size
        if total > MAX_CHECKPOINT_BYTES:
            raise ExchangeError("checkpoint exceeds 20 MiB budget")
        data = path.read_bytes()
        _privacy_bytes(data)
        files.append({"path": relative, "size": len(data), "sha256": _digest(data)})
    if not files or json.loads((base / "batch-plan.json").read_text(encoding="utf-8")) != batch:
        raise ExchangeError("checkpoint batch plan differs")
    for entry in batch["trials"]:
        td = base / "trials" / entry["trial_id"]
        run_spec = {**entry["study"], "symbols": symbols}
        cfg, out, receipt = (td / n for n in ("study-spec.json", "study-receipt.json", "trial-result.json"))
        if any(p.exists() for p in (cfg, out, receipt)):
            if not cfg.is_file() or json.loads(cfg.read_text(encoding="utf-8")) != run_spec:
                raise ExchangeError("checkpoint study spec differs")
            if receipt.exists():
                _trial_status(td, entry, batch, run_spec)
            elif out.exists():
                _study_status(out, run_spec, batch["runner_git_sha"])
    return files


def checkpoint(*, batch_spec: Path, data_root: Path, output_root: Path, destination: Path) -> dict:
    """Create one immutable, bounded, source-bound results snapshot; no raw data."""
    _outside_checkout(destination)
    if destination.exists() or destination.resolve().is_relative_to(output_root.resolve()):
        raise ExchangeError("checkpoint destination must be fresh and outside outputs")
    batch, symbols = _inputs(batch_spec, data_root)
    files = _output_files(batch, symbols, output_root)
    index = {"schema_version": CHECKPOINT_SCHEMA, "batch_id": batch["batch_id"],
             "batch_spec_sha256": _digest(batch_spec.read_bytes()),
             "batch_identity_sha256": batch["batch_spec_sha256"],
             "runner_git_sha": batch["runner_git_sha"], **batch["data"],
             "files": files, "research_only": True, "trade_ready": False,
             "pit_certified": False, "review_status": "incoming_unreviewed"}
    destination.mkdir(parents=True, exist_ok=False)
    for row in files:
        src, dst = output_root / row["path"], destination / row["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        with src.open("rb") as inp, dst.open("xb") as out:
            shutil.copyfileobj(inp, out)
        if _digest(dst.read_bytes()) != row["sha256"]:
            raise ExchangeError("checkpoint readback mismatch")
    # Drive FUSE does not promise hardlink support. Seal last and return its hash
    # only after all files have been read back, without changing an existing index.
    path = destination / "checkpoint-index.json"
    with path.open("xb") as out:
        out.write(_canonical(index) + b"\n")
    return {"status": "CHECKPOINT_VERIFIED_UNREVIEWED", "checkpoint": str(destination),
            "index_sha256": _digest(path.read_bytes()), "files": len(files),
            "total_bytes": sum(r["size"] for r in files), "trade_ready": False}


def restore(*, batch_spec: Path, data_root: Path, checkpoint_root: Path,
            expected_index_sha256: str, output_root: Path) -> dict:
    """Restore only an explicitly pinned checkpoint, verifying before any copy."""
    _outside_checkout(output_root)
    if output_root.exists() or checkpoint_root.is_symlink():
        raise ExchangeError("restore requires fresh output root and regular checkpoint")
    path = checkpoint_root / "checkpoint-index.json"
    if (not SHA.fullmatch(expected_index_sha256) or not path.is_file() or path.is_symlink() or
            path.stat().st_size > 1024 * 1024 or _digest(path.read_bytes()) != expected_index_sha256):
        raise ExchangeError("checkpoint index differs from independently pinned SHA256")
    index = json.loads(path.read_text(encoding="utf-8"))
    batch, symbols = _inputs(batch_spec, data_root)
    expected = {"schema_version": CHECKPOINT_SCHEMA, "batch_id": batch["batch_id"],
                "batch_spec_sha256": _digest(batch_spec.read_bytes()),
                "batch_identity_sha256": batch["batch_spec_sha256"],
                "runner_git_sha": batch["runner_git_sha"], **batch["data"],
                "research_only": True, "trade_ready": False, "pit_certified": False,
                "review_status": "incoming_unreviewed"}
    if any(index.get(k) != v for k, v in expected.items()):
        raise ExchangeError("checkpoint source/batch/runner boundary mismatch")
    files = _output_files(batch, symbols, checkpoint_root, checkpoint_index=True)
    if index.get("files") != files:
        raise ExchangeError("checkpoint file inventory/hash mismatch")
    output_root.mkdir(parents=True, exist_ok=False)
    for row in files:
        dst = output_root / row["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        with (checkpoint_root / row["path"]).open("rb") as inp, dst.open("xb") as out:
            shutil.copyfileobj(inp, out)
        if _digest(dst.read_bytes()) != row["sha256"]:
            raise ExchangeError("restored checkpoint readback mismatch")
    if _output_files(batch, symbols, output_root) != files:
        raise ExchangeError("restored output inventory mismatch")
    return {"status": "RESTORED_VERIFIED_UNREVIEWED", "files": len(files),
            "index_sha256": expected_index_sha256, "trade_ready": False}


def checkpoint_archive(*, batch_spec: Path, data_root: Path, output_root: Path, archive: Path) -> dict:
    """Use the same sealed checkpoint in a single Drive transport file."""
    _outside_checkout(archive)
    if archive.exists() or archive.resolve().is_relative_to(output_root.resolve()):
        raise ExchangeError("checkpoint archive must be new and outside outputs")
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="p2-checkpoint-") as temporary:
        root = Path(temporary) / "sealed"
        sealed = checkpoint(batch_spec=batch_spec, data_root=data_root, output_root=output_root, destination=root)
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as pack:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    pack.write(path, path.relative_to(root).as_posix())
        with zipfile.ZipFile(archive) as pack:
            if pack.testzip() is not None:
                raise ExchangeError("checkpoint archive CRC mismatch")
    return {**sealed, "checkpoint": str(archive), "archive_sha256": _digest(archive.read_bytes()),
            "archive_size_bytes": archive.stat().st_size}


def restore_archive(*, batch_spec: Path, data_root: Path, archive: Path,
                    expected_archive_sha256: str, expected_index_sha256: str, output_root: Path) -> dict:
    """Decode only bounded safe members, then reuse strict directory restore."""
    _outside_checkout(output_root)
    if (output_root.exists() or archive.is_symlink() or not archive.is_file() or
            archive.stat().st_size > MAX_CHECKPOINT_BYTES + 1024 * 1024 or
            not SHA.fullmatch(expected_archive_sha256) or
            _digest(archive.read_bytes()) != expected_archive_sha256):
        raise ExchangeError("checkpoint archive pin/size or fresh-output boundary mismatch")
    with zipfile.ZipFile(archive) as pack, tempfile.TemporaryDirectory(prefix="p2-restore-") as temporary:
        infos = pack.infolist()
        names = [i.filename for i in infos]
        if (len(infos) > 3002 or len(names) != len(set(names)) or
                sum(i.file_size for i in infos) > MAX_CHECKPOINT_BYTES + 1024 * 1024):
            raise ExchangeError("checkpoint archive member budget mismatch")
        for info in infos:
            if (info.is_dir() or "\\" in info.filename or ":" in info.filename or
                    info.filename.startswith("/") or any(p in ("", ".", "..") for p in info.filename.split("/")) or
                    (info.external_attr >> 16) & 0o170000 == 0o120000):
                raise ExchangeError("unsafe checkpoint archive member")
        if "checkpoint-index.json" not in names or pack.getinfo("checkpoint-index.json").file_size > 1024 * 1024:
            raise ExchangeError("checkpoint archive index missing/too large")
        content = pack.read("checkpoint-index.json")
        if _digest(content) != expected_index_sha256:
            raise ExchangeError("checkpoint inner index SHA mismatch")
        root = Path(temporary)
        for info in infos:
            target = root / info.filename
            if not target.resolve().is_relative_to(root.resolve()):
                raise ExchangeError("checkpoint archive escapes scratch")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as out:
                out.write(pack.read(info.filename))
        return restore(batch_spec=batch_spec, data_root=data_root, checkpoint_root=root,
                       expected_index_sha256=expected_index_sha256, output_root=output_root)


def _retain_trial(td: Path, entry: dict, batch: dict, run_spec: dict,
                  elapsed: float | None, recovered=False) -> str:
    out = td / "study-receipt.json"
    status = _study_status(out, run_spec, batch["runner_git_sha"])
    raw = json.loads(out.read_text(encoding="utf-8"))
    _write_new(td / "trial-result.json", {
        "schema_version": "p2_e2_batch_trial_receipt_v1",
        "batch_spec_sha256": batch["batch_spec_sha256"], "runner_git_sha": batch["runner_git_sha"],
        "trial_id": entry["trial_id"], "study_spec_sha256": _digest(_canonical(run_spec)),
        "receipt_sha256": _digest(out.read_bytes()), "study_status": status,
        "elapsed_seconds": elapsed, "recovered_completed_study": recovered,
        "blocked_reasons": raw.get("blocked_reasons", []), "research_only": True,
        "trade_ready": False, "pit_certified": False, "review_status": "incoming_unreviewed"})
    return _trial_status(td, entry, batch, run_spec)


def plan(spec: dict, data_root: Path | None = None) -> dict[str, Any]:
    """Validate a complete, bounded selection-only search without executing."""
    from src.research.colab_research_campaign import SCHEMA as CAMPAIGN_SCHEMA, compile_campaign
    if isinstance(spec, dict) and spec.get("schema_version") == CAMPAIGN_SCHEMA:
        return compile_campaign(spec, data_root)
    if not isinstance(spec, dict) or spec.get("schema_version") != SCHEMA:
        raise ExchangeError("unsupported batch schema")
    if not isinstance(spec.get("batch_id"), str) or not NAME.fullmatch(spec["batch_id"]):
        raise ExchangeError("invalid batch_id")
    if (not isinstance(spec.get("runner_git_sha"), str) or
            not re.fullmatch("[0-9a-f]{40}", spec["runner_git_sha"])):
        raise ExchangeError("exact experiment runner SHA required")
    if (not isinstance(spec.get("v5_bundle_manifest_sha256"), str) or
            not SHA.fullmatch(spec["v5_bundle_manifest_sha256"]) or
            not isinstance(spec.get("history_archive_sha256"), str) or
            not SHA.fullmatch(spec["history_archive_sha256"])):
        raise ExchangeError("source hashes must be independently pinned")
    if spec.get("purpose") != "validation_search_only":
        raise ExchangeError("batch is for validation search, NOT final holdout or production")
    base = spec.get("study")
    if not isinstance(base, dict) or base.get("study_id") != "cross_sectional_xgb_v1":
        raise ExchangeError("first batch must reuse existing XGBoost study")
    if (base.get("market") != "us" or
            base.get("pool_id") != "us_selected_equities_v2" or
            base.get("symbols") != "$US87" or base.get("benchmark") != "QQQ" or
            base.get("price_mode") != "anchored_adjusted"):
        raise ExchangeError("batch must retain full US87, QQQ and price-basis contract")
    # Fields must match existing Study Workspace config exactly, except 4 fold dates.
    from src.research.study_workspace import DEFAULT_XGB_CONFIG
    sample = DEFAULT_XGB_CONFIG.to_dict()
    if set(base) != set(sample) or set(base["xgb_params"]) != set(sample["xgb_params"]):
        raise ExchangeError("batch base study does not match existing study template fields")
    if (base.get("top_k", 0) <= 0 or base["top_k"] > 87 or
            base.get("cost_bps", -1) < 0 or base.get("slippage_bps", -1) < 0 or
            base.get("features") != list(DEFAULT_XGB_CONFIG.features)):
        raise ExchangeError("invalid benchmark/cost/feature contract")
    folds = spec.get("validation_folds")
    if not isinstance(folds, list) or not folds or len(folds) > 8:
        raise ExchangeError("1..8 explicitly frozen chronological folds required")
    for i, fold in enumerate(folds):
        if not isinstance(fold, dict) or set(fold) != {
                "fold_id", "train_start", "train_end", "test_start", "test_end"}:
            raise ExchangeError("invalid fold fields")
        if not NAME.fullmatch(str(fold["fold_id"])):
            raise ExchangeError("invalid fold_id")
        if not all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(fold[k])) for k in
                   ("train_start", "train_end", "test_start", "test_end")):
            raise ExchangeError("invalid dates")
        if not (fold["train_start"] < fold["train_end"] < fold["test_start"]
                <= fold["test_end"] <= base["as_of_cutoff"] <= "2026-11-03"):
            raise ExchangeError("out-of-range or overlapping train/validation dates")
        if i and folds[i - 1]["test_end"] >= fold["test_start"]:
            raise ExchangeError("validation windows overlap")
    search = spec.get("search_space")
    if not isinstance(search, dict) or not search or set(search) - ALLOWED_PARAMS:
        raise ExchangeError("unsupported search dimension")
    for key, values in search.items():
        if not isinstance(values, list) or not values or len(values) > 12:
            raise ExchangeError("search dimension must be a small explicit list")
        for value in values:
            if key == "learning_rate":
                if (not isinstance(value, (int, float)) or isinstance(value, bool) or
                        not 0 < value <= 1):
                    raise ExchangeError("invalid learning rate")
            elif not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 1000:
                raise ExchangeError("invalid integer XGBoost parameter")
    seeds = spec.get("seeds")
    if (not isinstance(seeds, list) or not seeds or len(seeds) > 10 or
            any(not isinstance(s, int) or isinstance(s, bool) or not 0 <= s <= 2**31 - 1
                for s in seeds) or len(seeds) != len(set(seeds))):
        raise ExchangeError("invalid deterministic seeds")
    max_trials = spec.get("max_trials")
    if (not isinstance(max_trials, int) or isinstance(max_trials, bool)
            or not 1 <= max_trials <= 100):
        raise ExchangeError("explicit max_trials must be between 1 and 100")
    if data_root is not None:
        root_doc = verify_stage(data_root)
        if (root_doc["bundle_manifest_sha256"] != spec["v5_bundle_manifest_sha256"] or
                root_doc["history_archive_sha256"] != spec["history_archive_sha256"]):
            raise ExchangeError("staged input root differs from experiment source")
    combos = itertools.product(
        folds, seeds, itertools.product(*[search[k] for k in sorted(search)]))
    trials = []
    for fold, seed, param_values in combos:
        params = dict(zip(sorted(search), param_values))
        study = {**base, **{k: fold[k] for k in
                 ("train_start", "train_end", "test_start", "test_end")}}
        study["as_of_cutoff"] = base["as_of_cutoff"]
        study["xgb_params"] = {**base["xgb_params"], **params, "seed": seed}
        study["symbols"] = "$US87"
        digest = _digest(_canonical(study))
        trials.append({"trial_id": f'{fold["fold_id"]}-s{seed}-{digest[:12]}',
                       "fold_id": fold["fold_id"], "seed": seed,
                       "params": params, "study": study, "study_sha256": digest})
        if len(trials) > max_trials:
            raise ExchangeError("search product exceeds max_trials budget")
    if len({t["trial_id"] for t in trials}) != len(trials):
        raise ExchangeError("duplicate trial identity")
    return {"schema_version": SCHEMA, "batch_id": spec["batch_id"],
            "batch_spec_sha256": _digest(_canonical(spec)),
            "runner_git_sha": spec["runner_git_sha"],
            "data": {"v5_bundle_manifest_sha256": spec["v5_bundle_manifest_sha256"],
                     "history_archive_sha256": spec["history_archive_sha256"]},
            "role": "validation_search_only", "trial_count": len(trials),
            "trials": trials, "trade_ready": False, "pit_certified": False,
            "research_only": True}


def execute(*, batch_spec: Path, data_root: Path, output_root: Path,
            resume: bool = False, max_new_trials: int | None = None,
            max_wall_seconds: int | None = None,
            shard_manifest: Path | None = None, shard_id: str | None = None) -> dict:
    """Run existing Study Workspace specs, checkpoint one immutable receipt per trial."""
    if max_new_trials is not None and (not isinstance(max_new_trials, int)
                                       or not 1 <= max_new_trials <= 100):
        raise ExchangeError("max_new_trials must be within 1..100")
    if max_wall_seconds is not None and (type(max_wall_seconds) is not int or not 1 <= max_wall_seconds <= 7200):
        raise ExchangeError("wall-time start budget must be within 1..7200 seconds")
    invocation_start = time.perf_counter()
    batch = plan(json.loads(batch_spec.read_text(encoding="utf-8")))
    if (shard_manifest is None) != (shard_id is None):
        raise ExchangeError("shard manifest and ID must be supplied together")
    selected_ids = None
    if shard_manifest is not None:
        from src.research.colab_campaign_shards import assigned_trial_ids
        selected_ids = assigned_trial_ids(
            json.loads(shard_manifest.read_text(encoding="utf-8")), batch, shard_id
        )
        # Every notebook writes to its own namespace; never a shared output root.
        if shard_id not in (output_root.name, output_root.parent.name):
            raise ExchangeError("shard output root must be namespaced by its shard ID")
    if _git_head() != batch["runner_git_sha"]:
        raise ExchangeError("runner checkout revision mismatch")
    batch, symbols = _inputs(batch_spec, data_root)
    _outside_checkout(output_root)
    if output_root.resolve().is_relative_to(Path(__file__).resolve().parents[2]):
        raise ExchangeError("training outputs must remain outside the public Git repo")
    # Source stage must be a fresh isolated root, not the original Git checkout.
    if data_root.resolve().is_relative_to(Path(__file__).resolve().parents[2]):
        raise ExchangeError("training data must use isolated v5 stage")
    from src.research.study_workspace import load_study_spec, run_study
    path = output_root / batch["batch_id"]
    if path.exists() and not resume:
        raise ExchangeError("immutable batch exists; use --resume after inspecting it")
    path.mkdir(parents=True, exist_ok=True)
    if selected_ids is not None and (path / "trials").exists():
        foreign = {p.name for p in (path / "trials").iterdir() if p.is_dir()} - selected_ids
        if foreign:
            raise ExchangeError("output root contains foreign shard trial receipts")
    frozen = path / "batch-plan.json"
    if frozen.exists():
        existing = json.loads(frozen.read_text(encoding="utf-8"))
        if existing != batch:
            raise ExchangeError("resume batch spec/hash differs")
    else:
        _write_new(frozen, batch)
    _output_files(batch, symbols, output_root)
    completed = 0
    new = 0
    blocked = 0
    recovered = 0
    failed_in_sequence = 0
    stop_reason = "complete"
    eligible_trials = (
        [e for e in batch["trials"] if e["trial_id"] in selected_ids]
        if selected_ids is not None else batch["trials"]
    )
    for entry in eligible_trials:
        td = path / "trials" / entry["trial_id"]
        run_spec = {**entry["study"], "symbols": symbols}
        cfg_path = td / "study-spec.json"
        out = td / "study-receipt.json"
        receipt = td / "trial-result.json"
        if receipt.exists():
            status = _trial_status(td, entry, batch, run_spec)
            completed += 1
            blocked += status == "blocked"
            continue
        if out.exists():
            status = _retain_trial(td, entry, batch, run_spec, None, recovered=True)
            completed += 1
            recovered += 1
            blocked += status == "blocked"
            continue
        if max_new_trials is not None and new >= max_new_trials:
            stop_reason = "chunk_trial_budget"
            continue
        if max_wall_seconds is not None and time.perf_counter() - invocation_start >= max_wall_seconds:
            stop_reason = "wall_time_start_budget"
            continue
        if failed_in_sequence >= 3:
            stop_reason = "consecutive_model_failure_budget"
            continue
        if cfg_path.exists():
            if json.loads(cfg_path.read_text(encoding="utf-8")) != run_spec:
                raise ExchangeError("existing frozen trial spec differs")
        else:
            _write_new(cfg_path, run_spec)
        load_study_spec(cfg_path)  # canonical Study Workspace validation
        started = time.perf_counter()
        try:
            result = run_study(cfg_path, data_root, output=out)
        except Exception as exc:
            # Per-trial research failures remain immutable evidence. The source
            # and configuration gates above still fail before any model starts.
            if out.exists():
                raise
            failure = {"study_id": run_spec["study_id"], "status": "blocked",
                "experiment_receipt": run_spec, "git_commit": batch["runner_git_sha"],
                "model_fitted": False, "research_only": True, "trade_ready": False, "pit_certified": False,
                "blocked_reasons": [{"code": "model_execution_failed", "exception_type": type(exc).__name__,
                                     "detail": str(exc)[:500]}]}
            failure["study_hash"] = _digest(_canonical(failure))
            _write_new(out, failure)
            result = {"status": "blocked"}
        elapsed = time.perf_counter() - started
        if result["status"] not in ("ready", "blocked"):
            raise ExchangeError("unexpected study receipt status")
        status = _retain_trial(td, entry, batch, run_spec, elapsed)
        new += 1
        if status == "blocked":
            blocked += 1
            failed_in_sequence += 1
        else:
            failed_in_sequence = 0
    pending = len(eligible_trials) - completed - new
    return {"status": ("BATCH_PARTIAL_CHECKPOINT_READY" if pending else
                       "BATCH_EXECUTED_RESEARCH_ONLY"), "batch_id": batch["batch_id"],
            "trials": len(eligible_trials), "campaign_trials": len(batch["trials"]),
            "shard_id": shard_id, "resumed_trials": completed,
            "new_trials": new, "pending_trials": pending, "blocked_trials": blocked,
            "recovered_completed_trials": recovered,
            "stop_reason": stop_reason if pending else "complete",
            "elapsed_seconds": time.perf_counter() - invocation_start,
            "review_status": "incoming_unreviewed",
            "trade_ready": False, "pit_certified": False}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    for cmd in ("plan", "run", "checkpoint", "restore", "report", "checkpoint-archive", "restore-archive"):
        subp = sub.add_parser(cmd)
        subp.add_argument("--batch-spec", required=True, type=Path)
        if cmd != "plan":
            subp.add_argument("--data-root", required=True, type=Path)
            subp.add_argument("--output-root", required=True, type=Path)
        if cmd == "run":
            subp.add_argument("--resume", action="store_true")
            subp.add_argument("--max-new-trials", type=int)
            subp.add_argument("--max-wall-seconds", type=int)
            subp.add_argument("--shared-feature-cache", action="store_true")
            subp.add_argument("--shard-manifest", type=Path)
            subp.add_argument("--shard-id", type=str)
        if cmd == "checkpoint":
            subp.add_argument("--destination", required=True, type=Path)
        if cmd == "restore":
            subp.add_argument("--checkpoint-root", required=True, type=Path)
            subp.add_argument("--expected-index-sha256", required=True)
        if cmd in ("checkpoint-archive", "restore-archive"):
            subp.add_argument("--archive", required=True, type=Path)
        if cmd == "restore-archive":
            subp.add_argument("--expected-archive-sha256", required=True)
            subp.add_argument("--expected-index-sha256", required=True)
    args = p.parse_args(argv)
    try:
        if args.action == "plan":
            spec = json.loads(args.batch_spec.read_text(encoding="utf-8"))
            result = plan(spec)
            # Plan output includes explicit spec inputs, not private source bars.
            print(json.dumps(result, indent=2))
        elif args.action == "checkpoint":
            print(json.dumps(checkpoint(batch_spec=args.batch_spec, data_root=args.data_root,
                output_root=args.output_root, destination=args.destination), indent=2))
        elif args.action == "restore":
            print(json.dumps(restore(batch_spec=args.batch_spec, data_root=args.data_root,
                output_root=args.output_root, checkpoint_root=args.checkpoint_root,
                expected_index_sha256=args.expected_index_sha256), indent=2))
        elif args.action == "report":
            from src.research.colab_research_campaign import comparison_report
            print(json.dumps(comparison_report(args.batch_spec, args.data_root, args.output_root), indent=2))
        elif args.action == "checkpoint-archive":
            print(json.dumps(checkpoint_archive(batch_spec=args.batch_spec, data_root=args.data_root,
                output_root=args.output_root, archive=args.archive), indent=2))
        elif args.action == "restore-archive":
            print(json.dumps(restore_archive(batch_spec=args.batch_spec, data_root=args.data_root,
                output_root=args.output_root, archive=args.archive,
                expected_archive_sha256=args.expected_archive_sha256,
                expected_index_sha256=args.expected_index_sha256), indent=2))
        else:
            run_kwargs = dict(batch_spec=args.batch_spec, data_root=args.data_root,
                              output_root=args.output_root, resume=args.resume,
                              max_new_trials=args.max_new_trials,
                              max_wall_seconds=args.max_wall_seconds,
                              shard_manifest=args.shard_manifest, shard_id=args.shard_id)
            if args.shared_feature_cache:
                from src.research.e2_feature_cache import feature_cache_scope
                # The frozen private batch spec includes source and runner identities.
                # This is only a same-process, same-invocation optimization.
                spec_sha = _digest(args.batch_spec.read_bytes())
                with feature_cache_scope(batch_spec_sha256=spec_sha) as cache:
                    result = execute(**run_kwargs)
                    cache_metrics = cache.summary()
                result["feature_cache"] = cache_metrics
            else:
                result = execute(**run_kwargs)
            print(json.dumps(result, indent=2))
        return 0
    except (ExchangeError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile,
            subprocess.CalledProcessError) as exc:
        print(f"BLOCKED_COLAB_BATCH: {exc}", file=sys.stderr)
        return 10


if __name__ == "__main__":
    raise SystemExit(main())
