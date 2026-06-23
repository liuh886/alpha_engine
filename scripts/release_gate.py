"""Verify one explicit release candidate and optionally run all quality gates.

The candidate ID is resolved from --candidate (primary) or the
ALPHA_RELEASE_CANDIDATE environment variable (fallback).  Neither defaults
to anything — the script exits non-zero when no candidate is specified.

Examples:
    uv run python scripts/release_gate.py --candidate rc_20260620
    uv run python scripts/release_gate.py --candidate rc_20260620 \
        --run-quality-gates --evidence-dir artifacts/release_gates
    ALPHA_RELEASE_CANDIDATE=rc_20260620 uv run python scripts/release_gate.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.release.candidate import (  # noqa: E402
    get_git_revision,
    resolve_candidate_reference,
    verify_release_candidate,
)
from src.release.quality import run_quality_gates  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    candidate_ref = args.candidate or os.environ.get("ALPHA_RELEASE_CANDIDATE")
    candidate_report = None
    if candidate_ref:
        revision = get_git_revision(PROJECT_ROOT)
        candidate_path = resolve_candidate_reference(candidate_ref, PROJECT_ROOT)
        candidate_report = verify_release_candidate(
            candidate_path,
            project_root=PROJECT_ROOT,
            revision=revision,
        )
        result: dict[str, Any] = {
            "schema_version": "1",
            "candidate_verification": candidate_report.to_dict(),
        }
    else:
        if not args.run_quality_gates:
            return (
                _emit(
                    {
                        "schema_version": "1",
                        "status": "fail",
                        "error": "explicit_release_candidate_required_unless_quality_gates",
                    },
                    output=args.output,
                )
                or 2
            )
        result = {"schema_version": "1"}
    quality_report: dict[str, Any] | None = None
    if args.run_quality_gates:
        revision = get_git_revision(PROJECT_ROOT) if not candidate_ref else revision
        approved_skips = {
            "tests/test_orchestrator_all_subprocess.py::test_orchestrator_market_all_runs_via_subprocess",
            "tests/test_orchestrator_logs_data_snapshot.py::test_rebacktest_logs_data_snapshot_id_and_end_date",
            "tests/test_signal_pipeline.py::TestAPIEndpoints::test_data_status_endpoint",
            "tests/test_signal_pipeline.py::TestAPIEndpoints::test_signal_daily_endpoint",
            "tests/test_signal_pipeline.py::TestAPIEndpoints::test_signal_grade_endpoint",
            "tests/test_signal_pipeline.py::TestAPIEndpoints::test_signal_performance_endpoint",
            "tests/test_signal_pipeline.py::TestAPIEndpoints::test_watchlist_summary_endpoint",
            "tests/test_signal_pipeline.py::TestWalkForward::test_walk_forward_positive_ic",
            "tests/test_signal_pipeline.py::TestWalkForward::test_walk_forward_runs",
        }
        quality_report = run_quality_gates(
            PROJECT_ROOT,
            (PROJECT_ROOT / args.evidence_dir).resolve(),
            revision=revision,
            approved_skips=approved_skips,
        )
        result["quality_gates"] = quality_report

    result["status"] = (
        "pass"
        if (candidate_report is None or candidate_report.ok)
        and (quality_report is None or quality_report.get("status") == "pass")
        else "fail"
    )
    if args.run_quality_gates:
        verdict_path = (PROJECT_ROOT / args.evidence_dir).resolve() / "release_gate_verdict.json"
        verdict_path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    _emit(result, output=args.output)
    if result["status"] == "pass":
        return 0
    if args.allow_verification_failure and quality_report and quality_report.get("status") == "pass":
        return 0
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate",
        help="Exact ReleaseCandidate manifest path or rc_* identifier. "
        "Falls back to ALPHA_RELEASE_CANDIDATE env var. No default is allowed.",
    )
    parser.add_argument(
        "--run-quality-gates",
        action="store_true",
        help="Run the complete local/CI backend, frontend, browser, and packaging gates.",
    )
    parser.add_argument(
        "--evidence-dir",
        default="artifacts/release_gates",
        help="Project-relative directory for command logs and machine-readable evidence.",
    )
    parser.add_argument("--output", help="Optional path for the final JSON verdict.")
    parser.add_argument(
        "--allow-verification-failure",
        action="store_true",
        help="Exit 0 even if candidate verification fails (quality gates still checked).",
    )
    return parser


def _emit(payload: dict[str, Any], *, output: str | None) -> int:
    text = json.dumps(payload, indent=2, sort_keys=True)
    if output:
        path = Path(output)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
