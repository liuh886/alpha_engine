from __future__ import annotations

import json
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_ROOT = REPOSITORY_ROOT / "qlib-dashboard"
MODEL_DATA_ROOT = REPOSITORY_ROOT / "data/research/model_data_bundle_v1"
PUBLISHED_FILES = (
    "model-data-readiness.json",
    "data-components.json",
    "training-profiles.json",
)


def test_model_data_sync_is_part_of_research_asset_publication() -> None:
    package = json.loads((DASHBOARD_ROOT / "package.json").read_text(encoding="utf-8"))
    scripts = package["scripts"]
    assert scripts["sync:model-data"] == "node scripts/sync-model-data.mjs"
    assert "npm run sync:model-data" in scripts["sync:research-assets"]


def test_model_data_sync_publishes_exact_governed_read_models() -> None:
    subprocess.run(
        ["node", "scripts/sync-model-data.mjs"],
        cwd=DASHBOARD_ROOT,
        check=True,
    )

    target_root = DASHBOARD_ROOT / "public/data"
    for name in PUBLISHED_FILES:
        source = MODEL_DATA_ROOT / name
        target = target_root / name
        assert target.read_bytes() == source.read_bytes()
        json.loads(target.read_text(encoding="utf-8"))
