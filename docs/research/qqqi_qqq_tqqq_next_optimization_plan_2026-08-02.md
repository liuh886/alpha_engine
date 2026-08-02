# QQQI / QQQ / TQQQ next optimization plan

**Decision date:** 2026-08-02  
**Current baseline:** v4.2 50/50 confidence bridge  
**Frozen cost:** 10 bps per turnover unit  
**Status:** research program; no candidate is trade-ready

## Executive decision

v4.2 remains the best current all-purpose research baseline.

It has the best combination of:

- net CAGR among the retained executable structures;
- lower turnover than v4.1;
- improved Sharpe, Sortino and Calmar;
- unchanged signal dates and unchanged state-2 exposure;
- a simple explanation: state 1 is a lower-confidence bridge.

The blended QQQI / SGOV structure is not a replacement. It is a separate drawdown-focused challenger because it improves loss depth but reduces CAGR and materially lengthens the underwater period.

The next optimization should not be another bridge-weight, SGOV-weight, VIX, VXN or MA threshold search.

## What the completed experiments established

### v4.2 is an allocation-efficiency improvement

The state-1 lifecycle attribution shows:

- failed recovery `0→1→0`: v4.2 improved mean net return by 0.275 percentage points and won 80% of episodes;
- fast successful recovery `0→1→2`: v4.2 gave up 0.257 percentage points on average;
- temporary deleveraging `2→1→2`: v4.2 produced a small positive improvement.

Therefore v4.2 reduces false-recovery cost without claiming better timing.

### The remaining tail problem is state 2

v4.2 does not improve the worst day or worst five-session loss because state 2 is unchanged:

```text
25% QQQ + 75% TQQQ
```

Further state-1 fitting cannot solve the principal drawdown source.

### SGOV changes the type of risk

The blended QQQI / SGOV challenger:

- reduces maximum drawdown from about -24.22% to -17.91%;
- improves expected shortfall and risk-adjusted ratios;
- lowers CAGR from about 33.06% to 29.54%;
- increases the longest underwater run from 113 to 195 sessions.

This is a genuine preference trade-off: lower loss depth versus slower capital recovery.

## Ordered research sequence

## Phase 1 — evidence and execution robustness

Complete these diagnostics before creating another economic challenger.

### 1. State-2 tail-event decomposition

For every worst state-2 episode, measure:

- entry date and trigger;
- days from entry to trough;
- open-to-open loss;
- overnight close-to-open component where reliable OHLC data permit;
- VIX and VXN path before entry and before exit;
- QQQ distance from MA20/50/200;
- whether the loss was an abrupt gap or a sustained high-volatility decline;
- exit lag and loss avoided after exit;
- episode contribution to total maximum drawdown and expected shortfall.

Decision value:

- if losses are mostly abrupt gaps, a daily close-based volatility scaler may not help;
- if losses build during observable high volatility, continuous risk budgeting may be justified.

### 2. Execution sensitivity without changing headline costs

Keep 10 bps as the official assumption. Run robustness-only diagnostics for:

- one-session delayed execution;
- opening-price slippage stress;
- missed execution and re-entry at the following open;
- provider-date mismatch;
- QQQI distribution/corporate-action reconciliation.

These are robustness checks, not optimization inputs.

### 3. SGOV episode attribution

For the blended challenger, identify why underwater duration increases:

- lower participation during successful recovery;
- particular state-0 or state-1 intervals;
- concentration in one market episode;
- SGOV data or distribution effects.

Do not search another SGOV weight.

## Phase 2 — one admissible state-2 challenger

Only proceed if Phase 1 shows that state-2 losses are sufficiently gradual and observable.

The preferred hypothesis is a **continuous volatility-budgeted state-2 overlay**, because it addresses the identified risk source without changing entry/exit dates.

Predeclared design principles:

- preserve the exact v4.2 decision trace;
- preserve states 0 and 1;
- replace the fixed state-2 risk amount with one continuous ex-ante volatility budget;
- use one declared volatility estimator and one declared target;
- do not run a target grid;
- do not add a new binary veto;
- keep the 10 bps convention;
- compare gross and net attribution;
- reject if improvement is concentrated in one episode or if return sacrifice is disproportionate.

This experiment should not begin until its target and estimator are justified independently of the current sample.

## Phase 3 — prospective comparison

The monitoring set should remain small:

1. v4.2 current baseline;
2. v4.1 historical signal comparator;
3. blended QQQI / SGOV challenger only after its monitor contract is frozen;
4. one state-2 volatility-budget challenger only if Phase 1 authorizes it.

No automatic promotion is allowed.

## Explicitly excluded directions

The following are currently inadmissible:

- alternative 50/50 bridge weights;
- alternative SGOV percentages;
- another VIX or VXN threshold;
- another MA period or persistence count;
- another fixed TQQQ weight search;
- reintroducing rejected breadth, downside-volatility or credit hard gates;
- selecting a rule only because it reduces maximum drawdown in the same sample.

## Promotion framework

A challenger may replace v4.2 only when it demonstrates:

- economic benefit after costs;
- better results across early and late chronological segments;
- no dependence on one or two episodes;
- explainable attribution tied to the intended mechanism;
- acceptable CAGR sacrifice relative to drawdown improvement;
- prospective evidence after the frozen monitoring date;
- stable data and execution behavior;
- a simpler or clearly more useful decision role.

## Current next action

The immediate next research task is:

> Build the state-2 tail-event decomposition and execution-robustness report. Do not modify the strategy while that diagnosis is being produced.

This is the highest-information step because it determines whether the next model should address gradual volatility, overnight gap risk or merely offer a separate lower-risk portfolio profile.
