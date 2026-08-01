# v4.2 confidence-weighted bridge allocation experiment

## Research question

The complete v4.1 event study shows that the 75% TQQQ transition is the strongest return-producing signal, while the initial QQQI-to-QQ transition has only a small average twenty-session relative benefit and approximately a 50% positive-benefit rate.

Can the strategy improve risk-adjusted performance by treating state 1 as a lower-confidence bridge rather than a full QQQ commitment?

## Frozen parent strategy

The parent is `qqqi_qqq_tqqq_vxn_leverage_v4_1`.

The following remain exactly unchanged:

- QQQ price-repair features and thresholds;
- VIX stress, easing and normalization rules;
- VXN stress definition and leverage-veto role;
- every state-transition date and reason;
- state 0 at 100% QQQI;
- state 2 at 25% QQQ and 75% TQQQ;
- close signal and next-open execution;
- 10 bps cost per turnover unit;
- QQQI common-history boundary and no pre-inception backfill.

## Single challenger

Only state 1 changes:

| State | v4.1 | v4.2 bridge challenger |
|---|---|---|
| 0: defensive | 100% QQQI | 100% QQQI |
| 1: early recovery | 100% QQQ | 50% QQQI + 50% QQQ |
| 2: confirmed recovery | 25% QQQ + 75% TQQQ | 25% QQQ + 75% TQQQ |

The 50/50 allocation is a neutral confidence bridge. No alternative weights are tested.

## Why this is not another factor

The challenger adds no market variable and changes no state decision. It only aligns capital allocation with the measured confidence hierarchy:

1. state 0: defensive;
2. state 1: recovery evidence exists but the relative QQQ edge is weak;
3. state 2: the leverage transition has a much stronger observed return edge.

## Required evidence

The workflow must report:

- complete portfolio metrics after identical costs;
- exact state-trace equality with v4.1;
- state-1 and state-2 contribution;
- transition-level turnover and costs;
- chronological early/late splits;
- every 0-to-1 event with 5/10/20/40-session bridge-minus-QQ outcomes;
- all daily holdings, trades and evidence hashes.

## Decision gate

The challenger may be retained only as a research monitoring candidate if all of the following hold:

- CAGR, Sharpe, Sortino and Calmar improve;
- maximum drawdown is not worse;
- turnover is lower or equal;
- state-2 sessions are exactly unchanged;
- improvement is not confined to one late event;
- no parameter selection follows from the observed result.

Even if all gates pass, the experiment remains `post_result_hypothesis=true`, `research_only=true` and `trade_ready=false`.
