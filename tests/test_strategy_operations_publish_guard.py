"""Tests for server-side publisher safety invariants and retained-evidence guards."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path("configs/strategies/registry.json")
EDGE_HANDLER_PATH = Path("supabase/functions/alpha-engine-publish-strategy-operations/handler.ts")
EDGE_INDEX_PATH = Path("supabase/functions/alpha-engine-publish-strategy-operations/index.ts")


def _extract_edge_function_constants() -> dict[str, str]:
    """Extract the active strategy allowlist from the Edge Function handler."""
    text = EDGE_HANDLER_PATH.read_text(encoding="utf-8")

    # Extract AUTHORIZED_ACTIVE_STRATEGIES
    active_match = re.search(
        r"export const AUTHORIZED_ACTIVE_STRATEGIES:\s*Record<string,\s*string>\s*=\s*\{([^}]+)\};",
        text,
    )
    assert active_match, "AUTHORIZED_ACTIVE_STRATEGIES not found in handler.ts"
    active_block = active_match.group(1)
    authorized: dict[str, str] = {}
    for line in active_block.strip().splitlines():
        line = line.strip().rstrip(",")
        if ":" in line:
            k, v = line.split(":", 1)
            authorized[k.strip().strip('"').strip("'")] = v.strip().strip('"').strip("'")
    return authorized


def _simulate_validator(records: list[dict[str, Any]]) -> tuple[bool, str]:
    """Pure Python simulation of the Edge Function pre-mutation validator."""
    authorized = _extract_edge_function_constants()
    expected_count = len(authorized)
    if not records or len(records) == 0:
        return False, "strategy operations records are required"
    if len(records) != expected_count:
        return False, f"exact {expected_count} active strategy records required; received {len(records)}"

    strategy_ids: set[str] = set()
    model_version_ids: set[str] = set()
    for record in records:
        sid = record.get("strategy_id")
        mvid = record.get("model_version_id")
        if not sid or not isinstance(sid, str):
            return False, "strategy_id must be a non-empty string"
        if not mvid or not isinstance(mvid, str):
            return False, "model_version_id must be a non-empty string"

        expected_model = authorized.get(sid)
        if not expected_model:
            return False, f"unauthorized strategy_id: {sid}"
        if mvid != expected_model:
            return False, f"model_version_id mismatch for {sid}: expected {expected_model}, received {mvid}"

        if sid in strategy_ids:
            return False, f"duplicate strategy_id: {sid}"
        if mvid in model_version_ids:
            return False, f"duplicate model_version_id: {mvid}"
        strategy_ids.add(sid)
        model_version_ids.add(mvid)

    for expected_id in authorized:
        if expected_id not in strategy_ids:
            return False, f"missing authorized active strategy: {expected_id}"

    return True, "ok"


def test_edge_function_constants_match_active_catalog() -> None:
    registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    catalog_active = {s["strategy_id"]: s["model_version_id"] for s in registry["strategies"]}
    authorized = _extract_edge_function_constants()

    # Must exactly equal the active catalog
    assert authorized == catalog_active, (
        f"Edge Function authorized strategies mismatch: {authorized} vs {catalog_active}"
    )


def test_edge_function_entrypoint_imports_handler() -> None:
    index_text = EDGE_INDEX_PATH.read_text(encoding="utf-8")
    assert 'import { createPublishHandler } from "./handler.ts";' in index_text
    assert "createPublishHandler(" in index_text
    assert "Deno.serve(handler);" in index_text


def test_edge_function_rejects_partial_records_before_mutation() -> None:
    authorized = _extract_edge_function_constants()

    # Full valid 4 records
    valid_records = [
        {"strategy_id": sid, "model_version_id": mvid}
        for sid, mvid in authorized.items()
    ]
    ok, msg = _simulate_validator(valid_records)
    assert ok, f"Valid 4-record payload failed: {msg}"

    # Partial: 3 records (omitting byd)
    partial_3 = [r for r in valid_records if r["strategy_id"] != "byd"]
    ok, msg = _simulate_validator(partial_3)
    assert not ok
    assert "exact 4 active strategy records required; received 3" in msg

    # Partial: 1 record
    partial_1 = [valid_records[0]]
    ok, msg = _simulate_validator(partial_1)
    assert not ok
    assert "exact 4 active strategy records required; received 1" in msg


def test_edge_function_rejects_surplus_or_unknown_records() -> None:
    authorized = _extract_edge_function_constants()
    valid_records = [
        {"strategy_id": sid, "model_version_id": mvid}
        for sid, mvid in authorized.items()
    ]

    # Surplus: 5 records (including an extra unknown strategy)
    surplus = valid_records + [{"strategy_id": "extra_strat", "model_version_id": "v1"}]
    ok, msg = _simulate_validator(surplus)
    assert not ok
    assert "exact 4 active strategy records required; received 5" in msg

    # 4 records, but one replaced by retired cn_x
    replaced = [r for r in valid_records if r["strategy_id"] != "cn_27"] + [
        {"strategy_id": "cn_x", "model_version_id": "cn_x1_2"}
    ]
    ok, msg = _simulate_validator(replaced)
    assert not ok
    assert "unauthorized strategy_id: cn_x" in msg


def test_edge_function_rejects_model_version_mismatch() -> None:
    authorized = _extract_edge_function_constants()
    valid_records = [
        {"strategy_id": sid, "model_version_id": mvid}
        for sid, mvid in authorized.items()
    ]

    # cn_27 with old cn_x1_2 model version
    mismatched = [
        r if r["strategy_id"] != "cn_27" else {"strategy_id": "cn_27", "model_version_id": "cn_x1_2"}
        for r in valid_records
    ]
    ok, msg = _simulate_validator(mismatched)
    assert not ok
    assert "model_version_id mismatch for cn_27" in msg


def test_edge_function_never_prunes_retained_retired_evidence() -> None:
    text = EDGE_HANDLER_PATH.read_text(encoding="utf-8")

    # Retained retired evidence is denied by the restrictive RLS allowlist and
    # must never be deleted as a publisher side effect.
    assert "RETIRED_ALLOWLIST_STRATEGY_IDS" not in text
    assert ".delete(" not in text
    assert '.not("strategy_id", "in"' not in text
    assert ".upsert(rows" in text
    assert 'onConflict: "strategy_id"' in text


def test_native_node_handler_suite_passes() -> None:
    node_bin = shutil.which("node")
    assert node_bin, "node executable not found on system PATH"
    cmd = [node_bin, "--test", "tests/test_publish_strategy_operations_handler.test.ts"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"Node test suite failed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    tests_match = re.search(r" tests (\d+)", proc.stdout)
    pass_match = re.search(r" pass (\d+)", proc.stdout)
    fail_match = re.search(r" fail (\d+)", proc.stdout)
    assert tests_match and pass_match and fail_match, f"Missing node test summary:\n{proc.stdout}"
    total = int(tests_match.group(1))
    assert int(pass_match.group(1)) == total, f"Not all node tests passed:\n{proc.stdout}"
    assert int(fail_match.group(1)) == 0, f"Node test failures:\n{proc.stdout}"
    # Floor preserves current security coverage; adding tests is fine, but
    # removing one requires an explicit review of this guard.
    assert total >= 12, f"Node security suite shrank to {total} tests:\n{proc.stdout}"
