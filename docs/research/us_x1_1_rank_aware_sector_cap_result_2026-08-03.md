# US x1.1 rank-aware sector-cap result

**Date:** 2026-08-03  
**Experiment:** 012  
**Issue / PR:** #432 / #433  
**Workflow / artifact:** `30779386691` / `8843152145`  
**Artifact digest:** `sha256:9ced02f9329d7c955a6166ee0303bf523c0a7e030fb9b7d8ea8a7f0a2bb4e3fc`  
**Provider:** `5c09d0fbc8348e182ce8829c44d43d96aaae4ed8a2c2ba8901e69034a7c6aa95`  
**Decision:** `rank_aware_sector_cap_supported_for_shadow`

## Executive conclusion

The rank-aware sector cap passed every pre-registered development-evidence gate.
It may advance as a frozen shadow portfolio-control contract, but it does not
replace US x1.1, create US x1.2 or establish trade readiness.

The challenger retains the fixed US87 pool, formal US x1.1 scores, Top-15 equal
weights and ten-session rebalance contract. It changes only selection: scan the
complete score ranking and admit no more than four names from one governed
sector, filling exactly 15 positions. The resulting maximum sector weight is
`4/15 = 26.67%`.

On the deterministic revision provider, the challenger improved four-window
20 bps compounded relative excess from **+113.35% to +120.85%**, improved the
worst window drawdown from **-33.88% to -29.36%**, reduced aggregate turnover by
**12.21%**, retained positive simple excess in all four development windows and
remained positive at 60 bps.

The result nevertheless has a material limitation. Mean Top-15 overlap was only
61.81%, with an average 5.73 replacements per rebalance and a maximum selected
rank of 46. In 2025H2 the constraint removed several exceptionally strong
Technology names and reduced return by 35.22 percentage points while worsening
drawdown by 6.69 percentage points. The control is therefore economically
material, not a cosmetic concentration limit, and requires unchanged shadow
validation on future evidence.

## Frozen contract

The experiment kept unchanged:

- `us_selected_equities_v2`, exactly 87 candidates;
- governed sector classification from PR #430;
- Experiment 007 deterministic US x1.1 score ledgers;
- model features, label, XGBoost parameters and training windows;
- ten-session forward-return, holding and rebalance definitions;
- Top-15 equal weights;
- QQQ benchmark;
- 20/40/60 bps cost stress;
- deterministic provider identity.

The challenger alone applied:

1. score descending, instrument ascending for ties;
2. scan the complete economically eligible cross-section;
3. select a name only while its sector has fewer than four selected names;
4. stop after exactly 15 names;
5. assign `1/15` to every selected name;
6. fail closed if 15 names cannot be filled;
7. never redistribute weight across the full pool.

2026H1 was not used for selection, tuning or acceptance.

## Aggregate economics

Compounded relative excess uses the canonical geometric definition:

```text
strategy_nav / QQQ_nav - 1
```

Window-level simple excess remains strategy total return minus QQQ total return.

| Contract | Cost | Strategy return | Relative excess | Worst window DD | Turnover | Strongest positive-window share |
|---|---:|---:|---:|---:|---:|---:|
| US x1.1 baseline | 20 bps | +231.11% | +113.35% | -33.88% | 25.67 | 48.72% |
| US x1.1 baseline | 40 bps | +214.99% | +102.96% | -34.13% | 25.67 | 50.51% |
| US x1.1 baseline | 60 bps | +199.64% | +93.07% | -34.38% | 25.67 | 52.55% |
| Rank-aware sector cap | 20 bps | **+242.76%** | **+120.85%** | **-29.36%** | **22.53** | **32.91%** |
| Rank-aware sector cap | 40 bps | +227.98% | +111.33% | -29.65% | 22.53 | 33.19% |
| Rank-aware sector cap | 60 bps | +213.82% | +102.21% | -29.93% | 22.53 | 33.52% |

At 20 bps:

- relative-excess retention versus baseline: **106.62%**;
- worst-drawdown improvement: **+4.52 percentage points**;
- turnover ratio: **87.79%** of baseline;
- all four windows retained positive simple excess;
- strongest positive-window share fell below the 55% gate.

## Window results at 20 bps

| Window | Baseline return | Sector-cap return | Baseline simple excess | Sector-cap simple excess | Baseline DD | Sector-cap DD |
|---|---:|---:|---:|---:|---:|---:|
| 2024H1 | +31.17% | **+47.16%** | +11.75% | **+27.74%** | -6.87% | **-4.53%** |
| 2024H2 | **+39.21%** | +33.13% | **+32.37%** | +26.28% | -13.97% | **-11.37%** |
| 2025H1 | +13.24% | **+40.07%** | +5.54% | **+32.37%** | -33.88% | **-29.36%** |
| 2025H2 | **+60.13%** | +24.91% | **+47.19%** | +11.97% | **-19.38%** | -26.07% |

The improvement is not uniformly positive. The candidate adds substantial value
in 2024H1 and 2025H1, gives back some return in 2024H2, and materially
underperforms in 2025H2.

## Concentration and portfolio displacement

The baseline reached maximum sector weights between 80.00% and 93.33% across
the four windows. The challenger held the maximum at 26.67% in every rebalance.
Mean sector HHI changed as follows:

| Window | Baseline mean HHI | Sector-cap mean HHI |
|---|---:|---:|
| 2024H1 | 0.4652 | 0.2015 |
| 2024H2 | 0.5096 | 0.1963 |
| 2025H1 | 0.4511 | 0.1956 |
| 2025H2 | 0.4830 | 0.2000 |

The portfolio displacement is material:

- mean Top-15 overlap: **61.81%**;
- minimum Top-15 overlap: **33.33%**;
- average replacements per rebalance: **5.73**;
- mean replacement rank displacement: **14.52 ranks**;
- maximum replacement rank displacement: **31 ranks**;
- maximum selected rank: **46**;
- mean selected rank: **13.55**.

The risk benefit therefore comes with a meaningful reduction in pure model-rank
concentration. Shadow monitoring must track both risk reduction and the
opportunity cost of skipping highly ranked names.

## 2025H1 mechanism

The formal baseline peak-to-trough interval ran from 2025-02-03 to 2025-04-01.
The largest single shock occurred on 2025-02-18.

| Phase | Baseline return | Sector-cap return | Improvement |
|---|---:|---:|---:|
| Initial shock | -21.07% | -19.26% | +1.81 pp |
| Continuation | -16.23% | -12.50% | +3.72 pp |

The control helped both phases but provided more benefit during continuation.
It did not eliminate the initial broad high-beta/high-volatility shock found in
Experiment 011.

QQQ-down net contribution improved from -35.57% to -26.41% in 2025H1, while
QQQ-up contribution improved from +54.26% to +66.64%. The benefit was therefore
not produced solely by avoiding QQQ-down periods.

## 2025H2 degradation

The 2025H2 result is the main reason the challenger cannot be promoted from
consumed development evidence:

- total-return and simple-excess change versus baseline: **-35.22 pp**;
- maximum-drawdown change: **-6.69 pp**;
- QQQ-up net contribution fell from +78.23% to +54.81%;
- QQQ-down net contribution worsened from -25.13% to -27.33%.

The largest negative replacement pairs show the mechanism. The cap removed
strong, highly ranked Technology winners and admitted lower-ranked names from
other sectors, including:

- ALAB replaced by MELI on 2025-07-16;
- IREN replaced by BE on 2025-09-11;
- SNDK replaced by HIMS on 2025-10-23;
- SNDK replaced by AXON on 2025-09-25;
- AEHR replaced by CRCL on 2025-07-30;
- LITE replaced by TEM on 2025-11-20;
- MU replaced by TYGO on 2025-10-23.

The worst relative period was 2025-10-23, when baseline returned +1.89% and the
sector-cap portfolio returned -5.55%, a difference of -7.44 percentage points.

This is not evidence that the governed sector classification is wrong. It is the
expected cost of a hard concentration ceiling when one sector contains many of
the period's strongest model-ranked winners.

## Sensitivity interpretation

Leave-one-sector and leave-one-replacement evidence does not support a hidden
single-name explanation for the aggregate result. Individual replacements can
be important in a window, but the candidate's behavior arises from repeated
rank displacement across many rebalances.

Examples of harmful 2025H2 incoming names include CRCL, HIMS, AXON and MELI;
removing CRCL from the replacement path improved 2025H2 return by 8.37
percentage points. This remains a diagnostic, not permission to create manual
exceptions. Any name-specific exception or sector-cap change would invalidate
the frozen candidate and restart the future challenge clock.

## Determinism and evidence identity

The entire evidence tree was materialized twice after the canonical
relative-excess correction.

- run-A file count: 25;
- run-B file count: 25;
- run-A tree SHA-256:
  `a9395adbbd5762cac1638588b22ae0b7821bd390c0b0861afb98985b6d7a587b`;
- run-B tree SHA-256:
  `a9395adbbd5762cac1638588b22ae0b7821bd390c0b0861afb98985b6d7a587b`.

All four baseline windows reproduced Experiment 007 within `1e-6`. Complete
selection, replacement, contribution, sector, style, regime and sensitivity
ledgers are retained in the workflow artifact.

## Gate decision

All pre-registered gates passed:

- [x] all four development windows have positive simple excess;
- [x] 60 bps compounded relative excess remains positive;
- [x] 20 bps relative excess retains at least 90% of baseline;
- [x] worst window drawdown improves by at least four percentage points;
- [x] turnover remains within 115% of baseline;
- [x] strongest positive-window share remains below 55%;
- [x] repeated materializations match exactly.

Decision:

```text
rank_aware_sector_cap_supported_for_shadow
```

## Governance outcome and next step

- US x1.1 remains the active research baseline.
- The sector-cap contract is a separate portfolio-control challenger.
- It is not US x1.2.
- It is not trade ready.
- 2024H1–2025H2 and 2026H1 are consumed evidence.
- The exact four-name sector ceiling, classification identity, Top-15 rule and
  rebalance contract must be frozen in shadow mode.
- The next complete untouched six-month window is reserved for final challenge
  evaluation.
- Any threshold, sector classification, exception or portfolio-rule change
  restarts the challenge clock.
