from __future__ import annotations

from pathlib import Path

from src.artifacts.formal_bundle_retention import pinned_benchmark_manifest_paths


def test_pinned_benchmark_manifests_are_read_from_nested_configs(tmp_path: Path) -> None:
    config = tmp_path / "configs" / "research_paradigms" / "frozen.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(
        "challenge:\n"
        "  benchmark_manifest: data/research/formal_model_runs/f/m/r/manifest.json\n",
        encoding="utf-8",
    )
    unrelated = tmp_path / "configs" / "models" / "unrelated.yaml"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("model_version_id: demo\n", encoding="utf-8")

    pinned = pinned_benchmark_manifest_paths(tmp_path)

    assert pinned == {
        (tmp_path / "data/research/formal_model_runs/f/m/r/manifest.json").resolve()
    }


def test_pinned_benchmark_manifests_tolerate_absent_configs(tmp_path: Path) -> None:
    assert pinned_benchmark_manifest_paths(tmp_path) == set()
