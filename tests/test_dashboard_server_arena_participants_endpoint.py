import tempfile
from pathlib import Path

import pytest

from src.assistant.arena_index import ArenaIndex
from src.assistant.model_registry_index import ModelRegistryIndex


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = Path(f.name)
    yield path
    if path.exists():
        path.unlink()


def test_arena_participant_with_model_version(temp_db):
    arena_idx = ArenaIndex(db_path=temp_db)
    model_idx = ModelRegistryIndex(db_path=temp_db)

    # 1. Setup Arena
    arena = arena_idx.create_arena(name="Test Arena", market="us")
    arena_id = arena["id"]

    # 2. Setup Model Version
    model_idx.upsert_entry({"id": "v1.0", "run_id": "run_abc", "market": "us", "tag": "LGBM"})

    # 3. Add participant with both IDs
    p = arena_idx.add_participant(
        arena_id=arena_id, name="Participant 1", run_id="run_abc", model_version_id="v1.0"
    )

    assert p["run_id"] == "run_abc"
    assert p["model_version_id"] == "v1.0"

    # 4. List and check
    participants = arena_idx.list_participants(arena_id=arena_id)
    assert len(participants) == 1
    assert participants[0]["model_version_id"] == "v1.0"

    # 5. Test idempotency with same IDs
    p2 = arena_idx.add_participant(
        arena_id=arena_id, name="Participant 1 duplicate", run_id="run_abc", model_version_id="v1.0"
    )
    assert p2["id"] == p["id"]

    # 6. Test different model version for same run (should be allowed now)
    p3 = arena_idx.add_participant(
        arena_id=arena_id, name="Participant 2", run_id="run_abc", model_version_id="v2.0"
    )
    assert p3["id"] != p["id"]
    assert p3["model_version_id"] == "v2.0"
