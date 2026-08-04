# BYD SMA25/70 breakout ATR claim verification

## Conclusion

The supplied 0%/100% SMA25/70, 55-session breakout and 3.2 ATR trailing-stop rule does **not** outperform BYD buy-and-hold or canonical BYD V1.0 on the immutable canonical dataset through 2026-08-03.

The governed conclusion is:

`improved_but_not_outperforming`

This means the core/tactical modifications materially improve the original rule, but none of the frozen candidates satisfies the pre-registered outperformance contract in Issue #521.

## Immutable data identity

- snapshot: `data/research/byd_canonical_v1_snapshot.tar.xz`
- snapshot SHA-256: `2e56595d3363b201469f6eefe5dd6390ba156da6fb7ea32a8348d25f06bac179`
- adjusted OHLCV SHA-256: `0cde8d3f1b6a94406532c6e8e04fabdc20d7830d0a58034aa489e87f94b77960`
- manifest SHA-256: `06202b594b036b0c815e4ffb46e9f3d14ba647d699aad0fd927f1665142a363e`
- cutoff: `2026-08-03`

No provider refetch, provider substitution, cross-provider stitching or quarantined-open repair was used.

## Frozen interpretation of the claim

- `SMA25` and `SMA70`: simple moving averages of adjusted close;
- medium-term bull state: `SMA25 > SMA70 and close > SMA70`;
- breakout: close above the maximum of the previous 55 sessions, excluding the current close;
- ATR: 14-session Wilder ATR;
- trailing stop: highest close since entry minus `3.2 × ATR14`;
- exit: trailing-stop breach or `SMA25 < SMA70 and close < SMA70`;
- formal execution: signal at close, execution at the next independently confirmed eligible open;
- cost: 20 bps per unit position change, with 40 bps stress.

A same-close implementation was retained only as a claimant diagnostic and was not eligible for promotion.

## Original claimant result

### Same-close diagnostic

- total return: `224.92%`
- CAGR: `8.76%`
- maximum drawdown: `-50.00%`
- Calmar: `0.1752`
- exposure: `47.47%`
- round trips/year: `4.03`

### Governed next-open version

- total return: `224.09%`
- CAGR: `8.74%`
- maximum drawdown: `-50.95%`
- Calmar: `0.1715`
- exposure: `47.44%`
- round trips/year: `4.03`

The small gap between the diagnostic and next-open implementation shows that execution timing is not the main reason for failure. The larger problem is that the rule stays out of BYD for too much of its long-run positive drift while still suffering substantial drawdowns and frequent re-entry.

## Frozen improvement family

| Candidate | Core/full exposure | ATR | Exit confirmation | Full CAGR | Full MDD | Full Calmar |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Original | 0% / 100% | 3.2 | 1 close | 8.74% | -50.95% | 0.1715 |
| Core 50 | 50% / 100% | 3.2 | 1 close | 15.62% | **-44.01%** | 0.3548 |
| Core 75 | 75% / 100% | 3.2 | 1 close | **18.16%** | -49.54% | **0.3665** |
| Core 75, wider stop | 75% / 100% | 3.6 | 1 close | 18.02% | -50.10% | 0.3596 |
| Core 75, confirmed exit | 75% / 100% | 3.2 | 2 closes | 17.80% | -49.74% | 0.3578 |
| Canonical V1.0 | 75% / 100% | — | hysteresis | 19.58% | -53.69% | 0.3647 |
| Buy-and-hold | 100% | — | — | 20.04% | -56.22% | 0.3564 |

All five candidates failed the development-selection CAGR gate. Therefore `claimant_core75_atr36` is retained only as the highest-development-Calmar diagnostic, not as an eligible promoted model.

## Validation evidence

### Fixed 2023–2024

The development-ranked diagnostic (`core75_atr36`) returned `9.59%`, versus `12.05%` for V1.0 and `12.22%` for buy-and-hold. Its maximum drawdown improved to `-40.35%`.

The non-selected `core75_atr32` candidate returned `12.55%` with a `-39.80%` drawdown and therefore showed the best validation balance in the frozen family. Because that fact was observed after the selection contract was fixed, it cannot be retroactively promoted or used to change the selection rule.

### Retrospective 2025–2026-08-03

- development-ranked diagnostic: `+2.50%`;
- `core75_atr32`: `+4.86%`;
- canonical V1.0: `+6.83%`;
- buy-and-hold: `+3.40%`.

The ATR family did not maintain an advantage over V1.0 in the recent window.

## Why the original claim fails

1. The 0%/100% rule gives up too much long-term BYD exposure: average exposure is only about 47%.
2. ATR exits are followed by fast trend-based re-entry, producing approximately four round trips per year in the original version.
3. The rule reduces some drawdowns but not enough to compensate for lost upside.
4. Adding a permanent core position fixes much of the return loss, but the resulting strategy converges toward—rather than exceeds—the canonical V1.0 architecture.
5. The improvement relative to V1.0 is negative in development, fixed validation and retrospective 2025+, so there is no cross-period excess-return evidence.

## Research boundary

The evidence does support one structural lesson: the SMA/ATR rule is more useful as a **tactical sleeve around a permanent BYD core** than as an all-in/all-out timing system. It does not justify replacing canonical V1.0.

No additional ATR multiplier, moving-average window, breakout window or exit confirmation may be selected from the observed history. A successor would require a separately frozen prospective challenger contract.

- `research_only=true`
- `trade_ready=false`
- fresh holdout: `false`
