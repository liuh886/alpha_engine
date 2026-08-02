#!/usr/bin/env python3
"""Locate repository evidence for the two user-designated XGBoost baselines."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, TypedDict


class Baseline(TypedDict):
    reported_value: float
    tokens: tuple[str, ...]
    benchmark: str


BASELINES: dict[str, Baseline] = {
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
    ".github/workflows/xgb-dual-market-improvement.yml",
    "configs/research_paradigms/xgb_dual_market_improvement_v1.yaml",
    "docs/research/xgb_dual_market_improvement_plan_2026-08-02.md",
    "scripts/audit_xgb_baseline_provenance.py",
    "tests/test_xgb_dual_market_improvement_contract.py",
}
HISTORY_SKIP_PREFIXES = (
    ".playwright-cli/",
    "data/",
    "tests/",
)
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
    classification: str


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )


def _history_ref(repo_root: Path) -> str:
    for candidate in ("origin/main", "main", "HEAD"):
        result = _run_git(repo_root, "rev-parse", "--verify", candidate)
        if result.returncode == 0:
            return candidate
    return "HEAD"


def _classify_candidate(excerpt: str) -> str:
    lowered = excerpt.lower()
    if "icir" in lowered or "ic ir" in lowered:
        return "metric_mismatch_icir"
    if "relative excess" in lowered or "compounded_relative_excess" in lowered:
        return "economic_metric_candidate"
    if "复合超额" in excerpt:
        return "economic_metric_candidate"
    if "超额收益" in excerpt:
        return "ambiguous_excess_context"
    if "qqq" in lowered or "csi300" in lowered or "csi 300" in lowered:
        return "benchmark_context_candidate"
    return "numeric_collision"


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
                        excerpt = line.strip()[:500]
                        hits.append(
                            Hit(
                                market=market,
                                token=token,
                                source="worktree",
                                path=relative,
                                line=line_number,
                                commit=None,
                                excerpt=excerpt,
                                classification=_classify_candidate(excerpt),
                            )
                        )
    return hits


def _candidate_commits(repo_root: Path, token: str) -> list[str]:
    result = _run_git(
        repo_root,
        "log",
        _history_ref(repo_root),
        f"-S{token}",
        "--format=%H",
        "--no-merges",
    )
    if result.returncode != 0:
        return []
    return list(dict.fromkeys(line.strip() for line in result.stdout.splitlines() if line.strip()))


def _skip_history_path(path: str) -> bool:
    return path in DECLARATION_PATHS or path.startswith(HISTORY_SKIP_PREFIXES)


def scan_history(repo_root: Path) -> list[Hit]:
    hits: list[Hit] = []
    seen: set[tuple[str, str, str, str]] = set()
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
                    if token not in line or _skip_history_path(current_path):
                        continue
                    key = (market, token, commit, current_path)
                    if key in seen:
                        continue
                    seen.add(key)
                    excerpt = line.strip()[:500]
                    hits.append(
                        Hit(
                            market=market,
                            token=token,
                            source="git_history",
                            path=current_path or "<unknown>",
                            line=None,
                            commit=commit,
                            excerpt=excerpt,
                            classification=_classify_candidate(excerpt),
                        )
                    )
    return hits


def build_report(repo_root: Path) -> dict[str, object]:
    all_hits = scan_worktree(repo_root) + scan_history(repo_root)

    markets: dict[str, object] = {}
    for market, baseline in BASELINES.items():
        selected = [hit for hit in all_hits if hit.market == market]
        classifications = Counter(hit.classification for hit in selected)
        meaningful = [
            hit
            for hit in selected
            if hit.classification not in {"numeric_collision", "metric_mismatch_icir"}
        ]
        markets[market] = {
            "reported_value": baseline["reported_value"],
            "benchmark": baseline["benchmark"],
            "status": "meaningful_candidates_found" if meaningful else "provenance_unresolved",
            "candidate_count": len(selected),
            "meaningful_candidate_count": len(meaningful),
            "classification_counts": dict(sorted(classifications.items())),
            "candidates": [asdict(hit) for hit in selected],
        }

    return {
        "schema_version": "1.1",
        "status": "baseline_provenance_audit_completed",
        "history_ref": _history_ref(repo_root),
        "repo_root": str(repo_root),
        "markets": markets,
        "interpretation": (
            "A token match is only a provenance candidate. Baseline verification requires "
            "an experiment manifest, provider identity, exact configuration and economic outputs. "
            "ICIR and raw market-data numeric collisions are not excess-return evidence."
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
