from pathlib import Path
import subprocess

BASE = "c30d33bf59bf7161846bd3b6bec3b874c7ac9597"

# Restore the long test file exactly; a prior Contents API write is intentionally discarded.
original = subprocess.check_output(
    ["git", "show", f"{BASE}:tests/test_formal_refresh.py"], text=True
)
Path("tests/test_formal_refresh.py").write_text(original, encoding="utf-8")

# Keep readiness as internal provider-build evidence; do not create a sixth run-scoped artifact class.
workflow_path = Path(".github/workflows/formal-backtest-refresh.yml")
workflow = workflow_path.read_text(encoding="utf-8")
start = workflow.index("      - name: Upload provider readiness evidence\n")
end = workflow.index("      - name: Upload failed provider diagnostics\n", start)
workflow = workflow[:start] + workflow[end:]
workflow_path.write_text(workflow, encoding="utf-8")

# Update the existing trigger-scope contract to the new effective-seed authority.
scope_path = Path("tests/test_formal_refresh_trigger_scope.py")
scope = scope_path.read_text(encoding="utf-8")
old = '''    assert "formal-provider-1.1.0-${{ matrix.market }}-${{ matrix.market == 'us' &&" in text
    assert "formal-provider-1.0.0-${{ matrix.market }}-${{ matrix.market == 'us' &&" in text
    assert "needs.prepare.outputs.us_seed_cutoff || needs.prepare.outputs.cn_seed_cutoff }}-" in text
'''
new = '''    assert "Resolve latest complete provider cutoff" in text
    assert '--seed-cutoff "$SEED_CUTOFF"' in text
    assert (
        "formal-provider-1.1.0-${{ matrix.market }}-"
        "${{ steps.readiness.outputs.effective_seed_cutoff }}-"
    ) in text
    assert (
        "formal-provider-1.0.0-${{ matrix.market }}-"
        "${{ steps.readiness.outputs.effective_seed_cutoff }}-"
    ) in text
'''
if scope.count(old) != 1:
    raise SystemExit("effective-seed contract marker not found exactly once")
scope_path.write_text(scope.replace(old, new, 1), encoding="utf-8")

# Candidate CI must execute the new resolver contract before merge, not first in production.
ci_path = Path(".github/workflows/formal-backtest-refresh-ci.yml")
ci = ci_path.read_text(encoding="utf-8")
script_marker = "            scripts/data/refresh_selected_pool_prices_v2.py \\\n"
script_insert = (
    "            scripts/data/resolve_formal_provider_cutoff.py \\\n"
    + script_marker
)
if ci.count(script_marker) != 2:
    raise SystemExit("expected resolver Ruff insertion marker twice")
ci = ci.replace(script_marker, script_insert)

test_marker = "            tests/test_formal_refresh_trigger_scope.py \\\n"
test_insert = (
    "            tests/test_resolve_formal_provider_cutoff.py \\\n"
    + test_marker
)
if ci.count(test_marker) != 2:
    raise SystemExit("expected resolver pytest insertion marker twice")
ci = ci.replace(test_marker, test_insert)

# Add the resolver to each candidate Mypy block only.
search_from = 0
for _ in range(2):
    mypy_start = ci.index("          uv run mypy \\\n", search_from)
    pytest_start = ci.index("          uv run pytest \\\n", mypy_start)
    block = ci[mypy_start:pytest_start]
    marker = "            scripts/run_formal_refresh_transaction.py \\\n"
    if marker not in block:
        raise SystemExit("mypy resolver insertion marker missing")
    block = block.replace(
        marker,
        "            scripts/data/resolve_formal_provider_cutoff.py \\\n" + marker,
        1,
    )
    ci = ci[:mypy_start] + block + ci[pytest_start:]
    search_from = mypy_start + len(block)
ci_path.write_text(ci, encoding="utf-8")
