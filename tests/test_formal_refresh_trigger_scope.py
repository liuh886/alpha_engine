from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/formal-backtest-refresh.yml")


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


def test_heavy_formal_refresh_keeps_source_and_release_gates() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    required = (
        '  schedule:',
        '  workflow_dispatch:',
        '      - "configs/models/**"',
        '      - "configs/strategies/registry.json"',
        '      - "configs/factor_libraries/ohlcv.yaml"',
        '      - "scripts/run_formal_refresh_transaction.py"',
        '      - "scripts/run_formal_strategy_refresh.py"',
        '      - "scripts/build_us_x1_3_preview.py"',
        '      - "tests/test_us_x1_3_preview_publication.py"',
        '      - name: Atomically fan in active preview results',
        '      - name: Wait for candidate checks, merge reviewed refresh, and verify Pages',
        '      - name: Upsert refresh operating status',
    )
    for token in required:
        assert token in text, f"formal refresh lost required source/release gate: {token}"


def test_heavy_formal_refresh_resolves_cutoff_per_completed_market_session() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "from src.research.market_session_clock import completed_market_date" in text
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


def test_heavy_formal_refresh_has_no_retired_us_x1_2_live_contract() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "test_us_x1_2_current_target.py" not in text
    assert "run_us_x1_2_current_target.py" not in text
    assert "us_x1_2_current_target.py" not in text
