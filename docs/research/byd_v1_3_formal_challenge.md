# BYD v1.3 formal challenge

Issue: #724  
Champion: **BYD v1.2 (`byd_v1_2_convex_momentum_budget_v1`)**  
Candidate: **BYD v1.3 (`byd_v1_3_min_hold_bear_defense`)**  
Historical cutoff: **2026-08-03**  
Research only: **true**  
Trade ready: **false**

## Why this challenge exists

Issue #716 found a promising V1.3 direction after a broad BYD model audit. The exploratory implementation also exposed a governance problem: several experiments reconstructed V1.2 locally and therefore produced different V1.2 headline metrics. A promotion challenge cannot compare a challenger against an approximate champion.

This challenge fixes that boundary. The maintained V1.2 implementation is the only champion implementation. V1.3 is expressed only as a small delta on its governed states, execution and costs.

## Frozen delta

Exactly three changes are allowed:

1. hold each inherited V1.2 base risk target for at least 20 sessions before accepting the next base-target transition;
2. when that held base target is defensive and the existing governed market state is `bear`, allocate 55% BYD / 45% 515180 instead of 75% / 25%;
3. retain the V1.2 expansion state rules but use a maximum financed increment of 15% and convex power 2.0.

The first ETF-overlap base state is treated as mature because it is inherited from canonical pre-overlap V1.2 history. No SMA, momentum, market-state or volatility-state definition is recomputed by V1.3.

## What is inherited unchanged

- immutable BYD and 515180 inputs;
- V1.2 base signal semantics;
- governed market and volatility states;
- close-time signal / next common independently confirmed eligible open execution;
- 20 bps primary and 40 bps stress transaction costs;
- 6% primary and 10% stress financing;
- evaluation windows and metrics.

## Evidence governance

The challenger was selected after historical exploration. Therefore all history through 2026-08-03 is consumed evidence, including 2023-2024 and 2025+. No fresh historical holdout claim is made.

The frozen formal run may certify historical support under the precommitted gates in `configs/research_candidates/byd_v1_3_min_hold_bear_defense_v1.yaml`. It may not change parameters, windows, costs or gates after the result is known.

Explicit user direction on 2026-08-10 authorizes promotion only if every frozen gate passes. Automatic promotion remains forbidden.

## Formal evidence

`scripts/validate_byd_v1_3_formal.py`:

1. verifies the machine-readable challenger contract;
2. rebuilds the maintained V1.2 champion from immutable inputs;
3. requires its full-period published metrics to match the accepted formal package exactly;
4. runs V1.3 through the same shared execution and cost implementation;
5. evaluates all frozen primary, stress, turnover and concentration gates;
6. emits exact daily traces, comparison/attribution tables, `decision.json` and a SHA-256 manifest.

The existing backend CI runs this validator with `--require-supported`, so a failed formal gate fails closed instead of silently promoting the candidate.
