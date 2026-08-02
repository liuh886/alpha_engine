# XGBoost dual-market baseline identity

## Corrected decision

The first provenance pass was incomplete because it searched the current `main`
history but did not inspect the successful evidence artifacts on the still-open
selected-pool retest branch.

The corrected baseline identity is:

| Market | User-reported figure | Verified governed result | Status |
| --- | ---: | ---: | --- |
| US vs QQQ | 81.43% | 73.72% | 81.43% unresolved; 73.72% is the current US87 baseline |
| CN vs CSI 300 | 20.18% | 20.1818% | verified |

The CN figure must no longer be dismissed as a collision with the historical
`IC IR = 20.18` table. The exact selected-pool artifact independently reports
`compounded_relative_excess_return = 0.2018176732282666` for XGBoost.

## Evidence identity

The source is the successful `Selected Pool Ranker Retest` workflow:

- PR: #289;
- workflow run: `30707914152`;
- head SHA: `ebf0eaf829bbadc86f3bd49ab4666682fbdf8de0`;
- US artifact: `8820927998`, digest
  `sha256:d7b530d4f7eed4a81ab635c6f3c2c8f127ebca3acfd14158f8a274bb41180dbe`;
- CN artifact: `8820979579`, digest
  `sha256:9f6cafde54fe4431f26f12145053611a72c2406b3333b12367f7b485624fe22a`.

Relative excess is calculated as:

```text
(1 + compounded strategy return) / (1 + compounded benchmark return) - 1
```

## US87 baseline

Candidate:

```text
xgb:daily_ranker:momentum_volatility_volume:
gain5_round100_leaves31_leaf10_lr0.05/xgb_rank_ndcg/original
```

Observed evidence:

- requested pool: 87 equities;
- retained common-history pool: 74 equities;
- 13 lifecycle exclusions, all explicitly reported;
- strategy return: 169.62%;
- QQQ return: 55.20%;
- compounded relative excess: 73.72%;
- positive excess windows: 4/4;
- mean ICIR: 0.2262;
- mean Rank IC: 0.0377;
- worst drawdown: -30.69%;
- ready ratio: 0.25;
- promotion decision: rejected.

The economic result remains material, but its quality is uneven. The 2025H1
window produced only 1.75 percentage points of simple excess while suffering a
30.69% drawdown and negative ICIR. By contrast, 2025H2 produced 40.94 points of
simple excess and contains a large share of the aggregate result. The next US
work must therefore test concentration and tail-risk robustness before adding a
large new factor set.

The historical 70.35% result remains a separate 126-symbol retrospectively
curated static-universe reference. It is neither the 81.43% claim nor the
current US87 baseline.

## CN130 baseline

Candidate:

```text
xgb:daily_ranker:cn_balanced_ohlcv:
gain5_round100_leaves31_leaf10_lr0.05/xgb_rank_ndcg/original
```

Observed evidence:

- requested pool: 130 equities;
- retained common-history pool: 122 equities;
- eight lifecycle exclusions, all explicitly reported;
- strategy return: 68.60%;
- CSI 300 return: 40.29%;
- compounded relative excess: 20.1818%;
- positive excess windows: 3/4;
- mean ICIR: 0.1022;
- mean Rank IC: 0.0059;
- worst drawdown: -16.12%;
- ready ratio: 0.00;
- promotion decision: rejected.

The CN result has improvement headroom, but the first question is whether it is
true stock-ranking alpha. Both 2024 windows produced positive portfolio excess
while IC and Rank IC were negative. This mismatch can arise from sector, size,
beta, volatility or concentration exposures rather than stable cross-sectional
ranking. The 2025H2 window then lost 8.29 percentage points relative to CSI 300.
Portfolio optimization alone would be premature until these exposures are
attributed.

## Next controlled research sequence

### US

1. Decompose 2025H1 drawdown into names, dates, sectors and overnight/intraday
   components where execution data permit.
2. Measure how much of 2025H2 and total relative excess is supplied by the top
   five and top ten contributors.
3. Run seed/bootstrap stability and Top-15 selection-overlap diagnostics.
4. Test cost, turnover-control, Top-K breadth and volatility-scaling sensitivity
   as separate portfolio-construction experiments.
5. Add new factor families only after the governed Alpha158 and PIT fundamental
   coverage gates pass.

### CN

1. Attribute 2024 positive excess despite negative IC/Rank IC to sector, size,
   beta, volatility and security concentration.
2. Diagnose the 2025H2 failure and compare score distributions across windows.
3. Run seed/bootstrap stability, rank correlation and Top-15 overlap tests.
4. Test feature-family ablations and one bounded objective/regularization grid.
5. Evaluate portfolio controls only after ranking signal stability is shown.

## Research boundary

Neither model is trade-ready. The US 81.43% number is not a valid optimization
target until an exact artifact is recovered. US and CN must remain separate
model decisions, and the final challenge evidence may be evaluated only once
for a frozen candidate.
