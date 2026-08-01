# VXN leverage-veto v4.1 experiment

## Question

Can VXN improve the 75% TQQQ switch when it is used only as a Nasdaq-specific leverage veto, while VIX continues to control broad-market defense and initial QQQ repair?

## Origin and evidence status

This hypothesis was generated after reviewing the breadth/VXN v4 evidence. It is therefore **post-result** and cannot be treated as independent validation.

V4 found that:

- VXN contains additional Nasdaq-specific stress information;
- replacing VIX across the entire state machine improved late-sample Sharpe but worsened the full-sample drawdown path;
- requiring complete VXN normalization was too restrictive;
- the useful information appeared concentrated around leveraged Nasdaq exposure.

## Frozen rule

The baseline remains VIX v3 with 75% TQQQ in the partial-leverage state.

VXN changes only the leverage layer:

- QQQI defense uses the existing VIX and price rules;
- QQQI to QQQ uses the existing QQQ repair plus VIX easing rule;
- QQQ to partial TQQQ requires the existing price repair and VIX normalization **and VXN must not be stressed**;
- while partially leveraged, VXN stress returns the strategy to QQQ;
- VXN alone never sends the portfolio to QQQI;
- lack of VXN stress is a permission condition, not a directional forecast.

The VXN stress definition reuses the frozen dynamic VIX parameters: rolling 252-session 80th percentile, 20% one-day spike or 35% five-day spike.

## Compared strategies

- QQQ buy and hold;
- VIX v3 with 75% TQQQ;
- VIX v3 plus VXN leverage veto with 75% TQQQ.

## Required evidence

The run reports:

- CAGR, volatility, Sharpe, maximum drawdown and Calmar;
- turnover and transaction costs;
- early/late chronological splits;
- leveraged-state contribution;
- every baseline leverage entry blocked by VXN and subsequent 5/10/20/40-session TQQQ outcomes;
- complete daily and trade traces;
- persistent strategy-run record and evidence hashes.

## Decision boundary

An attractive in-sample result can create an out-of-sample candidate only. It cannot promote the strategy, because the rule was generated from observed v4 behavior and the common QQQI history begins in 2024.
