# BYD v1.2 trend-expansion prospective protocol

Issue: #560  
Formal baseline: **BYD v1.1**  
Shadow candidate: `byd_v1_2_trend_expansion_1125`

## Purpose

Historical research found that a frozen 112.5% BYD trend-expansion state produced a small, financing-cost-resilient improvement over BYD v1.1, but the result was too concentrated and the sample was too small for formal promotion.

This ledger collects genuinely forward evidence without reopening historical selection.

## Frozen candidate

The only prospective candidate is:

- normal risk-on and defensive states: identical to BYD v1.1;
- frozen trend-expansion state: 112.5% BYD and -12.5% financing balance;
- primary costs: 20 bps per absolute weight change plus 6% annual financing;
- stress costs: 40 bps plus 10% annual financing.

The historical 110% candidate remains robustness evidence only. The 125% candidate remains diagnostic only. Neither can replace the frozen prospective candidate after the result was observed.

## Frozen state

Entry requires all:

- BYD v1.1 base target = 100%;
- market state = bull;
- volatility state = low;
- 20-session momentum > 0;
- 60-session momentum > 0;
- 252-session drawdown > -10%.

Exit occurs when any:

- base target returns to 75%;
- market state is not bull;
- volatility becomes high;
- 20-session momentum becomes non-positive.

The state is rebuilt deterministically from the immutable canonical BYD history and append-only chain-linked BYD observations. Existing observations are byte-compared on every run.

## Source and execution contract

The ledger joins two already-governed sources by signal date:

1. `data/research/byd_prospective_shadow/observations` for BYD prices and reconstructed factors;
2. `data/research/byd_515180_prospective/observations` for independently confirmed common-open eligibility and paired BYD/515180 prices.

A signal generated after close is executed only at the next independently confirmed common eligible open. An ineligible open keeps the prior executed position. Financing is charged daily only on negative cash.

No observation on or before 2026-08-05 is admitted to this new ledger. Historical rows are not backfilled as prospective evidence.

## Append-only store

Durable path:

`data/research/byd_v1_2_trend_expansion_prospective/`

It contains:

- immutable observation JSON records;
- immutable 5/10/20 common-open outcome records;
- a derived CSV ledger;
- a derived scorecard;
- a hash-bound manifest;
- a current README summary.

The scheduled workflow runs after the upstream BYD and BYD/515180 prospective workflows on weekdays. It first reproduces the complete store from source records, then appends only unseen dates.

## Reconsideration gates

No formal reconsideration before all of the following are true:

- at least 12 months of forward time;
- at least 10 completed expansion episodes;
- at least 126 financed sessions;
- positive net relative terminal wealth under both primary and stress costs;
- no single positive prospective episode contributes more than 60% of positive relative wealth.

Passing these gates does not trigger automatic promotion. It authorizes a separate governed review only.

## Prohibited actions

- no historical threshold repair;
- no additional leverage level;
- no substitution of the 110% or 125% variants;
- no change to financing assumptions after outcomes mature;
- no same-close execution;
- no rewriting or deleting an observation;
- no automatic formal promotion;
- no trade-ready claim without separately verified financing feasibility.

Current status:

- `research_only=true`;
- `trade_ready=false`;
- `automatic_promotion_allowed=false`.
