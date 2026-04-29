---
path: 100_Project/2601_Trading/agents/alpha/docs/factor-mining/2026-01-28-strategy-discovery-implementation-plan.md
title: Strategy Discovery Implementation Plan
date: 2026-01-28
owner_project: 100_Project/2601_Trading
status: archived
---

> Historical implementation plan migrated from root `docs/` on 2026-02-24.
> For current system behavior and active priorities, use `100_Project/2601_Trading/README.md`.

# Strategy Discovery Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the CN+US strategy discovery baseline (Alpha158 + Feature Pack A, h=10, Top5, 10-day rebalance, 2021-2024 train / 2025 validate) with auto-updated dashboard outputs.

**Architecture:** Use `configs/strategy_profile.json` as the single source of truth; compile into `configs/*_lgbm_workflow.yaml` via `scripts/strategy_to_workflow.py`; orchestrator runs pipeline; extractor writes meta for dashboard. Add minimal tests around the profile-to-workflow compiler.

**Tech Stack:** Python (Qlib), YAML/JSON configs, pytest for tests.

---

### Task 1: Add failing tests for strategy profile compilation

**Files:**
- Create: `tests/test_strategy_discovery_profile.py`

**Step 1: Write the failing test**

```python
from pathlib import Path
import yaml
from scripts.strategy_to_workflow import apply_profile_to_config

def test_profile_compiles_discovery_defaults(tmp_path):
    profile = {
        "meta": {"benchmark": "QQQ"},
        "model": {
            "class": "LGBModel",
            "feature_pack": "alpha158",
            "extra_features": [
                "$close/Ref($close, 5)-1",
                "$close/Ref($close, 10)-1",
                "$close/Ref($close, 20)-1",
                "Std($close, 10)",
                "$volume/Ref($volume, 10)-1",
            ],
            "label": ["Ref($close, -10) / Ref($close, -1) - 1"],
            "train_window": {
                "train": ["2021-01-01", "2024-12-31"],
                "valid": ["2025-01-01", "2025-12-31"],
                "test": ["2025-01-01", "2025-12-31"],
            },
        },
        "strategy": {
            "position_rule": {"topk": 5, "n_drop": 5},
            "costs_bps": 10,
            "capital": 10000,
            "backtest_window": ["2025-01-01", "2025-12-31"],
        },
    }
    base = {
        "task": {
            "dataset": {
                "kwargs": {
                    "handler": {"kwargs": {}}
                }
            }
        },
        "port_analysis_config": {"strategy": {"kwargs": {}}, "backtest": {}},
    }
    cfg = apply_profile_to_config(profile, base, "us")

    handler = cfg["task"]["dataset"]["kwargs"]["handler"]
    assert handler.get("class") == "Alpha158"
    assert handler["kwargs"]["label"] == ["Ref($close, -10) / Ref($close, -1) - 1"]
    assert handler["kwargs"]["extra_features"] == profile["model"]["extra_features"]

    strat = cfg["port_analysis_config"]["strategy"]["kwargs"]
    assert strat["topk"] == 5
    assert strat["n_drop"] == 5
    assert cfg["port_analysis_config"]["backtest"]["start_time"] == "2025-01-01"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_strategy_discovery_profile.py -v`  
Expected: FAIL (Alpha158/extra feature wiring not implemented yet)

**Step 3: Commit**

```bash
git add tests/test_strategy_discovery_profile.py
git commit -m "test: add discovery profile compiler tests"
```

---

### Task 2: Update strategy profile defaults for discovery

**Files:**
- Modify: `configs/strategy_profile.json`

**Step 1: Write a failing test (if needed)**

Extend the test above to assert the defaults match the design (topk=5, h=10, backtest window 2025).

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_strategy_discovery_profile.py -v`  
Expected: FAIL (profile defaults not yet updated)

**Step 3: Update config**

Update `configs/strategy_profile.json` to:
- `model.feature_pack = "alpha158"`
- `model.extra_features = [ret_5d, ret_10d, ret_20d, vol_10d, vol_chg_10d]`
- `model.label = ["Ref($close, -10) / Ref($close, -1) - 1"]`
- `model.train_window`: train 2021-01-01 → 2024-12-31, valid/test 2025-01-01 → 2025-12-31
- `strategy.position_rule.topk = 5`
- `strategy.costs_bps = 10`
- `strategy.backtest_window = ["2025-01-01", "2025-12-31"]`

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_strategy_discovery_profile.py -v`  
Expected: PASS

**Step 5: Commit**

```bash
git add configs/strategy_profile.json
git commit -m "feat: set discovery defaults in strategy profile"
```

---

### Task 3: Wire Alpha158 + Feature Pack A in compiler

**Files:**
- Modify: `scripts/strategy_to_workflow.py`

**Step 1: Write failing test**

Use the existing test in Task 1 (it already checks Alpha158 + extra features).

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_strategy_discovery_profile.py -v`  
Expected: FAIL

**Step 3: Implement minimal changes**

Update `apply_profile_to_config` to:
- Support `model.feature_pack == "alpha158"`:
  - Set handler `class` to `Alpha158` and `module_path` to `qlib.contrib.data.handler`
  - Move label into `handler_kwargs["label"]`
  - Store custom features in `handler_kwargs["extra_features"]`
- If `feature_pack` is not alpha158, keep the existing DataHandlerLP + `data_loader` wiring
- If `meta.benchmark` missing, set defaults per market (`cn=000300`, `us=QQQ`)

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_strategy_discovery_profile.py -v`  
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/strategy_to_workflow.py
git commit -m "feat: support alpha158 feature pack in workflow compiler"
```

---

### Task 4: Align workflow templates with discovery defaults

**Files:**
- Modify: `configs/cn_lgbm_workflow.yaml`
- Modify: `configs/us_lgbm_workflow.yaml`

**Step 1: Write failing test (optional)**

If needed, add a small test to ensure template defaults match the profile (topk=5, benchmark, label h=10).

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_strategy_discovery_profile.py -v`  
Expected: FAIL (if added)

**Step 3: Update templates**

Set:
- handler class to Alpha158 (if switching away from DataHandlerLP)
- label horizon to h=10
- topk=5, n_drop=5
- backtest window 2025
- benchmark: CN=000300, US=QQQ

**Step 4: Run tests to verify pass**

Run: `pytest tests/test_strategy_discovery_profile.py -v`  
Expected: PASS

**Step 5: Commit**

```bash
git add configs/cn_lgbm_workflow.yaml configs/us_lgbm_workflow.yaml
git commit -m "chore: align lgbm templates with discovery defaults"
```

---

### Task 5: Update diagnostics + dashboard meta expectations

**Files:**
- Modify: `scripts/check_features.py`
- Modify: `scripts/extract_backtest_sample.py` (only if meta fields missing)

**Step 1: Write failing test**

Add a test to assert `extract_backtest_sample` includes `meta.label`, `meta.features`, and `meta.benchmark` for each model entry.

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_strategy_discovery_profile.py -v`  
Expected: FAIL

**Step 3: Implement minimal changes**

Update diagnostics to include Feature Pack A checks; ensure extractor uses the new meta fields (feature_pack/extra_features).

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_strategy_discovery_profile.py -v`  
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/check_features.py scripts/extract_backtest_sample.py
git commit -m "chore: update diagnostics and meta for discovery profile"
```

---

### Task 6: Update documentation

**Files:**
- Modify: `100_Project/2601_Trading/README.md`

**Step 1: Update docs**

Add a brief section describing the discovery baseline (Alpha158 + Pack A, h=10, Top5, 2021-2024 train / 2025 validation, benchmark rules).

**Step 2: Commit**

```bash
git add 100_Project/2601_Trading/README.md
git commit -m "docs: document strategy discovery baseline"
```

---

**Note:** If the repository is not initialized with git, skip commit steps or initialize a repo first.
