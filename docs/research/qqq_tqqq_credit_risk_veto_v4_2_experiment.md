# QQQ/TQQQ HYG/SHY credit-risk veto v4.2

## Question

Does a liquid credit-risk appetite proxy improve the frozen v4.1 leveraged-state allocation after price, VIX and VXN are already active?

## Proxy and interpretation

The experiment uses:

```text
adjusted close of HYG / adjusted close of SHY
```

HYG represents US high-yield corporate bonds; SHY represents short-duration US Treasuries. A falling ratio indicates high yield underperforming short Treasuries.

This is a liquid, reproducible risk-appetite proxy. It is not treated as a pure option-adjusted credit spread because ETF duration, composition, flows and distributions may affect the ratio.

## Data-quality gate

Before any strategy calculation, the experiment requires:

- at least 756 common sessions;
- at least 98% coverage of prepared trading sessions within the common span;
- positive adjusted closes;
- no absolute one-day ratio return above 20%;
- fail-closed behavior when any requirement is violated.

The evidence stores common coverage, missing sessions and the largest daily ratio move.

## Frozen rule

Credit stress is active when HYG/SHY closes below its own 50-session moving average.

This is the only tested specification. The experiment does not compare:

- HYG/IEF;
- alternative Treasury ETFs;
- other moving-average windows;
- momentum confirmation;
- persistence or cooldown rules.

## Role

The factor affects only the leveraged state:

- it vetoes a new 75% TQQQ entry during credit stress;
- it returns existing leverage to QQQ during credit stress.

It cannot alter:

- QQQ defense or initial repair;
- price rules;
- VIX rules;
- VXN rules;
- the 25% QQQ / 75% TQQQ allocation;
- close signal and next-open execution;
- 10 bps cost per turnover unit.

## Validation

The evidence reports:

- data-quality diagnostics;
- overlap and unique stress relative to VIX/VXN;
- full-sample and fixed-period return/risk metrics;
- 2018 Q4, 2020 and 2022 windows;
- rolling one- and three-year metrics;
- all blocked entries or exits with subsequent 5/10/20/40-session outcomes;
- changed economic holdings and leverage episodes;
- cost sensitivity at 10, 25 and 50 bps.

## Decision gate

Add the factor only if data quality passes and the complete strategy shows clear, stable incremental value beyond v4.1 after costs. A plausible credit narrative or isolated drawdown improvement is insufficient.

Status:

- `research_only=true`;
- `trade_ready=false`.
