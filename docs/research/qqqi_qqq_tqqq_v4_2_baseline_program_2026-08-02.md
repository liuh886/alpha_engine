# QQQI / QQQ / TQQQ v4.2 baseline program

**Decision date:** 2026-08-02  
**Current research baseline:** `qqqi_qqq_tqqq_vxn_bridge_v4_2`  
**Historical signal comparator:** `qqqi_qqq_tqqq_vxn_leverage_v4_1`  
**Cost convention:** 10 basis points per turnover unit  
**Status:** research-only; not trade-ready

## 1. Baseline decision

v4.2 is now the current research baseline.

The decision is not based on a claim that v4.2 has a better signal. v4.2 preserves the exact v4.1 decision trace and changes only the lower-confidence state-1 allocation from 100% QQQ to 50% QQQI / 50% QQQ.

The published evidence shows that v4.2:

- reduces turnover from 71 to 55 units;
- reduces cumulative transaction-cost deduction from 7.10% to 5.50%;
- improves total net return from 101.17% to 103.53%;
- improves CAGR, Sharpe, Sortino and Calmar;
- slightly reduces annual volatility and maximum drawdown;
- preserves all state dates and all 129 partial-leverage sessions.

Lower turnover with no loss of net return is treated as an economic advantage. v4.1 remains immutable as the historical signal comparator, but new challengers must use v4.2 as the primary baseline.

This is a research-baseline promotion only. It does not set `trade_ready=true`, erase the post-result origin of v4.2, or waive prospective validation.

## 2. Buy and sell alert architecture

The alert system follows a two-layer design.

### 2.1 Canonical signal record

The v4.2 prospective monitor remains the source of truth. The alert layer reads:

- the latest actually executed position;
- the latest close-derived next-session decision;
- current and target portfolio weights;
- VIX and VXN context;
- the frozen decision reason.

It does not recalculate or modify the strategy signal.

### 2.2 Alert condition

An alert is produced only when:

1. the latest close decision state differs from the latest executed state; and
2. at least one target asset weight changes.

This naturally separates signal time from execution time:

- signal: current US session close;
- intended execution: next US session open.

A deterministic fingerprint contains the experiment, signal date, state transition and target weights. Repeated workflow runs cannot create duplicate GitHub issues for the same signal.

### 2.3 Delivery channels

The primary zero-configuration channel is a GitHub Issue created by the scheduled workflow. The issue mentions `@liuh886` and includes:

- transition type;
- current and target states;
- explicit BUY / SELL weight changes;
- decision reason;
- VIX / VXN context;
- research-only disclaimer;
- hidden deduplication fingerprint.

An optional Telegram channel is supported when these repository secrets are configured:

- `TELEGRAM_BOT_TOKEN`;
- `TELEGRAM_CHAT_ID`.

GitHub remains the durable audit trail even when Telegram is enabled.

### 2.4 Schedule

The alert workflow runs at `00:30 UTC` from Tuesday through Saturday, after the prior US session close and expected end-of-day data availability. Manual dispatch with an optional data end date is also supported.

The alert system does not place orders.

## 3. Experiment A — actual state-1 lifecycle attribution

The earlier fixed-horizon event study is insufficient because the strategy may leave state 1 before 5, 10, 20 or 40 sessions have elapsed.

The lifecycle study therefore measures each actual contiguous state-1 interval and classifies it by entry and exit path:

- `0->1->2`: defensive reserve to bridge to confirmed leveraged recovery;
- `0->1->0`: attempted recovery that returns to defense;
- `2->1->2`: temporary deleveraging followed by renewed recovery;
- `2->1->0`: deleveraging that proceeds to full defense;
- other boundary cases where the sample begins or ends in state 1.

For every interval it records:

- actual holding sessions;
- gross and net return;
- maximum drawdown;
- maximum favourable and adverse excursion;
- turnover and transaction cost;
- v4.2 minus v4.1 return difference;
- turnover and cost saved by v4.2.

The objective is to determine whether v4.2 is most valuable in failed recovery attempts, successful recovery bridges, or both.

## 4. Experiment B — tail-risk and drawdown diagnosis

Headline maximum drawdown is not sufficient. The baseline diagnostic suite additionally records:

- worst daily return;
- 5% daily return quantile;
- 95% expected shortfall;
- worst compounded 5-, 10- and 20-session returns;
- maximum drawdown peak, trough and recovery dates;
- maximum drawdown recovery duration;
- longest underwater run;
- ulcer index;
- state-conditioned worst returns and negative-session rates.

A later risk-control challenger should be judged primarily on tail-depth and drawdown-duration improvement, with CAGR and risk-adjusted return as guardrails.

## 5. Experiment C — SGOV defensive architecture

Two and only two SGOV structures are predeclared. No SGOV weight grid is allowed.

### Current v4.2 baseline

- state 0: 100% QQQI;
- state 1: 50% QQQI / 50% QQQ;
- state 2: 25% QQQ / 75% TQQQ.

### Pure SGOV defense

- state 0: 100% SGOV;
- state 1: 50% SGOV / 50% QQQ;
- state 2: unchanged at 25% QQQ / 75% TQQQ.

### Blended QQQI / SGOV defense

- state 0: 50% QQQI / 50% SGOV;
- state 1: 25% QQQI / 25% SGOV / 50% QQQ;
- state 2: unchanged at 25% QQQ / 75% TQQQ.

All three portfolios use:

- the exact same v4.2 state trace;
- the same next-open execution convention;
- the same 10 bps transaction-cost assumption;
- the same TQQQ leverage allocation;
- a common tradable sample without synthetic pre-inception data.

Primary objectives are maximum drawdown, expected shortfall, underwater duration and ulcer index. CAGR, Sharpe, Sortino and Calmar are return guardrails. No result is promoted automatically.

## 6. Evidence and notebook

The experiment workflow produces:

- lifecycle episode and lifecycle summary CSV files;
- tail-risk comparison CSV and JSON files;
- SGOV daily traces, trades, headline metrics and chronological metrics;
- evidence manifests and contract hashes;
- an executed notebook:
  `notebooks/18_qqqi_qqq_tqqq_v4_2_baseline_experiment_suite.ipynb`.

The notebook must display the actual lifecycle rows, headline and tail metrics, SGOV equity curves and drawdown curves. It remains research-only.

## 7. Decision sequence

1. Validate the daily alert workflow and delivery audit trail.
2. Run state-1 lifecycle and tail-risk diagnostics on the frozen v4.2 baseline.
3. Run the two predeclared SGOV structures.
4. Reject any candidate whose apparent benefit comes from a changed signal trace or changed cost convention.
5. Compare early and late chronological segments.
6. Preserve all evidence and update the experiment notebook.
7. Only after retrospective evidence is complete, decide whether one SGOV structure deserves prospective monitoring as a named challenger.
