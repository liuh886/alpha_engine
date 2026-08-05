# BYD v1.2 capped trend-expansion research

Issue: #560  
Status: completed historical experiment; prospective candidate only  
Formal decision: retain **BYD v1.1**

## Research question

After rejecting additional defense below the 75% BYD floor, this experiment tested a distinct return-expansion mechanism: whether BYD v1.1 should use a small financed BYD allocation above 100% during strong-trend, low-volatility conditions.

The 515180.SH defensive sleeve and the underlying BYD V1.0 state machine were not changed.

## Frozen state and costs

Entry required all:

- BYD v1.1 base target = 100%;
- market state = bull;
- volatility state = low;
- 20-session momentum > 0;
- 60-session momentum > 0;
- 252-session drawdown > -10%.

Exit occurred when the base target returned to 75%, market state stopped being bull, volatility became high, or 20-session momentum became non-positive.

Frozen candidates:

- BYD v1.1 baseline;
- 112.5% BYD primary candidate;
- 110% BYD robustness candidate;
- 125% BYD leverage diagnostic.

Primary cost assumptions were 20 bps per absolute weight change and 6% annual financing on negative cash. The stress case used 40 bps and 10% annual financing.

## Full-overlap primary-cost result

| Model | CAGR | Total return | Max drawdown | Calmar | Round trips/year |
|---|---:|---:|---:|---:|---:|
| **BYD v1.1** | **35.07%** | **581.81%** | **-48.74%** | **0.7196** | **1.06** |
| 110% trend expansion | 35.55% | 597.18% | -49.65% | 0.7159 | 1.53 |
| 112.5% trend expansion | 35.66% | 601.00% | -49.88% | 0.7150 | 1.64 |
| 125% diagnostic | 36.23% | 619.96% | -51.00% | 0.7104 | 2.23 |

The 112.5% primary candidate:

- improved CAGR by approximately 0.59 percentage points;
- improved cumulative return by approximately 19.19 percentage points;
- worsened maximum drawdown by approximately 1.14 percentage points;
- reduced Calmar by approximately 0.0046;
- paid approximately 0.26 percentage points of cumulative modeled financing cost;
- remained above BYD v1.1 under the 40 bps / 10% financing stress case: 571.02% versus 563.66% total return.

## Temporal evidence

Relative terminal wealth versus BYD v1.1 was positive in all three frozen periods:

- development: +0.40%;
- fixed validation: +2.23%;
- 2025+: +0.16%.

However, 79.75% of positive historical contribution came from the fixed-validation period. The candidate therefore failed the pre-registered contribution-concentration gate.

## Episode evidence

The state produced:

- 15 completed episodes;
- 86 financed sessions;
- 6 positive episodes and 9 negative episodes.

Important positive episodes included:

- 2020-06-23 through 2020-07-03: +1.89% relative terminal wealth;
- 2020-07-07 through 2020-07-10: +0.98%;
- 2024-09-02 through 2024-09-30: +3.60%.

The largest negative episode was 2024-07-26 through 2024-08-02 at approximately -1.08% relative terminal wealth.

The mechanism is economically plausible: when BYD enters a genuine persistent uptrend, limited additional exposure captures more convex upside even after financing. But the observed result is driven by a small number of powerful episodes, and the 86 financed sessions are below the frozen 126-session sample gate.

## Frozen gate result

The 112.5% candidate passed:

- maximum drawdown worsening <=3 percentage points;
- Calmar decline <=0.02;
- stress total return above baseline;
- no more than one negative frozen period;
- round trips/year <=3;
- at least ten completed episodes;
- 110% robustness candidate improves both primary CAGR and stress total return.

It failed:

- CAGR improvement >=1 percentage point;
- at least 126 financed sessions;
- maximum positive period contribution share <=60%.

Governed decision:

`retain_byd_v1_1`

## Research conclusion

This direction is not rejected in the same way as extreme defense. It produced a small, cost-resilient improvement in every frozen period, but the evidence is too concentrated and too sparse for formal promotion.

Therefore:

- BYD v1.1 remains the formal model;
- the 112.5% version becomes the only eligible prospective trend-expansion candidate;
- the 110% version remains robustness evidence only;
- the 125% version remains diagnostic and cannot replace the primary candidate after seeing the result;
- no leverage-level grid or state-threshold repair is authorized;
- live feasibility must separately verify executable financing terms before any trade-ready consideration;
- `research_only=true`;
- `trade_ready=false`;
- fresh historical holdout: false.

## Next step

Create an append-only prospective ledger for the frozen 112.5% candidate. It must record every signal, pending execution, common-open execution, financing assumption and 5/10/20 common-open outcome without rewriting historical observations.

The candidate should not be reconsidered for formal promotion until it accumulates at least:

- 12 months of forward time;
- 10 completed expansion episodes;
- 126 financed sessions;
- positive net relative terminal wealth under both primary and stress cost assumptions;
- evidence across at least two distinct market states or trend cycles;
- no single prospective episode contributing more than 60% of positive relative wealth.
