# QQQ/TQQQ VXN exit-persistence v4.2 experiment

## Question

Can one two-close persistence requirement remove harmful transient VXN exits without sacrificing the protective value of persistent Nasdaq-specific stress?

## Only allowed change

Baseline v4.1 exits existing leverage after one VXN-stress close. The challenger requires two consecutive VXN-stress closes before VXN alone exits an existing leveraged position.

Everything else is frozen:

- any VXN stress still vetoes a new leveraged entry immediately;
- VIX stress still exits leverage immediately;
- the existing MA20 price failure still exits leverage immediately;
- price-repair and VIX rules are unchanged;
- the leveraged allocation remains 25% QQQ / 75% TQQQ;
- close signal and next-open execution remain unchanged;
- transaction cost remains 10 bps per turnover unit.

## No parameter search

Two closes is the sole predeclared challenger derived from Phase B diagnostics. This experiment does not compare one, three, five or other persistence lengths and does not test a cooldown.

## Validation

Compare v4.1 immediate exit with v4.2 two-close exit persistence over the same long-history attack-layer sample. Report:

- full-sample return and risk metrics;
- 2010-2017, 2018-2021 and 2022-2026 periods;
- 2018 Q4, 2020 crash/recovery and 2022 drawdown windows;
- rolling one- and three-year metrics;
- every economic session changed by the rule;
- leveraged episodes and turnover;
- cost sensitivity at 10, 25 and 50 bps.

## Decision gate

Reject the rule even if it lowers turnover when CAGR, Sharpe, Sortino or Calmar deteriorate materially. Simplicity does not justify suppressing a useful risk signal.

Status:

- `research_only=true`;
- `trade_ready=false`;
- `post_result_hypothesis=true`.
