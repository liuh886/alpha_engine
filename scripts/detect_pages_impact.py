from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable

DEFAULT_CATALOG = Path("data/research/catalog.json")
ZERO_SHA = "0" * 40

DIRECT_EXACT_PATHS = {
    ".github/workflows/deploy-pages.yml",
    ".github/workflows/pages-release-receipt.yml",
    "data/research/catalog.json",
    "docs/architecture/legacy_web_inventory.json",
    "docs/contracts/alpha-engine-bundle.schema.json",
    "docs/methodology.md",
    "scripts/check_legacy_web_boundary.py",
    "scripts/check_repository_model_runs.py",
    "scripts/detect_pages_impact.py",
    "scripts/export_research_bundle.py",
    "scripts/export_static_site_data.py",
    "scripts/verify_pages_release.py",
    "src/artifacts/model_run_bundle_v2.py",
    "src/artifacts/model_run_decision.py",
    "src/artifacts/model_run_exporter.py",
    "src/artifacts/pages_release_verification.py",
    "src/artifacts/repository_research_store.py",
    "src/artifacts/research_bundle.py",
}
DIRECT_PREFIXES = (
    "data/research/formal_model_runs/",
    "data/research/market_evidence/",
    "data/research/model_data_bundle_v1/",
    "data/research/model_runs/",
    "data/research/model_decisions/",
    "data/research/strategy_operations/",
    "data/research/strategy_signal_ledgers/",
    "qlib-dashboard/",
)
RESULT_REPORT_PATTERN = re.compile(r"^\s*result_report\s*:\s*(?P<value>.+?)\s*$")


class PagesImpactError(ValueError):
    """Raised when the publication dependency graph cannot be resolved safely."""


@dataclass(frozen=True)
class ImpactDecision:
    schema_version: str
    deploy: bool
    reason: str
    changed_paths: tuple[str, ...]
    matched_paths: tuple[str, ...]
    dependency_paths: tuple[str, ...]
    dependency_prefixes: tuple[str, ...]
    fail_closed_detail: str | None = None


def _safe_repo_path(value: str) -> str:
    normalized = value.replace("\\", "/").strip()
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise PagesImpactError(f"unsafe repository path: {value!r}")
    return path.as_posix()


def _read_json_object(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PagesImpactError(f"unable to read publication catalog: {path}") from exc
    if not isinstance(payload, dict):
        raise PagesImpactError(f"publication catalog root must be an object: {path}")
    return payload


def _extract_result_reports(model_path: Path) -> set[str]:
    try:
        lines = model_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise PagesImpactError(f"unable to read published model source: {model_path}") from exc

    reports: set[str] = set()
    for line in lines:
        match = RESULT_REPORT_PATTERN.match(line)
        if not match:
            continue
        raw = match.group("value").split(" #", 1)[0].strip()
        if raw in {"", "null", "~"}:
            continue
        if raw.startswith(("'", '"')) and raw.endswith(raw[0]) and len(raw) >= 2:
            raw = raw[1:-1]
        if any(token in raw for token in ("${", "[", "{", "|", ">")):
            raise PagesImpactError(
                f"unsupported result_report syntax in published model source: {model_path}"
            )
        reports.add(_safe_repo_path(raw))
    return reports


def resolve_publication_dependencies(
    repository_root: Path,
    *,
    catalog_path: Path = DEFAULT_CATALOG,
) -> tuple[set[str], set[str]]:
    catalog_file = repository_root / catalog_path
    catalog = _read_json_object(catalog_file)

    exact = set(DIRECT_EXACT_PATHS)
    prefixes = set(DIRECT_PREFIXES)

    models = catalog.get("published_models")
    runs = catalog.get("published_runs")
    if not isinstance(models, list) or not models:
        raise PagesImpactError("publication catalog must contain published_models")
    if not isinstance(runs, list):
        raise PagesImpactError("publication catalog published_runs must be a list")

    for entry in models:
        if not isinstance(entry, dict):
            raise PagesImpactError("published model entry must be an object")
        source = _safe_repo_path(str(entry.get("source") or ""))
        exact.add(source)
        model_path = repository_root / source
        if not model_path.is_file():
            raise PagesImpactError(f"published model source is missing: {source}")
        exact.update(_extract_result_reports(model_path))

    for entry in runs:
        if not isinstance(entry, dict):
            raise PagesImpactError("published run entry must be an object")
        source = _safe_repo_path(str(entry.get("source") or ""))
        prefixes.add(source.rstrip("/") + "/")

    return exact, prefixes


def _normalize_changed_paths(paths: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({_safe_repo_path(path) for path in paths if path.strip()}))


def decide_impact(
    changed_paths: Iterable[str],
    *,
    repository_root: Path,
    catalog_path: Path = DEFAULT_CATALOG,
    forced_reason: str | None = None,
) -> ImpactDecision:
    changed = _normalize_changed_paths(changed_paths)
    if forced_reason:
        return ImpactDecision(
            schema_version="1.0.0",
            deploy=True,
            reason=forced_reason,
            changed_paths=changed,
            matched_paths=changed,
            dependency_paths=(),
            dependency_prefixes=(),
        )

    try:
        exact, prefixes = resolve_publication_dependencies(
            repository_root, catalog_path=catalog_path
        )
    except PagesImpactError as exc:
        return ImpactDecision(
            schema_version="1.0.0",
            deploy=True,
            reason="fail_closed_dependency_resolution",
            changed_paths=changed,
            matched_paths=changed,
            dependency_paths=(),
            dependency_prefixes=(),
            fail_closed_detail=str(exc),
        )

    matched = sorted(
        path
        for path in changed
        if path in exact or any(path.startswith(prefix) for prefix in prefixes)
    )
    return ImpactDecision(
        schema_version="1.0.0",
        deploy=bool(matched),
        reason="publication_dependency_changed" if matched else "no_publication_impact",
        changed_paths=changed,
        matched_paths=tuple(matched),
        dependency_paths=tuple(sorted(exact)),
        dependency_prefixes=tuple(sorted(prefixes)),
    )


def git_changed_paths(repository_root: Path, before: str, after: str) -> tuple[str, ...]:
    if not before or not after or before == ZERO_SHA:
        raise PagesImpactError("commit range is unavailable")
    command = [
        "git",
        "-C",
        str(repository_root),
        "diff",
        "--name-only",
        "--diff-filter=ACDMRTUXB",
        before,
        after,
    ]
    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PagesImpactError(f"unable to inspect commit range {before}..{after}") from exc
    return _normalize_changed_paths(completed.stdout.splitlines())


def _write_github_output(path: Path, decision: ImpactDecision) -> None:
    payload = asdict(decision)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"deploy={'true' if decision.deploy else 'false'}\n")
        handle.write(f"reason={decision.reason}\n")
        handle.write(
            "matched_paths_json="
            + json.dumps(payload["matched_paths"], separators=(",", ":"))
            + "\n"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Decide whether a main-branch change affects the published Pages artifact."
    )
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--before", default="")
    parser.add_argument("--after", default="")
    parser.add_argument("--changed-file", action="append", default=[])
    parser.add_argument("--manual", action="store_true")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/pages-impact-decision.json"),
    )
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    repository_root = args.repository_root.resolve()
    forced_reason: str | None = "manual_dispatch" if args.manual else None
    changed_paths: tuple[str, ...]
    if args.changed_file:
        changed_paths = _normalize_changed_paths(args.changed_file)
    elif forced_reason:
        changed_paths = ()
    else:
        try:
            changed_paths = git_changed_paths(
                repository_root,
                before=args.before,
                after=args.after,
            )
        except PagesImpactError as exc:
            changed_paths = ()
            forced_reason = f"fail_closed_commit_range:{exc}"

    decision = decide_impact(
        changed_paths,
        repository_root=repository_root,
        catalog_path=args.catalog,
        forced_reason=forced_reason,
    )
    output = repository_root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(asdict(decision), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.github_output:
        _write_github_output(args.github_output, decision)
    print(json.dumps(asdict(decision), sort_keys=True))


if __name__ == "__main__":
    main()
