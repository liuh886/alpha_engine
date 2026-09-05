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
    "corporate-action-store-ci.yml": 1,
    "etf-reference-bundle-ci.yml": 2,
    "factor-knowledge-registry-ci.yml": 1,
    "fundamental-acceleration-ci.yml": 1,
    "researcher-data-cli-ci.yml": 1,
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
    assert sum(WORKFLOW_JOB_COUNTS.values()) == 20
    root = Path(".github/workflows")
    for filename, job_count in WORKFLOW_JOB_COUNTS.items():
        content = (root / filename).read_text(encoding="utf-8")
        workflow = yaml.safe_load(content)
        triggers = workflow.get("on", workflow.get(True, {}))
        assert content.count("uses: actions/checkout@v7") == job_count
        assert content.count("uses: ./.github/actions/setup-python-uv") == job_count
        for event in ("pull_request", "push"):
            if event in triggers:
                assert ".github/actions/setup-python-uv/action.yml" in triggers[event][
                    "paths"
                ]
        assert "curl -LsSf https://astral.sh/uv/install.sh" not in content
        assert "actions/checkout@v4" not in content
        assert "actions/setup-python@v5" not in content
        assert "actions/upload-artifact@v4" not in content


def test_etf_live_bundle_keeps_provider_and_evidence_boundaries() -> None:
    workflow = yaml.safe_load(
        Path(".github/workflows/etf-reference-bundle-ci.yml").read_text(
            encoding="utf-8"
        )
    )
    live = workflow["jobs"]["live-bundle"]
    steps = live["steps"]
    upload = next(
        step
        for step in steps
        if step.get("name") == "Upload ETF reference bundle and credential evidence"
    )

    assert live["if"] == "github.event_name != 'pull_request'"
    assert live["needs"] == "contract"
    assert live["env"] == {"TIINGO_API_TOKEN": "${{ secrets.TIINGO_API_TOKEN }}"}
    assert steps[0]["uses"] == "actions/checkout@v7"
    assert steps[1]["uses"] == "./.github/actions/setup-python-uv"
    assert upload["if"] == "always()"
    assert upload["uses"] == "actions/upload-artifact@v7"
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["retention-days"] == 90


def test_researcher_cli_contract_stays_offline() -> None:
    workflow = yaml.safe_load(
        Path(".github/workflows/researcher-data-cli-ci.yml").read_text(
            encoding="utf-8"
        )
    )

    assert workflow["jobs"]["contract"]["env"] == {
        "TIINGO_API_TOKEN": "",
        "TUSHARE_TOKEN": "",
    }


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


def test_monthly_live_data_workflows_resolve_cutoffs_at_runtime() -> None:
    root = Path(".github/workflows")
    for filename in (
        "alpha158-canonical-vwap-ci.yml",
        "selected-pool-event-population-ci.yml",
    ):
        workflow = yaml.safe_load((root / filename).read_text(encoding="utf-8"))
        triggers = workflow.get("on", workflow.get(True, {}))
        cutoff = triggers["workflow_dispatch"]["inputs"]["cutoff"]
        assert cutoff["required"] is False
        assert cutoff["default"] == ""
        for job in workflow["jobs"].values():
            for step in job.get("steps", []):
                if step.get("id") == "cutoff":
                    assert step["env"]["REQUESTED_CUTOFF"] == "${{ inputs.cutoff }}"
                    assert '${{ inputs.cutoff }}' not in step["run"]
                    assert 'cutoff="$REQUESTED_CUTOFF"' in step["run"]
                    assert 'date -u -d "$cutoff" +%F' in step["run"]

    events = yaml.safe_load(
        (root / "selected-pool-event-population-ci.yml").read_text(encoding="utf-8")
    )
    steps = events["jobs"]["live-population"]["steps"]
    cutoff_step = next(step for step in steps if step.get("id") == "cutoff")
    restore = next(step for step in steps if step.get("id") == "event-source-cache")
    populate = next(
        step
        for step in steps
        if step.get("name") == "Populate public primary event stores"
    )

    assert "date -u -d '1 day ago' +%F" in cutoff_step["run"]
    assert 'date -u -d "$cutoff" +%F' in cutoff_step["run"]
    assert "${{ steps.cutoff.outputs.value }}" in restore["with"]["key"]
    assert "${{ steps.cutoff.outputs.value }}" in restore["with"]["restore-keys"]
    assert '--cutoff "${{ steps.cutoff.outputs.value }}"' in populate["run"]
    assert "inputs.cutoff || '2026-07-31'" not in (
        root / "selected-pool-event-population-ci.yml"
    ).read_text(encoding="utf-8")


def test_us_alpha158_live_panel_uses_only_approved_alpaca_sip_credentials() -> None:
    workflow = yaml.safe_load(
        Path(".github/workflows/alpha158-canonical-vwap-ci.yml").read_text(
            encoding="utf-8"
        )
    )
    live = workflow["jobs"]["live-us-panel"]

    assert live["env"] == {
        "APCA_API_KEY_ID": "${{ secrets.APCA_API_KEY_ID }}",
        "APCA_API_SECRET_KEY": "${{ secrets.APCA_API_SECRET_KEY }}",
    }
    content = Path(".github/workflows/alpha158-canonical-vwap-ci.yml").read_text(
        encoding="utf-8"
    )
    live_block = content[content.index("  live-us-panel:") : content.index("  live-cn-panel:")]
    assert "AlpacaAdapter" in live_block
    assert '("ABBNY", "otc")' in live_block
    assert '("SBGSY", "otc")' in live_block
    assert "PolygonAdapter" not in live_block
    assert "POLYGON_API_KEY" not in live_block
    assert "feed=sip" not in live_block  # The adapter owns frozen request semantics.

    contract = yaml.safe_load(
        Path("configs/data/alpha158_panel_v1.yaml").read_text(encoding="utf-8")
    )
    source = contract["markets"]["us"]["canonical_vwap_source"]
    assert source == {
        "provider": "alpaca_market_data",
        "endpoint": "historical_stock_bars",
        "feed": "sip",
        "symbol_feed_overrides": {"ABBNY": "otc", "SBGSY": "otc"},
        "timeframe": "1Day",
        "adjustment": "all",
        "credential_env": ["APCA_API_KEY_ID", "APCA_API_SECRET_KEY"],
        "credential_absence_status": "blocked",
        "same_record_ohlcv_vwap_required": True,
        "full_pool_live_preflight_required": True,
    }


def test_sec_population_uses_public_identity_variable_and_secret_proxy_only() -> None:
    content = Path(
        ".github/workflows/selected-pool-event-population-ci.yml"
    ).read_text(encoding="utf-8")
    live_block = content[content.index("      - name: Populate public primary event stores") :]

    assert "SEC_USER_AGENT: ${{ vars.SEC_USER_AGENT }}" in live_block
    assert "SEC_USER_AGENT: ${{ secrets.SEC_USER_AGENT }}" not in live_block
    assert "SEC_EGRESS_PROXY_URL: ${{ secrets.SEC_EGRESS_PROXY_URL || '' }}" in live_block


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
