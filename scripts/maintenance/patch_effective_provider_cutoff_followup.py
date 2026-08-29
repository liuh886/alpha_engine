from pathlib import Path

path = Path('.github/workflows/formal-backtest-refresh.yml')
text = path.read_text(encoding='utf-8')

status_env = '''          US_CUTOFF: ${{ needs.plan.outputs.us_cutoff }}
          CN_CUTOFF: ${{ needs.plan.outputs.cn_cutoff }}
          REVIEWED_MERGE_SHA: ${{ steps.release.outputs.merge_sha }}
'''
status_env_replacement = '''          US_CUTOFF: ${{ needs.plan.outputs.us_cutoff }}
          CN_CUTOFF: ${{ needs.plan.outputs.cn_cutoff }}
          EXPECTED_US_CUTOFF: ${{ needs.prepare.outputs.us_cutoff }}
          EXPECTED_CN_CUTOFF: ${{ needs.prepare.outputs.cn_cutoff }}
          REVIEWED_MERGE_SHA: ${{ steps.release.outputs.merge_sha }}
'''
if text.count(status_env) != 1:
    raise SystemExit('expected exactly one operating-status env marker')
text = text.replace(status_env, status_env_replacement, 1)

ruff_script = '''            scripts/govern_formal_provider_cache.py \\
            scripts/data/refresh_selected_pool_prices.py \\
'''
ruff_script_replacement = '''            scripts/govern_formal_provider_cache.py \\
            scripts/data/resolve_formal_provider_cutoff.py \\
            scripts/data/refresh_selected_pool_prices.py \\
'''
if text.count(ruff_script) != 1:
    raise SystemExit('expected exactly one Ruff script marker')
text = text.replace(ruff_script, ruff_script_replacement, 1)

ruff_test = '''            tests/test_selected_pool_governance.py \\
            tests/test_strategy_operations.py \\
'''
ruff_test_replacement = '''            tests/test_selected_pool_governance.py \\
            tests/test_resolve_formal_provider_cutoff.py \\
            tests/test_strategy_operations.py \\
'''
if text.count(ruff_test) < 1:
    raise SystemExit('Ruff test marker not found')
text = text.replace(ruff_test, ruff_test_replacement, 1)

mypy_marker = '''            scripts/govern_formal_provider_cache.py \\
            scripts/build_market_evidence.py \\
'''
mypy_replacement = '''            scripts/govern_formal_provider_cache.py \\
            scripts/data/resolve_formal_provider_cutoff.py \\
            scripts/build_market_evidence.py \\
'''
if text.count(mypy_marker) != 1:
    raise SystemExit('Mypy marker not found exactly once')
text = text.replace(mypy_marker, mypy_replacement, 1)

pytest_marker = '''            tests/test_selected_pool_governance.py \\
            tests/test_strategy_operations.py \\
'''
pytest_replacement = '''            tests/test_selected_pool_governance.py \\
            tests/test_resolve_formal_provider_cutoff.py \\
            tests/test_strategy_operations.py \\
'''
if text.count(pytest_marker) != 1:
    raise SystemExit('Pytest marker not found exactly once after Ruff replacement')
text = text.replace(pytest_marker, pytest_replacement, 1)

path.write_text(text, encoding='utf-8')
