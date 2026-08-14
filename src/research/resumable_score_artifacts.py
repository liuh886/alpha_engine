"""Durable, fail-closed score checkpoints for long research experiments."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import traceback
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


SCORE_ARTIFACT_SCHEMA_VERSION = "1.0"
RUN_STATE_SCHEMA_VERSION = "1.0"
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _clean(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return _clean(value.item())
        except (TypeError, ValueError):
            pass
    return value


def canonical_sha256(payload: Any) -> str:
    """Hash one JSON-compatible identity using a stable canonical encoding."""

    encoded = json.dumps(
        _clean(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _atomic_write_json(path: Path, payload: Any) -> None:
    rendered = json.dumps(
        _clean(payload),
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    )
    _atomic_write_text(path, rendered + "\n")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid checkpoint JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"checkpoint JSON must be a mapping: {path}")
    return payload


def _segment(value: str, *, label: str) -> str:
    if not _SAFE_SEGMENT.fullmatch(value):
        raise ValueError(f"unsafe {label}: {value!r}")
    return value


class ScoreCheckpointStore:
    """Persist and explicitly resume exact score frames one fit unit at a time."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    def _unit_paths(
        self,
        contract_identity: str,
        window: str,
        pass_id: str,
    ) -> tuple[Path, Path]:
        window_segment = _segment(window, label="window")
        pass_segment = _segment(pass_id, label="pass_id")
        directory = self.root / contract_identity / window_segment / pass_segment
        return directory / "scores.csv", directory / "manifest.json"

    @staticmethod
    def _serialize_scores(scores: pd.DataFrame) -> tuple[str, list[str], list[str]]:
        if not isinstance(scores.index, pd.MultiIndex):
            raise ValueError("score checkpoint requires a MultiIndex")
        index_names = [str(value) for value in scores.index.names]
        if any(not value or value == "None" for value in index_names):
            raise ValueError("score checkpoint index levels must be named")
        columns = [str(value) for value in scores.columns]
        ordered = scores.copy().sort_index()
        ordered.columns = columns
        payload = ordered.reset_index().to_csv(
            index=False,
            lineterminator="\n",
            float_format="%.17g",
        )
        return payload, index_names, columns

    @staticmethod
    def _deserialize_scores(
        path: Path,
        *,
        index_names: list[str],
        columns: list[str],
        attrs: Mapping[str, Any],
    ) -> pd.DataFrame:
        dtype = {"instrument": str} if "instrument" in index_names else None
        frame = pd.read_csv(path, dtype=dtype)
        missing = sorted(set([*index_names, *columns]) - set(frame.columns))
        if missing:
            raise ValueError(f"score checkpoint columns are missing: {missing}")
        if "datetime" in index_names:
            frame["datetime"] = pd.to_datetime(frame["datetime"], errors="raise")
        if "instrument" in index_names:
            frame["instrument"] = frame["instrument"].astype(str).str.zfill(6)
        result = frame.set_index(index_names).loc[:, columns].sort_index()
        result.attrs.update(dict(attrs))
        return result

    def load_or_fit(
        self,
        *,
        contract: Mapping[str, Any],
        window: str,
        pass_id: str,
        resume: bool,
        fit: Callable[[], pd.DataFrame],
        score_hash: Callable[[pd.DataFrame], str],
    ) -> tuple[pd.DataFrame, dict[str, Any]]:
        """Load one exact checkpoint only under explicit resume, otherwise fit and save."""

        cleaned_contract = _clean(dict(contract))
        contract_identity = canonical_sha256(cleaned_contract)
        data_path, manifest_path = self._unit_paths(contract_identity, window, pass_id)
        directory_exists = data_path.parent.exists()
        if directory_exists:
            if not resume:
                raise ValueError(
                    "score checkpoint already exists; use explicit resume or a new checkpoint root: "
                    f"{data_path.parent}"
                )
            if not data_path.is_file() or not manifest_path.is_file():
                raise ValueError(f"incomplete score checkpoint: {data_path.parent}")
            manifest = _read_json(manifest_path)
            expected = {
                "schema_version": SCORE_ARTIFACT_SCHEMA_VERSION,
                "contract_identity_sha256": contract_identity,
                "contract": cleaned_contract,
                "window": window,
                "pass_id": pass_id,
                "status": "completed",
            }
            for key, value in expected.items():
                if manifest.get(key) != value:
                    raise ValueError(f"score checkpoint identity mismatch at {key}")
            observed_file_hash = file_sha256(data_path)
            if observed_file_hash != manifest.get("content_sha256"):
                raise ValueError("score checkpoint content hash mismatch")
            scores = self._deserialize_scores(
                data_path,
                index_names=list(manifest.get("index_names") or []),
                columns=list(manifest.get("columns") or []),
                attrs=dict(manifest.get("attrs") or {}),
            )
            observed_score_hash = score_hash(scores)
            if observed_score_hash != manifest.get("score_sha256"):
                raise ValueError("score checkpoint semantic hash mismatch")
            return scores, {**manifest, "reused": True, "path": str(data_path.parent)}

        scores = fit()
        if not isinstance(scores, pd.DataFrame) or scores.empty:
            raise ValueError("fit returned an empty or non-DataFrame score artifact")
        payload, index_names, columns = self._serialize_scores(scores)
        data_path.parent.mkdir(parents=True, exist_ok=False)
        _atomic_write_text(data_path, payload)
        manifest = {
            "schema_version": SCORE_ARTIFACT_SCHEMA_VERSION,
            "contract_identity_sha256": contract_identity,
            "contract": cleaned_contract,
            "window": window,
            "pass_id": pass_id,
            "status": "completed",
            "row_count": int(len(scores)),
            "index_names": index_names,
            "columns": columns,
            "attrs": _clean(dict(scores.attrs)),
            "content_sha256": file_sha256(data_path),
            "score_sha256": score_hash(scores),
            "completed_at": _utc_now(),
        }
        _atomic_write_json(manifest_path, manifest)
        return scores, {**manifest, "reused": False, "path": str(data_path.parent)}


class RunStateTracker:
    """Maintain an atomic heartbeat and append-only progress log for one long run."""

    def __init__(
        self,
        output_dir: str | Path,
        *,
        experiment_id: str,
        runner: str,
        spec_identity_sha256: str,
        total_fit_units: int,
        resume: bool,
        heartbeat_seconds: float = 30.0,
    ) -> None:
        self.output_dir = Path(output_dir).resolve()
        self.state_path = self.output_dir / "run_state.json"
        self.log_path = self.output_dir / "run_progress.jsonl"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._heartbeat_seconds = heartbeat_seconds
        existing = _read_json(self.state_path) if self.state_path.is_file() else None
        if existing is not None and not resume:
            raise ValueError(
                "run state already exists; use explicit resume or a new output directory"
            )
        if existing is not None:
            if existing.get("experiment_id") != experiment_id:
                raise ValueError("run-state experiment identity mismatch")
            if existing.get("spec_identity_sha256") != spec_identity_sha256:
                raise ValueError("run-state spec identity mismatch")
        self.state: dict[str, Any] = {
            "schema_version": RUN_STATE_SCHEMA_VERSION,
            "experiment_id": experiment_id,
            "runner": runner,
            "spec_identity_sha256": spec_identity_sha256,
            "pid": os.getpid(),
            "attempt": int((existing or {}).get("attempt", 0)) + 1,
            "resumed_from_status": (existing or {}).get("status") if resume else None,
            "started_at": _utc_now(),
            "updated_at": _utc_now(),
            "status": "running",
            "phase": "initializing",
            "completed_fit_units": 0,
            "total_fit_units": int(total_fit_units),
            "current_unit": None,
            "completed_units": [],
            "checkpoint_hashes": {},
            "heartbeat_count": 0,
            "exit_code": None,
            "error": None,
        }

    def _append_event(self, event: str, details: Mapping[str, Any] | None = None) -> None:
        payload = {
            "timestamp": _utc_now(),
            "event": event,
            "pid": os.getpid(),
            "details": _clean(dict(details or {})),
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _write_locked(self) -> None:
        self.state["updated_at"] = _utc_now()
        _atomic_write_json(self.state_path, self.state)

    def start(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._write_locked()
            self._append_event("run_started", self.state)
        if self._heartbeat_seconds > 0:
            self._thread = threading.Thread(
                target=self._heartbeat_loop,
                name="research-run-heartbeat",
                daemon=True,
            )
            self._thread.start()

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self._heartbeat_seconds):
            with self._lock:
                if self.state["status"] != "running":
                    return
                self.state["heartbeat_count"] = int(self.state["heartbeat_count"]) + 1
                self._write_locked()

    def set_phase(self, phase: str) -> None:
        with self._lock:
            self.state["phase"] = phase
            self._write_locked()
            self._append_event("phase_changed", {"phase": phase})

    def begin_unit(self, unit: Mapping[str, Any]) -> None:
        with self._lock:
            self.state["phase"] = "fitting_scores"
            self.state["current_unit"] = _clean(dict(unit))
            self._write_locked()
            self._append_event("fit_unit_started", dict(unit))

    def complete_unit(self, unit_key: str, checkpoint: Mapping[str, Any]) -> None:
        with self._lock:
            completed = list(self.state["completed_units"])
            if unit_key not in completed:
                completed.append(unit_key)
            self.state["completed_units"] = completed
            self.state["completed_fit_units"] = len(completed)
            self.state["checkpoint_hashes"][unit_key] = checkpoint.get("score_sha256")
            self.state["current_unit"] = None
            self._write_locked()
            self._append_event(
                "fit_unit_completed",
                {
                    "unit_key": unit_key,
                    "score_sha256": checkpoint.get("score_sha256"),
                    "reused": bool(checkpoint.get("reused")),
                },
            )

    def finish(self, *, status: str, decision: str | None = None) -> None:
        with self._lock:
            self.state["status"] = status
            self.state["phase"] = "finished"
            self.state["current_unit"] = None
            self.state["decision"] = decision
            self.state["exit_code"] = 0 if status == "completed" else 1
            self._write_locked()
            self._append_event("run_finished", {"status": status, "decision": decision})
        self._shutdown_heartbeat()

    def fail(self, exc: BaseException) -> None:
        with self._lock:
            self.state["status"] = "failed"
            self.state["phase"] = "failed"
            self.state["exit_code"] = 1
            self.state["error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
            self._write_locked()
            self._append_event("run_failed", self.state["error"])
        self._shutdown_heartbeat()

    def _shutdown_heartbeat(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
