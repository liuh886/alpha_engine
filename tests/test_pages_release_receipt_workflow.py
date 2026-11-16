"""The Pages receipt observer must verify the revision Pages actually serves.

A manual ``workflow_dispatch`` deploy (for example a rollback) sets
``RELEASE_SHA`` from ``inputs.target_sha`` while ``workflow_run.head_sha``
stays at the repository's current HEAD. Verifying the live origin against
``head_sha`` would therefore fail on a correct rollback. The observer resolves
the deployed commit from the live ``deployment.json`` manifest instead.
"""

from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW = Path(".github/workflows/pages-release-receipt.yml")


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_observer_resolves_the_deployed_commit_from_the_live_manifest() -> None:
    text = _workflow_text()
    assert 'curl -fsS --max-time 60 "$PAGE_URL/deployment.json"' in text
    assert "artifacts/live-deployment.json" in text
    assert "commit_sha" in text
    assert 'git checkout --detach "$sha"' in text
    assert 'test "$(git rev-parse HEAD)" = "$sha"' in text
    assert "steps.deployed.outputs.sha" in text


def test_observer_verifies_the_resolved_commit_not_the_dispatched_head() -> None:
    text = _workflow_text()
    assert '--expected-commit "${{ steps.deployed.outputs.sha }}"' in text
    assert '--expected-commit "${{ github.event.workflow_run.head_sha }}"' not in text


def test_observer_reports_the_resolved_commit_with_a_skipped_fallback() -> None:
    text = _workflow_text()
    assert (
        "DEPLOYED_SHA: ${{ steps.deployed.outputs.sha || github.event.workflow_run.head_sha }}"
        in text
    )


def test_observer_workflow_remains_valid_yaml() -> None:
    assert isinstance(yaml.safe_load(_workflow_text()), dict)
