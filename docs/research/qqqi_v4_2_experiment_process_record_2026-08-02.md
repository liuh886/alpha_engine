# QQQI / QQQ / TQQQ v4.2 experiment process record

**Record date:** 2026-08-02  
**Current baseline:** `qqqi_qqq_tqqq_vxn_bridge_v4_2`  
**Status:** research-only; not trade-ready

## 1. Why this record exists

The purpose of this document is to preserve the research process rather than only the best-looking result. It records the hypotheses admitted, the evidence gates used, methodological corrections, rejected directions and the boundary for the next experiment.

The governing principle is:

> A model version may become the research baseline because it is simpler and more executable under the same signal trace, but it must not become trade-ready merely because its retrospective metrics are attractive.

## 2. Baseline lineage

### v4.1 — immutable signal comparator

v4.1 introduced the VXN veto on the partial TQQQ layer. It retained the price-repair and VIX state machine and used:

- state 0: 100% QQQI;
- state 1: 100% QQQ;
- state 2: 25% QQQ / 75% TQQQ.

It remains the immutable historical signal comparator.

### v4.2 — current research baseline

v4.2 changed only the state-1 allocation:

- state 0: 100% QQQI;
- state 1: 50% QQQI / 50% QQQ;
- state 2: 25% QQQ / 75% TQQQ.

The decision trace, thresholds, VIX/VXN rules, next-open execution and 10 bps cost convention remained unchanged. Relative to v4.1, v4.2 reduced turnover from 71 to 55 units and improved the published net metrics. It became the current research baseline in PR #327 while retaining `post_result_hypothesis=true`.

## 3. Experiment chain and decisions

| PR | Research question | Accepted conclusion |
|---:|---|---|
| #297 | Does a neutral state-1 bridge reduce false-recovery cost without changing signals? | Yes; retain as challenger |
| #327 | Is the bridge a better default execution architecture, and can SGOV improve defense? | Promote v4.2 to research baseline; retain only the 50/50 QQQI/SGOV profile as a drawdown-focused challenger |
| #335 | Does the alert contain enough information to support a next-open decision? | Yes; add freshness, threshold distance, cost, historical evidence and invalidation path |
| #339 | Can state-2 tail risk be reduced by daily-close volatility scaling, delayed execution or one-day confirmation? | No challenger met the robustness standard; retain v4.2 unchanged |

## 4. PR #339: formal process record

### 4.1 Pre-registered question

The experiment first asked whether state-2 losses were gradual enough, and observable early enough at the prior close, to justify a continuous daily-close volatility budget.

The gate required:

- no more than 50% of top-tail loss contribution from overnight gaps;
- at least 50% of top-tail sessions showing a prior-close warning;
- at least 50% of state-2 episodes classified as gradual or distributed.

### 4.2 Evidence generated

The accepted evidence included:

- all state-2 episodes;
- the ten worst leveraged sessions;
- adjusted open-to-close and close-to-next-open contribution;
- prior-close warning availability;
- same-close exit signals;
- true mechanical execution delay;
- isolated `0→1` and `1→2` confirmation ablations;
- chronological and event-level consistency;
- cost stress beyond the official 10 bps assumption.

### 4.3 Methodological correction

The first exploratory implementation used labels such as `risk_increase_delay_1` for a rule that actually required a target state to persist for another close. That is confirmation, not mechanical execution latency.

The accepted evidence separated:

- `fixed_execution_delay_1`: every target is executed one additional session late;
- `bridge_entry_confirmation_1`: only `0→1` must persist;
- `leverage_entry_confirmation_1`: only `1→2` must persist;
- `risk_increase_confirmation_1`: both risk-increasing transitions must persist.

The ambiguous initial result was not used for a decision.

### 4.4 Accepted findings

- The formal sample contained 12 state-2 episodes and 129 leveraged sessions.
- The worst state-2 episode returned about -7.85%.
- About 66.7% of episodes were abrupt or gap-dominated under the frozen classification.
- Only about 27.3% of negative contribution across the ten worst leveraged sessions occurred overnight.
- None of the ten worst sessions had a warning observable at the preceding close.
- About 60% generated an exit signal at the close of the loss day, after most intraday damage had already occurred.

The daily-close volatility-budget gate therefore failed. The evidence did not support retrofitting intraday protection into the daily v4.2 architecture.

### 4.5 Confirmation results

One-day confirmation on `1→2` improved the full-sample headline metrics, but only 5 of 12 affected entries improved. The benefit was concentrated in early history and in avoiding the 2024-09-03 leveraged session; late-period CAGR was lower than v4.2.

The result was retained only as a documented post-result observation. It was not promoted, not assigned a new version and not given a prospective monitor.

### 4.6 Stop decision

The following retrospective searches are closed on the current sample:

- confirmation-day grids;
- additional persistence rules;
- new VIX/VXN or moving-average thresholds;
- alternative state-1 bridge weights;
- alternative SGOV weights;
- alternative fixed TQQQ weights.

New evidence must come from prospective events, a genuinely new data regime, or a separately defined strategy family.

## 5. Reusable research rules learned

1. **Name the mechanism correctly.** Execution latency, signal confirmation and persistence filters are different treatments.
2. **Decompose the economic path.** A close signal cannot be credited with avoiding a loss already realized before that close.
3. **Require event consistency.** A higher CAGR dominated by one event is not sufficient.
4. **Require chronological consistency.** Early-sample improvement with late-sample deterioration is a warning, not validation.
5. **Preserve failed evidence.** Discarded or corrected runs must be identified and excluded explicitly.
6. **Separate architecture from risk preference.** The blended SGOV profile may suit a drawdown-sensitive user without being the universal baseline.
7. **Stop searching when the information boundary is reached.** Daily data cannot answer a genuinely intraday execution question.

## 6. Current decision state

- v4.2 remains the sole current research baseline and alert source.
- v4.1 remains the immutable historical signal comparator.
- the blended QQQI/SGOV allocation remains a separate drawdown-focused profile.
- no v4.3 strategy is authorized.
- all active strategies remain `research_only=true` and `trade_ready=false`.
