# Small-Pool Sector Rotation Charter

Date: 2026-07-30  
Design issue: #205

## Decision

Alpha Engine's active objective is no longer a universal cross-sectional stock model or a permanently fixed 19-name watchlist. The target is a **user-curated, versioned small stock pool** that can rotate among a small number of economic baskets and then apply transparent per-security timing rules.

The existing `WATCH / ENTER / HOLD / REDUCE / EXIT` engine remains part of the system. It becomes the stock-level execution and risk-control layer beneath basket selection.

## Three-layer architecture

1. **Market regime** — QQQ determines whether broad risk exposure is permitted.
2. **Basket rotation** — eligible baskets are compared every 10 QQQ trading sessions using one fixed, equal-weight score.
3. **Security timing** — selected baskets may hold only securities with an eligible individual state; daily reduction and exit remain possible between rotation dates.

The strategy may hold cash. It does not need to select a fixed number of baskets or securities when conditions are weak.

## Pool version 1

The first version contains 23 candidate securities and two reference instruments.

| Basket | Symbols |
| --- | --- |
| Semiconductor compute | ALAB, TSM, INTC, AMD, SNDK |
| Optical and networking | CRDO, POET, AAOI, LITE, NOK |
| AI infrastructure and power | VRT, NBIS, IREN, TIGO |
| Mega-cap platforms | AAPL, MSFT, ORCL |
| China consumer internet | PDD, JD |
| Defensive consumer | KO, WMT |
| Consumer growth | TSLA, HIMS |

QQQ is the market-regime reference and benchmark. SOX, sourced through provider symbol `^SOX`, is an informational semiconductor-cycle reference. Neither is a trading candidate.

The taxonomy is a research classification. It identifies the primary exposure used by this experiment and does not claim that each company has only one economic driver.

## Why the pool is versioned rather than permanently fixed

The user may add companies as the investable opportunity set evolves. That flexibility must not become retrospective selection.

Every run therefore binds to an immutable pool version and membership hash. Adding, removing, reclassifying, or changing a ticker alias creates a new pool version before any performance is inspected. Weak names and failed baskets cannot be removed from an already observed version.

## Basket score

Every 10 QQQ sessions, each eligible basket receives four equally weighted cross-basket percentile ranks:

- median 63-session constituent momentum relative to QQQ;
- median 20-session constituent momentum;
- breadth, measured as the fraction of constituents above SMA50;
- median drawdown from the constituent's 63-session high, where a smaller drawdown ranks higher.

A basket must have at least two eligible constituents, at least 50% constituent coverage, at least 50% breadth above SMA50, and positive median 63-session relative momentum. The combined score must be at or above the 50th percentile. At most two baskets may be selected.

No coefficients are fitted and no score weights are searched.

## Security selection and exposure

Within a selected basket, at most two names are selected. The order is:

1. individual state priority: `ENTER`, then `HOLD`, then `REDUCE`;
2. 63-session relative momentum versus QQQ.

`ENTER` and `HOLD` receive a full slot. `REDUCE` receives half a slot. `WATCH` and `EXIT` receive zero. Selected baskets are equally weighted, and selected securities are equally weighted within each basket.

Basket membership changes only at the 10-session rotation schedule. Individual `REDUCE` and `EXIT` decisions may occur daily. QQQ risk-off moves target gross exposure to zero.

## Evidence boundary

- 2021-01-01 through 2025-12-31: development observed.
- 2026-01-01 through 2026-06-30: falsification only.
- 2026-07-01 through 2026-12-31: independently reserved until the required forward horizon is complete.

## Required evidence

The system must report basket scores, selected baskets, selected and rejected securities, portfolio state, cash utilization, turnover, drawdown, QQQ-relative return, equal-weight-pool-relative return, contribution concentration, QQQ-regime behavior, SOX-context behavior, and short-history treatment.

## Prohibited work

- fitting score coefficients;
- searching score weights, rotation frequency, selection counts, or basket definitions;
- changing membership after observing results;
- per-basket or per-symbol rule variants;
- opening 2026H2 performance;
- broker integration;
- frontend expansion before real evidence.

## Next steps

Issue #206 implements the deterministic rotation engine. Issue #207 validates it on observed evidence. Issue #208 creates manual rotation trade tickets only after the research gates are satisfied.
