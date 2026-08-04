# CN130 cross-sectional ranking and rotation experiment log

Date: 2026-08-04  
Issue: #509  
Pull request: #511  
Experiment: `cn130_cross_sectional_ranking_rotation_v1`  
Status: completed; ranking not supported; rotation decision stage not opened

## Bound evidence identity

- provider cutoff: 2026-08-03;
- provider identity: `abae71f037571a9a847d4582e0bea9fabdd71796cac54a70aa7c6d07b668eeb0`;
- calendar SHA256: `c5532fa1563f794bb34c17c9f2858af9ffb0bb9fb8e79fb2dec5db1905ebf98c`;
- universe file SHA256: `4ce5b95e60d38a13e4852fb6f7a3a6437b55d6da0fb317ad553d114e85158529`;
- classification SHA256: `d1ef3bd06c0953c7e78fa0ba99c372da714ddce67203909d195d73e9eec61d15`;
- candidate membership: unchanged CN130;
- static membership survivorship bias: declared;
- research only: yes;
- trade ready: no.

## Execution record

1. Added a complete 130-name sector/industry taxonomy before reading final experiment results.
2. Confirmed the provider has no point-in-time shares outstanding or market-cap field. The experiment does not relabel turnover or traded amount as market capitalization.
3. Rebuilt the fourteen CN x1.0 OHLCV features directly from the bound provider and retained the effective XGBoost `rank:ndcg` identity: five gain bins, 100 rounds, 31 leaves, learning rate 0.05 and seed 42.
4. Applied an eleven-session purge before every half-year test window so a ten-session training label cannot enter the test period.
5. Ran R0, R1, R2, an ineligible partial R3, and R4 across 2024H1, 2024H2, 2025H1 and 2025H2.
6. Stored complete score, rank, return, sector, beta, volatility, liquidity, lifecycle and tradability ledgers as compressed window/candidate/family partitions.
7. Added reporting-only evidence for 2026H1 and the realizable part of 2026H2 through 2026-08-03.
8. Calculated diagnostic Top-15 economics only to show the difference between portfolio outcome and ranking validity. No portfolio return was used to select a ranking model.

## Engineering corrections made during implementation

### Evidence storage

The first implementation retained every full ledger in memory and attempted one uncompressed output. One half-year produced more than 130 MB of CSV evidence and made later windows inefficient. The implementation was changed to append-only gzip partitions by window, candidate and feature family. No observations or columns were removed.

### R4 query grouping

The first R4 prototype used one LambdaRank query for every date-sector pair. This created many tiny query groups and was both slow and statistically weak. Before the complete four-window run, R4 was fixed as:

1. sector model on sector-median features;
2. global industry-relative security model;
3. security score converted to a within-sector percentile;
4. frozen `0.35 * sector + 0.65 * within-sector security` combination.

This implementation is recorded in the experiment config and is not a post-result parameter search.

## Test record

- seven dedicated unit tests passed;
- nineteen focused ranking, missing-data and universe-contract tests passed;
- direct Qlib binary offset parsing, benchmark-relative rank identity, sector-relative labels, hierarchical score weights, next-session execution, sector caps and cash-inclusive turnover are covered;
- the final GitHub Actions workflow performs a locked-environment rerun and uploads the complete evidence package.

## Main results

- R1 and R0 have exact cross-sectional rank identity; R1 adds no information.
- The best eligible mean Rank IC is R2 momentum/reversal at `0.0096`, but only two of four windows have positive spread and the strongest positive window contributes `66.3%`.
- R0 mean Rank IC is `0.0011`; three of four windows have positive spread, but the strongest positive window contributes `55.7%`.
- Every candidate has negative Rank IC in both 2024 windows.
- 2025H1 and especially 2025H2 are substantially stronger, showing a pronounced regime dependency.
- 2026H1 is positive across the principal candidates, while partial 2026H2 sharply reverses: R0 Rank IC is approximately `-0.550`; R4 momentum/reversal reduces the magnitude to approximately `-0.185` but remains negative.
- Full R3 is data-blocked by missing PIT market capitalization. Partial R3 results are not promotion eligible.
- Some diagnostic Top-15 portfolios earn positive excess despite weak or negative full-cross-section Rank IC. This is evidence that portfolio concentration and market path can mask invalid ranking, not evidence to promote those variants.

## Decision

`cn130_cross_sectional_ranking_not_supported`

No ranking rule was frozen. Therefore P1-P5 were not opened for formal comparison, no CN x1.1 candidate was created, and CN x1.0 remains unchanged.
