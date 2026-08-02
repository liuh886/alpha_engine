from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = PROJECT_ROOT / "docs" / "architecture" / "legacy_web_inventory.json"
SCANNED_SUFFIXES = {
    ".py",
    ".pyw",
    ".ts",
    ".tsx",
    ".js",
    ".cjs",
    ".mjs",
    ".toml",
    ".yml",
    ".yaml",
    ".json",
    ".md",
    ".sh",
}
SCANNED_NAMES = {"Dockerfile", "Makefile", ".env.example"}
POLICY_FILES = {
    "scripts/check_legacy_web_boundary.py",
    "docs/architecture/legacy_web_inventory.json",
    "docs/architecture/legacy_web_retirement.md",
}
SERVER_IMPORT = re.compile(
    r"(?m)^\s*(?:from\s+(?:fastapi|uvicorn|slowapi)\b|import\s+(?:fastapi|uvicorn|slowapi)\b)"
)
DIRECT_SERVER_DEPENDENCY = re.compile(
    r'(?m)^\s*"(?:fastapi|uvicorn|slowapi)(?:[<>=!~].*)?",?\s*$'
)


def tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def load_policy() -> tuple[str, ...]:
    payload = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    if payload.get("status") != "completed":
        raise RuntimeError("legacy Web inventory must be in completed state")
    if payload.get("legacy_zones"):
        raise RuntimeError("completed legacy Web inventory must contain no active legacy zones")

    rules = payload.get("rules", {})
    required_false = (
        "allow_new_http_endpoints",
        "allow_new_frontend_api_calls",
        "allow_browser_mutations",
        "allow_domain_logic_only_in_router",
        "allow_active_legacy_zones",
    )
    for rule in required_false:
        if rules.get(rule) is not False:
            raise RuntimeError(f"legacy Web inventory must set {rule}=false")

    markers = tuple(str(item) for item in payload.get("prohibited_markers", []))
    if not markers:
        raise RuntimeError("completed legacy Web inventory must declare prohibited markers")
    return markers


def scan_file(relative: str, content: str, prohibited: tuple[str, ...]) -> list[str]:
    markers: list[str] = []
    path = Path(relative)
    if path.suffix == ".py" and SERVER_IMPORT.search(content):
        markers.append("server-framework import")
    if relative == "pyproject.toml" and DIRECT_SERVER_DEPENDENCY.search(content):
        markers.append("direct server dependency")
    markers.extend(marker for marker in prohibited if marker in content)
    return markers


def main() -> int:
    prohibited = load_policy()
    violations: list[tuple[str, list[str]]] = []

    for relative in tracked_files():
        if relative in POLICY_FILES:
            continue
        path = PROJECT_ROOT / relative
        if not path.is_file():
            continue
        if path.suffix not in SCANNED_SUFFIXES and path.name not in SCANNED_NAMES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        markers = scan_file(relative, content, prohibited)
        if markers:
            violations.append((relative, markers))

    if violations:
        print("ERROR: retired Web architecture markers remain:")
        for relative, markers in violations:
            print(f"  - {relative}: {', '.join(markers)}")
        print(
            "\nRemove the server/runtime reference. Browser reads belong in the research "
            "bundle; execution belongs in Python CLI, scripts or workflows."
        )
        return 1

    print("Legacy Web retirement is complete: no active server architecture markers found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
