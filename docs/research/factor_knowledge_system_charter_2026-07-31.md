# Factor Knowledge System Charter

Status: proposed research contract
Date: 2026-07-31
Scope: research only; no live orders or personalized trading recommendation

## Objective

Alpha Engine must accumulate reusable knowledge from every factor experiment. A factor test is not complete merely because it produces IC or backtest metrics. It must leave behind a versioned factor card that states what was tested, on which evidence, what worked, what failed, where it may apply, and whether it adds information beyond existing factors.

The long-run objective is a small, interpretable, low-turnover multi-factor system selected from accumulated evidence, not repeated isolated factor searches.

## Principles

1. Preserve all historical tests, including failures and invalid legacy evidence.
2. Never equate a legacy `Active` registry stage with current support.
3. Separate factor identity, evidence identity, evaluation result, and portfolio usage.
4. Use point-in-time availability dates and manifest-bound providers.
5. Evaluate economic usefulness after costs and turnover, not IC alone.
6. Select multi-factor combinations for complementarity and marginal contribution, not standalone leaderboard rank.
7. Freeze candidate sets and combination rules before observed evaluation.
8. Do not delete failed factors; record why they failed and what they taught us.
9. Keep US and China evidence separate while allowing explicit cross-market comparison.
10. Reserved evidence must remain unopened until the declared date and forward horizon are complete.

## Factor card

Every factor version must record:

- stable factor id and version;
- canonical definition or expression;
- economic thesis and expected mechanism;
- information family: price trend, risk, valuation, quality, growth, revisions, event, flow, or other;
- update frequency, lookback, availability lag, and transformation;
- orientation and neutralization rules;
- market, universe version, basket scope, benchmark, and horizon;
- provider, data-validity level, source hashes, and evidence-manifest hash;
- development, falsification, and reserved windows;
- IC, rank IC, spread, decay, and coverage diagnostics;
- after-cost return, benchmark-relative return, drawdown, downside capture, turnover, holding duration, and concentration;
- regime, basket, and market-specific behavior;
- score correlation, return correlation, and overlap with other factors;
- incremental and leave-one-out contribution in declared combinations;
- decision status, failed gates, failure class, and lessons learned;
- code/spec/report paths and immutable identities.

## Status taxonomy

- `legacy_unverified`: historical result not valid under current evidence rules;
- `data_blocked`: thesis not evaluated because required point-in-time data are incomplete;
- `rejected`: tested and failed declared gates;
- `market_specific_clue`: useful in one market, basket, or regime but not broadly supported;
- `candidate`: standalone evidence is promising but incomplete;
- `redundant`: individually useful but adds no independent information;
- `independent_validation_required`: passes observed evidence and awaits untouched evidence;
- `retired`: mechanism or data contract is no longer admissible.

No factor may be labeled `supported` or used as a production signal without independent validation.

## Historical backfill

Backfill every material factor family already tested, including at minimum:

- legacy 261-factor scan and prior Active/Proposed registry records;
- 5D and 10D momentum, Sharpe, close-volume correlation, moving-average deviation, and other previously promoted technical factors;
- benchmark-residual trend quality;
- Bollinger reversion, MACD histogram, RSI strength, and close-location pressure;
- LightGBM/XGBoost OHLCV feature-family results and the static-to-PIT collapse;
- basket-level momentum, breadth, and drawdown components;
- within-basket relative momentum, short momentum, drawdown, and realized volatility;
- time-series state-machine components;
- the simple fundamental acceleration factor tracked in Issue #225.

Legacy records must be preserved but reclassified. Strong static or non-PIT results become `legacy_unverified`, not current evidence.

## Multi-factor exploration

### Candidate families

The first multi-factor candidate set should contain a small number of distinct economic families rather than many variants of price momentum:

1. growth acceleration;
2. quality/profitability improvement;
3. valuation or cash-flow yield;
4. medium-term relative trend;
5. low-risk or downside-resilience;
6. revisions or event information when point-in-time data become available.

### Selection sequence

1. Evaluate each factor independently under one common contract.
2. Remove factors that are invalid, unstable, or economically unusable.
3. Group remaining factors by information family and empirical correlation.
4. Select at most one primary factor per highly correlated cluster.
5. Test simple equal-weight combinations before any learned weighting.
6. Require each included factor to show positive marginal or risk-reduction contribution.
7. Measure the combination against its best standalone member, equal-weight pool, and benchmark.
8. Reject combinations whose improvement depends on excessive turnover or one symbol/basket.

### Low-turnover portfolio contract

- monthly evaluation by default;
- point-in-time fundamental updates only after public availability;
- entry/retention buffers to reduce rank churn;
- minimum holding period except for data invalidation or hard risk failure;
- bounded replacements per rebalance;
- explicit annual turnover and average holding-duration gates;
- no daily factor-weight changes;
- transaction costs applied only to executable exposure changes.

### Combination diagnostics

Required outputs include:

- factor score correlation matrix;
- factor portfolio-return correlation matrix;
- selection overlap and churn attribution;
- standalone versus combination economics;
- add-one and leave-one-out contribution;
- regime, basket, and market contribution;
- turnover contribution by factor;
- concentration and risk contribution;
- failure modes and non-additivity residuals.

## Learning outputs

Every research cycle must update:

1. the factor catalog;
2. the evidence ledger;
3. the factor relationship map;
4. the combination experiment ledger;
5. an answer-first market learning report.

The market learning report must distinguish:

- robust findings;
- market-specific clues;
- disproven hypotheses;
- unresolved questions;
- data limitations;
- the next experiment justified by accumulated evidence.

## Immediate implementation phases

### Phase A — registry correction

Extend the registry schema and migration so missing required metrics fail closed, evidence identities are mandatory for authoritative records, and legacy Active factors are reclassified without deletion.

### Phase B — historical factor ledger

Create deterministic importers for maintained research reports, specs, manifests, and existing registry records. Produce a coverage report listing every historical factor and whether its evidence is complete.

### Phase C — factor relationship map

Store comparable factor score series and factor portfolio returns, then calculate correlations, overlap, regime behavior, and redundancy clusters on aligned evidence.

### Phase D — first frozen multi-factor experiment

Use a predeclared small candidate set, equal weighting, monthly evaluation, buffers, and strict turnover gates. Run once on observed evidence and issue a fail-closed decision.

## Truth boundary

This charter defines an exploratory knowledge system. It does not authorize trade-ready labels, live trading, broker integration, automated orders, or opening the 2026H2 reserved evidence.
