from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml

WORKFLOW_ROOT = Path(".github/workflows")

REQUIRED_PR = {
    "ci.yml",
    "frontend-static-pwa.yml",
    "governance-contracts.yml",
    "model-data-bundle-ci.yml",
    "pages-governance-ci.yml",
    "researcher-data-cli-ci.yml",
}
RELEASE_MARKERS = (
    "deploy",
    "pages",
    "promotion",
    "release",
    "lifecycle",
)
ADVISORY_MARKERS = (
    "advisory",
    "dependency",
    "health",
    "security",
    "watch",
)
RUN_ID_PATTERN = re.compile(r"\brun-id\s*:\s*['\"]?\d{6,}")
ACTION_PATTERN = re.compile(r"uses:\s*([^\s@]+)@([^\s#]+)")
NODE_PATTERN = re.compile(r"node-version:\s*['\"]?([^'\"\s]+)")


def load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return payload


def classify(filename: str) -> tuple[str, str]:
    lowered = filename.lower()
    if filename in REQUIRED_PR:
        return "tier_1_required_pr", "repository-local deterministic product contract"
    if any(marker in lowered for marker in ADVISORY_MARKERS):
        return "tier_4_advisory", "health or diagnostic signal"
    if any(marker in lowered for marker in RELEASE_MARKERS):
        return "tier_2_main_release", "main integration, formal promotion, or deployment"
    return "tier_3_research_evidence", "specialized research, provider, or evidence workflow"


def normalize_trigger(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, str):
        return {raw: None}
    if isinstance(raw, list):
        return {str(item): None for item in raw}
    if isinstance(raw, dict):
        return {str(key): value for key, value in raw.items()}
    raise ValueError(f"unsupported workflow trigger shape: {type(raw).__name__}")


def list_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def trigger_summary(triggers: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for event, config in sorted(triggers.items()):
        if isinstance(config, dict):
            result[event] = {
                "branches": list_values(config.get("branches")),
                "paths": list_values(config.get("paths")),
                "paths_ignore": list_values(config.get("paths-ignore")),
                "types": list_values(config.get("types")),
                "inputs": sorted((config.get("inputs") or {}).keys())
                if isinstance(config.get("inputs"), dict)
                else [],
            }
        else:
            result[event] = {}
    return result


def artifact_names(payload: dict[str, Any]) -> list[str]:
    names: set[str] = set()
    jobs = payload.get("jobs")
    if not isinstance(jobs, dict):
        return []
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            uses = str(step.get("uses", ""))
            with_block = step.get("with")
            if "upload-artifact" in uses and isinstance(with_block, dict):
                name = with_block.get("name")
                if name:
                    names.add(str(name))
    return sorted(names)


def inspect_workflow(path: Path) -> tuple[dict[str, Any], list[str]]:
    text = path.read_text(encoding="utf-8")
    payload = load_yaml(path)
    name = str(payload.get("name", "")).strip()
    triggers = normalize_trigger(payload.get("on"))
    tier, rationale = classify(path.name)
    trigger_data = trigger_summary(triggers)
    pr_config = trigger_data.get("pull_request", {})
    pr_paths = list(pr_config.get("paths", [])) + list(pr_config.get("paths_ignore", []))
    actions = sorted({f"{name}@{version}" for name, version in ACTION_PATTERN.findall(text)})
    node_versions = sorted(set(NODE_PATTERN.findall(text)))
    hardcoded_run_ids = RUN_ID_PATTERN.findall(text)

    violations: list[str] = []
    if not name:
        violations.append("workflow name is missing")
    if not triggers:
        violations.append("workflow has no trigger")
    if tier == "tier_1_required_pr" and "pull_request" not in triggers:
        violations.append("required PR workflow does not listen to pull_request")
    if tier == "tier_1_required_pr" and hardcoded_run_ids:
        violations.append("required PR workflow contains a hard-coded cross-run artifact ID")
    if tier == "tier_3_research_evidence" and "pull_request" in triggers and not pr_paths:
        violations.append("research/evidence workflow listens to every PR without path filtering")

    warnings: list[str] = []
    if any(action.endswith("@v4") for action in actions):
        warnings.append("uses an action major that should be modernized when the workflow is next edited")
    if "20" in node_versions:
        warnings.append("declares Node.js 20; migrate to Node.js 24")

    record = {
        "path": path.as_posix(),
        "name": name,
        "tier": tier,
        "tier_rationale": rationale,
        "blocking_policy": {
            "tier_1_required_pr": "blocking on relevant pull requests",
            "tier_2_main_release": "blocking on main integration or release",
            "tier_3_research_evidence": "path-scoped, scheduled, or manual evidence",
            "tier_4_advisory": "non-blocking diagnostic unless promoted by explicit policy",
        }[tier],
        "triggers": trigger_data,
        "pull_request_path_scoped": bool(pr_paths),
        "artifacts": artifact_names(payload),
        "actions": actions,
        "node_versions": node_versions,
        "hardcoded_cross_run_ids": hardcoded_run_ids,
        "warnings": warnings,
        "violations": violations,
    }
    return record, violations


def build_inventory() -> tuple[dict[str, Any], list[str]]:
    workflow_paths = sorted((*WORKFLOW_ROOT.glob("*.yml"), *WORKFLOW_ROOT.glob("*.yaml")))
    if not workflow_paths:
        raise ValueError("no GitHub Actions workflows found")

    records: list[dict[str, Any]] = []
    violations: list[str] = []
    counts: dict[str, int] = {}
    for path in workflow_paths:
        record, record_violations = inspect_workflow(path)
        records.append(record)
        counts[record["tier"]] = counts.get(record["tier"], 0) + 1
        violations.extend(f"{path}: {message}" for message in record_violations)

    inventory = {
        "schema_version": "1.0.0",
        "policy": "four_tier_ci_governance",
        "workflow_count": len(records),
        "tier_counts": dict(sorted(counts.items())),
        "violation_count": len(violations),
        "workflows": records,
    }
    return inventory, violations


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory and enforce Alpha Engine CI governance")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--enforce", action="store_true")
    args = parser.parse_args()

    inventory, violations = build_inventory()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"Inventoried {inventory['workflow_count']} workflows across "
        f"{len(inventory['tier_counts'])} governance tiers; violations={len(violations)}"
    )
    for violation in violations:
        print(f"CI GOVERNANCE VIOLATION: {violation}")
    if args.enforce and violations:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
