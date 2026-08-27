from __future__ import annotations

import json
from pathlib import Path

import yaml

from scripts.detect_pages_impact import decide_impact

ROOT = Path(__file__).resolve().parents[1]


def _repository(tmp_path: Path) -> Path:
    catalog = {
        "published_models": [
            {
                "model_id": "us_x1_0",
                "source": "configs/models/us_x1_0.yaml",
                "primary_run_id": "run-us",
            }
        ],
        "published_runs": [
            {"run_id": "run-us", "source": "data/research/runs/run-us"}
        ],
    }
    (tmp_path / "data/research").mkdir(parents=True)
    (tmp_path / "data/research/catalog.json").write_text(json.dumps(catalog))
    (tmp_path / "configs/models").mkdir(parents=True)
    (tmp_path / "configs/models/us_x1_0.yaml").write_text(
        "model_id: us_x1_0\n"
        "evidence_identity:\n"
        "  result_report: docs/research/us-result.md\n"
    )
    return tmp_path


def test_frontend_change_deploys(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    decision = decide_impact(["qlib-dashboard/src/App.tsx"], repository_root=root)
    assert decision.deploy is True
    assert decision.reason == "publication_dependency_changed"


def test_model_run_bundle_and_market_evidence_changes_deploy(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    for path in (
        "data/research/formal_model_runs/us_ranker/us_x1_1/run/manifest.json",
        "data/research/market_evidence/us/catalog.json",
        "data/research/market_evidence/us/symbols/AAPL.json",
        "data/research/model_data_bundle_v1/model-data-readiness.json",
        "data/research/model_runs/us_ranker/us_candidate/run/summary.json",
        "data/research/model_decisions/catalog.json",
    ):
        decision = decide_impact([path], repository_root=root)
        assert decision.deploy is True, path
        assert path in decision.matched_paths


def test_referenced_model_run_and_report_deploy(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    for path in (
        "configs/models/us_x1_0.yaml",
        "data/research/runs/run-us/metrics.json",
        "docs/research/us-result.md",
    ):
        decision = decide_impact([path], repository_root=root)
        assert decision.deploy is True, path


def test_unreferenced_research_and_docs_skip(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    decision = decide_impact(
        [
            "data/research/experiments/candidate-b.json",
            "docs/research/unpublished-note.md",
            "configs/models/candidates/candidate-b.yaml",
        ],
        repository_root=root,
    )
    assert decision.deploy is False
    assert decision.reason == "no_publication_impact"
    assert decision.matched_paths == ()


def test_catalog_and_release_runtime_changes_deploy(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    for path in (
        "data/research/catalog.json",
        "scripts/export_static_site_data.py",
        "src/artifacts/model_run_bundle_v2.py",
        ".github/workflows/pages-release-receipt.yml",
    ):
        decision = decide_impact([path], repository_root=root)
        assert decision.deploy is True, path


def test_dependency_resolution_failure_fails_closed(tmp_path: Path) -> None:
    (tmp_path / "data/research").mkdir(parents=True)
    (tmp_path / "data/research/catalog.json").write_text("{not-json")
    decision = decide_impact(["README.md"], repository_root=tmp_path)
    assert decision.deploy is True
    assert decision.reason == "fail_closed_dependency_resolution"
    assert decision.fail_closed_detail


def test_manual_dispatch_is_always_deployed(tmp_path: Path) -> None:
    decision = decide_impact(
        [],
        repository_root=tmp_path,
        forced_reason="manual_dispatch",
    )
    assert decision.deploy is True
    assert decision.reason == "manual_dispatch"


def test_pages_release_receipt_workflow_skips_operations_only_workflow_run() -> None:
    workflow_path = ROOT / ".github/workflows/pages-release-receipt.yml"
    text = workflow_path.read_text(encoding="utf-8")
    assert "if: github.event.workflow_run.event != 'workflow_run'" in text

    content = yaml.safe_load(text)
    triggers = content.get("on") if "on" in content else content.get(True)
    assert triggers is not None
    assert triggers["workflow_run"]["workflows"] == ["Deploy Strategy Console to Pages"]
    assert triggers["workflow_run"]["types"] == ["completed"]

    job = content["jobs"]["publish-receipt"]
    assert job["if"] == "github.event.workflow_run.event != 'workflow_run'"
    assert content["concurrency"] == {
        "group": "pages-release-receipt-${{ github.event.workflow_run.event }}",
        "cancel-in-progress": True,
    }

    # Contract behavior: skips for operations-only upstream workflow_run runs,
    # isolates them from real receipts before the job condition is evaluated,
    # and preserves publication for push and manual workflow_dispatch deploys.
    condition = job["if"]
    assert "event != 'workflow_run'" in condition
