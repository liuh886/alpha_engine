import tempfile
from pathlib import Path

import pytest

from src.assistant.arena_index import ArenaIndex
from src.assistant.model_registry_index import ModelRegistryIndex


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as file:
        path = Path(file.name)
    yield path
    if path.exists():
        path.unlink()


def test_arena_participant_with_model_version(temp_db):
    arena_index = ArenaIndex(db_path=temp_db)
    model_index = ModelRegistryIndex(db_path=temp_db)

    arena = arena_index.create_arena(name="Test Arena", market="us")
    arena_id = arena["id"]
    model_index.upsert_entry(
        {"id": "v1.0", "run_id": "run_abc", "market": "us", "tag": "LGBM"}
    )

    participant = arena_index.add_participant(
        arena_id=arena_id,
        name="Participant 1",
        run_id="run_abc",
        model_version_id="v1.0",
    )

    assert participant["run_id"] == "run_abc"
    assert participant["model_version_id"] == "v1.0"
    assert arena_index.list_participants(arena_id=arena_id)[0]["model_version_id"] == "v1.0"

    duplicate = arena_index.add_participant(
        arena_id=arena_id,
        name="Participant 1 duplicate",
        run_id="run_abc",
        model_version_id="v1.0",
    )
    assert duplicate["id"] == participant["id"]

    second_version = arena_index.add_participant(
        arena_id=arena_id,
        name="Participant 2",
        run_id="run_abc",
        model_version_id="v2.0",
    )
    assert second_version["id"] != participant["id"]
    assert second_version["model_version_id"] == "v2.0"
