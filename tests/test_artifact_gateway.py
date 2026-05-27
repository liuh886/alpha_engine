import json

import pytest

from src.assistant.services.artifact_gateway import ArtifactGateway


def test_artifact_gateway_reads_known_json(tmp_path):
    dashboard_dir = tmp_path / "dashboard"
    dashboard_dir.mkdir()
    (dashboard_dir / "dashboard_db.json").write_text(
        json.dumps({"models": [{"id": "run1"}]}), encoding="utf-8"
    )

    gateway = ArtifactGateway(artifacts_dir=tmp_path)

    assert gateway.get_json("dashboard-db") == {"models": [{"id": "run1"}]}


def test_artifact_gateway_rejects_unknown_key(tmp_path):
    gateway = ArtifactGateway(artifacts_dir=tmp_path)

    with pytest.raises(ValueError, match="unknown artifact key"):
        gateway.resolve_json_path("../secrets")


def test_artifact_gateway_reads_arena_leaderboard(tmp_path):
    (tmp_path / "arena_leaderboard_arena1.json").write_text(
        json.dumps({"leaderboard": [{"run_id": "r1"}]}), encoding="utf-8"
    )

    gateway = ArtifactGateway(artifacts_dir=tmp_path)

    assert gateway.get_arena_leaderboard("arena1") == {"leaderboard": [{"run_id": "r1"}]}
