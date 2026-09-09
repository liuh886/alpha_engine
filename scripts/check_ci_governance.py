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

RESEARCH_PARADIGM_ROOT = Path("configs/research_paradigms")
RESEARCH_EXPERIMENT_ROOT = Path("configs/research_experiments")
ARCHIVE_MARKER = "research_paradigms/archive"
# Directories whose mentions prove history, not life: docs and the archive
# itself never count as references for liveness purposes.
NON_LIVE_REFERENCE_ROOTS = ("docs/", "artifacts/evidence/", "configs/research_paradigms/archive/")

# File suffixes scanned for stem references. Notebooks and snapshots are
# deliberately excluded: they are frozen evidence, not live callers.
REFERENCE_SUFFIXES = (".py", ".yml", ".yaml", ".json")


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

    research_assets = inspect_research_assets(Path("."))
    violations.extend(archive_reference_violations(Path(".")))

    inventory = {
        "schema_version": "1.0.0",
        "policy": "four_tier_ci_governance",
        "workflow_count": len(records),
        "tier_counts": dict(sorted(counts.items())),
        "violation_count": len(violations),
        "workflows": records,
        "research_assets": research_assets,
    }
    return inventory, violations


# Live-caller roots: the only places that can keep a paradigm alive.
# data/, artifacts/, .venv and other bulk trees are history or tooling,
# never callers.
LIVE_SCAN_ROOTS = (".github/workflows", "src", "scripts", "tests", "configs")
# Evidence trees: a mention here proves past life (sealed receipts/ledgers),
# never current feeding.
EVIDENCE_SCAN_ROOTS = ("data/research",)
# The guard implementation itself names the archive it protects.
ARCHIVE_GUARD_EXEMPT = {"scripts/check_ci_governance.py"}


def _live_text_files(repo_root: Path) -> list[Path]:
    """Collect scannable live-caller files, excluding history-only roots."""
    files: list[Path] = []
    for root in LIVE_SCAN_ROOTS:
        scan_root = repo_root / root
        if not scan_root.is_dir():
            continue
        for suffix in REFERENCE_SUFFIXES:
            for path in scan_root.rglob(f"*{suffix}"):
                relative = path.relative_to(repo_root).as_posix()
                if relative.startswith(NON_LIVE_REFERENCE_ROOTS):
                    continue
                if "/archive/" in relative:
                    continue
                files.append(path)
    return files


def _paradigm_stems(repo_root: Path) -> list[str]:
    paradigm_root = repo_root / RESEARCH_PARADIGM_ROOT
    if not paradigm_root.is_dir():
        return []
    return sorted(
        path.stem
        for path in paradigm_root.glob("*.yaml")
        if path.is_file()
    )


def inspect_research_assets(repo_root: Path) -> dict[str, Any]:
    """Build the paradigm reference graph and derive lifecycle states.

    Lifecycle is derived, never declared: scheduled (a workflow names the
    stem), referenced_only (code/config names it but no workflow feeds it),
    orphan_candidate (no live caller at all). Advisory only: the caller
    prints suggestions but never fails the build.
    """
    stems = _paradigm_stems(repo_root)
    code_texts: dict[str, str] = {}
    for path in _live_text_files(repo_root):
        try:
            if path.suffix == ".json":
                continue
            code_texts[path.relative_to(repo_root).as_posix()] = path.read_text(
                encoding="utf-8"
            )
        except (OSError, UnicodeDecodeError):
            continue
    evidence_texts: dict[str, str] = {}
    for root in EVIDENCE_SCAN_ROOTS:
        scan_root = repo_root / root
        if not scan_root.is_dir():
            continue
        for path in scan_root.rglob("*.json"):
            try:
                evidence_texts[path.relative_to(repo_root).as_posix()] = path.read_text(
                    encoding="utf-8"
                )
            except (OSError, UnicodeDecodeError):
                continue
    workflow_texts = {
        name: body
        for name, body in code_texts.items()
        if name.startswith(".github/workflows/")
    }
    lifecycles: dict[str, str] = {}
    paradigm_prefix = f"{RESEARCH_PARADIGM_ROOT.as_posix()}/"
    for stem in stems:
        own_file = f"{paradigm_prefix}{stem}.yaml"
        scheduled = any(
            stem in body for name, body in workflow_texts.items() if name != own_file
        )
        if scheduled:
            lifecycles[stem] = "scheduled"
            continue
        # Paradigm-to-paradigm mentions (supersedes/bridges lineage notes) do
        # not feed anything: only callers outside the paradigm directory
        # confer referenced_only life.
        referenced = any(
            stem in body
            for name, body in code_texts.items()
            if name != own_file and not name.startswith(paradigm_prefix)
        )
        if referenced:
            lifecycles[stem] = "referenced_only"
            continue
        evidenced = any(
            stem in body for name, body in evidence_texts.items() if name != own_file
        )
        lifecycles[stem] = "evidence_only" if evidenced else "orphan_candidate"
    experiment_root = repo_root / RESEARCH_EXPERIMENT_ROOT
    experiment_count = (
        len(list(experiment_root.glob("*.yaml"))) if experiment_root.is_dir() else 0
    )
    orphans = sorted(stem for stem, state in lifecycles.items() if state == "orphan_candidate")
    referenced_only = sorted(
        stem for stem, state in lifecycles.items() if state == "referenced_only"
    )
    evidence_only = sorted(
        stem for stem, state in lifecycles.items() if state == "evidence_only"
    )
    return {
        "paradigm_count": len(stems),
        "experiment_count": experiment_count,
        "scheduled_count": sum(1 for state in lifecycles.values() if state == "scheduled"),
        "referenced_only": referenced_only,
        "evidence_only": evidence_only,
        "orphan_candidates": orphans,
        "lifecycles": lifecycles,
        "archive_suggestion": (
            "consider archiving orphan candidates to "
            "configs/research_paradigms/archive/ with provenance"
            if orphans
            else None
        ),
    }


def archive_reference_violations(repo_root: Path) -> list[str]:
    """Fail closed on new callers of the paradigm archive.

    The archive is write-once history: live code must never import, schedule
    or reference it. These are blocking violations, unlike zombie warnings.
    """
    violations: list[str] = []
    for path in _live_text_files(repo_root):
        relative = path.relative_to(repo_root).as_posix()
        if relative in ARCHIVE_GUARD_EXEMPT:
            continue
        try:
            body = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if ARCHIVE_MARKER in body:
            violations.append(
                f"{relative}: live file references the paradigm archive"
            )
    return violations


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
    research = inventory.get("research_assets", {})
    orphans = research.get("orphan_candidates", [])
    if orphans:
        print(
            f"CI GOVERNANCE ADVISORY: {len(orphans)} paradigm orphan candidates "
            f"(no live caller): {', '.join(orphans[:10])}"
            + ("..." if len(orphans) > 10 else "")
        )
        if research.get("archive_suggestion"):
            print(f"CI GOVERNANCE ADVISORY: {research['archive_suggestion']}")
    if args.enforce and violations:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
