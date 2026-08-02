from __future__ import annotations

import fnmatch
import json
import re
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = PROJECT_ROOT / "docs" / "architecture" / "legacy_web_inventory.json"
SCANNED_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".cjs", ".mjs", ".toml", ".yml", ".yaml"}
SCANNED_NAMES = {"Dockerfile", "Makefile"}
VALID_RETIREMENT_STATUSES = {
    "deprecated_frozen",
    "phase_1_frontend_cutover",
    "phase_2_domain_extraction",
    "phase_3_server_deletion",
    "phase_4_repository_normalization",
    "completed",
}

IMPORT_MARKER = re.compile(
    r"(?m)^\s*(?:from\s+(?:fastapi|uvicorn|slowapi)\b|import\s+(?:fastapi|uvicorn|slowapi)\b)"
)
TEXT_MARKERS = ("connected_research", "api_server.py")


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def load_patterns() -> list[str]:
    payload = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    status = payload.get("status")
    if status not in VALID_RETIREMENT_STATUSES:
        raise RuntimeError(
            "legacy Web inventory must declare a recognized retirement phase; "
            f"received {status!r}"
        )
    if payload.get("rules", {}).get("allow_new_http_endpoints") is not False:
        raise RuntimeError("legacy Web inventory must prohibit new HTTP endpoints")
    if payload.get("rules", {}).get("allow_new_frontend_api_calls") is not False:
        raise RuntimeError("legacy Web inventory must prohibit new frontend API calls")

    patterns: list[str] = []
    for zone in payload.get("legacy_zones", []):
        patterns.extend(str(path) for path in zone.get("paths", []))
    return patterns


def matches_pattern(path: str, pattern: str) -> bool:
    if pattern.endswith("/"):
        return path.startswith(pattern)
    if any(token in pattern for token in "*?["):
        return fnmatch.fnmatch(path, pattern)
    return path == pattern


def is_legacy_allowed(path: str, patterns: list[str]) -> bool:
    if path == "scripts/check_legacy_web_boundary.py":
        return True
    return any(matches_pattern(path, pattern) for pattern in patterns)


def contains_marker(path: Path, content: str) -> list[str]:
    markers: list[str] = []
    if path.suffix == ".py" and IMPORT_MARKER.search(content):
        markers.append("server-framework import")
    markers.extend(marker for marker in TEXT_MARKERS if marker in content)
    return markers


def main() -> int:
    patterns = load_patterns()
    violations: list[tuple[str, list[str]]] = []
    observed: list[tuple[str, list[str]]] = []

    for relative in tracked_files():
        path = PROJECT_ROOT / relative
        if not path.is_file():
            continue
        if path.suffix not in SCANNED_SUFFIXES and path.name not in SCANNED_NAMES:
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        markers = contains_marker(path, content)
        if not markers:
            continue

        observed.append((relative, markers))
        if not is_legacy_allowed(relative, patterns):
            violations.append((relative, markers))

    print(f"Observed legacy Web markers in {len(observed)} tracked files.")
    for relative, markers in observed:
        print(f"  - {relative}: {', '.join(markers)}")

    if violations:
        print("\nERROR: new legacy Web dependency detected outside the retirement inventory:")
        for relative, markers in violations:
            print(f"  - {relative}: {', '.join(markers)}")
        print(
            "\nMove reusable behavior to a pure Python service/CLI or artifact contract. "
            "Only expand the inventory when the change demonstrably reduces a migration blocker."
        )
        return 1

    print("Legacy Web boundary remains controlled; no unapproved dependency expansion detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
