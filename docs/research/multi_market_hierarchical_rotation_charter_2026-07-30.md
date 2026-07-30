# Multi-Market Hierarchical Cross-Sectional Rotation Charter

Date: 2026-07-30  
Parent issue: #212

## Decision

Alpha Engine will preserve cross-sectional selection, but move it into a controlled hierarchical system built on separately versioned market-specific pools.

The failed broad-universe result rejected the prior single-layer OHLCV ranker as an authoritative trading model. It did not show that relative comparison is useless. The revised hypothesis is narrower and more interpretable:

1. determine whether the market permits risk;
2. compare economic baskets within one market;
3. compare eligible securities within each selected basket;
4. use a time-series state machine for absolute entry, reduction, exit, and cash control.

The small structured pools are a proving ground. The long-term objective remains to test whether the mechanism can scale to larger pools without losing validity.

## Market separation

US and China A-share candidates must never be placed in one daily cross-section.

Each market has its own:

- pool version and membership identity;
- benchmark and trading calendar;
- market and style references;
- basket taxonomy;
- provider and adjustment contract;
- evidence ledger;
- validation decision.

Code, feature definitions, and deterministic weights may be shared. Cross-market ranks, labels, fitted parameters, and portfolios may not be shared.

## Four-layer architecture

### 1. Market regime

The market benchmark controls the gross-risk budget. A risk-off state may force the portfolio to cash even when one basket ranks first.

### 2. Basket cross-section

At each scheduled rotation date, baskets are compared only with other baskets in the same market. The first deterministic baseline retains four equally weighted components:

- median 63-session relative momentum versus the market benchmark;
- median 20-session momentum;
- breadth above the 50-session moving average;
- median drawdown from the 63-session high.

### 3. Security cross-section

After a basket is selected, its members are first filtered by absolute state. WATCH and EXIT cannot be promoted by a high relative rank.

The remaining securities are ranked within that basket using four equally weighted components:

- 63-session relative momentum versus the market benchmark;
- 20-session momentum;
- drawdown from the 63-session high;
- 20-session realized volatility, with lower volatility ranked higher.

State priority is only a deterministic tie-breaker. It is not the main security rank.

### 4. Security timing and risk

The existing WATCH / ENTER / HOLD / REDUCE / EXIT state machine is reused as an absolute timing and risk-control layer. Only the formula is reused. The old 19-symbol source universe is never inherited.

- ENTER and HOLD permit a full slot;
- REDUCE permits half of the selected slot;
- WATCH and EXIT permit no exposure;
- the market regime and trailing stop may force cash between scheduled basket rotations.

## Required attribution baselines

Every authoritative market validation must compare four implementations:

1. equal-weight pool buy-and-hold;
2. time-series state machine only;
3. hierarchical cross-sectional rotation only;
4. hierarchical cross-sectional rotation plus the state machine.

This decomposition is required before claiming that the complete system adds value. It must identify whether any improvement comes from market timing, basket selection, within-basket selection, or their combination.

## US pool

`us_small_pool_v1` remains the frozen US development pool. Its candidate membership is unchanged by this charter. The research contract changes only the selection mechanism by adding a true within-basket cross-sectional score.

QQQ remains the US market benchmark and SOX remains an informational semiconductor-cycle reference.

## China A-share pool

`cn_small_pool_v1_draft` is a compiled draft based on names repeatedly referenced by the user in prior holdings and watchlist discussions. It is deliberately non-authoritative until the user reviews and freezes both membership and basket assignments.

The draft includes six baskets:

- semiconductor and storage;
- optical, PCB, and connectivity;
- data-center power and thermal management;
- new energy and chemicals;
- metals and shipping;
- advanced manufacturing.

The draft uses exchange-aware canonical symbols and separate provider aliases. The CSI 300 is the market benchmark and the ChiNext Index is an informational growth-style context.

No A-share performance result may be produced while the pool status remains `draft_requires_user_freeze`.

## A-share market-microstructure boundary

An authoritative A-share provider and evaluator must explicitly handle:

- price limits;
- suspensions and missing sessions;
- ST and delisting status;
- corporate-action-adjusted OHLC consistency;
- next-session execution;
- information availability at the close;
- non-tradable sessions without fabricating returns or fills.

A suspended or short-history security remains in membership records. It may be marked unavailable or non-tradable, but it may not be silently deleted.

## Governance

- pool changes require a new version after the pool is frozen;
- no retrospective symbol removal after results are viewed;
- no basket, score-weight, rotation-frequency, or selection-count search in v1;
- no US/CN mixed cross-section;
- no 2026H2 performance inspection;
- no claim of trade readiness before market-specific observed and falsification evidence passes.

## Completion boundary

The contract phase is complete when:

1. the US spec contains basket and within-basket cross-sectional layers;
2. the draft CN pool and CN research contract are versioned;
3. contract tests enforce market isolation, fixed weights, four attribution baselines, and the CN draft gate;
4. separate implementation and validation tasks exist for both markets.

Completion decision: `multi_market_hierarchical_rotation_contract_ready`.
