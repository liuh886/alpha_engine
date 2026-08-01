# QQQ/TQQQ realized downside-volatility veto v4.2

## Question

Does QQQ's recently realized downside path provide useful leverage-risk information beyond the frozen v4.1 VIX and VXN signals?

## Frozen factor

For each close:

1. calculate adjusted close-to-close QQQ returns;
2. retain only negative returns;
3. calculate the annualized root mean square of negative returns over ten sessions;
4. compare that value with its trailing 252-session 80th percentile, using at least 126 observations;
5. mark downside-volatility stress when the current value is above the threshold.

No alternative lookback, percentile, volatility definition or persistence rule is tested.

## Role

The factor affects only the leveraged state:

- it vetoes a new 75% TQQQ entry when stressed;
- it returns existing leverage to QQQ when stressed.

It cannot change:

- the QQQ state or broad defense;
- price-repair rules;
- VIX stress, easing or normalization rules;
- VXN entry veto or exit rules;
- the 25% QQQ / 75% TQQQ allocation;
- close signal and next-open execution;
- 10 bps transaction cost per turnover unit.

## Incremental-information requirement

The evidence reports overlap with VIX and VXN stress. A factor that mostly duplicates implied-volatility states must demonstrate especially clear incremental portfolio value.

## Validation

Compare unchanged v4.1 with the downside-volatility challenger over the same long-history attack-layer sample. Report:

- full-sample return and risk metrics;
- fixed chronological periods and named stress windows;
- rolling one- and three-year metrics;
- leverage episodes;
- every blocked entry or early exit and subsequent 5/10/20/40-session QQQ and TQQQ returns;
- economic sessions whose holdings changed;
- stress overlap with VIX/VXN;
- cost sensitivity at 10, 25 and 50 bps.

## Decision gate

Add the factor only if it provides clear incremental information, improves false-start or tail-loss outcomes, and improves the complete portfolio after costs without material CAGR sacrifice or unstable period results.

Status:

- `research_only=true`;
- `trade_ready=false`.
