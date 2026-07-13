"""Apply the explicit incomplete-OOS-window policy integration.

Deleted before merge.
"""

from __future__ import annotations

from pathlib import Path

PARADIGM = Path("src/research/paradigm.py")
ALIGNMENT = Path("src/research/market_data_alignment.py")
DIAGNOSTICS = Path("src/research/spec_bound_factor_diagnostics.py")
EXECUTION = Path("src/research/spec_bound_execution.py")
CN_ADAPTER = Path("src/research/cn_qlib_execution_adapter.py")
US_ADAPTER = Path("src/research/us_qlib_execution_adapter.py")
RESEARCH_TESTS = Path("tests/test_research_paradigm.py")
DIAGNOSTIC_TESTS = Path("tests/test_spec_bound_factor_diagnostics.py")
CN_SPEC = Path("configs/research_paradigms/cn_10d_csi300_baseline.yaml")
US_SPEC = Path("configs/research_paradigms/us_10d_qqq_baseline.yaml")
CI_SPEC = Path("tests/fixtures/cn_qlib_ci/paradigm.yaml")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def patch_paradigm() -> None:
    text = PARADIGM.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'from src.research.ten_day_model_gates import GATE_THRESHOLDS\n',
        'from src.research.ten_day_model_gates import GATE_THRESHOLDS\n'
        'from src.research.window_policy import (\n'
        '    COMPLETE_WINDOWS_ONLY,\n'
        '    validate_partial_window_contract,\n'
        ')\n',
        "paradigm window policy import",
    )
    text = replace_once(
        text,
        'PARADIGM_SCHEMA_VERSION = "1.0"',
        'PARADIGM_SCHEMA_VERSION = "1.1"',
        "paradigm schema",
    )
    text = replace_once(
        text,
        """    if int(walk_forward.get("train_embargo_sessions", 0)) != 10:
        raise ValueError("walk_forward.train_embargo_sessions must be 10")
""",
        """    if int(walk_forward.get("train_embargo_sessions", 0)) != 10:
        raise ValueError("walk_forward.train_embargo_sessions must be 10")
    partial_policy = str(walk_forward.get("partial_window_policy", ""))
    raw_partial_minimum = walk_forward.get(
        "min_partial_window_eligible_sessions"
    )
    partial_minimum = (
        None if raw_partial_minimum is None else int(raw_partial_minimum)
    )
    validate_partial_window_contract(
        policy=partial_policy,
        min_partial_window_eligible_sessions=partial_minimum,
        cadence_sessions=int(strategy["rebalance_days"]),
    )
    if partial_policy == COMPLETE_WINDOWS_ONLY and (
        "min_partial_window_eligible_sessions" in walk_forward
    ):
        raise ValueError(
            "complete_windows_only must not declare a partial-window session minimum"
        )
""",
        "paradigm walk-forward policy validation",
    )
    PARADIGM.write_text(text, encoding="utf-8")


def patch_alignment() -> None:
    text = ALIGNMENT.read_text(encoding="utf-8")
    text = replace_once(
        text,
        """from src.research.rolling_windows import (
    RollingResearchWindow,
    filter_windows_by_available_range,
    half_year_rolling_windows,
)
""",
        """from src.research.rolling_windows import RollingResearchWindow
from src.research.window_policy import (
    COMPLETE_WINDOWS_ONLY,
    MIN_WINDOWS_COUNT_POLICY,
    complete_boundary_windows,
)
""",
        "alignment imports",
    )
    start = text.index("def get_aligned_windows(")
    end = text.index("\ndef _count_viable_oos_windows(", start)
    replacement = '''def get_aligned_windows(
    aligned_start: str,
    available_end: str,
    *,
    first_test_year: int = _FIRST_TEST_YEAR,
    last_test_year: int = _LAST_TEST_YEAR,
) -> list[RollingResearchWindow]:
    """Return complete aligned windows for boundary-only readiness checks.

    ``min_windows`` always counts complete half-year windows. Session-aware
    execution and diagnostics use ``build_window_sampling_plan`` from
    ``window_policy`` to append an optional eligible partial final window.
    """

    return complete_boundary_windows(
        aligned_start,
        available_end,
        first_test_year=first_test_year,
        last_test_year=last_test_year,
    )

'''
    text = text[:start] + replacement + text[end + 1 :]
    text = replace_once(
        text,
        """            "viable_windows": self.viable_windows,
            "min_viable_windows": self.min_viable_windows,
""",
        """            "viable_windows": self.viable_windows,
            "min_viable_windows": self.min_viable_windows,
            "viable_windows_policy": MIN_WINDOWS_COUNT_POLICY,
            "partial_windows_count_toward_min": False,
            "viability_evidence_scope": "boundary_only",
""",
        "alignment evidence semantics",
    )
    ALIGNMENT.write_text(text, encoding="utf-8")


def patch_diagnostics() -> None:
    text = DIAGNOSTICS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        """from src.research.market_data_alignment import get_aligned_windows
""",
        """from src.research.window_policy import build_window_sampling_plan
""",
        "diagnostic planner import",
    )
    text = replace_once(
        text,
        'FACTOR_DIAGNOSTICS_SCHEMA_VERSION = "1.2"',
        'FACTOR_DIAGNOSTICS_SCHEMA_VERSION = "1.3"',
        "diagnostic schema",
    )
    start = text.index("def _window_date_map(")
    end = text.index("\ndef _daily_factor_rows(", start)
    replacement = '''def _window_date_map(
    available_dates: pd.DatetimeIndex,
    spec: ResearchParadigmSpec,
) -> tuple[
    dict[pd.Timestamp, str],
    list[dict[str, Any]],
    dict[str, Any],
]:
    """Build the explicit, horizon-contained OOS sampling plan."""

    walk = spec.walk_forward
    raw_partial_minimum = walk.get("min_partial_window_eligible_sessions")
    plan = build_window_sampling_plan(
        available_dates,
        str(walk["requested_train_start"]),
        str(walk["test_end"]),
        first_test_year=int(walk["first_test_year"]),
        last_test_year=int(walk["last_test_year"]),
        min_complete_windows=int(walk["min_windows"]),
        partial_window_policy=str(walk["partial_window_policy"]),
        min_partial_window_eligible_sessions=(
            None
            if raw_partial_minimum is None
            else int(raw_partial_minimum)
        ),
        horizon_sessions=int(spec.strategy["horizon_days"]),
        cadence_sessions=int(spec.strategy["rebalance_days"]),
    )
    if not plan.complete_minimum_satisfied:
        raise ValueError(
            "declared walk-forward contract has too few complete, "
            "session-eligible diagnostic windows"
        )
    if not plan.date_map:
        raise ValueError(
            "no horizon-contained rebalance dates are available for factor diagnostics"
        )
    metadata = plan.to_dict()
    metadata.pop("windows", None)
    return plan.date_map, list(plan.window_rows), metadata

'''
    text = text[:start] + replacement + text[end + 1 :]
    text = replace_once(
        text,
        """    date_map, windows = _window_date_map(available_dates, spec)
""",
        """    date_map, windows, window_policy = _window_date_map(
        available_dates, spec
    )
""",
        "diagnostic plan unpack",
    )
    text = replace_once(
        text,
        """        "windows": windows,
        "sampled_rebalance_dates": len(date_map),
""",
        """        "window_policy": window_policy,
        "windows": windows,
        "sampled_rebalance_dates": len(date_map),
""",
        "diagnostic window policy evidence",
    )
    DIAGNOSTICS.write_text(text, encoding="utf-8")


def patch_execution_contract() -> None:
    text = EXECUTION.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'EXECUTION_CONTRACT_SCHEMA_VERSION = "1.0"',
        'EXECUTION_CONTRACT_SCHEMA_VERSION = "1.1"',
        "execution contract schema",
    )
    EXECUTION.write_text(text, encoding="utf-8")


def patch_adapter(path: Path, market_name: str) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        """from src.research.market_data_alignment import (
    align_train_start_to_coverage,
    get_aligned_windows,
)
""",
        """from src.research.market_data_alignment import align_train_start_to_coverage
""",
        f"{market_name} alignment import",
    )
    artifact_import = (
        "from src.research.walk_forward_stability import "
        "summarize_walk_forward_reports\n"
    )
    text = replace_once(
        text,
        artifact_import,
        artifact_import
        + "from src.research.window_policy import build_window_sampling_plan\n",
        f"{market_name} planner import",
    )
    text = replace_once(
        text,
        """    min_windows = int(walk_forward["min_windows"])
""",
        """    min_windows = int(walk_forward["min_windows"])
    partial_window_policy = str(
        walk_forward["partial_window_policy"]
    )
    raw_partial_minimum = walk_forward.get(
        "min_partial_window_eligible_sessions"
    )
    min_partial_window_eligible_sessions = (
        None
        if raw_partial_minimum is None
        else int(raw_partial_minimum)
    )
""",
        f"{market_name} policy fields",
    )
    old = """    windows = get_aligned_windows(
        alignment.aligned_train_start,
        available_end,
        first_test_year=first_test_year,
        last_test_year=last_test_year,
    )
    window_payload = {
        "schema_version": "1.0",
        "experiment_id": plan.spec.experiment_id,
        "requested_min_windows": min_windows,
        "available_end": available_end,
        "windows": [window.to_dict() for window in windows],
    }
    write_json(paths.walk_forward_windows, window_payload)
    runtime_metadata["windows"] = window_payload["windows"]
"""
    new = """    window_plan = build_window_sampling_plan(
        calendar,
        alignment.aligned_train_start,
        available_end,
        first_test_year=first_test_year,
        last_test_year=last_test_year,
        min_complete_windows=min_windows,
        partial_window_policy=partial_window_policy,
        min_partial_window_eligible_sessions=(
            min_partial_window_eligible_sessions
        ),
        horizon_sessions=int(strategy["horizon_days"]),
        cadence_sessions=int(strategy["rebalance_days"]),
    )
    windows = list(window_plan.selected_windows)
    window_payload = {
        **window_plan.to_dict(),
        "experiment_id": plan.spec.experiment_id,
        "available_end": available_end,
    }
    readiness.update(
        {
            "viable_windows": window_plan.complete_window_count,
            "viable_windows_policy": "complete_windows_only",
            "partial_windows_count_toward_min": False,
            "viability_evidence_scope": "session_aware",
            "partial_window_policy": partial_window_policy,
            "partial_window_count": window_plan.partial_window_count,
            "complete_minimum_satisfied": (
                window_plan.complete_minimum_satisfied
            ),
        }
    )
    write_json(paths.data_readiness, readiness)
    write_json(paths.walk_forward_windows, window_payload)
    runtime_metadata["windows"] = window_payload["windows"]
    runtime_metadata["window_policy"] = {
        key: value
        for key, value in window_payload.items()
        if key != "windows"
    }
"""
    text = replace_once(text, old, new, f"{market_name} window plan")
    text = replace_once(
        text,
        """    if len(windows) < min_windows:
""",
        """    if not window_plan.complete_minimum_satisfied:
""",
        f"{market_name} window minimum condition",
    )
    text = replace_once(
        text,
        """                f"only {len(windows)} aligned windows available; "
                f"need at least {min_windows}"
""",
        """                f"only {window_plan.complete_window_count} complete, "
                "session-eligible aligned windows available; "
                f"need at least {min_windows}"
""",
        f"{market_name} window minimum message",
    )
    path.write_text(text, encoding="utf-8")


def patch_yaml(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'schema_version: "1.0"',
        'schema_version: "1.1"',
        f"{path} schema",
    )
    text = replace_once(
        text,
        "  train_embargo_sessions: 10\n",
        "  train_embargo_sessions: 10\n"
        "  partial_window_policy: \"complete_windows_only\"\n",
        f"{path} complete window policy",
    )
    path.write_text(text, encoding="utf-8")


def patch_research_tests() -> None:
    text = RESEARCH_TESTS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'schema_version: "1.0"',
        'schema_version: "1.1"',
        "minimal spec schema",
    )
    text = replace_once(
        text,
        "  train_embargo_sessions: 10\n",
        "  train_embargo_sessions: 10\n"
        "  partial_window_policy: \"complete_windows_only\"\n",
        "minimal spec policy",
    )
    insertion = """        (
            lambda data: data["walk_forward"].update(
                partial_window_policy="implicit_or_unknown"
            ),
            "partial_window_policy",
        ),
        (
            lambda data: data["walk_forward"].update(
                min_partial_window_eligible_sessions=20
            ),
            "must be omitted",
        ),
"""
    anchor = """        (
            lambda data: data["evaluation"].update(benchmark_mode="active"),
            "benchmark_mode",
        ),
"""
    if "implicit_or_unknown" not in text:
        text = replace_once(text, anchor, insertion + anchor, "policy validation tests")
    extra = '''

def test_partial_final_window_contract_requires_session_minimum() -> None:
    data = _spec_dict()
    data["walk_forward"]["partial_window_policy"] = (
        "allow_horizon_contained_partial_final_window"
    )
    spec = ResearchParadigmSpec.from_dict(data)
    with pytest.raises(ValueError, match="is required"):
        validate_research_paradigm_spec(spec)

    data["walk_forward"]["min_partial_window_eligible_sessions"] = 20
    validate_research_paradigm_spec(ResearchParadigmSpec.from_dict(data))
'''
    marker = "\ndef test_contract_uses_profiles_not_duplicate_thresholds() -> None:\n"
    if "test_partial_final_window_contract_requires_session_minimum" not in text:
        text = replace_once(text, marker, extra + marker, "partial policy test insertion")
    RESEARCH_TESTS.write_text(text, encoding="utf-8")


def patch_diagnostic_tests() -> None:
    text = DIAGNOSTIC_TESTS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '                "schema_version": "1.0",',
        '                "schema_version": "1.1",',
        "diagnostic fixture schema",
    )
    text = replace_once(
        text,
        '                    "train_embargo_sessions": 10,\n',
        '                    "train_embargo_sessions": 10,\n'
        '                    "partial_window_policy": "complete_windows_only",\n',
        "diagnostic fixture policy",
    )
    text = replace_once(
        text,
        """    date_map, windows = _window_date_map(available_dates, spec)
""",
        """    date_map, windows, policy = _window_date_map(
        available_dates, spec
    )
""",
        "diagnostic window test unpack",
    )
    text = replace_once(
        text,
        """    assert selected
""",
        """    assert selected
    assert policy["partial_window_policy"] == "complete_windows_only"
    assert policy["complete_window_count"] == 4
    partial = next(row for row in windows if row["label"] == "2026H1")
    assert partial["status"] == "excluded"
    assert partial["boundary_status"] == "excluded_partial_by_policy"
    assert partial["natural_test_end"] == "2026-06-30"
    assert partial["effective_test_end"] == "2026-06-18"
""",
        "diagnostic complete policy evidence",
    )
    DIAGNOSTIC_TESTS.write_text(text, encoding="utf-8")


def main() -> None:
    patch_paradigm()
    patch_alignment()
    patch_diagnostics()
    patch_execution_contract()
    patch_adapter(CN_ADAPTER, "CN")
    patch_adapter(US_ADAPTER, "US")
    for path in (CN_SPEC, US_SPEC, CI_SPEC):
        patch_yaml(path)
    patch_research_tests()
    patch_diagnostic_tests()


if __name__ == "__main__":
    main()
