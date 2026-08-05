# BYD v1.2 extreme-defense research

Issue: #560  
Status: completed historical experiment; not supported  
Decision: retain **BYD v1.1**

## Model identity

The accepted formal model is now presented to users as **BYD v1.1**:

- BYD V1.0 supplies the canonical 75% / 100% BYD core timing state;
- BYD v1.1 fills the defensive 25% sleeve with 515180.SH;
- the immutable technical publication ID remains `byd_dividend_sleeve_v1_0` so the already-sealed package and historical SHA are not rewritten.

## Frozen hypothesis

This experiment tested whether BYD v1.1 should reduce BYD below its existing 75% floor during rare extreme deterioration.

The primary state required all of the following while the base model was already at 75% BYD:

- bear market state;
- high volatility state;
- 252-session drawdown at or below -20%;
- negative 20-session momentum;
- negative 60-session momentum.

The primary candidate used 50% BYD + 50% 515180 during the state. A 62.5%/37.5% robustness variant and a 50% BYD /25% ETF /25% cash diagnostic were frozen before the result.

## Full-overlap result, 20 bps

| Model | CAGR | Total return | Max drawdown | Calmar | Round trips/year |
|---|---:|---:|---:|---:|---:|
| **BYD v1.1** | **35.07%** | **581.81%** | **-48.74%** | **0.7196** | **1.06** |
| Extreme defense 50/50 | 34.34% | 558.50% | -48.74% | 0.7045 | 1.61 |
| Extreme defense 62.5/37.5 | 34.71% | 570.13% | -48.74% | 0.7121 | 1.33 |
| Extreme defense with cash | 33.70% | 538.69% | -48.74% | 0.6914 | 1.61 |

The primary candidate:

- reduced CAGR by approximately 0.73 percentage points;
- reduced total return by approximately 23.31 percentage points;
- did not improve maximum drawdown at all;
- reduced Calmar from 0.7196 to 0.7045;
- reduced 40 bps total return from 563.66% to 532.04%;
- failed six of seven frozen gates.

## Temporal evidence

Relative terminal wealth versus BYD v1.1 was:

- development: -0.68%;
- fixed validation: 0.00%, because the state never activated;
- 2025+: -2.76%.

The robustness and cash variants were also non-positive in every frozen period.

## Episode mechanism

The state produced seven completed episodes and only twenty active sessions.

Two short 2022 episodes had small positive relative contributions. Five episodes were negative, including all four episodes in June–July 2026. The largest relative loss occurred from 2026-07-03 through 2026-07-10, when the 50/50 candidate underperformed BYD v1.1 by approximately 1.41% in terminal wealth.

The key finding is that deep drawdown, high volatility and negative momentum identify conditions that look dangerous, but for BYD they frequently occur close to high-beta rebound intervals. Cutting the permanent 75% BYD core at those points removes the very exposure that drives subsequent recovery.

## Governed conclusion

`retain_byd_v1_1`

- do not reduce the normal 75% BYD floor using this extreme-state family;
- do not search drawdown thresholds, momentum windows, 50%/62.5% intermediate weights or exit repairs on the observed episodes;
- retain the 515180 sleeve unchanged;
- keep BYD v1.1 as the formal baseline;
- `research_only=true`;
- `trade_ready=false`;
- fresh historical holdout: false.

## Next bounded hypothesis

The remaining return-maximization question is no longer additional defense. The next distinct mechanism is a **strictly capped trend-expansion budget above 100% BYD** during strong-trend, low-volatility conditions, with explicit financing cost, turnover and drawdown gates.

That successor must be frozen as a separate experiment. It may not reuse the extreme-defense result to tune thresholds, and it cannot become a formal model without realistic financing assumptions and distributed evidence across time.
