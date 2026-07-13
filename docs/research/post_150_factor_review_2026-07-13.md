# Post-#150 CN/US canonical factor review

**Review date:** 2026-07-13  
**Evidence:** `docs/evidence/post-150-current-2026-07-13/`  
**Scope:** diagnostic review only; no factor-library, model, promotion, or trading change

## 1. Decision boundary

This review uses the current-contract single-factor diagnostics generated after PR #150. Both markets passed real-provider acceptance with one survivorship-bias warning and remain:

```text
diagnostic_only=true
promotion_eligible=false
promotion_evaluated=false
trade_ready=false
```

The `recommended_orientation` fields in the diagnostic report are retrospective descriptions of the full OOS sample. They must not be copied directly into a new model as though they were known ex ante. A follow-up experiment must either:

1. predeclare an economically justified sign before observing each OOS window; or
2. estimate orientation only from the corresponding training period under a nested, spec-bound procedure.

## 2. Evidence quality and limits

- CN: 23 canonical expressions, 47 factor IDs, 46 sampled rebalance dates.
- US: 9 canonical expressions, 24 factor IDs, 48 sampled rebalance dates.
- Included OOS windows: `2024H1`, `2024H2`, `2025H1`, and `2025H2`.
- `2026H1` is explicitly partial and excluded under `complete_windows_only`.
- Both universes are static current-membership universes, so the acceptance report correctly retains a survivorship-bias warning.
- Aggregate ICIR is not sufficient: window sign, Top–Bottom spread, economic duplication, and concentration in one period are considered jointly.

## 3. CN review

### 3.1 Key findings

The strongest CN results do not represent three independent signals.

`$close/Ref($close,5)-1` and `Ref($close,5)/$close-1` are strictly monotonic inverse transformations over valid positive prices. They therefore produce opposite but rank-equivalent cross-sectional ordering. Treating both as separate candidates would double-count the same five-day reversal information.

The short-horizon volatility/range expressions also form one economic cluster:

- `Std($close/Ref($close,1)-1,5)`;
- `($high/$low-1)`;
- `($high-$low)/($close+1e-12)`.

Their aggregate oriented ICIR is relatively high, but their Top–Bottom spread changes regime: the low-volatility orientation works in 2024 and reverses in 2025. They are therefore investigation candidates, not stable production candidates.

### 3.2 Classification

| Decision | Canonical representative | Evidence | Review conclusion |
|---|---|---|---|
| **Retain for controlled research** | `Ref($close,5)/$close-1` | oriented ICIR 0.2100; positive oriented window ratio 0.75; positive spread after the reviewed reversal sign in 3 of 4 windows | Keep one semantically explicit 5D reversal representative. Do not also include the inverse 5D return expression in the same grid. |
| **Retain as weak stability control** | `$close/Ref($close,20)-1` with reversal interpretation | oriented ICIR 0.0973; IC sign supports reversal in all 4 windows, but aggregate spread is only 0.0009 and changes sign by year | Useful as a horizon-control factor, not as a leading candidate. |
| **Isolate / investigate** | `Std($close/Ref($close,1)-1,5)` | oriented ICIR 0.2152; positive oriented windows 0.75; oriented spread is positive in 2024 but negative in 2025 | Test as a regime-sensitive low-volatility hypothesis. Do not combine with high/low range proxies before redundancy testing. |
| **Isolate / investigate** | `$volume/Mean($volume,5)-1` | oriented ICIR 0.1269; 3 of 4 IC windows positive under the reported sign; aggregate spread only 0.0010 | Evidence is too weak for promotion but sufficient for a standalone liquidity/attention diagnostic. |
| **Remove from the next candidate grid** | 5D return expression when 5D inverse-return reversal is present | rank-equivalent economic duplicate | Preserve provenance in the library, but do not count or test it as an independent signal. |
| **Remove from the next candidate grid** | high/low ratio and range/close when 5D volatility is present | same short-range/volatility cluster and nearly identical window behavior | Select one representative until cross-factor rank correlation proves incremental information. |
| **Remove from the next candidate grid** | 5D/10D/20D risk-adjusted returns | ICIR 0.066–0.118; weak or sign-inconsistent spread; no improvement over simpler representatives | Complexity is not justified by the current evidence. |
| **Remove from the next candidate grid** | 10D/20D volume shocks, MA deviations, price-volume interactions, 3D return/reversal pair, plain 10D momentum | low aggregate signal, window instability, or algebraic duplication | Do not spend the next experiment budget on these expressions. |

### 3.3 CN shortlist

The next CN experiment should contain no more than four canonical hypotheses:

1. 5D reversal — primary candidate;
2. 20D reversal — weak horizon control;
3. 5D realized volatility — isolated regime candidate;
4. 5D relative volume — isolated liquidity candidate.

This is a research shortlist, not a factor-library deletion decision.

## 4. US review

### 4.1 Key findings

The highest aggregate US ICIR belongs to 20D return divided by 20D volatility, but its IC direction is positive in only 2 of 4 windows and its spread is dominated by `2025H2`. Plain 20D momentum has almost the same ICIR, a better 3-of-4 window sign pattern, and simpler economic interpretation. Plain 20D momentum is therefore the preferred primary representative.

US realized volatility is the most stable family in this run:

- 20D volatility has positive IC and positive Top–Bottom spread in all four windows;
- 10D volatility behaves similarly and is likely redundant at this stage.

The positive volatility sign is economically nonstandard for a generic low-volatility hypothesis. It must be treated as a market-regime or growth-beta diagnostic until sector, size, beta, and concentration effects are examined.

### 4.2 Classification

| Decision | Canonical representative | Evidence | Review conclusion |
|---|---|---|---|
| **Retain for controlled research** | `$close/Ref($close,20)-1` | oriented ICIR 0.2842; positive window ratio 0.75; aggregate spread 0.0111 | Preferred primary momentum candidate. The spread is still concentrated in `2025H2`, so it is not promotion-ready. |
| **Retain for controlled research** | `Std($close/Ref($close,1)-1,20)` | oriented ICIR 0.1682; positive IC and spread in all 4 windows; spread 0.0344 | Best stability candidate, but the positive sign requires beta/sector/regime attribution before interpretation. |
| **Retain as secondary horizon control** | `$close/Ref($close,5)-1` | oriented ICIR 0.1505; positive window ratio 0.75; one near-zero IC window | Useful to test whether momentum strength is genuinely medium-term rather than a broad trend effect. |
| **Isolate / challenge** | 20D return / 20D volatility | oriented ICIR 0.2869; positive window ratio only 0.50; spread heavily concentrated in `2025H2` | Compare directly with plain 20D momentum. Retain only if it adds independent rank information or downside robustness. |
| **Remove from the next candidate grid** | 10D volatility when 20D volatility is present | similar behavior and lower ICIR than 20D volatility | Use only as a robustness sensitivity, not a simultaneous candidate. |
| **Remove from the next candidate grid** | 10D momentum and 10D risk-controlled momentum | weaker and less stable than the 20D and 5D representatives | No incremental case in the current evidence. |
| **Remove from the next candidate grid** | 20D relative volume and 10D volume momentum | ICIR 0.0367 and 0.0114; poor window consistency | Insufficient evidence for another experiment cycle. |

### 4.3 US shortlist

The next US experiment should use:

1. 20D momentum — primary candidate;
2. 20D realized volatility — stability/regime candidate;
3. 5D momentum — secondary horizon control;
4. 20D risk-controlled momentum — isolated challenger, not an equal-weight duplicate.

## 5. Required next experiment

The next experiment must preserve the current universe, benchmark, dates, 10-session horizon/cadence, Top/Bottom N, return semantics, acceptance gates, and promotion rules.

Before any factor combination or model fitting, it must produce:

- train-only or economically predeclared orientation evidence;
- pairwise cross-sectional rank-correlation and signal-overlap matrices;
- per-window Rank IC, ICIR, Top–Bottom spread, coverage, and turnover;
- contribution concentration by window, with an explicit flag when one window supplies more than 60% of aggregate spread;
- sector, size, market-beta, and liquidity attribution for retained factors;
- transaction-cost sensitivity at the fixed 10D cadence;
- an explicit comparison against the simpler representative whenever a normalized or risk-adjusted variant is tested.

A candidate may advance from this review only when:

1. it is not an algebraic or rank-equivalent duplicate;
2. its sign is determined without OOS look-ahead;
3. at least 3 of 4 complete windows support the declared direction;
4. IC and Top–Bottom spread have economically coherent direction;
5. results are not dominated by one window or one broad risk exposure;
6. a separate spec-bound run generates a valid execution identity and PromotionDecision.

## 6. Final decision

### Retain for research

- CN: 5D reversal; 20D reversal as weak control.
- US: 20D momentum; 20D realized volatility; 5D momentum as secondary control.

### Isolate / investigate

- CN: 5D realized volatility; 5D relative volume.
- US: 20D risk-controlled momentum.

### Remove from the next candidate grid

- algebraic inverse duplicates;
- redundant volatility/range horizons;
- weak volume and price-volume interactions;
- weaker 10D momentum variants;
- factors with near-zero aggregate signal or persistent IC/spread inconsistency.

No factor is approved for production, promotion, or trading by this review.

Closes #155 when merged.
