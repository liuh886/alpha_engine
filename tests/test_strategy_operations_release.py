from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.doctor import diagnose


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/strategy-operations-release.yml"
PUBLICATION_GATE = "steps.cache.outputs.cache-hit != 'true' || inputs.force == true"


def _workflow() -> dict:
    content = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(content, dict)
    return content


def _triggers(content: dict) -> dict:
    triggers = content.get("on") if "on" in content else content.get(True)
    assert isinstance(triggers, dict)
    return triggers


def _steps(content: dict) -> list[dict]:
    steps = content["jobs"]["publish-operations"]["steps"]
    assert isinstance(steps, list)
    return steps


def test_release_triggers_and_serializes_all_canonical_sources() -> None:
    content = _workflow()
    triggers = _triggers(content)

    assert triggers["push"]["branches"] == ["main"]
    assert triggers["workflow_run"] == {
        "workflows": [
            "QQQ Rotation v4.3 Signal Alert",
            "10D Ranker Current Target",
            "Reviewed Formal Backtest Refresh",
        ],
        "types": ["completed"],
    }
    assert triggers["repository_dispatch"] == {
        "types": ["strategy_operations_publication"]
    }
    assert triggers["schedule"] == [{"cron": "0 */6 * * *"}]
    assert triggers["workflow_dispatch"]["inputs"]["force"] == {
        "description": "Force publication bypassing cache receipt",
        "type": "boolean",
        "required": False,
        "default": False,
    }
    assert content["concurrency"] == {
        "group": "strategy-operations-publication",
        "cancel-in-progress": False,
    }

    condition = " ".join(content["jobs"]["publish-operations"]["if"].split())
    assert condition == (
        "github.event_name == 'push' || github.event_name == 'schedule' || "
        "github.event_name == 'workflow_dispatch' || "
        "github.event_name == 'repository_dispatch' || "
        "(github.event_name == 'workflow_run' && "
        "github.event.workflow_run.conclusion == 'success' && "
        "github.event.workflow_run.head_branch == 'main')"
    )


def test_release_uses_exact_revision_and_success_only_idempotency_receipt() -> None:
    content = _workflow()
    steps = _steps(content)
    by_name = {step["name"]: step for step in steps}

    revision = by_name["Resolve current canonical main SHA"]
    assert revision["id"] == "revision"
    assert "git/ref/heads/main" in revision["run"]
    assert "^[0-9a-f]{40}$" in revision["run"]
    assert 'echo "sha=$sha" >> "$GITHUB_OUTPUT"' in revision["run"]
    assert '21600' in revision["run"]
    assert 'echo "window=' in revision["run"]

    restore = by_name["Restore publication idempotency receipt"]
    assert restore["continue-on-error"] is True
    assert restore["uses"] == "actions/cache/restore@v5"
    assert restore["with"] == {
        "path": "artifacts/strategy-operations-publication-receipt.json",
        "key": "strategy-operations-publication-v3-${{ steps.revision.outputs.sha }}-${{ steps.private_ledgers.outputs.archive_sha256 }}-${{ steps.revision.outputs.window }}",
        "lookup-only": True,
    }

    gated_names = {
        "Validate runtime publisher contract",
        "Materialize current operations from canonical evidence",
        "Publish current operations through GitHub OIDC",
        "Record publication receipt",
        "Retain publication artifacts",
    }
    assert gated_names <= set(by_name)
    for name in gated_names:
        assert by_name[name]["if"] == PUBLICATION_GATE

    ordered = list(by_name)
    assert ordered.index("Restore authoritative private ledgers") < ordered.index("Restore publication idempotency receipt")
    assert "if" not in by_name["Restore authoritative private ledgers"]
    checkout = by_name["Checkout canonical revision"]
    assert checkout["with"]["ref"] == "${{ steps.revision.outputs.sha }}"
    verify = by_name["Verify canonical revision identity"]["run"]
    assert 'git rev-parse HEAD' in verify
    assert "steps.revision.outputs.sha" in verify

    receipt = by_name["Record publication receipt"]["run"]
    for contract in (
        '"schema_version": "1.0.0"',
        '"status": "success"',
        '"canonical_sha": os.environ["CANONICAL_SHA"]',
        '"research_only": True',
        '"trade_ready": False',
    ):
        assert contract in receipt

    ordered_names = [step["name"] for step in steps]
    assert ordered_names.index("Publish current operations through GitHub OIDC") < ordered_names.index(
        "Record publication receipt"
    )
    assert ordered_names.index("Record publication receipt") < ordered_names.index(
        "Retain publication artifacts"
    )
    assert ordered_names.index("Retain publication artifacts") < ordered_names.index(
        "Save successful publication receipt"
    )

    save = by_name["Save successful publication receipt"]
    assert save["if"] == "steps.cache.outputs.cache-hit != 'true'"
    assert save["continue-on-error"] is True
    assert save["uses"] == "actions/cache/save@v5"
    assert save["with"] == {
        "path": "artifacts/strategy-operations-publication-receipt.json",
        "key": "strategy-operations-publication-v3-${{ steps.revision.outputs.sha }}-${{ steps.private_ledgers.outputs.archive_sha256 }}-${{ steps.revision.outputs.window }}",
    }


def test_byd_terminates_deep_workflow_chain_with_repository_dispatch() -> None:
    path = ROOT / ".github/workflows/byd-daily-signal-alert.yml"
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = content["jobs"]["evaluate"]["steps"]
    by_name = {step.get("name"): step for step in steps if step.get("name")}

    request = by_name["Request canonical decision delivery"]
    assert request["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert 'event_type: "strategy_signal_delivery"' in request["run"]
    assert '"repos/${GITHUB_REPOSITORY}/dispatches"' in request["run"]
    assert request["run"].index("producer_workflow") < request["run"].index("gh api")

    assert steps.index(by_name["Commit canonical BYD decision"]) < steps.index(request)
    # BYD Daily can itself be the third workflow_run hop. Deliver through the
    # existing outbox before its receipt dispatches operations publication.
    outbox = yaml.safe_load((ROOT / ".github/workflows/strategy-signal-delivery-outbox.yml").read_text())
    assert _triggers(outbox)["repository_dispatch"]["types"] == ["strategy_signal_delivery"]
    assert "BYD v1.3 Daily Signal" not in _triggers(outbox)["workflow_run"]["workflows"]
    delivery_steps = {step.get("name"): step for step in outbox["jobs"]["deliver"]["steps"]}
    assert 'event_type: "strategy_operations_publication"' in delivery_steps["Request strategy operations publication"]["run"]
    release_triggers = _triggers(_workflow())
    assert "BYD v1.3 Daily Signal" not in release_triggers["workflow_run"]["workflows"]
    assert release_triggers["repository_dispatch"]["types"] == [
        "strategy_operations_publication"
    ]


def test_cn27_publishes_sealed_observations_through_existing_dispatch() -> None:
    content = yaml.safe_load((ROOT / ".github/workflows/cn27-current-target.yml").read_text())
    steps = content["jobs"]["evaluate"]["steps"]
    request = next(step for step in steps if step.get("name") == "Request strategy operations publication")
    assert request["if"] == "github.event_name != 'pull_request'"
    assert request["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert 'event_type: "strategy_operations_publication"' in request["run"]
    assert '"repos/${GITHUB_REPOSITORY}/dispatches"' in request["run"]


def test_review_collection_is_independent_of_publish_cache_and_retains_failure_evidence() -> None:
    content = _workflow()
    job = content["jobs"]["collect-operating-evidence"]
    assert job["needs"] == "publish-operations"
    assert "!cancelled()" in job["if"] and "head_branch == 'main'" in job["if"]
    assert "conclusion == 'success'" not in job["if"]
    assert job["permissions"] == {"contents": "read", "actions": "read"}
    steps = {step.get("name"): step for step in job["steps"]}
    collect = steps["Collect current review without declaring acceptance"]
    assert "--collect-repository" in collect["run"] and "--archive-repository" in collect["run"]
    assert "--declarations" not in collect["run"]
    assert "GOVERNED_SOURCE_ARCHIVE_WRITE_SSH_KEY" in collect["env"]
    retain = steps["Retain operating review packet"]
    assert retain["if"] == "always()" and retain["with"]["retention-days"] == 90


@pytest.mark.parametrize("job_name", ["publish-operations", "collect-operating-evidence"])
def test_declared_checkout_reproduces_full_operations_and_health(
    tmp_path: Path, job_name: str,
) -> None:
    steps = _workflow()["jobs"][job_name]["steps"]
    checkout = next(step for step in steps if step.get("uses") == "actions/checkout@v6")["with"]
    assert checkout["fetch-depth"] == 1 and checkout["lfs"] is False
    assert checkout["sparse-checkout-cone-mode"] is True
    root = tmp_path / "checkout"
    for relative in checkout["sparse-checkout"].splitlines():
        relative = relative.strip()
        if relative:
            shutil.copytree(ROOT / relative, root / relative,
                            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # Cone checkout includes root files; these are the locked environment inputs.
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copyfile(ROOT / name, root / name)
    assert not (root / "data/research/market_evidence").exists()
    assert not (root / "data/csv_clean").exists()
    assert (root / ".github/actions/setup-python-uv/action.yml").is_file()
    freshness = json.loads((ROOT / "data/research/formal_model_runs/freshness.json").read_text(encoding="utf-8"))
    generated_at = freshness["declared_at"]
    expected_health, expected_operations = diagnose(ROOT, generated_at=generated_at)
    result = subprocess.run(
        [sys.executable, "-m", "src.cli.main", "ops", "build",
         "--generated-at", generated_at, "--output", "artifacts/snapshots.json"],
        cwd=root, env={**os.environ, "PYTHONPATH": str(root)},
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads((root / "artifacts/snapshots.json").read_text(encoding="utf-8")) == expected_operations
    assert json.loads((root / "artifacts/system-health.json").read_text(encoding="utf-8")) == expected_health
