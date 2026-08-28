import importlib.util
from pathlib import Path

import yaml


POLICY_MODULE_SPEC = importlib.util.spec_from_file_location(
    "active_data_plane_ci_policy", Path("scripts/check_ci_policy.py")
)
assert POLICY_MODULE_SPEC is not None
assert POLICY_MODULE_SPEC.loader is not None
POLICY_MODULE = importlib.util.module_from_spec(POLICY_MODULE_SPEC)
POLICY_MODULE_SPEC.loader.exec_module(POLICY_MODULE)
action_refs = POLICY_MODULE.action_refs


WORKFLOW_JOB_COUNTS = {
    "alpha158-canonical-vwap-ci.yml": 3,
    "fundamental-event-store-ci.yml": 1,
    "selected-pool-event-population-ci.yml": 3,
    "factor-catalog-alpha158-ci.yml": 1,
    "alpha158-panel-ci.yml": 2,
    "us87-professional-prices-ci.yml": 2,
    "model-data-bundle-ci.yml": 2,
}


def test_shared_python_environment_is_frozen_and_cache_safe() -> None:
    action = yaml.safe_load(
        Path(".github/actions/setup-python-uv/action.yml").read_text(encoding="utf-8")
    )
    steps = action["runs"]["steps"]

    assert steps[0]["uses"] == "actions/setup-python@v7"
    assert steps[0]["with"]["python-version"] == "3.12"
    assert steps[1]["uses"] == (
        "astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d"
    )
    assert steps[1]["with"]["version"] == "0.12.7"
    assert steps[1]["with"]["enable-cache"] is True
    assert steps[1]["with"]["cache-dependency-glob"].splitlines() == [
        "pyproject.toml",
        "uv.lock",
    ]
    assert steps[2]["run"] == "uv sync --frozen --extra dev"


def test_active_data_plane_workflows_use_one_governed_environment_setup() -> None:
    root = Path(".github/workflows")
    for filename, job_count in WORKFLOW_JOB_COUNTS.items():
        content = (root / filename).read_text(encoding="utf-8")
        assert content.count("uses: actions/checkout@v7") == job_count
        assert content.count("uses: ./.github/actions/setup-python-uv") == job_count
        assert '".github/actions/setup-python-uv/action.yml"' in content
        assert "curl -LsSf https://astral.sh/uv/install.sh" not in content
        assert "actions/checkout@v4" not in content
        assert "actions/setup-python@v5" not in content
        assert "actions/upload-artifact@v4" not in content


def test_domain_data_caches_use_current_runtime_without_changing_keys() -> None:
    root = Path(".github/workflows")
    for filename in (
        "alpha158-canonical-vwap-ci.yml",
        "selected-pool-event-population-ci.yml",
    ):
        content = (root / filename).read_text(encoding="utf-8")
        assert "actions/cache/restore@v6" in content
        assert "actions/cache/save@v6" in content
        assert "actions/cache/restore@v4" not in content
        assert "actions/cache/save@v4" not in content

    canonical = yaml.safe_load(
        (root / "alpha158-canonical-vwap-ci.yml").read_text(encoding="utf-8")
    )
    steps = canonical["jobs"]["live-cn-panel"]["steps"]
    restore = next(step for step in steps if step.get("id") == "vwap-cache")
    save = next(
        step
        for step in steps
        if step.get("name") == "Save exact-cutoff CN source pairs"
    )
    assert restore["with"]["path"].splitlines() == [
        "artifacts/data/canonical_vwap/cn/raw",
        "artifacts/data/canonical_vwap/cn/qfq",
        "artifacts/data/canonical_vwap/cn/cache_metadata",
    ]
    assert restore["with"]["key"] == (
        "${{ runner.os }}-alpha158-vwap-cn-"
        "${{ hashFiles('configs/research_universes/cn_selected_equities_v3.yaml') }}-"
        "${{ steps.cutoff.outputs.value }}"
    )
    assert save["if"] == "always()"
    assert save["with"]["key"] == "${{ steps.vwap-cache.outputs.cache-primary-key }}"


def test_ci_policy_resolves_actions_inside_the_shared_composite() -> None:
    workflow = Path(
        ".github/workflows/fundamental-event-store-ci.yml"
    ).read_text(encoding="utf-8")

    refs = action_refs(workflow)

    assert "actions/checkout@v7" in refs
    assert "actions/setup-python@v7" in refs
    assert (
        "astral-sh/setup-uv@20cfd1bf945f4377ade1205e4dbc17946fc9a30d"
        in refs
    )


def test_ci_policy_resolves_quoted_local_action_references() -> None:
    refs = action_refs(
        'runs:\n  using: composite\n  steps:\n    - uses: "./.github/actions/setup-python-uv"\n'
    )

    assert "actions/setup-python@v7" in refs
