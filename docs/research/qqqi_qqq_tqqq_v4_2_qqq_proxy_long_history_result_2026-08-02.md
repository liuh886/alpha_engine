# v4.2 recovery precursor — QQQ proxy long-history result

**Evidence date:** 2026-08-02  
**Actual QQQI sample:** 2024-01-30 through 2026-07-30  
**QQQ proxy sample:** 2020-06-01 through 2026-07-30  
**Proxy observations:** 1,549 adjusted open-to-open returns  
**Official cost:** 10 basis points per turnover unit  
**Status:** research-only; not trade-ready

## Executive decision

1. Replacing QQQI with QQQ expands the precursor sample from 3 to 15 events.
2. The longer sample does **not** support 50% TQQQ as structurally superior to 25% TQQQ.
3. On the QQQ proxy sample, 50% underperforms 25% on full-sample CAGR, early-sample CAGR, Sharpe and maximum drawdown.
4. Only 40% of the 15 marginal 50%-versus-25% events are positive.
5. The three actual post-2024 events remain directionally consistent between QQQI and the QQQ proxy, so the earlier positive result was not an implementation error.
6. The combined evidence indicates strong regime dependence: the 50% precursor worked after 2024 but failed repeatedly during 2020-2023.
7. v4.2 remains unchanged. Neither 25% nor 50% becomes actionable.

The key finding is that the short QQQI history was not merely hiding more positive events. Once the sample is extended with QQQ, many failed recovery episodes appear.

## 1. Proxy definition and boundary

The experiment keeps actual QQQI bars for the native sample. For the long-history sample it creates an in-memory mapping in which:

```text
QQQI adjusted bars = exact copy of QQQ adjusted bars
```

Everything else remains unchanged:

- actual SGOV and TQQQ returns;
- frozen v4.2 states and precursor conditions;
- close-time decisions and next-open execution;
- 10 basis points per turnover unit;
- 25% and 50% precursor dates;
- formal state 2 at 25% QQQ / 75% TQQQ.

The proxy is evidence about recovery timing and leverage sizing. It is not a reconstruction of QQQI option income, distributions, fees, tax character or covered-call path dependence.

## 2. Sample expansion

| Evidence layer | Start | Observations | Precursor events | Precursor sessions |
|---|---|---:|---:|---:|
| Actual QQQI | 2024-01-30 | 627 | 3 | 6 |
| QQQ proxy | 2020-06-01 | 1,549 | 15 | 32 |

The event-count gate is therefore no longer the binding limitation in the proxy experiment.

## 3. Long-sample headline results

| Strategy | CAGR | Volatility | Sharpe | Sortino | Maximum drawdown | Calmar |
|---|---:|---:|---:|---:|---:|---:|
| QQQ-proxy v4.2 | **36.20%** | 30.34% | 1.171 | 1.695 | -38.92% | 0.930 |
| QQQ-proxy static SGOV | 34.64% | **24.79%** | **1.325** | **1.947** | **-23.65%** | **1.464** |
| QQQ-proxy 25% precursor | 32.94% | 25.19% | 1.257 | 1.827 | -25.62% | 1.286 |
| QQQ-proxy 50% precursor | 31.70% | 25.59% | 1.205 | 1.732 | -26.95% | 1.176 |

Relative to the 25% precursor, the 50% precursor produces:

- CAGR: **-1.24 percentage points**;
- Sharpe: **-0.052**;
- maximum drawdown: **1.33 percentage points deeper**;
- full-sample total return: lower;
- no reduction in the longest unresolved recovery problem.

The long sample also shows that both precursor variants underperform the static SGOV profile. This means the concern is broader than choosing 25% versus 50%: the frozen precursor timing itself generated multiple false recovery releases before 2024.

## 4. Chronological stability

| Segment | 25% precursor CAGR | 50% precursor CAGR | 50% minus 25% |
|---|---:|---:|---:|
| Early: 2020-06-01 to 2024-02-07 | **33.94%** | 31.12% | **-2.82 pp** |
| Late: 2024-02-08 to 2026-07-30 | 31.45% | **32.57%** | **+1.12 pp** |
| Full sample | **32.94%** | 31.70% | **-1.24 pp** |

The sign reversal is economically important. The 50% precursor is not generally superior; it is superior only in the later market segment represented by the short QQQI sample.

## 5. Event-level evidence

The QQQ proxy produces 15 contiguous precursor events. Only 6 are positive for 50% relative to 25%, giving a positive-event rate of **40%**.

Largest negative marginal events include:

| Event | 50% minus 25% |
|---|---:|
| 2020-09-16 | -2.32% |
| 2021-05-10 | -2.09% |
| 2022-04-05 | -1.78% |
| 2021-03-18 | -0.89% |
| 2023-03-03 to 2023-03-09 | -0.58% |

The negative events are consistent with failed or incomplete recoveries: medium repair and volatility normalization were temporarily observable, but the additional TQQQ exposure was introduced before the market path became durable.

Positive post-2024 proxy events are:

| Event | QQQ proxy 50% minus 25% |
|---|---:|
| 2024-08-16 to 2024-08-21 | +1.19% |
| 2024-11-07 | +0.36% |
| 2026-04-09 | +0.40% |

## 6. Actual QQQI overlap validation

All three actual QQQI events match the QQQ proxy by date and direction:

| Event | Actual QQQI marginal return | QQQ proxy marginal return | Direction match |
|---|---:|---:|---|
| 2024-08-16 to 2024-08-21 | +1.34% | +1.19% | yes |
| 2024-11-07 | +0.46% | +0.36% | yes |
| 2026-04-09 | +0.45% | +0.40% | yes |

Overlap sign concordance is **100%**. The post-2024 result is therefore robust to substituting QQQ for QQQI within the same dates. The failure appears when earlier market regimes are added.

## 7. Gate result

The long-history structural-support gate passes:

- minimum event count;
- minimum additional-event count;
- full overlap matching;
- overlap sign concordance;
- earlier proxy sample start;
- event concentration limit;
- late-sample improvement.

It fails:

- full-sample CAGR improvement versus 25%;
- early-sample CAGR improvement versus 25%;
- minimum marginal-event positive rate;
- Sharpe requirement in the inherited 50% gate;
- major-trough protection requirements in the inherited 50% gate;
- unresolved-major-episode requirement.

**Decision:** `qqq_proxy_does_not_support_structural_50_percent_superiority`.

## 8. Research interpretation

The evidence now supports a narrower conclusion:

> A 50% TQQQ precursor captured the three observed post-2024 recoveries better than 25%, but it was too aggressive across the broader 2020-2023 recovery set.

This distinction matters. The post-2024 result may reflect a specific market regime rather than a generally reliable transition rule. Increasing event count does not validate the 50% hypothesis; it reveals its instability.

## 9. Current governance decision

- retain v4.2 unchanged as the only actionable baseline and Telegram source;
- retain static QQQI/SGOV as the descriptive drawdown-first profile;
- remove 50% TQQQ's status as the preferred deferred shadow hypothesis;
- retain 25% and 50% only as frozen research comparators;
- continue non-actionable prospective recording in actual QQQI data;
- do not search intermediate weights or new thresholds on the same sample.

The next admissible research is a failure taxonomy of the 15 proxy events using already-frozen observable features. Its purpose is to determine whether failed recoveries are distinguishable ex ante, not to optimize a new threshold retrospectively.

## 10. Evidence

- workflow: `QQQI v4.2 QQQ Proxy Long History`;
- workflow run: `30738861599`;
- artifact ID: `8830582711`;
- artifact digest: `sha256:5a69cb3a3bb8dff9359cbcad313e9ec1b6f1fc9a56d47ef35af1471e3105c3ca`;
- notebook: `notebooks/24_qqqi_qqq_tqqq_v4_2_qqq_proxy_long_history.ipynb`.
