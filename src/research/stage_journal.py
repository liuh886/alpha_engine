"""Content-addressed stage journal for resumable long research runs.

Long experiment loops (candidate grids across development windows) spend
hours on feature loading and model fitting. A crash mid-run previously
meant restarting from zero. This journal records each completed stage as
an atomic JSON file keyed by a deterministic content fingerprint, so a
re-run skips exactly the stages whose inputs have not changed and
recomputes everything else.

Design rules:

- Fingerprints are canonical-json sha256 over stage *inputs* only; wall
  clock never participates in resume decisions.
- Records are written atomically (tmp + rename), so a killed process can
  never leave a half-written completion behind.
- Resume is opt-in per run (`resume_journal_root=None` keeps legacy
  behavior bit-for-bit).
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

STAGE_JOURNAL_DIR = "stage_journal"


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, allow_nan=False
    ).encode("utf-8")


def fingerprint(payload: Any) -> str:
    """Deterministic content digest over stage inputs."""

    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class StageDecision:
    action: str  # "reuse" or "run"
    stage_id: str
    fingerprint: str
    result: Mapping[str, Any] | None


class StageJournal:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.dir = self.root / STAGE_JOURNAL_DIR

    def _stage_path(self, stage_id: str) -> Path:
        if not stage_id or "/" in stage_id or "\\" in stage_id or ".." in stage_id:
            raise ValueError(f"unsafe stage_id: {stage_id!r}")
        return self.dir / f"{stage_id}.json"

    def record(self, *, stage_id: str, fp: str, result: Mapping[str, Any]) -> None:
        path = self._stage_path(stage_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"stage_id": stage_id, "fingerprint": fp, "result": dict(result)}
        tmp = path.with_suffix(".json.tmp")
        tmp.write_bytes(canonical_bytes(payload))
        os.replace(tmp, path)

    def load(self, stage_id: str, fp: str) -> Mapping[str, Any] | None:
        """Return the recorded result iff the stage completed with this fp."""

        path = self._stage_path(stage_id)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"corrupt stage journal entry: {path}") from exc
        if (
            not isinstance(payload, dict)
            or payload.get("stage_id") != stage_id
            or payload.get("fingerprint") != fp
        ):
            return None
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ValueError(f"stage journal entry lacks a result object: {path}")
        return result

    def decide(
        self,
        *,
        stage_id: str,
        fp: str,
        required_artifacts: tuple[Path, ...] = (),
    ) -> StageDecision:
        """Reuse the recorded result iff fingerprints match and every
        referenced artifact still exists on disk; otherwise run."""

        recorded = self.load(stage_id, fp)
        if recorded is None:
            return StageDecision("run", stage_id, fp, None)
        for artifact in required_artifacts:
            if not Path(artifact).is_file():
                return StageDecision("run", stage_id, fp, None)
        return StageDecision("reuse", stage_id, fp, recorded)
