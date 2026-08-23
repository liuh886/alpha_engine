from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/formal-backtest-refresh.yml")
CI_WORKFLOW = Path(".github/workflows/formal-backtest-refresh-ci.yml")


def test_heavy_formal_refresh_does_not_trigger_from_its_own_outputs() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    forbidden_push_paths = (
        '      - "data/research/formal_backtests/**"',
        '      - "data/research/formal_model_runs/**"',
        '      - "data/research/model_runs/**"',
        '      - "data/research/market_evidence/**"',
        '      - "data/research/model_data_bundle_v1/**"',
        '      - "data/research/strategy_signal_ledgers/**"',
        '      - "qlib-dashboard/scripts/**"',
        '      - "qlib-dashboard/src/**"',
        '      - "qlib-dashboard/package.json"',
        '      - "qlib-dashboard/package-lock.json"',
    )
    for path in forbidden_push_paths:
        assert path not in text, f"heavy formal refresh recursively watches {path}"


def test_heavy_formal_refresh_excludes_independent_event_population_workstream() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    exclusions = (
        (
            '      - "configs/data/**"',
            '      - "!configs/data/selected_pool_event_population_v1.yaml"',
        ),
        (
            '      - "src/data/**"',
            '      - "!src/data/selected_pool_event_population.py"',
        ),
        ('      - "src/data/**"', '      - "!src/data/fundamentals/**"'),
        ('      - "src/data/**"', '      - "!src/data/corporate_actions/**"'),
        (
            '      - "scripts/data/**"',
            '      - "!scripts/data/populate_selected_pool_events.py"',
        ),
    )
    for broad_path, exclusion in exclusions:
        assert broad_path in text
        assert exclusion in text
        assert text.index(broad_path) < text.index(exclusion), (
            f"GitHub path exclusion must follow its positive pattern: {exclusion}"
        )


def test_formal_candidate_ci_excludes_independent_event_population_workstream() -> None:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    exclusions = (
        '      - "!src/data/selected_pool_event_population.py"',
        '      - "!src/data/fundamentals/**"',
        '      - "!src/data/corporate_actions/**"',
        '      - "!scripts/data/populate_selected_pool_events.py"',
    )
    for exclusion in exclusions:
        assert exclusion in text
        broad_path = (
            '      - "scripts/data/**"'
            if exclusion.startswith('      - "!scripts/')
            else '      - "src/data/**"'
        )
        assert text.index(broad_path) < text.index(exclusion), (
            f"GitHub path exclusion must follow its positive pattern: {exclusion}"
        )


def test_heavy_formal_refresh_keeps_source_and_release_gates() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    required = (
        '  schedule:',
        '  workflow_dispatch:',
        '      - "configs/models/**"',
        '      - "configs/strategies/registry.json"',
        '      - "src/governance/**"',
        '      - "configs/factor_libraries/ohlcv.yaml"',
        '      - "scripts/run_formal_refresh_transaction.py"',
        '      - "scripts/run_formal_strategy_refresh.py"',
        '      - "scripts/build_us_x1_3_preview.py"',
        '      - "tests/test_us_x1_3_preview_publication.py"',
        '      - "tests/test_strategy_runtime_capabilities.py"',
        '      - name: Atomically fan in active preview results',
        '      - name: Wait for candidate checks, merge reviewed refresh, and verify Pages',
        '      - name: Upsert refresh operating status',
    )
    for token in required:
        assert token in text, f"formal refresh lost required source/release gate: {token}"


def test_heavy_formal_refresh_does_not_publish_after_explicit_cancellation() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    publish_job = (
        "  publish:\n"
        "    needs: [prepare, providers, plan, strategy]\n"
        "    if: ${{ !cancelled() }}\n"
    )
    assert publish_job in text
    assert "if: always()" not in text
    assert text.count("if: ${{ !cancelled() }}") == 4


def test_formal_candidate_ci_uses_bounded_research_paths() -> None:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert '      - "src/research/**"' not in text
    required = (
        '      - "src/research/formal_model_replay.py"',
        '      - "src/research/qqq_authoritative_replay.py"',
        '      - "src/research/rules_formal_replay_gate.py"',
        '      - "src/research/cn_x1_2_prospective.py"',
        '      - "src/research/cn_x1_2_current_target.py"',
        '      - "src/research/ranker_current_target.py"',
        '      - "src/research/us_x1_3_current_target.py"',
        '      - "src/research/replay_comparison.py"',
        '      - "src/research/ranker_training.py"',
        '      - "src/research/market_session_clock.py"',
        '      - "src/research/byd_v1_3_low_vol_recovery.py"',
    )
    for path in required:
        assert path in text, f"formal candidate CI lost required research input: {path}"


def test_heavy_formal_refresh_uses_bounded_research_paths() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '      - "src/research/**"' not in text
    required = (
        '      - "src/research/formal_model_replay.py"',
        '      - "src/research/qqq_authoritative_replay.py"',
        '      - "src/research/rules_formal_replay_gate.py"',
        '      - "src/research/cn_x1_2_prospective.py"',
        '      - "src/research/cn_x1_2_current_target.py"',
        '      - "src/research/ranker_current_target.py"',
        '      - "src/research/us_x1_3_current_target.py"',
        '      - "src/research/replay_comparison.py"',
        '      - "src/research/ranker_training.py"',
        '      - "src/research/market_session_clock.py"',
        '      - "src/research/byd_v1_3_low_vol_recovery.py"',
    )
    for path in required:
        assert path in text, f"heavy formal refresh lost required research input: {path}"


def test_heavy_formal_refresh_resolves_cutoff_per_completed_market_session() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "from src.research.market_session_clock import completed_market_date" in text
    assert "Resolve immutable workflow start" in text
    assert 'gh api "/repos/${GITHUB_REPOSITORY}/actions/runs/${GITHUB_RUN_ID}"' in text
    assert "RUN_CREATED_AT: ${{ steps.run_identity.outputs.created_at }}" in text
    assert "os.environ['RUN_CREATED_AT']" in text
    assert "datetime.now(timezone.utc)" not in text
    assert "us_cutoff: ${{ steps.clock.outputs.us_cutoff }}" in text
    assert "cn_cutoff: ${{ steps.clock.outputs.cn_cutoff }}" in text
    assert "completed_market_date('us', requested, now_utc=now)" in text
    assert "completed_market_date('cn', requested, now_utc=now)" in text
    market_cutoff_binding = (
        "REQUESTED_CUTOFF: ${{ matrix.market == 'us' && "
        "needs.prepare.outputs.us_cutoff || needs.prepare.outputs.cn_cutoff }}"
    )
    assert text.count(market_cutoff_binding) == 2
    assert "requested_cutoff: ${{ steps.clock.outputs.requested_cutoff }}" not in text
    assert 'requested_cutoff="$(date -u +%Y-%m-%d)"' not in text


def test_heavy_formal_refresh_reuses_previous_governed_provider_incrementally() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "us_seed_cutoff: ${{ steps.clock.outputs.us_seed_cutoff }}" in text
    assert "cn_seed_cutoff: ${{ steps.clock.outputs.cn_seed_cutoff }}" in text
    assert "Restore previous governed provider seed" in text
    assert "Prepare governed provider seed" in text
    assert "seed_source=governed_cache" in text
    assert "Incrementally extend isolated selected-pool provider" in text
    assert '--source-csv-dir "$SOURCE_CSV_DIR"' in text
    assert "--auxiliary-symbol" in text
    assert "--full-refresh" not in text
    assert "formal-provider-1.0.0-${{ matrix.market }}-${{ matrix.market == 'us' &&" in text
    assert "needs.prepare.outputs.us_seed_cutoff || needs.prepare.outputs.cn_seed_cutoff }}-" in text


def test_heavy_formal_refresh_has_no_retired_us_x1_2_live_contract() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "test_us_x1_2_current_target.py" not in text
    assert "run_us_x1_2_current_target.py" not in text
    assert "us_x1_2_current_target.py" not in text
