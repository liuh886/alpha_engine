# QQQ/TQQQ v4.1 long-history attack-layer validation

## Research question

Does the frozen v4.1 VXN leverage veto improve the QQQ/TQQQ attack layer across multiple historical stress and recovery regimes, rather than only in the 2026 episode that motivated the rule?

## What is frozen

No signal or allocation parameter changes in this experiment:

- QQQ price-repair rules;
- VIX stress, easing and normalization rules;
- VXN stress definition;
- VXN's role as a veto on the leveraged state only;
- 25% QQQ / 75% TQQQ leveraged allocation;
- close signal and next-open execution;
- 10 bps cost per turnover unit.

## Why QQQI is excluded

QQQI begins in 2024 and cannot support validation of 2018, 2020 or 2022. This experiment does not synthesize or backfill QQQI. Instead:

- source state 0 maps to QQQ;
- source state 1 maps to QQQ;
- source state 2 maps to 25% QQQ / 75% TQQQ.

The experiment therefore evaluates only whether the strategy should add or remove leverage. It does not make a historical claim about the complete QQQI/QQQ/TQQQ portfolio.

## Frozen comparisons

1. QQQ buy and hold;
2. static 25% QQQ / 75% TQQQ;
3. frozen VIX v3 attack layer without VXN veto;
4. frozen v4.1 attack layer with VXN veto.

## Predeclared validation

The workflow reports:

- full-sample CAGR, volatility, Sharpe, Sortino, maximum drawdown and Calmar;
- fixed chronological periods: 2010-2017, 2018-2021 and 2022-2026;
- named windows: 2018 Q4, the 2020 crash/recovery and the 2022 drawdown;
- rolling 252- and 756-session metrics;
- leverage episodes and every VXN-blocked entry;
- 5/10/20/40-session TQQQ outcomes after blocked entries;
- cost sensitivity at 10, 25 and 50 bps without changing any signal.

## Decision boundary

Retain VXN for further prospective monitoring only if its risk-adjusted benefit is repeated across periods and is not dependent on the 2026 event. Reject or demote it if it consistently misses major recoveries, merely moves losses between periods, or produces unstable rolling performance.

This remains retrospective structural validation:

- `research_only=true`;
- `trade_ready=false`;
- `post_result_hypothesis=true`.
