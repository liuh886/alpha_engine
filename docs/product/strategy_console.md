# Alpha Engine Strategy Console

Status: active frontend product direction.

## Product position

Alpha Engine is a governed medium-frequency systematic strategy research and monitoring system. Python pipelines remain authoritative for data, factor materialization, model research, formal backtests, reviewed refresh and signal production. The public PWA remains read-only and does not train models, mutate registries, connect to brokers or execute orders.

The frontend is organized around the **formal strategy** rather than repository subsystems.

## Primary user questions

The first scan should answer:

1. Is the strategy's operating evidence current and usable?
2. What is the current governed state or allocation?
3. What is the next target and what changed?
4. When will the strategy evaluate again?
5. Why did the current decision occur?
6. How has the formal strategy performed relative to its benchmark and risk contract?
7. Which holdings, trades, drivers and evidence support that conclusion?

## Information architecture

Only four product-level destinations are navigation-visible:

- **Overview** — Strategy Fleet: current state, target, change, next decision, risk and operating status.
- **Strategies** — accepted formal baselines and strategy-level drill-down.
- **Research** — runs, comparisons, decisions, factors, reports and notebooks used to evolve formal strategies.
- **System** — data lineage, freshness, local bundles and methodology.

Backtests, review, compare, data, factors, reports and library remain valid analytical routes but are drill-down surfaces rather than top-level products.

## Strategy workspace

A strategy workspace follows one reading order:

`Now -> Performance / Risk / Holdings / Trades / Attribution -> Drivers -> Evidence`

Current operating evidence must never be reconstructed from a historical backtest. If a formal model lacks a governed signal publication pipeline, the frontend explicitly reports `pipeline_unavailable` while keeping formal historical evidence readable.

## Operations contract

The frontend consumes one `StrategyOperationsSnapshot` shape across model kinds. The minimum semantic fields are:

- strategy/model identity;
- operational status;
- signal/as-of date and latest completed session;
- decision cadence and next decision;
- current and target holdings with deltas;
- turnover and estimated cost when retained;
- data freshness, factor freshness and delivery status;
- decision state/reason;
- current signal drivers;
- source record identity/link.

Current statuses are intentionally small and explicit:

- `pipeline_unavailable`
- `awaiting_observation`
- `current_no_change`
- `target_pending_execution`
- `execution_observed`
- `stale`
- `blocked`
- `delivery_failed`

QQQ Rotation v4.2 and BYD v1.2 currently adapt their governed public ledgers into this contract. US x1.1 and CN x1.1 remain `pipeline_unavailable` until Issue #600 publishes their governed 10-session signals. The UI does not invent live holdings from their formal backtests.

## Evidence architecture

Three durable evidence families form the frontend boundary:

1. **Formal Model Run Bundle v2** — historical performance, risk, portfolio, trades, attribution, robustness and lineage.
2. **Strategy operations evidence** — current state, targets, changes and operational status.
3. **Research receipts** — hypothesis, immutable identities, evaluated windows, gates, verdict and learning.

Issue #626 adds canonical factor evidence across those boundaries. Factor definitions remain versioned research code; factor observations refresh at the exact model cutoff. Stale/missing required factor observations must block a fresh signal explanation rather than silently reusing old values.

## Visualization rules

The console is an operational analytical workspace, not a KPI card gallery.

- Current state is the dominant viewport.
- Strategy Fleet uses aligned rows for peer scanning rather than equal-weight cards.
- Holdings use tables because leveraged and negative-cash weights make clipped progress bars misleading.
- Performance uses strategy/benchmark/excess traces with drawdown and robustness available nearby.
- Status, freshness and last-updated context stay adjacent to the evidence they qualify.
- Mobile keeps the current decision before filters and analytical depth.
- Essential values are visible without hover.

## Runtime boundary

The public product remains:

- static GitHub Pages/PWA;
- read-only;
- no broker integration;
- no browser-side training;
- no hidden model promotion;
- fail-closed on invalid formal Bundle v2 evidence;
- explicit when current operating evidence is absent, stale or blocked.

`research_only=true` and `trade_ready=false` remain mandatory formal evidence boundaries.
