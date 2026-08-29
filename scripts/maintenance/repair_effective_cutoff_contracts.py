from pathlib import Path
import subprocess

BASE = "c30d33bf59bf7161846bd3b6bec3b874c7ac9597"

# Restore the long test file exactly; discard the accidental whole-file placeholder write.
original = subprocess.check_output(
    ["git", "show", f"{BASE}:tests/test_formal_refresh.py"], text=True
)
Path("tests/test_formal_refresh.py").write_text(original, encoding="utf-8")

# Readiness is internal provider-build evidence; keep the existing five run-scoped artifact classes.
workflow_path = Path(".github/workflows/formal-backtest-refresh.yml")
workflow = workflow_path.read_text(encoding="utf-8")
start = workflow.index("      - name: Upload provider readiness evidence\n")
end = workflow.index("      - name: Upload failed provider diagnostics\n", start)
workflow = workflow[:start] + workflow[end:]
workflow_path.write_text(workflow, encoding="utf-8")

# The effective provider watermark is now the seed-cache authority.
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

# Candidate CI must validate the resolver before merge.
ci_path = Path(".github/workflows/formal-backtest-refresh-ci.yml")
ci = ci_path.read_text(encoding="utf-8")

script_line = "            scripts/data/refresh_selected_pool_prices_v2.py"
if script_line not in ci:
    raise SystemExit("candidate Ruff refresh marker missing")
ci = ci.replace(
    script_line,
    "            scripts/data/resolve_formal_provider_cutoff.py \\\n" + script_line,
)

test_line = "            tests/test_formal_refresh_trigger_scope.py"
if test_line not in ci:
    raise SystemExit("candidate pytest trigger-scope marker missing")
ci = ci.replace(
    test_line,
    "            tests/test_resolve_formal_provider_cutoff.py \\\n" + test_line,
)

# Insert into every candidate Mypy block, without touching Ruff blocks.
search_from = 0
mypy_blocks = 0
while True:
    try:
        mypy_start = ci.index("          uv run mypy ", search_from)
    except ValueError:
        break
    pytest_start = ci.index("          uv run pytest ", mypy_start)
    block = ci[mypy_start:pytest_start]
    marker = "            scripts/run_formal_refresh_transaction.py"
    if marker not in block:
        raise SystemExit("candidate Mypy transaction marker missing")
    if "scripts/data/resolve_formal_provider_cutoff.py" not in block:
        block = block.replace(
            marker,
            "            scripts/data/resolve_formal_provider_cutoff.py \\\n" + marker,
            1,
        )
        ci = ci[:mypy_start] + block + ci[pytest_start:]
    search_from = mypy_start + len(block)
    mypy_blocks += 1
if mypy_blocks != 2:
    raise SystemExit(f"expected two candidate Mypy blocks, saw {mypy_blocks}")

for required in (
    "scripts/data/resolve_formal_provider_cutoff.py",
    "tests/test_resolve_formal_provider_cutoff.py",
):
    if required not in ci:
        raise SystemExit(f"candidate resolver contract missing: {required}")
ci_path.write_text(ci, encoding="utf-8")
