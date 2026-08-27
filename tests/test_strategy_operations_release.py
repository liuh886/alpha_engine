from __future__ import annotations

from pathlib import Path

import yaml


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

    restore = by_name["Restore publication idempotency receipt"]
    assert restore["continue-on-error"] is True
    assert restore["uses"] == "actions/cache/restore@v5"
    assert restore["with"] == {
        "path": "artifacts/strategy-operations-publication-receipt.json",
        "key": "strategy-operations-publication-v1-${{ steps.revision.outputs.sha }}",
        "lookup-only": True,
    }

    gated_names = {
        "Checkout canonical revision",
        "Verify canonical revision identity",
        "Setup Python",
        "Install locked environment",
        "Validate runtime publisher contract",
        "Materialize current operations from canonical evidence",
        "Publish current operations through GitHub OIDC",
        "Record publication receipt",
        "Retain publication artifacts",
    }
    assert gated_names <= set(by_name)
    for name in gated_names:
        assert by_name[name]["if"] == PUBLICATION_GATE

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
        "key": "strategy-operations-publication-v1-${{ steps.revision.outputs.sha }}",
    }


def test_byd_terminates_deep_workflow_chain_with_repository_dispatch() -> None:
    path = ROOT / ".github/workflows/byd-daily-signal-alert.yml"
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = content["jobs"]["evaluate"]["steps"]
    by_name = {step.get("name"): step for step in steps if step.get("name")}

    request = by_name["Request strategy operations publication"]
    assert request["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert 'event_type: "strategy_operations_publication"' in request["run"]
    assert '"repos/${GITHUB_REPOSITORY}/dispatches"' in request["run"]
    assert request["run"].index("producer_workflow") < request["run"].index("gh api")

    # BYD Daily can itself be the third workflow_run hop. The release workflow
    # therefore consumes this explicit dispatch, not another BYD workflow_run.
    release_triggers = _triggers(_workflow())
    assert "BYD v1.3 Daily Signal" not in release_triggers["workflow_run"]["workflows"]
    assert release_triggers["repository_dispatch"]["types"] == [
        "strategy_operations_publication"
    ]
