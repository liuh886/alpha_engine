"""Governance automation for research entropy: lifecycle graph + archive guard."""

from __future__ import annotations

from pathlib import Path

from scripts.check_ci_governance import (
    archive_reference_violations,
    inspect_research_assets,
)


def _tree(root: Path) -> None:
    (root / "configs" / "research_paradigms").mkdir(parents=True)
    (root / "configs" / "research_experiments").mkdir(parents=True)
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "src").mkdir(parents=True)
    (root / "docs").mkdir(parents=True)
    paradigms = root / "configs" / "research_paradigms"
    (paradigms / "live_scheduled.yaml").write_text(
        "id: live_scheduled\n", encoding="utf-8"
    )
    (paradigms / "live_code.yaml").write_text("id: live_code\n", encoding="utf-8")
    (paradigms / "dead.yaml").write_text("id: dead\n", encoding="utf-8")
    (root / ".github" / "workflows" / "feed.yml").write_text(
        "on: {schedule: [{cron: '0 0 * * *'}]}\njobs: {x: {steps: [{run: 'x live_scheduled'}]}}\n",
        encoding="utf-8",
    )
    (root / "src" / "engine.py").write_text("SPEC = 'live_code'\n", encoding="utf-8")
    (root / "docs" / "notes.md").write_text("we once tried dead\n", encoding="utf-8")


def test_lifecycle_derivation_separates_life_from_history(tmp_path: Path) -> None:
    _tree(tmp_path)
    assets = inspect_research_assets(tmp_path)

    assert assets["paradigm_count"] == 3
    assert assets["lifecycles"]["live_scheduled"] == "scheduled"
    assert assets["lifecycles"]["live_code"] == "referenced_only"
    # docs mentions never count as life.
    assert assets["lifecycles"]["dead"] == "orphan_candidate"
    assert assets["orphan_candidates"] == ["dead"]


def test_self_mentions_do_not_confer_life(tmp_path: Path) -> None:
    _tree(tmp_path)
    lonely = tmp_path / "configs" / "research_paradigms" / "lonely.yaml"
    lonely.write_text("id: lonely\nnotes: lonely supersedes nothing\n", encoding="utf-8")

    assets = inspect_research_assets(tmp_path)

    assert assets["lifecycles"]["lonely"] == "orphan_candidate"


def test_paradigm_to_paradigm_notes_do_not_confer_life(tmp_path: Path) -> None:
    _tree(tmp_path)
    (tmp_path / "configs" / "research_paradigms" / "dead.yaml").write_text(
        "id: dead\nnotes: supersedes live_code\n", encoding="utf-8"
    )

    assets = inspect_research_assets(tmp_path)

    assert assets["lifecycles"]["dead"] == "orphan_candidate"


def test_archive_references_are_blocking_violations(tmp_path: Path) -> None:
    _tree(tmp_path)
    # NOTE: the marker is assembled dynamically so this test file itself does
    # not become a (fake) live caller of the archive it protects.
    marker = "configs/research_paradigms/" + "archive/old.yaml"
    (tmp_path / "src" / "sneaky.py").write_text(
        f"SPEC = '{marker}'\n", encoding="utf-8"
    )

    violations = archive_reference_violations(tmp_path)

    assert len(violations) == 1
    assert "sneaky.py" in violations[0]


def test_clean_tree_has_no_archive_violations(tmp_path: Path) -> None:
    _tree(tmp_path)

    assert archive_reference_violations(tmp_path) == []
