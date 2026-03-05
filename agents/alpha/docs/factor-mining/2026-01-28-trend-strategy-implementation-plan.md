# Trend Strategy Sell Rules Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add biweekly rebalance + min-hold + MA60 + Top20 sell rules to the Qlib backtest strategy and refresh the dashboard output.

**Architecture:** Implement a custom Qlib strategy (based on BaseSignalStrategy) that enforces rebalance cadence, min hold (calendar days), MA60 trend sell, and rank-based sell. Wire it into workflow configs via `strategy_profile.json` and `scripts/strategy_to_workflow.py`, then re-run the pipeline and dashboard extraction/build.

**Tech Stack:** Python (qlib), YAML/JSON configs, pytest, Node/Vite for dashboard build.

---

### Task 1: Add unit tests for biweekly rule helpers

**Files:**
- Create: `100_Project/2601_Trading/tests/test_biweekly_trend_rules.py`

**Step 1: Write the failing test**

```python
from datetime import date
from src.strategies.biweekly_trend_rules import is_rebalance_day, can_sell


def test_is_rebalance_day_every_10_steps():
    assert is_rebalance_day(0, 10)
    assert not is_rebalance_day(1, 10)
    assert is_rebalance_day(10, 10)


def test_can_sell_min_hold_calendar_days():
    entry = date(2025, 1, 1)
    assert not can_sell(entry, date(2025, 1, 10), 10)  # 9 days elapsed
    assert can_sell(entry, date(2025, 1, 11), 10)      # 10 days elapsed
```

**Step 2: Run test to verify it fails**

Run: `pytest 100_Project/2601_Trading/tests/test_biweekly_trend_rules.py -v`
Expected: FAIL with “module not found” or missing functions.

**Step 3: Write minimal implementation**

Create `100_Project/2601_Trading/src/strategies/biweekly_trend_rules.py`:

```python
from datetime import date


def is_rebalance_day(trade_step: int, rebalance_steps: int) -> bool:
    if rebalance_steps <= 0:
        return True
    return trade_step % rebalance_steps == 0


def can_sell(entry_date: date, current_date: date, min_hold_days: int) -> bool:
    if not entry_date or not current_date:
        return True
    delta = (current_date - entry_date).days
    return delta >= min_hold_days
```

**Step 4: Run test to verify it passes**

Run: `pytest 100_Project/2601_Trading/tests/test_biweekly_trend_rules.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add 100_Project/2601_Trading/tests/test_biweekly_trend_rules.py 100_Project/2601_Trading/src/strategies/biweekly_trend_rules.py
git commit -m "test: add biweekly rule helpers"
```

---

### Task 2: Implement custom Qlib strategy with biweekly + MA60 + Top20 sells

**Files:**
- Create: `100_Project/2601_Trading/src/strategies/biweekly_trend_strategy.py`

**Step 1: Write the failing test**

```python
from src.strategies.biweekly_trend_strategy import BiweeklyTrendStrategy


def test_strategy_class_loadable():
    assert BiweeklyTrendStrategy is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest 100_Project/2601_Trading/tests/test_biweekly_trend_rules.py -k strategy -v`
Expected: FAIL import error

**Step 3: Write minimal implementation**

Implement `BiweeklyTrendStrategy` using `BaseSignalStrategy` with:
- params: `topk`, `rebalance_steps`, `min_hold_days`, `sell_ma_window`, `sell_rank_threshold`
- internal `entry_dates: dict[str, date]` updated on buy
- rebalance check via `is_rebalance_day`
- daily sell on MA60 (if holding period satisfied)
- sell on rebalance day when rank falls out of Top20
- buy on rebalance day to fill Top5
- use `D.features([...], ["$close", "Mean($close, 60)"])` for MA60 data

**Step 4: Run test to verify it passes**

Run: `pytest 100_Project/2601_Trading/tests/test_biweekly_trend_rules.py -k strategy -v`
Expected: PASS

**Step 5: Commit**

```bash
git add 100_Project/2601_Trading/src/strategies/biweekly_trend_strategy.py
git commit -m "feat: biweekly trend strategy"
```

---

### Task 3: Wire strategy params into strategy_profile + workflow compiler

**Files:**
- Modify: `100_Project/2601_Trading/configs/strategy_profile.json`
- Modify: `100_Project/2601_Trading/scripts/strategy_to_workflow.py`

**Step 1: Write the failing test**

```python
import json
from pathlib import Path


def test_strategy_profile_has_biweekly_rules():
    profile = json.loads(Path("100_Project/2601_Trading/configs/strategy_profile.json").read_text())
    s = profile.get("strategy", {})
    assert s.get("rebalance_frequency") == "biweekly"
    assert s.get("min_hold_days") == 10
    assert s.get("sell_on_ma") == 60
    assert s.get("sell_rank_threshold") == 20
```

**Step 2: Run test to verify it fails**

Run: `pytest 100_Project/2601_Trading/tests/test_biweekly_trend_rules.py -k profile -v`
Expected: FAIL on missing keys

**Step 3: Implement minimal changes**

- Add fields to `strategy_profile.json`:
  - `rebalance_frequency: "biweekly"`
  - `min_hold_days: 10`
  - `sell_on_ma: 60`
  - `sell_rank_threshold: 20`
- Update `strategy_to_workflow.py` to emit:
  - `port_analysis_config.strategy.class = BiweeklyTrendStrategy`
  - `port_analysis_config.strategy.module_path = src.strategies.biweekly_trend_strategy`
  - `port_analysis_config.strategy.kwargs` set from strategy profile

**Step 4: Run test to verify it passes**

Run: `pytest 100_Project/2601_Trading/tests/test_biweekly_trend_rules.py -k profile -v`
Expected: PASS

**Step 5: Commit**

```bash
git add 100_Project/2601_Trading/configs/strategy_profile.json 100_Project/2601_Trading/scripts/strategy_to_workflow.py
git commit -m "feat: wire biweekly trend rules into workflow"
```

---

### Task 4: Regenerate workflow configs

**Files:**
- Modify: `100_Project/2601_Trading/configs/us_lgbm_workflow.yaml`
- Modify: `100_Project/2601_Trading/configs/cn_lgbm_workflow.yaml`

**Step 1: Run compiler**

Run:
```
python 100_Project/2601_Trading/scripts/strategy_to_workflow.py --market us
python 100_Project/2601_Trading/scripts/strategy_to_workflow.py --market cn
```
Expected: workflow files updated with new strategy class and kwargs.

**Step 2: Commit**

```bash
git add 100_Project/2601_Trading/configs/us_lgbm_workflow.yaml 100_Project/2601_Trading/configs/cn_lgbm_workflow.yaml
git commit -m "chore: regenerate workflow configs"
```

---

### Task 5: Run backtests and refresh dashboard data

**Files:**
- Modify: `100_Project/2601_Trading/mlruns/...`
- Modify: `100_Project/2601_Trading/artifacts/dashboard/dashboard_db.json`
- Modify: `100_Project/2601_Trading/qlib-dashboard/dist/index.html`

**Step 1: Run pipeline**

Run:
```
python 100_Project/2601_Trading/src/orchestrator.py run --market cn --model_type lgbm
python 100_Project/2601_Trading/src/orchestrator.py run --market us --model_type lgbm
```
Expected: new runs in `artifacts/dashboard/dashboard_db.json` after extraction

**Step 2: Extract dashboard data**

Run:
```
python 100_Project/2601_Trading/scripts/build_dashboard_db.py
```
Expected: `artifacts/dashboard/dashboard_db.json` updated

**Step 3: Build dashboard**

Run:
```
cd 100_Project/2601_Trading/qlib-dashboard
npm run build
```
Expected: `qlib-dashboard/dist/index.html` updated

**Step 4: Commit**

```bash
git add 100_Project/2601_Trading/artifacts/dashboard/dashboard_db.json 100_Project/2601_Trading/qlib-dashboard/dist/index.html
git commit -m "chore: refresh dashboard data"
```

---

## Verification Checklist
- All new tests pass.
- Strategy class is referenced in workflow configs.
- New backtest runs appear in `artifacts/dashboard/dashboard_db.json`.
- Dashboard displays updated model params and turnover reduction.
