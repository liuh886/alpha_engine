from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

import yaml

WORKFLOW_ROOT = Path('.github/workflows')
LOCKFILES = {
    'npm': ('package-lock.json',),
    'pnpm': ('pnpm-lock.yaml',),
    'yarn': ('yarn.lock',),
    'bun': ('bun.lock', 'bun.lockb'),
}
RUN_ID_RE = re.compile(r'\brun-id\s*:\s*["\']?\d{6,}')
RETENTION_RE = re.compile(r'retention-days:\s*(\d+)')
LEGACY_ACTION_PREFIXES = (
    'actions/checkout@v4',
    'actions/setup-node@v4',
    'actions/setup-python@v5',
)


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value, dict):
        raise ValueError(f'{path} must contain a JSON object')
    return value


def has_event(text: str, event: str) -> bool:
    return bool(re.search(rf'^\s{{2}}{re.escape(event)}\s*:', text, re.MULTILINE))


def top_permissions(text: str) -> dict[str, str]:
    lines = text.splitlines()
    result: dict[str, str] = {}
    for index, line in enumerate(lines):
        if line == 'permissions:':
            for child in lines[index + 1:]:
                if child and not child.startswith(' '):
                    break
                match = re.match(r'^\s{2}([\w-]+):\s*(\w+)', child)
                if match:
                    result[match.group(1)] = match.group(2)
            break
    return result


def upload_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    blocks: list[str] = []
    for index, line in enumerate(lines):
        if 'actions/upload-artifact@' in line:
            blocks.append('\n'.join(lines[index:index + 18]))
    return blocks


def iter_uses(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == 'uses' and isinstance(child, str):
                yield child
            yield from iter_uses(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_uses(child)


def action_refs(text: str, seen: set[Path] | None = None) -> set[str]:
    """Return external actions, including actions used by local composite actions."""
    uses = tuple(iter_uses(yaml.safe_load(text)))
    refs = {ref for ref in uses if not ref.startswith('./') and '@' in ref}
    visited = set() if seen is None else seen
    for local_ref in (ref for ref in uses if ref.startswith('./.github/actions/')):
        action_root = Path(local_ref.removeprefix('./'))
        candidates = (action_root / 'action.yml', action_root / 'action.yaml')
        action_path = next((path for path in candidates if path.is_file()), None)
        if action_path is None or action_path in visited:
            continue
        visited.add(action_path)
        refs.update(action_refs(action_path.read_text(encoding='utf-8'), visited))
    return refs


def inspect_workflow(
    path: Path,
    governed: bool,
    required_pr: bool,
    modern_runtime_required: bool,
    max_days: int,
) -> tuple[dict[str, Any], list[str]]:
    text = path.read_text(encoding='utf-8')
    actions = sorted(action_refs(text))
    events = [event for event in ('pull_request', 'push', 'workflow_run', 'workflow_dispatch', 'schedule') if has_event(text, event)]
    permissions = top_permissions(text)
    violations: list[str] = []
    warnings: list[str] = []

    if governed:
        if not re.search(r'^name:\s*\S', text, re.MULTILINE):
            violations.append('missing workflow name')
        if 'permissions:' not in text:
            violations.append('missing explicit permissions')
        if any(event in events for event in ('pull_request', 'push')) and 'concurrency:' not in text:
            violations.append('PR/push workflow lacks concurrency control')
        if 'pull_request' in events and any(value == 'write' for value in permissions.values()):
            violations.append('pull-request workflow grants top-level write authority')
        if required_pr and RUN_ID_RE.search(text):
            violations.append('required PR workflow contains a hard-coded cross-run ID')
        for block in upload_blocks(text):
            match = RETENTION_RE.search(block)
            if not match:
                violations.append('upload-artifact step lacks retention-days')
            elif int(match.group(1)) > max_days:
                violations.append(f'upload-artifact retention exceeds {max_days} days')

    legacy_actions = [action for action in actions if action.startswith(LEGACY_ACTION_PREFIXES)]
    for action in legacy_actions:
        warnings.append(f'legacy action runtime: {action}')
    if modern_runtime_required:
        violations.extend(f'critical workflow uses legacy action runtime: {action}' for action in legacy_actions)

    return {
        'path': path.as_posix(),
        'governed': governed,
        'required_pr': required_pr,
        'modern_runtime_required': modern_runtime_required,
        'events': events,
        'permissions': permissions,
        'actions': actions,
        'warnings': warnings,
        'violations': violations,
    }, violations


def validate_lockfile(policy: dict[str, Any]) -> list[str]:
    violations: list[str] = []
    manager = str(policy.get('package_manager', 'none'))
    package_exists = Path('package.json').exists()
    present = [item for values in LOCKFILES.values() for item in values if Path(item).exists()]
    if manager == 'none':
        if package_exists or present:
            violations.append('package_manager is none but JavaScript package files exist')
        return violations
    if manager not in LOCKFILES:
        return [f'unsupported package_manager: {manager}']
    if not package_exists:
        violations.append('package manager declared but package.json is missing')
    expected = [item for item in LOCKFILES[manager] if Path(item).exists()]
    if len(expected) != 1:
        violations.append(f'{manager} requires exactly one recognized lockfile')
    foreign = [item for item in present if item not in LOCKFILES[manager]]
    if foreign:
        violations.append(f'foreign package-manager lockfiles present: {foreign}')
    return violations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--policy', type=Path, default=Path('.github/ci-policy.json'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--enforce', action='store_true')
    args = parser.parse_args()

    policy = read_json(args.policy)
    governed = set(policy.get('governed_workflows', []))
    required_pr = set(policy.get('required_pr_workflows', []))
    release = set(policy.get('release_workflows', []))
    declared = governed | required_pr | release | set(policy.get('advisory_workflows', []))
    critical_runtime = governed | required_pr | release
    violations: list[str] = []

    for rel in sorted(declared):
        if not Path(rel).is_file():
            violations.append(f'declared workflow is missing: {rel}')

    retention = policy.get('artifact_retention_days', {})
    pr_days = int(retention.get('pr_diagnostics', 14))
    build_days = int(retention.get('deployable_build', 7))
    durable_days = int(retention.get('durable_evidence', 90))
    if not (1 <= pr_days <= 14 and 1 <= build_days <= 7 and 1 <= durable_days <= 90):
        violations.append('artifact retention classes exceed portfolio limits')

    audit = policy.get('dependency_audit', {})
    if audit.get('production_high_critical') != 'blocking':
        violations.append('production High/Critical dependency risk must be blocking')
    if audit.get('development_tooling') != 'advisory':
        violations.append('development/tooling dependency risk must be advisory')

    violations.extend(validate_lockfile(policy))
    exceptions = {str(key): int(value) for key, value in policy.get('retention_exceptions', {}).items()}
    records = []
    for path in sorted((*WORKFLOW_ROOT.glob('*.yml'), *WORKFLOW_ROOT.glob('*.yaml'))):
        rel = path.as_posix()
        max_days = exceptions.get(rel, pr_days if rel in required_pr else max(build_days, pr_days))
        record, found = inspect_workflow(
            path,
            rel in governed,
            rel in required_pr,
            rel in critical_runtime,
            max_days,
        )
        records.append(record)
        violations.extend(f'{rel}: {message}' for message in found)

    workflow_count_budget = int(policy.get('workflow_count_budget', len(records)))
    if workflow_count_budget < 1:
        violations.append('workflow_count_budget must be positive')
    elif len(records) > workflow_count_budget:
        violations.append(
            f'workflow count {len(records)} exceeds budget {workflow_count_budget}; '
            'retire or consolidate an existing workflow before adding another permanent entrypoint'
        )

    report = {
        'schema_version': '1.0.0',
        'repository': policy.get('repository'),
        'default_branch': policy.get('default_branch'),
        'workflow_count': len(records),
        'workflow_count_budget': workflow_count_budget,
        'governed_workflow_count': len(governed),
        'violations': violations,
        'workflows': records,
        'branch_protection': policy.get('branch_protection', {}),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(
        f'CI policy: workflows={len(records)} budget={workflow_count_budget} '
        f'governed={len(governed)} violations={len(violations)}'
    )
    for violation in violations:
        print(f'CI POLICY VIOLATION: {violation}')
    return 1 if args.enforce and violations else 0


if __name__ == '__main__':
    raise SystemExit(main())
