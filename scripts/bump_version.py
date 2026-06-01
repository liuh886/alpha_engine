"""Bump version in pyproject.toml and optionally create git tag.

Usage:
    python scripts/bump_version.py patch    # 2.5.0 -> 2.5.1
    python scripts/bump_version.py minor    # 2.5.0 -> 2.6.0
    python scripts/bump_version.py major    # 2.5.0 -> 3.0.0
    python scripts/bump_version.py 3.1.0    # Set explicit version
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


def _read_version(pyproject: Path) -> str:
    content = pyproject.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', content, re.MULTILINE)
    if not match:
        print("Error: could not find version in pyproject.toml", file=sys.stderr)
        sys.exit(1)
    return match.group(1)


def _write_version(pyproject: Path, old: str, new: str) -> None:
    content = pyproject.read_text(encoding="utf-8")
    content = content.replace(f'version = "{old}"', f'version = "{new}"', 1)
    pyproject.write_text(content, encoding="utf-8")


def bump_version(current: str, bump: str) -> str:
    """Compute the new version string."""
    major, minor, patch = (int(x) for x in current.split("."))

    if bump == "patch":
        patch += 1
    elif bump == "minor":
        minor += 1
        patch = 0
    elif bump == "major":
        major += 1
        minor = 0
        patch = 0
    else:
        # Explicit version
        parts = bump.split(".")
        if len(parts) != 3 or not all(p.isdigit() for p in parts):
            print(f"Error: invalid version '{bump}'. Use major/minor/patch or x.y.z", file=sys.stderr)
            sys.exit(1)
        major, minor, patch = (int(x) for x in parts)

    return f"{major}.{minor}.{patch}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Bump project version in pyproject.toml")
    parser.add_argument(
        "bump",
        help="Version bump type (major/minor/patch) or explicit version (x.y.z)",
    )
    parser.add_argument(
        "--tag",
        action="store_true",
        default=False,
        help="Create a git tag v{version} after bumping",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Print the new version without writing",
    )
    args = parser.parse_args()

    pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
    if not pyproject.exists():
        print(f"Error: {pyproject} not found", file=sys.stderr)
        sys.exit(1)

    current = _read_version(pyproject)
    new = bump_version(current, args.bump)

    if args.dry_run:
        print(f"{current} -> {new}")
        return

    _write_version(pyproject, current, new)
    print(f"Version bumped: {current} -> {new}")

    if args.tag:
        tag = f"v{new}"
        try:
            subprocess.run(["git", "tag", tag], check=True, capture_output=True, text=True)
            print(f"Git tag created: {tag}")
        except subprocess.CalledProcessError as exc:
            print(f"Error creating git tag: {exc.stderr}", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    main()
