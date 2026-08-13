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
