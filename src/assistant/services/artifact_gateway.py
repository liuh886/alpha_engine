from __future__ import annotations

import json
from pathlib import Path


class ArtifactGateway:
    def __init__(self, *, artifacts_dir: str | Path):
        self._artifacts_dir = Path(artifacts_dir)

    def get_json(self, artifact_key: str) -> dict:
        path = self.resolve_json_path(artifact_key)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"artifact not found: {artifact_key}")
        return json.loads(path.read_text(encoding="utf-8"))

    def get_arena_leaderboard(self, arena_id: str) -> dict:
        arena_id = str(arena_id or "").strip()
        if not arena_id or "/" in arena_id or "\\" in arena_id:
            raise ValueError("invalid arena_id")
        path = self._artifacts_dir / f"arena_leaderboard_{arena_id}.json"
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"arena leaderboard not found: {arena_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def resolve_json_path(self, artifact_key: str) -> Path:
        known = {
            "dashboard-db": self._artifacts_dir / "dashboard" / "dashboard_db.json",
            "thought-stream": self._artifacts_dir / "agent_thought_stream.json",
            "arenas": self._artifacts_dir / "arenas.json",
            "reports": self._artifacts_dir / "reports.json",
            "models": self._artifacts_dir / "models.json",
            "data-status": self._artifacts_dir / "data_status.json",
            "data-quality": self._artifacts_dir / "data_quality.json",
        }
        if artifact_key not in known:
            raise ValueError(f"unknown artifact key: {artifact_key}")
        return known[artifact_key]
