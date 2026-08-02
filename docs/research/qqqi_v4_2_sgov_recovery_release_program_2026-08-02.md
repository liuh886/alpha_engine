# v4.2 SGOV recovery-release research program

**Pre-registration date:** 2026-08-02  
**Research status:** active experiment; research-only; not trade-ready  
**Current baseline:** `qqqi_qqq_tqqq_vxn_bridge_v4_2`

## Research question

The blended QQQI/SGOV profile reduced all five major v4.2 troughs, but its resolved major episodes recovered a median 57 sessions later than v4.2. The next question is not whether SGOV protects during stress; that mechanism is already established. The question is whether the SGOV sleeve can be released earlier during a recovery without destroying that protection.

The experiment separates two mechanisms:

1. release SGOV to QQQI when the frozen v4.2 state machine enters state 1;
2. release a maximum 25% sleeve to TQQQ when existing medium-repair and volatility-normalization conditions are observable, before formal state 2.

No new indicator or threshold is introduced.

## Frozen comparator structures

### Current v4.2

- state 0: 100% QQQI;
- state 1: 50% QQQI / 50% QQQ;
- state 2: 25% QQQ / 75% TQQQ.

### Static blended profile

- state 0: 50% QQQI / 50% SGOV;
- state 1: 25% QQQI / 25% SGOV / 50% QQQ;
- state 2: 25% QQQ / 75% TQQQ.

## Three admitted ablations

### A. QQQI release on state 1

- state 0 remains 50% QQQI / 50% SGOV;
- state 1 becomes 50% QQQI / 50% QQQ;
- TQQQ timing remains unchanged.

This isolates whether the recovery penalty comes primarily from keeping 25% SGOV after the model has already recognized an early recovery.

### B. TQQQ release on frozen precursor

- ordinary state 1 remains 25% QQQI / 25% SGOV / 50% QQQ;
- when shock memory, medium repair and VIX normalization are true and VXN is not stressed, the 25% SGOV sleeve becomes 25% TQQQ at the next open;
- formal state 2 remains unchanged at 75% TQQQ.

This isolates the value and risk of limited early leverage.

### C. Staged QQQI then TQQQ release

- state 1 first removes SGOV in favor of QQQI;
- the same frozen precursor then moves 25% from QQQI to TQQQ;
- state 2 remains unchanged.

This tests a recovery ladder rather than a binary switch.

## Execution discipline

- all signals are observed at the US session close;
- all allocation changes execute at the next session open;
- adjusted open-to-adjusted-open returns are used;
- transaction cost remains 10 bps per turnover unit;
- the current v4.2 state trace is identical for every variant;
- pre-state-2 TQQQ exposure is capped at 25%;
- no weight, threshold, quantile, moving average or persistence search is permitted.

## Candidate gate

A release variant may become a separate prospective challenger only if all conditions pass:

- at least 80% of the five major v4.2 troughs remain improved;
- median same-trough protection remains at least 2 percentage points;
- median recovery lag is no more than 30 sessions;
- no major episode remains unresolved;
- CAGR sacrifice versus v4.2 is no more than 2 percentage points;
- maximum drawdown worsens by no more than 0.5 percentage points versus v4.2;
- early- and late-segment CAGR both improve versus the static blended profile;
- for TQQQ precursor variants, at least 60% of precursor episodes are beneficial;
- no single precursor episode supplies more than 60% of total positive benefit.

Passing never promotes a candidate directly. It only authorizes prospective monitoring alongside the unchanged v4.2 baseline.

## Interpretation rules

- If QQQI release passes and TQQQ release fails, the recovery penalty is primarily a defensive-asset allocation problem, not a leverage-timing problem.
- If TQQQ release improves headline return but fails event consistency, the result is treated as rebound-event concentration.
- If the staged release passes, it becomes a separate research challenger; the Telegram production alert remains v4.2 until prospective evidence exists.
- If all candidates fail, the static blended profile remains a descriptive drawdown-first allocation and no further same-sample release timing search is allowed.

## Deliverables

- versioned experiment contract;
- daily weights and returns for all variants;
- five-major-trough protection and recovery-lag tables;
- early/late chronological metrics;
- precursor episode event study;
- candidate gate output;
- Notebook 22;
- CI evidence artifact and manifest.
