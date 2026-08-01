# QQQI / QQQ / TQQQ v4.1 prospective monitoring

## Purpose

This workflow accumulates evidence generated after the frozen monitoring start of 2026-08-01. It does not continue the retrospective factor search and does not change the strategy.

## Frozen candidate

Candidate: `qqqi_qqq_tqqq_vxn_leverage_v4_1`

Architecture:

1. QQQ price repair identifies recovery opportunity.
2. VIX controls broad defense and the QQQI/QQQ transition.
3. VXN vetoes the leveraged layer during Nasdaq-specific stress.
4. The leveraged state holds 25% QQQ and 75% TQQQ.
5. Close-derived signals execute at the next adjusted open.
6. Transaction cost remains 10 bps per turnover unit.

No factor rejected during the sequential cycle is active.

## Monitoring clock

- monitoring start: `2026-08-01`;
- first possible US economic return after the boundary: the next available trading session;
- scheduled run: Saturday at 14:00 UTC, after the Friday US session and normal daily-data publication;
- manual runs remain available.

The workflow permits zero prospective observations. Before the first post-boundary return is available, it records `awaiting_first_prospective_return` rather than borrowing earlier observations.

## Outputs

Each run writes:

- contract and evidence hashes;
- latest provider coverage;
- prospective-only metrics for QQQ buy-and-hold, VIX v3 and v4.1;
- prospective state counts, turnover and costs;
- every post-boundary close where VXN changes the next-session state;
- subsequent 5/10/20/40-session TQQQ outcomes when mature;
- latest executed position;
- latest close-derived next-session decision and reason;
- a machine-readable `StrategyExperimentJournal` record.

Full-history metrics are recomputed only as context. They are explicitly excluded from prospective evidence.

## Governance

The workflow cannot:

- tune VIX or VXN thresholds;
- change the 75% TQQQ weight;
- activate breadth, downside-volatility, credit or persistence rules;
- combine factors;
- mark the strategy trade ready;
- promote the strategy automatically.

Any future promotion decision requires a separate review of accumulated prospective evidence, concentration by event, costs and operational behavior.

Status remains:

- `research_only=true`;
- `trade_ready=false`;
- `prospective_monitoring=true`.
