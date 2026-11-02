"""Tests for server-side publisher safety invariants and snapshot pruning guards."""

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


def _extract_edge_function_constants() -> tuple[dict[str, str], list[str]]:
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

    # Extract RETIRED_ALLOWLIST_STRATEGY_IDS
    retired_match = re.search(
        r"export const RETIRED_ALLOWLIST_STRATEGY_IDS:\s*readonly\s*string\[\]\s*=\s*\[([^\]]+)\];",
        text,
    )
    assert retired_match, "RETIRED_ALLOWLIST_STRATEGY_IDS not found in handler.ts"
    retired_block = retired_match.group(1)
    retired = [
        item.strip().strip('"').strip("'")
        for item in retired_block.split(",")
        if item.strip()
    ]
    return authorized, retired


def _simulate_validator(records: list[dict[str, Any]]) -> tuple[bool, str]:
    """Pure Python simulation of the Edge Function pre-mutation validator."""
    authorized, _ = _extract_edge_function_constants()
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
    authorized, retired = _extract_edge_function_constants()

    # Must exactly equal the active catalog
    assert authorized == catalog_active, (
        f"Edge Function authorized strategies mismatch: {authorized} vs {catalog_active}"
    )

    # Retired allowlist must NOT intersect with any active strategy
    intersection = set(retired) & set(authorized.keys())
    assert not intersection, f"Retired allowlist intersects with active strategies: {intersection}"

    # cn_x must be in retired allowlist
    assert "cn_x" in retired, "cn_x must be declared in RETIRED_ALLOWLIST_STRATEGY_IDS"


def test_edge_function_entrypoint_imports_handler() -> None:
    index_text = EDGE_INDEX_PATH.read_text(encoding="utf-8")
    assert 'import { createPublishHandler } from "./handler.ts";' in index_text
    assert "createPublishHandler(" in index_text
    assert "Deno.serve(handler);" in index_text


def test_edge_function_rejects_partial_records_before_mutation() -> None:
    authorized, _ = _extract_edge_function_constants()

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
    authorized, _ = _extract_edge_function_constants()
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
    authorized, _ = _extract_edge_function_constants()
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


def test_prune_logic_in_edge_function_only_targets_retired_allowlist() -> None:
    text = EDGE_HANDLER_PATH.read_text(encoding="utf-8")

    # Must NOT contain unsafe blind prune: delete().not("strategy_id", "in", ...)
    assert '.not("strategy_id", "in"' not in text, (
        "Unsafe blind prune detected! delete().not('strategy_id', 'in', ...) can delete active strategies."
    )

    # Must use explicit allowlist prune: delete().in("strategy_id", [...RETIRED_ALLOWLIST_STRATEGY_IDS])
    assert '.in("strategy_id", [...RETIRED_ALLOWLIST_STRATEGY_IDS])' in text, (
        "Prune must strictly target allowlisted retired strategy IDs."
    )


def test_native_node_handler_suite_passes() -> None:
    node_bin = shutil.which("node")
    assert node_bin, "node executable not found on system PATH"
    cmd = [node_bin, "--test", "tests/test_publish_strategy_operations_handler.test.ts"]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert proc.returncode == 0, f"Node test suite failed:\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert "pass 8" in proc.stdout, f"Expected 8 passing tests in node output:\n{proc.stdout}"
