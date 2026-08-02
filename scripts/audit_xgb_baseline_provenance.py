#!/usr/bin/env python3
"""Locate repository evidence for the two user-designated XGBoost baselines."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

BASELINES = {
    "us": {
        "reported_value": 0.8143,
        "tokens": ("81.43%", "81.43", "0.8143"),
        "benchmark": "QQQ",
    },
    "cn": {
        "reported_value": 0.2018,
        "tokens": ("20.18%", "20.18", "0.2018"),
        "benchmark": "CSI300",
    },
}

TEXT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".md",
    ".txt",
    ".yaml",
    ".yml",
}
SKIP_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "data",
    "dist",
    "node_modules",
}
DECLARATION_PATHS = {
    "configs/research_paradigms/xgb_dual_market_improvement_v1.yaml",
    "docs/research/xgb_dual_market_improvement_plan_2026-08-02.md",
}
MAX_TEXT_BYTES = 5_000_000


@dataclass(frozen=True)
class Hit:
    market: str
    token: str
    source: str
    path: str
    line: int | None
    commit: str | None
    excerpt: str


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )


def _iter_text_files(repo_root: Path) -> Iterable[Path]:
    for path in repo_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        relative = path.relative_to(repo_root)
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        if relative.as_posix() in DECLARATION_PATHS:
            continue
        try:
            if path.stat().st_size > MAX_TEXT_BYTES:
                continue
        except OSError:
            continue
        yield path


def scan_worktree(repo_root: Path) -> list[Hit]:
    hits: list[Hit] = []
    for path in _iter_text_files(repo_root):
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        relative = path.relative_to(repo_root).as_posix()
        for line_number, line in enumerate(lines, start=1):
            for market, baseline in BASELINES.items():
                for token in baseline["tokens"]:
                    if token in line:
                        hits.append(
                            Hit(
                                market=market,
                                token=token,
                                source="worktree",
                                path=relative,
                                line=line_number,
                                commit=None,
                                excerpt=line.strip()[:500],
                            )
                        )
    return hits


def _candidate_commits(repo_root: Path, token: str) -> list[str]:
    result = _run_git(
        repo_root,
        "log",
        "--all",
        f"-S{token}",
        "--format=%H",
        "--no-merges",
    )
    if result.returncode != 0:
        return []
    return list(dict.fromkeys(line.strip() for line in result.stdout.splitlines() if line.strip()))


def scan_history(repo_root: Path) -> list[Hit]:
    hits: list[Hit] = []
    seen: set[tuple[str, str, str]] = set()
    for market, baseline in BASELINES.items():
        for token in baseline["tokens"]:
            for commit in _candidate_commits(repo_root, token):
                diff = _run_git(repo_root, "show", "--format=", "--unified=0", commit)
                if diff.returncode != 0:
                    continue
                current_path = ""
                for line in diff.stdout.splitlines():
                    if line.startswith("+++ b/"):
                        current_path = line[6:]
                        continue
                    if token not in line or current_path in DECLARATION_PATHS:
                        continue
                    key = (market, token, commit)
                    if key in seen:
                        continue
                    seen.add(key)
                    hits.append(
                        Hit(
                            market=market,
                            token=token,
                            source="git_history",
                            path=current_path or "<unknown>",
                            line=None,
                            commit=commit,
                            excerpt=line.strip()[:500],
                        )
                    )
    return hits


def build_report(repo_root: Path) -> dict[str, object]:
    worktree_hits = scan_worktree(repo_root)
    history_hits = scan_history(repo_root)
    all_hits = worktree_hits + history_hits

    markets: dict[str, object] = {}
    for market, baseline in BASELINES.items():
        market_hits = [asdict(hit) for hit in all_hits if hit.market == market]
        markets[market] = {
            "reported_value": baseline["reported_value"],
            "benchmark": baseline["benchmark"],
            "status": "provenance_candidates_found" if market_hits else "provenance_unresolved",
            "candidate_count": len(market_hits),
            "candidates": market_hits,
        }

    return {
        "schema_version": "1.0",
        "status": "baseline_provenance_audit_completed",
        "repo_root": str(repo_root),
        "markets": markets,
        "interpretation": (
            "A token match is only a provenance candidate. Baseline verification requires "
            "an experiment manifest, provider identity, exact configuration and economic outputs."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/evidence/xgb_baseline_provenance_report.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()
    report = build_report(repo_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
