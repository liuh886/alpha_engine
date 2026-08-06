# BYD v1.2 governed promotion challenge

Issue: #592  
Formal baseline while this work runs: **BYD v1.1**  
Historical evidence cutoff: **2026-08-03**  
Research only: **true**  
Automatic promotion: **forbidden**

## Why a new challenge is required

The original frozen 112.5% trend-expansion candidate improved historical compound return, but its benefit was too concentrated and its sample was too small. PR #588 then changed the state rules after those failures were known and promoted a relaxed 110% rule even though its own governed result still failed the concentration gate and was negative in the 2025+ reporting window.

That result remains useful research evidence, but it is not an independent promotion result. The registry therefore keeps BYD v1.1 as the accepted formal baseline while this challenge runs.

## What is frozen

All candidates reuse the original trend state from `src/research/byd_v1_2_trend_expansion.py`:

- BYD v1.1 base target is 100%;
- market state is bull;
- volatility state is low;
- 20-session and 60-session momentum are positive;
- 252-session drawdown is above -10%;
- the original exit contract is unchanged.

The search does not modify entry thresholds. It tests how a maximum 12.5% financed increment is budgeted after entry.

## Candidate mechanisms

### Episode budget

Apply 112.5% BYD only for the first 20 financed sessions of an expansion episode. This prevents unusually long historical episodes from receiving unlimited incremental exposure.

### Volatility budget

Scale the 12.5% increment by a fixed 30% annualized, 20-session BYD volatility budget. This reduces financing when the same trend state carries a larger ex-ante risk load.

### Relative-strength confirmation

Apply 112.5% only when the frozen state is active, BYD's fixed 60-session return is positive, and BYD has outperformed 515180 over the same fixed window.

The original 112.5% rule is retained as a diagnostic comparator. The relaxed 110% rule from #588 is excluded from selection.

## Historical decision

The runner produces:

- exact primary and stress daily ledgers;
- evaluation by frozen period;
- period contribution concentration;
- expansion-episode attribution;
- candidate state and budget ledger;
- a deterministic `decision.json`.

A candidate must pass every gate in the machine-readable contract. Historical success can only select one append-only prospective challenger. `promotion_authorized` remains false in every historical output.

## Formal promotion

A separately frozen challenger must then accumulate at least 12 months, 10 completed episodes and 126 financed sessions in genuinely forward data, while remaining positive under primary and stress costs and within episode and quarterly concentration limits.

Passing those gates authorizes a reviewed promotion decision; it does not automatically change the model registry.
